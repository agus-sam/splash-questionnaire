from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np

from . import properties as pr

_BETA_UR = {"A": 0.15, "B": 0.15, "C": 0.20, "D": 0.25, "E": 0.30, "F": 0.30}
_BETA_RU = {"A": 0.07, "B": 0.07, "C": 0.10, "D": 0.15, "E": 0.35, "F": 0.35}


_CLASS_DAY = [
    ["A", "A-B", "B"],
    ["A-B", "B", "C"],
    ["B", "B-C", "C"],
    ["C", "C-D", "D"],
    ["C", "D", "D"],
]

_CLASS_NIGHT = [["E", "F"], ["E", "F"], ["D", "E"], ["D", "D"], ["D", "D"]]
_SPEED_EDGES = np.array([2.0, 3.0, 5.0, 6.0])


_ALPHA_HOURS = list(range(6, 21))
_ALPHA_TABLE = np.array(
    [
        [0, 0, 0, 0, 0.442, 0.570, 0.405, 0, 0, 0, 0, 0],
        [0, 0, 0.221, 0.774, 0.776, 0.800, 0.771, 0.798, 0.713, 0.276, 0, 0],
        [0.285, 0.672, 0.768, 0.811, 0.863, 0.843, 0.836, 0.824, 0.815, 0.760, 0.790, 0.497],
        [0.745, 0.806, 0.836, 0.856, 0.866, 0.867, 0.865, 0.859, 0.851, 0.829, 0.815, 0.777],
        [0.820, 0.842, 0.862, 0.874, 0.874, 0.874, 0.873, 0.872, 0.868, 0.861, 0.846, 0.824],
        [0.852, 0.861, 0.870, 0.876, 0.875, 0.874, 0.874, 0.875, 0.872, 0.872, 0.859, 0.851],
        [0.862, 0.867, 0.872, 0.875, 0.874, 0.874, 0.873, 0.875, 0.871, 0.876, 0.865, 0.861],
        [0.865, 0.869, 0.874, 0.874, 0.874, 0.873, 0.873, 0.873, 0.872, 0.876, 0.866, 0.863],
        [0.865, 0.868, 0.874, 0.875, 0.875, 0.873, 0.874, 0.873, 0.872, 0.875, 0.864, 0.861],
        [0.857, 0.865, 0.872, 0.875, 0.874, 0.873, 0.874, 0.874, 0.871, 0.870, 0.856, 0.849],
        [0.833, 0.855, 0.867, 0.873, 0.873, 0.872, 0.874, 0.872, 0.867, 0.853, 0.834, 0.816],
        [0.795, 0.825, 0.848, 0.859, 0.865, 0.867, 0.869, 0.863, 0.849, 0.810, 0.785, 0.737],
        [0.736, 0.745, 0.809, 0.821, 0.836, 0.848, 0.847, 0.835, 0.806, 0.777, 0.570, 0.570],
        [0, 0.163, 0.681, 0.789, 0.770, 0.809, 0.803, 0.769, 0.656, 0.018, 0, 0],
        [0, 0, 0, 0.019, 0.423, 0.732, 0.727, 0.248, 0, 0, 0, 0],
    ]
)


@dataclass(frozen=True)
class OutdoorParams:
    sigma: float = 5.67e-8
    eps_water: float = 0.95
    f_sky: float = 1.0
    a_max: float = 4.5
    z_b6: float = 0.5
    z_ref: float = 10.0
    b6_c0: float = 0.28
    b6_c1: float = 0.784
    b6_exp: float = 0.695
    bowen_const: float = 0.622
    b17_a: float = -0.4373
    b17_b: float = 0.0037
    b17_c: float = 0.0027
    f_re: float = 0.03
    alpha_w_mode: str = "constant"
    alpha_w_const: float = 0.855
    cloud_mode: str = "S9_ctot_only"
    cloud_c_const: float = 0.55
    ro: float = 0.7
    d_m: float = 0.474
    mixed_rule: str = "shah"
    pasquill_day_ghi: float = 5.0
    pasquill_overcast: float = 0.875
    dp_floor_pa: float = 50.0

    @classmethod
    def from_mapping(cls, m: Mapping[str, object], **overrides) -> "OutdoorParams":
        names = {f for f in cls.__dataclass_fields__}
        rename = {
            "B6_c0": "b6_c0",
            "B6_c1": "b6_c1",
            "B6_exp": "b6_exp",
            "B17_a": "b17_a",
            "B17_b": "b17_b",
            "B17_c": "b17_c",
            "A_max": "a_max",
            "z_B6": "z_b6",
            "F_sky": "f_sky",
            "F_re": "f_re",
            "d_m": "d_m",
            "cloud_C_const": "cloud_c_const",
        }
        kw: dict[str, object] = {}
        for key, val in {**m, **overrides}.items():
            k = rename.get(key, key)
            if k in names:
                kw[k] = val
        for k, v in list(kw.items()):
            ftype = cls.__dataclass_fields__[k].type
            if "float" in str(ftype):
                kw[k] = float(v)
            else:
                kw[k] = str(v)
        p = cls(**kw)
        if p.z_b6 <= p.d_m:
            raise ValueError("wind profile B22 needs z > d (z_B6 must exceed d_m)")
        return p


@dataclass
class OutdoorForcing:
    t_a: np.ndarray
    rh: np.ndarray
    ghi: np.ndarray
    ws10: np.ndarray
    sp: np.ndarray
    t_re: np.ndarray
    occ_per_m2: np.ndarray
    cloud: np.ndarray
    ir: np.ndarray
    month: np.ndarray
    hour_local: np.ndarray

    def __len__(self) -> int:
        return len(self.t_a)

    def slice(self, i: int, j: int) -> "OutdoorForcing":
        return OutdoorForcing(**{k: v[i:j] for k, v in self.__dict__.items()})


@dataclass(frozen=True)
class OutdoorGeometry:
    depth_m: float
    l_ch_m: float


def _class_beta(label: str, ro: float) -> float:
    letters = label.split("-")
    vals = [_BETA_RU[c] + (_BETA_UR[c] - _BETA_RU[c]) * ro for c in letters]
    return float(np.mean(vals))


def wind_at_pool(f: OutdoorForcing, p: OutdoorParams) -> tuple[np.ndarray, np.ndarray]:
    beta_day = np.array([[_class_beta(c, p.ro) for c in row] for row in _CLASS_DAY])
    beta_night = np.array([[_class_beta(c, p.ro) for c in row] for row in _CLASS_NIGHT])
    beta_d = _class_beta("D", p.ro)
    ws = np.asarray(f.ws10, dtype=float)
    vi = np.digitize(ws, _SPEED_EDGES)
    cloud = np.where(np.isnan(f.cloud), p.cloud_c_const / 0.784, f.cloud)
    day = f.ghi > p.pasquill_day_ghi
    gi = np.where(f.ghi > 700.0, 0, np.where(f.ghi >= 350.0, 1, 2))
    ci = np.where(cloud > 0.5, 0, 1)
    beta = np.where(day, beta_day[vi, gi], beta_night[vi, ci])
    beta = np.where(cloud >= p.pasquill_overcast, beta_d, beta)
    v_wi = ws * ((p.z_b6 - p.d_m) / p.z_ref) ** beta
    return v_wi, beta


def solar_absorptance(f: OutdoorForcing, p: OutdoorParams) -> np.ndarray:
    if p.alpha_w_mode == "constant":
        return np.full(len(f), p.alpha_w_const)
    if p.alpha_w_mode == "athens_lookup":
        hrs = np.clip(f.hour_local, _ALPHA_HOURS[0], _ALPHA_HOURS[-1]) - _ALPHA_HOURS[0]
        a = _ALPHA_TABLE[hrs, f.month - 1]
        return np.where((f.hour_local < 6) | (f.hour_local > 20), 0.0, a)
    raise ValueError(f"unknown alpha_w_mode {p.alpha_w_mode}")


def occupancy_factor(occ_per_m2: np.ndarray, p: OutdoorParams) -> np.ndarray:
    fu = p.a_max * np.asarray(occ_per_m2, dtype=float)
    return np.where(fu < 0.1, 1.0 + 2.3 * fu, np.where(fu <= 1.0, 1.2 + 0.3 * fu, 1.5))


def sky_temperature(f: OutdoorForcing, p: OutdoorParams) -> np.ndarray:
    t_a_k = pr.kelvin(f.t_a)
    if p.cloud_mode == "ir_bypass":
        if np.isnan(f.ir).any():
            raise ValueError("cloud_mode ir_bypass needs IR_h_wm2 without gaps")
        return (f.ir / p.sigma) ** 0.25
    eps_cl = p.b17_a + p.b17_b * t_a_k + p.b17_c * f.rh
    if p.cloud_mode == "const":
        c = np.full(len(f), p.cloud_c_const)
    elif p.cloud_mode == "S9_ctot_only":
        c = np.where(np.isnan(f.cloud), p.cloud_c_const, 0.784 * f.cloud)
    else:
        raise ValueError(f"unknown cloud_mode {p.cloud_mode}")
    eps_sky = eps_cl * (1.0 - c) + c
    return eps_sky**0.25 * t_a_k


def heat_balance(
    t_w: np.ndarray | float,
    f: OutdoorForcing,
    geo: OutdoorGeometry,
    p: OutdoorParams,
    v_wi: np.ndarray | None = None,
    alpha_w: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    n = len(f)
    t_w = np.broadcast_to(np.asarray(t_w, dtype=float), (n,))
    if v_wi is None:
        v_wi, _ = wind_at_pool(f, p)
    if alpha_w is None:
        alpha_w = solar_absorptance(f, p)

    t_w_k = pr.kelvin(t_w)
    t_a_k = pr.kelvin(f.t_a)
    p_vi = pr.p_vs_buck(t_w)
    p_ve = pr.p_vs_buck(f.t_a) * f.rh / 100.0
    dh = pr.latent_heat(t_w)
    dp = p_vi - p_ve

    e_fc = (p.b6_c0 + p.b6_c1 * v_wi) * np.maximum(dp, 0.0) ** p.b6_exp / dh

    rho_ae = pr.rho_moist_air(f.t_a, p_ve, f.sp)
    rho_ai = pr.rho_moist_air(t_w, p_vi, f.sp)
    d_rho = rho_ae - rho_ai
    t_f = 0.5 * (t_w_k + t_a_k)
    d_wa = pr.diffusivity_water_air(t_f, f.sp)
    mu = pr.mu_air(t_f)
    ra = pr.G_STD * np.maximum(d_rho, 0.0) * geo.l_ch_m**3 / (mu * d_wa)
    sh = np.where(ra < 1e7, 0.54 * np.maximum(ra, 1e-12) ** 0.25, 0.15 * ra ** (1.0 / 3.0))
    h_m = sh * d_wa / geo.l_ch_m
    rho_v_i = p_vi / (pr.R_V * t_w_k)
    rho_v_e = p_ve / (pr.R_V * t_a_k)
    e_nc = np.where(d_rho > 0.0, np.maximum(h_m * (rho_v_i - rho_v_e), 0.0), 0.0)

    if p.mixed_rule == "shah":
        e_un = np.where(d_rho > 0.0, np.maximum(e_nc, e_fc), e_fc)
    elif p.mixed_rule == "lovell":
        e_un = (e_fc**3.5 + e_nc**3.5) ** (2.0 / 7.0)
    else:
        raise ValueError(f"unknown mixed_rule {p.mixed_rule}")

    f_a = occupancy_factor(f.occ_per_m2, p)
    e_p = f_a * e_un
    q_eva = e_p * dh

    cp_a = pr.cp_air_humid(p_ve, f.sp)
    dp_g = np.maximum(dp, p.dp_floor_pa)
    r_bo = cp_a * f.sp / (p.bowen_const * dh) * (t_w - f.t_a) / dp_g
    q_conv = r_bo * q_eva

    t_sky = sky_temperature(f, p)
    q_rad = p.sigma * p.eps_water * p.f_sky * (t_w_k**4 - t_sky**4)

    q_re = pr.rho_water(t_w) * geo.depth_m * p.f_re / 86400.0 * pr.cp_water(t_w) * (t_w - f.t_re)

    q_sun = f.ghi * alpha_w
    loss = q_eva + q_conv + q_rad + q_re
    return {
        "eva": q_eva,
        "conv": q_conv,
        "rad": q_rad,
        "re": q_re,
        "sun": q_sun,
        "loss": loss,
        "net": loss - q_sun,
        "evap_kg_m2_s": e_p,
        "d_rho": d_rho,
        "ra": ra,
    }
