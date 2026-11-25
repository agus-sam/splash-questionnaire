from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class FacResult:
    q_basin: np.ndarray
    q_hall: np.ndarray
    short: np.ndarray
    hall_short: np.ndarray
    spill: np.ndarray
    energy: np.ndarray
    grid_el: np.ndarray
    curt_el: np.ndarray
    conv_basin: np.ndarray | None = None
    conv_hall: np.ndarray | None = None

    @classmethod
    def empty(cls, nb: int, T: int) -> "FacResult":
        z = np.zeros
        return cls(z((nb, T)), z(T), z((nb, T)), z(T), z((nb, T)), z((nb, T + 1)), z(T), z(T), z((nb, T)), z(T))

    @property
    def el(self) -> np.ndarray:
        return self.grid_el + self.curt_el

    @property
    def p2h_heat(self) -> np.ndarray:
        return self.q_basin.sum(axis=0) + self.q_hall

    @property
    def conv_heat(self) -> np.ndarray:
        return self.conv_basin.sum(axis=0) + self.conv_hall
