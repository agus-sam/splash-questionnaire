from __future__ import annotations

import numpy as np

from .model import FacilityModel
from .results import FacResult
from .rules import simulate_rule

BASE = "-"
MODES = ("baseline", "hysteresis_addon", "hysteresis_replace", "hysteresis_optimised")
_RULE = {
    "baseline": ("floor", "conv"),
    "hysteresis_addon": ("hysteresis", "addon"),
    "hysteresis_replace": ("hysteresis", "replace"),
    "hysteresis_optimised": ("hysteresis", "addon"),
}


def run_zone_mode(
    fms: list[FacilityModel],
    q_rated: dict[int, float],
    avail_kw: np.ndarray,
    mode: str,
    *,
    depth: float = 1.0,
    priority: str = "hall",
    hold_margin_k: float = 0.0,
) -> dict[int, FacResult]:
    if mode not in MODES:
        raise ValueError(f"mode must be in {MODES}")
    rule, supply = _RULE[mode]
    return simulate_rule(fms, q_rated, avail_kw, rule, supply=supply, depth=depth, hold_margin_k=hold_margin_k, priority=priority)
