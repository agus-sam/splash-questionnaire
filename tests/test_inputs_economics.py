"""Demand calibration, economic inputs, storage robustness and the results page."""
import copy
import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from splash_app.demo import DEMO_ANSWERS
from splash_app.storage import MemoryStore, SqliteStore, StorageError, _retry, build_rows, export_safe, make_record
from splash_calc import Params, run
from splash_calc.economics import economics

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "app.py")


# ------------------------------------------------------------ economics inputs
def test_apply_input_keeps_range_for_uncertain_parameters():
    p = Params.load().apply_input({"wacc": 0.05, "lifetime_years": 25})
    assert p.central("wacc") == 0.05
    pess, opt = p.at_case("pessimistic").get("wacc"), p.at_case("optimistic").get("wacc")
    d = Params.load()
    assert pess - 0.05 == pytest.approx(d.at_case("pessimistic").get("wacc") - d.central("wacc"))
    assert opt < 0.05 < pess
    assert p.get("lifetime_years") == 25


def test_nominal_npv_matches_real_formulation():
    """Nominal cash flows at nominal WACC equal real cash flows at the real rate (Fisher)."""
    p = Params.load().at_case("central").with_overrides(wacc=0.07, inflation=0.02)
    e = economics(100_000, 0, {"gas": 100_000.0}, {"gas": 0.1}, 20_000, 0.2, 1000, p)
    r_real = 1.07 / 1.02 - 1
    n = int(p.get("lifetime_years"))
    gf, ge = float(p.get("price_escalation_fuel")), float(p.get("price_escalation_electricity"))
    real = -100_000 + sum((10_000 * (1 + gf) ** t - 4_000 * (1 + ge) ** t - 1000) / (1 + r_real) ** t for t in range(1, n + 1))
    assert e.npv_eur == pytest.approx(real, rel=1e-9)


def test_irr_and_discounted_payback():
    p = Params.load().at_case("central")
    e = economics(50_000, 0, {"gas": 100_000.0}, {"gas": 0.1}, 0.0, 0.2, 0, p)
    assert e.irr is not None and e.irr > p.get("wacc")  # positive NPV means IRR above WACC
    assert e.npv_eur > 0
    assert e.discounted_payback_years is not None and e.discounted_payback_years > e.payback_years


def test_higher_wacc_lowers_npv(params):
    lo = economics(50_000, 0, {"gas": 100_000.0}, {"gas": 0.1}, 0.0, 0.2, 0, params.with_overrides(wacc=0.03))
    hi = economics(50_000, 0, {"gas": 100_000.0}, {"gas": 0.1}, 0.0, 0.2, 0, params.with_overrides(wacc=0.10))
    assert lo.npv_eur > hi.npv_eur


# ------------------------------------------------------------------ calibration
def test_physics_is_default_and_calibration_is_optional(answers, params):
    from splash_calc import Options

    raw = run(answers, params, Options(), False, "en").context.splash
    assert not raw.calibration["applied"] and raw.calibration["factor"] == 1.0
    cal = run(answers, params, Options(calibrate=True), False, "en").context.splash
    assert cal.calibration["applied"]
    target = cal.calibration["target_mwh"]
    b, h = cal.demand_split_mwh[2025]
    assert b + h == pytest.approx(target, rel=1e-6)          # basins and hall are calibrated, hot water follows the visitors
    assert cal.model_demand_mwh[2025] == pytest.approx(target + cal.demand_dhw_mwh[2025], rel=1e-6)
    assert cal.model_demand_mwh[2025] != pytest.approx(raw.model_demand_mwh[2025], rel=0.01)


def test_default_zone_is_t6():
    from splash_calc import climate

    assert climate.DEFAULT_ZONE == "T6"


# ---------------------------------------------------------------------- storage
def test_phone_number_is_stored_exactly():
    rows = build_rows(make_record("AAAA-BBBB", "final", {"q1_name": "-Test"}, "de", None, {"name": "A", "contact": "+49 170 1234567",
                                                                                             "method": "email", "consent": True}))
    assert rows["contacts"][0][3] == "+49 170 1234567"
    assert rows["answers"][0][4] == "-Test"


def test_export_safe_only_for_formula_starts():
    assert export_safe("+49 170 1") == "'+49 170 1"
    assert export_safe("=SUM(A1)") == "'=SUM(A1)"
    assert export_safe("Müller") == "Müller" and export_safe(5) == 5


def test_sqlite_roundtrip_keeps_text(tmp_path):
    s = SqliteStore(tmp_path / "t.db")
    s.save(make_record("AAAA-BBBB", "final", {"q1_name": "-Test Bad"}, "de", None,
                       {"name": "x", "contact": "+4915123456789", "consent": True}))
    assert s.read_table("contacts")[0]["contact"] == "+4915123456789"
    assert s.read_table("answers")[0]["value"] == "-Test Bad"


def test_retry_backs_off_on_quota(monkeypatch):
    import time

    monkeypatch.setattr(time, "sleep", lambda s: None)

    class Resp:
        status_code = 429

    class Quota(Exception):
        response = Resp()

    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise Quota()
        return "ok"

    assert _retry(flaky) == "ok" and calls["n"] == 3
    with pytest.raises(StorageError):
        _retry(lambda: (_ for _ in ()).throw(Quota()), attempts=2)


def test_no_silent_fallback_when_sheets_configured(monkeypatch):
    from splash_app import backend

    monkeypatch.setattr(backend, "_secrets_section", lambda n: {"backend": "sheets"})  # incomplete on purpose
    with pytest.raises(ValueError):
        backend.get_store.__wrapped__()


# ---------------------------------------------------------------------- versions
def test_versions_agree_with_changelog_and_pyproject():
    import splash_calc

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    latest = re.search(r"^## (\d+\.\d+\.\d+)", changelog, re.M).group(1)
    pyproject = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
    assert splash_calc.__version__ == latest == pyproject


def test_vendor_manifest_matches_files():
    import hashlib

    manifest = (ROOT / "vendor" / "MANIFEST.sha256").read_text().splitlines()
    assert manifest
    for line in manifest:
        digest, rel = line.split("  ", 1)
        assert hashlib.sha256((ROOT / "vendor" / rel).read_bytes()).hexdigest() == digest, rel


# --------------------------------------------------------------------------- app
def test_logged_in_admin_export_does_not_crash(monkeypatch):
    from splash_app import admin
    from splash_app.backend import get_store

    get_store().save(make_record("ADMN-TEST", "final", {"q1_name": "+Pool"}, "de", {"zone": "T6"},
                                 {"name": "N", "contact": "+49 1", "consent": True}))
    monkeypatch.setattr(admin, "admin_password", lambda: "secret")
    at = AppTest.from_file(APP, default_timeout=60)
    at.query_params["admin"] = "1"
    at.run()
    at.text_input[0].set_value("secret").run()
    assert not at.exception, [x.value for x in at.exception]
    assert any(d for d in at.dataframe)
    assert any(b.label.startswith("Excel export") for b in at.get("download_button"))


def test_admin_locks_after_failed_attempts(monkeypatch):
    from splash_app import admin

    monkeypatch.setattr(admin, "admin_password", lambda: "secret")
    at = AppTest.from_file(APP, default_timeout=60)
    at.query_params["admin"] = "1"
    at.run()
    for _ in range(admin.MAX_ATTEMPTS + 1):
        at.text_input[0].set_value("wrong").run()
    assert not at.dataframe


def test_band_slider_default_follows_question_11():
    a = copy.deepcopy(DEMO_ANSWERS)
    a["q11_change"] = "1"
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["answers"], at.session_state["is_demo"], at.session_state["step"] = a, True, 4
    at.run()
    assert next(s for s in at.slider if s.key.startswith("sl_band_")).value == 1.0
    a2 = copy.deepcopy(a)
    a2["q11_change"] = "4"
    at.session_state["answers"] = a2
    at.run()
    sl = next(s for s in at.slider if s.key.startswith("sl_band_"))
    assert sl.value == 4.0 and at.session_state["opts"]["band_k"] in (None, 4.0)


def test_results_page_has_economic_inputs_and_changes_result():
    a = copy.deepcopy(DEMO_ANSWERS)
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["answers"], at.session_state["is_demo"], at.session_state["step"] = a, True, 4
    at.run()
    keys = {n.key for n in at.number_input}
    assert {"ec_wacc", "ec_inflation", "ec_lifetime_years", "ec_price_electricity"} <= keys
    before = at.session_state["_last_result"].central.hp.econ.npv_eur
    next(n for n in at.number_input if n.key == "ec_wacc").set_value(0.12).run()
    assert at.session_state["_last_result"].central.hp.econ.npv_eur == before  # not applied yet
    next(b for b in at.button if b.key == "recalc_btn").click().run()
    after = at.session_state["_last_result"].central.hp.econ.npv_eur
    assert after < before


def test_resume_code_shown_after_first_save():
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["step"] = 2
    at.session_state["saved_stage"] = "step1"
    at.run()
    assert any(at.session_state["submission_id"] in c.value for c in at.caption)


def test_stored_results_carry_assumptions(answers, params):
    from splash_app.summary import flat_results

    res = run(answers, params, None, False, "en")
    flat = flat_results(res, {"econ": {"wacc": 0.05}, "fuel_factor": 1.2, "el_factor": 1.0})
    assert flat["whatif_active"] is True and flat["opt_econ_wacc"] == 0.05
    assert flat_results(res, None)["whatif_active"] is False
    assert MemoryStore().name == "memory"


def test_calibration_toggle_on_results_page_changes_result():
    a = copy.deepcopy(DEMO_ANSWERS)
    at = AppTest.from_file(APP, default_timeout=180)
    at.session_state["answers"], at.session_state["is_demo"], at.session_state["step"] = a, True, 4
    at.run()
    assert not at.exception, [x.value for x in at.exception]
    d0 = at.session_state["_last_result"].context.splash.model_demand_mwh[2025]
    next(t for t in at.toggle if t.key == "sl_calibrate").set_value(True).run()
    next(b for b in at.button if b.key == "recalc_btn").click().run()
    assert not at.exception, [x.value for x in at.exception]
    d1 = at.session_state["_last_result"].context.splash.model_demand_mwh[2025]
    assert d1 != pytest.approx(d0, rel=0.01)


def test_grid_connection_note(answers, params):
    from splash_calc import Options

    answers["r_grid_kw"] = 5
    res = run(answers, params, Options(), False, "en")
    assert res.context.inp.grid_kw == 5
    assert res.central.flex["2025_100"].res.capacity_kw_el > 5


def test_every_what_if_input_changes_results_after_recalculate():
    """Each control must reach the calculation once 'Recalculate' is pressed (user report: value sometimes unchanged)."""
    a = copy.deepcopy(DEMO_ANSWERS)
    at = AppTest.from_file(APP, default_timeout=240)
    at.session_state["answers"], at.session_state["is_demo"], at.session_state["step"] = a, True, 4
    at.run()
    base = at.session_state["_last_result"].central
    flex0 = base.flex["2025_200"].econ.npv_eur
    hp0 = base.hp.econ.npv_eur
    changes = [("sl_curt", 60.0, "flex"), ("sl_el", 1.4, "hp"), ("sl_fuel", 1.4, "hp"), ("ec_price_electricity", 0.40, "hp"),
               ("ec_lifetime_years", 12, "hp"), ("sl_hp", 120.0, "hp")]
    for key, val, kind in changes:
        wid = next(w for w in list(at.number_input) + list(at.slider) if w.key == key)
        wid.set_value(val).run()
        next(b for b in at.button if b.key == "recalc_btn").click().run()
        c = at.session_state["_last_result"].central
        now = c.flex["2025_200"].econ.npv_eur if kind == "flex" else c.hp.econ.npv_eur
        ref = flex0 if kind == "flex" else hp0
        assert now != pytest.approx(ref, rel=1e-6), key
        flex0, hp0 = c.flex["2025_200"].econ.npv_eur, c.hp.econ.npv_eur
