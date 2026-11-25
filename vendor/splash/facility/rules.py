from __future__ import annotations

import numpy as np

from .model import FacilityModel
from .results import FacResult

RULE_MODES = ("floor", "hysteresis")
SUPPLIES = ("conv", "addon", "replace")


def simulate_rule(
    fms: list[FacilityModel],
    q_rated: dict[int, float],
    avail_kw: np.ndarray,
    mode: str,
    *,
    supply: str = "replace",
    depth: float = 1.0,
    hold_margin_k: float = 0.0,
    priority: str = "hall",
    t0: int = 0,
    t1: int | None = None,
    e0: dict[int, np.ndarray] | None = None,
) -> dict[int, FacResult]:
    if mode not in RULE_MODES:
        raise ValueError(f"mode must be in {RULE_MODES}")
    if supply not in SUPPLIES:
        raise ValueError(f"supply must be in {SUPPLIES}")
    if supply == "conv":
        mode = "floor"
    T = fms[0].T if t1 is None else t1
    nt = T - t0
    B = [(fm, i) for fm in fms for i in range(fm.n_basins)]
    nb = len(B)
    fidx = {fm.facility_id: k for k, fm in enumerate(fms)}
    fb = np.array([fidx[fm.facility_id] for fm, _ in B])
    nf = len(fms)
    d = depth
    a = np.vstack([fm.basins[i].a_kw[t0:T] for fm, i in B])
    rate = np.vstack([fm.basins[i].rate[t0:T] for fm, i in B])
    frac = np.vstack([fm.basins[i].active[t0 : T + 1] for fm, i in B])
    cop = np.vstack([fm.cop_basin(i)[t0:T] for fm, i in B])
    cap = np.array([fm.basins[i].cap_kwh for fm, i in B])
    c_k = np.array([fm.basins[i].c_kwh_per_k for fm, i in B])
    e_hi = d * cap[:, None] * frac
    Hh = np.vstack([fm.load_kw()[t0:T] for fm in fms])
    cop_h = np.vstack([fm.cop_load()[t0:T] if fm.has_load else np.ones(nt) for fm in fms])
    cap_t = np.vstack([q_rated[fm.facility_id] * fm.avail[t0:T] for fm in fms])
    margin_e = hold_margin_k * c_k
    avail = avail_kw[t0:T]
    e = np.concatenate([(e0[fm.facility_id] if e0 is not None else np.zeros(fm.n_basins)) for fm in fms]).astype(float)
    e_hist = np.zeros((nb, nt + 1))
    e_hist[:, 0] = e
    qb = np.zeros((nb, nt))
    cvb = np.zeros((nb, nt))
    cvh = np.zeros((nf, nt))
    curt_h = np.zeros((nb, nt))
    spill = np.zeros((nb, nt))
    unmet = np.zeros((nb, nt))
    qh_hist = np.zeros((nf, nt))
    curt_el = np.zeros((nf, nt))
    grid_el = np.zeros((nf, nt))
    charging = np.zeros(nb, dtype=bool)

    def fsum(x):
        return np.bincount(fb, weights=x, minlength=nf)

    for t in range(nt):
        net = a[:, t] + rate[:, t] * e
        q_floor = np.maximum(net - e, 0.0)
        capf = cap_t[:, t]
        if priority == "hall":
            qh = np.minimum(Hh[:, t], capf)
            rem = capf - qh
            sc = np.where(fsum(q_floor) > 1e-12, np.minimum(1.0, rem / np.maximum(fsum(q_floor), 1e-12)), 0.0)
            qf = q_floor * sc[fb]
        else:
            sc = np.where(fsum(q_floor) > 1e-12, np.minimum(1.0, capf / np.maximum(fsum(q_floor), 1e-12)), 0.0)
            qf = q_floor * sc[fb]
            qh = np.minimum(Hh[:, t], capf - fsum(qf))
        left = capf - qh - fsum(qf)
        zone_on = bool(avail[t] > 1e-9)
        if supply == "addon" and not (zone_on and mode != "floor"):
            qh = np.zeros(nf)
        if mode == "floor":
            total = qf
        else:
            on = np.full(nb, zone_on)
            if margin_e.max() > 0.0:
                trigger = on & (e <= e_hi[:, t + 1] - margin_e + 1e-9)
                charging = np.where(on, charging | trigger, False)
                charging &= e < e_hi[:, t + 1] - 1e-9
            else:
                charging = on
            q_des = np.where(charging, np.maximum(net + (e_hi[:, t + 1] - e), 0.0), 0.0)
            extra = np.maximum(q_des - q_floor, 0.0)
            esc = np.where(fsum(extra) > 1e-12, np.minimum(1.0, np.maximum(left, 0.0) / np.maximum(fsum(extra), 1e-12)), 0.0)
            total = qf + extra * esc[fb]
        req = np.where(charging, total, 0.0) if mode != "floor" else np.zeros(nb)
        tot_el = (req / cop[:, t]).sum() + ((qh / cop_h[:, t]).sum() if supply == "addon" else 0.0)
        s_z = min(1.0, avail[t] / tot_el) if tot_el > 1e-12 else 0.0
        c_t = req * s_z
        if supply == "replace":
            g_t = np.maximum(qf - c_t, 0.0)
            q = c_t + g_t
            v_t = np.zeros(nb)
        else:
            qh = qh * s_z
            v_t = np.maximum(q_floor - c_t, 0.0)
            g_t = np.zeros(nb)
            q = c_t + v_t
        e_next = e + q - net
        dmp = np.maximum(e_next - e_hi[:, t + 1], 0.0)
        e_next = e_next - dmp
        unmet[:, t] = np.maximum(-e_next, 0.0)
        e_next = np.maximum(e_next, 0.0)
        qb[:, t], curt_h[:, t], spill[:, t] = (q if supply == "replace" else c_t), c_t, dmp
        cvb[:, t] = v_t
        qh_hist[:, t] = qh
        if supply == "replace":
            curt_el[:, t] = fsum(c_t / cop[:, t])
            grid_el[:, t] = fsum(g_t / cop[:, t]) + qh / cop_h[:, t]
        else:
            curt_el[:, t] = fsum(c_t / cop[:, t]) + qh / cop_h[:, t]
            cvh[:, t] = Hh[:, t] - qh
        e = e_next
        e_hist[:, t + 1] = e
    out = {}
    for fm in fms:
        k = fidx[fm.facility_id]
        rows = np.flatnonzero(fb == k)
        r = FacResult.empty(fm.n_basins, nt)
        r.q_basin, r.short, r.spill, r.energy = qb[rows], unmet[rows], spill[rows], e_hist[rows]
        r.q_hall, r.hall_short = qh_hist[k], (Hh[k] - qh_hist[k]) if supply == "replace" else np.zeros(nt)
        r.conv_basin, r.conv_hall = cvb[rows], cvh[k]
        r.grid_el, r.curt_el = grid_el[k], curt_el[k]
        out[fm.facility_id] = r
    return out
