"""BEG heating grant for non-residential buildings (KfW 522 / 422).

Grant = rate x min(eligible costs, cap). The cap depends on the heated net floor
area. There is no legal entitlement and the application must be filed before
work starts. Electric direct heaters are not eligible.
"""
from __future__ import annotations

from .params import Params


def eligible_cost_cap(area_m2: float, params: Params) -> float:
    cfg = params.central("subsidy_cap_bands")
    flat_area = float(cfg["flat_up_to_m2"])
    cap = float(cfg["flat_eur"])
    if area_m2 <= flat_area:
        return cap
    lower = flat_area
    for band in cfg["bands"]:
        upper = band["up_to_m2"]
        top = area_m2 if upper is None else min(area_m2, float(upper))
        if top > lower:
            cap += (top - lower) * float(band["eur_per_m2"])
            lower = top
        if upper is None or area_m2 <= float(upper):
            break
    return cap


def heat_pump_subsidy(capex_eur: float, hall_area_m2: float | None, params: Params) -> dict:
    """Return the grant and the numbers behind it."""
    area = float(hall_area_m2 or 0.0) * float(params.central("subsidy_area_factor"))
    cap = eligible_cost_cap(area, params)
    eligible = float(capex_eur) * float(params.central("subsidy_eligible_share"))
    base = min(eligible, cap)
    grant = base * float(params.get("subsidy_rate"))
    return {
        "grant_eur": grant,
        "cap_eur": cap,
        "eligible_eur": eligible,
        "rate": float(params.get("subsidy_rate")),
        "cap_binding": eligible > cap,
        "area_m2": area,
    }
