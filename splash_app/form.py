"""Renders the questionnaire steps from data/questions.yaml and validates them."""
from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from splash_calc.inputs import BASIN_TYPES, Basin

from .i18n import olabel, qhelp, qlabel, questions_for_step, t
from .state import answers, lang, visible
from .theme import e, fmt_num

CONSUMPTION_ROWS = [
    ("gas", ["kwh", "mwh", "m3"], "cons_gas"),
    ("oil", ["l", "kwh"], "cons_oil"),
    ("district_heat", ["kwh", "mwh"], "cons_district_heat"),
    ("other_heat", ["kwh", "mwh"], "cons_other_heat"),
    ("electricity", ["kwh", "mwh"], "cons_electricity"),
]
UNIT_LABEL = {"kwh": "kWh", "mwh": "MWh", "m3": "m³", "l": "L"}


def _label(q: dict, lg: str) -> str:
    base = qlabel(q, lg)
    return f"{base} *" if q.get("required") and q["type"] not in ("basins", "consumption") else base


def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


# ------------------------------------------------------------------- widgets
def _w_text(q, lg, ans):
    v = st.text_input(_label(q, lg), value=ans.get(q["id"], "") or "", key=f"w_{q['id']}", help=qhelp(q, lg) or None)
    ans[q["id"]] = v.strip()


def _w_textarea(q, lg, ans):
    v = st.text_area(_label(q, lg), value=ans.get(q["id"], "") or "", key=f"w_{q['id']}", help=qhelp(q, lg) or None)
    ans[q["id"]] = v.strip()


def _w_number(q, lg, ans):
    qid = q["id"]
    is_int = q.get("step_size") == 1
    lo, hi = q.get("min"), q.get("max")
    cur = _clean(ans.get(qid))
    kw: dict = {"key": f"w_{qid}", "help": qhelp(q, lg) or None}
    unit = q.get("unit")
    label = _label(q, lg)
    if is_int:
        kw.update(min_value=int(lo) if lo is not None else None, max_value=int(hi) if hi is not None else None,
                  step=1, format="%d")
        cur = int(cur) if cur is not None else None
    else:
        kw.update(min_value=float(lo) if lo is not None else None, max_value=float(hi) if hi is not None else None,
                  step=1.0 if (hi is None or float(hi) >= 100) else 0.5)
        cur = float(cur) if cur is not None else None
    v = st.number_input(label, value=cur, placeholder=unit or "", **kw)
    ans[qid] = v


def _w_single(q, lg, ans):
    qid = q["id"]
    opts = q["options"]
    values = [str(o["value"]) for o in opts]
    labels = {str(o["value"]): olabel(o, lg) for o in opts}
    cur = ans.get(qid)
    idx = values.index(str(cur)) if cur is not None and str(cur) in values else None
    v = st.radio(_label(q, lg), values, index=idx, format_func=lambda x: labels[x], key=f"w_{qid}",
                 help=qhelp(q, lg) or None, horizontal=len(opts) <= 4 and max(len(x) for x in labels.values()) < 22)
    ans[qid] = v


def _w_multi(q, lg, ans):
    qid = q["id"]
    opts = q["options"]
    values = [str(o["value"]) for o in opts]
    labels = {str(o["value"]): olabel(o, lg) for o in opts}
    cur = [x for x in (ans.get(qid) or []) if x in values]
    v = st.multiselect(_label(q, lg), values, default=cur, format_func=lambda x: labels[x], key=f"w_{qid}",
                       help=qhelp(q, lg) or None, placeholder=t("choose", lg))
    ans[qid] = list(v)


def _w_scale(q, lg, ans):
    qid = q["id"]
    scale = q["scale"]
    values = [int(s["value"]) for s in scale]
    labels = {int(s["value"]): f"{s['value']}  {olabel(s, lg)}" for s in scale}
    cur = ans.get(qid)
    idx = values.index(int(cur)) if cur is not None and int(cur) in values else None
    v = st.radio(_label(q, lg), values, index=idx, format_func=lambda x: labels[x], key=f"w_{qid}",
                 horizontal=True, help=qhelp(q, lg) or None)
    ans[qid] = v


def _w_checkbox(q, lg, ans):
    v = st.checkbox(_label(q, lg), value=bool(ans.get(q["id"], False)), key=f"w_{q['id']}", help=qhelp(q, lg) or None)
    ans[q["id"]] = bool(v)


def _w_basins(q, lg, ans):
    qid = q["id"]
    st.markdown(f"**{qlabel(q, lg)}{' *' if q.get('required') else ''}**")
    if qhelp(q, lg):
        st.caption(qhelp(q, lg))
    type_labels = {bt: t(f"basin_{bt}", lg) for bt in BASIN_TYPES}
    rev = {v: k for k, v in type_labels.items()}
    combined = ans.get("q1_pool_type") == "combined"
    env_labels = {"indoor": t("basin_env_indoor", lg), "outdoor": t("basin_env_outdoor", lg)}
    env_rev = {v: k for k, v in env_labels.items()}
    if combined:
        st.info(t("basin_env_hint", lg))
    init_key = "_basin_init"
    # Streamlit drops the editor state when the step is left. Rebuild the table from the saved
    # answers then, so edits survive navigation. While editing, keep the same initial data.
    if init_key not in st.session_state or "w_basins_editor" not in st.session_state or st.session_state.get("_basin_combined") != combined:
        st.session_state["_basin_combined"] = combined
        st.session_state.pop("w_basins_editor", None)
        rows = ans.get(qid) or []
        data = [{
            "type": type_labels.get(r.get("type"), type_labels["lap"]),
            "environment": env_labels.get(r.get("environment") or "indoor", env_labels["indoor"]),
            "length_m": r.get("length_m"), "width_m": r.get("width_m"),
            "depth_min_m": r.get("depth_min_m"), "depth_max_m": r.get("depth_max_m"),
            "setpoint_c": r.get("setpoint_c"), "volume_known_m3": r.get("volume_known_m3"),
        } for r in rows]
        if not data:
            data = [{"type": type_labels["lap"], "environment": env_labels["indoor"], "length_m": None, "width_m": None, "depth_min_m": None,
                     "depth_max_m": None, "setpoint_c": None, "volume_known_m3": None}]
        df = pd.DataFrame(data)
        for c in ("length_m", "width_m", "depth_min_m", "depth_max_m", "setpoint_c", "volume_known_m3"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        st.session_state[init_key] = df
    cc = st.column_config
    edited = st.data_editor(
        st.session_state[init_key], key="w_basins_editor", num_rows="dynamic", hide_index=True,
        column_config={
            "type": cc.SelectboxColumn(t("basin_type", lg), options=list(type_labels.values()), required=True),
            "environment": (cc.SelectboxColumn(t("basin_env", lg), options=list(env_labels.values()), required=True) if combined else None),
            "length_m": cc.NumberColumn(t("basin_length", lg), min_value=0.0, max_value=200.0, step=0.5),
            "width_m": cc.NumberColumn(t("basin_width", lg), min_value=0.0, max_value=100.0, step=0.5),
            "depth_min_m": cc.NumberColumn(t("basin_dmin", lg), min_value=0.0, max_value=10.0, step=0.1),
            "depth_max_m": cc.NumberColumn(t("basin_dmax", lg), min_value=0.0, max_value=10.0, step=0.1),
            "setpoint_c": cc.NumberColumn(t("basin_temp", lg), min_value=15.0, max_value=40.0, step=0.5),
            "volume_known_m3": cc.NumberColumn(t("basin_vol", lg), min_value=0.0, step=1.0),
        },
        **_stretch(),
    )
    rows = []
    for _, r in edited.iterrows():
        rows.append({
            "type": rev.get(r.get("type"), "lap"),
            "environment": env_rev.get(r.get("environment"), "indoor") if combined else None,
            "length_m": _clean(r.get("length_m")), "width_m": _clean(r.get("width_m")),
            "depth_min_m": _clean(r.get("depth_min_m")), "depth_max_m": _clean(r.get("depth_max_m")),
            "setpoint_c": _clean(r.get("setpoint_c")), "volume_known_m3": _clean(r.get("volume_known_m3")),
        })
    rows = [r for r in rows if r["length_m"] or r["width_m"]]
    ans[qid] = rows
    basins = [Basin(**r) for r in rows]
    area = sum(b.area_m2() for b in basins)
    vol = sum(b.volume_m3()[0] for b in basins)
    if area > 0:
        st.markdown(
            f'<div class="sp-small">{e(t("basin_sum", lg))}: <b>{e(fmt_num(area, 0, lg))} m²</b> · '
            f'{e(t("basin_vol_sum", lg))}: <b>{e(fmt_num(vol, 0, lg))} m³</b></div>',
            unsafe_allow_html=True,
        )


def _stretch() -> dict:
    from .theme import stretch

    return stretch()


def _w_consumption(q, lg, ans):
    qid = q["id"]
    st.markdown(f"**{_label(q, lg)}**")
    if qhelp(q, lg):
        st.caption(qhelp(q, lg))
    cur = dict(ans.get(qid) or {})
    out: dict = {}
    for carrier, units, label_key in CONSUMPTION_ROWS:
        c1, c2, c3 = st.columns([3, 2, 2])
        c1.markdown(f"<div style='padding-top:2.1rem'>{e(t(label_key, lg))}</div>", unsafe_allow_html=True)
        item = cur.get(carrier) or {}
        val = item.get("value")
        val = float(val) if val not in (None, "") else None
        v = c2.number_input(t("cons_value", lg), value=val, min_value=0.0, step=1000.0,
                            key=f"w_cons_{carrier}_v", label_visibility="collapsed" if carrier != "gas" else "visible")
        unit_default = item.get("unit") if item.get("unit") in units else units[0]
        u = c3.selectbox(t("cons_unit", lg), units, index=units.index(unit_default),
                         format_func=lambda x: UNIT_LABEL[x], key=f"w_cons_{carrier}_u",
                         label_visibility="collapsed" if carrier != "gas" else "visible")
        if v:
            out[carrier] = {"value": v, "unit": u}
    ans[qid] = out


MONTH_DAYS = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _date_pick(lg: str, key: str, cur: list | None, default: tuple[int, int]) -> list[int]:
    day0, month0 = (cur or default)[0], (cur or default)[1]
    months = t("months", lg)
    c1, c2 = st.columns([1, 2])
    month = c2.selectbox(t("season_month", lg), list(range(1, 13)), index=int(month0) - 1, format_func=lambda m: months[m - 1],
                         key=f"{key}_m", label_visibility="collapsed")
    day = c1.selectbox(t("season_day", lg), list(range(1, MONTH_DAYS[month - 1] + 1)),
                       index=min(int(day0), MONTH_DAYS[month - 1]) - 1, key=f"{key}_d", label_visibility="collapsed")
    return [int(day), int(month)]


def _w_season(q, lg, ans):
    qid = q["id"]
    cur = ans.get(qid) or {}
    options = ["year_round", "season"]
    idx = None
    if cur.get("year_round"):
        idx = 0
    elif cur.get("from") and cur.get("to"):
        idx = 1
    st.markdown(f"**{_label(q, lg)}**")
    if qhelp(q, lg):
        st.caption(qhelp(q, lg))
    pick = st.radio(_label(q, lg), options, index=idx, horizontal=True, key=f"w_{qid}_mode",
                    format_func=lambda x: t(f"season_{x}", lg), label_visibility="collapsed")
    if pick == "year_round":
        ans[qid] = {"year_round": True}
    elif pick == "season":
        a, b = st.columns(2)
        with a:
            st.caption(t("season_from", lg))
            f = _date_pick(lg, f"w_{qid}_from", cur.get("from"), (1, 5))
        with b:
            st.caption(t("season_to", lg))
            to = _date_pick(lg, f"w_{qid}_to", cur.get("to"), (30, 9))
        ans[qid] = {"year_round": False, "from": f, "to": to}
    else:
        ans[qid] = None


def _w_weekdays(q, lg, ans):
    qid = q["id"]
    cur = set(ans.get(qid) or [])
    st.markdown(f"**{_label(q, lg)}**")
    cols = st.columns(7)
    picked = [d for d, col in zip(WEEKDAYS, cols, strict=True)
              if col.checkbox(t(f"day_{d}", lg), value=d in cur, key=f"w_{qid}_{d}")]
    ans[qid] = picked


def _to_time(v):
    import datetime as dt

    try:
        h, m = str(v).split(":")
        return dt.time(int(h), int(m))
    except (ValueError, TypeError):
        return None


def _w_hours(q, lg, ans):
    qid = q["id"]
    cur = ans.get(qid) or {}
    st.markdown(f"**{_label(q, lg)}**")
    if qhelp(q, lg):
        st.caption(qhelp(q, lg))
    out: dict = {}
    for part in ("weekday", "weekend"):
        c0, c1, c2 = st.columns([1.2, 1, 1])
        c0.markdown(t(f"hours_{part}", lg))
        old = cur.get(part) or [None, None]
        a = c1.time_input(t("hours_open", lg), value=_to_time(old[0]), step=1800, key=f"w_{qid}_{part}_o")
        b = c2.time_input(t("hours_close", lg), value=_to_time(old[1]), step=1800, key=f"w_{qid}_{part}_c")
        if a is not None and b is not None:
            out[part] = [a.strftime("%H:%M"), b.strftime("%H:%M")]
    ans[qid] = out or None


WIDGETS = {
    "season": _w_season, "weekdays": _w_weekdays, "hours": _w_hours,
    "text": _w_text, "textarea": _w_textarea, "number": _w_number, "single": _w_single, "multi": _w_multi,
    "scale": _w_scale, "checkbox": _w_checkbox, "basins": _w_basins, "consumption": _w_consumption,
}


def render_step(step: int, skip: set[str] | None = None) -> None:
    lg, ans = lang(), answers()
    skip = skip or set()
    for q in questions_for_step(step):
        if q["id"] in skip or not visible(q, ans):
            continue
        WIDGETS[q["type"]](q, lg, ans)


# ---------------------------------------------------------------- validation
def _filled(q: dict, ans: dict) -> bool:
    v = ans.get(q["id"])
    typ = q["type"]
    if typ == "checkbox":
        return bool(v)
    if typ == "basins":
        return any((r.get("length_m") or 0) > 0 and (r.get("width_m") or 0) > 0 for r in (v or []))
    if typ in ("multi", "weekdays", "season", "hours"):
        return bool(v)
    if typ == "consumption":
        return bool(v)
    if typ in ("text", "textarea"):
        return bool((v or "").strip())
    return v is not None


def missing_required(step: int) -> list[str]:
    lg, ans = lang(), answers()
    out = []
    for q in questions_for_step(step):
        if q.get("required") and visible(q, ans) and not _filled(q, ans):
            out.append(qlabel(q, lg))
    return out
