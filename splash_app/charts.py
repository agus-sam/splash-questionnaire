"""Plotly figures. Colours come from theme.py. No external assets."""
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

from splash_calc.economics import pv_factor
from splash_calc.params import Params
from splash_calc.profiles import LEVELS
from splash_calc.scenarios import CaseResult, Result

from .i18n import t
from .theme import AQUA, CORAL, GREEN, NAVY, SAND, SLATE, TEAL

FONT = dict(family="system-ui, -apple-system, Segoe UI, Roboto, sans-serif", size=13)
LEVEL_COLORS = {"pool_water": AQUA, "hall_air": SAND, "dhw": CORAL, "space_heating": SLATE}
LEVEL_LABELS = {
    "pool_water": {"de": "Beckenwasser", "en": "Pool water"},
    "hall_air": {"de": "Hallenluft", "en": "Hall air"},
    "dhw": {"de": "Warmwasser", "en": "Hot water"},
    "space_heating": {"de": "Raumheizung", "en": "Space heating"},
}
MONTH_START = np.cumsum([0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]) * 24
MONTHS = {
    "de": ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"],
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}


def _base(fig: go.Figure, height: int = 340, title: str | None = None) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=44 if title else 14, b=10), font=FONT,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        title=dict(text=title, x=0, font=dict(size=15)) if title else None,
        legend=dict(orientation="h", y=-0.2),
    )
    fig.update_xaxes(gridcolor="rgba(120,140,150,.2)", zerolinecolor="rgba(120,140,150,.5)")
    fig.update_yaxes(gridcolor="rgba(120,140,150,.2)", zerolinecolor="rgba(120,140,150,.5)")
    return fig


def energy_bars(c: CaseResult, lang: str) -> go.Figure:
    before_fuel = c.baseline.e_fuel_total
    hp = c.hp.res
    after_fuel = before_fuel - sum(hp.fuel_saved_kwh.values())
    fig = go.Figure()
    fig.add_bar(x=[t("baseline_heat", lang), t("tab_hp", lang)], y=[before_fuel / 1000, after_fuel / 1000],
                name="Brennstoff / Fuel" if lang == "de" else "Fuel", marker_color=SLATE,
                hovertemplate="%{y:,.0f} MWh<extra></extra>")
    fig.add_bar(x=[t("baseline_heat", lang), t("tab_hp", lang)], y=[0, hp.elec_kwh / 1000],
                name="Strom / Electricity" if lang == "de" else "Electricity", marker_color=AQUA,
                hovertemplate="%{y:,.0f} MWh<extra></extra>")
    fig.update_layout(barmode="stack", yaxis_title="MWh / a")
    return _base(fig, 320, "Endenergie" if lang == "de" else "Final energy")


def _size_label(key: str, lang: str) -> str:
    from splash_calc.flexsplash import parse_key

    _, size = parse_key(key)
    return f"{int(round(size * 100))} %"


def npv_ranges(res: Result, key: str, lang: str) -> go.Figure:
    from splash_calc.flexsplash import ALL_KEYS, parse_key

    year, _ = parse_key(key)
    names, central, lo, hi = [], [], [], []
    entries = []
    if res.central.hp is not None:
        entries.append((t("tab_hp", lang), lambda cr: cr.hp.econ.npv_eur))
    for k in ALL_KEYS:
        if parse_key(k)[0] == year:
            entries.append((f"{t('tab_flex', lang)} {_size_label(k, lang)}", lambda cr, k=k: cr.flex[k].econ.npv_eur))
    for name, f in entries:
        vals = [f(res.cases[c]) for c in ("pessimistic", "central", "optimistic")]
        names.append(name)
        central.append(vals[1] / 1000)
        lo.append((vals[1] - min(vals)) / 1000)
        hi.append((max(vals) - vals[1]) / 1000)
    colors = [GREEN if c >= 0 else CORAL for c in central]
    fig = go.Figure(go.Bar(
        x=names, y=central, marker_color=colors,
        error_y=dict(type="data", symmetric=False, array=hi, arrayminus=lo, color=NAVY, thickness=2, width=8),
        hovertemplate="%{y:,.0f} kEUR<extra></extra>",
    ))
    fig.update_layout(yaxis_title="kEUR", showlegend=False)
    return _base(fig, 340, "Kapitalwert mit Spanne" if lang == "de" else "NPV with range")


def size_comparison(res: Result, lang: str) -> go.Figure:
    """Absorbed curtailed power by heater size, 2025 and 2026 side by side."""
    from splash_calc.flexsplash import ALL_KEYS, parse_key
    from splash_calc.splash_engine import SIZES, YEARS

    fig = go.Figure()
    colors = {YEARS[0]: TEAL, YEARS[1]: SAND}
    for y in YEARS:
        ks = [k for k in ALL_KEYS if parse_key(k)[0] == y]
        full = res.central.flex[ks[0]].res.full_year
        name = str(y) if full else f"{y} ({'bis 22.11.' if lang == 'de' else 'to 22 Nov'})"
        fig.add_bar(x=[f"{int(s * 100)} %" for s in SIZES], y=[res.central.flex[k].res.absorbed_kwh_el / 1000 for k in ks],
                    name=name, marker_color=colors[y], hovertemplate="%{y:,.0f} MWh<extra></extra>")
    fig.update_layout(barmode="group", yaxis_title="MWh", xaxis_title="Heizstab-Größe (Anteil der Auslegungslast)" if lang == "de" else "Heater size (share of design load)")
    return _base(fig, 340, "Aufgenommener Überschussstrom je Heizstab-Größe" if lang == "de" else "Curtailed power absorbed by heater size")


def tornado(rows: list[dict], lang: str, top: int = 8) -> go.Figure:
    rows = rows[:top][::-1]
    base = rows[0]["base"] / 1000 if rows else 0
    fig = go.Figure()
    for key, color, name in (("pessimistic", CORAL, "pessimistic" if lang == "en" else "pessimistisch"),
                             ("optimistic", GREEN, "optimistic" if lang == "en" else "optimistisch")):
        fig.add_bar(y=[r["label"][:48] for r in rows], x=[(r[key] - r["base"]) / 1000 for r in rows], base=base,
                    orientation="h", name=name, marker_color=color,
                    hovertemplate="%{customdata:,.0f} kEUR<extra></extra>",
                    customdata=[r[key] / 1000 for r in rows])
    fig.update_layout(barmode="overlay", xaxis_title="kEUR")
    fig.add_vline(x=base, line_color=NAVY, line_width=1)
    return _base(fig, 360, t("tornado_title", lang))


def npv_vs_price(fo, params: Params, lang: str) -> go.Figure:
    n = int(params.get("lifetime_years"))
    r = float(params.get("wacc"))
    ge = (1 + float(params.get("inflation"))) * (1 + float(params.get("price_escalation_electricity"))) - 1
    slope = fo.res.absorbed_kwh_el * pv_factor(ge, r, n)       # EUR NPV per EUR/kWh
    p_now = fo.price_eff
    pmax = max(0.35, p_now * 1.4)
    xs = np.linspace(0, pmax, 60)
    ys = (fo.econ.npv_eur + slope * (p_now - xs)) / 1000
    fig = go.Figure()
    fig.add_scatter(x=xs, y=ys, mode="lines", line=dict(color=TEAL, width=3), name="NPV",
                    hovertemplate="%{x:.3f} EUR/kWh → %{y:,.0f} kEUR<extra></extra>")
    fig.add_hline(y=0, line_color=SLATE, line_dash="dot")
    fig.add_scatter(x=[p_now], y=[fo.econ.npv_eur / 1000], mode="markers", marker=dict(size=12, color=NAVY),
                    name="aktuell" if lang == "de" else "current")
    be = fo.econ.break_even_price
    if be is not None and 0 < be < pmax:
        fig.add_scatter(x=[be], y=[0], mode="markers+text", marker=dict(size=12, color=GREEN),
                        text=[f"{be:.3f}"], textposition="top center", name="Break-even")
    fig.update_layout(xaxis_title="EUR/kWh", yaxis_title="kEUR")
    return _base(fig, 340, "Kapitalwert je Preis des Überschussstroms" if lang == "de" else "NPV by price of curtailed power")


def benchmark(kwh_m2: float | None, bench: dict, lang: str, is_default: bool) -> go.Figure:
    labels = ["Min", "Median", "Mittel" if lang == "de" else "Mean", "Max"]
    vals = [bench["min"], bench["median"], bench["mean"], bench["max"]]
    fig = go.Figure(go.Bar(x=labels, y=vals, marker_color=[SLATE, TEAL, AQUA, SLATE],
                           hovertemplate="%{y:,.0f} kWh/m²<extra>UBA 2024</extra>"))
    if kwh_m2 and not is_default:
        fig.add_hline(y=kwh_m2, line_color=CORAL, line_width=3,
                      annotation_text=("Ihr Bad" if lang == "de" else "Your pool") + f": {kwh_m2:,.0f}",
                      annotation_position="top left")
    fig.update_layout(yaxis_title="kWh/(m² a)", showlegend=False)
    return _base(fig, 320, "Wärmeverbrauch je m² Wasserfläche" if lang == "de" else "Heat use per m² water surface")


def demand_reconciliation(levels: dict[str, np.ndarray], b, lang: str) -> go.Figure:
    """Model demand by use next to the useful heat the operator reported."""
    fig = go.Figure()
    xm = t("recon_model", lang)
    for lv in ("pool_water", "hall_air", "dhw"):
        if lv == "dhw" and not float(levels[lv].sum()) > 0:
            continue
        fig.add_bar(x=[xm], y=[float(levels[lv].sum()) / 1000], name=LEVEL_LABELS[lv][lang], marker_color=LEVEL_COLORS[lv],
                    hovertemplate="%{y:,.0f} MWh<extra>" + LEVEL_LABELS[lv][lang] + "</extra>")
    if b.reported_q_use_kwh:
        fig.add_bar(x=[t("recon_reported", lang)], y=[b.reported_q_use_kwh / 1000], name=t("recon_reported", lang),
                    marker_color=SLATE, hovertemplate="%{y:,.0f} MWh<extra></extra>")
    fig.update_layout(barmode="stack", yaxis_title="MWh / a")
    return _base(fig, 340, t("recon_title", lang))


def monthly_demand(levels: dict[str, np.ndarray], lang: str) -> go.Figure:
    fig = go.Figure()
    for lv in LEVELS:
        monthly = [float(levels[lv][MONTH_START[i]:MONTH_START[i + 1]].sum()) / 1000 for i in range(12)]
        fig.add_bar(x=MONTHS[lang], y=monthly, name=LEVEL_LABELS[lv][lang], marker_color=LEVEL_COLORS[lv])
    fig.update_layout(barmode="stack", yaxis_title="MWh")
    return _base(fig, 340, "Wärmebedarf je Monat (SPLASH-Modell)" if lang == "de" else "Heat demand by month (SPLASH model)")


def cashflow(c: CaseResult, key: str, lang: str) -> go.Figure:
    fig = go.Figure()
    if c.hp is not None:
        n = len(c.hp.econ.cumulative_cashflow)
        fig.add_scatter(x=list(range(n)), y=[v / 1000 for v in c.hp.econ.cumulative_cashflow], mode="lines", name=t("tab_hp", lang),
                        line=dict(color=TEAL, width=3))
    fl = c.flex[key].econ.cumulative_cashflow
    fig.add_scatter(x=list(range(len(fl))), y=[v / 1000 for v in fl], mode="lines",
                    name=f"{t('tab_flex', lang)} {_size_label(key, lang)}", line=dict(color=SAND, width=3))
    fig.add_hline(y=0, line_color=SLATE, line_dash="dot")
    fig.update_layout(xaxis_title=t("years", lang), yaxis_title="kEUR")
    return _base(fig, 320, "Kumulierter Cashflow (undiskontiert)" if lang == "de" else "Cumulative cash flow (undiscounted)")
