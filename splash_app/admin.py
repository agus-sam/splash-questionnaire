"""Password protected project area: counts, tables and Excel export."""
from __future__ import annotations

import hmac
import io

import pandas as pd
import streamlit as st

from .backend import admin_password, get_store
from .i18n import t
from .state import lang
from .storage import sanitise_frame
from .theme import mini_hero, note, stretch

MAX_ATTEMPTS = 5


def _latest(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    if df.empty:
        return df
    return df.sort_values("timestamp_utc").drop_duplicates(keys, keep="last")


def _wide(df: pd.DataFrame, name_col: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    last = _latest(df, ["submission_id", name_col])
    if "stage" in df.columns and name_col == "question_id":
        # an answer removed in a later save must not stay as current: keep rows of the newest save only
        newest = df.groupby("submission_id")["timestamp_utc"].transform("max")
        last = df[df["timestamp_utc"] == newest].drop_duplicates(["submission_id", name_col], keep="last")
    wide = last.pivot(index="submission_id", columns=name_col, values="value")
    wide.columns.name = None
    return wide.reset_index()


def render() -> None:
    lg = lang()
    mini_hero(t("admin_title", lg), "")
    pw = admin_password()
    if not pw:
        note("warn", t("admin_not_set", lg))
        return
    ss = st.session_state
    if ss.get("admin_ok") is not True:
        if ss.get("admin_fails", 0) >= MAX_ATTEMPTS:
            note("bad", t("admin_locked", lg))
            return
        entered = st.text_input(t("admin_pw", lg), type="password", key="admin_pw_input")
        if not entered:
            return
        if not hmac.compare_digest(entered.encode(), pw.encode()):
            ss["admin_fails"] = ss.get("admin_fails", 0) + 1
            note("bad", t("admin_wrong", lg))
            return
        ss["admin_ok"] = True

    store = get_store()
    st.caption(f"Backend: {store.name}" + (" (test mode)" if store.is_test else ""))
    subs = pd.DataFrame(store.read_table("submissions"))
    answers = pd.DataFrame(store.read_table("answers"))
    results = pd.DataFrame(store.read_table("results"))

    n_all = subs["submission_id"].nunique() if not subs.empty else 0
    n_final = _latest(subs, ["submission_id"]).query("stage == 'final'").shape[0] if not subs.empty else 0
    c1, c2, c3 = st.columns(3)
    c1.metric("Submissions", n_all)
    c2.metric("Completed", n_final)
    c3.metric("Rows (answers)", len(answers))

    wide_a, wide_r = _wide(answers, "question_id"), _wide(results, "kpi")
    st.subheader("Answers")
    st.dataframe(wide_a, **stretch())
    st.subheader("Results")
    st.dataframe(wide_r, **stretch())

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        sanitise_frame(_latest(subs, ["submission_id"]).drop(columns=["answers_json"], errors="ignore")).to_excel(
            xl, sheet_name="submissions", index=False)
        sanitise_frame(wide_a).to_excel(xl, sheet_name="answers", index=False)
        sanitise_frame(wide_r).to_excel(xl, sheet_name="results", index=False)
        sanitise_frame(answers).to_excel(xl, sheet_name="answers_log", index=False)
    st.download_button("Excel export (no contact data)", buf.getvalue(), "splash-export.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary", key="dl_xlsx")

    with st.expander("Contact data (handle with care)"):
        contacts = pd.DataFrame(store.read_table("contacts"))
        st.dataframe(contacts, **stretch())
        st.download_button("Contacts CSV", sanitise_frame(contacts).to_csv(index=False).encode("utf-8"), "splash-contacts.csv",
                           "text/csv", key="dl_contacts")
