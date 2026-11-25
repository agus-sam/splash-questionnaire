from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

from .. import viz
from ..preprocessing import report_months
from ..viz import COL, COMP_COLOR, MON
from .demand import COMPONENTS, DHW, HALL, LATENT

STACK = COMPONENTS + [HALL, DHW]
LAYERS = COMPONENTS + [HALL, DHW]


def _signed_bars(ax, x, series: dict[str, np.ndarray], width: float = 0.8):
    pos = np.zeros(len(x))
    neg = np.zeros(len(x))
    for name in STACK:
        v = np.asarray(series.get(name, np.zeros(len(x))), dtype=float)
        if name == DHW and not np.any(v):
            continue
        bottom = np.where(v >= 0, pos, neg)
        ax.bar(x, v, width, bottom=bottom, color=COMP_COLOR[name], label=name, linewidth=0)
        pos = pos + np.where(v >= 0, v, 0.0)
        neg = neg + np.where(v < 0, v, 0.0)
    ax.set_ylim(min(neg.min() * 1.08, 0.0), max(pos.max(), 1e-9) * 1.12)
    return pos


def _signed_area(ax, x, series: dict[str, np.ndarray]):
    pos = np.zeros(len(x))
    neg = np.zeros(len(x))
    for name in STACK:
        v = np.asarray(series.get(name, np.zeros(len(x))), dtype=float)
        if name == DHW and not np.any(v):
            continue
        up = np.where(v >= 0, v, 0.0)
        dn = np.where(v < 0, v, 0.0)
        ax.fill_between(x, pos, pos + up, color=COMP_COLOR[name], label=name, linewidth=0, step="post")
        ax.fill_between(x, neg, neg + dn, color=COMP_COLOR[name], linewidth=0, step="post")
        pos, neg = pos + up, neg + dn


def plot_facility(fd: dict, path: Path, dpi: int, group: str = "") -> None:
    sc0 = fd["scenarios"][0]
    df = fd["hourly"][sc0]
    idx = fd["index"]
    fig = plt.figure(figsize=(13, 7.4))
    gs = fig.add_gridspec(2, 3, width_ratios=[1.1, 1.1, 0.8])

    ax = fig.add_subplot(gs[0, :2])
    months = sorted(set(report_months(idx)))
    mon = {c: df[c].groupby(report_months(idx)).sum().reindex(months).to_numpy() / 1000.0 for c in LAYERS}
    has_dhw = bool(df[DHW].any())
    x = np.arange(len(months))
    _signed_bars(ax, x, mon)
    tot = df["total"].groupby(report_months(idx)).sum().reindex(months).to_numpy() / 1000.0
    ax.plot(
        x,
        tot,
        "o-",
        color=COL["total"],
        lw=1.6,
        ms=4,
        label=f"Total = basins + hall{' + hot water' if has_dhw else ''}, net of solar gain (the model counts hours of net loss only)",
    )
    if len(fd["scenarios"]) > 1 and fd["hall"] is not None:
        d2 = fd["hourly"][fd["scenarios"][1]]
        ax.plot(
            x,
            d2["total"].groupby(report_months(idx)).sum().reindex(months).to_numpy() / 1000.0,
            "d",
            color=COL["total"],
            ms=5,
            mfc="white",
            label=f"Total, hall scenario {fd['scenarios'][1]}",
        )
    ax.plot(
        x,
        df[LATENT].groupby(report_months(idx)).sum().reindex(months).to_numpy() / 1000.0,
        ":",
        color=COL["memo"],
        lw=1.2,
        label="Dehumidification (memo, not added)",
    ) if fd["hall"] is not None else None
    ax.set_xticks(x)
    ax.set_xticklabels([MON[m - 1] for m in months])
    ax.set_ylabel("Heat demand (MWh per month)")
    ax.set_title("Monthly heat demand at T_min")
    ax2 = ax.twinx()
    ax2.plot(x, fd["t_out"].groupby(report_months(idx)).mean().reindex(months).to_numpy(), "-", color=COL["temp"], lw=1, alpha=0.8)
    ax2.set_ylabel("Outdoor temperature (degC)", color=COL["temp"])
    ax2.grid(False)
    ax2.spines["right"].set_visible(True)
    legend_src = ax

    ax = fig.add_subplot(gs[0, 2])
    cats = fd["scenarios"] if fd["hall"] is not None else [sc0]
    area = fd["water_area_m2"]
    ann = {c: [fd["hourly"][sc][c].sum() / 1000.0 * 1000.0 / area for sc in cats] for c in LAYERS}
    pos_top = _signed_bars(ax, np.arange(len(cats)), ann, 0.55)
    for k, sc in enumerate(cats):
        t = fd["hourly"][sc]["total"].sum() / area
        ax.text(k, pos_top[k] * 1.015, f"Total {t:,.0f}", ha="center", va="bottom", fontsize=8, fontweight="bold")
    ax.set_xticks(range(len(cats)))
    ax.set_xticklabels([f"hall {c}" if fd["hall"] is not None else "open air" for c in cats])
    ax.set_ylabel("Annual heat demand (kWh per m2 water)")
    ax.set_title("Total per m2 water")

    for col, key, lab in ((0, "cold", "Coldest operating week"), (1, "warm", "Warmest operating week")):
        ax = fig.add_subplot(gs[1, col])
        w = fd["weeks"]
        sl = slice(w[key], w[key] + w["n"])
        xx = idx[sl]
        _signed_area(ax, xx, {c: df[c].to_numpy()[sl] / 1000.0 for c in LAYERS})
        ax.step(xx, df["total"].to_numpy()[sl] / 1000.0, where="post", color=COL["total"], lw=1.2, label="Total")
        if fd["hall"] is not None:
            ax.step(xx, df[LATENT].to_numpy()[sl] / 1000.0, where="post", color=COL["memo"], lw=1, ls=":", label="Dehumidification (memo)")
        ax.set_title(f"{lab}, from {idx[w[key]]:%d %b}")
        ax.set_ylabel("Heat demand (MW)")
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))

    ax = fig.add_subplot(gs[1, 2])
    ax.axis("off")
    e = df.sum() / 1000.0
    lines = [f"Total demand   {e['total']:>9,.0f} MWh", f"  basins       {e['basins']:>9,.0f} MWh", f"  hall air     {e[HALL]:>9,.0f} MWh"]
    if has_dhw:
        lines += [f"  hot water    {e[DHW]:>9,.0f} MWh"]
    if fd["hall"] is not None:
        lines += [f"Hall share     {100 * e[HALL] / e['total']:>8.0f} %", f"Latent (memo)  {e[LATENT]:>9,.0f} MWh", "  not in the total"]
    lines += [f"Water area     {fd['water_area_m2']:>9,.0f} m2", f"Basins {fd['n_indoor']} in, {fd['n_outdoor']} out | zone {fd['zone']}"]
    ax.text(0.0, 1.0, "\n".join(lines), va="top", ha="left", family="monospace", fontsize=7.5)
    h, lab = legend_src.get_legend_handles_labels()
    keep = {}
    for a, b in zip(h, lab):
        keep.setdefault(b, a)
    ax.legend(
        list(keep.values()),
        list(keep.keys()),
        fontsize=6.5,
        ncol=2,
        loc="lower left",
        bbox_to_anchor=(-0.05, -0.04),
        columnspacing=0.8,
        handlelength=1.2,
    )
    fig.suptitle(
        f"{fd['name']} ({fd['badtyp']}): heat demand = basins + hall air side{' + hot water' if has_dhw else ''}{' | ' + group if group else ''}",
        fontsize=11,
        fontweight="bold",
        y=0.995,
    )
    viz.save(fig, path, dpi)


def plot_region(rd: dict, path: Path, dpi: int) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.8), gridspec_kw={"width_ratios": [1.2, 1.0, 1.0]})
    m = rd["monthly"]
    x = np.arange(len(m))
    ax = axes[0]
    bottom = np.zeros(len(m))
    layers_r = [("indoor basins", "#0072B2"), ("outdoor basins", "#56B4E9"), (HALL, COMP_COLOR[HALL])]
    has_dhw = DHW in m.columns and bool(m[DHW].any())
    if has_dhw:
        layers_r.append((DHW, COMP_COLOR[DHW]))
    for name, col in layers_r:
        v = m[name].to_numpy() / 1000.0
        ax.bar(x, v, 0.8, bottom=bottom, color=col, label=name, linewidth=0)
        bottom += v
    ax.set_xticks(x)
    ax.set_xticklabels([MON[i - 1] for i in m.index])
    ax.set_ylabel("Heat demand (GWh per month)")
    ax.set_title("Region: total = basins + hall air" + (" + hot water" if has_dhw else ""))
    ax2 = ax.twinx()
    ax2.plot(
        x,
        m["curtailed available (MWh el)"].to_numpy() / 1000.0,
        "o-",
        color=COL["curt"],
        lw=1.6,
        ms=4,
        label="Curtailed electricity available (right)",
    )
    ax2.set_ylabel("Curtailed electricity (GWh el per month)", color=COL["curt"])
    ax2.grid(False)
    ax2.spines["right"].set_visible(True)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.set_ylim(top=ax.get_ylim()[1] * 1.45)
    ax.legend(h1 + h2, l1 + l2, fontsize=7, loc="upper left")
    ax = axes[1]
    t = rd["by_type"].sort_values("total_mwh", ascending=False)
    xx = np.arange(len(t))
    ax.bar(xx, t["basins_mwh"] / 1000.0, 0.7, color="#0072B2", label="Basins", linewidth=0)
    ax.bar(xx, t["hall_sensible_mwh"] / 1000.0, 0.7, bottom=t["basins_mwh"] / 1000.0, color=COMP_COLOR[HALL], label=HALL, linewidth=0)
    if has_dhw:
        ax.bar(
            xx,
            t["dhw_mwh"] / 1000.0,
            0.7,
            bottom=(t["basins_mwh"] + t["hall_sensible_mwh"]) / 1000.0,
            color=COMP_COLOR[DHW],
            label=DHW,
            linewidth=0,
        )
    ax.set_xticks(xx)
    ax.set_xticklabels(t["badtyp"], rotation=20, ha="right")
    ax.set_ylabel("Annual heat demand (GWh)")
    ax.set_title("By facility type")
    ax.set_ylim(top=ax.get_ylim()[1] * 1.15)
    ax.legend(fontsize=7, loc="upper right")
    ax = axes[2]
    z = rd["by_zone"]
    xx = np.arange(len(z))
    ax.bar(xx - 0.2, z["total_mwh"] / 1000.0, 0.4, color="#0072B2", label="Heat demand (GWh th)", linewidth=0)
    ax.bar(xx + 0.2, z["curtailed_available_mwh_el"] / 1000.0, 0.4, color=COL["curt"], label="Curtailed electricity available (GWh el)", linewidth=0)
    ax.set_ylabel("GWh per year")
    ax.set_ylim(top=ax.get_ylim()[1] * 1.3)
    ax.set_xticks(xx)
    ax.set_xticklabels(z["zone"])
    ax.set_title("By curtailment zone")
    ax.legend(fontsize=7)
    fig.suptitle(
        f"Heat demand at T_min of all modelled pools, window of {rd['hours']} h, hall scenario {rd['hall_scenario']}",
        fontsize=11,
        fontweight="bold",
        y=0.995,
    )
    viz.save(fig, path, dpi)
