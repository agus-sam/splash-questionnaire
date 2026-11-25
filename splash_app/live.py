"""Live feedback while the questionnaire is filled in (no simulation run, instant)."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from splash_calc.baseline import PRICE_NAME, carrier_efficiency, vat_factor
from splash_calc.inputs import from_answers
from splash_calc.params import Params
from splash_calc.provenance import BADGE

from .charts import _base
from .state import answers, lang, visible_answers
from .theme import CORAL, SLATE, TEAL, fmt_eur, fmt_kwh, fmt_num, kpi_row, note, stretch
from .viz import WATER_KWH_PER_M3K, L

CARRIER_NAME = {
    "gas": {"de": "Erdgas", "en": "Natural gas"}, "oil": {"de": "Heizöl", "en": "Heating oil"},
    "district_heat": {"de": "Fernwärme", "en": "District heat"}, "other_heat": {"de": "Sonstige Wärme", "en": "Other heat"},
}


def _parsed():
    ans = visible_answers(answers())
    return ans, from_answers(ans, Params.load())


def pool_feedback(lg: str | None = None) -> None:
    """After step 1: area, volume and the storage capability of the water."""
    lg = lg or lang()
    ans, p = _parsed()
    inp = p.inputs
    area = inp.water_surface_m2()
    if area <= 0:
        return
    vol = sum(b.volume_m3()[0] for b in inp.basins)
    est = any(b.volume_m3()[1] for b in inp.basins)
    per_k = vol * WATER_KWH_PER_M3K
    tol = inp.allowed_change_k
    items = [
        {"label": L(lg, "Wasserfläche", "Water surface"), "value": f"{fmt_num(area, 0, lg)} m²",
         "range": BADGE["entered"][lg]},
        {"label": L(lg, "Wasservolumen", "Water volume"), "value": f"{fmt_num(vol, 0, lg)} m³",
         "range": BADGE["calculated" if est else "entered"][lg]},
        {"label": L(lg, "Speicherfähigkeit", "Storage capability"), "value": f"{fmt_num(per_k, 0, lg)} kWh/K",
         "range": L(lg, "Wasser, 1,163 kWh je m³ und K", "water, 1.163 kWh per m³ and K")},
    ]
    if tol:
        items.append({"label": L(lg, f"Bei {fmt_num(tol, 1, lg)} K Spielraum", f"At {fmt_num(tol, 1, lg)} K allowance"),
                      "value": fmt_kwh(per_k * tol, lg), "range": L(lg, "theoretisch", "theoretical")})
    kpi_row(items)


def energy_feedback(lg: str | None = None) -> None:
    """After step 2: energy flow of the existing system and an immediate energy and cost summary."""
    lg = lg or lang()
    ans, p = _parsed()
    inp = p.inputs
    params = Params.load()
    cons = {c: v for c, v in inp.consumption_kwh.items() if v > 0}
    if not cons:
        note("info", L(lg, "Sobald Sie Verbräuche eintragen, sehen wir hier sofort Energiefluss und Kosten.",
                       "As soon as you enter consumption, energy flow and cost appear here."))
        return
    total = sum(cons.values())
    area = inp.water_surface_m2()
    useful = {c: v * carrier_efficiency(c, inp, params) for c, v in cons.items()}
    eta_mix = sum(useful.values()) / total
    if inp.heat_cost_eur:
        cost, cost_note = inp.heat_cost_eur, BADGE["entered"][lg]
    else:
        vf = vat_factor(inp, params)
        cost = sum(v * float(params.get(PRICE_NAME[c])) * vf for c, v in cons.items())
        cost_note = BADGE["default"][lg]
    bench = params.central("bench_heat_kwh_per_m2")
    rows = [
        {"label": L(lg, "Endenergie Wärme", "Final energy (heat)"), "value": fmt_kwh(total, lg),
         "range": (f"{fmt_num(total / area, 0, lg)} kWh/m²" if area > 0 else "")},
        {"label": L(lg, "Wärmekosten", "Heat cost"), "value": fmt_eur(cost, lg), "range": cost_note},
        {"label": L(lg, "Mittlerer Nutzungsgrad", "Mean efficiency"), "value": f"{fmt_num(eta_mix * 100, 0, lg)} %",
         "range": L(lg, "Wärmeerzeugung", "heat generation")},
    ]
    kpi_row(rows)
    if area > 0 and inp.pool_type != "open_air":
        med = float(bench["median"])
        note("info", L(lg, f"Zum Vergleich: Median kommunaler Bäder (UBA) {fmt_num(med, 0, lg)} kWh/m². Ihr Wert: {fmt_num(total / area, 0, lg)} kWh/m².",
                       f"For comparison: UBA median of municipal pools {fmt_num(med, 0, lg)} kWh/m². Yours: {fmt_num(total / area, 0, lg)} kWh/m²."))
    labels = [CARRIER_NAME.get(c, {"de": c, "en": c})[lg] for c in cons] + [L(lg, "Nutzwärme", "Useful heat"), L(lg, "Verluste", "Losses")]
    n = len(cons)
    src = list(range(n)) * 2
    dst = [n] * n + [n + 1] * n
    val = [useful[c] / 1000 for c in cons] + [(cons[c] - useful[c]) / 1000 for c in cons]
    fig = go.Figure(go.Sankey(
        arrangement="snap",
        node=dict(label=labels, pad=22, thickness=18, color=[SLATE] * n + [TEAL, CORAL]),
        link=dict(source=src, target=dst, value=val,
                  color=["rgba(91,112,131,.4)"] * n + ["rgba(209,73,91,.3)"] * n,
                  hovertemplate="%{value:,.0f} MWh/a<extra></extra>"),
    ))
    fig = _base(fig, 260, L(lg, "Energiefluss Ihres bestehenden Systems (MWh/a)", "Energy flow of your existing system (MWh/a)"))
    st.plotly_chart(fig, key="live_flow", **stretch())


def flex_feedback(lg: str | None = None) -> None:
    """After step 3: storage in the allowed range and grid connection against the heater."""
    lg = lg or lang()
    ans, p = _parsed()
    inp = p.inputs
    area = inp.water_surface_m2()
    if area <= 0:
        return
    vol = sum(b.volume_m3()[0] for b in inp.basins)
    per_k = vol * WATER_KWH_PER_M3K
    if inp.allowed_change_k:
        note("info", L(lg, f"Bei {fmt_num(inp.allowed_change_k, 1, lg)} K zulässiger Erhöhung kann das Wasser theoretisch {fmt_kwh(per_k * inp.allowed_change_k, lg)} "
                           f"Wärme speichern ({fmt_num(per_k, 0, lg)} kWh/K).",
                       f"With {fmt_num(inp.allowed_change_k, 1, lg)} K allowed rise the water can theoretically store {fmt_kwh(per_k * inp.allowed_change_k, lg)} "
                       f"of heat ({fmt_num(per_k, 0, lg)} kWh/K)."))
    ref = inp.main_capacity_kw
    if ref:
        note("info", L(lg, f"Zur Einordnung: Ihre Hauptwärmequelle hat {fmt_num(ref, 0, lg)} kW. Ein Heizstab dieser Größenordnung braucht entsprechend "
                           "freie elektrische Anschlussleistung. Die genaue Heizstabgröße zeigt Ihnen das Ergebnis.",
                       f"For orientation: your main heat source is {fmt_num(ref, 0, lg)} kW. A heater of that order needs matching spare electrical "
                       "connection capacity. The results show the exact heater size."))
    note("info", L(lg, "Hinweis zum Netzanschluss: Reicht er nicht, kommen ein kleinerer Heizstab, Lastmanagement oder eine Anschlussverstärkung in Frage. "
                       "Die Anschlussleistung können Sie unter 'Genauer rechnen' angeben.",
                   "Grid connection hint: if it is too small, options are a smaller heater, load management or a connection upgrade. "
                   "You can enter the connection capacity under 'Refine'."))
