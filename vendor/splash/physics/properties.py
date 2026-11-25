from __future__ import annotations

import numpy as np

G_STD = 9.80665
R_DA = 287.055
R_V = 461.52
EPS_W = 0.621945

ArrayLike = np.ndarray | float


def kelvin(t_c: ArrayLike) -> np.ndarray:
    return np.asarray(t_c, dtype=float) + 273.15


def rho_water(t_c: ArrayLike) -> np.ndarray:
    t = np.asarray(t_c, dtype=float)
    num = 999.83952 + 16.945176 * t - 7.9870401e-3 * t**2 - 46.170461e-6 * t**3 + 105.56302e-9 * t**4 - 280.54253e-12 * t**5
    return num / (1.0 + 16.879850e-3 * t)


def cp_water(t_c: ArrayLike) -> np.ndarray:
    t = np.asarray(t_c, dtype=float)
    return 4219.21145 - 3.29999397 * t + 0.104303179 * t**2 - 1.56562573e-3 * t**3 + 9.9555536e-6 * t**4


def latent_heat(t_c: ArrayLike) -> np.ndarray:
    t = np.asarray(t_c, dtype=float)
    return 2_500_925.72 - 2379.41524 * t + 0.749363187 * t**2 - 0.015111874 * t**3


def p_vs_buck(t_c: ArrayLike) -> np.ndarray:
    t = np.asarray(t_c, dtype=float)
    return 611.21 * np.exp((18.678 - t / 234.5) * t / (257.14 + t))


def p_vs_ashrae(t_c: ArrayLike) -> np.ndarray:
    tk = kelvin(t_c)
    c8, c9, c10, c11, c12, c13 = (
        -5.800226e3,
        1.3914993,
        -4.8640239e-2,
        4.1764768e-5,
        -1.4452093e-8,
        6.5459673,
    )
    return np.exp(c8 / tk + c9 + tk * (c10 + tk * (c11 + tk * c12)) + c13 * np.log(tk))


def p_vs(t_c: ArrayLike, method: str = "buck") -> np.ndarray:
    if method == "buck":
        return p_vs_buck(t_c)
    if method == "ashrae":
        return p_vs_ashrae(t_c)
    raise ValueError(f"unknown saturation pressure method: {method}")


def humidity_ratio(p_v: ArrayLike, p_tot: ArrayLike) -> np.ndarray:
    p_v = np.asarray(p_v, dtype=float)
    return EPS_W * p_v / (np.asarray(p_tot, dtype=float) - p_v)


def rho_moist_air(t_c: ArrayLike, p_v: ArrayLike, p_tot: ArrayLike) -> np.ndarray:
    tk = kelvin(t_c)
    p_v = np.asarray(p_v, dtype=float)
    return (np.asarray(p_tot, dtype=float) - p_v) / (R_DA * tk) + p_v / (R_V * tk)


def mu_air(t_k: ArrayLike) -> np.ndarray:
    t_k = np.asarray(t_k, dtype=float)
    return 1.716e-5 * (t_k / 273.15) ** 1.5 * (273.15 + 110.4) / (t_k + 110.4)


def cp_air_humid(p_v: ArrayLike, p_tot: ArrayLike) -> np.ndarray:
    w = humidity_ratio(p_v, p_tot)
    return 1006.0 + w * 1860.0


def diffusivity_water_air(t_f_k: ArrayLike, p_tot: ArrayLike) -> np.ndarray:
    return 1.049e-4 * np.asarray(t_f_k, dtype=float) ** 1.774 / np.asarray(p_tot, dtype=float)
