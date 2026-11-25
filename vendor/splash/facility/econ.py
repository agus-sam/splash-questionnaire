from __future__ import annotations

from dataclasses import dataclass

from ..config import Settings
from ..data_loader import SplashData
from ..economics import facility_conventional, load_inputs
from .model import TECH_SOURCE


def crf(rate: float, years: float) -> float:
    return 1.0 / years if rate <= 0 else rate * (1 + rate) ** years / ((1 + rate) ** years - 1)


@dataclass
class Econ:
    grid_eur_per_mwh_e: float
    curt_eur_per_mwh_e: float
    grid_co2_kg_per_mwh_e: float
    curt_co2_kg_per_mwh_e: float
    conv_eur_per_mwh_th: dict[int, float]
    conv_co2_kg_per_mwh_th: dict[int, float]
    main_source: dict[int, str]
    plant: dict[str, dict]
    controller: dict


def econ_inputs(data: SplashData, s: Settings) -> Econ:
    ei = load_inputs(data, s)
    cat, inv = ei.catalogue, ei.inv
    r, sub = inv.discount_rate, inv.capex_subsidy_pct
    plant = {}
    for tech, sid in TECH_SOURCE.items():
        row = cat.loc[sid]
        capex = float(row["capex"]) * (1.0 - sub)
        plant[tech] = {
            "source_id": sid,
            "capex": capex,
            "fom": float(row["fixed_om"]),
            "vom": float(row["variable_om_eur_per_mwh_th"]),
            "lifetime": float(row["lifetime_years"]),
            "ann": capex * crf(r, float(row["lifetime_years"])) + float(row["fixed_om"]),
        }
    ctrl = {"capex": 0.0, "ann": 0.0, "fom": 0.0}
    if s.facility.economics.include_controller:
        c = cat.loc["flex_controller"]
        capex = float(c["capex"]) * (1.0 - sub)
        ctrl = {"capex": capex, "fom": float(c["fixed_om"]), "ann": capex * crf(r, float(c["lifetime_years"])) + float(c["fixed_om"])}
    fc = facility_conventional(ei, data.facilities)
    conv = (fc["conv_eur_per_mwh_th"] + fc["vom_eur_per_mwh_th"]).to_dict()
    return Econ(
        ei.grid_price,
        ei.curt_price,
        ei.grid_co2,
        ei.curt_co2,
        {int(k): float(v) for k, v in conv.items()},
        {int(k): float(v) for k, v in fc["co2_kg_per_mwh_th"].items()},
        {int(k): str(v) for k, v in fc["main_source"].items()},
        plant,
        ctrl,
    )


def econ_row(
    e: Econ,
    fid: int,
    tech: str,
    mode: str,
    conv_mwh: float,
    p2h_mwh: float,
    grid_mwh: float,
    curt_mwh: float,
    q_rated_kw: float,
    k: float,
    base_conv_mwh: float,
) -> dict:
    c, co2 = e.conv_eur_per_mwh_th[fid], e.conv_co2_kg_per_mwh_th[fid]
    pl = e.plant.get(tech, {"vom": 0.0, "ann": 0.0, "fom": 0.0, "capex": 0.0})
    has_p2h = mode != "baseline" and q_rated_kw > 0
    cost_conv = conv_mwh * c * k
    cost_el = (grid_mwh * e.grid_eur_per_mwh_e + curt_mwh * e.curt_eur_per_mwh_e) * k
    cost_vom = p2h_mwh * pl["vom"] * k
    ann = (q_rated_kw * pl["ann"] + e.controller["ann"]) if has_p2h else 0.0
    cost = cost_conv + cost_el + cost_vom + ann
    base = base_conv_mwh * c * k
    op_saving = base - (cost_conv + cost_el + cost_vom) - ((q_rated_kw * pl["fom"] + e.controller["fom"]) if has_p2h else 0.0)
    invest = (q_rated_kw * pl["capex"] + e.controller["capex"]) if has_p2h else 0.0
    return {
        "main_current_source": e.main_source[fid],
        "cost_current_heat_eur_a": cost_conv,
        "cost_electricity_eur_a": cost_el,
        "cost_plant_vom_eur_a": cost_vom,
        "plant_annuity_eur_a": ann,
        "cost_total_eur_a": cost,
        "cost_baseline_eur_a": base,
        "net_benefit_eur_a": base - cost,
        "co2_t_a": (conv_mwh * co2 + grid_mwh * e.grid_co2_kg_per_mwh_e + curt_mwh * e.curt_co2_kg_per_mwh_e) * k / 1e3,
        "co2_baseline_t_a": base_conv_mwh * co2 * k / 1e3,
        "invest_eur": invest,
        "simple_payback_a": invest / op_saving if has_p2h and op_saving > 0 else float("nan"),
    }
