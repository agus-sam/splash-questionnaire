"""Hot water for showers: visitors, model demand, design load, hot water tank, heat pump, exports, questions."""
import copy

import numpy as np
import pytest

from splash_app.demo import DEMO_ANSWERS
from splash_app.exports import hourly_table, results_table
from splash_calc import Options, Params, from_answers, run
from splash_calc.inputs import Basin, PoolInputs
from splash_calc.splash_engine import run_splash

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _answers(**over):
    a = copy.deepcopy(DEMO_ANSWERS)
    a.update(over)
    return a


def _sr(**over):
    return run(_answers(**over), Params.load(), with_tornado=False).context.splash


@pytest.fixture(scope="module")
def central():
    return _sr()


@pytest.fixture(scope="module")
def none():
    return _sr(q4_dhw_supply="none")


# ------------------------------------------------------------------ visitors
def test_annual_visitors_from_daily_values():
    p = PoolInputs(visitors_weekday=380, visitors_weekend=520, open_days=DAYS, operating_weeks=52)
    assert p.annual_visitors() == (pytest.approx((380 * 5 + 520 * 2) * 52), "derived")


def test_annual_visitors_follow_open_days_and_weeks():
    p = PoolInputs(visitors_weekday=100, visitors_weekend=300, open_days=["mon", "wed", "sat"], operating_weeks=20)
    assert p.annual_visitors()[0] == pytest.approx((100 * 2 + 300 * 1) * 20)


def test_annual_figure_wins_and_missing_group_takes_the_other():
    assert PoolInputs(visitors_year=80000, visitors_weekday=1).annual_visitors() == (80000.0, "entered")
    p = PoolInputs(visitors_weekday=200, open_days=DAYS, operating_weeks=10)
    assert p.annual_visitors()[0] == pytest.approx(200 * 7 * 10)
    assert PoolInputs().annual_visitors() == (None, "default")


def test_provenance_of_visitors(params):
    assert from_answers(_answers(), params).provenance["visitors"] == "estimated"
    assert from_answers(_answers(q4_visitors_year=90000), params).provenance["visitors"] == "entered"
    a = _answers(q4_visitors_weekday=None, q4_visitors_weekend=None)
    assert from_answers(a, params).provenance["visitors"] == "default"


def test_supply_and_litres_parsing(params):
    p = from_answers(_answers(q4_dhw_supply="bogus"), params).inputs
    assert p.dhw_supply == "central"
    assert from_answers(_answers(q4_dhw_supply="separate"), params).inputs.dhw_supply == "separate"
    ok = from_answers(_answers(r_shower_litres=70), params)
    assert ok.inputs.shower_litres == 70 and not any(w["code"] == "shower_litres_range" for w in ok.warnings)
    bad = from_answers(_answers(r_shower_litres=500), params)
    assert bad.inputs.shower_litres is None and any(w["code"] == "shower_litres_range" for w in bad.warnings)


# ------------------------------------------------------------------- engine
def test_demand_is_basins_hall_and_hot_water(central):
    b, h = central.demand_split_mwh[2025]
    assert central.dhw["enabled"]
    assert central.model_demand_mwh[2025] == pytest.approx(b + h + central.demand_dhw_mwh[2025], rel=1e-9)
    assert central.demand_dhw_mwh[2025] > 0
    assert central.demand_dhw_kw.sum() / 1000 == pytest.approx(central.demand_dhw_mwh[2025], rel=1e-9)


def test_hot_water_formula_with_derived_visitors(central):
    visitors = (380 * 5 + 520 * 2) * 52
    assert central.dhw["visitors_per_year"] == pytest.approx(visitors, rel=1e-6)
    per_m3 = central.demand_dhw_mwh[2025] * 1000 / (visitors * 0.05)       # kWh per m3 of shower water
    assert 30.0 < per_m3 < 38.0                                             # 40 C minus mains water of 6 to 17 C


def test_without_hot_water_nothing_changes_against_the_physics(none, central):
    assert none.demand_dhw_kw is None and none.design_dhw_kw == 0.0 and none.dhw["enabled"] is False
    b0, h0 = none.demand_split_mwh[2025]
    b1, h1 = central.demand_split_mwh[2025]
    assert (b0, h0) == pytest.approx((b1, h1))
    assert central.design_kw > none.design_kw
    assert central.design_kw <= none.design_kw + central.design_dhw_kw + 1e-6


def test_separate_and_none_are_the_same(none):
    sep = _sr(q4_dhw_supply="separate")
    assert sep.model_demand_mwh == none.model_demand_mwh and sep.design_kw == none.design_kw


def test_visitors_and_litres_scale_the_demand(central):
    half = _sr(q4_visitors_year=(380 * 5 + 520 * 2) * 52 / 2)
    assert half.demand_dhw_mwh[2025] == pytest.approx(central.demand_dhw_mwh[2025] / 2, rel=1e-6)
    l80 = _sr(r_shower_litres=80)
    assert l80.demand_dhw_mwh[2025] == pytest.approx(central.demand_dhw_mwh[2025] * 1.6, rel=1e-6)


def test_default_visitors_use_the_model_profile(central):
    d = _sr(q4_visitors_weekday=None, q4_visitors_weekend=None)
    assert d.dhw["visitor_source"] == "default" and not d.dhw["visitors_from_data"]
    assert d.demand_dhw_mwh[2025] > 0


def test_balances_and_no_unmet_heat_with_hot_water(central):
    for r in central.results.values():
        assert r.max_residual < 1e-3
        assert r.unmet_mwh_th == pytest.approx(0.0, abs=1e-6)
        assert r.demand_mwh_th == pytest.approx(central.model_demand_mwh[r.year] if r.year == 2025 else r.demand_mwh_th)
        assert r.hourly_dhw_kw is not None and r.hourly_dhw_kw.sum() > 0


def test_calibration_scales_basins_and_hall_but_not_hot_water(answers, params):
    cal = run(answers, params, Options(calibrate=True), False, "en").context.splash
    raw = run(answers, params, Options(), False, "en").context.splash
    assert cal.calibration["applied"]
    b, h = cal.demand_split_mwh[2025]
    assert b + h == pytest.approx(cal.calibration["target_mwh"], rel=1e-6) or cal.calibration["clipped"]
    assert cal.demand_dhw_mwh[2025] == pytest.approx(raw.demand_dhw_mwh[2025], rel=1e-9)
    assert cal.model_demand_mwh[2025] == pytest.approx(b + h + cal.demand_dhw_mwh[2025], rel=1e-9)
    assert cal.design_kw == pytest.approx(cal.design_basins_kw + cal.design_hall_kw + cal.design_dhw_kw, rel=1e-6)


def test_open_air_pool_with_hot_water():
    p = PoolInputs(name="Frei", pool_type="open_air", visitors_year=50000, season_year_round=False, season_from=(1, 5),
                   season_to=(30, 9), operating_weeks=21.9, basins=[Basin("lap", 50, 20, 1.8, 2.0, 24)], allowed_change_k=2.0)
    sr = run_splash(p, "T6")
    assert sr.dhw["enabled"] and sr.demand_dhw_mwh[2025] > 0
    assert sr.demand_dhw_mwh[2025] == pytest.approx(50000 * 0.05 * 1.163 * 30 / 1000, rel=0.3)
    assert max(r.max_residual for r in sr.results.values()) < 1e-3


# -------------------------------------------------------------- heat pump, export
def test_heat_pump_rule_serves_hot_water(answers, params):
    r = run(answers, params, with_tornado=False)
    hp = r.central.hp
    assert hp is not None and hp.res.dispatch == "rule"
    assert "dhw" in hp.res.served_levels
    assert hp.res.heat_hp_kwh > 0 and hp.res.scop > 1.0


def test_exports_carry_hot_water(answers, params):
    r = run(answers, params, with_tornado=False)
    t = results_table(r)
    assert (t["hot_water_demand_mwh_th"] > 0).all()
    h = hourly_table(r, "2025_200")
    assert {"heat_demand_total_kw", "heat_demand_hot_water_kw"} <= set(h.columns)
    assert h["heat_demand_hot_water_kw"].sum() / 1000 == pytest.approx(r.context.splash.demand_dhw_mwh[2025], rel=1e-3)
    assert (h["heat_demand_total_kw"] >= h["heat_demand_hot_water_kw"] - 1e-6).all()


def test_levels_have_a_hot_water_series(central, answers, params):
    r = run(answers, params, with_tornado=False)
    lv = r.context.levels
    assert np.asarray(lv["dhw"]).sum() / 1000 == pytest.approx(r.context.splash.demand_dhw_mwh[2025], rel=1e-9)
    assert r.context.q_use_kwh == pytest.approx(r.context.splash.model_demand_mwh[2025] * 1000)


def test_texts_exist_in_both_languages():
    from splash_app.i18n import t

    for k in ("dhw_note", "dhw_note_default", "dhw_note_off", "warn_shower_litres_range", "model_design_dhw"):
        assert t(k, "de") and t(k, "en") and t(k, "de") != t(k, "en")


# ---------------------------------------------------------------- hot water tank
TANK = {"q4_dhw_tank": "yes", "q4_dhw_tank_size": 5000, "q4_dhw_tank_unit": "l"}


def test_tank_parsing_units_and_limits(params):
    assert from_answers(_answers(**TANK), params).inputs.dhw_tank_m3 == pytest.approx(5.0)
    assert from_answers(_answers(**{**TANK, "q4_dhw_tank_size": 5, "q4_dhw_tank_unit": "m3"}), params).inputs.dhw_tank_m3 == pytest.approx(5.0)
    no = from_answers(_answers(q4_dhw_tank="no", q4_dhw_tank_size=5000), params)
    assert no.inputs.dhw_tank_m3 is None
    small = from_answers(_answers(**{**TANK, "q4_dhw_tank_size": 10}), params)
    assert small.inputs.dhw_tank_m3 is None and any(w["code"] == "dhw_tank_range" for w in small.warnings)
    miss = from_answers(_answers(q4_dhw_tank="yes"), params)
    assert any(w["code"] == "dhw_tank_missing" for w in miss.warnings)
    sep = from_answers(_answers(**TANK, q4_dhw_supply="separate"), params)
    assert sep.inputs.dhw_tank_m3 is None


def test_tank_lowers_the_design_load_and_leaves_demand_alone(central):
    big = _sr(q4_dhw_tank="yes", q4_dhw_tank_size=30, q4_dhw_tank_unit="m3")
    assert big.dhw["window_h"] == 12 and big.dhw["tank_kwh"] > 1000
    assert big.design_kw < central.design_kw and big.design_dhw_kw < central.design_dhw_kw
    assert big.model_demand_mwh == central.model_demand_mwh and big.demand_dhw_mwh == central.demand_dhw_mwh
    for r in big.results.values():
        assert r.max_residual < 1e-3 and r.unmet_mwh_th == pytest.approx(0.0, abs=1e-6)
    mid = _sr(**TANK)
    assert 1 < mid.dhw["window_h"] < 12 and big.design_kw <= mid.design_kw <= central.design_kw


def test_small_tank_gives_no_smoothing(central):
    small = _sr(q4_dhw_tank="yes", q4_dhw_tank_size=500, q4_dhw_tank_unit="l")
    assert small.dhw["window_h"] == 1 and small.design_kw == pytest.approx(central.design_kw)


def test_tank_texts_exist():
    from splash_app.i18n import t

    for k in ("dhw_tank_note", "warn_dhw_tank_range", "warn_dhw_tank_missing"):
        assert t(k, "de") and t(k, "en") and t(k, "de") != t(k, "en")
