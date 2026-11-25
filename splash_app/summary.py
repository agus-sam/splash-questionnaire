"""Flat KPI dictionary of a result. Used for saving, the PDF and the admin view."""
from __future__ import annotations

from datetime import datetime, timezone

from splash_calc.scenarios import Result


def _r(x: float | None, nd: int = 2) -> float | None:
    return None if x is None else round(float(x), nd)


PARAM_KEYS = ("wacc", "inflation", "price_escalation_fuel", "price_escalation_electricity", "lifetime_years",
              "price_gas", "price_oil", "price_district_heat", "price_electricity", "hp_capex_per_kw_th",
              "heater_capex_per_kw_el", "heater_efficiency", "eta_carnot", "reported_heat_pool_share",
              "shower_water_l_per_visitor", "shower_mix_temp_c", "stay_in_water_h")


def flat_results(res: Result, opts: dict | None = None, params=None, selection: dict | None = None,
                 items: dict | None = None) -> dict:
    out: dict = {"calc_status": res.status, "params_version": res.params_version,
                 "params_draft": res.params_draft}
    if res.baseline is not None:
        b = res.baseline
        out.update({
            "base_fuel_kwh": _r(b.e_fuel_total, 0), "base_useful_kwh": _r(b.q_use_kwh, 0),
            "base_kwh_per_m2": _r(b.kwh_per_m2, 0), "base_plausibility": b.plausibility or "",
            "base_heat_default": b.heat_is_default,
        })
    # assumptions behind the numbers: standard run or what-if run
    o = opts or {}
    econ = o.get("econ") or {}
    out["whatif_active"] = bool(econ or o.get("calibrate") or o.get("hp_kw") or o.get("band_k") or o.get("curt_mwh") is not None or o.get("zone")
                                or abs(float(o.get("fuel_factor") or 1) - 1) > 1e-9 or abs(float(o.get("el_factor") or 1) - 1) > 1e-9)
    for k in ("fuel_factor", "el_factor", "hp_kw", "band_k", "curt_mwh", "zone", "calibrate"):
        out[f"opt_{k}"] = o.get(k) if o.get(k) is not None else ""
    for k, v in econ.items():
        out[f"opt_econ_{k}"] = v
    if res.status == "ok" and res.context.splash is not None:
        cal = res.context.splash.calibration or {}
        out["demand_calibration_factor"] = _r(cal.get("factor", 1.0), 3)
    ent, tot = res.parsed.confidence()
    out.update({"confidence_entered": ent, "confidence_total": tot})
    for k, v in res.parsed.provenance.items():
        out[f"prov_{k}"] = v
    out["calc_timestamp_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for k, v in (selection or {}).items():
        out[f"sel_{k}"] = v
    if items:
        for k, it in items.items():
            out[f"cls_{k}"] = it.cls
            if it.value is not None and not isinstance(it.value, str):
                out[f"resolved_{k}"] = _r(it.value, 3)
        out["defaults_used"] = ",".join(k for k, it in items.items() if it.cls in ("default", "benchmark"))
    if params is not None:
        for k in PARAM_KEYS:
            try:
                v = params.get(k)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(v, (int, float)):
                out[f"param_{k}"] = v
    if res.status != "ok":
        return out
    ctx = res.context
    sp = ctx.splash
    out.update({"zone": ctx.zone, "zone_mapped": ctx.zone_mapped, "splash_version": sp.version if sp else "",
                "design_load_kw": _r(sp.design_kw, 1) if sp else None})
    for case, cr in res.cases.items():
        s = case[:3]
        if cr.hp is not None:
            out[f"hp_npv_{s}"] = _r(cr.hp.econ.npv_eur, 0)
            out[f"hp_saving_y1_{s}"] = _r(cr.hp.econ.net_saving_eur_y1, 0)
            out[f"hp_co2_t_y1_{s}"] = _r(cr.hp.co2.net_t_y1, 1)
        for k, fo in cr.flex.items():
            out[f"flex_{k}_npv_{s}"] = _r(fo.econ.npv_eur, 0)
            out[f"flex_{k}_saving_y1_{s}"] = _r(fo.econ.net_saving_eur_y1, 0)
    c = res.central
    if c.hp is not None:
        out.update({
            "hp_capacity_kw_th": _r(c.hp.res.capacity_kw_th, 1), "hp_scop": _r(c.hp.res.scop, 2),
            "hp_coverage": _r(c.hp.res.coverage, 3), "hp_elec_kwh": _r(c.hp.res.elec_kwh, 0),
            "hp_fuel_saved_kwh": _r(sum(c.hp.res.fuel_saved_kwh.values()), 0),
            "hp_investment_eur": _r(c.hp.investment, 0), "hp_grant_eur": _r(c.hp.subsidy["grant_eur"], 0),
            "hp_payback_years": _r(c.hp.econ.payback_years, 1),
        })
    for k, fo in c.flex.items():
        r = fo.res
        out.update({
            f"flex_{k}_capacity_kw_el": _r(r.capacity_kw_el, 1),
            f"flex_{k}_absorbed_kwh": _r(r.absorbed_kwh_el, 0),
            f"flex_{k}_displaced_kwh": _r(r.displaced_kwh_th, 0),
            f"flex_{k}_investment_eur": _r(fo.investment, 0),
            f"flex_{k}_break_even_eur_kwh": _r(fo.econ.break_even_price, 4),
            f"flex_{k}_curt_hours": r.curtail_hours,
            f"flex_{k}_absorption_hours": r.absorption_hours,
        })
    return out
