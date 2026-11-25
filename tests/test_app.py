import copy
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from splash_app.backend import get_store
from splash_app.demo import DEMO_ANSWERS

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def _app():
    return AppTest.from_file(APP, default_timeout=90)


def _no_errors(at):
    assert not at.exception, [x.value for x in at.exception]


def _btn(at, key):
    return next(b for b in at.button if b.key == key)


def test_welcome_page_german_default():
    at = _app().run()
    _no_errors(at)
    assert at.session_state["step"] == 0
    assert _btn(at, "start_btn").disabled  # consent missing


def test_language_toggle():
    at = _app().run()
    _btn(at, "lang_btn").click()
    at.run()
    _no_errors(at)
    assert at.session_state["lang"] == "en"
    assert any("Let's start" in b.label for b in at.button)


def test_consent_enables_start_and_moves_on():
    at = _app().run()
    at.checkbox(key="w_q0_consent").check()
    at.run()
    assert not _btn(at, "start_btn").disabled
    _btn(at, "start_btn").click()
    at.run()
    _no_errors(at)
    assert at.session_state["step"] == 1


def test_required_questions_block_next():
    at = _app().run()
    at.session_state["step"] = 1
    at.run()
    _btn(at, "next_s1").click()
    at.run()
    _no_errors(at)
    assert at.session_state["step"] == 1
    assert at.session_state["_missing"]


def test_demo_results_render_in_both_languages():
    at = _app().run()
    _btn(at, "demo_btn").click()
    at.run()
    _no_errors(at)
    assert at.session_state["step"] == 4 and at.session_state["is_demo"]
    assert len(at.tabs) == 11  # seven result tabs and four views of the heater detail
    at.session_state["lang"] = "en"
    at.run()
    _no_errors(at)


def test_demo_is_not_saved():
    store = get_store()
    before = len(store.read_table("submissions"))
    at = _app().run()
    _btn(at, "demo_btn").click()
    at.run()
    _btn(at, "to_followup_btn").click()
    at.run()
    assert len(store.read_table("submissions")) == before


def test_full_flow_saves_and_resumes():
    store = get_store()
    at = _app().run()
    at.session_state["answers"] = copy.deepcopy(DEMO_ANSWERS)
    at.session_state["step"] = 3
    at.run()
    _no_errors(at)
    _btn(at, "next_s3").click()
    at.run()
    _no_errors(at)
    assert at.session_state["step"] == 4
    sid = at.session_state["submission_id"]
    assert store.load(sid)["stage"] == "core"

    _btn(at, "to_followup_btn").click()
    at.run()
    _no_errors(at)
    assert at.session_state["step"] == 6
    assert store.load(sid)["stage"] == "results"
    assert any(r["kpi"] == "hp_npv_cen" for r in store.read_table("results") if r["submission_id"] == sid)

    _btn(at, "finish_btn").click()  # required interview answer missing
    at.run()
    assert not at.session_state["done"]
    at.radio(key="w_q14_interview").set_value("yes")
    at.text_input(key="w_q14_contact_name").set_value("Test Person")
    at.text_input(key="w_q14_contact_email").set_value("test@example.org")
    at.checkbox(key="w_q14_consent").check()
    at.run()
    _btn(at, "finish_btn").click()
    at.run()
    _no_errors(at)
    assert at.session_state["done"]
    assert store.load(sid)["stage"] == "final"
    contacts = [r for r in store.read_table("contacts") if r["submission_id"] == sid]
    assert len(contacts) == 1 and contacts[0]["contact"] == "test@example.org"
    stored = [r for r in store.read_table("answers") if r["submission_id"] == sid]
    assert not any("test@example.org" in r["value"] for r in stored)

    # resume with the code in a fresh session
    at2 = _app().run()
    at2.text_input(key="w_resume_code").set_value(sid.lower())
    at2.run()
    _btn(at2, "resume_btn").click()
    at2.run()
    _no_errors(at2)
    assert at2.session_state["step"] == 4
    assert at2.session_state["answers"]["q1_name"] == DEMO_ANSWERS["q1_name"]


def test_open_air_and_empty_basins_do_not_crash():
    for patch in ({"q1_pool_type": "open_air"}, {"q3_basins": []}):
        at = _app().run()
        a = copy.deepcopy(DEMO_ANSWERS)
        a.update(patch)
        at.session_state["answers"] = a
        at.session_state["is_demo"] = True
        at.session_state["step"] = 4
        at.run()
        _no_errors(at)


def test_admin_requires_password():
    at = AppTest.from_file(APP, default_timeout=60)
    at.query_params["admin"] = "1"
    at.run()
    _no_errors(at)
    assert not at.dataframe  # nothing shown without a password


def test_pdf_builds_in_both_languages(answers, params):
    from splash_app.report import build_pdf
    from splash_calc import run

    res = run(answers, params, with_tornado=False)
    for lg in ("de", "en"):
        pdf = build_pdf(res, params, answers, lg)
        assert pdf[:5] == b"%PDF-" and len(pdf) > 2000


@pytest.mark.parametrize("lg", ["de", "en"])
def test_texts_have_both_languages(lg):
    from splash_app.i18n import TEXTS

    assert all(v.get(lg) for v in TEXTS.values())


def _render_step(at, step):
    at.session_state["step"] = step
    at.run()
    _no_errors(at)


def test_every_step_renders_and_keeps_demo_answers():
    at = _app().run()
    at.session_state["answers"] = copy.deepcopy(DEMO_ANSWERS)
    at.session_state["is_demo"] = True
    for step in (1, 2, 3, 5, 6, 4):
        _render_step(at, step)
    a = at.session_state["answers"]
    assert len(a["q3_basins"]) == 3 and a["q3_basins"][0]["length_m"] == 25.0
    assert a["q8_consumption"]["gas"]["value"] == 640000.0
    assert a["q11_change"] == "1" and a["q11_hold"] == "8" and a["q10_willing"] == 3
    assert a["q7_sources"] == ["gas"] and a["q1_postcode"] == "24937"


def test_basin_edits_survive_navigation():
    at = _app().run()
    at.session_state["answers"] = copy.deepcopy(DEMO_ANSWERS)
    _render_step(at, 1)
    assert len(at.session_state["_basin_init"]) == 3
    # an edit is stored in answers; leaving and returning must show it
    at.session_state["answers"]["q3_basins"] = at.session_state["answers"]["q3_basins"][:2]
    _render_step(at, 2)
    _render_step(at, 1)
    assert len(at.session_state["_basin_init"]) == 2


def test_german_and_english_on_every_step():
    at = _app().run()
    at.session_state["answers"] = copy.deepcopy(DEMO_ANSWERS)
    at.session_state["is_demo"] = True
    for lg in ("en", "de"):
        at.session_state["lang"] = lg
        for step in (0, 1, 2, 3, 4, 5, 6):
            _render_step(at, step)


def test_operation_widgets_store_season_days_hours():
    at = _app()
    at.session_state["lang"] = "en"
    at.session_state["step"] = 2
    at.run()
    _no_errors(at)
    step = next(q["step"] for q in __import__("splash_app.i18n", fromlist=["x"]).load_questions()["questions"] if q["id"] == "q4_season")
    at.session_state["step"] = step
    at.run()
    _no_errors(at)
    at.radio(key="w_q4_season_mode").set_value("season")
    at.run()
    _no_errors(at)
    at.selectbox(key="w_q4_season_from_m").select(5)
    at.selectbox(key="w_q4_season_to_m").select(9)
    at.checkbox(key="w_q4_days_mon").check()
    at.checkbox(key="w_q4_days_sat").check()
    at.run()
    _no_errors(at)
    ans = at.session_state["answers"]
    assert ans["q4_season"]["from"][1] == 5 and ans["q4_season"]["to"][1] == 9
    assert ans["q4_days"] == ["mon", "sat"]


def test_combined_pool_shows_basin_location_and_outdoor_window():
    import copy

    at = _app().run()
    ans = copy.deepcopy(DEMO_ANSWERS)
    ans["q1_pool_type"] = "combined"
    ans["q3_basins"][0]["environment"] = "outdoor"
    at.session_state["answers"] = ans
    at.session_state["is_demo"] = True
    for lg in ("en", "de"):
        at.session_state["lang"] = lg
        for step in (0, 1):
            _render_step(at, step)
        step = next(q["step"] for q in __import__("splash_app.i18n", fromlist=["x"]).load_questions()["questions"] if q["id"] == "q4_season_outdoor")
        at.session_state["step"] = step
        at.run()
        _no_errors(at)
        assert any(r.key == "w_q4_season_outdoor_mode" for r in at.radio)
        assert any("outdoor" in (i.value or "").lower() or "außen" in (i.value or "").lower() for i in at.info)
