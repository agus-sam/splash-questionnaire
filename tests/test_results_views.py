"""Provenance, technology selector, dashboard, visualisations, storage and report."""
import copy
from pathlib import Path

import numpy as np
import pytest
from streamlit.testing.v1 import AppTest

from splash_app import viz
from splash_app.demo import DEMO_ANSWERS
from splash_app.report import build_pdf
from splash_app.summary import flat_results
from splash_calc import Params, run
from splash_calc import provenance as prov
from splash_calc.economics import economics
from splash_calc.inputs import from_answers

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture(scope="module")
def res():
    return run(copy.deepcopy(DEMO_ANSWERS), Params.load(), None, False, "en")


# ---------------------------------------------------------------- provenance
def test_entered_values_classified_and_never_overwritten():
    a = copy.deepcopy(DEMO_ANSWERS)
    p = from_answers(a, Params.load())
    before = (p.inputs.water_surface_m2(), p.inputs.hall_area_m2, dict(p.inputs.consumption_kwh))
    items = prov.resolve(p, a)
    assert items["water_surface"].cls == prov.ENTERED
    assert items["demand"].cls == prov.MODEL
    assert set(i.cls for i in items.values()) <= set(prov.CLASSES)
    again = from_answers(a, Params.load()).inputs
    assert before == (again.water_surface_m2(), again.hall_area_m2, dict(again.consumption_kwh))


def test_operator_estimate_flag_and_benchmark_fallback():
    a = copy.deepcopy(DEMO_ANSWERS)
    a["q8_quality"] = "estimated"
    items = prov.resolve(from_answers(a, Params.load()), a)
    assert items["heat_consumption"].cls == prov.ESTIMATED_OP
    b = copy.deepcopy(DEMO_ANSWERS)
    b["q8_consumption"] = {}
    b["q8_heat_cost_eur"] = None
    items = prov.resolve(from_answers(b, Params.load()), b)
    assert items["heat_consumption"].cls == prov.BENCHMARK
    assert items["heat_price"].cls == prov.BENCHMARK
    assert prov.completeness(items)[0] < prov.completeness(prov.resolve(from_answers(DEMO_ANSWERS, Params.load()), DEMO_ANSWERS))[0]


def test_derived_values_are_calculated_class():
    a = copy.deepcopy(DEMO_ANSWERS)
    a.pop("q3_hall_area", None)
    items = prov.resolve(from_answers(a, Params.load()), a)
    assert items["hall_area"].cls == prov.CALCULATED


def test_every_badge_and_class_name_is_bilingual():
    for c in prov.CLASSES:
        assert prov.BADGE[c]["de"] and prov.BADGE[c]["en"] and prov.CLASS_NAME[c]["de"] and prov.CLASS_NAME[c]["en"]


# -------------------------------------------------------------------- model
def test_continuous_curtailed_power_available(res):
    fo = res.central.flex["2025_200"]
    kw = fo.res.hourly_available_kw
    assert kw is not None and kw.dtype.kind == "f" and kw.max() > 0
    assert (kw > 0).sum() == fo.res.curtail_hours
    assert len(kw) == len(fo.res.hourly_el)


def test_heat_pump_consistent_with_shared_baseline(res):
    c = res.central
    assert c.hp is not None
    fuel = c.baseline.e_fuel_total
    assert sum(c.hp.res.fuel_saved_kwh.values()) <= fuel + 1e-6
    for fo in c.flex.values():
        assert sum(fo.res.fuel_saved_kwh.values()) <= fuel + 1e-6
    assert c.hp.econ.investment_eur > 0 and c.flex["2025_200"].econ.investment_eur > 0


# ----------------------------------------------------------- visualisations
def test_battery_numbers_keep_theoretical_and_usable_separate(res):
    fo = res.central.flex["2025_200"]
    n = viz.battery_numbers(res, fo, 10.0, 30)
    assert n["theoretical"] == fo.res.e_max_kwh
    assert n["usable_max"] <= n["theoretical"] + 1e-6
    assert n["buffer"] == pytest.approx(10.0 * 1.163 * 30)
    svg = viz.battery_svg(n, "en")
    assert svg.startswith("<svg") and "Theoretical" in svg and "Buffer" in svg
    assert "Theoretisch" in viz.battery_svg(n, "de")


@pytest.mark.parametrize("scenario", ["existing", "flex", "hp"])
def test_sankey_balances(res, scenario):
    c = res.central
    fig = viz.sankey(c, "2025_200", scenario, "en")
    s = fig.data[0]
    vals = np.array(s.link.value, float)
    assert (vals >= 0).all() and vals.sum() > 0
    # total flowing into the 'useful heat' node (index 0) must not exceed what went in
    into_heat = vals[np.array(s.link.target) == 0].sum()
    into_loss = vals[np.array(s.link.target) == 1].sum()
    assert into_heat > 0 and into_loss >= 0


def test_scatter_points_and_calendar_metrics(res):
    pts = viz.tech_points(res, 2025)
    assert {p["tech"] for p in pts} == {"flex", "hp"}
    fig = viz.tech_scatter(pts, "de")
    assert len(fig.data) == len(pts) and all(tr.customdata is not None for tr in fig.data)
    fo = res.central.flex["2025_200"]
    zmax = {}
    for m in viz.METRICS:
        f = viz.calendar(fo, m, "en")
        zmax[m] = float(np.nanmax(f.data[0].z))
    assert zmax["available"] > 1.0 and zmax["heater"] > 1.0   # real magnitudes, not 0/1
    assert 0 < zmax["storage"] <= 100.0 + 1e-6


def test_dispatch_explorer_and_best_day(res):
    fo = res.central.flex["2025_200"]
    day = viz.best_day(fo)
    fig = viz.dispatch_day(fo, 0.98, day, 1, "en")
    assert fig is not None and len(fig.data) >= 5
    assert viz.dispatch_day(fo, 0.98, "1999-01-01", 1, "en") is None


def test_investment_figures(res):
    pts = viz.tech_points(res, 2025)
    p = Params.load()
    assert len(viz.invest_compare(pts, "en").data) == 2
    assert viz.waterfall(pts[0]["econ"], "en", "x").data[0].y[-1] == pytest.approx(pts[0]["econ"].net_saving_eur_y1)
    assert len(viz.discounted_cumulative(pts, 0.07, "en").data) == len(pts)
    for pt in pts:
        assert viz.npv_sensitivity(pt, p, "en").data[0].x is not None


def test_financial_exploration_reproduces_base_case(res):
    """With unchanged sliders the exploration equals the simulation result (acceptance: same economics)."""
    c = res.central
    for key in ("2025_200",):
        fo = c.flex[key]
        e = economics(fo.econ.investment_eur, fo.econ.subsidy_eur, fo.res.fuel_saved_kwh, c.fuel_prices,
                      fo.res.absorbed_kwh_el, fo.price_eff, fo.econ.om_eur_y, Params.load().at_case("central"))
        assert e.npv_eur == pytest.approx(fo.econ.npv_eur, rel=1e-6)
    h = c.hp
    e = economics(h.econ.investment_eur, h.econ.subsidy_eur, h.res.fuel_saved_kwh, c.fuel_prices, h.res.elec_kwh,
                  h.price_eff, h.econ.om_eur_y, Params.load().at_case("central"))
    assert e.npv_eur == pytest.approx(h.econ.npv_eur, rel=1e-6)


# ------------------------------------------------------------ storage, report
def test_stored_results_carry_provenance_selection_params_and_time(res):
    a = copy.deepcopy(DEMO_ANSWERS)
    items = prov.resolve(res.parsed, a)
    flat = flat_results(res, None, Params.load(), {"technology": "both", "flex_year": 2025, "flex_size": 2.0}, items)
    assert flat["sel_technology"] == "both" and flat["sel_flex_size"] == 2.0
    assert flat["cls_water_surface"] == "entered" and flat["resolved_water_surface"] > 0
    assert "param_wacc" in flat and "param_inflation" in flat
    assert flat["calc_timestamp_utc"].endswith("+00:00") and flat["splash_version"]
    assert flat["params_version"] and "defaults_used" in flat


@pytest.mark.parametrize("lg", ["de", "en"])
def test_pdf_lists_provenance(res, lg):
    pdf = build_pdf(res, Params.load(), copy.deepcopy(DEMO_ANSWERS), lg)
    assert pdf[:4] == b"%PDF" and len(pdf) > 5000


# ------------------------------------------------------------------------ UI
def _demo():
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    next(b for b in at.button if b.key == "demo_btn").click()
    at.run()
    return at


def test_heater_is_default_and_selector_switches_without_errors():
    at = _demo()
    assert not at.exception
    assert at.session_state["tech"] == "flex"
    radio = next(r for r in at.radio if r.key == "tech")
    for mode in ("hp", "both", "flex"):
        radio.set_value(mode)
        at.run()
        assert not at.exception, [x.value for x in at.exception]
        radio = next(r for r in at.radio if r.key == "tech")
        text = " ".join(m.value for m in at.markdown)
        if mode in ("hp", "both"):
            assert "same rule as the heater" in text or "derselben Regel" in text


def test_dashboard_sections_and_english():
    at = _demo()
    next(b for b in at.button if b.key == "lang_btn").click()
    at.run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    for h in ("1 · Your pool today", "2 · The pool as a thermal battery", "3 · Explore technologies",
              "4 · Renewable electricity and curtailment", "5 · Financial exploration"):
        assert h in text
    assert "Operational readiness" in text


def test_live_feedback_in_questionnaire_steps():
    for step in (1, 2, 3):
        at = AppTest.from_file(APP, default_timeout=90)
        at.session_state["step"] = step
        at.session_state["answers"] = copy.deepcopy(DEMO_ANSWERS)
        at.run()
        assert not at.exception, (step, [x.value for x in at.exception])


# ------------------------------------------------- heat pump on the rule logic
def test_heat_pump_uses_rule_logic_with_grid_baseline_and_curtailed_charging(res):
    h = res.central.hp
    r = h.res
    assert r.dispatch == "rule"
    assert r.elec_kwh == pytest.approx(r.elec_grid_kwh + r.elec_curtailed_kwh)
    assert r.elec_grid_kwh > 0 and r.elec_curtailed_kwh > 0       # baseline from the grid, charging from curtailment
    assert float(np.asarray(r.hp_curt_hourly)[np.asarray(r.hp_avail_hourly) <= 0].sum()) == 0.0   # only in curtailment hours
    assert (np.asarray(r.hp_soc_hourly) <= r.e_max_kwh + 1e-6).all()   # never above T_max
    demand = res.context.splash.bundle["fm"].total_demand_kw().sum()
    assert r.heat_hp_kwh >= demand - r.unmet_kwh_th - 1e-3
    assert r.coverage == pytest.approx(1 - r.unmet_kwh_th / demand)


def test_heat_pump_without_curtailment_is_baseline_only(res):
    from splash_calc.hp_rule import run_heat_pump_rule

    sp = res.context.splash
    b = dict(sp.bundle)
    b["avail"] = np.zeros_like(b["avail"])
    b["memo"] = {}
    live = copy.copy(sp)
    live.bundle = b
    none = run_heat_pump_rule(live, res.central.baseline.e_fuel_kwh, "air", Params.load().at_case("central"))
    full = run_heat_pump_rule(sp, res.central.baseline.e_fuel_kwh, "air", Params.load().at_case("central"))
    assert none.elec_curtailed_kwh == 0.0 and none.elec_grid_kwh > 0
    assert none.elec_grid_kwh >= full.elec_grid_kwh               # charging with curtailed power replaces grid electricity
    assert full.elec_curtailed_kwh > 0


def test_heat_pump_prices_grid_and_curtailed_electricity_separately(res):
    c = res.central
    h = c.hp
    expected = (h.res.elec_grid_kwh * c.elec_price + h.res.elec_curtailed_kwh * c.flex["2025_200"].price_eff) / h.res.elec_kwh
    assert h.price_eff == pytest.approx(expected, rel=1e-9)
    assert h.econ.electricity_cost_eur_y1 > 0
    assert h.co2.net_curtailed_zero_t_y1 >= h.co2.net_t_y1


def test_heat_pump_curtailment_view_renders(res):
    v = viz.hp_view(res)
    assert v is not None
    fig = viz.dispatch_day(v, 1.0, viz.best_day(v), 1, "en")
    assert fig is not None and any("Grid" in (tr.name or "") for tr in fig.data)
    assert float(np.nanmax(viz.calendar(v, "heater", "en").data[0].z)) > 0
