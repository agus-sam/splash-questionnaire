"""Session state helpers."""
from __future__ import annotations

import streamlit as st

from splash_calc import __version__ as CALC_VERSION

from .i18n import load_questions
from .storage import new_submission_id

APP_VERSION = CALC_VERSION
FINAL_STEP = 6


def init_state() -> None:
    ss = st.session_state
    ss.setdefault("lang", "de")
    ss.setdefault("step", 0)
    ss.setdefault("answers", {})
    ss.setdefault("submission_id", new_submission_id())
    ss.setdefault("is_demo", False)
    ss.setdefault("save_error", False)
    ss.setdefault("done", False)
    ss.setdefault("opts", {"fuel_factor": 1.0, "el_factor": 1.0, "zone": None,
                           "hp_kw": None, "band_k": None, "curt_mwh": None, "econ": {}, "calibrate": False})
    ss.setdefault("pool_token", "")
    ss.setdefault("prefilled", False)


def lang() -> str:
    return st.session_state.get("lang", "de")


def answers() -> dict:
    return st.session_state["answers"]


def goto(step: int) -> None:
    st.session_state["step"] = step


def clear_widget_state() -> None:
    """Drop widget state so that widgets re-read the answers (after demo or resume)."""
    for k in list(st.session_state.keys()):
        if k.startswith(("w_", "sl_", "assump_", "flex_")) or k == "_basin_init":
            del st.session_state[k]


def reset_all() -> None:
    for k in list(st.session_state.keys()):
        if k not in ("lang",):
            del st.session_state[k]
    init_state()


def versions(params_version: str) -> dict:
    return {
        "questionnaire": str(load_questions()["meta"]["version"]),
        "params": params_version,
        "app": APP_VERSION,
    }


def visible(q: dict, ans: dict) -> bool:
    cond = q.get("show_if")
    if not cond:
        return True
    val = ans.get(cond["id"])
    if cond.get("truthy"):
        return bool(val)
    allowed = set(cond.get("in", []))
    if isinstance(val, (list, tuple, set)):
        return bool(allowed & set(map(str, val)))
    return val is not None and str(val) in allowed


def visible_answers(ans: dict) -> dict:
    """Answers of questions that are currently visible (hidden follow-ups are dropped)."""
    out = {}
    for q in load_questions()["questions"]:
        if q["id"] in ans and visible(q, ans):
            out[q["id"]] = ans[q["id"]]
    return out
