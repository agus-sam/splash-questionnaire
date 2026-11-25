from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import InvestmentCfg, Settings
from .data_loader import SplashData


class EconomicsError(RuntimeError):
    pass


@dataclass
class EconInputs:
    catalogue: pd.DataFrame
    grid_price: float
    curt_price: float
    grid_co2: float
    curt_co2: float
    co2_price: float
    heat_cost: pd.Series
    heat_co2: pd.Series
    facility_mix: pd.DataFrame
    heat_input: pd.Series
    heat_vom: pd.Series
    heat_fom: pd.Series
    inv: InvestmentCfg


def load_inputs(data: SplashData, s: Settings) -> EconInputs:
    ec = s.economics
    if data.heat_sources is None:
        raise EconomicsError("config/heat_sources.csv is missing in the data package, economics cannot run")
    cat = data.heat_sources.set_index("source_id").copy()
    for sid, price in ec.price_overrides.items():
        if sid not in cat.index:
            raise EconomicsError(f"economics.price_overrides: unknown source_id {sid!r}")
        cat.loc[sid, "price_eur_per_mwh_input"] = float(price)
    if ec.grid_price_eur_per_mwh is not None:
        cat.loc["grid_electricity", "price_eur_per_mwh_input"] = float(ec.grid_price_eur_per_mwh)
    if ec.curtailed_price_eur_per_mwh is not None:
        cat.loc["curtailed_electricity", "price_eur_per_mwh_input"] = float(ec.curtailed_price_eur_per_mwh)
    co2p = ec.co2_price_eur_per_t if ec.include_co2_cost else 0.0
    for sid, val in ec.capex_overrides.items():
        if sid not in cat.index:
            raise EconomicsError(f"economics.capex_overrides: unknown source_id {sid!r}")
        cat.loc[sid, "capex"] = float(val)
    conv = cat[(cat["row_role"] == "heat_source") & (cat["is_electric_p2h"] == 0)]
    heat_cost = conv["price_eur_per_mwh_input"] / conv["conversion_efficiency"]
    heat_co2 = conv["co2_kg_per_mwh_input"] / conv["conversion_efficiency"]
    heat_input = 1.0 / conv["conversion_efficiency"]
    if data.facility_heat_sources is None:
        raise EconomicsError("config/facility_heat_sources.csv is missing in the data package")
    mix = data.facility_heat_sources[["facility_id", "source_id", "share_of_heat"]].copy()
    if ec.reference_source != "facility_mix":
        if ec.reference_source not in conv.index:
            raise EconomicsError(f"economics.reference_source must be facility_mix or one of {sorted(conv.index)}")
        mix = pd.DataFrame({"facility_id": data.facilities["facility_id"], "source_id": ec.reference_source, "share_of_heat": 1.0})
    return EconInputs(
        catalogue=cat,
        grid_price=float(cat.loc["grid_electricity", "price_eur_per_mwh_input"]),
        curt_price=float(cat.loc["curtailed_electricity", "price_eur_per_mwh_input"]),
        grid_co2=float(cat.loc["grid_electricity", "co2_kg_per_mwh_input"]),
        curt_co2=float(cat.loc["curtailed_electricity", "co2_kg_per_mwh_input"]),
        co2_price=co2p,
        heat_cost=heat_cost,
        heat_co2=heat_co2,
        facility_mix=mix,
        heat_input=heat_input,
        heat_vom=conv["variable_om_eur_per_mwh_th"],
        heat_fom=conv["fixed_om"],
        inv=ec.investment,
    )


def facility_conventional(ei: EconInputs, facilities: pd.DataFrame) -> pd.DataFrame:
    m = ei.facility_mix.copy()
    m["fuel"] = m["share_of_heat"] * m["source_id"].map(ei.heat_cost)
    m["co2"] = m["share_of_heat"] * m["source_id"].map(ei.heat_co2)
    m["inp"] = m["share_of_heat"] * m["source_id"].map(ei.heat_input)
    m["vom"] = m["share_of_heat"] * m["source_id"].map(ei.heat_vom)
    m["fom"] = m["share_of_heat"] * m["source_id"].map(ei.heat_fom)
    g = m.groupby("facility_id")[["fuel", "co2", "inp", "vom", "fom"]].sum()
    g["co2_cost"] = g["co2"] / 1e3 * ei.co2_price
    g["conv_eur_per_mwh_th"] = g["fuel"] + g["co2_cost"]
    g = g.rename(columns={"vom": "vom_eur_per_mwh_th", "fom": "fom_eur_per_kw_th_a", "inp": "conv_input_mwh_per_mwh_th"})
    main = m.sort_values("share_of_heat", ascending=False).drop_duplicates("facility_id").set_index("facility_id")["source_id"]
    g["main_source"] = main
    g = g.rename(columns={"fuel": "fuel_eur_per_mwh_th", "co2": "co2_kg_per_mwh_th"})
    return g.reindex(facilities["facility_id"]).fillna(0.0).rename_axis("facility_id")
