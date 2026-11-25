"""Write hourly calendars for 2025 and 2026 (Europe/Berlin year grid, 8760 hours each).

Day types follow the SPLASH calendar: Sundays and public holidays of Schleswig-Holstein are
``sunday_holiday``. Needs the ``holidays`` package (development only, not at run time).
"""
from __future__ import annotations

from pathlib import Path

import holidays
import pandas as pd

OUT = Path(__file__).resolve().parents[1] / "data" / "splash" / "weather"


def calendar(year: int) -> pd.DataFrame:
    start = pd.Timestamp(year=year, month=1, day=1, tz="Europe/Berlin").tz_convert("UTC")
    utc = pd.date_range(start, periods=8760, freq="h")
    loc = utc.tz_convert("Europe/Berlin")
    hol = holidays.Germany(subdiv="SH", years=[year, year + 1])
    date = pd.Series(loc.date, index=utc)
    is_hol = date.map(lambda d: d in hol).to_numpy()
    wd = loc.weekday.to_numpy()
    day_type = pd.Series("weekday", index=utc)
    day_type[wd == 5] = "saturday"
    day_type[(wd == 6) | is_hol] = "sunday_holiday"
    return pd.DataFrame(
        {
            "hour_of_year": range(1, 8761),
            "ts_utc": [t.isoformat() for t in utc],
            "ts_local": [t.isoformat() for t in loc],
            "date_local": [d.isoformat() for d in loc.date],
            "month": loc.month,
            "hour_local": loc.hour,
            "weekday": wd,
            "day_type": day_type.to_numpy(),
        }
    )


if __name__ == "__main__":
    for y in (2025, 2026):
        c = calendar(y)
        c.to_csv(OUT / f"calendar_{y}.csv", index=False)
        print(y, (c.groupby("date_local").day_type.first().value_counts()).to_dict())
