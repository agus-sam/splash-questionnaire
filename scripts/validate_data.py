"""Validate the data behind the flexible heating model before deployment.

Checks the hourly operator curtailment, the calendars, the SPLASH data package and the zone map.
Usage: python scripts/validate_data.py
Exit code 0 if everything is usable, 1 otherwise.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from splash_calc import climate  # noqa: E402
from splash_calc.splash_engine import YEARS, ZONES, calendar, curtailment_mw, static_data  # noqa: E402


def main() -> int:
    problems = 0
    try:
        d = static_data()
        print(f"OK  SPLASH data package: {len(d.basins)} basins, zones {sorted(d.weather)}")
        for name, flag in d.synthetic_flags.items():
            if flag:
                print(f"    note: input '{name}' is synthetic or assumed in the SPLASH package")
    except Exception as exc:
        print(f"ERR SPLASH data package: {exc}")
        return 1
    for y in YEARS:
        cal, cur = calendar(y), curtailment_mw(y)
        ok = len(cal) == 8760 and len(cur) == 8760 and (cur[list(ZONES)] >= 0).all().all()
        print(f"{'OK ' if ok else 'ERR'} {y}: calendar and curtailment 8760 h")
        problems += 0 if ok else 1
        flags = cur["flag"].value_counts().to_dict()
        print(f"    flags {flags}; " + ", ".join(f"{z} {cur[z].sum():,.0f} MWh" for z in ZONES))
    print("OK  zones.csv found" if (climate.REAL_DIR / "zones.csv").exists()
          else "WARN zones.csv missing: every pool is mapped to the default zone (the user can choose the zone)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
