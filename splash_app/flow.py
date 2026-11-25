"""Page flow: welcome, three question steps, results, refinement, follow-up."""
from __future__ import annotations

import copy
from datetime import date

import pandas as pd
import streamlit as st

from splash_calc import Params

from . import admin, live, results
from .backend import get_store
from .demo import DEMO_ANSWERS
from .form import missing_required, render_step
from .i18n import DATA_DIR, t
from .state import (
    answers,
    clear_widget_state,
    goto,
    init_state,
    lang,
    versions,
    visible_answers,
)
from .storage import make_record, normalise_code
from .summary import flat_results
from .theme import code_box, e, hero, inject_css, mini_hero, note, stepper, stretch

CONTACT_KEYS = ("q14_contact_name", "q14_contact_email", "q14_contact_method", "q14_consent", "q14_summary")
STEPPER_MAP = {1: 0, 2: 1, 3: 2, 4: 3, 5: 3, 6: 4}


# ------------------------------------------------------------------- helpers
def _stepper(lg: str, step: int) -> None:
    labels = [t_step("pool", lg), t_step("energy", lg), t_step("flex", lg), t_step("results", lg), t_step("followup", lg)]
    stepper(labels, STEPPER_MAP[step])


def t_step(key: str, lg: str) -> str:
    from .i18n import load_questions

    for v in load_questions()["steps"].values():
        if v["key"] == key:
            return v[f"title_{lg}"]
    return key


def _params_version() -> str:
    return Params.load().version


def save(stage: str, with_results: bool = False, with_contact: bool = False) -> bool:
    """Append a record. A failure never blocks the respondent."""
    ss = st.session_state
    if ss.get("is_demo"):
        return True
    ans = visible_answers(answers())
    contact: dict = {}
    if with_contact:
        contact = {"name": ans.get("q14_contact_name", ""), "contact": ans.get("q14_contact_email", ""),
                   "method": ans.get("q14_contact_method", ""), "consent": ans.get("q14_consent", False),
                   "summary": ans.get("q14_summary", False)}
        if not contact["consent"]:
            contact = {}
    stored = {k: v for k, v in ans.items() if k not in CONTACT_KEYS}
    res = flat_results(
        ss["_last_result"], ss.get("applied_opts") or ss.get("opts"), ss.get("_last_params"),
        {"technology": ss.get("tech", "flex"), "flex_year": ss.get("flex_year"), "flex_size": ss.get("flex_size")},
        ss.get("_last_items")) if with_results and ss.get("_last_result") is not None else None
    rec = make_record(ss["submission_id"], stage, stored, lang(), res, contact,
                      versions(_params_version()), ss.get("pool_token", ""))
    try:
        get_store().save(rec)
        ss["save_error"] = False
        ss["saved_stage"] = stage
        return True
    except Exception:
        ss["save_error"] = True
        return False


def _prefill_from_token() -> None:
    ss = st.session_state
    if ss.get("prefilled"):
        return
    ss["prefilled"] = True
    token = st.query_params.get("pool")
    path = DATA_DIR / "pool_prefill.csv"
    if not token or not path.exists():
        return
    df = pd.read_csv(path, dtype=str).fillna("")
    row = df[df["token"] == token]
    if row.empty:
        return
    r = row.iloc[0]
    exp = r.get("expires", "")
    if exp:
        try:
            if date.fromisoformat(exp) < date.today():
                return
        except ValueError:  # malformed date in the prefill file: treat the link as expired
            return
    ss["pool_token"] = token
    for col in df.columns:
        if col.startswith("q1_") and r[col]:
            answers()[col] = r[col]


def _nav(lg: str, back: int | None, nxt_label: str, on_next, key: str, extra: list | None = None) -> None:
    cols = st.columns([1, 1, 3] if back is not None else [1, 4])
    i = 0
    if back is not None:
        if cols[0].button(t("back", lg), key=f"back_{key}", **stretch()):
            goto(back)
            st.rerun()
        i = 1
    if cols[i].button(nxt_label, type="primary", key=f"next_{key}", **stretch()):
        on_next()


def _banners(lg: str) -> None:
    try:
        if get_store().is_test:
            note("info", t("test_mode", lg))
    except Exception:
        note("bad", t("store_unavailable", lg))
    if st.session_state.get("save_error"):
        note("warn", t("save_failed", lg))
    ss = st.session_state
    if ss.get("saved_stage") and not ss.get("is_demo") and ss.get("step", 0) > 0:
        st.caption(f"{t('code_line', lg)} **{ss['submission_id']}**")


# --------------------------------------------------------------------- pages
def welcome(lg: str) -> None:
    hero(t("app_title", lg), t("tagline", lg), t("hero_sub", lg),
         ["⏱ " + t("minutes", lg), "🔒 " + ("ohne externe Dienste" if lg == "de" else "no external services"),
          "📄 PDF"])
    _banners(lg)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f'<div class="sp-card"><h3>{e(t("welcome_what_title", lg))}</h3>{e(t("welcome_what", lg))}</div>',
                    unsafe_allow_html=True)
        st.markdown(f'<div class="sp-card"><h3>{e(t("welcome_honest_title", lg))}</h3>{e(t("welcome_honest", lg))}</div>',
                    unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div class="sp-card"><h3>{e(t("welcome_you_get_title", lg))}</h3>{e(t("welcome_you_get", lg))}</div>',
                    unsafe_allow_html=True)
        st.markdown(f'<div class="sp-card"><h3>{e(t("privacy_title", lg))}</h3>{e(t("privacy_text", lg))}</div>',
                    unsafe_allow_html=True)
    notice = DATA_DIR / "privacy_notice.md"
    if notice.exists():
        with st.expander(t("privacy_full", lg)):
            txt = notice.read_text(encoding="utf-8")
            parts = txt.split("<!--EN-->")
            st.markdown(parts[0] if lg == "de" or len(parts) == 1 else parts[1])
    st.caption(t("contact_info", lg))

    render_step(0)
    consent = bool(answers().get("q0_consent"))
    b1, b2, _ = st.columns([2, 2, 3])
    if b1.button(t("start", lg), type="primary", disabled=not consent, key="start_btn", **stretch()):
        goto(1)
        st.rerun()
    if b2.button("✨ " + t("demo_btn", lg), key="demo_btn", **stretch()):
        clear_widget_state()
        st.session_state["answers"] = copy.deepcopy(DEMO_ANSWERS)
        st.session_state["is_demo"] = True
        goto(4)
        st.rerun()
    st.caption(t("demo_note", lg))

    with st.expander(t("resume_title", lg)):
        code = st.text_input(t("resume_code", lg), key="w_resume_code")
        if st.button(t("resume_btn", lg), key="resume_btn") and code:
            try:
                rec = get_store().load(normalise_code(code))
            except Exception:
                rec = None
            if rec:
                clear_widget_state()
                st.session_state["answers"] = rec["answers"]
                st.session_state["submission_id"] = rec["submission_id"]
                st.session_state["is_demo"] = False
                goto({"step1": 2, "step2": 3}.get(rec["stage"], 4 if rec["stage"] in ("results", "final", "core") else 1))
                st.rerun()
            else:
                note("warn", t("resume_not_found", lg))


def _question_page(lg: str, step: int) -> None:
    mini_hero(t_step({1: "pool", 2: "energy", 3: "flex"}[step], lg), t("tagline", lg))
    _stepper(lg, step)
    _banners(lg)
    st.caption(t("required_hint", lg))
    render_step(step)
    {1: live.pool_feedback, 2: live.energy_feedback, 3: live.flex_feedback}[step](lg)

    def go_next() -> None:
        miss = missing_required(step)
        if miss:
            st.session_state["_missing"] = miss
            return
        st.session_state.pop("_missing", None)
        save("core" if step == 3 else f"step{step}")
        goto(step + 1)
        st.rerun()

    if st.session_state.get("_missing"):
        note("bad", t("required_missing", lg) + " " + "; ".join(st.session_state["_missing"]))
    label = t("show_results", lg) if step == 3 else t("next", lg)
    _nav(lg, step - 1, label, go_next, f"s{step}")


def _results_page(lg: str) -> None:
    results.render()
    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    if c1.button(t("back", lg), key="back_s4", **stretch()):
        goto(3)
        st.rerun()
    if c2.button(t("refine", lg), key="refine_btn", **stretch()):
        save("results", with_results=True)
        goto(5)
        st.rerun()
    if c3.button(t("to_followup", lg), type="primary", key="to_followup_btn", **stretch()):
        save("results", with_results=True)
        goto(6)
        st.rerun()


def _refine_page(lg: str) -> None:
    mini_hero(t("refine_title", lg), t("refine_intro", lg))
    render_step(5)
    c1, c2 = st.columns(2)
    if c1.button(t("show_results", lg), type="primary", key="refine_back", **stretch()):
        goto(4)
        st.rerun()
    if c2.button(t("to_followup", lg), key="refine_follow", **stretch()):
        save("results", with_results=True)
        goto(6)
        st.rerun()


def _followup_page(lg: str) -> None:
    mini_hero(t("followup_title", lg), "")
    _stepper(lg, 6)
    _banners(lg)
    render_step(6)

    def finish() -> None:
        miss = missing_required(6)
        if miss:
            st.session_state["_missing"] = miss
            return
        st.session_state.pop("_missing", None)
        if not save("final", with_results=True, with_contact=True):
            st.session_state["_save_block"] = True
            return
        st.session_state.pop("_save_block", None)
        st.session_state["done"] = True
        st.rerun()

    if st.session_state.get("_missing"):
        note("bad", t("required_missing", lg) + " " + "; ".join(st.session_state["_missing"]))
    if st.session_state.get("_save_block"):
        note("bad", t("final_not_saved", lg))
    c1, c2, _ = st.columns([1, 1, 3])
    if c1.button(t("back", lg), key="back_s6", **stretch()):
        goto(4)
        st.rerun()
    if c2.button(t("finish", lg), type="primary", key="finish_btn", **stretch()):
        finish()


def _done_page(lg: str) -> None:
    mini_hero(t("done_title", lg), "")
    st.markdown(t("done_text", lg))
    if st.session_state.get("is_demo"):
        note("info", t("demo_note", lg))
    else:
        st.markdown(f"**{t('your_code', lg)}**")
        code_box(st.session_state["submission_id"])
    if st.session_state.get("save_error"):
        note("warn", t("save_failed", lg))


def main() -> None:
    st.set_page_config(page_title="SPLASH Fragebogen und Simulation", page_icon="🏊", layout="centered",
                       initial_sidebar_state="collapsed")
    init_state()
    inject_css()
    lg = lang()
    with st.sidebar:
        if st.button(t("lang_toggle", lg), key="lang_btn"):
            st.session_state["lang"] = "en" if lg == "de" else "de"
            st.rerun()
        st.caption(f"v{versions('')['app']}")
    _prefill_from_token()
    if st.query_params.get("admin") == "1":
        admin.render()
        return
    step = st.session_state["step"]
    if st.session_state.get("done"):
        _done_page(lg)
    elif step == 0:
        welcome(lg)
    elif step in (1, 2, 3):
        _question_page(lg, step)
    elif step == 4:
        _results_page(lg)
    elif step == 5:
        _refine_page(lg)
    else:
        _followup_page(lg)
