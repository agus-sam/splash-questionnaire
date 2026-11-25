"""Orchestration: baseline, heat pump scenario, flexible heating scenario,
three cases (pessimistic / central / optimistic) and a tornado analysis."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from . import climate, hp_rule
from .baseline import (
    Baseline,
    baseline_co2_kg,
    baseline_cost_eur,
    compute_baseline,
    effective_prices,
    vat_factor,
)
from .economics import Co2, Economics, co2, economics, investment_hp
from .flexsplash import FlexOutcome, flex_key, flex_outcomes
from .heatpump import HeatPumpResult, run_heat_pump
from .inputs import Parsed, PoolInputs, from_answers
from .params import CASES, Params
from .profiles import levels_from_model, no_levels
from .splash_engine import DEFAULT_SIZE, DEFAULT_YEAR, SplashInputError, SplashRun, run_splash, static_data
from .subsidy import heat_pump_subsidy

DEFAULT_KEY = flex_key(DEFAULT_YEAR, DEFAULT_SIZE)


@dataclass
class Options:
    hp_capacity_kw: float | None = None
    curtailed_price_net: float | None = None   # net price of curtailed power, EUR/kWh (default from parameters)
    band_k: float | None = None                # allowed temperature rise in K, replaces the questionnaire value
    band_factor: float = 1.0                   # sensitivity multiplier on the band
    zone: str | None = None
    access_share: float = 1.0                  # share of the zone curtailment open to this pool
    calibrate: bool = False                    # optional: scale the SPLASH demand to the reported useful heat


@dataclass
class Context:
    inp: PoolInputs
    parsed: Parsed
    options: Options
    zone: str
    zone_mapped: bool
    weather: climate.Series
    curtail: climate.Series
    q_use_kwh: float
    levels: dict[str, np.ndarray]
    shares: dict[str, float]
    splash: SplashRun | None = None
    splash_error: str | None = None



@dataclass
class HpOutcome:
    res: HeatPumpResult
    subsidy: dict
    investment: float
    om: float
    econ: Economics
    co2: Co2
    price_eff: float = 0.0          # average price of the heat pump electricity (grid and curtailed power), EUR/kWh


@dataclass
class CaseResult:
    case: str
    baseline: Baseline
    base_cost_eur: float
    base_co2_t: float
    fuel_prices: dict[str, float]
    elec_price: float
    hp: HpOutcome | None
    flex: dict[str, FlexOutcome]            # key "<year>_<size in %>", e.g. "2025_200"


@dataclass
class Result:
    status: str                                    # ok | insufficient | open_air
    parsed: Parsed
    context: Context | None = None
    cases: dict[str, CaseResult] = field(default_factory=dict)
    tornado: dict[str, list[dict]] = field(default_factory=dict)
    sensitivity_band2: dict[str, Any] = field(default_factory=dict)
    baseline: Baseline | None = None
    params_version: str = ""
    params_draft: bool = True

    @property
    def central(self) -> CaseResult:
        return self.cases["central"]


# ---------------------------------------------------------------------- build
def _zone_series(zone: str) -> tuple[climate.Series, climate.Series]:
    """Weather (SPLASH TMY of the zone) and the operator curtailment of 2025 as display series."""
    from .splash_engine import curtailment_mw

    w = static_data().weather[zone]["T2m_c"].to_numpy(float)
    c = curtailment_mw(DEFAULT_YEAR)[zone].to_numpy(float)
    return (climate.Series(w, False, f"SPLASH TMY {zone}"), climate.Series(c, False, f"operator curtailment {DEFAULT_YEAR} {zone}"))


def _baseline(ctx_or_none: Context | None, inp: PoolInputs, params: Params) -> Baseline:
    """Baseline on the basis of the SPLASH demand when the model ran, else on reported consumption."""
    q = ctx_or_none.q_use_kwh if ctx_or_none is not None and ctx_or_none.splash is not None else None
    return compute_baseline(inp, params, q)


def _dhw_params(params: Params) -> tuple[float, float, float]:
    """Shower water per visitor (L), shower temperature (degC) and mean stay in the water (h) from the parameter file."""
    return (float(params.central("shower_water_l_per_visitor")), float(params.central("shower_mix_temp_c")),
            float(params.central("stay_in_water_h")))


def build_context(parsed: Parsed, params: Params, options: Options | None = None) -> Context:
    """The questionnaire sets the parameters of the SPLASH model. The model demand is the basis of every scenario."""
    options = options or Options()
    inp = parsed.inputs
    if options.zone:
        zone, mapped = options.zone, True
    else:
        zone, mapped = climate.zone_for_postcode(inp.postcode)
    if zone not in ("T5", "T6"):
        zone, mapped = climate.DEFAULT_ZONE, False
    weather, curtail = _zone_series(zone)
    sp, err = None, None
    reported = compute_baseline(inp, params).reported_q_use_kwh
    pool_heat = reported * float(params.central("reported_heat_pool_share")) if (options.calibrate and reported) else None
    try:
        sp = run_splash(inp, zone, eta=float(params.central("heater_efficiency")),
                        band_factor=options.band_factor, band_k=options.band_k, share=options.access_share,
                        target_heat_kwh=pool_heat, dhw=_dhw_params(params))
    except SplashInputError as exc:
        err = str(exc)
    if sp is not None:
        levels = levels_from_model(sp.demand_basins_kw, sp.demand_hall_kw, sp.demand_dhw_kw)
        q_use = float(sp.model_demand_mwh[DEFAULT_YEAR]) * 1000.0
        tot = {lv: float(levels[lv].sum()) for lv in levels}
        shares = {lv: (v / sum(tot.values()) if sum(tot.values()) > 0 else 0.0) for lv, v in tot.items()}
    else:
        levels, shares = no_levels(len(weather.values)), {}
        q_use = compute_baseline(inp, params).q_use_kwh
    return Context(inp, parsed, options, zone, mapped, weather, curtail, q_use, levels, shares, sp, err)


def curtailed_price_net(options: Options, params: Params) -> float:
    """Net price of curtailed electricity in EUR/kWh. The default is the parameter in EUR/MWh."""
    if options.curtailed_price_net is not None:
        return float(options.curtailed_price_net)
    return float(params.central("curtailed_price_eur_per_mwh")) / 1000.0


# ------------------------------------------------------------------- one case
def case_flex(ctx: Context, params: Params, base: Baseline | None = None) -> dict[str, FlexOutcome]:
    """Economics of the flexible heating scenario for every year and heater size."""
    if ctx.splash is None:
        return {}
    inp = ctx.inp
    base = base or _baseline(ctx, inp, params)
    fuel_prices, p_el = effective_prices(inp, base, params)
    net_c = curtailed_price_net(ctx.options, params)
    p_c = net_c * vat_factor(inp, params)
    return flex_outcomes(ctx.splash, base.e_fuel_kwh, base.q_use_kwh, fuel_prices, p_c, params)


def run_case(ctx: Context, params: Params, with_hp: bool = True) -> CaseResult:
    inp = ctx.inp
    base = _baseline(ctx, inp, params)
    fuel_prices, p_el = effective_prices(inp, base, params)

    hp = None
    if with_hp and inp.pool_type != "open_air":
        rule = ctx.splash is not None and hp_rule.available(ctx.splash)
        if rule:
            hp_res = hp_rule.run_heat_pump_rule(ctx.splash, base.e_fuel_kwh, inp.hp_source, params,
                                                capacity_kw=ctx.options.hp_capacity_kw)
            p_c = curtailed_price_net(ctx.options, params) * vat_factor(inp, params)
            cost_el = hp_res.elec_grid_kwh * p_el + hp_res.elec_curtailed_kwh * p_c
            p_eff = cost_el / hp_res.elec_kwh if hp_res.elec_kwh > 0 else p_el
            share = hp_res.elec_curtailed_kwh / hp_res.elec_kwh if hp_res.elec_kwh > 0 else 0.0
        else:
            hp_res = run_heat_pump(
                ctx.levels, ctx.weather.values, base.q_use_kwh, base.e_fuel_kwh,
                inp.hp_source, params, capacity_kw=ctx.options.hp_capacity_kw,
            )
            p_eff, share = p_el, 0.0
        inv, om = investment_hp(hp_res.capacity_kw_th, params)
        sub = heat_pump_subsidy(inv, inp.hall_area_m2, params)
        econ = economics(inv, sub["grant_eur"], hp_res.fuel_saved_kwh, fuel_prices,
                         hp_res.elec_kwh, p_eff, om, params)
        hp = HpOutcome(hp_res, sub, inv, om, econ, co2(hp_res.fuel_saved_kwh, hp_res.elec_kwh, params, share),
                       price_eff=p_eff)

    return CaseResult(
        case=params.case,
        baseline=base,
        base_cost_eur=baseline_cost_eur(base, fuel_prices),
        base_co2_t=baseline_co2_kg(base, params) / 1000.0,
        fuel_prices=fuel_prices,
        elec_price=p_el,
        hp=hp,
        flex=case_flex(ctx, params, base),
    )


# -------------------------------------------------------------------- tornado
def _tornado(ctx: Context, params: Params, label_lang: str = "en") -> dict:
    cp = params.at_case("central")
    central = run_case(ctx, cp)
    base_hp = central.hp.econ.npv_eur if central.hp else None
    base_fx = {k: v.econ.npv_eur for k, v in central.flex.items()}
    out: dict = {"hp": [], "flex": {k: [] for k in base_fx}}
    for name in cp.uncertain_names():
        lo = run_case(ctx, cp.pinned(name, "pessimistic"))
        hi = run_case(ctx, cp.pinned(name, "optimistic"))
        label = params.entry(name).get(f"label_{label_lang}") or name
        if base_hp is not None:
            a, b = lo.hp.econ.npv_eur, hi.hp.econ.npv_eur
            if abs(a - base_hp) > 1e-6 or abs(b - base_hp) > 1e-6:
                out["hp"].append({"id": name, "label": label, "pessimistic": a, "optimistic": b, "base": base_hp})
        for k, bv in base_fx.items():
            a, b = lo.flex[k].econ.npv_eur, hi.flex[k].econ.npv_eur
            if abs(a - bv) > 1e-6 or abs(b - bv) > 1e-6:
                out["flex"][k].append({"id": name, "label": label, "pessimistic": a, "optimistic": b, "base": bv})
    out["hp"].sort(key=lambda d: abs(d["optimistic"] - d["pessimistic"]), reverse=True)
    for k in out["flex"]:
        out["flex"][k].sort(key=lambda d: abs(d["optimistic"] - d["pessimistic"]), reverse=True)
    return out


# ----------------------------------------------------------------- entry point
def run(
    answers: dict | Parsed,
    params: Params | None = None,
    options: Options | None = None,
    with_tornado: bool = True,
    lang: str = "en",
) -> Result:
    params = params or Params.load()
    parsed = answers if isinstance(answers, Parsed) else from_answers(answers, params)
    inp = parsed.inputs
    res = Result(status="ok", parsed=parsed, params_version=params.version, params_draft=params.is_draft)

    if inp.water_surface_m2() <= 0:
        res.status = "insufficient"
        return res

    if inp.pool_type == "open_air":
        res.status = "open_air"

    ctx = build_context(parsed, params, options)
    res.context = ctx
    res.baseline = _baseline(ctx, inp, params)
    if ctx.splash is None:
        res.status = "insufficient"
        return res
    for case in CASES:
        res.cases[case] = run_case(ctx, params.at_case(case))
    if with_tornado:
        res.tornado = _tornado(ctx, params, lang)

    # sensitivity: the band twice as wide (central case), all years and sizes
    import copy

    opt2 = copy.copy(ctx.options)
    opt2.band_factor = ctx.options.band_factor * 2.0
    ctx2 = copy.copy(ctx)
    ctx2.options = opt2
    ctx2.splash = run_splash(inp, ctx.zone, eta=float(params.central("heater_efficiency")),
                             band_factor=opt2.band_factor, band_k=opt2.band_k, share=opt2.access_share,
                             target_heat_kwh=(ctx.splash.calibration.get("target_mwh") or 0.0) * 1000.0 or None,
                             dhw=_dhw_params(params))
    c2 = case_flex(ctx2, params.at_case("central"))
    res.sensitivity_band2 = {
        k: {"npv_eur": v.econ.npv_eur, "displaced_kwh": v.res.displaced_kwh_th, "absorbed_kwh": v.res.absorbed_kwh_el}
        for k, v in c2.items()
    }
    return res
