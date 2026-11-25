"""Baseline: final energy, useful heat, prices and emissions of today's supply."""
from __future__ import annotations

from dataclasses import dataclass, field

from .inputs import CARRIERS, PoolInputs
from .params import Params

EF_NAME = {
    "gas": "ef_gas",
    "oil": "ef_oil",
    "district_heat": "ef_district_heat",
    "other_heat": "ef_other_heat",
}
PRICE_NAME = {
    "gas": "price_gas",
    "oil": "price_oil",
    "district_heat": "price_district_heat",
    "other_heat": "price_other_heat",
}
ETA_NAME = {
    "gas": "eta_boiler_gas",
    "oil": "eta_boiler_oil",
    "district_heat": "eta_district_heat",
    "other_heat": "eta_other_heat",
}
MAIN_TO_CARRIER = {
    "gas": "gas",
    "oil": "oil",
    "district_heat": "district_heat",
    "chp": "other_heat",
    "biomass": "other_heat",
    "other": "other_heat",
}


@dataclass
class Baseline:
    e_fuel_kwh: dict[str, float]          # final energy per heat carrier
    eta: dict[str, float]                 # efficiency per carrier
    q_use_kwh: float                      # useful heat
    elec_kwh: float
    kwh_per_m2: float | None              # final heat per m2 water surface
    heat_is_default: bool
    elec_is_default: bool
    plausibility: str | None = None       # low | ok | high | None
    notes: list[str] = field(default_factory=list)
    model_based: bool = False             # useful heat comes from the SPLASH model
    reported_q_use_kwh: float | None = None   # useful heat from the operator's consumption, if entered

    @property
    def e_fuel_total(self) -> float:
        return float(sum(self.e_fuel_kwh.values()))

    @property
    def mix_eta(self) -> float:
        return self.q_use_kwh / self.e_fuel_total if self.e_fuel_total > 0 else 0.0


def carrier_efficiency(carrier: str, inp: PoolInputs, params: Params) -> float:
    eta = float(params.get(ETA_NAME[carrier]))
    if carrier == "district_heat":
        return eta
    if inp.boiler_eta:
        return float(inp.boiler_eta)
    if inp.boiler_age_years and inp.boiler_age_years > float(params.get("old_boiler_age_years")):
        eta += float(params.get("old_boiler_eta_delta"))
    return eta


def compute_baseline(inp: PoolInputs, params: Params, model_q_use_kwh: float | None = None) -> Baseline:
    """Baseline of today's supply.

    With ``model_q_use_kwh`` the useful heat is the demand of the SPLASH model (pool water plus hall air).
    The operator's reported consumption then only sets the mix of carriers and is kept for the comparison.
    Without it, the useful heat comes from the reported consumption or from the benchmark.
    """
    area = inp.water_surface_m2()
    bench = params.central("bench_heat_kwh_per_m2")
    bench_el = params.central("bench_elec_kwh_per_m2")
    notes: list[str] = []

    if inp.consumption_kwh:
        e = {c: float(v) for c, v in inp.consumption_kwh.items() if c in CARRIERS and v > 0}
        heat_default = False
    else:
        carrier = MAIN_TO_CARRIER.get(inp.main_source or "gas", "gas")
        e = {carrier: float(bench["median"]) * area} if area > 0 else {}
        heat_default = True
        notes.append("heat_from_benchmark")

    eta = {c: carrier_efficiency(c, inp, params) for c in e}
    q_use = sum(e[c] * eta[c] for c in e)
    reported = None if heat_default else q_use
    model_based = model_q_use_kwh is not None and model_q_use_kwh > 0
    if model_based:
        weights = {c: (e[c] * eta[c] if not heat_default else 1.0) for c in e}
        wsum = sum(weights.values()) or 1.0
        e = {c: float(model_q_use_kwh) * weights[c] / wsum / eta[c] for c in e}
        q_use = float(model_q_use_kwh)
        notes = [n for n in notes if n != "heat_from_benchmark"] + ["heat_from_model"]

    if inp.electricity_kwh:
        elec, elec_default = float(inp.electricity_kwh), False
    else:
        elec, elec_default = float(bench_el["median"]) * area, True

    rep_m2 = (sum(inp.consumption_kwh.values()) / area) if inp.consumption_kwh and area > 0 else None
    kwh_m2 = rep_m2 if rep_m2 is not None else ((sum(e.values()) / area) if area > 0 and e else None)
    plaus = None
    if rep_m2 is not None and inp.pool_type != "open_air":
        if rep_m2 < float(bench["min"]):
            plaus = "low"
        elif rep_m2 > float(bench["max"]):
            plaus = "high"
        else:
            plaus = "ok"

    return Baseline(
        e_fuel_kwh=e,
        eta=eta,
        q_use_kwh=q_use,
        elec_kwh=elec,
        kwh_per_m2=kwh_m2,
        heat_is_default=heat_default,
        elec_is_default=elec_default,
        plausibility=plaus,
        notes=notes,
        model_based=model_based,
        reported_q_use_kwh=reported,
    )


# ------------------------------------------------------------------- prices
def vat_factor(inp: PoolInputs, params: Params) -> float:
    """Factor from net price to the price the operator effectively pays."""
    deductible = bool(params.central("vat_deductible_by_legal_form").get(inp.legal_form, False))
    return 1.0 if deductible else 1.0 + float(params.central("vat_rate"))


def _entered_price(cost_eur: float, kwh: float, inp: PoolInputs, params: Params) -> float:
    """Effective price per kWh from an annual cost entered by the operator."""
    price = cost_eur / kwh
    if inp.costs_incl_vat == "yes":
        net = price / (1.0 + float(params.central("vat_rate")))
        return net * vat_factor(inp, params)
    if inp.costs_incl_vat == "no":
        return price * vat_factor(inp, params)
    return price  # unknown: take as entered


def effective_prices(inp: PoolInputs, base: Baseline, params: Params) -> tuple[dict[str, float], float]:
    """Return (price per heat carrier, electricity price), EUR/kWh, effective."""
    vf = vat_factor(inp, params)
    if inp.heat_cost_eur and inp.consumption_kwh:
        p_avg = _entered_price(inp.heat_cost_eur, sum(inp.consumption_kwh.values()), inp, params)
        fuel = {c: p_avg for c in base.e_fuel_kwh}
    else:
        fuel = {c: float(params.get(PRICE_NAME[c])) * vf for c in base.e_fuel_kwh}

    if inp.elec_cost_eur and inp.electricity_kwh:
        p_el = _entered_price(inp.elec_cost_eur, inp.electricity_kwh, inp, params)
    else:
        p_el = float(params.get("price_electricity")) * vf
    return fuel, p_el


def baseline_cost_eur(base: Baseline, fuel_prices: dict[str, float]) -> float:
    return sum(base.e_fuel_kwh[c] * fuel_prices[c] for c in base.e_fuel_kwh)


def baseline_co2_kg(base: Baseline, params: Params) -> float:
    return sum(base.e_fuel_kwh[c] * float(params.get(EF_NAME[c])) for c in base.e_fuel_kwh)
