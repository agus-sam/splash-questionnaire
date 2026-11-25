"""v1.4 figures: thermal battery, Sankey, technology scatter, calendar, dispatch explorer, investment set.

Pure functions of the calculation result. Colours: existing heating slate, heat pump blue,
resistive heater teal.
"""
from __future__ import annotations

import html

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from splash_calc.economics import pv_factor
from splash_calc.flexsplash import FlexOutcome, parse_key
from splash_calc.scenarios import CaseResult, Result

from .charts import _base
from .flexcharts import _fx, _grid, _local
from .theme import AQUA, CORAL, GREEN, NAVY, SAND, SLATE, TEAL

C_EXIST = SLATE
C_HP = "#3B6FD1"
C_HEATER = TEAL
TECH_NAME = {
    "existing": {"de": "Bestehende Heizung", "en": "Existing heating"},
    "hp": {"de": "Wärmepumpe", "en": "Heat pump"},
    "flex": {"de": "Elektro-Heizstab", "en": "Electric resistance heater"},
}
TECH_COLOR = {"existing": C_EXIST, "hp": C_HP, "flex": C_HEATER}
WATER_KWH_PER_M3K = 1.163        # physical constant: specific heat of water


def L(lg: str, de: str, en: str) -> str:
    return de if lg == "de" else en


# ------------------------------------------------------------ thermal battery
def battery_numbers(res: Result, fo: FlexOutcome, buffer_m3: float | None, buffer_k: float) -> dict:
    sp = res.context.splash
    r = fo.res
    soc = np.asarray(r.hourly_soc, float)
    avail = np.asarray(r.hourly_available_kw if r.hourly_available_kw is not None else r.hourly_available, float) > 0
    head = np.maximum(r.e_max_kwh - soc, 0.0)
    buf = (buffer_m3 or 0.0) * WATER_KWH_PER_M3K * buffer_k
    return {
        "per_k": sp.storage_per_k_kwh,
        "band_k": r.band_k,
        "theoretical": r.e_max_kwh,
        "usable_max": float(soc.max()) if soc.size else 0.0,
        "free_in_window": float(head[avail].mean()) if avail.any() else float(r.e_max_kwh),
        "buffer": buf,
        "volume_m3": float(sum(b.volume_m3 for b in sp.basins)),
        "area_m2": float(sum(b.area_m2 for b in sp.basins)),
    }


def battery_svg(n: dict, lg: str) -> str:
    """Signature schematic: a pool tank whose temperature band is filled in proportion to use."""
    th = max(n["theoretical"], 1e-9)
    use = min(n["usable_max"] / th, 1.0)
    free = min(n["free_in_window"] / th, 1.0)
    h = 150
    y_use = 30 + h * (1 - use)
    y_free = 30 + h * (1 - free)
    f = lambda v: f"{v:,.0f}".replace(",", "." if lg == "de" else ",")  # noqa: E731
    lab = {
        "top": L(lg, "Obere Grenze", "Upper limit"), "bot": L(lg, "Untere Grenze (Sollwert)", "Lower limit (setpoint)"),
        "th": L(lg, "Theoretisch", "Theoretical"), "us": L(lg, "Modelliert nutzbar", "Modelled usable"),
        "fr": L(lg, "Frei im Überschussfenster", "Free in curtailment window"),
    }
    buf = ""
    if n["buffer"] > 0:
        buf = (f'<rect x="250" y="80" width="46" height="100" rx="8" fill="#fff" stroke="{C_HP}" stroke-width="2"/>'
               f'<text x="273" y="196" text-anchor="middle" font-size="11" fill="{NAVY}">{html.escape(L(lg, "Puffer", "Buffer"))} '
               f'{f(n["buffer"])} kWh</text>')
    return (
        f'<svg viewBox="0 0 560 215" role="img" aria-label="{html.escape(L(lg, "Schema Wärmespeicher Becken", "Thermal battery schematic"))}" '
        f'style="width:100%;max-width:640px">'
        f'<rect x="20" y="30" width="200" height="{h}" rx="10" fill="#E8F7F8" stroke="{TEAL}" stroke-width="2"/>'
        f'<rect x="21" y="{y_use:.1f}" width="198" height="{30 + h - y_use:.1f}" fill="{AQUA}" opacity=".55"/>'
        f'<rect x="21" y="{y_free:.1f}" width="198" height="{30 + h - y_free:.1f}" fill="{TEAL}" opacity=".35"/>'
        f'<line x1="14" y1="30" x2="226" y2="30" stroke="{CORAL}" stroke-width="2" stroke-dasharray="5 3"/>'
        f'<line x1="14" y1="{30 + h}" x2="226" y2="{30 + h}" stroke="{SLATE}" stroke-width="2"/>'
        f'<text x="20" y="22" font-size="11" fill="{CORAL}">{html.escape(lab["top"])} (+{n["band_k"]:.1f} K)</text>'
        f'<text x="20" y="{30 + h + 15}" font-size="11" fill="{SLATE}">{html.escape(lab["bot"])}</text>'
        f'<text x="120" y="{30 + h / 2:.0f}" text-anchor="middle" font-size="22" font-weight="700" fill="{NAVY}">{f(n["theoretical"])} kWh</text>'
        f'<text x="120" y="{30 + h / 2 + 18:.0f}" text-anchor="middle" font-size="11" fill="{NAVY}">{n["per_k"]:,.0f} kWh/K</text>'
        f'<g font-size="12" fill="{NAVY}">'
        f'<rect x="320" y="40" width="12" height="12" fill="#E8F7F8" stroke="{TEAL}"/><text x="340" y="51">{html.escape(lab["th"])}: {f(n["theoretical"])} kWh</text>'
        f'<rect x="320" y="68" width="12" height="12" fill="{AQUA}" opacity=".7"/><text x="340" y="79">{html.escape(lab["us"])}: {f(n["usable_max"])} kWh</text>'
        f'<rect x="320" y="96" width="12" height="12" fill="{TEAL}" opacity=".5"/><text x="340" y="107">{html.escape(lab["fr"])}: {f(n["free_in_window"])} kWh</text>'
        f'</g>{buf}</svg>'
    )


# --------------------------------------------------------------------- Sankey
def _eta_mix(c: CaseResult) -> float:
    return c.baseline.mix_eta


def sankey(c: CaseResult, key: str, scenario: str, lg: str, eur: str = "") -> go.Figure:
    """scenario: existing | flex | hp. Quantities in MWh per year."""
    b = c.baseline
    fuel = b.e_fuel_total / 1000
    eta = _eta_mix(c)
    labels: list[str] = []
    colors: list[str] = []

    def node(name: str, color: str) -> int:
        labels.append(name)
        colors.append(color)
        return len(labels) - 1

    src: list[int] = []
    dst: list[int] = []
    val: list[float] = []
    lcol: list[str] = []

    def link(a: int, z: int, v: float, color: str) -> None:
        if v > 1e-9:
            src.append(a)
            dst.append(z)
            val.append(v)
            lcol.append(color)

    heat = node(L(lg, "Nutzwärme", "Useful heat"), TEAL)
    loss = node(L(lg, "Verluste", "Losses"), CORAL)
    if scenario == "existing":
        f = node(L(lg, "Brennstoff / Fernwärme", "Fuel / district heat"), C_EXIST)
        link(f, heat, fuel * eta, "rgba(91,112,131,.45)")
        link(f, loss, fuel * (1 - eta), "rgba(209,73,91,.3)")
    elif scenario == "flex":
        fo = c.flex[key]
        saved = sum(fo.res.fuel_saved_kwh.values()) / 1000
        rest = max(fuel - saved, 0.0)
        f = node(L(lg, "Restbrennstoff", "Remaining fuel"), C_EXIST)
        el = node(L(lg, "Überschussstrom im Heizstab", "Curtailed power in heater"), C_HEATER)
        link(f, heat, rest * eta, "rgba(91,112,131,.45)")
        link(f, loss, rest * (1 - eta), "rgba(209,73,91,.3)")
        h = fo.res.heat_kwh_th / 1000
        a = fo.res.absorbed_kwh_el / 1000
        link(el, heat, h, "rgba(14,124,134,.5)")
        link(el, loss, max(a - h, 0.0), "rgba(209,73,91,.3)")
    else:
        hp = c.hp
        if hp is None:
            return go.Figure()
        saved = sum(hp.res.fuel_saved_kwh.values()) / 1000
        rest = max(fuel - saved, 0.0)
        f = node(L(lg, "Restbrennstoff", "Remaining fuel"), C_EXIST)
        el = node(L(lg, "Netzstrom (hält T_min)", "Grid electricity (holds T_min)"), C_HP)
        ec = node(L(lg, "Überschussstrom (lädt bis T_max)", "Curtailed power (charges to T_max)"), C_HEATER)
        amb = node(L(lg, "Umweltwärme", "Ambient heat"), AQUA)
        link(f, heat, rest * eta, "rgba(91,112,131,.45)")
        link(f, loss, rest * (1 - eta), "rgba(209,73,91,.3)")
        e_g = hp.res.elec_grid_kwh / 1000
        e_c = hp.res.elec_curtailed_kwh / 1000
        h = hp.res.heat_hp_kwh / 1000
        link(el, heat, e_g, "rgba(59,111,209,.5)")
        link(ec, heat, e_c, "rgba(14,124,134,.5)")
        link(amb, heat, max(h - e_g - e_c, 0.0), "rgba(25,181,196,.5)")
    fig = go.Figure(go.Sankey(
        arrangement="snap",
        node=dict(label=labels, color=colors, pad=26, thickness=20,
                  hovertemplate="%{label}: %{value:,.0f} MWh/a<extra></extra>"),
        link=dict(source=src, target=dst, value=val, color=lcol, hovertemplate="%{value:,.0f} MWh/a<extra></extra>"),
    ))
    title = TECH_NAME[scenario][lg] + (f" · {eur}" if eur else "")
    fig = _base(fig, 330, title)
    fig.update_layout(margin=dict(l=10, r=10, t=44, b=10))
    return fig


# ------------------------------------------------------------ technology scatter
def tech_points(res: Result, year: int) -> list[dict]:
    c = res.central
    pts = []
    for k, fo in sorted(c.flex.items(), key=lambda kv: parse_key(kv[0])[1]):
        y, s = parse_key(k)
        if y != year:
            continue
        pts.append({"id": k, "tech": "flex", "name": f"{TECH_NAME['flex']['en']} {int(round(s * 100))} %",
                    "saving": fo.econ.net_saving_eur_y1, "co2": fo.co2.net_curtailed_zero_t_y1 * 1.0,
                    "invest": fo.investment, "econ": fo.econ, "fo": fo,
                    "elec_kwh": fo.res.absorbed_kwh_el, "price": fo.price_eff})
    if c.hp is not None:
        pts.append({"id": "hp", "tech": "hp", "name": TECH_NAME["hp"]["en"], "saving": c.hp.econ.net_saving_eur_y1,
                    "co2": c.hp.co2.net_curtailed_zero_t_y1, "invest": c.hp.investment, "econ": c.hp.econ, "fo": None,
                    "elec_kwh": c.hp.res.elec_kwh, "price": c.hp.price_eff or c.elec_price})
    return pts


def tech_scatter(pts: list[dict], lg: str) -> go.Figure:
    fig = go.Figure()
    mx = max([p["invest"] for p in pts] + [1.0])
    for p in pts:
        fig.add_scatter(
            x=[p["saving"]], y=[p["co2"]], mode="markers+text", name=p["name"], customdata=[p["id"]],
            text=[p["name"].replace(TECH_NAME["flex"]["en"], L(lg, "Heizstab", "Heater")
                                    ).replace(TECH_NAME["hp"]["en"], TECH_NAME["hp"][lg])],
            textposition="top center",
            marker=dict(size=[18 + 52 * (p["invest"] / mx) ** 0.5], color=TECH_COLOR[p["tech"]], opacity=.8,
                        line=dict(color="#fff", width=2)),
            hovertemplate=(f"{p['name']}<br>" + L(lg, "Investition", "Investment") + f": {p['invest']:,.0f} EUR<br>"
                           + L(lg, "Einsparung", "Saving") + ": %{x:,.0f} EUR/a<br>CO₂: %{y:,.1f} t/a<extra></extra>"))
    fig.add_vline(x=0, line_color=SLATE, line_dash="dot")
    fig.add_hline(y=0, line_color=SLATE, line_dash="dot")
    fig.update_layout(xaxis_title=L(lg, "Jährliche Kosteneinsparung (EUR/a)", "Annual cost savings (EUR/a)"),
                      yaxis_title=L(lg, "CO₂-Minderung (t/a)", "CO₂ reduction (t/a)"), showlegend=False, clickmode="event+select")
    return _base(fig, 400, L(lg, "Technologien im Vergleich (Blasengröße = Investition)",
                              "Technologies compared (bubble size = investment)"))


# ------------------------------------------------------------------- calendar
METRICS = ("available", "heater", "storage")


def calendar(fo: FlexOutcome, metric: str, lg: str) -> go.Figure:
    r = fo.res
    idx = _local(r)
    if metric == "available":
        x = np.asarray(r.hourly_available_kw if r.hourly_available_kw is not None else r.hourly_available, float)
        unit, color, name = "kW", TEAL, L(lg, "Verfügbare Überschussleistung", "Available curtailed power")
    elif metric == "heater":
        x, unit, color, name = np.asarray(r.hourly_el, float), "kW el", C_HEATER, L(lg, "Strom im Heizstab", "Heater electricity")
    else:
        x = np.asarray(r.hourly_soc, float) / max(r.e_max_kwh, 1e-9) * 100
        unit, color, name = "%", SAND, L(lg, "Speicherauslastung", "Storage utilisation")
    z, dates = _grid(idx, x)
    fig = go.Figure(go.Heatmap(
        z=z, x=dates, y=list(range(24)), zmin=0, colorscale=[[0, "#F4FAFB"], [1, color]],
        colorbar=dict(title=unit), hovertemplate="%{x} %{y}:00<br>%{z:,.0f} " + unit + "<extra></extra>"))
    fig.update_layout(yaxis_title=L(lg, "Stunde", "Hour"), yaxis=dict(autorange="reversed", dtick=6))
    return _fx(fig, 330, name)


# ----------------------------------------------------------- dispatch explorer
def hp_view(res: Result):
    """The rule-based heat pump in the shape that the calendar and dispatch figures read (reference year 2025)."""
    from types import SimpleNamespace

    h = res.central.hp
    if h is None or h.res.dispatch != "rule":
        return None
    ref = next(fo for k, fo in res.central.flex.items() if parse_key(k)[0] == 2025)
    r = SimpleNamespace(
        hourly_available_kw=h.res.hp_avail_hourly, hourly_available=h.res.hp_avail_hourly > 0, hourly_el=h.res.hp_curt_hourly,
        hourly_soc=h.res.hp_soc_hourly, e_max_kwh=h.res.e_max_kwh or ref.res.e_max_kwh, band_k=ref.res.band_k,
        hourly_demand=ref.res.hourly_demand, start_local=h.res.start_local,
        grid_hourly=h.res.hp_grid_hourly, heat_hourly=h.res.hp_curt_heat_hourly)
    return SimpleNamespace(res=r)


def dispatch_day(fo: FlexOutcome, params_eta: float, day, days: int, lg: str) -> go.Figure | None:
    import pandas as pd

    r = fo.res
    idx = _local(r)
    start = pd.Timestamp(day).normalize()
    m = (idx >= start) & (idx < start + pd.Timedelta(days=days))
    if not m.any():
        return None
    x = idx[m]
    avail = np.asarray(r.hourly_available_kw if r.hourly_available_kw is not None else r.hourly_available, float)[m]
    el = np.asarray(r.hourly_el, float)[m]
    dem = np.asarray(r.hourly_demand, float)[m]
    soc = np.asarray(r.hourly_soc, float)[m]
    per_k = max(r.e_max_kwh / max(r.band_k, 1e-9), 1e-9)
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(x=x, y=avail, name=L(lg, "Überschussleistung (Zone)", "Curtailed power (zone)"),
                marker=dict(color="rgba(25,181,196,.25)", line_width=0), hovertemplate="%{y:,.0f} kW<extra></extra>")
    fig.add_scatter(x=x, y=el, name=L(lg, "Strom aus Überschuss", "Electricity from curtailment"), mode="lines",
                    line=dict(color=C_HEATER, width=2.5, shape="hv"), hovertemplate="%{y:,.0f} kW<extra></extra>")
    heat = getattr(r, "heat_hourly", None)
    heat = np.asarray(heat, float)[m] if heat is not None else el * params_eta
    fig.add_scatter(x=x, y=heat, name=L(lg, "Nutzwärme aus Überschussstrom", "Useful heat from curtailed power"), mode="lines",
                    line=dict(color=GREEN, width=1.5, shape="hv"), hovertemplate="%{y:,.0f} kW<extra></extra>")
    grid = getattr(r, "grid_hourly", None)
    if grid is not None:
        fig.add_scatter(x=x, y=np.asarray(grid, float)[m], name=L(lg, "Netzstrom (hält T_min)", "Grid electricity (holds T_min)"),
                        mode="lines", line=dict(color=C_HP, width=1.5, dash="dot", shape="hv"),
                        hovertemplate="%{y:,.0f} kW<extra></extra>")
    fig.add_scatter(x=x, y=dem, name=L(lg, "Wärmebedarf", "Heat demand"), mode="lines",
                    line=dict(color=SLATE, width=2, shape="hv"), hovertemplate="%{y:,.0f} kW<extra></extra>")
    fig.add_scatter(x=x, y=soc / max(r.e_max_kwh, 1e-9) * 100, name=L(lg, "Speicherstand (%)", "State of charge (%)"), mode="lines",
                    line=dict(color=SAND, width=2.5), secondary_y=True, hovertemplate="%{y:.0f} %<extra></extra>")
    fig.add_scatter(x=x, y=soc / per_k, name=L(lg, "Temperatur über Sollwert (K, modelliert)", "Temperature above setpoint (K, modelled)"),
                    mode="lines", line=dict(color=CORAL, width=1.5, dash="dot"), secondary_y=True,
                    hovertemplate="%{y:.2f} K<extra></extra>")
    fig.update_yaxes(title_text="kW", secondary_y=False)
    fig.update_yaxes(title_text="% / K", secondary_y=True, showgrid=False)
    return _fx(fig, 400, L(lg, "Stundenverlauf", "Hourly dispatch") + f" {start:%d.%m.%Y}")


def best_day(fo: FlexOutcome):
    import pandas as pd

    idx = _local(fo.res)
    s = pd.Series(np.asarray(fo.res.hourly_el, float), index=idx).resample("D").sum()
    return (s.idxmax() if s.max() > 0 else s.index[0]).date()


# --------------------------------------------------------- investment / break-even
def invest_compare(pts: list[dict], lg: str) -> go.Figure:
    names = [p["name"] for p in pts]
    fig = go.Figure()
    fig.add_bar(x=names, y=[p["econ"].investment_eur / 1000 for p in pts], name=L(lg, "Investition brutto", "Gross investment"),
                marker_color=[TECH_COLOR[p["tech"]] for p in pts])
    fig.add_bar(x=names, y=[p["econ"].subsidy_eur / 1000 for p in pts], name=L(lg, "Förderung", "Grant"), marker_color=GREEN)
    fig.update_layout(barmode="group", yaxis_title="kEUR")
    return _base(fig, 320, L(lg, "Investition und Förderung", "Investment and grant"))


def waterfall(econ, lg: str, title: str) -> go.Figure:
    fig = go.Figure(go.Waterfall(
        x=[L(lg, "Brennstoff gespart", "Fuel saved"), L(lg, "Stromkosten", "Electricity"), "O&M", L(lg, "Netto Jahr 1", "Net year 1")],
        y=[econ.fuel_saving_eur_y1, -econ.electricity_cost_eur_y1, -econ.om_eur_y, econ.net_saving_eur_y1],
        measure=["relative", "relative", "relative", "total"],
        increasing=dict(marker=dict(color=GREEN)), decreasing=dict(marker=dict(color=CORAL)), totals=dict(marker=dict(color=NAVY)),
        hovertemplate="%{y:,.0f} EUR<extra></extra>"))
    fig.update_layout(yaxis_title="EUR / " + L(lg, "Jahr", "year"), showlegend=False)
    return _base(fig, 320, title)


def discounted_cumulative(pts: list[dict], wacc: float, lg: str) -> go.Figure:
    fig = go.Figure()
    for p in pts:
        cum = p["econ"].cumulative_cashflow
        acc = [cum[0]]
        for t in range(1, len(cum)):
            acc.append(acc[-1] + (cum[t] - cum[t - 1]) / (1 + wacc) ** t)
        fig.add_scatter(x=list(range(len(acc))), y=[v / 1000 for v in acc], mode="lines", name=p["name"],
                        line=dict(color=TECH_COLOR[p["tech"]], width=3, dash="solid" if p["id"] in ("hp", "2025_200", "2026_200") else "dot"))
    fig.add_hline(y=0, line_color=SLATE, line_dash="dot")
    fig.update_layout(xaxis_title=L(lg, "Jahre", "Years"), yaxis_title="kEUR")
    return _base(fig, 340, L(lg, "Kumulierter diskontierter Cashflow", "Cumulative discounted cash flow"))


def npv_sensitivity(fo_or_pt: dict, params, lg: str) -> go.Figure:
    """NPV against electricity price and break-even price for one technology (linear in the price)."""
    econ = fo_or_pt["econ"]
    n = int(params.get("lifetime_years"))
    r = float(params.get("wacc"))
    ge = (1 + float(params.get("inflation"))) * (1 + float(params.get("price_escalation_electricity"))) - 1
    elec_kwh = fo_or_pt["elec_kwh"]
    p_now = fo_or_pt["price"]
    pmax = max(0.35, p_now * 1.4)
    xs = np.linspace(0, pmax, 60)
    slope = elec_kwh * pv_factor(ge, r, n)
    ys = (econ.npv_eur + slope * (p_now - xs)) / 1000
    fig = go.Figure()
    fig.add_scatter(x=xs, y=ys, mode="lines", line=dict(color=TECH_COLOR[fo_or_pt["tech"]], width=3), name="NPV")
    fig.add_hline(y=0, line_color=SLATE, line_dash="dot")
    fig.add_scatter(x=[p_now], y=[econ.npv_eur / 1000], mode="markers", marker=dict(size=12, color=NAVY),
                    name=L(lg, "angesetzt", "assumed"))
    be = econ.break_even_price
    if be is not None and 0 < be < pmax:
        fig.add_scatter(x=[be], y=[0], mode="markers+text", marker=dict(size=12, color=GREEN), text=[f"{be:.3f}"],
                        textposition="top center", name="Break-even")
    fig.update_layout(xaxis_title="EUR/kWh", yaxis_title="kEUR")
    return _base(fig, 320, L(lg, "Kapitalwert je Strompreis", "NPV by electricity price") + f" · {fo_or_pt['name']}")
