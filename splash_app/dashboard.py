"""v1.4 results dashboard: five sections, technology selector, provenance, readiness.

Presentation only. All numbers come from splash_calc; the financial exploration re-evaluates
the (linear, cheap) economics function and does not touch the hourly simulation.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from splash_calc import provenance as prov
from splash_calc.economics import economics
from splash_calc.flexsplash import parse_key
from splash_calc.params import Params
from splash_calc.scenarios import Result

from . import viz
from .theme import e, fmt_eur, fmt_kwh, fmt_num, kpi_row, note, stretch
from .viz import L

TECHS = ("flex", "hp", "both")


# ----------------------------------------------------------------- selectors
def tech_selector(lg: str) -> str:
    labels = {
        "flex": L(lg, "Elektro-Heizstab (Überschussstrom)", "Electric resistance heater (curtailed power)"),
        "hp": L(lg, "Wärmepumpe (Regelbetrieb)", "Heat pump (rule-based operation)"),
        "both": L(lg, "Beide vergleichen", "Compare both"),
    }
    st.session_state.setdefault("tech", "flex")
    tech = st.radio(L(lg, "Technologie", "Technology"), TECHS, format_func=labels.get, horizontal=True, key="tech")
    if tech in ("hp", "both"):
        note("info", L(lg, "Die Wärmepumpe folgt derselben Regel wie der Heizstab: Netzstrom hält das Becken bei T_min und deckt den Bedarf, "
                           "bei Überschussstrom lädt sie bis T_max. Bedarf, Basissystem und Wirtschaftlichkeitsannahmen sind für alle "
                           "Technologien gleich. Die Wärmepumpe wird für das Referenzjahr 2025 simuliert.",
                       "The heat pump follows the same rule as the heater: grid electricity holds the pool at T_min and covers the demand, "
                       "with curtailed power it charges up to T_max. Demand, baseline system and economic assumptions are identical for "
                       "all technologies. The heat pump is simulated for the reference year 2025."))
    return tech


def flex_selectors(res: Result, lg: str) -> None:
    from splash_calc.splash_engine import SIZES, YEARS

    ylab = {y: (str(y) if res.central.flex[f"{y}_100"].res.full_year else f"{y} ({L(lg, 'bis 22.11.', 'to 22 Nov')})") for y in YEARS}
    c1, c2 = st.columns(2)
    c1.radio(L(lg, "Überschussstrom-Jahr", "Curtailment year"), list(YEARS), format_func=ylab.get, horizontal=True, key="flex_year")
    c2.radio(L(lg, "Heizstab-Größe (Anteil der Auslegungslast)", "Heater size (share of design load)"), list(SIZES),
             index=list(SIZES).index(2.0), format_func=lambda x: f"{int(x * 100)} %", horizontal=True, key="flex_size")


def _key() -> str:
    from .results import _selected_key

    return _selected_key()


def _selected(res: Result, tech: str, key: str) -> list[dict]:
    year, _ = parse_key(key)
    pts = viz.tech_points(res, year)
    pick = {"flex": [key], "hp": ["hp"], "both": [key, "hp"]}[tech]
    return [p for p in pts if p["id"] in pick]


def badge(item: prov.Item, lg: str) -> str:
    colour = {"entered": "#2E9E6B", "estimated_op": "#5B9E2E", "calculated": "#0E7C86", "default": "#F2A541",
              "benchmark": "#D17A2B", "model": "#3B6FD1"}[item.cls]
    return (f'<span style="background:{colour}1f;color:{colour};border:1px solid {colour}66;border-radius:10px;'
            f'padding:1px 8px;font-size:.78rem;white-space:nowrap">{e(item.badge(lg))}</span>')


def _badges_line(items: dict, keys: list[str], lg: str) -> None:
    parts = [f"{e(items[k].label(lg))} {badge(items[k], lg)}" for k in keys if k in items]
    st.markdown('<div class="sp-small" style="line-height:2">' + " &nbsp;·&nbsp; ".join(parts) + "</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------- section 1
def section_today(res: Result, items: dict, lg: str) -> None:
    c = res.central
    b = c.baseline
    st.markdown(f"### {L(lg, '1 · Ihr Bad heute', '1 · Your pool today')}")
    rep = sum(res.context.inp.consumption_kwh.values()) or None
    kpi_row([
        {"label": L(lg, "Modellierte Nutzwärme", "Modelled useful heat"), "value": fmt_kwh(b.q_use_kwh, lg),
         "range": L(lg, "SPLASH, typisches Jahr (TMY)", "SPLASH, typical year (TMY)")},
        {"label": L(lg, "Gemeldete Endenergie Wärme", "Reported final energy (heat)"),
         "value": fmt_kwh(rep, lg) if rep else "–", "range": (L(lg, "Ihre Angabe", "your input") if rep else L(lg, "nicht angegeben", "not entered"))},
        {"label": L(lg, "Modellierte Endenergie (Basis)", "Modelled final energy (baseline)"), "value": fmt_kwh(b.e_fuel_total, lg),
         "range": (f"{fmt_num(b.kwh_per_m2, 0, lg)} kWh/m²" if b.kwh_per_m2 else "")},
    ])
    kpi_row([
        {"label": L(lg, "Ausgaben Wärme", "Heat expenditure"), "value": fmt_eur(c.base_cost_eur, lg), "range": L(lg, "pro Jahr", "per year")},
        {"label": "CO₂", "value": f"{fmt_num(c.base_co2_t, 0, lg)} t", "range": L(lg, "pro Jahr", "per year")},
        {"label": L(lg, "Spezifischer Bedarf", "Specific demand"),
         "value": f"{fmt_num(b.q_use_kwh / max(res.context.inp.water_surface_m2(), 1e-9), 0, lg)} kWh/m²",
         "range": L(lg, "Nutzwärme je m² Wasserfläche", "useful heat per m² water")},
    ])
    note("info", L(lg, "Die Modellgrenze (Becken und Hallenluft nach SPLASH) ist nicht gleich dem Gesamtverbrauch Ihres Bades. "
                       "Modellierte Nutzwärme und gemeldete Endenergie sind getrennte Größen und werden nicht gleichgesetzt.",
                   "The model boundary (basins and hall air per SPLASH) is not your pool's total consumption. Modelled useful heat "
                   "and reported final energy are separate quantities and are not treated as equivalent."))
    if b.reported_q_use_kwh:
        ratio = b.q_use_kwh / b.reported_q_use_kwh
        if ratio > 1.5 or ratio < 0.67:
            note("warn", L(lg, f"Modell und Meldung weichen um den Faktor {fmt_num(ratio, 1, lg)} ab. Ergebnisse sind Szenarien, "
                               "keine Rekonstruktion Ihres Verbrauchs. Eine Kalibrierung ist unter 'Spielraum' optional.",
                           f"Model and reported figures differ by a factor of {fmt_num(ratio, 1, lg)}. Results are scenarios, not a "
                           "reconstruction of your consumption. Calibration is optional under 'What if'."))
    ent, tot = prov.completeness(items)
    st.progress(ent / tot, text=L(lg, f"Datenvollständigkeit: {ent} von {tot} Eingaben stützen sich auf Ihre Angaben",
                                  f"Data completeness: {ent} of {tot} inputs rest on your information"))
    _badges_line(items, list(prov.TRACKED_FIELDS), lg)
    st.plotly_chart(viz.sankey(c, _key(), "existing", lg, fmt_eur(c.base_cost_eur, lg) + L(lg, " / Jahr", " / year")),
                    key="sk_existing", **stretch())


# ---------------------------------------------------------------- section 2
def section_battery(res: Result, items: dict, lg: str) -> None:
    key = _key()
    fo = res.central.flex[key]
    st.markdown(f"### {L(lg, '2 · Das Becken als thermische Batterie', '2 · The pool as a thermal battery')}")
    buf_default = float(res.context.inp.buffer_m3 or 0.0)
    c1, c2, c3 = st.columns(3)
    allow = c1.slider(L(lg, "Temperaturspielraum (K), nur Erkundung", "Temperature allowance (K), exploration only"), 0.5, 4.0,
                      float(round(fo.res.band_k * 2) / 2 or 1.0) if 0.5 <= fo.res.band_k <= 4.0 else 1.0, 0.5, key="bat_allow")
    buf_m3 = c2.number_input(L(lg, "Optionaler Pufferspeicher (m³)", "Optional buffer tank (m³)"), 0.0, 500.0, buf_default, 1.0, key="bat_buf")
    buf_k = c3.slider(L(lg, "Puffer-Temperaturhub (K)", "Buffer temperature swing (K)"), 5, 60, 30, 5, key="bat_bufk")
    n = viz.battery_numbers(res, fo, buf_m3, buf_k)
    theo_explore = n["per_k"] * allow
    st.markdown(viz.battery_svg(n, lg), unsafe_allow_html=True)
    kpi_row([
        {"label": L(lg, "Speicherfähigkeit", "Storage capability"), "value": f"{fmt_num(n['per_k'], 0, lg)} kWh/K",
         "range": f"{fmt_num(n['volume_m3'], 0, lg)} m³ · {fmt_num(n['area_m2'], 0, lg)} m²"},
        {"label": L(lg, "Theoretisch im Band", "Theoretical in band"), "value": fmt_kwh(n["theoretical"], lg),
         "range": f"{L(lg, 'Band', 'band')} {fmt_num(n['band_k'], 1, lg)} K"},
        {"label": L(lg, "Modelliert nutzbar", "Modelled usable"), "value": fmt_kwh(n["usable_max"], lg),
         "range": L(lg, "Maximaler Speicherstand der Simulation", "peak state of charge in the simulation")},
        {"label": L(lg, "Frei im Überschussfenster", "Free during curtailment"), "value": fmt_kwh(n["free_in_window"], lg),
         "range": L(lg, "Mittel der freien Kapazität", "mean free capacity")},
    ])
    st.caption(L(lg, f"Erkundung: Bei {allow:.1f} K Spielraum wären theoretisch {fmt_kwh(theo_explore, lg)} speicherbar. Dieser Wert "
                     "ändert die Simulation nicht. Dafür Spielraum unter 'Was wäre wenn' anpassen und neu berechnen."
                     + (f" Pufferspeicher: {fmt_kwh(n['buffer'], lg)} zusätzlich (getrennt ausgewiesen)." if n["buffer"] > 0 else ""),
                 f"Exploration: with {allow:.1f} K allowance the theoretical storage would be {fmt_kwh(theo_explore, lg)}. This value does not "
                 "change the simulation. Adjust the allowance under 'What if' and recalculate for that."
                 + (f" Buffer tank: {fmt_kwh(n['buffer'], lg)} additional (shown separately)." if n["buffer"] > 0 else "")))
    _badges_line(items, ["water_surface", "water_volume", "setpoints", "tolerance", "buffer"], lg)


# ---------------------------------------------------------------- section 3
def _tech_table(res: Result, pts: list[dict], lg: str) -> pd.DataFrame:
    c = res.central
    fuel = c.baseline.e_fuel_total
    rows: dict[str, list[str]] = {}

    def add(label: str, vals: list[str]) -> None:
        rows[label] = vals

    cols = []
    cap, heat, el, rem, opex, diff, capex, grant, om, npv, dpb, irr, co2 = ([] for _ in range(13))
    for p in pts:
        ec = p["econ"]
        cols.append(viz.TECH_NAME[p["tech"]][lg] + (f" {int(round(parse_key(p['id'])[1] * 100))} %" if p["tech"] == "flex" else ""))
        if p["tech"] == "flex":
            r = p["fo"].res
            cap.append(f"{fmt_num(r.capacity_kw_el, 0, lg)} kW el / {fmt_num(r.capacity_kw_th, 0, lg)} kW th")
            heat.append(fmt_kwh(r.heat_kwh_th, lg))
            el.append(fmt_kwh(r.absorbed_kwh_el, lg))
            rem.append(fmt_kwh(fuel - sum(r.fuel_saved_kwh.values()), lg))
            co2.append(f"{fmt_num(p['fo'].co2.net_curtailed_zero_t_y1, 1, lg)} t ({L(lg, 'Netzmix', 'grid mix')} {fmt_num(p['fo'].co2.net_t_y1, 1, lg)} t)")
        else:
            h = c.hp
            cap.append(f"{fmt_num(h.res.capacity_kw_th, 0, lg)} kW th (SCOP {fmt_num(h.res.scop, 1, lg)})")
            heat.append(fmt_kwh(h.res.heat_hp_kwh, lg))
            el.append(fmt_kwh(h.res.elec_kwh, lg) + (
                f" ({L(lg, 'Netz', 'grid')} {fmt_kwh(h.res.elec_grid_kwh, lg)}, {L(lg, 'Überschuss', 'curtailed')} {fmt_kwh(h.res.elec_curtailed_kwh, lg)})"
                if h.res.dispatch == "rule" else ""))
            rem.append(fmt_kwh(fuel - sum(h.res.fuel_saved_kwh.values()), lg))
            co2.append(f"{fmt_num(h.co2.net_curtailed_zero_t_y1, 1, lg)} t ({L(lg, 'Netzmix', 'grid mix')} {fmt_num(h.co2.net_t_y1, 1, lg)} t)")
        opex.append(fmt_eur(ec.electricity_cost_eur_y1 + ec.om_eur_y, lg))
        diff.append(fmt_eur(ec.net_saving_eur_y1, lg))
        capex.append(fmt_eur(ec.investment_eur, lg))
        grant.append(fmt_eur(ec.subsidy_eur, lg))
        om.append(fmt_eur(ec.om_eur_y, lg))
        npv.append(fmt_eur(ec.npv_eur, lg))
        dpb.append("–" if ec.discounted_payback_years is None else f"{fmt_num(ec.discounted_payback_years, 1, lg)} {L(lg, 'Jahre', 'years')}")
        irr.append("–" if ec.irr is None else f"{fmt_num(ec.irr * 100, 1, lg)} %")
    add(L(lg, "Leistung", "Capacity"), cap)
    add(L(lg, "Gelieferte Wärme", "Heat delivered"), heat)
    add(L(lg, "Strombedarf", "Electricity use"), el)
    add(L(lg, "Verbleibender Brennstoff", "Remaining fuel"), rem)
    add(L(lg, "Betriebskosten (Strom + Wartung)", "Operating cost (electricity + maintenance)"), opex)
    add(L(lg, "Jährliche Kostendifferenz", "Annual cost difference"), diff)
    add(L(lg, "Investition (brutto)", "CAPEX (gross)"), capex)
    add(L(lg, "Förderung", "Grant"), grant)
    add(L(lg, "Wartung", "Maintenance"), om)
    add(L(lg, "Kapitalwert (NPV)", "NPV"), npv)
    add(L(lg, "Diskontierte Amortisation", "Discounted payback"), dpb)
    add("IRR", irr)
    add("CO₂ / " + L(lg, "Jahr", "year"), co2)
    df = pd.DataFrame(rows, index=cols).T
    df.index.name = ""
    return df


def section_tech(res: Result, tech: str, lg: str) -> list[dict]:
    key = _key()
    c = res.central
    st.markdown(f"### {L(lg, '3 · Technologien erkunden', '3 · Explore technologies')}")
    flex_selectors(res, lg)
    year, _ = parse_key(key)
    pts_all = viz.tech_points(res, year)
    sel = _selected(res, tech, key)
    if tech in ("hp", "both") and c.hp is None:
        note("warn", L(lg, "Für die Wärmepumpe liegen keine Ergebnisse vor.", "No heat pump results are available."))
    ev = st.plotly_chart(viz.tech_scatter(pts_all, lg), key="tech_scatter", on_select="rerun", selection_mode="points", **stretch())
    clicked = None
    try:
        pts = ev.selection.points if ev is not None else []
        if pts:
            clicked = pts[0].get("customdata")
            clicked = clicked[0] if isinstance(clicked, (list, tuple)) else clicked
    except Exception:  # noqa: BLE001
        clicked = None
    shown = [p for p in pts_all if p["id"] == clicked] if clicked else sel
    if not shown:
        shown = sel
    st.caption(L(lg, "Klicken Sie auf eine Blase, um ihre Kennzahlen zu sehen. Ohne Auswahl gilt Ihre Technologiewahl oben.",
                 "Click a bubble to see its KPIs. Without a selection your technology choice above applies."))
    st.dataframe(_tech_table(res, shown, lg), **stretch())
    cols = st.columns(len(shown) + 1)
    with cols[0]:
        st.plotly_chart(viz.sankey(c, key, "existing", lg), key="sk_base3", **stretch())
    for col, p in zip(cols[1:], shown, strict=False):
        with col:
            st.plotly_chart(viz.sankey(c, key, p["tech"], lg), key=f"sk_{p['id']}", **stretch())
    st.caption(L(lg, "Mengen in MWh pro Jahr. Verluste umfassen Kessel- und Umwandlungsverluste.",
                 "Quantities in MWh per year. Losses include boiler and conversion losses."))
    return shown


# ---------------------------------------------------------------- section 4
def _calendar_and_dispatch(fo, key: str, lg: str, eta: float | None = None) -> None:
    r = fo.res
    metric_lab = {"available": L(lg, "Verfügbare Überschussleistung", "Available curtailed power"),
                  "heater": L(lg, "Strom im Heizstab", "Heater electricity"),
                  "storage": L(lg, "Speicherauslastung", "Storage utilisation")}
    m = st.radio(L(lg, "Kalenderansicht", "Calendar view"), viz.METRICS, format_func=metric_lab.get, horizontal=True, key="cal_metric")
    st.plotly_chart(viz.calendar(fo, m, lg), key="cal_chart", **stretch())
    idx = viz._local(r)
    d0, d1 = idx[0].date(), idx[-1].date()
    best = viz.best_day(fo)
    if st.session_state.get("disp_key") != key:
        st.session_state["disp_key"] = key
        st.session_state["disp_day"] = best
    d_in = st.session_state.get("disp_day", best)
    st.session_state["disp_day"] = min(max(d_in, d0), d1)
    c1, c2 = st.columns([2, 1])
    day = c1.date_input(L(lg, "Tag wählen (Voreinstellung: Tag mit höchster Aufnahme)", "Select day (default: day with highest absorption)"),
                        min_value=d0, max_value=d1, key="disp_day")
    ndays = c2.slider(L(lg, "Tage", "Days"), 1, 7, 1, key="disp_days")
    from splash_calc.params import Params as _P

    if eta is None:
        eta = r.heat_kwh_th / r.absorbed_kwh_el if r.absorbed_kwh_el > 0 else float(_P.load().get("heater_efficiency"))
    fig = viz.dispatch_day(fo, eta, day, ndays, lg)
    if fig is not None:
        st.plotly_chart(fig, key="disp_chart", **stretch())
    st.caption(L(lg, "Die Temperatur über dem Sollwert ist aus dem Speicherstand abgeleitet (modelliert, Mittel über alle Becken).",
                 "Temperature above setpoint is derived from the state of charge (modelled, mean over all basins)."))



def section_curtailment(res: Result, tech: str, lg: str) -> None:
    key = _key()
    fo = res.central.flex[key]
    r = fo.res
    st.markdown(f"### {L(lg, '4 · Erneuerbarer Überschussstrom', '4 · Renewable electricity and curtailment')}")
    view = "flex"
    hpv = viz.hp_view(res)
    if tech == "hp" and hpv is not None:
        view = "hp"
    elif tech == "both" and hpv is not None:
        view = st.radio(L(lg, "Anzeige", "View"), ("flex", "hp"), horizontal=True, key="cur_view",
                        format_func=lambda v: viz.TECH_NAME[v][lg])
    if view == "hp":
        fo = hpv
        r = fo.res
        h = res.central.hp
        note("info", L(lg, "Anzeige der Wärmepumpe im Referenzjahr 2025 (Regelbetrieb).", "Heat pump view for the reference year 2025 (rule-based operation)."))
        kpi_row([
            {"label": L(lg, "Überschussstrom der Zone", "Zone curtailment"), "value": fmt_kwh(float(r.hourly_available_kw.sum()), lg),
             "range": f"{fmt_num(int((r.hourly_available_kw > 0).sum()), 0, lg)} h"},
            {"label": L(lg, "Aufnahme Wärmepumpe", "Heat pump absorption"), "value": fmt_kwh(h.res.elec_curtailed_kwh, lg),
             "range": f"{L(lg, 'Wärme', 'heat')}: {fmt_kwh(h.res.heat_curtailed_kwh, lg)}"},
            {"label": L(lg, "Netzstrom (Basisbedarf)", "Grid electricity (baseline demand)"), "value": fmt_kwh(h.res.elec_grid_kwh, lg),
             "range": f"SCOP {fmt_num(h.res.scop, 1, lg)}"},
            {"label": L(lg, "Nicht aufgenommenes Potenzial", "Unabsorbed potential"),
             "value": fmt_kwh(max(float(r.hourly_available_kw.sum()) - h.res.elec_curtailed_kwh, 0.0), lg), "range": L(lg, "auf Zonenebene", "zone level")},
        ])
        _calendar_and_dispatch(fo, key, lg, eta=1.0)
        return
    unabs = max(r.zone_available_kwh - r.absorbed_kwh_el, 0.0)
    kpi_row([
        {"label": L(lg, "Überschussstrom der Zone", "Zone curtailment"), "value": fmt_kwh(r.zone_available_kwh, lg),
         "range": f"{fmt_num(r.curtail_hours, 0, lg)} h"},
        {"label": L(lg, "Aufnahme Heizstab", "Heater absorption"), "value": fmt_kwh(r.absorbed_kwh_el, lg),
         "range": f"{fmt_num(r.absorption_hours, 0, lg)} h"},
        {"label": L(lg, "Nicht aufgenommenes Potenzial", "Unabsorbed potential"), "value": fmt_kwh(unabs, lg),
         "range": L(lg, "auf Zonenebene", "zone level")},
        {"label": L(lg, "Wärmebedarf / verdrängt", "Demand / displaced"), "value": fmt_kwh(r.demand_kwh_th, lg),
         "range": f"{L(lg, 'verdrängt', 'displaced')}: {fmt_kwh(r.displaced_kwh_th, lg)}"},
    ])
    _calendar_and_dispatch(fo, key, lg)


# ---------------------------------------------------------------- section 5
def section_finance(res: Result, params: Params, shown: list[dict], items: dict, lg: str) -> None:
    c = res.central
    st.markdown(f"### {L(lg, '5 · Finanzen erkunden', '5 · Financial exploration')}")
    pts = shown or []
    if not pts:
        return
    tariff_entered = items["electricity_price"].cls == prov.ENTERED
    note("info", L(lg, "Strompreis: " + ("Ihr Tarif aus Ihren Angaben." if tariff_entered else "illustrative Annahme (Parameterdatei), kein Tarif."),
                   "Electricity price: " + ("your tariff from your inputs." if tariff_entered else "illustrative assumption (parameter file), not a tariff.")))
    with st.expander(L(lg, "Regler (sofortige Neuberechnung der Wirtschaftlichkeit, Simulation bleibt unverändert)",
                       "Controls (instant re-evaluation of the economics, simulation unchanged)"), expanded=True):
        a1, a2, a3 = st.columns(3)
        fuel_f = a1.slider(L(lg, "Brennstoffpreis (% des angesetzten)", "Fuel price (% of assumed)"), 50, 200, 100, 5, key="fin_fuel")
        inv_f = a2.slider(L(lg, "Investition (% der angesetzten)", "Investment (% of assumed)"), 50, 200, 100, 5, key="fin_inv")
        wacc = a3.slider(L(lg, "Kalkulationszins WACC (%)", "Discount rate WACC (%)"), 0.0, 15.0,
                         float(params.central("wacc")) * 100, 0.25, key="fin_wacc")
        b1, b2, b3 = st.columns(3)
        life = b1.slider(L(lg, "Betrachtungszeitraum (Jahre)", "Evaluation period (years)"), 5, 40, int(params.get("lifetime_years")), 1, key="fin_life")
        grid_price_now = c.elec_price
        grid_p = b2.slider(L(lg, "Netzstrompreis (EUR/kWh), Wärmepumpe", "Grid electricity price (EUR/kWh), heat pump"), 0.05, 0.60,
                           float(round(grid_price_now, 3)), 0.005, key="fin_grid")
        flex_now = pts[0]["price"] if pts[0]["tech"] == "flex" else c.flex[_key()].price_eff
        curt_p = b3.slider(L(lg, "Preis Überschussstrom (EUR/MWh)", "Curtailed power price (EUR/MWh)"), 0.0, 300.0,
                           float(round(flex_now * 1000)), 5.0, key="fin_curt")
    p2 = params.apply_input({"wacc": wacc / 100.0, "lifetime_years": int(life)})
    new_pts = []
    for p in pts:
        if p["tech"] == "flex":
            price = curt_p / 1000.0
        else:
            hr = c.hp.res
            tot = hr.elec_kwh or 1.0
            price = (hr.elec_grid_kwh * grid_p + hr.elec_curtailed_kwh * curt_p / 1000.0) / tot if hr.dispatch == "rule" else grid_p
        if p["tech"] == "flex":
            fuel_saved = p["fo"].res.fuel_saved_kwh
        else:
            fuel_saved = c.hp.res.fuel_saved_kwh
        fp = {k: v * fuel_f / 100.0 for k, v in c.fuel_prices.items()}
        ec0 = p["econ"]
        ec = economics(ec0.investment_eur * inv_f / 100.0, ec0.subsidy_eur * (inv_f / 100.0 if p["tech"] == "flex" else 1.0),
                       fuel_saved, fp, p["elec_kwh"], price, ec0.om_eur_y, p2)
        q = dict(p)
        q["econ"], q["price"], q["invest"] = ec, price, ec.investment_eur
        new_pts.append(q)
    kpi_row([
        {"label": f"NPV · {q['name']}", "value": fmt_eur(q["econ"].npv_eur, lg),
         "range": L(lg, "Break-even Strompreis: ", "Break-even price: ") + ("–" if not q["econ"].break_even_price or q["econ"].break_even_price <= 0
                                                                           else f"{fmt_num(q['econ'].break_even_price, 3, lg)} EUR/kWh"),
         "tone": "good" if q["econ"].npv_eur > 0 else "bad"} for q in new_pts])
    g1, g2 = st.columns(2)
    g1.plotly_chart(viz.invest_compare(new_pts, lg), key="fin_inv_chart", **stretch())
    g2.plotly_chart(viz.discounted_cumulative(new_pts, wacc / 100.0, lg), key="fin_cum_chart", **stretch())
    h1, h2 = st.columns(2)
    h1.plotly_chart(viz.waterfall(new_pts[0]["econ"], lg, L(lg, "Jahr 1 · ", "Year 1 · ") + new_pts[0]["name"]), key="fin_wf", **stretch())
    h2.plotly_chart(viz.npv_sensitivity(new_pts[-1], p2, lg), key="fin_sens", **stretch())


# ------------------------------------------------------------- readiness
def readiness(res: Result, items: dict, ans: dict, lg: str) -> None:
    st.markdown(f"#### {L(lg, 'Betriebsbereitschaft', 'Operational readiness')}")
    fo = res.central.flex[_key()]
    inp = res.context.inp
    rows = []

    def row(area: str, status: str, text: str) -> None:
        rows.append({L(lg, "Bereich", "Area"): area, L(lg, "Stand", "Status"): {"ok": "✓", "check": "!", "open": "?"}[status],
                     L(lg, "Einschätzung", "Assessment"): text})

    if inp.grid_kw:
        ok = fo.res.capacity_kw_el <= inp.grid_kw
        row(L(lg, "Netzanschluss", "Grid connection"), "ok" if ok else "check",
            L(lg, f"Heizstab {fmt_num(fo.res.capacity_kw_el, 0, lg)} kW el, Anschluss {fmt_num(inp.grid_kw, 0, lg)} kW"
                  + ("" if ok else ". Anschlussverstärkung oder kleinerer Heizstab prüfen."),
              f"Heater {fmt_num(fo.res.capacity_kw_el, 0, lg)} kW el, connection {fmt_num(inp.grid_kw, 0, lg)} kW"
              + ("" if ok else ". Check a grid upgrade or a smaller heater.")))
    else:
        row(L(lg, "Netzanschluss", "Grid connection"), "open",
            L(lg, f"Anschlussleistung nicht angegeben. Der Heizstab bräuchte {fmt_num(fo.res.capacity_kw_el, 0, lg)} kW el.",
              f"Connection capacity not entered. The heater would need {fmt_num(fo.res.capacity_kw_el, 0, lg)} kW el."))
    row(L(lg, "Speicher", "Storage"), "ok" if fo.res.e_max_kwh > 0 else "open",
        L(lg, f"Becken speichern {fmt_kwh(fo.res.e_max_kwh, lg)} im Band", f"Basins store {fmt_kwh(fo.res.e_max_kwh, lg)} within the band"))
    tol = inp.allowed_change_k
    row(L(lg, "Temperaturflexibilität", "Temperature flexibility"), "open" if tol is None else ("check" if tol == 0 else "ok"),
        L(lg, "Zulässiger Spielraum nicht angegeben (Klassenstandard)" if tol is None else f"{fmt_num(tol, 1, lg)} K zulässig",
          "Allowed range not entered (class default)" if tol is None else f"{fmt_num(tol, 1, lg)} K allowed"))
    auto = ans.get("q3_auto_temp")
    row(L(lg, "Regelungsfähigkeit", "Control capability"), {"yes": "ok", "partly": "check"}.get(auto, "open"),
        {"yes": L(lg, "Temperatur wird automatisch geregelt", "Temperature is controlled automatically"),
         "partly": L(lg, "Teilweise automatisch geregelt", "Partly automatic control")}.get(
            auto, L(lg, "Regelung nicht angegeben", "Control not stated")))
    open_items = [items[k].label(lg) for k in prov.LABEL if k in items and items[k].cls in (prov.DEFAULT, prov.BENCHMARK)]
    row(L(lg, "Offene Angaben", "Outstanding information"), "open" if open_items else "ok",
        ", ".join(open_items) if open_items else L(lg, "Keine", "None"))
    st.dataframe(pd.DataFrame(rows), hide_index=True, **stretch())
    st.caption(L(lg, "Keine Gesamtbewertung: Jede Zeile beschreibt eine Bedingung.", "No overall score: each row describes one condition."))


# ---------------------------------------------------------- provenance table
def provenance_table(items: dict, lg: str) -> None:
    counts = prov.counts(items)
    st.caption(" · ".join(f"{prov.CLASS_NAME[k][lg]}: {v}" for k, v in counts.items() if v))
    rows = []
    for it in items.values():
        v = it.value
        rows.append({L(lg, "Eingabe", "Input"): it.label(lg), L(lg, "Wert", "Value"): "" if v is None else (fmt_num(v, 1, lg) if isinstance(v, float) else str(v)),
                     L(lg, "Einheit", "Unit"): it.unit, L(lg, "Herkunft", "Source"): prov.CLASS_NAME[it.cls][lg]})
    st.dataframe(pd.DataFrame(rows), hide_index=True, **stretch())
