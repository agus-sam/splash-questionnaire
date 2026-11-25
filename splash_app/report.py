"""PDF summary of the results (fpdf2, core fonts, no external assets)."""
from __future__ import annotations

from datetime import date

from fpdf import FPDF

from splash_calc.scenarios import Result

from .theme import fmt_eur, fmt_kwh, fmt_num

_REPL = {"₂": "2", "–": "-", "—": "-", "…": "...", "€": "EUR", "≈": "~", "→": "->", "“": '"', "”": '"',
         "‘": "'", "’": "'", "≥": ">=", "≤": "<=", "·": "-", "±": "+/-", "°": " deg", "³": "3", "²": "2"}


def _s(text: object) -> str:
    s = str(text)
    for a, b in _REPL.items():
        s = s.replace(a, b)
    return s.encode("latin-1", "replace").decode("latin-1")


T = {
    "title": {"de": "SPLASH Fragebogen und Simulation: Ergebnis", "en": "SPLASH Questionnaire and Simulation: results"},
    "draft": {
        "de": "VORLÄUFIG: Preise, Kosten und Technikwerte sind Platzhalter und noch nicht freigegeben.",
        "en": "DRAFT: prices, costs and technology values are placeholders not yet signed off.",
    },
    "tmy": {
        "de": "Wetter: typisches Jahr (TMY), nicht das Wetter von 2025/2026. Abregelung: Betreiberdaten, Zone T5/T6, stündlich.",
        "en": "Weather: typical year (TMY), not the weather of 2025/2026. Curtailment: operator data, zone T5/T6, hourly.",
    },
    "partial": {
        "de": "2026 liegt nur bis 22.11. vor und ist nicht hochgerechnet.",
        "en": "2026 is available up to 22 November and is not scaled to a full year.",
    },
    "model": {
        "de": "Berechnung mit dem SPLASH-Modell {v} (Zone {z}): stündliche Becken- und Hallenbilanz und Warmwasser für Duschen aus der Besucherzahl, Heizstab nur bei Abregelung, Beladung bis zur oberen Temperaturgrenze.",
        "en": "Calculated with the SPLASH model {v} (zone {z}): hourly basin and hall balance and hot water for showers from the visitor numbers, heater only during curtailment, charging up to the upper temperature limit.",
    },
    "demo": {
        "de": "Demo-Daten für Wetter und Abregelung. Das Flexibilitäts-Ergebnis ist ein Platzhalter.",
        "en": "Demo data for weather and curtailment. The flexibility result is a placeholder.",
    },
    "base": {"de": "Ausgangslage", "en": "Starting point"},
    "hp": {"de": "Szenario Wärmepumpe", "en": "Heat pump scenario"},
    "flex": {"de": "Szenario Flexibles Heizen (Elektro-Heizstab, SPLASH-Modell)", "en": "Flexible heating scenario (electric heater)"},
    "range": {"de": "Spanne (pessimistisch bis optimistisch)", "en": "Range (pessimistic to optimistic)"},
    "disc": {
        "de": "Die Ergebnisse sind eine erste Orientierung auf Basis Ihrer Angaben und vereinfachter Annahmen. Sie ersetzen keine Fachplanung und keine Förderberatung. Förderung: Antrag vor Beginn der Arbeiten, kein Rechtsanspruch.",
        "en": "The results are a first orientation based on your inputs and simplified assumptions. They do not replace professional planning or grant advice. Grants: apply before work starts, no legal entitlement.",
    },
    "contact": {
        "de": "SPLASH, Europa-Universität Flensburg (SEDEV). Rückfragen: Agus Samsudin, agus.samsudin@uni-flensburg.de",
        "en": "SPLASH, Europa-Universität Flensburg (SEDEV). Questions: gus Samsudin, agus.samsudin@uni-flensburg.de",
    },
}


class _Pdf(FPDF):
    def footer(self) -> None:  # pragma: no cover - layout only
        self.set_y(-14)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(110, 120, 130)
        self.cell(0, 8, _s(f"SPLASH Questionnaire and Simulation - page {self.page_no()}"), align="C")


def _row(pdf: FPDF, cells: list[str], widths: list[float], bold: bool = False, fill: bool = False) -> None:
    pdf.set_font("Helvetica", "B" if bold else "", 9.5)
    if fill:
        pdf.set_fill_color(232, 247, 248)
    for txt, w in zip(cells, widths, strict=False):
        pdf.cell(w, 7, _s(txt), border="B", fill=fill)
    pdf.ln(7)


def _h(pdf: FPDF, text: str) -> None:
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(11, 42, 60)
    pdf.cell(0, 8, _s(text), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(30, 40, 50)


def _para(pdf: FPDF, text: str, size: float = 9.5) -> None:
    pdf.set_font("Helvetica", "", size)
    pdf.multi_cell(0, 5, _s(text), new_x="LMARGIN", new_y="NEXT")


def build_pdf(res: Result, params, answers: dict, lg: str, key: str | None = None) -> bytes:
    from splash_calc.flexsplash import flex_key, parse_key
    from splash_calc.splash_engine import DEFAULT_SIZE, DEFAULT_YEAR, SIZES

    key = key or flex_key(DEFAULT_YEAR, DEFAULT_SIZE)
    year, _size = parse_key(key)
    pdf = _Pdf(format="A4")
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_page()
    pdf.set_fill_color(11, 42, 60)
    pdf.rect(0, 0, 210, 28, "F")
    pdf.set_xy(12, 8)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 17)
    pdf.cell(0, 8, _s(T["title"][lg]), new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(12)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _s(f"{answers.get('q1_name', '')}, {answers.get('q1_city', '')}  |  {date.today().isoformat()}"))
    pdf.set_text_color(30, 40, 50)
    pdf.set_xy(12, 34)
    pdf.set_left_margin(12)
    pdf.set_right_margin(12)

    if res.params_draft:
        pdf.set_text_color(160, 90, 0)
        _para(pdf, T["draft"][lg], 9)
        pdf.set_text_color(30, 40, 50)
    ctx = res.context
    if ctx is not None and ctx.splash is not None:
        pdf.set_text_color(160, 90, 0)
        _para(pdf, T["tmy"][lg], 9)
        if not res.central.flex[key].res.full_year:
            _para(pdf, T["partial"][lg], 9)
        pdf.set_text_color(30, 40, 50)

    if res.status not in ("ok", "open_air"):
        _para(pdf, "-", 10)
        return bytes(pdf.output())

    c = res.central
    b = c.baseline
    w = [62, 40, 78]
    _h(pdf, T["base"][lg])
    _row(pdf, ["", "", ""], w, fill=True)
    _row(pdf, ["Heat (final energy)" if lg == "en" else "Wärme (Endenergie)", fmt_kwh(b.e_fuel_total, lg),
               f"{fmt_num(b.kwh_per_m2, 0, lg)} kWh/m2" if b.kwh_per_m2 else ""], w)
    _row(pdf, ["Heat cost" if lg == "en" else "Wärmekosten", fmt_eur(c.base_cost_eur, lg), "/ a"], w)
    _row(pdf, ["CO2", f"{fmt_num(c.base_co2_t, 0, lg)} t", "/ a"], w)

    def rng(f) -> str:
        v = [f(res.cases[k]) for k in ("pessimistic", "central", "optimistic")]
        return f"{fmt_num(min(v), 0, lg)} ... {fmt_num(max(v), 0, lg)}"

    if c.hp is not None:
        _h(pdf, T["hp"][lg])
        _row(pdf, ["KPI", "Central" if lg == "en" else "Zentral", T["range"][lg]], w, bold=True, fill=True)
        h = c.hp
        _row(pdf, ["Fuel saved" if lg == "en" else "Brennstoff gespart", fmt_kwh(sum(h.res.fuel_saved_kwh.values()), lg),
                   f"{fmt_num(h.res.coverage * 100, 0, lg)} %"], w)
        _row(pdf, ["Net saving / year" if lg == "en" else "Netto-Ersparnis / Jahr", fmt_eur(h.econ.net_saving_eur_y1, lg),
                   rng(lambda x: x.hp.econ.net_saving_eur_y1)], w)
        _row(pdf, ["NPV" if lg == "en" else "Kapitalwert", fmt_eur(h.econ.npv_eur, lg), rng(lambda x: x.hp.econ.npv_eur)], w)
        _row(pdf, ["CO2 / year" if lg == "en" else "CO2 / Jahr", f"{fmt_num(h.co2.net_t_y1, 0, lg)} t",
                   rng(lambda x: x.hp.co2.net_t_y1)], w)
        _row(pdf, ["Investment / grant" if lg == "en" else "Investition / Förderung", fmt_eur(h.investment, lg),
                   fmt_eur(h.subsidy["grant_eur"], lg)], w)
        _row(pdf, ["Capacity / SCOP" if lg == "en" else "Leistung / JAZ", f"{fmt_num(h.res.capacity_kw_th, 0, lg)} kW",
                   fmt_num(h.res.scop, 1, lg)], w)

    _h(pdf, T["flex"][lg])
    f = c.flex[key]
    w4 = [30, 34, 34, 34, 40]
    _row(pdf, ["Heater size" if lg == "en" else "Heizstab", "kW el", "Absorbed MWh" if lg == "en" else "Aufgen. MWh",
               "Displaced MWh" if lg == "en" else "Verdr. MWh", "NPV EUR" if lg == "en" else "Kapitalwert EUR"], w4, bold=True, fill=True)
    for x in SIZES:
        fx = c.flex[flex_key(year, x)]
        _row(pdf, [f"{int(round(x * 100))} % ({year})", fmt_num(fx.res.capacity_kw_el, 0, lg), fmt_num(fx.res.absorbed_kwh_el / 1000, 0, lg),
                   fmt_num(fx.res.displaced_kwh_th / 1000, 0, lg), fmt_num(fx.econ.npv_eur, 0, lg)], w4)
    pdf.ln(2)
    _row(pdf, ["KPI", "Central" if lg == "en" else "Zentral", T["range"][lg]], w, bold=True, fill=True)
    sz = f"{int(round(_size * 100))} %"
    _row(pdf, [f"{'Selected' if lg == 'en' else 'Gewählt'}: {year}, {sz}", fmt_kwh(f.res.absorbed_kwh_el, lg),
               f"{'Heat displaced' if lg == 'en' else 'Verdrängte Wärme'}: {fmt_kwh(f.res.displaced_kwh_th, lg)}"], w)
    _row(pdf, ["Net saving / year" if lg == "en" else "Netto-Ersparnis / Jahr", fmt_eur(f.econ.net_saving_eur_y1, lg),
               rng(lambda x: x.flex[key].econ.net_saving_eur_y1)], w)
    _row(pdf, ["NPV" if lg == "en" else "Kapitalwert", fmt_eur(f.econ.npv_eur, lg), rng(lambda x: x.flex[key].econ.npv_eur)], w)
    be = f.econ.break_even_price
    be_txt = ("not reachable" if lg == "en" else "nicht erreichbar") if (be is None or be <= 0) else f"{fmt_num(be, 3, lg)} EUR/kWh"
    _row(pdf, ["Break-even electricity price" if lg == "en" else "Break-even-Strompreis", be_txt,
               f"{'Price used' if lg == 'en' else 'Angesetzter Preis'}: {fmt_num(f.price_eff, 3, lg)} EUR/kWh"], w)
    _row(pdf, ["Investment" if lg == "en" else "Investition", fmt_eur(f.investment, lg),
               f"{fmt_num(f.res.capacity_kw_el, 0, lg)} kW el"], w)
    _row(pdf, ["CO2 / year (curtailed = 0)" if lg == "en" else "CO2 / Jahr (Überschussstrom = 0)",
               f"{fmt_num(f.co2.net_curtailed_zero_t_y1, 0, lg)} t",
               f"{'grid mix' if lg == 'en' else 'Netzmix'}: {fmt_num(f.co2.net_t_y1, 0, lg)} t"], w)
    _para(pdf, T["model"][lg].format(v=ctx.splash.version, z=ctx.zone), 8.5)

    from splash_calc import provenance as prov

    items = prov.resolve(res.parsed, answers)
    _h(pdf, "Datengrundlage und Herkunft" if lg == "de" else "Data basis and provenance")
    groups = (
        ("operator", "Vom Betreiber (eingegeben oder geschätzt)" if lg == "de" else "Operator-provided (entered or estimated)"),
        ("derived", "Aus Betreiberangaben berechnet / Modell" if lg == "de" else "Derived from operator inputs / model"),
        ("benchmark", "Benchmark-basiert (UBA)" if lg == "de" else "Benchmark-based (UBA)"),
        ("splash", "SPLASH-Annahmen (Standardwerte)" if lg == "de" else "SPLASH assumptions (defaults)"),
    )
    for gid, title in groups:
        rows = [it for it in items.values() if prov.PDF_GROUP[it.cls] == gid]
        if not rows:
            continue
        _row(pdf, [title, "", ""], w, bold=True, fill=True)
        for it in rows:
            val = "" if it.value is None else (fmt_num(it.value, 1, lg) if isinstance(it.value, float) else str(it.value))
            _row(pdf, [it.label(lg), f"{val} {it.unit}".strip(), prov.CLASS_NAME[it.cls][lg]], w)
    _para(pdf, ("Die Wärmepumpe folgt derselben Regel wie der Heizstab: Netzstrom hält das Becken bei T_min, Überschussstrom lädt bis "
                "T_max (Referenzjahr 2025). Modellierte Nutzwärme und gemeldete Endenergie sind getrennte Größen. Ergebnisse sind "
                "Szenarien eines typischen Jahres, keine Rekonstruktion."
                if lg == "de" else
                "The heat pump follows the same rule as the heater: grid electricity holds the pool at T_min, curtailed power charges up to "
                "T_max (reference year 2025). Modelled useful heat and reported final energy are separate quantities. Results are "
                "typical-year scenarios, not a reconstruction."), 8.5)
    _h(pdf, "Hinweise" if lg == "de" else "Notes")
    _para(pdf, T["disc"][lg])
    pdf.ln(2)
    _para(pdf, f"Parameter set {res.params_version}.", 8.5)
    pdf.ln(1)
    _para(pdf, T["contact"][lg], 8.5)
    return bytes(pdf.output())
