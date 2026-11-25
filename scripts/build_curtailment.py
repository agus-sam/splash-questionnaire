"""Convert the operator CSV 'Ausgewiesene Abregelungsstrommenge' (15 min, MW) to hourly series.

Output: data/real/curtailment_hourly_T5_T6.csv with one row per UTC hour of 2025 and 2026.

Rules (documented in docs/METHODS.md):
* Local wall time plus the CET/CEST label is converted to UTC, so the autumn DST overlap is unambiguous.
* Hourly value = mean of the four quarter-hours (MW, equal to MWh per hour).
* Quarter-hours marked "N.A." by the operator are missing. They are set to 0 MW and flagged ``na_filled``.
* Hours after the last complete day before the download are flagged ``not_observed`` and set to 0 MW.
  The simulation window of 2026 ends before them.

Usage: python scripts/build_curtailment.py <operator.csv> [--observed-until 2026-11-22]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ZONES = ("T5", "T6")
OUT = Path(__file__).resolve().parents[1] / "data" / "real" / "curtailment_hourly_T5_T6.csv"


def read_operator_csv(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";", encoding="utf-8-sig", dtype=str)
    missing = {"Datum", "Zeitzone", "von", "Einheit", *ZONES} - set(df.columns)
    if missing:
        raise ValueError(f"operator csv lacks columns {sorted(missing)}")
    if set(df["Einheit"].unique()) != {"MW"}:
        raise ValueError("operator csv: unit must be MW")
    off = df["Zeitzone"].map({"CET": 1, "CEST": 2})
    if off.isna().any():
        raise ValueError("operator csv: Zeitzone must be CET or CEST")
    naive = pd.to_datetime(df["Datum"] + " " + df["von"], format="%d.%m.%Y %H:%M")
    out = pd.DataFrame({"utc": naive - pd.to_timedelta(off, unit="h")})
    for z in ZONES:
        out[z] = pd.to_numeric(df[z].str.replace(".", "", regex=False).str.replace(",", ".", regex=False), errors="coerce")
        out[f"{z}_na"] = out[z].isna()
    if out["utc"].duplicated().any():
        raise ValueError("operator csv: duplicate timestamps after UTC conversion")
    return out


def hourly(q: pd.DataFrame, observed_until: str) -> pd.DataFrame:
    q = q.set_index("utc").sort_index()
    h = pd.DataFrame(index=pd.date_range(q.index.min().floor("h"), q.index.max().floor("h"), freq="h"))
    for z in ZONES:
        g = q[z].fillna(0.0).resample("h")
        h[f"{z}_mw"] = g.mean()
        h[f"{z}_na"] = q[f"{z}_na"].astype(int).resample("h").max().astype(bool)
    h["quarters"] = q[ZONES[0]].resample("h").size()
    local = h.index.tz_localize("UTC").tz_convert("Europe/Berlin")
    h["ts_local"] = local
    h["year"] = local.year
    cut = pd.Timestamp(observed_until, tz="Europe/Berlin") + pd.Timedelta(days=1)
    h["flag"] = "ok"
    h.loc[h[[f"{z}_na" for z in ZONES]].any(axis=1), "flag"] = "na_filled"
    h.loc[local >= cut, "flag"] = "not_observed"
    h.loc[h["flag"] == "not_observed", [f"{z}_mw" for z in ZONES]] = 0.0
    h = h[h["year"].isin([2025, 2026])]
    for y, g in h.groupby("year"):
        n = 8760
        if y == 2025 and len(g) != n:
            raise ValueError(f"2025 must have {n} hours, found {len(g)}")
    h.index.name = "ts_utc"
    return h[["ts_local", "year", "T5_mw", "T6_mw", "flag"]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--observed-until", default="2026-11-22", help="last complete local day with operator data")
    a = ap.parse_args()
    h = hourly(read_operator_csv(a.csv), a.observed_until)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    h.round(4).to_csv(OUT)
    print(h.groupby("year")[["T5_mw", "T6_mw"]].sum().round(0), "\n", h.groupby(["year", "flag"]).size())


if __name__ == "__main__":
    main()
