"""Figures for the flexible heating scenario. All series come from the SPLASH model run."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from splash_calc.flexsplash import FlexOutcome, parse_key

from .charts import MONTHS, _base
from .i18n import t
from .theme import AQUA, CORAL, GREEN, NAVY, SAND, SLATE, TEAL

GRID = "rgba(120,140,150,.2)"


def _fx(fig: go.Figure, height: int, title: str | None = None) -> go.Figure:
    fig = _base(fig, height, title)
    fig.update_layout(margin=dict(l=58, r=52, t=48 if title else 30, b=88), legend=dict(orientation="h", y=-0.3))
    return fig


def _local(r) -> pd.DatetimeIndex:
    idx = pd.date_range(r.start_local, periods=len(r.hourly_el), freq="h")
    return idx.tz_localize(None) if idx.tz is not None else idx


def _month_sum(idx: pd.DatetimeIndex, x: np.ndarray) -> np.ndarray:
    return np.bincount(idx.month - 1, weights=np.asarray(x, dtype=float), minlength=12)[:12]


def _grid(idx: pd.DatetimeIndex, x: np.ndarray) -> tuple[np.ndarray, list]:
    days = (idx.normalize() - idx[0].normalize()).days.to_numpy()
    n_days = int(days.max()) + 1
    z = np.full((24, n_days), np.nan)
    z[idx.hour.to_numpy(), days] = np.asarray(x, dtype=float)
    dates = [(idx[0].normalize() + pd.Timedelta(days=int(d))).strftime("%Y-%m-%d") for d in range(n_days)]
    return z, dates


def _scale(color: str) -> list:
    return [[0.0, "rgba(255,255,255,0)"], [0.001, "rgba(255,255,255,1)"], [1.0, color]]


# ------------------------------------------------------------------ year view
def year_heatmaps(fo: FlexOutcome, lang: str) -> go.Figure:
    """Hour of day against day of year: curtailment in the zone, power taken by the heater, stored heat."""
    r = fo.res
    idx = _local(r)
    cap = max(r.e_max_kwh, 1e-9)
    rows = [
        (t("fx_hm_curt", lang), r.hourly_available.astype(float), SLATE, "%{z:.0f}", [0, 1]),
        (t("fx_hm_power", lang), r.hourly_el, TEAL, "%{z:,.0f} kW", None),
        (t("fx_hm_store", lang), r.hourly_soc / cap * 100.0, SAND, "%{z:.0f} %", [0, 100]),
    ]
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.07, subplot_titles=[x[0] for x in rows])
    for i, (_, series, color, hover, zr) in enumerate(rows, start=1):
        z, dates = _grid(idx, series)
        fig.add_trace(go.Heatmap(
            z=z, x=dates, y=list(range(24)), colorscale=_scale(color), zmin=zr[0] if zr else 0, zmax=zr[1] if zr else None,
            showscale=False, hovertemplate="%{x} %{y}:00<br>" + hover + "<extra></extra>", xgap=0, ygap=0), row=i, col=1)
        fig.update_yaxes(title_text=t("fx_hour", lang), autorange="reversed", row=i, col=1, dtick=6)
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(showgrid=False)
    fig.update_xaxes(tickformat="%b", dtick="M1", showticklabels=True, row=3, col=1)
    fig.update_yaxes(tickvals=[0, 6, 12, 18, 23], showticklabels=True)
    return _fx(fig, 660)


def monthly_absorption(fo: FlexOutcome, lang: str) -> go.Figure:
    r = fo.res
    idx = _local(r)
    absorbed = _month_sum(idx, r.hourly_el) / 1000
    displaced = _month_sum(idx, r.hourly_displaced) / 1000
    hours = _month_sum(idx, r.hourly_available.astype(float))
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(x=MONTHS[lang], y=absorbed, name=t("fx_absorbed", lang), marker_color=TEAL,
                hovertemplate="%{y:,.1f} MWh<extra></extra>")
    fig.add_bar(x=MONTHS[lang], y=displaced, name=t("fx_displaced", lang), marker_color=SAND,
                hovertemplate="%{y:,.1f} MWh<extra></extra>")
    fig.add_scatter(x=MONTHS[lang], y=hours, name=t("fx_curt_hours", lang), mode="lines+markers",
                    line=dict(color=NAVY, width=2), secondary_y=True, hovertemplate="%{y:,.0f} h<extra></extra>")
    fig.update_layout(barmode="group")
    fig.update_yaxes(title_text="MWh", secondary_y=False)
    fig.update_yaxes(title_text=t("fx_hours", lang), secondary_y=True, showgrid=False, nticks=6, tickformat=",.0f", rangemode="tozero")
    return _fx(fig, 340, t("fx_monthly_title", lang))


def monthly_coverage(fo: FlexOutcome, lang: str) -> go.Figure:
    """How much of the model heat demand the curtailed power covers in each month."""
    r = fo.res
    idx = _local(r)
    demand = _month_sum(idx, r.hourly_demand) / 1000
    displaced = _month_sum(idx, r.hourly_displaced) / 1000
    rest = np.clip(demand - displaced, 0, None)
    share = np.divide(displaced, demand, out=np.zeros(12), where=demand > 0) * 100
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(x=MONTHS[lang], y=displaced, name=t("fx_cover_curt", lang), marker_color=TEAL,
                hovertemplate="%{y:,.1f} MWh<extra></extra>")
    fig.add_bar(x=MONTHS[lang], y=rest, name=t("fx_cover_rest", lang), marker_color="rgba(91,112,131,.35)",
                hovertemplate="%{y:,.1f} MWh<extra></extra>")
    fig.add_scatter(x=MONTHS[lang], y=share, name=t("fx_cover_share", lang), mode="lines+markers",
                    line=dict(color=CORAL, width=2), secondary_y=True, hovertemplate="%{y:.1f} %<extra></extra>")
    fig.update_layout(barmode="stack")
    fig.update_yaxes(title_text="MWh", secondary_y=False)
    fig.update_yaxes(title_text="%", secondary_y=True, showgrid=False, rangemode="tozero", nticks=6, tickformat=".0f")
    return _fx(fig, 340, t("fx_cover_title", lang))


def duration_curve(fo: FlexOutcome, lang: str) -> go.Figure:
    """Hourly heater power in descending order, with the rated electrical capacity."""
    r = fo.res
    p = np.sort(r.hourly_el[r.hourly_el > 1e-6])[::-1]
    fig = go.Figure()
    fig.add_scatter(x=np.arange(1, len(p) + 1), y=p, mode="lines", fill="tozeroy", line=dict(color=TEAL, width=2),
                    fillcolor="rgba(14,124,134,.25)", name=t("fx_power", lang),
                    hovertemplate="%{x} h: %{y:,.0f} kW<extra></extra>")
    fig.add_hline(y=r.capacity_kw_el, line_color=CORAL, line_dash="dash",
                  annotation_text=f"{t('fx_rated', lang)}: {r.capacity_kw_el:,.0f} kW", annotation_position="top right")
    flh = r.absorbed_kwh_el / r.capacity_kw_el if r.capacity_kw_el > 0 else 0.0
    fig.update_layout(xaxis_title=t("fx_hours_run", lang), yaxis_title="kW el", showlegend=False)
    return _fx(fig, 340, t("fx_duration_title", lang, h=f"{flh:,.0f}"))


# ------------------------------------------------------------------ energy flow
def energy_flow(fo: FlexOutcome, lang: str) -> go.Figure:
    r = fo.res
    a = r.absorbed_kwh_el / 1000
    heat = r.heat_kwh_th / 1000
    disp = r.displaced_kwh_th / 1000
    extra = max(heat - disp, 0.0)
    conv_loss = max(a - heat, 0.0)
    labels = [t("fx_n_absorbed", lang), t("fx_n_heat", lang), t("fx_n_loss", lang), t("fx_n_displaced", lang),
              t("fx_n_extra", lang)]
    src = [0, 0, 1, 1]
    dst = [1, 2, 3, 4]
    val = [heat, conv_loss, disp, extra]
    colors = ["rgba(14,124,134,.45)", "rgba(209,73,91,.35)", "rgba(46,158,107,.45)", "rgba(209,73,91,.35)"]
    fig = go.Figure(go.Sankey(
        arrangement="snap",
        node=dict(label=labels, pad=28, thickness=20, color=[TEAL, AQUA, CORAL, GREEN, CORAL],
                  hovertemplate="%{label}: %{value:,.0f} MWh<extra></extra>"),
        link=dict(source=src, target=dst, value=val, color=colors, hovertemplate="%{value:,.0f} MWh<extra></extra>"),
    ))
    ratio = disp / a * 100 if a > 0 else 0.0
    return _fx(fig, 380, t("fx_flow_title", lang, p=f"{ratio:,.0f}"))


# ------------------------------------------------------------------ week view
def best_week(fo: FlexOutcome) -> int:
    """Index of the week (0-based) with the most absorbed energy."""
    p = fo.res.hourly_el
    n_weeks = max(len(p) // 168, 1)
    sums = [float(p[i * 168:(i + 1) * 168].sum()) for i in range(n_weeks)]
    return int(np.argmax(sums)) if max(sums) > 0 else 0


def n_weeks(fo: FlexOutcome) -> int:
    return max(len(fo.res.hourly_el) // 168, 1)


def week_dispatch(fo: FlexOutcome, week: int, lang: str) -> go.Figure:
    r = fo.res
    idx = _local(r)
    sl = slice(week * 168, min((week + 1) * 168, len(idx)))
    x = idx[sl]
    cap = max(r.e_max_kwh, 1e-9)
    peak = max(float(r.hourly_demand[sl].max()), float(r.hourly_el[sl].max()), 1.0)
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(x=x, y=r.hourly_available[sl].astype(float) * peak * 1.05, name=t("fx_curt_window", lang),
                marker=dict(color="rgba(25,181,196,.14)", line_width=0), hoverinfo="skip")
    fig.add_scatter(x=x, y=r.hourly_demand[sl], mode="lines", line=dict(color=SLATE, width=2, shape="hv"),
                    name=t("fx_demand", lang), hovertemplate="%{y:,.0f} kW<extra></extra>")
    fig.add_scatter(x=x, y=r.hourly_displaced[sl], mode="lines", fill="tozeroy", line=dict(color=GREEN, width=1.5, shape="hv"),
                    fillcolor="rgba(46,158,107,.28)", name=t("fx_displaced_kw", lang), hovertemplate="%{y:,.0f} kW<extra></extra>")
    fig.add_scatter(x=x, y=r.hourly_el[sl], mode="lines", line=dict(color=TEAL, width=2.5, shape="hv"),
                    name=t("fx_power", lang), hovertemplate="%{y:,.0f} kW<extra></extra>")
    fig.add_scatter(x=x, y=r.hourly_soc[sl] / cap * 100, mode="lines", line=dict(color=SAND, width=2.5),
                    name=t("fx_store_pct", lang), secondary_y=True, hovertemplate="%{y:.0f} %<extra></extra>")
    fig.update_layout(bargap=0)
    fig.update_yaxes(title_text="kW", secondary_y=False)
    fig.update_yaxes(title_text="%", range=[0, 105], tickvals=[0, 25, 50, 75, 100], secondary_y=True, showgrid=False)
    return _fx(fig, 400, t("fx_week_title", lang, d=f"{x[0]:%d.%m.%Y}"))


# ------------------------------------------------------------------ sizes
def size_efficiency(res, year: int, lang: str) -> go.Figure:
    """Full-load hours per heater size and the NPV, to show where larger heaters stop paying."""
    keys = sorted((k for k in res.central.flex if parse_key(k)[0] == year), key=lambda k: parse_key(k)[1])
    sizes = [f"{int(parse_key(k)[1] * 100)} %" for k in keys]
    flh = [res.central.flex[k].res.absorbed_kwh_el / max(res.central.flex[k].res.capacity_kw_el, 1e-9) for k in keys]
    npv = [res.central.flex[k].econ.npv_eur / 1000 for k in keys]
    marg = [None]
    for a, b in zip(keys[:-1], keys[1:], strict=False):
        ra, rb = res.central.flex[a].res, res.central.flex[b].res
        dk = rb.capacity_kw_el - ra.capacity_kw_el
        marg.append((rb.absorbed_kwh_el - ra.absorbed_kwh_el) / dk if dk > 0 else None)
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(x=sizes, y=flh, name=t("fx_flh", lang), marker_color=AQUA, hovertemplate="%{y:,.0f} h<extra></extra>")
    fig.add_bar(x=sizes, y=marg, name=t("fx_marginal", lang), marker_color=SAND, hovertemplate="%{y:,.0f} h<extra></extra>")
    fig.add_scatter(x=sizes, y=npv, name="NPV (kEUR)", mode="lines+markers", line=dict(color=NAVY, width=3),
                    secondary_y=True, hovertemplate="%{y:,.0f} kEUR<extra></extra>")
    fig.update_layout(barmode="group", xaxis_title=t("fx_size_axis", lang))
    fig.update_yaxes(title_text=t("fx_hours_unit", lang), secondary_y=False)
    fig.update_yaxes(title_text="kEUR", secondary_y=True, showgrid=False, nticks=6, tickformat=",.0f")
    fig.update_xaxes(type="category")
    return _fx(fig, 360, t("fx_size_title", lang))
