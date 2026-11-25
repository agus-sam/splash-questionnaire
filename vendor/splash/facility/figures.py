from __future__ import annotations

import logging
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

from .. import viz
from ..config import OPT_SIZE
from ..viz import COL, COMP_COLOR, MON
from . import kpis
from .demand import COMPONENTS, DHW, HALL, LATENT, pick_weeks
from .demand_plots import plot_facility as plot_demand_facility
from .demand_plots import plot_region as plot_demand_region
from .model import FacilityModel
from .viz_helpers import pick_samples
from .zone import BASE

log = logging.getLogger(__name__)
SC = ("baseline", "hysteresis_addon", "hysteresis_replace", "hysteresis_optimised")
SC_COL = {"baseline": "#7f7f7f", "hysteresis_addon": "#0072B2", "hysteresis_replace": "#009E73", "hysteresis_optimised": "#E69F00"}
SC_LAB = {
    "baseline": "Baseline: current heating system",
    "hysteresis_addon": "Rule hysteresis, new technology added to the current system",
    "hysteresis_replace": "Rule hysteresis, new technology replaces the current system",
    "hysteresis_optimised": "Rule hysteresis, new technology added to the current system, optimised plant size (oemof, HiGHS)",
}
SC_SHORT = {
    "baseline": "Baseline",
    "hysteresis_addon": "Add-on",
    "hysteresis_replace": "Replacement",
    "hysteresis_optimised": "Add-on, optimised size",
}
TECH_LAB = {"heat_pump": "heat pump", "resistive": "resistive heater", BASE: "current system"}
C_P2H = "#D55E00"
C_BASIN_COL = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00", "#7B3F98", "#999999"]


def _size_label(R, mode) -> str:
    return OPT_SIZE if mode == "hysteresis_optimised" else R["primary"]


def _key(R, tech, mode, zone):
    return (BASE, BASE, zone, "baseline") if mode == "baseline" else (tech, _size_label(R, mode), zone, mode)


def _res(R, tech, mode, fm):
    return R["results"][_key(R, tech, mode, fm.zone)][fm.facility_id]


def _modes(R) -> list[str]:
    return ["baseline", *[m for m in SC[1:] if m in R["modes"]]]


def _sh(R, tech, mode) -> pd.DataFrame:
    return R["sh_hourly"][(BASE, BASE, mode) if mode == "baseline" else (tech, _size_label(R, mode), mode)]


def _rated_kw(R, fm, tech, mode) -> float:
    t = R["tech"]
    return float(t[(t.facility_id == fm.facility_id) & (t.technology == tech) & (t.plant_size == _size_label(R, mode))].p2h_rated_kw_th.iloc[0])


def _fig_dir(R) -> Path:
    return Path(R["out"]) / "figures"


def _ctx(fm) -> str:
    return f"{fm.name} (facility {fm.facility_id}, {fm.badtyp}, zone {fm.zone}, {fm.n_basins} basins)"


def _circ(a: int, b: int) -> int:
    d = abs(a - b)
    return min(d, 12 - d)


def detail_months(absorbed: np.ndarray, avail: np.ndarray, months: np.ndarray) -> list[int]:
    ms = sorted(set(int(m) for m in months))
    if len(ms) <= 2:
        return ms
    ab = pd.Series(absorbed).groupby(months).sum()
    av = pd.Series(avail).groupby(months).sum()
    a = int(ab.idxmax()) if ab.max() > 0 else int(av.idxmax())
    far = [m for m in ms if _circ(m, a) >= 3]
    return sorted([a] + ([int(av.loc[far].idxmax())] if far else []))


def _fac_months(R, fm, tech) -> list[int]:
    ab = sum(_res(R, tech, m, fm).curt_el for m in R["modes"])
    return detail_months(ab, R["avail"][fm.zone], R["months"])


def _x(R, mask):
    return R["tl"].index_local[mask]


def _headline(fig, title: str, sub: str | None = None) -> None:
    fig.suptitle(title, x=0.01, ha="left", fontsize=11.5, fontweight="bold", y=1 - 0.06 / fig.get_figheight())
    if sub:
        fig.text(0.01, 1 - 0.40 / fig.get_figheight(), sub, ha="left", va="top", fontsize=8.5, color="#444444")


def _avail_strip(ax, x, av_kw, zone_label: str, absorbed_kw=None) -> None:
    ax.fill_between(x, av_kw / 1e3, step="post", color=COL["curt"], alpha=0.30, lw=0)
    ax.step(x, av_kw / 1e3, where="post", color=COL["curt"], lw=0.8)
    if absorbed_kw is not None:
        ax.step(x, absorbed_kw / 1e3, where="post", color="black", lw=0.9)
    ax.set_ylabel("MW el", fontsize=8)
    ax.set_title(zone_label, fontsize=8.5, loc="left")


def _fmt(v: float, unit: str = "") -> str:
    a = abs(v)
    t = f"{v:,.0f}" if a >= 100 else (f"{v:,.1f}" if a >= 10 else f"{v:,.2f}")
    return f"{t}{unit}"


def component_kw(fm: FacilityModel) -> pd.DataFrame:
    out = pd.DataFrame(0.0, index=range(fm.T), columns=COMPONENTS)
    for b in fm.basins:
        c = b.phys.components(b.t_min, b.t_air)
        w = b.area_m2 * b.active[:-1]
        if b.environment == "indoor":
            d = {"evaporation": c["evap"], "convection": c["conv"], "radiation": c["rad"], "conduction": c["cond"], "make-up water": c["renov"]}
        else:
            d = {"evaporation": c["eva"], "convection": c["conv"], "radiation": c["rad"], "make-up water": c["re"], "solar gain": -c["sun"]}
        for k, v in d.items():
            out[k] += np.nan_to_num(np.asarray(v, float)) * w
    return out


def demand_dict(R, fm: FacilityModel) -> dict:
    idx = R["tl"].index_local
    df = component_kw(fm)
    if not np.allclose(df.sum(axis=1).to_numpy(), np.sum([b.a_kw for b in fm.basins], axis=0), atol=1e-4):
        log.warning("facility %d: loss components do not add up to the basin loss of the model", fm.facility_id)
    df.index = idx
    df["basins"] = df[COMPONENTS].sum(axis=1)
    df[HALL] = fm.hall_kw()
    df[DHW] = fm.dhw_kw()
    df[LATENT] = fm.hall.latent_diag_kw if fm.hall is not None else 0.0
    df["total"] = df["basins"] + df[HALL] + df[DHW]
    t_out = pd.Series(fm.t_ext, index=idx)
    active = np.any([b.active[:-1] > 0 for b in fm.basins], axis=0)
    hall = {"A": {"id": fm.hall.hall_id, "t_air_c": fm.hall.t_air_c, "water_area_m2": fm.hall.area_m2}} if fm.hall is not None else None
    return {
        "facility_id": fm.facility_id,
        "name": fm.name,
        "badtyp": fm.badtyp,
        "zone": fm.zone,
        "n_basins": fm.n_basins,
        "n_indoor": sum(b.environment == "indoor" for b in fm.basins),
        "n_outdoor": sum(b.environment == "outdoor" for b in fm.basins),
        "water_area_m2": sum(b.area_m2 for b in fm.basins),
        "scenarios": ["A"],
        "hourly": {"A": df},
        "hall": hall,
        "t_out": t_out,
        "weeks": pick_weeks(fm.t_ext, active, idx),
        "index": idx,
    }


def fig_demand(R, fm) -> Path:
    p = viz.fac_path(_fig_dir(R), fm.facility_id, fm.name, "D", "demand")
    plot_demand_facility(demand_dict(R, fm), p, R["settings"].output.dpi)
    return p


def fig_demand_profile(R, fm) -> Path:
    idx = R["tl"].index_local
    fig, ax = plt.subplots(2, 1, figsize=(14, 7), sharex=True)
    for b in fm.basins:
        ax[0].plot(idx, b.demand_kw(), lw=0.4, label=f"B{b.basin_id} {b.size_class} ({b.environment})")
    ax[0].set(ylabel="kW thermal", title="Individual basin heat demand at T_min")
    ax[0].legend(fontsize=6, ncol=3)
    ax[1].plot(idx, fm.basin_demand_kw(), lw=0.5, color="#0072B2", label="total basins")
    ax[1].plot(idx, fm.hall_kw(), lw=0.5, color=COMP_COLOR[HALL], label="hall sensible heating")
    ax[1].plot(idx, fm.total_demand_kw(), lw=0.5, color="black", label="facility total")
    ax[1].set(
        ylabel="kW thermal", title="Facility demand: basins + hall sensible (latent evaporation heat is inside the basin loss, not added again)"
    )
    ax[1].legend(fontsize=7)
    ax[1].xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    fig.suptitle(f"Hourly thermal demand of the year: {_ctx(fm)}", fontsize=10, fontweight="bold")
    p = viz.fac_path(_fig_dir(R), fm.facility_id, fm.name, "D", "demand_profile")
    viz.save(fig, p, R["settings"].output.dpi)
    return p


def fig_sizing(R, fm) -> Path:
    from ..config import HP_SCENARIOS

    fig, ax = plt.subplots(1, 3, figsize=(15, 4.6))
    names = [f"B{b.basin_id}\n{b.size_class[:10]}\n{b.environment[:3]}" for b in fm.basins]
    col = ["#0072B2" if b.environment == "indoor" else "#009E73" for b in fm.basins]
    ax[0].bar(names, [b.volume_m3 for b in fm.basins], color=col)
    ax[0].set(title="Basins: water volume", ylabel="m³")
    ax[0].tick_params(axis="x", labelsize=7)
    ax[0].text(
        0.98,
        0.95,
        f"total {sum(b.volume_m3 for b in fm.basins):,.0f} m³\n{sum(b.area_m2 for b in fm.basins):,.0f} m² surface\nblue indoor, green outdoor",
        transform=ax[0].transAxes,
        ha="right",
        va="top",
        fontsize=8,
    )
    d = fm.design
    ax[1].bar(["Q_design"], [d["q_design_basins_kw"]], color="#0072B2", label="basins (at design hour)")
    ax[1].bar(["Q_design"], [d["q_design_hall_kw"]], bottom=[d["q_design_basins_kw"]], color=COMP_COLOR[HALL], label="hall sensible")
    if d.get("q_design_dhw_kw", 0.0) > 0.0:
        ax[1].bar(["Q_design"], [d["q_design_dhw_kw"]], bottom=[d["q_design_basins_kw"] + d["q_design_hall_kw"]], color=DHW_COLOR, label="hot water (showers)")
    if any(m != "hysteresis_optimised" for m in R["modes"]):
        for scn in R["settings"].facility.sizing.scenarios:
            ax[1].bar([f"plant {scn}"], [HP_SCENARIOS[scn] * d["q_design_kw"]], color=C_P2H)
    if "hysteresis_optimised" in R["modes"]:
        for tch in R["technologies"]:
            ax[1].bar([f"optimised\n{TECH_LAB[tch]}"], [_rated_kw(R, fm, tch, "hysteresis_optimised")], color=SC_COL["hysteresis_optimised"])
    ax[1].set(title="Rated thermal capacity of the new plant (heat pump or resistive)", ylabel="kW thermal")
    ax[1].legend(fontsize=7)
    hd = fm.hall_kw().sum() / 1e3
    labels = [f"B{b.basin_id}" for b in fm.basins] + (["hall"] if fm.hall else []) + (["hot water"] if fm.dhw is not None else [])
    vals = [b.demand_kw().sum() / 1e3 for b in fm.basins] + ([hd] if fm.hall else []) + ([fm.dhw_kw().sum() / 1e3] if fm.dhw is not None else [])
    ax[2].barh(labels, vals, color=col + ([COMP_COLOR[HALL]] if fm.hall else []) + ([DHW_COLOR] if fm.dhw is not None else []))
    ax[2].set(title="Annual heat demand at T_min set point", xlabel="MWh thermal")
    sink = ", ".join(f"{k} {v:.0f} °C" for k, v in fm.flags["circuit_sink_c"].items())
    el = []
    psz = R["primary"] if any(m != "hysteresis_optimised" for m in R["modes"]) else OPT_SIZE
    for t in R["technologies"]:
        row = R["tech"][(R["tech"].facility_id == fm.facility_id) & (R["tech"].technology == t) & (R["tech"].plant_size == psz)].iloc[0]
        el.append(f"{TECH_LAB[t]}: design COP {row.cop_design:.2f}, electrical input {row.p2h_el_capacity_kw_e:,.0f} kW")
    fig.suptitle(
        f"Facility characteristics and plant sizing: {_ctx(fm)}\nQ_design {d['q_design_kw']:.0f} kWth ({d['method']}), sink temperatures: {sink}; "
        + "; ".join(el),
        fontsize=9,
        fontweight="bold",
    )
    p = viz.fac_path(_fig_dir(R), fm.facility_id, fm.name, "D", "plant_sizing")
    viz.save(fig, p, R["settings"].output.dpi, bottom=0.03)
    return p


DHW_COLOR = COMP_COLOR[DHW]


def _demand_layers(fm, sel):
    """Layers of the demand stack: basins, hall air and, if switched on, hot water for bathers."""
    lay = [fm.basin_demand_kw()[sel], fm.hall_kw()[sel]]
    col = ["#0072B2", COMP_COLOR[HALL]]
    lab = ["basins", "hall sensible"]
    if fm.dhw is not None:
        lay.append(fm.dhw_kw()[sel])
        col.append(DHW_COLOR)
        lab.append("hot water (showers)")
    return lay, col, lab


def fig_heat_supply_cold_warm(R, fm, tech) -> Path:
    flags = R["flags"][(fm.facility_id, tech)]
    mt = R["monthly"][(fm.facility_id, tech)]
    modes = _modes(R)
    nrow = 1 + 2 * (len(modes) - 1) + 1
    fig, ax = plt.subplots(nrow, 2, figsize=(15, 2.0 * nrow + 1), sharey="row")
    for j, (m, lab) in enumerate(((flags["coldest_month"], "coldest"), (flags["warmest_month"], "warmest"))):
        msk = R["months"] == m
        x = _x(R, msk)
        lay, col, lab = _demand_layers(fm, msk)
        ax[0, j].stackplot(x, *lay, colors=col, labels=lab)
        ax[0, j].set_title(f"{lab} month {MON[m - 1]} (mean {mt.loc[m, 't_ext_mean_c']:.1f} °C): heat demand at T_min")
        k = 1
        for mode in modes[1:]:
            r = _res(R, tech, mode, fm)
            ax[k, j].stackplot(x, r.conv_heat[msk], r.p2h_heat[msk], colors=[COL["conv"], C_P2H], labels=["current system", TECH_LAB[tech]])
            ax[k, j].set_title(f"{SC_SHORT[mode]}: heat supply", fontsize=9)
            ax[k + 1, j].stackplot(x, r.grid_el[msk], r.curt_el[msk], colors=[COL["grid"], COL["curt"]], labels=["grid", "curtailed"])
            ax[k + 1, j].set_title(f"{SC_SHORT[mode]}: electricity of the {TECH_LAB[tech]}", fontsize=9)
            k += 2
        ax[-1, j].fill_between(x, R["avail"][fm.zone][msk] / 1e3, step="mid", color=COL["curt"], alpha=0.4)
        ax[-1, j].set_title(f"Curtailed power available in zone {fm.zone} (MW electric)", fontsize=9)
        for a in ax[:, j]:
            a.xaxis.set_major_formatter(mdates.DateFormatter("%d"))
    for k in range(nrow - 1):
        ax[k, 0].set_ylabel("kW")
    ax[-1, 0].set_ylabel("MW")
    for k in range(min(nrow - 1, 4)):
        ax[k, 0].legend(fontsize=7)
    fig.suptitle(f"Coldest vs warmest month, {TECH_LAB[tech]}: {_ctx(fm)}", fontsize=10, fontweight="bold")
    p = viz.fac_path(_fig_dir(R), fm.facility_id, fm.name, "O", f"cold_vs_warm_{tech}")
    viz.save(fig, p, R["settings"].output.dpi)
    return p


def fig_absorption(R, fm, tech) -> Path:
    ms = _fac_months(R, fm, tech)
    modes = _modes(R)[1:]
    n = len(ms)
    nr = 1 + 2 * len(modes)
    fig = plt.figure(figsize=(5.4 * n + 3.8, 1.9 * nr + 1.6))
    gs = fig.add_gridspec(nr, n + 1, width_ratios=[1.0] * n + [0.75], height_ratios=[0.8] + [1.2, 0.9] * len(modes))
    for k, m in enumerate(ms):
        msk = R["months"] == m
        x = _x(R, msk)
        a0 = fig.add_subplot(gs[0, k])
        first = a0
        _avail_strip(a0, x, R["avail"][fm.zone][msk], f"{MON[m - 1]}: curtailed power available in zone {fm.zone}")
        for q, mode in enumerate(modes):
            r = _res(R, tech, mode, fm)
            ax = fig.add_subplot(gs[1 + 2 * q, k], sharex=first)
            ax.stackplot(
                x,
                r.curt_el[msk] / 1e3,
                r.grid_el[msk] / 1e3,
                colors=[COL["curt"], COL["grid"]],
                step="post",
                alpha=0.95,
                labels=["from curtailed power", "from the grid"],
            )
            ax.set_ylabel("MW el", fontsize=8)
            ax.set_title(f"{SC_SHORT[mode]}: electricity of the facility", fontsize=8.5, loc="left")
            bx = fig.add_subplot(gs[2 + 2 * q, k], sharex=first)
            bx.axhspan(0, 1, color=COL["band"], alpha=0.07)
            for j, b in enumerate(fm.basins):
                soc = np.clip(r.energy[j, :-1] / max(b.cap_kwh, 1e-9), 0, 1)
                soc = np.where(b.active[:-1] > 0, soc, np.nan)
                bx.plot(x, soc[msk], color=C_BASIN_COL[j % 8], lw=0.9, label=f"B{b.basin_id} {b.size_class[:10]}" if k == 0 and q == 0 else None)
            bx.set_ylim(-0.05, 1.05)
            bx.set_ylabel("State of charge", fontsize=8)
            if q == len(modes) - 1:
                bx.set_xlabel(f"Day of {MON[m - 1]}")
            else:
                bx.tick_params(labelbottom=False)
            ax.tick_params(labelbottom=False)
            if k == 0 and q == 0:
                ax.legend(fontsize=7, loc="upper left", ncol=2)
                bx.legend(fontsize=6.5, loc="upper left", ncol=3)
        a0.tick_params(labelbottom=False)
    for a in fig.axes:
        a.xaxis.set_major_formatter(mdates.DateFormatter("%d"))
    ax = fig.add_subplot(gs[:, n])
    tot = []
    for q, mode in enumerate(modes):
        r = _res(R, tech, mode, fm)
        g, c = r.grid_el.sum() / 1e3, r.curt_el.sum() / 1e3
        tot.append((mode, g, c))
        ax.barh(q, c, 0.55, color=COL["curt"], label="curtailed" if q == 0 else None)
        ax.barh(q, g, 0.55, left=c, color=COL["grid"], label="grid" if q == 0 else None)
        ax.text(c + g, q, f" {_fmt(c + g)} MWh, {100 * c / max(g + c, 1e-9):.1f} % curtailed", va="center", fontsize=7.5)
    ax.set_yticks(range(len(modes)))
    ax.set_yticklabels([SC_SHORT[m] for m in modes])
    ax.invert_yaxis()
    ax.set_xlim(0, max(g + c for _, g, c in tot) * 1.9 + 1e-6)
    ax.set_xlabel("Electricity of the period (MWh el)")
    ax.set_title("Period total", fontsize=9, loc="left")
    ax.legend(fontsize=7, loc="lower right")
    _headline(
        fig,
        f"Absorption of curtailed electricity, {TECH_LAB[tech]}: {_ctx(fm)}",
        "Per scenario: electricity of the plant and state of charge of each basin; the strip on top shows when curtailed power exists",
    )
    fig.tight_layout(rect=(0, 0.03, 1, 0.94))
    p = viz.fac_path(_fig_dir(R), fm.facility_id, fm.name, "O", f"absorption_{tech}")
    viz.save(fig, p, R["settings"].output.dpi, tight=False)
    return p


def fig_monthly_energy(R, fm, tech) -> Path:
    modes = _modes(R)
    ms = sorted(set(int(m) for m in R["months"]))
    mo = np.asarray(R["months"])
    fig, ax = plt.subplots(2, len(modes), figsize=(4.0 * len(modes) + 1.2, 6.2), sharex=True, squeeze=False)
    xs = np.arange(len(ms))
    top = 0.0
    for r_ in range(len(modes)):
        pass
    heat = {}
    for mode in modes:
        r = _res(R, tech, mode, fm)
        heat[mode] = (
            np.array([r.conv_heat[mo == m].sum() / 1e3 for m in ms]),
            np.array([(r.q_basin.sum(axis=0) + r.q_hall)[mo == m].sum() / 1e3 for m in ms]),
            r,
        )
        top = max(top, float((heat[mode][0] + heat[mode][1]).max()))
    ab_top = max([float(np.max([heat[m][2].curt_el[mo == q].sum() / 1e3 for q in ms])) for m in modes[1:]] + [1e-6])
    for c, mode in enumerate(modes):
        conv, p2h, r = heat[mode]
        ax[0, c].bar(xs, conv, 0.75, color=COL["conv"], label="current system")
        ax[0, c].bar(xs, p2h, 0.75, bottom=conv, color=C_P2H, label=TECH_LAB[tech])
        ax[0, c].set_ylim(0, top * 1.1)
        ax[0, c].set_title(SC_SHORT[mode], fontsize=9.5, loc="left")
        if mode == "baseline":
            ax[1, c].text(0.5, 0.5, "no curtailed power used", transform=ax[1, c].transAxes, ha="center", color="#777777")
        else:
            ax[1, c].bar(xs, [r.curt_el[mo == m].sum() / 1e3 for m in ms], 0.75, color=SC_COL[mode])
            ax[1, c].set_ylim(0, ab_top * 1.1)
        ax[1, c].set_xticks(xs)
        ax[1, c].set_xticklabels([MON[m - 1][:1] for m in ms])
    ax[0, 0].set_ylabel("Heat (MWh th per month)")
    ax[1, 0].set_ylabel("Curtailed electricity absorbed\n(MWh el per month)")
    ax[0, 1 if len(modes) > 1 else 0].legend(fontsize=7.5, loc="upper right")
    tot_abs = {m: heat[m][2].curt_el.sum() / 1e3 for m in modes[1:]}
    sub = "; ".join(f"{SC_SHORT[m]} absorbs {_fmt(v)} MWh el" for m, v in tot_abs.items())
    _headline(fig, f"Monthly heat by source and curtailed electricity absorbed, {TECH_LAB[tech]}: {_ctx(fm)}", sub)
    fig.tight_layout(rect=(0, 0.03, 1, 0.89))
    p = viz.fac_path(_fig_dir(R), fm.facility_id, fm.name, "O", f"monthly_energy_{tech}")
    viz.save(fig, p, R["settings"].output.dpi, tight=False)
    return p


def _heatmap(ax, soc, loc, title, cmap="Blues"):
    df = pd.DataFrame({"soc": soc, "date": loc.date, "hour": loc.hour})
    pv = df.pivot_table(index="hour", columns="date", values="soc", aggfunc="first")
    dates = pd.to_datetime(pv.columns)
    x0, x1 = mdates.date2num(dates[0]), mdates.date2num(dates[-1]) + 1
    im = ax.imshow(pv.values, aspect="auto", origin="lower", cmap=cmap, vmin=0, vmax=1, extent=[x0, x1, -0.5, 23.5], interpolation="nearest")
    ax.xaxis_date()
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    ax.set_yticks([0, 6, 12, 18, 23])
    ax.set_ylabel("Hour of day")
    ax.grid(False)
    ax.set_title(title, fontsize=9, loc="left")
    return im


def fig_load_soc(R, fm, tech) -> Path:
    modes = _modes(R)[1:]
    j = int(np.argmax([b.area_m2 * b.active[:-1].mean() for b in fm.basins]))
    b = fm.basins[j]
    loc = R["tl"].index_local
    fig = plt.figure(figsize=(14, 2.4 * len(modes) + 1.6))
    gs = fig.add_gridspec(len(modes), 2, width_ratios=[1.0, 1.7], right=0.9)
    ax = fig.add_subplot(gs[:, 0])
    for mode in modes:
        r = _res(R, tech, mode, fm)
        h = np.sort(r.p2h_heat)[::-1]
        nz = int((h > 1e-6).sum())
        ax.plot(np.arange(len(h)), h, color=SC_COL[mode], lw=1.6, label=f"{SC_SHORT[mode]}: {nz:,} h in use")
        ax.axhline(_rated_kw(R, fm, tech, mode), color=SC_COL[mode], ls=":", lw=1.0)
    ax.plot([], [], color="#777777", ls=":", lw=1.0, label="rated capacity (dotted)")
    ax.set(xlabel="Hours of the period, sorted", ylabel="Thermal output (kW th)")
    ax.set_title(f"Load duration of the {TECH_LAB[tech]}", fontsize=9, loc="left")
    ax.legend(fontsize=7.5)
    im = None
    for q, mode in enumerate(modes):
        r = _res(R, tech, mode, fm)
        soc = np.clip(r.energy[j, :-1] / max(b.cap_kwh, 1e-9), 0, 1)
        soc = np.where(b.active[:-1] > 0, soc, np.nan)
        a2 = fig.add_subplot(gs[q, 1])
        im = _heatmap(a2, soc, loc, f"{SC_SHORT[mode]}: state of charge of B{b.basin_id} ({b.size_class}), whole period")
    cax = fig.add_axes([0.92, 0.18, 0.012, 0.6])
    fig.colorbar(im, cax=cax, label="State of charge (share of band)")
    _headline(
        fig,
        f"Plant load and state of charge, {TECH_LAB[tech]}: {_ctx(fm)}",
        "Dark = basin charged up to T_max, light = at T_min; white = basin not in operation",
    )
    fig.subplots_adjust(top=0.88, bottom=0.12, left=0.06, hspace=0.45, wspace=0.18)
    p = viz.fac_path(_fig_dir(R), fm.facility_id, fm.name, "O", f"load_duration_soc_{tech}")
    viz.save(fig, p, R["settings"].output.dpi, tight=False)
    return p


def _env_temp(fm, r, env, sl):
    idx = [i for i, b in enumerate(fm.basins) if b.environment == env]
    if not idx:
        return None
    w = np.array([fm.basins[i].area_m2 * fm.basins[i].active[:-1][sl] for i in idx])
    t = np.array([fm.basins[i].temp_c(r.energy[i, :-1])[sl] for i in idx])
    t = np.nan_to_num(t)
    den = np.maximum(w.sum(axis=0), 1e-9)
    on = w.sum(axis=0) > 1e-9

    def f(x):
        return np.where(on, x, np.nan)

    lo = f((w * np.array([fm.basins[i].t_min for i in idx])[:, None]).sum(axis=0) / den)
    hi = f((w * np.array([fm.basins[i].t_max for i in idx])[:, None]).sum(axis=0) / den)
    return f((w * t).sum(axis=0) / den), lo, hi


def fig_thermal(R, fm, tech) -> Path:
    ms = _fac_months(R, fm, tech)
    envs = [e for e in ("indoor", "outdoor") if any(b.environment == e for b in fm.basins)]
    rows = 1 + len(envs) + 1
    fig, ax = plt.subplots(rows, len(ms), figsize=(5.6 * len(ms) + 1.5, 2.1 * rows + 1.2), sharex="col", squeeze=False)
    for c, m in enumerate(ms):
        msk = R["months"] == m
        sl = np.flatnonzero(msk)
        sl = slice(sl[0], sl[-1] + 1)
        x = _x(R, msk)
        ax[0, c].plot(x, fm.t_ext[msk], color=COL["temp"], label="Outdoor air")
        if fm.hall is not None:
            ax[0, c].axhline(fm.hall.t_air_c, color="black", ls=":", lw=1.1, label="Hall air (fixed)")
        ax[0, c].set_title(MON[m - 1], fontsize=9)
        for r_i, env in enumerate(envs, start=1):
            for mode in _modes(R):
                tt = _env_temp(fm, _res(R, tech, mode, fm), env, sl)
                ax[r_i, c].plot(
                    x,
                    tt[0],
                    color=SC_COL[mode],
                    lw={"baseline": 1.0, "hysteresis_addon": 3.2, "hysteresis_replace": 1.2, "hysteresis_optimised": 1.0}[mode],
                    alpha=0.55 if mode == "hysteresis_addon" else 1.0,
                    ls="--" if mode == "baseline" else "-",
                    label=SC_SHORT[mode] if c == 0 else None,
                )
            ax[r_i, c].fill_between(x, tt[1], tt[2], color=COL["band"], alpha=0.12, label="Allowed band" if c == 0 else None)
            ax[r_i, c].set_ylabel(f"{env.capitalize()} water (°C)")
        ax[-1, c].fill_between(x, R["avail"][fm.zone][msk] / 1e3, step="mid", color=COL["curt"], alpha=0.4)
        ax[-1, c].set_ylabel(f"Zone {fm.zone} curtailment (MW el)")
        ax[-1, c].xaxis.set_major_formatter(mdates.DateFormatter("%d"))
        ax[-1, c].set_xlabel("Day")
    ax[0, 0].set_ylabel("Air (°C)")
    ax[0, 0].legend(fontsize=7)
    ax[1, 0].legend(fontsize=7, ncol=2)
    fig.suptitle(
        f"Thermal state, {TECH_LAB[tech]}: {_ctx(fm)}\nArea weighted water temperature of the basins; baseline holds T_min. All hysteresis scenarios follow the same charging rule; they differ in plant size and supply, so their water temperatures coincide where the plant is large enough (add-on drawn wide underneath)",
        fontsize=10,
        fontweight="bold",
    )
    p = viz.fac_path(_fig_dir(R), fm.facility_id, fm.name, "T", f"thermal_{tech}")
    viz.save(fig, p, R["settings"].output.dpi)
    return p


def fig_trajectories(R, fm, tech) -> Path:
    m = _fac_months(R, fm, tech)[0]
    msk = R["months"] == m
    x = _x(R, msk)
    modes = _modes(R)[1:]
    nb = fm.n_basins
    show = list(range(nb)) if nb <= 6 else sorted(np.argsort([-b.volume_m3 for b in fm.basins])[:6])
    fig, ax = plt.subplots(len(show), len(modes), figsize=(7 * len(modes), 1.9 * len(show) + 1.4), sharex=True, squeeze=False)
    for c, mode in enumerate(modes):
        r = _res(R, tech, mode, fm)
        on = r.curt_el[msk] > 1e-6
        for k, i in enumerate(show):
            b = fm.basins[i]
            a = ax[k, c]
            a.plot(x, b.temp_c(r.energy[i, :-1])[msk], color=SC_COL[mode], lw=1)
            a.axhline(b.t_min, color=COL["band"], ls="--", lw=0.8)
            a.axhline(b.t_max, color=COL["band"], ls="--", lw=0.8)
            a.fill_between(x, b.t_min, b.t_max, where=on, color=COL["curt"], alpha=0.2, step="mid")
            a.set_ylabel("°C", fontsize=7)
            a.set_title(
                f"{SC_SHORT[mode]}: B{b.basin_id} {b.size_class} ({b.environment}) band {b.t_min:.0f}-{b.t_max:.0f} °C", fontsize=8, loc="left"
            )
        ax[-1, c].xaxis.set_major_formatter(mdates.DateFormatter("%d"))
    note = "" if nb <= 6 else f" ({len(show)} largest of {nb} basins)"
    fig.suptitle(
        f"Basin temperature trajectories, {MON[m - 1]}, {TECH_LAB[tech]}{note}, orange: hours with curtailed power absorbed: {_ctx(fm)}",
        fontsize=9.5,
        fontweight="bold",
    )
    p = viz.fac_path(_fig_dir(R), fm.facility_id, fm.name, "T", f"trajectories_{tech}")
    viz.save(fig, p, R["settings"].output.dpi)
    return p


def _kpi_grid(tab: pd.DataFrame, title: str, path: Path, dpi: int, sub: str) -> Path:
    tab = tab.copy()
    tab["label"] = tab.apply(lambda r: SC_SHORT[r["mode"]] + ("" if r["technology"] == BASE else f" ({TECH_LAB[r['technology']]})"), axis=1)
    tab = tab.sort_values(["mode", "technology"], key=lambda s_: s_.map({m: i for i, m in enumerate(SC)}) if s_.name == "mode" else s_).reset_index(
        drop=True
    )
    y = np.arange(len(tab))
    base = tab[tab["mode"] == "baseline"].iloc[0]
    has_eco = "cost_total_eur_a" in tab
    panels = [
        ("heat", "Heat by source (MWh th)"),
        ("el", "Electricity of the new technology (MWh el)"),
        ("abs", "Curtailed electricity absorbed (MWh el)"),
    ]
    if has_eco:
        panels += [("cost", "Annual cost incl. plant annuity (k€)"), ("co2", "CO2 of the heat supply (t)")]
    fig, ax = plt.subplots(1, len(panels), figsize=(3.6 * len(panels) + 2.2, 0.62 * len(tab) + 2.6), sharey=True)
    for a, (k, ttl) in zip(ax, panels):
        a.set_title(ttl, fontsize=9, loc="left")
        a.grid(axis="y", visible=False)
        if k == "heat":
            a.barh(y, tab.conv_heat_mwh_th, 0.6, color=COL["conv"], label="current system")
            a.barh(y, tab.p2h_heat_mwh_th, 0.6, left=tab.conv_heat_mwh_th, color=C_P2H, label="new technology")
            tot = tab.conv_heat_mwh_th + tab.p2h_heat_mwh_th
            a.legend(fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.08), ncol=2)
        elif k == "el":
            a.barh(y, tab.absorbed_mwh_e, 0.6, color=COL["curt"], label="curtailed")
            a.barh(y, tab.grid_el_mwh_e, 0.6, left=tab.absorbed_mwh_e, color=COL["grid"], label="grid")
            tot = tab.absorbed_mwh_e + tab.grid_el_mwh_e
            a.legend(fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.08), ncol=2)
        elif k == "abs":
            a.barh(y, tab.absorbed_mwh_e, 0.6, color=[SC_COL[m] for m in tab["mode"]])
            tot = tab.absorbed_mwh_e
        elif k == "cost":
            tot = tab.cost_total_eur_a / 1e3
            a.barh(y, tot, 0.6, color=[SC_COL[m] for m in tab["mode"]])
        else:
            tot = tab.co2_t_a
            a.barh(y, tot, 0.6, color=[SC_COL[m] for m in tab["mode"]])
        mx = max(float(np.max(tot)), 1e-9)
        for yi, v in zip(y, tot):
            txt = _fmt(float(v))
            if k in ("cost", "co2"):
                b0 = float(base.cost_total_eur_a / 1e3 if k == "cost" else base.co2_t_a)
                if abs(b0) > 1e-9 and yi != 0 and tab.loc[yi, "mode"] != "baseline":
                    txt += f" ({100 * (v - b0) / abs(b0):+.1f} %)"
            a.text(v + mx * 0.01, yi, txt, va="center", fontsize=7.5)
        a.set_xlim(0, mx * 1.45)
        if k in ("cost", "co2"):
            a.set_xlim(0, mx * 1.6)
    ax[0].set_yticks(y)
    ax[0].set_yticklabels(tab.label, fontsize=8.5)
    ax[0].invert_yaxis()
    _headline(fig, title, sub)
    fig.tight_layout(rect=(0, 0.03, 1, 0.89))
    viz.save(fig, path, dpi, tight=False)
    return path


def fig_compare(R, fm) -> Path:
    f = R["flex"]
    tab = f[(f.facility_id == fm.facility_id) & f.plant_size.isin([R["primary"], BASE, OPT_SIZE])]
    p = viz.fac_path(_fig_dir(R), fm.facility_id, fm.name, "C", "scenario_comparison")
    return _kpi_grid(
        tab,
        f"Scenario comparison, period totals (cost and CO2 annualised): {_ctx(fm)}",
        p,
        R["settings"].output.dpi,
        "Baseline = current heating system. Economics: synthetic prices of the data package, indicative only",
    )


def _fm_tab(R) -> pd.DataFrame:
    rows = []
    for fm in R["fms"].values():
        for b in fm.basins:
            rows.append({"badtyp": fm.badtyp, "zone": fm.zone, "environment": b.environment})
    return pd.DataFrame(rows)


def fig_sh_demand(R) -> Path:
    mo = np.asarray(R["months"])
    cat = {"indoor basins": np.zeros(R["tl"].n), "outdoor basins": np.zeros(R["tl"].n), HALL: np.zeros(R["tl"].n), DHW: np.zeros(R["tl"].n)}
    rows = []
    for fm in R["fms"].values():
        for b in fm.basins:
            cat["indoor basins" if b.environment == "indoor" else "outdoor basins"] += b.demand_kw()
        cat[HALL] += fm.hall_kw()
        cat[DHW] += fm.dhw_kw()
        rows.append(
            {
                "badtyp": fm.badtyp,
                "zone": fm.zone,
                "basins_mwh": fm.basin_demand_kw().sum() / 1e3,
                "hall_mwh": fm.hall_kw().sum() / 1e3,
                "dhw_mwh": fm.dhw_kw().sum() / 1e3,
            }
        )
    monthly = pd.DataFrame(cat).groupby(mo).sum() / 1e3
    avail = sum(R["avail"].values())
    monthly["curtailed available (MWh el)"] = pd.Series(avail).groupby(mo).sum() / 1e3
    r = pd.DataFrame(rows)
    by_type = r.groupby("badtyp").agg(basins_mwh=("basins_mwh", "sum"), hall_sensible_mwh=("hall_mwh", "sum"), dhw_mwh=("dhw_mwh", "sum")).reset_index()
    by_type["total_mwh"] = by_type.basins_mwh + by_type.hall_sensible_mwh + by_type.dhw_mwh
    by_zone = r.groupby("zone").agg(basins_mwh=("basins_mwh", "sum"), hall_mwh=("hall_mwh", "sum"), dhw_mwh=("dhw_mwh", "sum")).reset_index()
    by_zone["total_mwh"] = by_zone.basins_mwh + by_zone.hall_mwh + by_zone.dhw_mwh
    by_zone["curtailed_available_mwh_el"] = [R["avail"][z].sum() / 1e3 for z in by_zone.zone]
    p = viz.sh_path(_fig_dir(R), "D", 1, "demand_overview")
    plot_demand_region(
        {"monthly": monthly, "by_type": by_type, "by_zone": by_zone, "hours": R["tl"].n, "hall_scenario": "A"}, p, R["settings"].output.dpi
    )
    return p


def _sh_window(R, tech) -> tuple[int, slice]:
    ab = sum(_sh(R, tech, m)["absorbed_kw_e"].to_numpy() for m in R["modes"])
    av = sum(R["avail"].values())
    m = detail_months(ab, av, R["months"])[0]
    return m, slice(0, 0)


def fig_sh_dispatch(R, tech, n: int, month: int) -> Path:
    modes = _modes(R)
    msk = R["months"] == month
    x = _x(R, msk)
    av = sum(R["avail"].values())[msk]
    fig, ax = plt.subplots(
        1 + len(modes), 1, figsize=(13, 2.2 * len(modes) + 2.4), sharex=True, gridspec_kw={"height_ratios": [0.8] + [1.2] * len(modes)}
    )
    best = _modes(R)[1:]
    _avail_strip(
        ax[0], x, av, "Curtailed power available in Schleswig-Holstein (shaded) and absorbed by the heaters, all scenarios of this technology (lines)"
    )
    for mode in best:
        ax[0].step(x, _sh(R, tech, mode)["absorbed_kw_e"].to_numpy()[msk] / 1e3, where="post", color=SC_COL[mode], lw=1.0)
    top = max(float((_sh(R, tech, m)["conv_heat_kw_th"] + _sh(R, tech, m)["p2h_heat_kw_th"]).to_numpy()[msk].max()) for m in modes) / 1e3
    for k, mode in enumerate(modes, start=1):
        d = _sh(R, tech, mode)
        ax[k].stackplot(
            x,
            d["conv_heat_kw_th"].to_numpy()[msk] / 1e3,
            d["p2h_heat_kw_th"].to_numpy()[msk] / 1e3,
            colors=[COL["conv"], C_P2H],
            step="post",
            alpha=0.95,
            labels=["current system", TECH_LAB[tech]],
        )
        ax[k].set_ylim(0, top * 1.12)
        ax[k].set_ylabel("MW th")
        ax[k].set_title(SC_SHORT[mode], fontsize=9, loc="left", color=SC_COL[mode] if mode != "baseline" else "#444444")
    ax[1].legend(fontsize=7.5, ncol=2, loc="upper right")
    ax[-1].xaxis.set_major_formatter(mdates.DateFormatter("%d"))
    ax[-1].set_xlabel(f"Day of {MON[month - 1]}")
    _headline(
        fig,
        f"Schleswig-Holstein, heat supply in {MON[month - 1]}, {TECH_LAB[tech]}",
        f"All {len(R['fms'])} facilities of the run; month with the most absorbed curtailed power",
    )
    fig.tight_layout(rect=(0, 0.02, 1, 0.94))
    p = viz.sh_path(_fig_dir(R), "O", 2, "dispatch", f"_{tech}_m{month:02d}")
    viz.save(fig, p, R["settings"].output.dpi, tight=False)
    return p


def fig_sh_monthly(R) -> Path:
    modes = _modes(R)
    mo = np.asarray(R["months"])
    ms = sorted(set(int(m) for m in mo))
    techs = R["technologies"]
    fig, ax = plt.subplots(len(techs), len(modes), figsize=(3.6 * len(modes) + 1.0, 3.2 * len(techs) + 1.4), sharex=True, sharey=True, squeeze=False)
    xs = np.arange(len(ms))
    for c, tech in enumerate(techs):
        for k, mode in enumerate(modes):
            d = _sh(R, tech, mode)
            conv = np.array([d["conv_heat_kw_th"].to_numpy()[mo == m].sum() / 1e6 for m in ms])
            p2h = np.array([d["p2h_heat_kw_th"].to_numpy()[mo == m].sum() / 1e6 for m in ms])
            a = ax[c, k]
            a.bar(xs, conv, 0.75, color=COL["conv"], label="current system")
            a.bar(xs, p2h, 0.75, bottom=conv, color=C_P2H, label=TECH_LAB[tech])
            a.set_title(f"{SC_SHORT[mode]}" + ("" if mode == "baseline" else f", {TECH_LAB[tech]}"), fontsize=9, loc="left")
            a.set_xticks(xs)
            a.set_xticklabels([MON[m - 1][:1] for m in ms])
            share = p2h.sum() / max((conv + p2h).sum(), 1e-9) * 100
            if mode != "baseline":
                a.text(0.98, 0.95, f"new technology: {share:.0f} % of heat", transform=a.transAxes, ha="right", va="top", fontsize=7.5)
        ax[c, 0].set_ylabel("Heat (GWh th per month)")
    fig.legend(
        [plt.Rectangle((0, 0), 1, 1, color=COL["conv"]), plt.Rectangle((0, 0), 1, 1, color=C_P2H)],
        ["current system", "new technology (heat pump or resistive heater, as titled)"],
        loc="lower center",
        ncol=2,
        fontsize=8,
        bbox_to_anchor=(0.5, 0.02),
    )
    _headline(
        fig, "Schleswig-Holstein: monthly heat by source and scenario", "Same scale in all panels; the baseline panel shows today's heat supply"
    )
    fig.tight_layout(rect=(0, 0.06, 1, 0.89))
    p = viz.sh_path(_fig_dir(R), "O", 3, "monthly_energy")
    viz.save(fig, p, R["settings"].output.dpi, tight=False)
    return p


def fig_sh_duration(R, tech) -> Path:
    av = sum(R["avail"].values()) / 1e3
    mask = av > 0
    order = np.argsort(-av[mask])
    fig, ax = plt.subplots(figsize=(9, 4.4))
    xs = np.arange(mask.sum())
    ax.fill_between(xs, 0, av[mask][order], color=COL["curt"], alpha=0.25, label="Available curtailment")
    for mode in _modes(R)[1:]:
        used = _sh(R, tech, mode)["absorbed_kw_e"].to_numpy() / 1e3
        ax.plot(xs, used[mask][order], color=SC_COL[mode], lw=1.0, label=f"Used: {SC_SHORT[mode]}")
    ax.set(xlabel="Hours with curtailment, sorted", ylabel="Power (MW electric)", title=f"Duration curve of curtailed power, {TECH_LAB[tech]}")
    ax.legend()
    p = viz.sh_path(_fig_dir(R), "O", 4, "duration_curve", f"_{tech}")
    viz.save(fig, p, R["settings"].output.dpi)
    return p


def fig_sh_potential(R) -> Path:
    mo = np.asarray(R["months"])
    ms = sorted(set(int(m) for m in mo))
    av = sum(R["avail"].values())
    combos = [(t, m) for t in R["technologies"] for m in _modes(R)[1:]]
    fig, ax = plt.subplots(1, 2, figsize=(14, 5.0), gridspec_kw={"width_ratios": [1.1, 1.0]})
    ax[0].bar(np.arange(len(ms)), [av[mo == m].sum() / 1e6 for m in ms], 0.75, color=COL["curt"], alpha=0.35)
    ax[0].set_xticks(np.arange(len(ms)))
    ax[0].set_xticklabels([MON[q - 1] for q in ms])
    ax[0].set_ylabel("Curtailed electricity available (GWh el per month)")
    ax[0].set_title(f"Available in Schleswig-Holstein: {av.sum() / 1e6:,.0f} GWh el in the period", fontsize=9, loc="left")
    ax[0].grid(axis="x", visible=False)
    zones = sorted(R["avail"])
    labs, vals, cols, hat, bold = [], [], [], [], []
    for t, m in combos:
        for z in [*zones, "SH"]:
            d = (_sh(R, t, m) if z == "SH" else R["zone_frames"][(t, _size_label(R, m), z, m)])["absorbed_kw_e"].to_numpy()
            a = av.sum() if z == "SH" else R["avail"][z].sum()
            labs.append(f"{SC_SHORT[m]}, {TECH_LAB[t]}: {z}")
            vals.append(d.sum() / max(a, 1e-9) * 100)
            cols.append(SC_COL[m] if z == "SH" else "#9bb7d4")
            hat.append(d.sum() / 1e6)
            bold.append(z == "SH")
    y = np.arange(len(labs))
    ax[1].barh(y, vals, 0.6, color=cols)
    mx = max(vals + [1e-9])
    for yi, v, g in zip(y, vals, hat):
        ax[1].text(v + mx * 0.01, yi, f"{v:.2f} %  ({_fmt(g)} GWh el)", va="center", fontsize=8)
    ax[1].set_yticks(y)
    ax[1].set_yticklabels(labs, fontsize=8.5)
    for lab, b in zip(ax[1].get_yticklabels(), bold):
        if b:
            lab.set_fontweight("bold")
    ax[1].invert_yaxis()
    ax[1].set_xlim(0, mx * 1.6)
    ax[1].grid(axis="y", visible=False)
    ax[1].set_xlabel("Share of the curtailment of the zone absorbed (%)")
    ax[1].set_title("Share absorbed over the period, per zone and for Schleswig-Holstein (SH)", fontsize=9, loc="left")
    n_all = len(R["data"].facilities)
    sub = "Zone shares are relative to the curtailment of that zone; SH is the sum of the zones"
    if len(R["fms"]) < n_all:
        sub = f"ONLY {len(R['fms'])} OF {n_all} FACILITIES IN THE RUN: the shares are relative to the whole zone and are not representative. " + sub
    _headline(fig, "Schleswig-Holstein: how much of the curtailed power the facilities can take", sub)
    fig.tight_layout(rect=(0, 0.02, 1, 0.89))
    p = viz.sh_path(_fig_dir(R), "F", 1, "monthly_potential")
    viz.save(fig, p, R["settings"].output.dpi, tight=False)
    return p


def fig_sh_economics(R) -> Path:
    e = R["flex"]
    e = e[e.plant_size.isin([R["primary"], BASE, OPT_SIZE])]
    comp = [
        ("cost_current_heat_eur_a", "current heating system", COL["conv"]),
        ("cost_electricity_eur_a", "electricity of the new plant", COL["grid"]),
        ("cost_plant_vom_eur_a", "plant operation", "#999999"),
        ("plant_annuity_eur_a", "plant annuity", "#CC79A7"),
    ]
    g = (
        e.groupby(["technology", "mode"])[[c for c, *_ in comp] + ["net_benefit_eur_a", "cost_total_eur_a", "cost_baseline_eur_a"]]
        .sum()
        .reset_index()
    )
    g["order"] = g["mode"].map({m: i for i, m in enumerate(SC)})
    g = g.sort_values(["order", "technology"]).reset_index(drop=True)
    g["label"] = g.apply(lambda r: SC_SHORT[r["mode"]] + ("" if r.technology == BASE else f" ({TECH_LAB[r.technology]})"), axis=1)
    nb = g[g["mode"] != "baseline"].reset_index(drop=True)
    npos = e[e["mode"] != "baseline"].groupby(["technology", "mode"]).net_benefit_eur_a.apply(lambda s_: int((s_ > 0).sum())).to_dict()
    fig, ax = plt.subplots(1, 2, figsize=(15, 0.55 * len(g) + 3.2), gridspec_kw={"width_ratios": [1.0, 1.3]})
    y = np.arange(len(nb))
    ax[0].barh(y, nb.net_benefit_eur_a / 1e3, 0.6, color=[SC_COL[m] for m in nb["mode"]])
    ax[0].axvline(0, color="#555555", lw=0.8)
    lo, hi = float(min(nb.net_benefit_eur_a.min() / 1e3, 0)), float(max(nb.net_benefit_eur_a.max() / 1e3, 0))
    pad = max(hi - lo, 1) * 0.02
    for yi, r_ in zip(y, nb.itertuples()):
        v = r_.net_benefit_eur_a / 1e3
        ax[0].text(
            max(v, 0) + pad,
            yi,
            f"{v:+,.0f} k€/a  ({npos.get((r_.technology, r_.mode), 0)} of {R['flex'].facility_id.nunique()} facilities gain)",
            va="center",
            ha="left",
            fontsize=8,
        )
    ax[0].set_xlim(lo - (hi - lo) * 0.05 - 1, hi + (hi - lo) * 1.0 + 1)
    ax[0].set_yticks(y)
    ax[0].set_yticklabels(nb.label, fontsize=8.5)
    ax[0].invert_yaxis()
    ax[0].grid(axis="y", visible=False)
    ax[0].set_xlabel("Net benefit against the baseline (k€ per year)")
    ax[0].set_title("Net benefit (cost saving minus plant annuity)", fontsize=9, loc="left")
    y2 = np.arange(len(g))
    left = np.zeros(len(g))
    for c, lab, col in comp:
        v = g[c].to_numpy() / 1e3
        ax[1].barh(y2, v, 0.6, left=left, color=col, label=lab)
        left += v
    for yi, t in zip(y2, left):
        ax[1].text(t + left.max() * 0.01, yi, f"{t:,.0f} k€/a", va="center", fontsize=8)
    ax[1].set_yticks(y2)
    ax[1].set_yticklabels(g.label, fontsize=8.5)
    ax[1].invert_yaxis()
    ax[1].set_xlim(0, left.max() * 1.2)
    ax[1].grid(axis="y", visible=False)
    ax[1].set_xlabel("Annual cost (k€ per year)")
    ax[1].set_title("Composition of the annual cost", fontsize=9, loc="left")
    ax[1].legend(fontsize=7.5, loc="lower right")
    best = nb.loc[nb.net_benefit_eur_a.idxmax()]
    _headline(
        fig,
        "Schleswig-Holstein: economics of the scenarios (indicative, synthetic prices)",
        f"Best scenario: {best.label}, {best.net_benefit_eur_a / 1e3:+,.0f} k€ per year against the baseline",
    )
    fig.tight_layout(rect=(0, 0.02, 1, 0.89))
    p = viz.sh_path(_fig_dir(R), "E", 1, "economics")
    viz.save(fig, p, R["settings"].output.dpi, tight=False)
    return p


def fig_sh_sizing(R, tech) -> Path | None:
    if "hysteresis_optimised" not in R["modes"]:
        return None
    sz = R["sizing"]
    sz = sz[sz.technology == tech].copy()
    f = R["flex"]
    f = f[(f.technology == tech) & (f["mode"] == "hysteresis_optimised")][["facility_id", "net_benefit_eur_a"]]
    sz = sz.merge(f, on="facility_id", how="left")
    inv = sz.size_kw_th > 1e-6
    fig, ax = plt.subplots(1, 3, figsize=(16, 5.2), gridspec_kw={"width_ratios": [1.1, 1.0, 1.1]})
    ax[0].scatter(sz.q_design_kw_th[~inv], sz.size_kw_th[~inv], s=18, color="#999999", label=f"no investment ({int((~inv).sum())})")
    ax[0].scatter(
        sz.q_design_kw_th[inv],
        sz.size_kw_th[inv],
        s=26,
        color=SC_COL["hysteresis_optimised"],
        edgecolor="white",
        lw=0.5,
        label=f"invests ({int(inv.sum())})",
    )
    mx = float(sz.q_design_kw_th.max()) * 1.05
    for fac, ls in ((1.0, "-"), (0.5, "--"), (3.0, ":")):
        ax[0].plot([0, mx], [0, fac * mx], color="#888888", lw=0.8, ls=ls)
        ax[0].text(mx, fac * mx, f" {fac:g}×", fontsize=7, va="center", color="#666666")
    ax[0].set_xlim(0, mx * 1.08)
    ax[0].set_ylim(0, max(float(sz.size_kw_th.max()) * 1.1, 1))
    ax[0].set(xlabel="Design heat load of the facility (kW th)", ylabel="Optimised plant size (kW th)")
    ax[0].set_title("Size against design load (lines: share of design load)", fontsize=9, loc="left")
    ax[0].legend(fontsize=8, loc="upper left")
    bins = np.linspace(0, max(float(sz.size_over_q_design.max()), 0.1) * 1.02, 16)
    ax[1].hist(sz.size_over_q_design[inv], bins=bins, color=SC_COL["hysteresis_optimised"], edgecolor="white")
    ax[1].set(xlabel="Optimised size / design heat load", ylabel="Facilities that invest")
    ax[1].set_title("How large the investing plants are", fontsize=9, loc="left")
    ax[1].grid(axis="x", visible=False)
    r = sz[inv].sort_values("net_benefit_eur_a", ascending=False).reset_index(drop=True)
    ax[2].bar(r.index, r.net_benefit_eur_a / 1e3, color=[("#009E73" if v > 0 else "#D55E00") for v in r.net_benefit_eur_a], width=0.85)
    ax[2].axhline(0, color="#555555", lw=0.8)
    ax[2].set(xlabel="Investing facilities, ranked", ylabel="Net benefit (k€ per year)")
    ax[2].set_title(f"Net benefit per facility: {r.net_benefit_eur_a.sum() / 1e3:,.0f} k€/a in total", fontsize=9, loc="left")
    ax[2].grid(axis="x", visible=False)
    cap = sz.size_kw_th.sum() / 1e3
    _headline(
        fig,
        f"Schleswig-Holstein: optimised {TECH_LAB[tech]} sizing (oemof, HiGHS)",
        f"{int(inv.sum())} of {len(sz)} facilities invest, {cap:,.1f} MW th in total; green bars pay back the annuity, orange do not",
    )
    fig.tight_layout(rect=(0, 0.02, 1, 0.85))
    p = viz.sh_path(_fig_dir(R), "F", 2, "optimised_sizing", f"_{tech}")
    viz.save(fig, p, R["settings"].output.dpi, tight=False)
    return p


def fig_sh_compare(R) -> Path:
    s = R["sh"].copy()
    s = s[s.plant_size.isin([R["primary"], BASE, OPT_SIZE])]
    e = R["flex"]
    e = e[e.plant_size.isin([R["primary"], BASE, OPT_SIZE])]
    cols = [c for c in ("cost_total_eur_a", "co2_t_a") if c in e]
    agg = (
        e.groupby(["technology", "mode"])[
            ["conv_heat_mwh_th", "p2h_heat_mwh_th", "grid_el_mwh_e", "absorbed_mwh_e", "conv_heat_displaced_mwh_th", *cols]
        ]
        .sum()
        .reset_index()
    )
    p = viz.sh_path(_fig_dir(R), "C", 1, "scenario_comparison")
    return _kpi_grid(
        agg,
        "Schleswig-Holstein: scenario comparison, period totals (cost and CO2 annualised)",
        p,
        R["settings"].output.dpi,
        "Baseline = current heating system. Economics: synthetic prices of the data package, indicative only",
    )


def _mean_temp_sh(R, tech, mode, env, msk):
    num = den = 0.0
    for fm in R["fms"].values():
        r = _res(R, tech, mode, fm)
        for i, b in enumerate(fm.basins):
            if b.environment != env:
                continue
            w = b.area_m2 * b.active[:-1][msk]
            num = num + w * np.nan_to_num(b.temp_c(r.energy[i, :-1])[msk] - b.t_min)
            den = den + w
    return None if np.isscalar(den) else np.where(den > 1e-9, num / np.maximum(den, 1e-9), np.nan)


def fig_sh_thermal(R, tech, month: int) -> Path:
    envs = [e for e in ("indoor", "outdoor") if (_fm_tab(R).environment == e).any()]
    msk = R["months"] == month
    x = _x(R, msk)
    fig, ax = plt.subplots(len(envs) + 1, 1, figsize=(13, 2.6 * (len(envs) + 1) + 0.8), sharex=True)
    for r_i, env in enumerate(envs):
        for mode in _modes(R):
            t = _mean_temp_sh(R, tech, mode, env, msk)
            if t is not None:
                ax[r_i].plot(x, t, color=SC_COL[mode], lw=1.3, ls="--" if mode == "baseline" else "-", label=SC_SHORT[mode])
        ax[r_i].set_ylabel(f"{env.capitalize()} basins\nabove T_min (K)")
        if _mean_temp_sh(R, tech, "baseline", env, msk) is None or not np.isfinite(_mean_temp_sh(R, tech, "baseline", env, msk)).any():
            ax[r_i].text(
                0.5, 0.5, f"no {env} basin in operation in {MON[month - 1]}", transform=ax[r_i].transAxes, ha="center", va="center", color="#777777"
            )
            ax[r_i].set_yticks([])
        else:
            ax[r_i].legend(fontsize=7, ncol=3)
    ax[-1].fill_between(x, sum(R["avail"].values())[msk] / 1e3, step="mid", color=COL["curt"], alpha=0.4)
    ax[-1].set_ylabel("Curtailment (MW el)")
    ax[-1].xaxis.set_major_formatter(mdates.DateFormatter("%d"))
    fig.suptitle(
        f"Schleswig-Holstein: mean water temperature above T_min (area weighted), {MON[month - 1]}, {TECH_LAB[tech]}", fontsize=10, fontweight="bold"
    )
    p = viz.sh_path(_fig_dir(R), "T", 1, "thermal", f"_{tech}_m{month:02d}")
    viz.save(fig, p, R["settings"].output.dpi)
    return p


C_IND, C_OUT = "#0072B2", "#009E73"
C_ZONE = {"T5": "#332288", "T6": "#44AA99"}
LOSS_KEYS = (
    ("evaporation", "extra_loss_evaporation"),
    ("convection", "extra_loss_convection"),
    ("radiation", "extra_loss_radiation"),
    ("conduction", "extra_loss_conduction"),
    ("make-up water", "extra_loss_make_up_water"),
)


def _focus_mode(R) -> str:
    return next(m for m in ("hysteresis_addon", "hysteresis_optimised", "hysteresis_replace") if m in R["modes"])


def fig_sh_storage(R, tech) -> Path:
    mode = _focus_mode(R)
    st = R["storage"]
    s = st["summary"][(st["summary"].technology == tech) & (st["summary"].scenario == mode)]
    fac = st["facility"][(st["facility"].technology == tech) & (st["facility"].scenario == mode)]
    zones = [*sorted(R["avail"]), "SH"]

    def g(z, e, c):
        return float(s[(s.zone == z) & (s.environment == e)][c].sum())

    sh = s[(s.zone == "SH") & (s.environment == "all")].iloc[0]
    fig, ax = plt.subplots(1, 3, figsize=(17, 5.6), gridspec_kw={"width_ratios": [1.0, 1.0, 1.15]})
    y = np.arange(len(zones))

    for env, col, lab in (("indoor", C_IND, "indoor basins"), ("outdoor", C_OUT, "outdoor basins")):
        left = np.array([sum(g(z, e, "water_volume_m3") for e in ("indoor", "outdoor")[: ("indoor", "outdoor").index(env)]) for z in zones])
        ax[0].barh(y, [g(z, env, "water_volume_m3") for z in zones], 0.6, left=left, color=col, label=lab)
    for yi, z in enumerate(zones):
        v, c = g(z, "all", "water_volume_m3"), g(z, "all", "storage_mwh_th_per_k")
        ax[0].text(v * 1.01, yi, f"{v:,.0f} m³  =  {c:,.0f} MWh th per K", va="center", fontsize=8.5, fontweight="bold" if z == "SH" else None)
    ax[0].set_yticks(y)
    ax[0].set_yticklabels(zones)
    ax[0].invert_yaxis()
    ax[0].set_xlim(0, g("SH", "all", "water_volume_m3") * 2.0)
    ax[0].set_xlabel("Water volume (m³)")
    ax[0].xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax[0].set_title("Water volume and heat capacity per 1 K", fontsize=9, loc="left")
    ax[0].grid(axis="y", visible=False)
    ax[0].legend(fontsize=7.5, loc="lower right")

    for env, col in (("indoor", C_IND), ("outdoor", C_OUT)):
        left = np.array([g(z, "indoor", "storage_band_mwh_th") if env == "outdoor" else 0.0 for z in zones])
        ax[1].barh(y, [g(z, env, "storage_band_mwh_th") for z in zones], 0.6, left=left, color=col)
    for yi, z in enumerate(zones):
        b = g(z, "all", "storage_band_mwh_th")
        ax[1].text(
            b * 1.01,
            yi,
            f"{b:,.0f} MWh th  (band {g(z, 'indoor', 'mean_band_width_k'):.0f} K indoor, {g(z, 'outdoor', 'mean_band_width_k'):.0f} K outdoor)",
            va="center",
            fontsize=8,
            fontweight="bold" if z == "SH" else None,
        )
    ax[1].set_yticks(y)
    ax[1].set_yticklabels(zones)
    ax[1].invert_yaxis()
    ax[1].set_xlim(0, g("SH", "all", "storage_band_mwh_th") * 1.95)
    ax[1].set_xlabel("Heat that fits into the allowed band (MWh th)")
    ax[1].set_title("Storage in the allowed band, all basins charged from T_min to T_max", fontsize=9, loc="left")
    ax[1].grid(axis="y", visible=False)

    mx = float(fac.water_volume_m3.max()) * 1.05
    for zone in sorted(R["avail"]):
        d = fac[fac.zone == zone]
        ax[2].scatter(
            d.water_volume_m3,
            d.plant_el_capacity_kw_e / 1e3,
            s=22,
            color=C_ZONE.get(zone, "#777777"),
            alpha=0.85,
            label=f"{zone} facilities ({len(d)})",
        )
    ymax = float(fac.plant_el_capacity_kw_e.max()) / 1e3 * 1.1
    for w in (250, 500, 1000):
        ax[2].plot([0, mx], [0, w * mx / 1e6], color="#888888", lw=0.8, ls=":")
        if w * mx / 1e6 <= ymax:
            ax[2].text(mx, w * mx / 1e6, f" {w} kW per 1000 m³", fontsize=7, va="center", color="#666666")
        else:
            ax[2].text(ymax / (w / 1e6) * 1.02, ymax * 0.985, f"{w} kW per\n1000 m³", fontsize=7, va="top", ha="left", color="#666666")
    ax[2].set_xlim(0, mx * 1.2)
    ax[2].set_ylim(0, ymax)
    ax[2].set(xlabel="Water volume of the facility (m³)", ylabel="Rated electric power of the plant (MW el)")
    ax[2].xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax[2].set_title(f"Charging power against volume, {_size_label(R, mode)} plant", fontsize=9, loc="left")
    ax[2].legend(fontsize=7.5, loc="upper left")
    txt = (
        f"SH: {sh.plant_el_capacity_mw_e:,.1f} MW el rated = {sh.plant_kw_el_per_1000m3:,.0f} kW el per 1000 m³\n"
        f"peak absorbed (all zones at once) {sh.peak_absorbed_mw_e_coincident:,.1f} MW = {sh.peak_absorbed_kw_el_per_1000m3:,.0f} kW per 1000 m³\n"
        f"band filled from T_min in {sh.hours_to_fill_band_at_rated_power_h:,.0f} h at rated power (no losses)"
    )
    ax[2].text(
        0.98, 0.04, txt, transform=ax[2].transAxes, ha="right", va="bottom", fontsize=7.5, bbox=dict(boxstyle="round", fc="white", ec="#cccccc")
    )
    _headline(
        fig,
        f"Schleswig-Holstein: storage potential of the pools, {TECH_LAB[tech]}",
        f"{sh.water_volume_m3:,.0f} m³ of water store {sh.storage_mwh_th_per_k:,.0f} MWh th per 1 K; the allowed bands hold {sh.storage_band_mwh_th:,.0f} MWh th. "
        f"Open-air pools are closed part of the year: time weighted {sh.storage_mwh_th_per_k_time_weighted:,.0f} MWh th per K",
    )
    fig.tight_layout(rect=(0, 0.02, 1, 0.88))
    p = viz.sh_path(_fig_dir(R), "F", 3, "storage_potential", f"_{tech}")
    viz.save(fig, p, R["settings"].output.dpi, tight=False)
    return p


def fig_sh_charge_balance(R, tech) -> Path:
    mode = _focus_mode(R)
    b = R["storage"]["balance"]
    b = b[(b.technology == tech) & (b.scenario == mode)]
    zones = [*sorted(R["avail"]), "SH"]

    def row(z, e="all"):
        return b[(b.zone == z) & (b.environment == e)].iloc[0]

    parts = [("Current heat displaced", "current_heat_displaced_mwh_th", COL["conv"])]
    parts += [(f"Extra {n}", k, COMP_COLOR[n]) for n, k in LOSS_KEYS if abs(float(row("SH")[k])) > 1e-6]
    parts += [("Spill and closure release", "spill", "#bbbbbb")]
    fig, ax = plt.subplots(1, 3, figsize=(17, 5.2), gridspec_kw={"width_ratios": [1.0, 1.0, 0.9]})
    y = np.arange(len(zones))
    for a, norm in ((ax[0], False), (ax[1], True)):
        left = np.zeros(len(zones))
        for lab, k, col in parts:
            v = np.array([float(row(z)[k]) for z in zones])
            tot = np.array([float(row(z).p2h_heat_mwh_th) for z in zones])
            w = v / tot * 100 if norm else v
            a.barh(y, w, 0.6, left=left, color=col, label=lab)
            if norm:
                for yi, (l0, wi) in enumerate(zip(left, w)):
                    if wi >= 4:
                        a.text(
                            l0 + wi / 2,
                            yi,
                            f"{wi:.0f} %",
                            ha="center",
                            va="center",
                            fontsize=7.5,
                            color="white" if lab == "Current heat displaced" else "black",
                        )
            left = left + w
        a.set_yticks(y)
        a.set_yticklabels(zones)
        a.invert_yaxis()
        a.grid(axis="y", visible=False)
    for yi, z in enumerate(zones):
        t = float(row(z).p2h_heat_mwh_th)
        ax[0].text(t * 1.01, yi, f"{t:,.0f} MWh th", va="center", fontsize=8.5, fontweight="bold" if z == "SH" else None)
    ax[0].set_xlim(0, float(row("SH").p2h_heat_mwh_th) * 1.25)
    ax[0].set_xlabel("Heat delivered by the new plant (MWh th)")
    ax[0].set_title("Use of the plant heat, absolute", fontsize=9, loc="left")
    ax[1].set_xlim(0, 100)
    ax[1].set_xlabel("Share of the heat delivered by the new plant (%)")
    ax[1].set_title("Use of the plant heat, shares", fontsize=9, loc="left")

    comps = [n for n, k in LOSS_KEYS if abs(float(row("SH")[k])) > 1e-6]
    yy = np.arange(len(comps))
    for env, col in (("indoor", C_IND), ("outdoor", C_OUT)):
        if not ((b.zone == "SH") & (b.environment == env)).any():
            continue
        r_ = row("SH", env)
        left = np.array([float(row("SH", "indoor")[k]) if env == "outdoor" else 0.0 for n, k in LOSS_KEYS if n in comps])
        ax[2].barh(yy, [float(r_[k]) for n, k in LOSS_KEYS if n in comps], 0.6, left=left, color=col, label=f"{env} basins")
    tot_loss = float(row("SH").extra_loss_total)
    for yi, (n, k) in enumerate((n, k) for n, k in LOSS_KEYS if n in comps):
        v = float(row("SH")[k])
        ax[2].text(v * 1.01, yi, f"{v:,.0f} MWh th ({100 * v / tot_loss:.0f} %)", va="center", fontsize=8)
    ax[2].set_yticks(yy)
    ax[2].set_yticklabels(comps)
    ax[2].invert_yaxis()
    ax[2].set_xlim(0, tot_loss * 0.95)
    ax[2].set_xlabel("Extra heat loss of the charged basins, SH (MWh th)")
    ax[2].set_title("Which loss grows when the water is warmer", fontsize=9, loc="left")
    ax[2].grid(axis="y", visible=False)
    ax[2].legend(fontsize=7.5, loc="lower right")
    sh = row("SH")
    _headline(
        fig,
        f"Schleswig-Holstein: where the heat of the charged basins goes, {SC_SHORT[mode].lower()}, {TECH_LAB[tech]}",
        f"Of {sh.p2h_heat_mwh_th:,.0f} MWh th delivered, {sh.current_heat_displaced_mwh_th:,.0f} MWh th ({100 * sh.current_heat_displaced_mwh_th / sh.p2h_heat_mwh_th:.0f} %) displace current heat; "
        f"{sh.extra_loss_total:,.0f} MWh th ({100 * sh.extra_loss_total / sh.p2h_heat_mwh_th:.0f} %) are lost because the warmer water loses more, "
        f"{sh.extra_loss_evaporation:,.0f} MWh th of it by evaporation",
    )
    fig.text(
        0.01,
        0.022,
        f"Balance: plant heat = current heat displaced + extra loss + spill + change of stored heat (residual {abs(sh.balance_residual):.2g} MWh th). Components use the nonlinear pool "
        f"physics at the actual water temperature, scaled by {sh.nonlinear_over_secant:.3f} to the secant loss of the simulation (builder.py).",
        fontsize=7.5,
        color="#444444",
    )
    h, lab = ax[0].get_legend_handles_labels()
    fig.legend(h, lab, loc="lower center", ncol=len(lab), fontsize=8, bbox_to_anchor=(0.5, 0.045))
    fig.tight_layout(rect=(0, 0.11, 1, 0.88))
    p = viz.sh_path(_fig_dir(R), "B", 1, "charging_loss_balance", f"_{tech}")
    viz.save(fig, p, R["settings"].output.dpi, tight=False)
    return p


HOURS_WEEK = 168
C_HALL = COMP_COLOR[HALL]
LOAD_PARTS = (
    ("basins_curt", "Basins, curtailed power", COL["curt"], None),
    ("hall_curt", "Hall air, curtailed power", C_HALL, None),
    ("basins_grid", "Basins, grid electricity", COL["grid"], None),
    ("hall_grid", "Hall air, grid electricity", C_HALL, "///"),
)


def peak_week(avail_kw: np.ndarray, n: int = HOURS_WEEK) -> slice:
    a = np.asarray(avail_kw, float)
    if len(a) <= n:
        return slice(0, len(a))
    cs = np.concatenate([[0.0], np.cumsum(a)])
    tot = cs[n:] - cs[:-n]
    s0 = int(np.argmax(tot))
    return slice(s0, s0 + n)


def _load_stack(ax, x, parts: dict[str, np.ndarray], unit_div: float) -> None:
    ys = [parts[k] / unit_div for k, *_ in LOAD_PARTS]
    cols = [c for _, _, c, _ in LOAD_PARTS]
    st = ax.stackplot(x, *ys, colors=cols, step="post", alpha=0.95, labels=[lab for _, lab, _, _ in LOAD_PARTS])
    for poly, (_, _, _, hatch) in zip(st, LOAD_PARTS):
        if hatch:
            poly.set_hatch(hatch)
            poly.set_edgecolor("white")


def _week_title(idx, sl) -> str:
    a, b = idx[sl][0], idx[sl][-1]
    return f"{a:%a %d %b %Y} to {b:%a %d %b %Y}"


def _week_frame(idx, sl, avail_kw, parts: dict[str, dict[str, np.ndarray]], extra: dict | None = None) -> pd.DataFrame:
    d = {"curtailed_power_available_kw_e": np.asarray(avail_kw)[sl]}
    for mode, pp in parts.items():
        for k, v in pp.items():
            d[f"{mode}__load_{k}_kw_e"] = v[sl]
        d[f"{mode}__load_total_kw_e"] = sum(v[sl] for v in pp.values())
    for k, v in (extra or {}).items():
        d[k] = np.asarray(v)[sl]
    return pd.DataFrame(d, index=pd.DatetimeIndex(idx[sl], name="ts_local"))


def fig_sh_peak_week(R, tech) -> Path:
    modes = _modes(R)[1:]
    idx = R["tl"].index_local
    av = sum(R["avail"].values())
    sl = peak_week(av)
    x = idx[sl]
    parts: dict[str, dict[str, np.ndarray]] = {}
    for mode in modes:
        acc = {k: np.zeros(R["tl"].n) for k, *_ in LOAD_PARTS}
        for fm in R["fms"].values():
            for k, v in kpis.load_split(fm, _res(R, tech, mode, fm), mode).items():
                acc[k] += v
        parts[mode] = acc
    fig, ax = plt.subplots(1 + len(modes), 1, figsize=(13, 2.6 * (1 + len(modes)) + 1.0), sharex=True)
    ax[0].fill_between(x, av[sl] / 1e3, step="post", color=COL["curt"], alpha=0.35, label="Curtailed power available in Schleswig-Holstein")
    ax[0].step(x, av[sl] / 1e3, where="post", color=COL["curt"], lw=1.0)
    ax[0].set_ylabel("Available (MW el)")
    ax[0].set_title(
        f"Curtailed power available: peak {av[sl].max() / 1e3:,.0f} MW, {av[sl].sum() / 1e6:,.2f} GWh in the week", fontsize=9, loc="left"
    )
    ax[0].legend(fontsize=7, loc="upper right")
    top = max(sum(p[sl] for p in parts[m].values()).max() for m in modes) / 1e3
    for k, mode in enumerate(modes, start=1):
        pp = parts[mode]
        _load_stack(ax[k], x, {a: b[sl] for a, b in pp.items()}, 1e3)
        tot = sum(pp.values())
        cu = (pp["basins_curt"] + pp["hall_curt"])[sl].sum() / 1e3
        gr = (pp["basins_grid"] + pp["hall_grid"])[sl].sum() / 1e3
        ax[k].set_ylim(0, max(top * 1.3, 1e-6))
        ax[k].set_ylabel("Load (MW el)")
        ax[k].set_title(
            f"{SC_LAB[mode]}\nLoad of the {TECH_LAB[tech]}: peak {tot[sl].max() / 1e3:,.1f} MW. Week: {cu:,.0f} MWh from curtailed power "
            f"({100 * cu * 1e3 / max(av[sl].sum(), 1e-9):.1f} % of the available), {gr:,.0f} MWh from the grid",
            fontsize=8.5,
            loc="left",
        )
        if k == 1:
            ax[k].legend(fontsize=7, ncol=4, loc="upper right")
    ax[-1].xaxis.set_major_formatter(mdates.DateFormatter("%a %d"))
    fig.suptitle(
        f"Schleswig-Holstein, hourly load in the week with most curtailed power ({_week_title(idx, sl)}), {TECH_LAB[tech]}, "
        f"{len(R['fms'])} facilities of the run",
        fontsize=10,
        fontweight="bold",
    )
    p = viz.sh_path(_fig_dir(R), "O", 5, "peak_week_load", f"_{tech}")
    viz.save(fig, p, R["settings"].output.dpi)
    tab = Path(R["out"]) / "tables"
    _week_frame(idx, sl, av, parts).round(3).to_csv(tab / f"peak_week_load_sh__{tech}.csv")
    return p


def fig_fac_peak_week(R, fm, tech) -> Path:
    modes = _modes(R)[1:]
    idx = R["tl"].index_local
    av = R["avail"][fm.zone]
    sl = peak_week(av)
    x = idx[sl]
    parts = {m: kpis.load_split(fm, _res(R, tech, m, fm), m) for m in modes}
    dem = fm.total_demand_kw()
    fig = plt.figure(figsize=(15, 2.6 * (1 + len(modes)) + 1.0))
    gs = fig.add_gridspec(1 + len(modes), 2, width_ratios=[1.0, 1.0])
    a0 = fig.add_subplot(gs[0, :])
    a0.fill_between(x, av[sl] / 1e3, step="post", color=COL["curt"], alpha=0.35, label=f"Curtailed power available in zone {fm.zone}")
    a0.step(x, av[sl] / 1e3, where="post", color=COL["curt"], lw=1.0)
    a0.set_ylabel("Available (MW el)")
    a0.set_title(
        f"Curtailed power available in zone {fm.zone}: peak {av[sl].max() / 1e3:,.0f} MW, {av[sl].sum() / 1e6:,.2f} GWh in the week",
        fontsize=9,
        loc="left",
    )
    a0.legend(fontsize=7, loc="upper right")
    top = max(sum(p[sl] for p in parts[m].values()).max() for m in modes)
    axes_l, axes_r = [], []
    for k, mode in enumerate(modes, start=1):
        r = _res(R, tech, mode, fm)
        pp = parts[mode]
        al = fig.add_subplot(gs[k, 0], sharex=a0)
        _load_stack(al, x, {a: b[sl] for a, b in pp.items()}, 1.0)
        al.set_ylim(0, max(top * 1.3, 1e-6))
        al.set_ylabel("Load (kW el)")
        cu = (pp["basins_curt"] + pp["hall_curt"])[sl].sum()
        gr = (pp["basins_grid"] + pp["hall_grid"])[sl].sum()
        rated = _rated_kw(R, fm, tech, mode)
        al.set_title(
            f"{SC_SHORT[mode]}, plant {rated:,.0f} kW th: {cu:,.0f} kWh from curtailed power, {gr:,.0f} kWh from the grid", fontsize=8.5, loc="left"
        )
        ar = fig.add_subplot(gs[k, 1], sharex=a0)
        ar.stackplot(
            x,
            r.conv_heat[sl],
            r.q_basin.sum(axis=0)[sl],
            r.q_hall[sl],
            colors=[COL["conv"], C_P2H, C_HALL],
            step="post",
            alpha=0.95,
            labels=["Current heating system", f"{TECH_LAB[tech].capitalize()}, basins", f"{TECH_LAB[tech].capitalize()}, hall air"],
        )
        ar.step(x, dem[sl], where="post", color="black", lw=0.9, ls="--", label="Heat demand at T_min (basins + hall)")
        ar.set_ylim(0, max(float(np.max(r.conv_heat[sl] + r.q_basin.sum(axis=0)[sl] + r.q_hall[sl])), float(dem[sl].max())) * 1.3 + 1e-6)
        ar.set_ylabel("Heat (kW th)")
        ar.set_title(f"{SC_SHORT[mode]}: heat supply", fontsize=8.5, loc="left")
        axes_l.append(al)
        axes_r.append(ar)
    axes_l[0].legend(fontsize=7, ncol=2, loc="upper right")
    axes_r[0].legend(fontsize=7, ncol=2, loc="upper right")
    for a in (axes_l[-1], axes_r[-1]):
        a.xaxis.set_major_formatter(mdates.DateFormatter("%a %d"))
    fig.suptitle(
        f"Hourly load in the week with most curtailed power ({_week_title(idx, sl)}), {TECH_LAB[tech]}: {_ctx(fm)}", fontsize=10, fontweight="bold"
    )
    p = viz.fac_path(_fig_dir(R), fm.facility_id, fm.name, "O", f"peak_week_load_{tech}")
    viz.save(fig, p, R["settings"].output.dpi)
    extra = {"demand_kw_th": dem}
    for m in modes:
        r = _res(R, tech, m, fm)
        extra[f"{m}__heat_current_system_kw_th"] = r.conv_heat
        extra[f"{m}__heat_plant_basins_kw_th"] = r.q_basin.sum(axis=0)
        extra[f"{m}__heat_plant_hall_kw_th"] = r.q_hall
    _week_frame(idx, sl, av, parts, extra).round(3).to_csv(Path(R["out"]) / "tables" / f"peak_week_load_fac{fm.facility_id:03d}__{tech}.csv")
    return p


def fig_fac_curtail_week(R, fm, tech) -> Path:
    modes = _modes(R)[1:]
    idx = R["tl"].index_local
    r0 = _res(R, tech, modes[0], fm)
    sl = peak_week(r0.curt_el)
    x = idx[sl]
    nrow = 1 + 2 * len(modes) + 1
    fig, ax = plt.subplots(nrow, 1, figsize=(11, 2.0 * nrow + 1), sharex=True)
    lay, col, lab = _demand_layers(fm, sl)
    ax[0].stackplot(x, *lay, colors=col, labels=lab, step="post")
    ax[0].set_title("Heat demand at T_min and outdoor air temperature", fontsize=9)
    t_out = np.asarray(fm.t_ext, float)[sl]
    tx = ax[0].twinx()
    tx.step(x, t_out, where="post", color="#E69F00", lw=1.6, label="outdoor air temperature (right axis)")
    tx.set_ylabel("°C", color="#B36B00")
    tx.tick_params(axis="y", colors="#B36B00")
    tx.set_ylim(min(0.0, float(t_out.min()) - 1.0), float(t_out.max()) + 12.0)
    tx.spines["right"].set_visible(True)
    tx.grid(False)
    k = 1
    big = max(range(fm.n_basins), key=lambda i: fm.basins[i].volume_m3)
    bb = fm.basins[big]
    for mode in modes:
        r = _res(R, tech, mode, fm)
        ax[k].stackplot(
            x,
            r.conv_basin.sum(axis=0)[sl],
            r.conv_hall[sl],
            r.p2h_heat[sl],
            colors=[COL["conv"], "#D9B382", C_P2H],
            labels=["current system, basins", "current system, hall air", TECH_LAB[tech]],
            step="post",
        )
        rated = _rated_kw(R, fm, tech, mode)
        ax[k].axhline(rated, color="black", lw=1.1, ls="--", label=f"heater capacity {rated:,.0f} kW th")
        ax[k].set_ylim(0, max(rated, float((r.conv_heat + r.p2h_heat)[sl].max())) * 1.12)
        ax[k].set_title(f"{SC_SHORT[mode]}: heat supply ({r.curt_el[sl].sum() / 1e3:,.1f} MWh el from curtailed power in the week)", fontsize=9)
        temp = bb.t_min + r.energy[big][sl.start : sl.stop] / bb.c_kwh_per_k
        ax[k + 1].step(x, temp, where="post", color="#0072B2", lw=1.6, label=f"basin {bb.basin_id} water temperature")
        ax[k + 1].axhline(bb.t_min, color="#666666", lw=0.9, ls=":", label=f"T_min {bb.t_min:.1f} °C")
        ax[k + 1].axhline(bb.t_max, color="#666666", lw=0.9, ls="-.", label=f"T_max {bb.t_max:.1f} °C")
        ax[k + 1].set_ylim(bb.t_min - 0.3, bb.t_max + 0.3)
        ax[k + 1].set_title(
            f"{SC_SHORT[mode]}: water temperature of the biggest basin (basin {bb.basin_id}, {bb.environment}, {bb.volume_m3:,.0f} m³)", fontsize=9
        )
        ax[k + 1].set_ylabel("°C")
        k += 2
    ax[-1].fill_between(x, R["avail"][fm.zone][sl] / 1e3, step="post", color=COL["curt"], alpha=0.4)
    ax[-1].set_title(f"Curtailed power available in zone {fm.zone} (MW electric)", fontsize=9)
    for a in ax[:-1]:
        if not a.get_ylabel():
            a.set_ylabel("kW")
    ax[-1].set_ylabel("MW")
    for i, a in enumerate(ax[:-1]):
        h_, l_ = a.get_legend_handles_labels()
        if i == 0:
            h2, l2 = tx.get_legend_handles_labels()
            h_, l_ = h_ + h2, l_ + l2
        a.legend(h_, l_, fontsize=7, loc="center left", bbox_to_anchor=(1.06 if i == 0 else 1.005, 0.5), frameon=False)
    for a in ax:
        a.xaxis.set_major_formatter(mdates.DateFormatter("%a %d %b"))
        a.set_xlim(x[0], x[-1] + pd.Timedelta(hours=1))
    fig.suptitle(f"Week with most absorbed curtailed energy ({_week_title(idx, sl)}), {TECH_LAB[tech]}\n{_ctx(fm)}", fontsize=10, fontweight="bold")
    p = viz.fac_path(_fig_dir(R), fm.facility_id, fm.name, "O", f"curtailed_week_{tech}")
    viz.save(fig, p, R["settings"].output.dpi)
    return p


def make_all(R) -> list[Path]:
    viz.style()
    R["monthly"], R["flags"] = {}, {}
    focus_mode = next(m for m in ("hysteresis_replace", "hysteresis_addon", "hysteresis_optimised") if m in R["modes"])
    samples = pick_samples(R)
    ref = R.get("reference_facility")
    ref = ref if ref in R["fms"] else samples[0]
    for tech in R["technologies"]:
        for fid in samples:
            fm = R["fms"][fid]
            mt = kpis.monthly(fm, _res(R, tech, focus_mode, fm), R["months"])
            R["monthly"][(fid, tech)] = mt
            R["flags"][(fid, tech)] = kpis.month_flags(mt)
    files: list[Path] = []
    for fid in samples:
        fm = R["fms"][fid]
        files += [fig_demand(R, fm), fig_demand_profile(R, fm), fig_sizing(R, fm), fig_compare(R, fm)]
        for tech in R["technologies"]:
            files += [
                fig_heat_supply_cold_warm(R, fm, tech),
                fig_absorption(R, fm, tech),
                fig_monthly_energy(R, fm, tech),
                fig_load_soc(R, fm, tech),
                fig_thermal(R, fm, tech),
                fig_trajectories(R, fm, tech),
            ]
    files += [fig_sh_demand(R), fig_sh_monthly(R), fig_sh_potential(R), fig_sh_compare(R), fig_sh_economics(R)]
    for tech in R["technologies"]:
        month, _ = _sh_window(R, tech)
        opt = fig_sh_sizing(R, tech)
        files += [opt] if opt else []
        files += [fig_sh_storage(R, tech), fig_sh_charge_balance(R, tech)]
        files += [
            fig_sh_dispatch(R, tech, 2, month),
            fig_sh_duration(R, tech),
            fig_sh_thermal(R, tech, month),
            fig_sh_peak_week(R, tech),
            fig_fac_peak_week(R, R["fms"][ref], tech),
            fig_fac_curtail_week(R, R["fms"][ref], tech),
        ]
    log.info("%d figures", len(files))
    return files
