from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np

from . import properties as pr

EVAP_VARIANTS = ("ashrae", "shah_eq6_7", "s5_activity", "shah_max")

_SHAH_VAPOUR_COEF_KG_H_M2_PA = 1.80e-4


@dataclass(frozen=True)
class IndoorParams:
    coef_radiation: float = 0.0057
    eps_water: float = 0.87
    shah_c_high_drho: float = 35.0
    shah_c_low_drho: float = 40.0
    drho_switch: float = 0.02
    shah_occ_a: float = 1.9
    shah_occ_b: float = 21.0
    shah_occ_c: float = 5.3
    n_star_min: float = 0.05
    s5_coef: float = 4.0e-5

    ashrae_c0: float = 0.089
    ashrae_c1: float = 0.0782
    ashrae_v_air: float = 0.10

    ashrae_unocc_ratio: float = 0.5
    ashrae_n_full: float = 0.10
    renovation_r: float = 0.025
    h_conv_option: str = "S6"
    u_side: float = 2.94
    u_bottom: float = 0.5
    evaporation_variant: str = "ashrae"
    psat_method: str = "ashrae"

    @classmethod
    def from_mapping(cls, m: Mapping[str, object], **overrides) -> "IndoorParams":
        rename = {
            "shah_C_high_drho": "shah_c_high_drho",
            "shah_C_low_drho": "shah_c_low_drho",
            "S5_coef": "s5_coef",
            "v_air": "ashrae_v_air",
            "N_star_min": "n_star_min",
            "renovation_R": "renovation_r",
            "U_side": "u_side",
            "U_bottom": "u_bottom",
        }
        names = set(cls.__dataclass_fields__)
        kw: dict[str, object] = {}
        for key, val in {**m, **overrides}.items():
            k = rename.get(key, key)
            if k in names:
                kw[k] = val
        for k, v in list(kw.items()):
            ftype = str(cls.__dataclass_fields__[k].type)
            kw[k] = float(v) if "float" in ftype else str(v)
        p = cls(**kw)
        if p.evaporation_variant not in EVAP_VARIANTS:
            raise ValueError(f"evaporation_variant must be one of {EVAP_VARIANTS}")
        return p

    def h_const(self) -> float | None:
        if self.h_conv_option.upper() == "S6":
            return None
        return float(self.h_conv_option)


@dataclass
class IndoorForcing:
    p_tot: np.ndarray
    occ_per_m2: np.ndarray
    t_wn: np.ndarray

    def __len__(self) -> int:
        return len(self.p_tot)

    def slice(self, i: int, j: int) -> "IndoorForcing":
        return IndoorForcing(**{k: v[i:j] for k, v in self.__dict__.items()})


@dataclass(frozen=True)
class IndoorGeometry:
    depth_m: float
    side_area_per_m2: float
    f_act: float = 1.0


def occupancy_ratio(n_star: np.ndarray, d_rho_pos: np.ndarray, p: IndoorParams) -> np.ndarray:
    n_star = np.asarray(n_star, dtype=float)

    def r(n):
        return p.shah_occ_a - p.shah_occ_b * d_rho_pos + p.shah_occ_c * n

    r_min = r(p.n_star_min)
    return np.where(n_star >= p.n_star_min, r(n_star), 1.0 + (r_min - 1.0) * n_star / p.n_star_min)


def heat_balance(
    t_w: np.ndarray | float,
    t_a: np.ndarray | float,
    rh_pct: float,
    t_wall: np.ndarray | float,
    t_rs: float,
    t_g: float,
    f: IndoorForcing,
    geo: IndoorGeometry,
    p: IndoorParams,
) -> dict[str, np.ndarray]:
    n = len(f)
    t_w = np.broadcast_to(np.asarray(t_w, dtype=float), (n,))
    t_a = np.broadcast_to(np.asarray(t_a, dtype=float), (n,))
    t_wall = np.broadcast_to(np.asarray(t_wall, dtype=float), (n,))

    p_w = pr.p_vs(t_w, p.psat_method)
    p_r = pr.p_vs(t_a, p.psat_method) * rh_pct / 100.0
    w_w = pr.humidity_ratio(p_w, f.p_tot)
    w_r = pr.humidity_ratio(p_r, f.p_tot)
    rho_w_air = pr.rho_moist_air(t_w, p_w, f.p_tot)
    rho_r = pr.rho_moist_air(t_a, p_r, f.p_tot)
    d_rho = rho_r - rho_w_air
    d_rho_pos = np.maximum(d_rho, 0.0)
    c_shah = np.where(d_rho > p.drho_switch, p.shah_c_high_drho, p.shah_c_low_drho)

    e_buoy = c_shah * rho_w_air * d_rho_pos ** (1.0 / 3.0) * np.maximum(w_w - w_r, 0.0)
    dp = np.maximum(p_w - p_r, 0.0)
    n_star = f.occ_per_m2
    if p.evaporation_variant == "ashrae":
        y_kj_kg = pr.latent_heat(t_w) / 1000.0
        occ = p.ashrae_unocc_ratio + (1.0 - p.ashrae_unocc_ratio) * np.minimum(np.maximum(n_star, 0.0) / p.ashrae_n_full, 1.0)
        e = (dp / 1000.0) * (p.ashrae_c0 + p.ashrae_c1 * p.ashrae_v_air) / y_kj_kg * geo.f_act * occ * 3600.0
    elif p.evaporation_variant == "shah_eq6_7":
        e = e_buoy * occupancy_ratio(n_star, d_rho_pos, p)
    elif p.evaporation_variant == "shah_max":
        e0 = np.maximum(e_buoy, _SHAH_VAPOUR_COEF_KG_H_M2_PA * dp)
        e = e0 * occupancy_ratio(n_star, d_rho_pos, p)
    elif p.evaporation_variant == "s5_activity":
        e = p.s5_coef * 3600.0 * geo.f_act * dp / 1000.0
    else:
        raise ValueError(p.evaporation_variant)
    m_dot = e / 3600.0

    latent = pr.latent_heat(t_w) / 1000.0
    c_w = pr.cp_water(t_w) / 1000.0
    q_evap = m_dot * (latent + c_w * (t_w - f.t_wn))

    q_rad = p.coef_radiation * p.eps_water * (((t_w + 273.15) / 100.0) ** 4 - ((t_wall + 273.15) / 100.0) ** 4)
    q_cond = (p.u_side * geo.side_area_per_m2 * (t_w - t_rs) + p.u_bottom * (t_w - t_g)) / 1000.0
    h_c = p.h_const()
    h = 0.22 * np.abs(t_w - t_a) ** (1.0 / 3.0) if h_c is None else h_c
    q_conv = h * (t_w - t_a) / 1000.0
    q_renov = pr.rho_water(t_w) * geo.depth_m * p.renovation_r / 86400.0 * c_w * (t_w - f.t_wn)

    loss = q_evap + q_rad + q_cond + q_conv + q_renov
    return {
        "evap": q_evap,
        "rad": q_rad,
        "cond": q_cond,
        "conv": q_conv,
        "renov": q_renov,
        "loss": loss,
        "evap_kg_m2_s": m_dot,
        "d_rho": d_rho,
    }
