"""Series container and the mapping from postal code to curtailment zone.

Weather and curtailment data come from the SPLASH package (``data/splash``) and the operator file
(``data/real/curtailment_hourly_T5_T6.csv``). See ``splash_engine.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .params import DATA_DIR

REAL_DIR = DATA_DIR / "real"
DEFAULT_ZONE = "T6"


@dataclass(frozen=True)
class Series:
    values: np.ndarray
    is_demo: bool
    label: str


def zone_for_postcode(postcode: str, directory: Path | None = None) -> tuple[str, bool]:
    """Map a postal code to a grid zone using data/real/zones.csv.

    The file has the columns ``plz_prefix`` and ``zone``. The longest matching
    prefix wins. Returns (zone, mapped). Without a file or a match the default
    zone is returned with ``mapped=False``.
    """
    path = (directory or REAL_DIR) / "zones.csv"
    pc = (postcode or "").strip()
    if path.exists() and pc:
        df = pd.read_csv(path, dtype=str)
        best: tuple[int, str] | None = None
        for _, row in df.iterrows():
            prefix = str(row["plz_prefix"]).strip()
            if prefix and pc.startswith(prefix) and (best is None or len(prefix) > best[0]):
                best = (len(prefix), str(row["zone"]).strip())
        if best:
            return best[1], True
    return DEFAULT_ZONE, False
