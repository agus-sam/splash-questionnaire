"""SPLASH model integration: data conversion, calendars, pool mapping and the charging rule."""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from splash_calc import Options, run
from splash_calc.flexsplash import ALL_KEYS, flex_key, parse_key
from splash_calc.inputs import Basin, PoolInputs
from splash_calc.splash_engine import (
    SIZES,
    YEARS,
    SplashInputError,
    calendar,
    curtailment_mw,
    map_pool,
    run_splash,
)

ROOT = Path(__file__).resolve().parent.parent


def _load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def pool():
    return PoolInputs(
        name="Testbad", pool_type="indoor", hall_area_m2=1500, allowed_change_k=2.0, heat_recovery=True,
        basins=[Basin("lap", 25, 12.5, 1.8, 2.0, 28), Basin("teaching", 12.5, 8, 1.0, 1.4, 30), Basin("children", 5, 4, 0.3, 0.5, 32)],
    )


@pytest.fixture(scope="module")
def run_t5(pool):
    return run_splash(pool, "T5")


# --------------------------------------------------------------- conversion
def test_operator_csv_conversion_dst_and_na(tmp_path):
    bc = _load_script("build_curtailment")
    rows = ["Datum;Zeitzone;von;bis;Einheit;H1;H2;T1;T2;T3;T4;T5;T6"]
    # autumn overlap 26.10.2025: 02:00 CEST and 02:00 CET both exist
    for tz, vals in (("CEST", "4,000"), ("CET", "8,000")):
        for m in ("00", "15", "30", "45"):
            rows.append(f"26.10.2025;{tz};02:{m};02:{m};MW;0;0;0;0;0;0;{vals};1.234,5")
    rows.append("27.10.2025;CET;00:00;00:15;MW;N.A.;N.A.;N.A.;N.A.;N.A.;N.A.;N.A.;N.A.")
    f = tmp_path / "op.csv"
    f.write_text("\n".join(rows), encoding="utf-8-sig")
    q = bc.read_operator_csv(f)
    assert q["utc"].is_unique
    assert q["T6"].iloc[0] == pytest.approx(1234.5)      # thousands dot, decimal comma
    assert q["T5_na"].iloc[-1] and np.isnan(q["T5"].iloc[-1])
    cest = q[q["T5"] == 4.0]["utc"].iloc[0]
    cet = q[q["T5"] == 8.0]["utc"].iloc[0]
    assert cet - cest == pd.Timedelta(hours=1)           # same wall clock, one hour apart


def test_hourly_file_is_consistent():
    c = curtailment_mw(2025)
    assert len(c) == 8760 and (c[["T5", "T6"]] >= 0).all().all()
    assert set(c["flag"]) == {"ok"}
    c26 = curtailment_mw(2026)
    assert len(c26) == 8760
    assert (c26["flag"] == "not_observed").sum() == 936 and "na_filled" in set(c26["flag"])
    assert c26.loc[c26["flag"] == "not_observed", ["T5", "T6"]].to_numpy().sum() == 0


def test_hourly_values_match_operator_totals():
    # operator file: 2025 T5 total 151,849 MWh, T6 97,366 MWh (sum of quarter-hours / 4)
    c = curtailment_mw(2025)
    assert c["T5"].sum() == pytest.approx(151849, abs=2)
    assert c["T6"].sum() == pytest.approx(97366, abs=2)


@pytest.mark.parametrize("year,holidays_sundays", [(2025, 62), (2026, 62)])
def test_calendar(year, holidays_sundays):
    cal = calendar(year)
    assert len(cal) == 8760 and cal["hour_of_year"].iloc[-1] == 8760
    days = cal.groupby("date_local")["day_type"].first()
    assert (days == "sunday_holiday").sum() == holidays_sundays
    assert cal["ts_local"].iloc[0].startswith(f"{year}-01-01T00:00")


# --------------------------------------------------------------- mapping
def test_pool_mapping_classes_and_bands(pool):
    maps, meta = map_pool(pool)
    assert [m.size_class for m in maps] == ["Schwimmer", "Kurs/Lehr", "Kleinkind"]
    assert all(m.environment == "indoor" for m in maps)
    assert maps[0].t_min == 28 and maps[0].t_max == 30        # setpoint + allowed change


def test_open_air_and_outdoor_basin_environment():
    inp = PoolInputs(pool_type="open_air", basins=[Basin("lap", 50, 20, 2, 2, 24), Basin("leisure", 15, 10, 1, 1, 24)])
    maps, _ = map_pool(inp)
    assert all(m.environment == "outdoor" for m in maps) and maps[1].size_class == "Wellen/Natur"
    comb = PoolInputs(pool_type="combined", basins=[Basin("lap", 25, 12.5, 2, 2, 28), Basin("outdoor", 50, 20, 2, 2, 24)])
    assert [m.environment for m in map_pool(comb)[0]] == ["indoor", "outdoor"]


def test_basin_without_geometry_is_skipped_and_empty_pool_raises():
    inp = PoolInputs(basins=[Basin("lap", None, None, None, None, 28), Basin("lap", 25, 12.5, 2, 2, 28)])
    assert len(map_pool(inp)[0]) == 1
    with pytest.raises(SplashInputError):
        map_pool(PoolInputs(basins=[Basin("lap")]))


# ------------------------------------------------------------ charging rule
def test_all_years_and_sizes_present(run_t5):
    assert set(run_t5.results) == {(y, float(x)) for y in YEARS for x in SIZES}
    assert set(ALL_KEYS) == {flex_key(y, x) for y in YEARS for x in SIZES}
    assert parse_key("2026_300") == (2026, 3.0)


def test_heater_size_is_share_of_design_load(run_t5):
    for (_y, x), r in run_t5.results.items():
        assert r.q_rated_kw == pytest.approx(x * run_t5.design_kw)
    assert run_t5.design_kw == pytest.approx(run_t5.design_basins_kw + run_t5.design_hall_kw + run_t5.design_dhw_kw, rel=1e-6)


def test_model_balances_close(run_t5):
    for r in run_t5.results.values():
        assert r.max_residual < 1e-3
        assert r.unmet_mwh_th == pytest.approx(0, abs=1e-6)


def test_absorption_grows_with_size_but_saturates(run_t5):
    for y in YEARS:
        a = [run_t5.get(y, x).absorbed_mwh_el for x in SIZES]
        assert a[0] < a[1] <= a[2] + 1e-9
        assert (a[2] - a[1]) < (a[1] - a[0])                  # diminishing returns


def test_physical_limits(run_t5):
    for r in run_t5.results.values():
        assert r.displaced_mwh_th <= r.baseline_conv_mwh_th + 1e-9
        assert r.absorbed_mwh_el <= r.zone_available_mwh
        assert r.peak_kw <= r.el_capacity_kw + 1e-6
        assert (r.hourly_el_kw[r.hourly_available_kw <= 0] == 0).all()     # add-on: curtailed power only
        assert r.absorbed_mwh_el * 0.99 >= r.p2h_heat_mwh * 0.99 - 1e-9
        assert r.hourly_soc_kwh.max() <= run_t5.storage_kwh + 1e-6


def test_window_lengths(run_t5):
    assert run_t5.get(2025, 1).window_hours == 8760
    assert run_t5.get(2026, 1).window_hours == 326 * 24
    assert not run_t5.get(2026, 1).full_year


def test_wider_band_absorbs_more(pool):
    a = run_splash(pool, "T5", band_factor=1.0, sizes=(2.0,), years=(2025,)).get(2025, 2.0)
    b = run_splash(pool, "T5", band_factor=2.0, sizes=(2.0,), years=(2025,)).get(2025, 2.0)
    assert b.absorbed_mwh_el > a.absorbed_mwh_el


def test_zone_share_limits_intake(pool):
    full = run_splash(pool, "T5", sizes=(2.0,), years=(2025,)).get(2025, 2.0)
    part = run_splash(pool, "T5", share=1e-6, sizes=(2.0,), years=(2025,)).get(2025, 2.0)
    assert part.absorbed_mwh_el < full.absorbed_mwh_el
    assert part.absorbed_mwh_el <= part.zone_available_mwh + 1e-9


def test_zones_differ(pool):
    t5 = run_splash(pool, "T5", sizes=(2.0,), years=(2025,)).get(2025, 2.0)
    t6 = run_splash(pool, "T6", sizes=(2.0,), years=(2025,)).get(2025, 2.0)
    assert t5.zone_available_mwh != t6.zone_available_mwh
    with pytest.raises(SplashInputError):
        run_splash(pool, "T1")


def test_ventilation_answer_keeps_splash_hall_archetype(pool):
    """From 1.4.2 the ventilation answer does not change the hall: heat recovery stays at the SPLASH archetype value."""
    import dataclasses

    no_hr = dataclasses.replace(pool, heat_recovery=False)
    a = run_splash(pool, "T5", sizes=(1.0,), years=(2025,))
    b = run_splash(no_hr, "T5", sizes=(1.0,), years=(2025,))
    assert b.design_hall_kw == pytest.approx(a.design_hall_kw)
    assert b.model_demand_mwh[2025] == pytest.approx(a.model_demand_mwh[2025])


def test_open_air_pool_only_runs_in_season():
    inp = PoolInputs(pool_type="open_air", operating_weeks=21, allowed_change_k=2.0,
                     basins=[Basin("lap", 50, 20, 2, 2, 24), Basin("children", 10, 8, 0.4, 0.4, 26)])
    r = run_splash(inp, "T5", sizes=(2.0,), years=(2025,)).get(2025, 2.0)
    month = calendar(2025)["month"].to_numpy()
    assert r.hourly_demand_kw[(month < 5) | (month > 9)].sum() == pytest.approx(0, abs=1e-6)
    assert r.hourly_el_kw[(month < 5) | (month > 9)].sum() == 0


# ---------------------------------------------------------- full pipeline
def test_pipeline_flex_outcomes(answers, params):
    res = run(answers, params)
    assert res.status == "ok"
    keys = set(res.central.flex)
    assert keys == set(ALL_KEYS)
    for case in ("pessimistic", "central", "optimistic"):
        for k in ALL_KEYS:
            assert res.cases[case].flex[k].econ.npv_eur is not None
    for k in ALL_KEYS:
        assert set(res.tornado["flex"]) == set(ALL_KEYS)
        assert res.sensitivity_band2[k]["absorbed_kwh"] >= res.central.flex[k].res.absorbed_kwh_el - 1e-6
    f = res.central.flex["2025_200"]
    assert f.investment > res.central.flex["2025_100"].investment
    assert f.res.fuel_saved_kwh and sum(f.res.fuel_saved_kwh.values()) <= res.central.baseline.e_fuel_total


def test_pipeline_zone_option(answers, params):
    a = run(answers, params, Options(zone="T5"), with_tornado=False)
    b = run(answers, params, Options(zone="T6"), with_tornado=False)
    assert a.context.zone == "T5" and b.context.zone == "T6"
    assert a.central.flex["2025_200"].res.zone_available_kwh != b.central.flex["2025_200"].res.zone_available_kwh


def test_fuel_saving_capped_by_reported_heat(answers, params):
    res = run(answers, params, with_tornado=False)
    for fo in res.central.flex.values():
        assert fo.res.coverage <= 1.0
        assert sum(fo.res.fuel_saved_kwh.values()) <= res.central.baseline.e_fuel_total + 1e-6


# ------------------------------------------------------------ season and hours
def _season_inp(**kw):
    return PoolInputs(pool_type=kw.pop("pool_type", "open_air"), allowed_change_k=2.0, **kw)


def test_season_dates_set_model_months():
    from splash_calc.splash_engine import _season

    inp = _season_inp(season_year_round=False, season_from=(1, 5), season_to=(30, 9))
    assert _season(inp, "open_air") == (5, 9, "all")
    inp = _season_inp(season_year_round=False, season_from=(20, 5), season_to=(10, 9))
    assert _season(inp, "open_air")[:2] == (6, 8)          # mid-month rounding
    inp = _season_inp(season_year_round=False, season_from=(1, 10), season_to=(30, 4))
    assert _season(inp, "indoor")[:2] == (10, 4)          # over the new year
    assert _season(_season_inp(season_year_round=True), "open_air") == (1, 12, "all")
    assert _season(_season_inp(season_year_round=False, season_from=(3, 6), season_to=(12, 6)), "open_air")[:2] == (6, 6)
    assert _season(inp, "combined")[2] == "outdoor_basins"


def test_combined_pool_outdoor_window():
    from splash_calc.splash_engine import _season
    """Combined pool: the outdoor window sets the months. Without an answer the default is May to September, not all year."""
    default = _season_inp(season_year_round=True)                         # the hall answer must not open the outdoor basins all year
    assert _season(default, "combined")[:2] == (5, 9)
    own = _season_inp(outdoor_year_round=False, outdoor_from=(1, 6), outdoor_to=(31, 8))
    assert _season(own, "combined")[:2] == (6, 8)
    assert _season(_season_inp(outdoor_year_round=True), "combined")[:2] == (1, 12)
    assert _season(_season_inp(season_year_round=False, season_from=(1, 5), season_to=(30, 9)), "indoor")[:2] == (5, 9)


def test_outdoor_window_is_parsed(params):
    from splash_calc.inputs import from_answers

    inp = from_answers({"q4_season_outdoor": {"year_round": False, "from": [15, 5], "to": [15, 9]}}, params).inputs
    assert inp.outdoor_from == (15, 5) and inp.outdoor_to == (15, 9)


def test_questionnaire_operation_is_parsed(params):
    from splash_calc.inputs import from_answers

    a = {"q4_season": {"year_round": False, "from": [1, 5], "to": [30, 9]},
         "q4_days": ["mon", "tue", "wed", "thu", "fri", "sat"],
         "q4_hours": {"weekday": ["07:00", "21:00"], "weekend": ["09:00", "17:00"]}}
    inp = from_answers(a, params).inputs
    assert inp.season_from == (1, 5) and inp.season_to == (30, 9)
    assert inp.operating_weeks == pytest.approx(21.9, abs=0.1)
    assert inp.hours_per_week == pytest.approx(5 * 14 + 8)
    bad = from_answers({"q4_hours": {"weekday": ["21:00", "07:00"]}}, params)
    assert bad.inputs.hours_weekday is None and any(w["code"] == "hours_invalid" for w in bad.warnings)


def test_combined_pool_basin_environment(params):
    """Combined pool: the location column of each basin sets indoor or outdoor. Other pool types ignore it."""
    from splash_calc.inputs import from_answers
    from splash_calc.splash_engine import map_pool

    rows = [{"type": "lap", "length_m": 25, "width_m": 12.5, "depth_min_m": 1.8, "depth_max_m": 1.8, "setpoint_c": 27, "environment": "indoor"},
            {"type": "lap", "length_m": 50, "width_m": 20, "depth_min_m": 2.0, "depth_max_m": 2.0, "setpoint_c": 25, "environment": "outdoor"}]
    res = from_answers({"q1_pool_type": "combined", "q3_basins": rows}, params)
    maps, _ = map_pool(res.inputs)
    assert [m.environment for m in maps] == ["indoor", "outdoor"]
    assert not any(w["code"] == "combined_no_outdoor" for w in res.warnings)
    indoor_only = from_answers({"q1_pool_type": "combined", "q3_basins": [dict(rows[0])]}, params)
    assert any(w["code"] == "combined_no_outdoor" for w in indoor_only.warnings)
    plain = from_answers({"q1_pool_type": "indoor", "q3_basins": rows}, params)
    assert [m.environment for m in map_pool(plain.inputs)[0]] == ["indoor", "indoor"]
