from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import properties as pr

RHO_AIR = 1.2
CP_AIR = 1006.0


@dataclass(frozen=True)
class HallArchetype:
    name: str
    ua_kw_per_k_per_m2: float
    tau_fa: float
    air_changes_per_h: float
    hru_effectiveness: float
    air_temp_c: float
    rh_pct: float
    t_wall_c: float
    t_rs_c: float
    t_g_c: float
    volume_m3_per_m2: float = 12.0

    def air_mass_flow_per_m2(self) -> float:
        return self.air_changes_per_h * self.volume_m3_per_m2 * RHO_AIR / 3600.0

    def sensitivity_kw_per_k_per_m2(self) -> float:
        fresh = self.tau_fa * self.air_mass_flow_per_m2() * CP_AIR / 1000.0 * (1.0 - self.hru_effectiveness)
        return self.ua_kw_per_k_per_m2 + fresh

    def wall_offset_k(self) -> float:
        return self.t_wall_c - self.air_temp_c


def dehumidification_load_kw_per_m2(
    m_v_kg_s_per_m2: np.ndarray,
    t_air: np.ndarray,
    rh_pct: float,
    t_ext: np.ndarray,
    rh_ext_pct: np.ndarray,
    p_tot: np.ndarray,
    arch: HallArchetype,
) -> np.ndarray:
    w_a = pr.humidity_ratio(pr.p_vs_ashrae(t_air) * rh_pct / 100.0, p_tot)
    w_ext = pr.humidity_ratio(pr.p_vs_ashrae(t_ext) * rh_ext_pct / 100.0, p_tot)
    m_a = arch.air_mass_flow_per_m2()
    m_h2o = m_a * arch.tau_fa * (w_a - w_ext) - m_v_kg_s_per_m2
    latent = pr.latent_heat(t_air) / 1000.0
    return np.maximum(-m_h2o, 0.0) * latent
