"""Hourly heat demand by use. The SPLASH model is the only source of the demand.

The model covers pool water (heat loss of all basins) and hall air (sensible load of the hall).
Hot water for showers is part of the model when the pool heats it centrally (``facility.dhw``). Space heating of
other rooms is not part of the model and is not calculated.
"""
from __future__ import annotations

import numpy as np

LEVELS = ("pool_water", "hall_air", "dhw", "space_heating")


def levels_from_model(basins_kw: np.ndarray, hall_kw: np.ndarray, dhw_kw: np.ndarray | None = None) -> dict[str, np.ndarray]:
    """Hourly demand (kWh per hour = kW) of the reference year, taken from the SPLASH facility model."""
    zeros = np.zeros_like(basins_kw, dtype=float)
    return {
        "pool_water": np.asarray(basins_kw, dtype=float),
        "hall_air": np.asarray(hall_kw, dtype=float),
        "dhw": zeros if dhw_kw is None else np.asarray(dhw_kw, dtype=float),
        "space_heating": zeros.copy(),
    }


def no_levels(n: int = 8760) -> dict[str, np.ndarray]:
    return {lv: np.zeros(n) for lv in LEVELS}
