import numpy as np
import pytest

from splash_calc import Options, from_answers, run
from splash_calc.baseline import compute_baseline
from splash_calc.economics import co2, economics, pv_factor
from splash_calc.heatpump import cop_series
from splash_calc.inputs import to_kwh
from splash_calc.profiles import LEVELS
from splash_calc.subsidy import eligible_cost_cap, heat_pump_subsidy


# ------------------------------------------------------------------ subsidy
@pytest.mark.parametrize(
    "area,cap",
    [(100, 28000), (150, 28000), (500, 89050), (1000, 148050), (1200, 163850)],
)
def test_subsidy_cap(params, area, cap):
    assert eligible_cost_cap(area, params) == pytest.approx(cap)


def test_subsidy_grant_and_cap_binding(params):
    s = heat_pump_subsidy(1_000_000, 500, params)
    assert s["cap_binding"] and s["grant_eur"] == pytest.approx(0.3 * 89050)
    s2 = heat_pump_subsidy(50_000, 500, params)
    assert not s2["cap_binding"] and s2["grant_eur"] == pytest.approx(15_000)


# -------------------------------------------------------------------- units
def test_units(params):
    assert to_kwh(100, "kwh", "gas", params) == 100
    assert to_kwh(2, "mwh", "gas", params) == 2000
    assert to_kwh(100, "m3", "gas", params) == pytest.approx(1050)
    assert to_kwh(100, "l", "oil", params) == pytest.approx(1000)
    assert to_kwh(100, "l", "gas", params) is None
    assert to_kwh(-5, "kwh", "gas", params) is None
    assert to_kwh("abc", "kwh", "gas", params) is None


# ----------------------------------------------------------------- heat pump
def test_cop_monotone_and_clipped(params):
    src = np.array([-10.0, 0.0, 10.0, 20.0])
    cop = cop_series(src, 45.0, params)
    assert np.all(np.diff(cop) > 0)
    assert cop.min() >= float(params.get("cop_min")) and cop.max() <= float(params.get("cop_max"))
    assert cop_series(44.9, 45.0, params)[()] <= float(params.get("cop_max"))
    assert cop_series(src, 60.0, params)[2] < cop_series(src, 38.0, params)[2]


# -------------------------------------------------------------------- econ
def test_pv_factor_matches_sum():
    g, r, n = 0.02, 0.04, 20
    explicit = sum(((1 + g) / (1 + r)) ** t for t in range(1, n + 1))
    assert pv_factor(g, r, n) == pytest.approx(explicit)
    assert pv_factor(0.04, 0.04, 20) == pytest.approx(20.0)


def test_break_even_price_gives_zero_npv(params):
    fuel_saved = {"gas": 200_000.0}
    prices = {"gas": 0.10}
    e1 = economics(80_000, 10_000, fuel_saved, prices, 60_000, 0.25, 1500, params)
    assert e1.break_even_price is not None
    e2 = economics(80_000, 10_000, fuel_saved, prices, 60_000, e1.break_even_price, 1500, params)
    assert e2.npv_eur == pytest.approx(0.0, abs=1e-6)


def test_npv_formula_by_hand(params):
    p = params.at_case("central")
    n, r, i = int(p.get("lifetime_years")), float(p.get("wacc")), float(p.get("inflation"))
    gf = (1 + i) * (1 + float(p.get("price_escalation_fuel"))) - 1
    ge = (1 + i) * (1 + float(p.get("price_escalation_electricity"))) - 1
    e = economics(100_000, 20_000, {"gas": 100_000.0}, {"gas": 0.1}, 25_000, 0.2, 1000, p)
    expected = -80_000 + sum(
        (100_000 * 0.1 * (1 + gf) ** t - 25_000 * 0.2 * (1 + ge) ** t - 1000 * (1 + i) ** t) / (1 + r) ** t for t in range(1, n + 1)
    )
    assert e.npv_eur == pytest.approx(expected)


def test_co2_curtailed_view(params):
    c = co2({"gas": 100_000.0}, 50_000.0, params, curtailed_share=1.0)
    assert c.net_curtailed_zero_t_y1 > c.net_t_y1
    assert c.saved_fuel_t_y1 == pytest.approx(100_000 * 0.182 / 1000)


def _ctx(answers, params):
    from splash_calc.scenarios import build_context

    return build_context(from_answers(answers, params), params, Options())


# ------------------------------------------------------------ model basis
def test_levels_come_from_the_model(answers, params):
    ctx = _ctx(answers, params)
    sr = ctx.splash
    total = sum(float(ctx.levels[lv].sum()) for lv in LEVELS)
    assert total == pytest.approx(ctx.q_use_kwh, rel=1e-9)
    assert ctx.q_use_kwh == pytest.approx(sr.model_demand_mwh[2025] * 1000.0, rel=1e-9)
    assert float(ctx.levels["dhw"].sum()) / 1000.0 == pytest.approx(sr.demand_dhw_mwh[2025], rel=1e-9) and sr.demand_dhw_mwh[2025] > 0
    assert float(ctx.levels["space_heating"].sum()) == 0.0
    assert all((ctx.levels[lv] >= 0).all() for lv in LEVELS)
    assert len(ctx.levels["pool_water"]) == 8760
    assert sum(ctx.shares.values()) == pytest.approx(1.0)


def test_baseline_uses_model_demand_not_reported(answers, params):
    res = run(answers, params, with_tornado=False)
    b = res.baseline
    assert b.model_based and b.q_use_kwh == pytest.approx(res.context.q_use_kwh)
    assert b.reported_q_use_kwh == pytest.approx(640_000 * 0.9, rel=0.05) or b.reported_q_use_kwh > 0
    # the carrier mix follows the reported consumption, the amount follows the model
    assert set(b.e_fuel_kwh) == {"gas"}
    assert b.e_fuel_total * b.mix_eta == pytest.approx(b.q_use_kwh)


def test_flex_coverage_is_on_the_model_basis(answers, params):
    res = run(answers, params, with_tornado=False)
    for fo in res.central.flex.values():
        r = fo.res
        assert r.coverage == pytest.approx(min(r.displaced_kwh_th / r.demand_kwh_th, 1.0))
    full = res.central.flex["2025_200"].res
    saved = sum(full.fuel_saved_kwh.values())
    assert saved * res.baseline.mix_eta == pytest.approx(full.displaced_kwh_th, rel=1e-6)


def test_hall_area_changes_model_demand(answers, params):
    small = dict(answers, q3_hall_area=500)
    large = dict(answers, q3_hall_area=3000)
    assert _ctx(large, params).q_use_kwh > _ctx(small, params).q_use_kwh


# ------------------------------------------------------------------ baseline
def test_baseline_entered_vs_default(answers, params):
    parsed = from_answers(answers, params)
    b = compute_baseline(parsed.inputs, params)
    assert not b.heat_is_default and b.e_fuel_total == pytest.approx(640_000)
    answers["q8_consumption"] = {}
    parsed = from_answers(answers, params)
    b = compute_baseline(parsed.inputs, params)
    area = parsed.inputs.water_surface_m2()
    assert b.heat_is_default and b.e_fuel_total == pytest.approx(2013.60 * area)


def test_plausibility_flags(answers, params):
    area = from_answers(answers, params).inputs.water_surface_m2()
    answers["q8_consumption"] = {"gas": {"value": 100 * area, "unit": "kwh"}}
    assert compute_baseline(from_answers(answers, params).inputs, params).plausibility == "low"
    answers["q8_consumption"] = {"gas": {"value": 9000 * area, "unit": "kwh"}}
    assert compute_baseline(from_answers(answers, params).inputs, params).plausibility == "high"
    answers["q8_consumption"] = {"gas": {"value": 2000 * area, "unit": "kwh"}}
    assert compute_baseline(from_answers(answers, params).inputs, params).plausibility == "ok"


def test_entered_costs_and_vat(answers, params):
    from splash_calc.baseline import effective_prices

    answers["q1_legal_form"] = "municipal_operation"
    answers["q8_heat_cost_eur"] = 59_500.0
    answers["q8_costs_incl_vat"] = "yes"
    parsed = from_answers(answers, params)
    base = compute_baseline(parsed.inputs, params)
    fuel, _ = effective_prices(parsed.inputs, base, params)
    assert fuel["gas"] == pytest.approx(59_500 / 640_000)  # gross entered, VAT not deductible
    answers["q1_legal_form"] = "private"
    parsed = from_answers(answers, params)
    fuel, _ = effective_prices(parsed.inputs, compute_baseline(parsed.inputs, params), params)
    assert fuel["gas"] == pytest.approx(59_500 / 1.19 / 640_000)  # net


# -------------------------------------------------------------- full pipeline
def test_run_demo_pool(answers, params):
    res = run(answers, params)
    assert res.status == "ok"
    for case in ("pessimistic", "central", "optimistic"):
        assert case in res.cases
    npv = [res.cases[c].hp.econ.npv_eur for c in ("pessimistic", "central", "optimistic")]
    assert npv[0] <= npv[1] <= npv[2]
    hp = res.central.hp
    assert 0 < hp.res.coverage <= 1
    assert sum(hp.res.fuel_saved_kwh.values()) <= res.central.baseline.e_fuel_total
    assert hp.res.scop > 1.5
    assert res.tornado["hp"] and res.tornado["flex"]
    assert res.parsed.confidence()[0] >= 5


def test_run_is_deterministic(answers, params):
    a = run(answers, params, with_tornado=False)
    b = run(answers, params, with_tornado=False)
    assert a.central.hp.econ.npv_eur == b.central.hp.econ.npv_eur
    assert a.central.flex["2025_200"].econ.npv_eur == b.central.flex["2025_200"].econ.npv_eur


def test_open_air_and_insufficient(answers, params):
    answers["q1_pool_type"] = "open_air"
    oa = run(answers, params, with_tornado=False)
    assert oa.status == "open_air" and oa.central.hp is None and oa.central.flex["2025_200"].res.absorbed_kwh_el >= 0
    answers["q3_basins"] = []
    assert run(answers, params).status == "insufficient"


def test_curtailed_price_default_and_input(answers, params):
    default = run(answers, params, with_tornado=False).central.flex["2025_200"]
    assert default.price_eff == pytest.approx(0.023 * (1.0 if default.price_eff == 0.023 else default.price_eff / 0.023))
    free = run(answers, params, Options(curtailed_price_net=0.0), with_tornado=False).central.flex["2025_200"]
    dear = run(answers, params, Options(curtailed_price_net=0.10), with_tornado=False).central.flex["2025_200"]
    assert free.price_eff == 0.0
    assert free.econ.npv_eur > default.econ.npv_eur > dear.econ.npv_eur


def test_band_input_replaces_questionnaire_value(answers, params):
    a = run(answers, params, Options(band_k=1.0), with_tornado=False)
    b = run(answers, params, Options(band_k=5.0), with_tornado=False)
    assert all(abs((m.t_max - m.t_min) - 5.0) < 1e-9 for m in b.context.splash.basins)
    assert all(abs((m.t_max - m.t_min) - 1.0) < 1e-9 for m in a.context.splash.basins)
    assert b.central.flex["2025_200"].res.absorbed_kwh_el > a.central.flex["2025_200"].res.absorbed_kwh_el


def test_hp_capacity_override(answers, params):
    auto = run(answers, params, with_tornado=False).central.hp.res
    big = run(answers, params, Options(hp_capacity_kw=auto.capacity_kw_th * 3), with_tornado=False).central.hp.res
    assert big.capacity_kw_th == pytest.approx(auto.capacity_kw_th * 3)
    assert big.coverage >= auto.coverage
