from __future__ import annotations

import numpy as np
import pandas as pd

COMPONENTS = ["evaporation", "convection", "radiation", "conduction", "make-up water", "solar gain"]
HALL = "hall air (sensible)"
LATENT = "hall dehumidification (latent, memo)"
DHW = "hot water (showers)"
WEEK_H = 168


def pick_weeks(t_out: np.ndarray, active: np.ndarray, index_local: pd.DatetimeIndex) -> dict[str, int]:
    T = len(t_out)
    n = min(WEEK_H, T)
    starts = [p for p in range(0, T - n + 1) if index_local[p].hour == 0 and active[p : p + n].all()]
    if not starts:
        first = int(np.argmax(active)) if active.any() else 0
        starts = [min(first, T - n)]
    score = np.array([np.nanmean(t_out[p : p + n]) for p in starts])
    return {"cold": starts[int(np.argmin(score))], "warm": starts[int(np.argmax(score))], "n": n}
