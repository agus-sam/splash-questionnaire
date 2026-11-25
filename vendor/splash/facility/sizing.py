from __future__ import annotations

import logging
import time
import warnings
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from ..config import Settings
from .econ import Econ
from .model import FacilityModel
from .results import FacResult

log = logging.getLogger(__name__)
TAIL_TOL = 0.02


@dataclass
class SizeResult:
    facility_id: int
    facility_name: str
    zone: str
    technology: str
    q_design_kw_th: float
    size_kw_th: float
    size_model_kw_th: float
    size_over_q_design: float
    bound_active: bool
    decision: str
    status: str
    n_windows: int
    model_hours: int
    tail_h_mean: float
    saving_window_eur: float
    annuity_plant_eur: float
    annuity_controller_eur: float
    absorbed_model_mwh_e: float
    annuity_eur_per_kw: float = np.nan
    max_value_eur_per_kw: float = np.nan
    absorbed_rule_mwh_e: float = np.nan
    solve_s: float = 0.0

    def row(self) -> dict:
        d = asdict(self)
        d["absorbed_rule_over_model"] = d["absorbed_rule_mwh_e"] / d["absorbed_model_mwh_e"] if d["absorbed_model_mwh_e"] > 1e-9 else np.nan
        return d


def coast_tail_h(fm: FacilityModel, base_e: np.ndarray, t_end: int, max_tail: int) -> int:
    T = fm.T
    cap = np.array([b.cap_kwh for b in fm.basins])
    e = np.array([b.cap_kwh * b.active[min(t_end + 1, T)] for b in fm.basins])
    tol = TAIL_TOL * max(cap.sum(), 1e-9)
    for k in range(1, max_tail + 1):
        t = t_end + k
        if t >= T:
            return min(k, max_tail)
        a = np.array([b.a_kw[t] for b in fm.basins])
        r = np.array([b.rate[t] for b in fm.basins])
        hi = np.array([b.cap_kwh * b.active[t + 1] for b in fm.basins])
        e = np.minimum(np.maximum(e - (a + r * e), 0.0), hi)
        if np.maximum(e - base_e[:, t + 1], 0.0).sum() <= tol:
            return k
    return max_tail


def make_windows(fm: FacilityModel, avail_kw: np.ndarray, base_e: np.ndarray, tail_h, max_tail: int) -> tuple[list[tuple[int, int]], list[int]]:
    on = np.flatnonzero((avail_kw > 1e-9) & (fm.avail > 1e-9))
    if len(on) == 0:
        return [], []
    cuts = np.flatnonzero(np.diff(on) > 1)
    starts = np.r_[on[0], on[cuts + 1]]
    ends = np.r_[on[cuts], on[-1]]
    wins: list[list[int]] = []
    tails: list[int] = []
    for s0, e0 in zip(starts, ends):
        tail = int(tail_h) if tail_h != "auto" else coast_tail_h(fm, base_e, int(e0), max_tail)
        tails.append(tail)
        end = min(int(e0) + 1 + tail, fm.T)
        if wins and s0 <= wins[-1][1]:
            wins[-1][1] = max(wins[-1][1], end)
        else:
            wins.append([int(s0), end])
    return [(a, b) for a, b in wins], tails


def _solve(fm: FacilityModel, avail_kw: np.ndarray, base: FacResult, econ: Econ, s: Settings, tech: str, k_year: float) -> SizeResult:
    import pyomo.environ as po
    from oemof import solph
    from oemof.solph import buses, flows
    from oemof.solph import components as comp

    cfg = s.facility.optimised_sizing
    fid = fm.facility_id
    t0 = time.time()
    qd = float(fm.design["q_design_kw"])
    pl = econ.plant[tech]

    ann_kw = pl["ann"]
    ctrl_ann = econ.controller["ann"]
    c_conv = econ.conv_eur_per_mwh_th[fid] / 1e3 * k_year
    c_curt = econ.curt_eur_per_mwh_e / 1e3 * k_year
    c_vom = pl["vom"] / 1e3 * k_year
    hours_on = int(np.sum((avail_kw > 1e-9) & (fm.avail > 1e-9)))
    cop_best = max(float(np.max(c)) for c in fm.circuits.values())
    out = dict(
        annuity_eur_per_kw=ann_kw,
        max_value_eur_per_kw=hours_on * max(c_conv - c_curt / cop_best - c_vom, 0.0),
        facility_id=fid,
        facility_name=fm.name,
        zone=fm.zone,
        technology=tech,
        q_design_kw_th=qd,
        size_over_q_design=0.0,
        bound_active=False,
        n_windows=0,
        model_hours=0,
        tail_h_mean=0.0,
        saving_window_eur=0.0,
        annuity_plant_eur=0.0,
        annuity_controller_eur=ctrl_ann,
        absorbed_model_mwh_e=0.0,
    )
    if qd <= 1e-6:
        return SizeResult(size_kw_th=0.0, size_model_kw_th=0.0, decision="no_demand", status="skipped", solve_s=0.0, **out)
    wins, tails = make_windows(fm, avail_kw, base.energy, cfg.tail_h, cfg.max_tail_h)
    if not wins:
        return SizeResult(size_kw_th=0.0, size_model_kw_th=0.0, decision="no_curtailment", status="skipped", solve_s=0.0, **out)

    hours, dummy = [], []
    for a, b in wins:
        hours += [a] + list(range(a, b))
        dummy += [True] + [False] * (b - a)
    hh, is_d = np.array(hours), np.array(dummy)
    N = len(hh)
    live = ~is_d

    def steps(x, fill=0.0):
        x = np.asarray(x, float)
        o = np.full(N, fill)
        o[live] = x[hh[live]]
        return o

    pt_l: list[int] = []
    for w, (a, b) in enumerate(wins):
        pt_l.append(wins[w - 1][1] if w > 0 else a)
        pt_l.extend(range(a, b))
    pt_l.append(wins[-1][1])
    pt = np.array(pt_l)

    ti = pd.date_range("2000-01-01", periods=N + 1, freq="h")
    es = solph.EnergySystem(timeindex=ti, infer_last_interval=False)
    b_el, b_cap = buses.Bus(label="b_el"), buses.Bus(label="b_cap")
    nodes = [b_el, b_cap]
    avail_s = steps(avail_kw)
    curt = comp.Source(label="curt", outputs={b_el: flows.Flow(nominal_capacity=1.0, maximum=avail_s, variable_costs=c_curt)})
    pmax, pmin = cfg.max_size_factor * qd, cfg.min_size_factor * qd
    cap = comp.Source(
        label="cap",
        outputs={b_cap: flows.Flow(nominal_capacity=solph.Investment(ep_costs=ann_kw, minimum=pmin, maximum=pmax), maximum=steps(fm.avail))},
    )
    nodes += [curt, cap]
    conv_nodes, p2h_nodes = [], []

    def consumer(tag, cop, dem_kw, gain_kw, a_s=None):
        bus = buses.Bus(label=f"b_{tag}")
        cv = comp.Converter(
            label=f"p2h_{tag}",
            inputs={b_el: flows.Flow(), b_cap: flows.Flow()},
            outputs={bus: flows.Flow(variable_costs=c_vom)},
            conversion_factors={bus: steps(cop, 1.0), b_cap: steps(cop, 1.0)},
        )
        cs = comp.Source(label=f"conv_{tag}", outputs={bus: flows.Flow(variable_costs=c_conv)})
        nodes.extend([bus, cv, cs])
        p2h_nodes.append((cv, bus))
        conv_nodes.append((cs, bus))
        if np.max(dem_kw) > 0:
            nodes.append(comp.Sink(label=f"dem_{tag}", inputs={bus: flows.Flow(nominal_capacity=1.0, fix=steps(dem_kw))}))
        if gain_kw is not None and np.max(gain_kw) > 0:
            nodes.append(comp.Source(label=f"gain_{tag}", outputs={bus: flows.Flow(nominal_capacity=1.0, fix=steps(gain_kw))}))
        return bus

    for i, b in enumerate(fm.basins):
        net = b.a_kw
        bus = consumer(f"B{i}", fm.cop_basin(i), np.maximum(net, 0.0), np.maximum(-net, 0.0))
        e0 = np.zeros(N)
        for w, (a, _) in enumerate(wins):
            e0[np.flatnonzero(is_d)[w]] = base.energy[i, a]
        if e0.max() > 0:
            nodes.append(comp.Source(label=f"init_B{i}", outputs={bus: flows.Flow(nominal_capacity=1.0, fix=e0)}))
        loss = steps(b.rate, 0.0)
        loss[is_d] = 1.0
        lvl = b.active[pt]
        nodes.append(comp.Sink(label=f"dump_B{i}", inputs={bus: flows.Flow()}))
        nodes.append(
            comp.GenericStorage(
                label=f"sto_B{i}",
                inputs={bus: flows.Flow()},
                outputs={bus: flows.Flow()},
                nominal_capacity=max(b.cap_kwh, 1e-6),
                loss_rate=loss,
                max_storage_level=lvl,
                min_storage_level=0.0,
                initial_storage_level=0.0,
                balanced=False,
            )
        )
    if fm.has_load:
        consumer("hall", fm.cop_load(), fm.load_kw(), None)
    es.add(*nodes)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m = solph.Model(es)
    opt = po.SolverFactory("highs")
    opt.options["time_limit"] = float(cfg.time_limit_s if cfg.time_limit_s is not None else s.solver.time_limit_s)
    res = opt.solve(m, tee=s.solver.verbose)
    cond = str(res.solver.termination_condition).split(".")[-1]
    if cond != "optimal":
        raise RuntimeError(f"facility {fid} {tech}: sizing model returned {cond}")
    p_opt = max(float(next(v.value for k, v in m.InvestmentFlowBlock.invest.items() if k[0] is cap or getattr(k[0], "label", None) == "cap")), 0.0)
    obj = float(po.value(m.objective))
    absorbed = sum(float(m.flow[curt, b_el, t].value) for t in range(N)) / 1e3

    win_h = np.concatenate([np.arange(a, b) for a, b in wins])
    base_cost = float(base.conv_heat[win_h].sum()) * c_conv
    opex = obj - p_opt * ann_kw
    saving = base_cost - opex
    pays = saving > p_opt * ann_kw + ctrl_ann
    if cfg.allow_zero and not pays:
        size, decision = 0.0, "no_investment"
    else:
        size, decision = p_opt, "invest"
    return SizeResult(
        facility_id=fid,
        facility_name=fm.name,
        zone=fm.zone,
        technology=tech,
        q_design_kw_th=qd,
        size_kw_th=size,
        size_model_kw_th=p_opt,
        size_over_q_design=size / qd,
        bound_active=bool(p_opt >= pmax * 0.999 and pmax > 0),
        decision=decision,
        status=cond,
        n_windows=len(wins),
        model_hours=int(live.sum()),
        tail_h_mean=float(np.mean(tails)),
        saving_window_eur=float(saving),
        annuity_plant_eur=float(p_opt * ann_kw),
        annuity_controller_eur=float(ctrl_ann),
        absorbed_model_mwh_e=float(absorbed),
        solve_s=time.time() - t0,
        annuity_eur_per_kw=ann_kw,
        max_value_eur_per_kw=out["max_value_eur_per_kw"],
    )


def size_plants(
    fms: dict[int, FacilityModel],
    base_res: dict[str, dict[int, FacResult]],
    avail: dict[str, np.ndarray],
    econ: Econ,
    s: Settings,
    k_year: float,
    tech: str,
) -> dict[int, SizeResult]:
    out: dict[int, SizeResult] = {}
    t0 = time.time()
    for n, (fid, fm) in enumerate(sorted(fms.items()), start=1):
        out[fid] = _solve(fm, avail[fm.zone], base_res[fm.zone][fid], econ, s, tech, k_year)
        if n % 20 == 0 or n == len(fms):
            log.info("optimised sizing %s: %d of %d facilities (%.0f s)", tech, n, len(fms), time.time() - t0)
    return out


def sizing_table(sz: dict[int, SizeResult]) -> pd.DataFrame:
    return pd.DataFrame([r.row() for r in sz.values()])
