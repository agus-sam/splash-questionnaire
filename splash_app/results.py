"""Results dashboard (step 4)."""
from __future__ import annotations

import copy
import json

import pandas as pd
import streamlit as st

from splash_calc import Options, Params, run
from splash_calc import provenance as prov
from splash_calc.scenarios import Result

from . import charts, dashboard, exports, flexcharts
from .form import render_step
from .i18n import t
from .report import build_pdf
from .state import answers, lang, visible_answers
from .theme import fmt_eur, fmt_kwh, fmt_num, fmt_range, kpi_row, mini_hero, note, stretch
from .viz import L

ECON_FIELDS = [
    # (parameter, label_de, label_en, min, max, step, format, factor shown to the user)
    ("wacc", "Nominaler Kalkulationszins (WACC)", "Nominal discount rate (WACC)", 0.0, 0.20, 0.0025, "%.4f", 1.0),
    ("inflation", "Allgemeine Inflation p. a.", "General inflation p.a.", 0.0, 0.10, 0.0025, "%.4f", 1.0),
    ("price_escalation_fuel", "Reale Preissteigerung Wärme p. a. (über Inflation)", "Real heat price change p.a. (above inflation)", -0.05, 0.10, 0.005, "%.3f", 1.0),
    ("price_escalation_electricity", "Reale Preissteigerung Strom p. a. (über Inflation)", "Real electricity price change p.a. (above inflation)", -0.05, 0.10, 0.005, "%.3f", 1.0),
    ("lifetime_years", "Betrachtungszeitraum (Jahre)", "Evaluation period (years)", 5, 40, 1, "%d", 1.0),
    ("price_gas", "Gaspreis netto (EUR/kWh)", "Gas price net (EUR/kWh)", 0.02, 0.30, 0.005, "%.3f", 1.0),
    ("price_electricity", "Strompreis netto (EUR/kWh)", "Electricity price net (EUR/kWh)", 0.05, 0.60, 0.005, "%.3f", 1.0),
    ("hp_capex_per_kw_th", "Wärmepumpe, Investition (EUR/kW thermisch)", "Heat pump capex (EUR/kW thermal)", 200.0, 3000.0, 50.0, "%.0f", 1.0),
    ("heater_capex_per_kw_el", "Elektro-Heizeinsatz, Investition (EUR/kW elektrisch)", "Electric heater capex (EUR/kW electric)", 20.0, 600.0, 10.0, "%.0f", 1.0),
]
ECON_KEYS = [f[0] for f in ECON_FIELDS]


@st.cache_data(show_spinner=False, max_entries=20, ttl=7200)
def compute(answers_json: str, overrides_json: str, opts_json: str, lg: str) -> tuple[Result, Params]:
    params = Params.load()
    ov = json.loads(overrides_json)
    if ov:
        params = params.apply_input(ov)
    o = json.loads(opts_json)
    price = o.get("curt_mwh")
    options = Options(hp_capacity_kw=o.get("hp_kw") or None, zone=o.get("zone") or None,
                      band_k=o.get("band_k") or None, calibrate=bool(o.get("calibrate")),
                      curtailed_price_net=None if price is None else float(price) / 1000.0)
    return run(json.loads(answers_json), params, options, True, lg), params


def overrides_from(opts: dict) -> dict:
    """Operator input as parameter values. Uncertain parameters keep their range (see Params.apply_input)."""
    base = Params.load()
    ov: dict = {}
    f = float(opts.get("fuel_factor") or 1.0)
    if abs(f - 1.0) > 1e-9:
        for n in ("price_gas", "price_oil", "price_district_heat", "price_other_heat"):
            ov[n] = float(base.central(n)) * f
    g = float(opts.get("el_factor") or 1.0)
    if abs(g - 1.0) > 1e-9:
        ov["price_electricity"] = float(base.central("price_electricity")) * g
    for k, v in (opts.get("econ") or {}).items():
        if k in ECON_KEYS and v is not None:
            ov[k] = int(v) if k == "lifetime_years" else float(v)
    return ov


def _tone(lo: float, hi: float) -> str:
    if min(lo, hi) >= 0:
        return "good"
    if max(lo, hi) <= 0:
        return "bad"
    return "warn"


def _vals(res: Result, f) -> tuple[float, float, float]:
    """(central, min, max) of f(case_result) over the three cases."""
    v = [f(res.cases[k]) for k in ("pessimistic", "central", "optimistic")]
    return v[1], min(v), max(v)


def _be_text(be: float | None, lg: str) -> str:
    if be is None:
        return "–"
    if be <= 0:
        return "nicht erreichbar" if lg == "de" else "not reachable"
    return f"{fmt_num(be, 3, lg)} EUR/kWh"


def _calibration_note(res: Result, lg: str) -> None:
    sp = res.context.splash if res.status == "ok" else None
    cal = (sp.calibration if sp else None) or {}
    if cal.get("applied"):
        f = cal["factor"]
        txt = t("calib_note", lg, f=fmt_num(f, 2, lg), a=fmt_num(cal["raw_model_mwh"], 0, lg), b=fmt_num(cal["target_mwh"], 0, lg))
        note("info", txt + (" " + t("calib_clipped", lg) if cal.get("clipped") else ""))


def _warn_notes(res: Result, lg: str) -> None:
    for w in res.parsed.warnings:
        code = w["code"]
        key = {"existing_heat_pump": "existing_hp_note", "dh_binding": "dh_binding_note",
               "no_tolerance": "no_tolerance_note", "open_air": "open_air_note",
               "no_basins": "insufficient_note", "hours_invalid": "warn_hours_invalid",
               "boiler_eta_range": "warn_boiler_eta_range", "basin_size": "warn_basin_size",
               "basin_depth_order": "warn_basin_depth", "combined_no_outdoor": "warn_combined_no_outdoor",
               "shower_litres_range": "warn_shower_litres_range", "dhw_tank_range": "warn_dhw_tank_range",
               "dhw_tank_missing": "warn_dhw_tank_missing"}.get(code)
        if key:
            note("warn", t(key, lg))


def _default_band_k() -> float:
    """Allowed temperature rise from the questionnaire (question 11), else 2 K, limited to the slider range."""
    from splash_calc import from_answers

    k = from_answers(visible_answers(answers()), Params.load()).inputs.allowed_change_k
    return float(min(max(k if k is not None else 2.0, 0.25), 5.0))


def _controls(lg: str) -> None:
    ss = st.session_state
    o = ss["opts"]
    base = Params.load()
    with st.expander("🎚️ " + ("Spielraum: Was wäre wenn?" if lg == "de" else "What if? Adjust the assumptions"), expanded=True):
        c1, c2 = st.columns(2)
        o["fuel_factor"] = c1.slider(t("sl_gas_price", lg), 0.5, 1.8, float(o["fuel_factor"]), 0.05, key="sl_fuel")
        o["el_factor"] = c2.slider(t("sl_el_price", lg), 0.5, 1.8, float(o["el_factor"]), 0.05, key="sl_el")
        c4, c5, c6 = st.columns(3)
        o["hp_kw"] = c4.number_input(t("sl_hp_cap", lg) + " (0 = auto)", min_value=0.0, value=float(o["hp_kw"] or 0.0),
                                     step=5.0, key="sl_hp") or None
        band0 = _default_band_k()
        v = c5.slider(t("sl_band", lg), 0.25, 5.0, float(o.get("band_k") or band0), 0.25, key=f"sl_band_{band0:g}",
                      format="%.2f K", help=t("sl_band_help", lg))
        o["band_k"] = None if abs(v - band0) < 1e-9 else float(v)
        price0 = float(base.central("curtailed_price_eur_per_mwh"))
        p = c6.number_input(t("curt_price", lg) + " (EUR/MWh)", min_value=0.0, max_value=400.0,
                            value=float(o.get("curt_mwh") if o.get("curt_mwh") is not None else price0), step=1.0,
                            key="sl_curt", help=t("curt_help", lg))
        o["curt_mwh"] = None if abs(p - price0) < 1e-9 else float(p)
        st.caption(t("curt_help", lg))
        zones = ["auto", "T5", "T6"]
        zl = {"auto": t("zone_auto", lg), "T5": "T5", "T6": "T6"}
        cur_z = o.get("zone") or "auto"
        pick = st.radio(t("sl_zone", lg), zones, index=zones.index(cur_z), format_func=lambda x: zl[x], horizontal=True,
                        key="sl_zone", help=t("sl_zone_help", lg))
        o["zone"] = None if pick == "auto" else pick
        o["calibrate"] = st.toggle(t("sl_calibrate", lg), value=bool(o.get("calibrate")), key="sl_calibrate",
                                   help=t("sl_calibrate_help", lg))
        st.divider()
        _econ_panel(lg)
        st.divider()
        _recalc_bar(lg)
        if st.button(t("sl_reset", lg), key="sl_reset_btn"):
            ss.pop("applied_opts", None)
            ss.pop("calc_no", None)
            ss["opts"] = {"fuel_factor": 1.0, "el_factor": 1.0, "hp_kw": None, "band_k": None, "curt_mwh": None,
                          "zone": None, "econ": {}, "calibrate": False}
            for k in list(ss.keys()):
                if k in ("sl_fuel", "sl_el", "sl_hp", "sl_curt", "sl_zone", "sl_calibrate") or k.startswith(("sl_band_", "ec_")):
                    ss.pop(k, None)
            st.rerun()


def _opts_json(o: dict) -> str:
    return json.dumps(o, sort_keys=True, default=str)


def _is_dirty() -> bool:
    ss = st.session_state
    return "applied_opts" in ss and _opts_json(ss["opts"]) != _opts_json(ss["applied_opts"])


def _changes_text(o: dict, lg: str) -> str:
    """Short list of the settings that differ from the defaults, for the confirmation line."""
    parts: list[str] = []
    if abs(float(o.get("fuel_factor") or 1) - 1) > 1e-9:
        parts.append(f"{t('sl_gas_price', lg)} {fmt_num(o['fuel_factor'], 2, lg)}")
    if abs(float(o.get("el_factor") or 1) - 1) > 1e-9:
        parts.append(f"{t('sl_el_price', lg)} {fmt_num(o['el_factor'], 2, lg)}")
    if o.get("hp_kw"):
        parts.append(f"{t('sl_hp_cap', lg)} {fmt_num(o['hp_kw'], 0, lg)}")
    if o.get("band_k"):
        parts.append(f"{t('sl_band', lg)} {fmt_num(o['band_k'], 2, lg)}")
    if o.get("curt_mwh") is not None:
        parts.append(f"{t('curt_price', lg)} {fmt_num(o['curt_mwh'], 0, lg)} EUR/MWh")
    if o.get("zone"):
        parts.append(f"{t('sl_zone', lg)} {o['zone']}")
    if o.get("calibrate"):
        parts.append(t("sl_calibrate", lg))
    labels = {f[0]: (f[1] if lg == "de" else f[2]) for f in ECON_FIELDS}
    for k, v in (o.get("econ") or {}).items():
        parts.append(f"{labels.get(k, k)} {fmt_num(float(v), 4 if float(v) < 1 else 0, lg)}")
    return "; ".join(parts) if parts else t("recalc_defaults", lg)


def _recalc_bar(lg: str) -> None:
    """The one place where changed assumptions are applied. Inputs only change a draft until this button is pressed."""
    import time

    ss = st.session_state
    if "applied_opts" not in ss:
        ss["applied_opts"] = copy.deepcopy(ss["opts"])
    dirty = _is_dirty()
    if st.button(t("recalc_btn", lg), type="primary" if dirty else "secondary", key="recalc_btn", disabled=not dirty,
                 use_container_width=True):
        ss["applied_opts"] = copy.deepcopy(ss["opts"])
        ss["calc_no"] = int(ss.get("calc_no", 0)) + 1
        ss["calc_at"] = time.strftime("%H:%M:%S")
        ss["calc_pending_toast"] = True
        st.rerun()
    if dirty:
        st.caption(t("recalc_dirty", lg))
    elif ss.get("calc_no"):
        st.caption(t("recalc_done", lg, n=ss["calc_no"], at=ss.get("calc_at", ""), what=_changes_text(ss["applied_opts"], lg)))
    else:
        st.caption(t("recalc_clean", lg))


def _wacc_helper(lg: str) -> float | None:
    """Small WACC calculator. Returns the computed value; the caller decides whether to adopt it."""
    c1, c2, c3, c4 = st.columns(4)
    eq = c1.number_input("Eigenkapitalanteil (%)" if lg == "de" else "Equity share (%)", 0.0, 100.0, 30.0, 5.0, key="wc_eq")
    ke = c2.number_input("Eigenkapitalkosten (% p. a.)" if lg == "de" else "Cost of equity (% p.a.)", 0.0, 25.0, 8.0, 0.25, key="wc_ke")
    kd = c3.number_input("Fremdkapitalzins (% p. a.)" if lg == "de" else "Cost of debt (% p.a.)", 0.0, 15.0, 4.0, 0.25, key="wc_kd")
    tx = c4.number_input("Steuersatz auf Zinsen (%)" if lg == "de" else "Tax rate on interest (%)", 0.0, 45.0, 0.0, 1.0, key="wc_tx",
                         help=t("wacc_tax_help", lg))
    w = (eq / 100) * ke / 100 + (1 - eq / 100) * kd / 100 * (1 - tx / 100)
    st.caption(f"WACC = {w * 100:.2f} %")
    return w


def _econ_panel(lg: str) -> None:
    """Editable economic assumptions. Defaults are German typical values from the parameter file."""
    ss = st.session_state
    o = ss["opts"]
    base = Params.load()
    econ = o.setdefault("econ", {})
    if True:
        st.markdown("**💶 " + t("econ_title", lg) + "**")
        st.caption(t("econ_intro", lg))
        cols = st.columns(3)
        for i, (name, de, en, lo, hi, step, fmt, _f) in enumerate(ECON_FIELDS):
            d = base.central(name)
            val = econ.get(name, d)
            integer = name == "lifetime_years"
            v = cols[i % 3].number_input(
                de if lg == "de" else en,
                min_value=int(lo) if integer else float(lo), max_value=int(hi) if integer else float(hi),
                value=int(val) if integer else float(val), step=int(step) if integer else float(step),
                format=fmt if not integer else None, key=f"ec_{name}",
                help=t("econ_default", lg, v=f"{d:g}"))
            if abs(float(v) - float(d)) > 1e-12:
                econ[name] = v
            else:
                econ.pop(name, None)
        if st.toggle(t("wacc_calc", lg), key="wc_toggle"):
            w = _wacc_helper(lg)
            if st.button(t("wacc_apply", lg), key="wc_apply") and w is not None:
                econ["wacc"] = round(w, 4)
                ss["ec_wacc"] = round(w, 4)
                st.rerun()
        d_real = (1 + float(econ.get("wacc", base.central("wacc")))) / (1 + float(econ.get("inflation", base.central("inflation")))) - 1
        st.caption(t("econ_real_rate", lg, r=f"{d_real * 100:.2f}"))
        st.caption(t("econ_vat", lg))


def _overview(res: Result, params: Params, lg: str) -> None:
    c = res.central
    b = c.baseline
    st.markdown(f"### {t('baseline_title', lg)}")
    kpi_row([
        {"label": t("baseline_heat", lg), "value": fmt_kwh(b.e_fuel_total, lg),
         "range": (f"{fmt_num(b.kwh_per_m2, 0, lg)} kWh/m²" if b.kwh_per_m2 else "")},
        {"label": t("baseline_cost", lg), "value": fmt_eur(c.base_cost_eur, lg), "range": t("per_year", lg)},
        {"label": t("baseline_co2", lg), "value": f"{fmt_num(c.base_co2_t, 0, lg)} t", "range": t("per_year", lg)},
    ])
    note("info", t("model_basis_note", lg))
    if b.heat_is_default:
        note("warn", t("heat_default_note", lg))
    if b.reported_q_use_kwh:
        ratio = b.q_use_kwh / b.reported_q_use_kwh
        kind = "recon_high" if ratio > 1.5 else "recon_low" if ratio < 0.67 else "recon_ok"
        note("warn" if kind != "recon_ok" else "info",
             t(kind, lg, pct=fmt_num(abs(ratio - 1) * 100, 0, lg), f=fmt_num(ratio, 1, lg)))
    if b.plausibility in ("low", "high"):
        note("warn", t(f"plaus_{b.plausibility}", lg))
    ent, tot = res.parsed.confidence()
    st.progress(ent / tot, text=f"{t('confidence', lg)}: " + t("confidence_text", lg, n=ent, m=tot))

    key = _selected_key()
    if c.hp is not None:
        left, right = st.columns(2)
        with left:
            st.markdown(f"### 🌡️ {t('tab_hp', lg)}")
            _hp_tiles(res, lg)
        with right:
            st.markdown(f"### ⚡ {t('tab_flex', lg)} ({_key_text(key, lg)})")
            _flex_tiles(res, key, lg)
    else:
        st.markdown(f"### ⚡ {t('tab_flex', lg)} ({_key_text(key, lg)})")
        _flex_tiles(res, key, lg)
    st.plotly_chart(charts.npv_ranges(res, key, lg), **stretch())
    cc1, cc2 = st.columns(2)
    cc1.plotly_chart(charts.demand_reconciliation(res.context.levels, b, lg), **stretch())
    cc2.plotly_chart(charts.monthly_demand(res.context.levels, lg), **stretch())
    if b.plausibility and not b.heat_is_default:
        with st.expander(t("bench_title", lg)):
            st.plotly_chart(charts.benchmark(b.kwh_per_m2, params.central("bench_heat_kwh_per_m2"), lg, b.heat_is_default),
                            **stretch())
            st.caption(t("bench_note", lg))


def _hp_tiles(res: Result, lg: str) -> None:
    c = res.central
    es = _vals(res, lambda cr: sum(cr.hp.res.fuel_saved_kwh.values()))
    sv = _vals(res, lambda cr: cr.hp.econ.net_saving_eur_y1)
    nv = _vals(res, lambda cr: cr.hp.econ.npv_eur)
    co = _vals(res, lambda cr: cr.hp.co2.net_t_y1)
    kpi_row([
        {"label": t("kpi_energy_saved", lg), "value": fmt_kwh(es[0], lg), "range": f"{fmt_num(c.hp.res.coverage * 100, 0, lg)} %"},
        {"label": t("kpi_cost_saved", lg), "value": fmt_eur(sv[0], lg), "range": fmt_range(sv[1], sv[2], lambda x: fmt_num(x, 0, lg)),
         "tone": _tone(sv[1], sv[2])},
        {"label": t("kpi_npv", lg), "value": fmt_eur(nv[0], lg), "range": fmt_range(nv[1], nv[2], lambda x: fmt_num(x, 0, lg)),
         "tone": _tone(nv[1], nv[2])},
        {"label": t("kpi_co2", lg), "value": f"{fmt_num(co[0], 0, lg)} t", "range": fmt_range(co[1], co[2], lambda x: fmt_num(x, 0, lg)),
         "tone": _tone(co[1], co[2])},
    ])
    ir = c.hp.econ.irr
    dp = c.hp.econ.discounted_payback_years
    kpi_row([
        {"label": t("kpi_irr", lg), "value": "–" if ir is None else f"{fmt_num(ir * 100, 1, lg)} %", "range": t("kpi_irr_note", lg)},
        {"label": t("kpi_dpayback", lg), "value": "–" if dp is None else f"{fmt_num(dp, 1, lg)} " + t("years", lg), "range": t("kpi_dpayback_note", lg)},
    ])


def _selected_key() -> str:
    from splash_calc.flexsplash import flex_key
    from splash_calc.splash_engine import DEFAULT_SIZE, DEFAULT_YEAR

    ss = st.session_state
    return flex_key(int(ss.get("flex_year", DEFAULT_YEAR)), float(ss.get("flex_size", DEFAULT_SIZE)))


def _key_text(key: str, lg: str) -> str:
    from splash_calc.flexsplash import parse_key

    y, s = parse_key(key)
    return f"{y}, {t('flex_size_short', lg)} {int(round(s * 100))} %"


def _flex_tiles(res: Result, key: str, lg: str) -> None:
    c = res.central
    fo = c.flex[key]
    sv = _vals(res, lambda cr: cr.flex[key].econ.net_saving_eur_y1)
    nv = _vals(res, lambda cr: cr.flex[key].econ.npv_eur)
    co = _vals(res, lambda cr: cr.flex[key].co2.net_curtailed_zero_t_y1)
    kpi_row([
        {"label": t("kpi_absorbed", lg), "value": fmt_kwh(fo.res.absorbed_kwh_el, lg),
         "range": f"{t('kpi_displaced', lg)}: {fmt_kwh(fo.res.displaced_kwh_th, lg)}"},
        {"label": t("kpi_cost_saved", lg), "value": fmt_eur(sv[0], lg), "range": fmt_range(sv[1], sv[2], lambda x: fmt_num(x, 0, lg)),
         "tone": _tone(sv[1], sv[2])},
        {"label": t("kpi_npv", lg), "value": fmt_eur(nv[0], lg), "range": fmt_range(nv[1], nv[2], lambda x: fmt_num(x, 0, lg)),
         "tone": _tone(nv[1], nv[2])},
        {"label": t("kpi_co2", lg), "value": f"{fmt_num(co[0], 0, lg)} t",
         "range": f"{t('co2_view_grid', lg)}: {fmt_num(fo.co2.net_t_y1, 0, lg)} t", "tone": _tone(co[1], co[2])},
    ])


def _hp_tab(res: Result, params: Params, lg: str) -> None:
    c = res.central
    h = c.hp
    _hp_tiles(res, lg)
    pb = f"{fmt_num(h.econ.payback_years, 1, lg)} {t('years', lg)}" if h.econ.payback_years is not None else t("no_payback", lg)
    kpi_row([
        {"label": t("kpi_capacity", lg), "value": f"{fmt_num(h.res.capacity_kw_th, 0, lg)} kW",
         "range": f"{t('kpi_scop', lg)}: {fmt_num(h.res.scop, 1, lg)}"},
        {"label": t("kpi_invest", lg), "value": fmt_eur(h.investment, lg)},
        {"label": t("kpi_grant", lg), "value": fmt_eur(h.subsidy["grant_eur"], lg),
         "range": f"{fmt_num(h.subsidy['rate'] * 100, 0, lg)} %"},
        {"label": t("kpi_payback", lg), "value": pb},
    ])
    note("info", t("grant_note", lg))
    a, b = st.columns(2)
    a.plotly_chart(charts.energy_bars(c, lg), **stretch())
    b.plotly_chart(charts.cashflow(c, _selected_key(), lg), **stretch())
    if res.tornado.get("hp"):
        st.plotly_chart(charts.tornado(res.tornado["hp"], lg), **stretch())
        st.caption(t("tornado_caption", lg))


def _size_table(res: Result, year: int, lg: str) -> pd.DataFrame:
    from splash_calc.flexsplash import flex_key
    from splash_calc.splash_engine import SIZES

    rows = []
    for x in SIZES:
        fo = res.central.flex[flex_key(year, x)]
        r = fo.res
        rows.append({
            t("flex_size", lg): f"{int(round(x * 100))} %",
            "kW el": fmt_num(r.capacity_kw_el, 0, lg),
            t("kpi_absorbed", lg) + " (MWh)": fmt_num(r.absorbed_kwh_el / 1000, 0, lg),
            t("kpi_displaced", lg) + " (MWh)": fmt_num(r.displaced_kwh_th / 1000, 0, lg),
            t("tbl_share_zone", lg): f"{fmt_num(r.share_of_zone * 100, 1, lg)} %",
            t("tbl_hours", lg): fmt_num(r.absorption_hours, 0, lg),
            t("tbl_util", lg): f"{fmt_num(r.utilisation * 100, 0, lg)} %",
            t("kpi_invest", lg) + " (EUR)": fmt_num(fo.investment, 0, lg),
            t("kpi_npv", lg) + " (EUR)": fmt_num(fo.econ.npv_eur, 0, lg),
        })
    return pd.DataFrame(rows)


def _flex_tab(res: Result, params: Params, lg: str, selectors: bool = True) -> None:
    from splash_calc.flexsplash import parse_key
    from splash_calc.splash_engine import SIZES, YEARS

    ctx = res.context
    sr = ctx.splash
    years_lbl = {y: (str(y) if res.central.flex[f"{y}_100"].res.full_year else t("year_ytd", lg, y=y)) for y in YEARS}
    if selectors:
        c1, c2 = st.columns(2)
        c1.radio(t("flex_year", lg), list(YEARS), format_func=lambda y: years_lbl[y], horizontal=True, key="flex_year")
        c2.radio(t("flex_size", lg), list(SIZES), index=list(SIZES).index(2.0), format_func=lambda x: f"{int(x * 100)} %",
                 horizontal=True, key="flex_size", help=t("flex_size_help", lg))
    key = _selected_key()
    year, _ = parse_key(key)
    c = res.central
    fo = c.flex[key]
    r = fo.res
    if not r.full_year:
        note("warn", t("year_partial_note", lg))
    _flex_tiles(res, key, lg)
    kpi_row([
        {"label": t("kpi_capacity", lg), "value": f"{fmt_num(r.capacity_kw_el, 0, lg)} kW el",
         "range": f"{t('design_load', lg)}: {fmt_num(sr.design_kw, 0, lg)} kW th"},
        {"label": t("kpi_invest", lg), "value": fmt_eur(fo.investment, lg)},
        {"label": t("kpi_breakeven", lg), "value": _be_text(fo.econ.break_even_price, lg),
         "range": (t("be_unreachable_hint", lg) if (fo.econ.break_even_price is None or fo.econ.break_even_price <= 0)
                   else f"{t('curt_price', lg)}: {fmt_num(fo.price_eff, 3, lg)} EUR/kWh")},
        {"label": t("kpi_curt_hours", lg), "value": fmt_num(r.curtail_hours, 0, lg),
         "range": f"{t('tbl_hours', lg)}: {fmt_num(r.absorption_hours, 0, lg)}"},
    ])
    grid = ctx.inp.grid_kw
    if grid:
        ok = r.capacity_kw_el <= float(grid)
        note("info" if ok else "warn", t("grid_ok" if ok else "grid_exceeded", lg, h=fmt_num(r.capacity_kw_el, 0, lg), g=fmt_num(grid, 0, lg)))
    key_thr = "flex_threshold_ok" if r.above_threshold else "flex_threshold_below"
    note("info", t(key_thr, lg, k=fmt_num(r.flex_threshold_kw, 0, lg)))
    if res.sensitivity_band2.get(key):
        note("info", t("band2", lg, npv=fmt_eur(res.sensitivity_band2[key]["npv_eur"], lg)))
    _splash_notes(res, lg)

    st.markdown(f"#### {t('size_table_title', lg, y=years_lbl[year])}")
    st.dataframe(_size_table(res, year, lg), hide_index=True, **stretch())
    st.caption(t("size_table_help", lg))
    sub = st.tabs([t("fx_sub_year", lg), t("fx_sub_week", lg), t("fx_sub_flow", lg), t("fx_sub_size", lg)])
    with sub[0]:
        st.caption(t("fx_year_help", lg))
        st.plotly_chart(flexcharts.year_heatmaps(fo, lg), key="fx_heat", **stretch())
        m1, m2 = st.columns(2)
        m1.plotly_chart(flexcharts.monthly_absorption(fo, lg), key="fx_month", **stretch())
        m2.plotly_chart(flexcharts.monthly_coverage(fo, lg), key="fx_cover", **stretch())
    with sub[1]:
        nw = flexcharts.n_weeks(fo)
        best = flexcharts.best_week(fo) + 1
        if st.session_state.get("fx_week_key") != key:
            st.session_state["fx_week_key"] = key
            st.session_state["fx_week"] = best
        st.session_state["fx_week"] = min(max(int(st.session_state.get("fx_week", best)), 1), nw)
        wk = st.slider(t("fx_week_pick", lg), 1, nw, key="fx_week", help=t("fx_week_best", lg) + f": {best}")
        st.plotly_chart(flexcharts.week_dispatch(fo, wk - 1, lg), key="fx_week_chart", **stretch())
        st.plotly_chart(flexcharts.duration_curve(fo, lg), key="fx_duration", **stretch())
    with sub[2]:
        st.plotly_chart(flexcharts.energy_flow(fo, lg), key="fx_flow", **stretch())
        st.plotly_chart(charts.npv_vs_price(fo, params, lg), key="fx_npv_price", **stretch())
    with sub[3]:
        s1, s2 = st.columns(2)
        s1.plotly_chart(charts.size_comparison(res, lg), key="fx_size_cmp", **stretch())
        s2.plotly_chart(flexcharts.size_efficiency(res, year, lg), key="fx_size_eff", **stretch())
    st.plotly_chart(charts.cashflow(c, key, lg), key="flex_cashflow", **stretch())
    rows = res.tornado.get("flex", {}).get(key)
    if rows:
        st.plotly_chart(charts.tornado(rows, lg), **stretch())
        st.caption(t("tornado_caption", lg))
    _model_expander(res, lg)


def _splash_notes(res: Result, lg: str) -> None:
    ctx = res.context
    sr = ctx.splash
    note("warn", t("note_tmy", lg))
    synth = [k for k in ("occupancy", "hall_geometry") if sr.flags.get(k)]
    if synth:
        note("warn", t("note_synth", lg))
    d = sr.dhw
    if d.get("enabled"):
        if d.get("visitor_source") == "default":
            note("warn", t("dhw_note_default", lg))
        note("info", t("dhw_note", lg, v=fmt_num(d["visitors_per_year"], 0, lg), l=fmt_num(d["litres_per_visitor"], 0, lg),
                       e=fmt_num(sr.demand_dhw_mwh.get(2025, 0.0), 0, lg), p=fmt_num(d["peak_kw"], 0, lg)))
        if d.get("tank_m3"):
            note("info", t("dhw_tank_note", lg, v=fmt_num(d["tank_m3"], 1, lg), e=fmt_num(d["tank_kwh"], 0, lg), h=fmt_num(d["window_h"], 0, lg))
                 + (" " + t("dhw_tank_capped", lg) if d.get("window_capped") else ""))
    else:
        note("info", t("dhw_note_off", lg))
    if not ctx.zone_mapped:
        note("info", t("note_zone_default", lg, z=ctx.zone))


def _model_expander(res: Result, lg: str) -> None:
    ctx = res.context
    sr = ctx.splash
    with st.expander(t("model_expander", lg), expanded=False):
        st.markdown(t("model_text", lg, v=sr.version, z=ctx.zone))
        rows = []
        for m in sr.basins:
            rows.append({
                t("mp_basin", lg): m.index + 1, t("mp_class", lg): m.size_class,
                t("mp_env", lg): ("innen" if lg == "de" else "indoor") if m.environment == "indoor" else ("außen" if lg == "de" else "outdoor"),
                "m²": fmt_num(m.area_m2, 0, lg), "m³": fmt_num(m.volume_m3, 0, lg),
                t("mp_band", lg): f"{fmt_num(m.t_min, 1, lg)} - {fmt_num(m.t_max, 1, lg)} °C",
                t("mp_notes", lg): ", ".join(t(f"mn_{n}", lg) for n in m.notes),
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, **stretch())
        worst = max(fo.res.max_residual for fo in res.central.flex.values())
        st.caption(t("model_check", lg, x=f"{worst:.1e}"))
        if sr.dhw.get("enabled"):
            st.caption(t("model_design_dhw", lg, d=fmt_num(sr.design_kw, 0, lg), b=fmt_num(sr.design_basins_kw, 0, lg),
                         h=fmt_num(sr.design_hall_kw, 0, lg), w=fmt_num(sr.design_dhw_kw, 0, lg), s=fmt_num(sr.storage_kwh, 0, lg)))
        else:
            st.caption(t("model_design", lg, d=fmt_num(sr.design_kw, 0, lg), b=fmt_num(sr.design_basins_kw, 0, lg),
                         h=fmt_num(sr.design_hall_kw, 0, lg), s=fmt_num(sr.storage_kwh, 0, lg)))


def _assumptions_tab(params: Params, lg: str) -> None:
    st.caption(t("assump_intro", lg))
    df = pd.DataFrame(params.table(lg))
    df["value"] = df["value"].map(lambda v: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v))
    status_filter = st.multiselect("Status", ["sourced", "project", "illustrative"],
                                   default=["sourced", "project", "illustrative"], key="assump_filter")
    df = df[df["status"].isin(status_filter)]
    st.dataframe(df[["label", "value", "range", "unit", "status", "source"]], hide_index=True, **stretch())
    counts = params.status_counts()
    st.caption(" · ".join(f"{k}: {v}" for k, v in counts.items()))


def _download(res: Result, params: Params, ans: dict, lg: str) -> None:
    st.caption(t("dl_note", lg))
    pdf = build_pdf(res, params, ans, lg, _selected_key())
    st.download_button(t("dl_pdf", lg), data=pdf, file_name="splash-questionnaire-simulation.pdf", mime="application/pdf",
                       type="primary", key="dl_pdf_btn")
    key = _selected_key()
    c1, c2 = st.columns(2)
    c1.download_button(t("dl_table", lg), data=exports.results_table(res).to_csv(index=False).encode("utf-8"),
                       file_name="splash-questionnaire-simulation-results.csv", mime="text/csv", key="dl_table_btn")
    c2.download_button(t("dl_hourly", lg, k=_key_text(key, lg)), data=exports.hourly_table(res, key).to_csv(index=False).encode("utf-8"),
                       file_name=f"splash-questionnaire-simulation-hourly-{key}.csv", mime="text/csv", key="dl_hourly_btn")


def render() -> None:
    lg = lang()
    ans = visible_answers(answers())
    name = ans.get("q1_name") or ""
    mini_hero(t("res_title", lg), f"{t('res_for', lg)} {name}" if name else "")
    _controls(lg)
    ss = st.session_state
    if "applied_opts" not in ss:
        ss["applied_opts"] = copy.deepcopy(ss["opts"])
    if _is_dirty():
        note("warn", t("recalc_dirty_top", lg))
    opts = ss["applied_opts"]
    res, params = compute(json.dumps(ans, sort_keys=True, default=str), json.dumps(overrides_from(opts), sort_keys=True),
                          json.dumps(opts, sort_keys=True, default=str), lg)
    st.session_state["_last_result"] = res
    st.session_state["_last_params"] = params
    if ss.pop("calc_pending_toast", False):
        st.toast(t("recalc_toast", lg, n=ss.get("calc_no", 0)), icon="✅")

    if res.params_draft:
        note("warn", t("draft_params", lg))
    _warn_notes(res, lg)
    _calibration_note(res, lg)

    if res.status == "insufficient":
        note("bad", t("insufficient_note", lg))
        return

    if res.status == "open_air":
        b = res.baseline
        kpi_row([{"label": t("baseline_bench", lg), "value": f"{fmt_num(b.kwh_per_m2, 0, lg)} kWh/m²" if b.kwh_per_m2 else "–"}])
        st.plotly_chart(charts.benchmark(b.kwh_per_m2, params.central("bench_heat_kwh_per_m2"), lg, b.heat_is_default),
                        **stretch())
        names = [t("tab_flex", lg), t("tab_assump", lg), t("tab_download", lg)]
        tabs = st.tabs(names)
        with tabs[0]:
            _flex_tab(res, params, lg)
        with tabs[1]:
            _assumptions_tab(params, lg)
        with tabs[2]:
            _download(res, params, ans, lg)
    else:
        tech = dashboard.tech_selector(lg)
        items = prov.resolve(res.parsed, ans)
        ss["_last_items"] = items
        names = [L(lg, "1 Heute", "1 Today"), L(lg, "2 Wärmespeicher", "2 Thermal battery"), L(lg, "3 Technologien", "3 Technologies"),
                 L(lg, "4 Überschussstrom", "4 Curtailment"), L(lg, "5 Finanzen", "5 Finance"),
                 L(lg, "Herkunft & Annahmen", "Provenance & assumptions"), t("tab_download", lg)]
        tabs = st.tabs(names)
        with tabs[0]:
            dashboard.section_today(res, items, lg)
            with st.expander(L(lg, "Technische Details: Bedarfsaufteilung", "Technical detail: demand breakdown")):
                cc1, cc2 = st.columns(2)
                cc1.plotly_chart(charts.demand_reconciliation(res.context.levels, res.central.baseline, lg), key="ov_recon", **stretch())
                cc2.plotly_chart(charts.monthly_demand(res.context.levels, lg), key="ov_month", **stretch())
        with tabs[1]:
            dashboard.section_battery(res, items, lg)
        with tabs[2]:
            shown = dashboard.section_tech(res, tech, lg)
            if res.central.hp is not None and tech in ("hp", "both"):
                with st.expander(L(lg, "Technische Details: Wärmepumpe", "Technical detail: heat pump")):
                    _hp_tab(res, params, lg)
        with tabs[3]:
            dashboard.section_curtailment(res, tech, lg)
            dashboard.readiness(res, items, ans, lg)
            with st.expander(L(lg, "Technische Details: Heizstab", "Technical detail: resistance heater")):
                _flex_tab(res, params, lg, selectors=False)
        with tabs[4]:
            dashboard.section_finance(res, params, shown, items, lg)
        with tabs[5]:
            st.markdown(f"#### {L(lg, 'Herkunft der Eingaben', 'Provenance of inputs')}")
            dashboard.provenance_table(items, lg)
            st.markdown(f"#### {L(lg, 'Parameter und Annahmen', 'Parameters and assumptions')}")
            _assumptions_tab(params, lg)
        with tabs[6]:
            _download(res, params, ans, lg)

    st.markdown(f"### {t('post_title', lg)}")
    render_step(4)
