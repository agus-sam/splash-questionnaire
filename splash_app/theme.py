"""Look and feel: palette, CSS and small HTML components. No external assets."""
from __future__ import annotations

import html
import inspect

import streamlit as st

NAVY = "#0B2A3C"
TEAL = "#0E7C86"
AQUA = "#19B5C4"
FOAM = "#E8F7F8"
SAND = "#F2A541"
CORAL = "#D1495B"
GREEN = "#2E9E6B"
SLATE = "#5B7083"

CSS = f"""
<style>
:root {{ --navy:{NAVY}; --teal:{TEAL}; --aqua:{AQUA}; --foam:{FOAM}; --sand:{SAND}; --coral:{CORAL}; --green:{GREEN}; --slate:{SLATE}; }}
.block-container {{ padding-top: 1.2rem; max-width: 1100px; }}
header[data-testid="stHeader"] {{ background: transparent; }}

.sp-hero {{ position: relative; overflow: hidden; border-radius: 22px; padding: 34px 38px 70px 38px;
  background: linear-gradient(135deg, {NAVY} 0%, {TEAL} 62%, {AQUA} 100%); color: #fff; margin-bottom: 18px;
  box-shadow: 0 10px 30px rgba(11,42,60,.25); }}
.sp-hero h1 {{ color:#fff; font-size: 2.1rem; margin: 0 0 4px 0; letter-spacing: -.5px; }}
.sp-hero .sp-tag {{ font-size: 1.25rem; font-weight: 600; margin: 6px 0 10px 0; color:#fff; }}
.sp-hero .sp-sub {{ max-width: 760px; opacity: .92; font-size: 1.02rem; line-height: 1.5; }}
.sp-chips {{ margin-top: 16px; display:flex; gap:8px; flex-wrap: wrap; }}
.sp-chip {{ background: rgba(255,255,255,.16); border: 1px solid rgba(255,255,255,.28); border-radius: 999px;
  padding: 4px 12px; font-size: .85rem; }}
.sp-waves {{ position:absolute; left:0; right:0; bottom:0; height:56px; width:100%; }}
.sp-waves .w1 {{ animation: sp-drift 9s linear infinite; }}
.sp-waves .w2 {{ animation: sp-drift 14s linear infinite reverse; }}
@keyframes sp-drift {{ from {{ transform: translateX(0); }} to {{ transform: translateX(-50%); }} }}
@media (prefers-reduced-motion: reduce) {{ .sp-waves .w1, .sp-waves .w2 {{ animation: none; }} }}

.sp-steps {{ display:flex; gap:6px; margin: 4px 0 18px 0; flex-wrap: wrap; }}
.sp-step {{ flex:1; min-width: 92px; text-align:center; padding: 8px 6px; border-radius: 12px; font-size:.85rem;
  background: {FOAM}; color: {SLATE}; border: 1px solid #d5eef0; }}
.sp-step b {{ display:block; font-size: 1.05rem; }}
.sp-step.done {{ background: {TEAL}; color:#fff; border-color:{TEAL}; }}
.sp-step.now {{ background: {NAVY}; color:#fff; border-color:{NAVY}; box-shadow: 0 4px 12px rgba(11,42,60,.3); }}

.sp-card {{ background:#fff; border:1px solid #dbe9ec; border-radius:16px; padding:18px 20px; margin-bottom:14px;
  box-shadow: 0 2px 8px rgba(11,42,60,.05); }}
.sp-card h3 {{ margin-top:0; color:{NAVY}; }}

.sp-kpis {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; margin: 8px 0 14px 0; }}
.sp-kpi {{ border-radius: 16px; padding: 14px 16px; background: linear-gradient(160deg, #fff 0%, {FOAM} 100%);
  border: 1px solid #cfe6e9; border-left: 6px solid {TEAL}; }}
.sp-kpi.good {{ border-left-color: {GREEN}; }}
.sp-kpi.warn {{ border-left-color: {SAND}; }}
.sp-kpi.bad {{ border-left-color: {CORAL}; }}
.sp-kpi .l {{ font-size:.82rem; color:{SLATE}; text-transform: uppercase; letter-spacing:.4px; }}
.sp-kpi .v {{ font-size:1.65rem; font-weight:700; color:{NAVY}; line-height:1.2; }}
.sp-kpi .r {{ font-size:.82rem; color:{SLATE}; margin-top:2px; }}

.sp-note {{ border-radius: 12px; padding: 10px 14px; margin: 8px 0; font-size:.93rem; }}
.sp-note.info {{ background:{FOAM}; border:1px solid #cfe6e9; color:{NAVY}; }}
.sp-note.warn {{ background:#FFF4E0; border:1px solid #f4d9a8; color:#6b4a0c; }}
.sp-note.bad {{ background:#FDECEF; border:1px solid #f3c1c9; color:#7a2433; }}

.sp-code {{ font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 1.6rem; letter-spacing: 3px;
  background:{FOAM}; border:2px dashed {TEAL}; border-radius:12px; padding:10px 18px; display:inline-block; color:{NAVY}; }}
.sp-small {{ color:{SLATE}; font-size:.85rem; }}
div[data-testid="stButton"] > button[kind="primary"] {{ background: {TEAL}; border-color: {TEAL}; }}
div[data-testid="stButton"] > button[kind="primary"]:hover {{ background: {NAVY}; border-color: {NAVY}; }}
div[data-testid="stButton"] > button[kind="primary"]:disabled {{ background: #9CC9CD; border-color: #9CC9CD; color: #ffffff; opacity: 1; }}
</style>
"""

WAVES = """
<svg class="sp-waves" viewBox="0 0 1200 56" preserveAspectRatio="none" aria-hidden="true">
  <g class="w2" opacity=".35"><path d="M0 28 Q 75 6 150 28 T 300 28 T 450 28 T 600 28 T 750 28 T 900 28 T 1050 28 T 1200 28 T 1350 28 T 1500 28 T 1650 28 T 1800 28 T 1950 28 T 2100 28 T 2250 28 T 2400 28 V56 H0Z" fill="#ffffff"/></g>
  <g class="w1" opacity=".9"><path d="M0 34 Q 75 14 150 34 T 300 34 T 450 34 T 600 34 T 750 34 T 900 34 T 1050 34 T 1200 34 T 1350 34 T 1500 34 T 1650 34 T 1800 34 T 1950 34 T 2100 34 T 2250 34 T 2400 34 V56 H0Z" fill="#ffffff"/></g>
</svg>
"""


def stretch() -> dict:
    """Keyword for full-width widgets that works across Streamlit versions."""
    if "width" in inspect.signature(st.button).parameters:
        return {"width": "stretch"}
    return {"use_container_width": True}


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def e(text: object) -> str:
    return html.escape(str(text))


def hero(title: str, tagline: str, sub: str, chips: list[str]) -> None:
    chips_html = "".join(f'<span class="sp-chip">{e(c)}</span>' for c in chips)
    st.markdown(
        f'<div class="sp-hero"><h1>{e(title)}</h1><div class="sp-tag">{e(tagline)}</div>'
        f'<div class="sp-sub">{e(sub)}</div><div class="sp-chips">{chips_html}</div>{WAVES}</div>',
        unsafe_allow_html=True,
    )


def mini_hero(title: str, subtitle: str) -> None:
    st.markdown(
        f'<div class="sp-hero" style="padding:20px 30px 52px 30px"><h1 style="font-size:1.5rem">{e(title)}</h1>'
        f'<div class="sp-sub">{e(subtitle)}</div>{WAVES}</div>',
        unsafe_allow_html=True,
    )


def stepper(labels: list[str], current: int) -> None:
    parts = []
    for i, lab in enumerate(labels):
        cls = "now" if i == current else ("done" if i < current else "")
        parts.append(f'<div class="sp-step {cls}"><b>{i + 1}</b>{e(lab)}</div>')
    st.markdown(f'<div class="sp-steps">{"".join(parts)}</div>', unsafe_allow_html=True)


def kpi_row(items: list[dict]) -> None:
    """items: {label, value, range?, tone?} where tone in good|warn|bad|''."""
    tiles = []
    for it in items:
        rng = f'<div class="r">{e(it["range"])}</div>' if it.get("range") else ""
        tiles.append(
            f'<div class="sp-kpi {e(it.get("tone", ""))}"><div class="l">{e(it["label"])}</div>'
            f'<div class="v">{e(it["value"])}</div>{rng}</div>'
        )
    st.markdown(f'<div class="sp-kpis">{"".join(tiles)}</div>', unsafe_allow_html=True)


def note(kind: str, text: str) -> None:
    st.markdown(f'<div class="sp-note {e(kind)}">{e(text)}</div>', unsafe_allow_html=True)


def code_box(code: str) -> None:
    st.markdown(f'<div class="sp-code">{e(code)}</div>', unsafe_allow_html=True)


# ------------------------------------------------------------ number formats
def fmt_num(x: float | None, decimals: int = 0, lang: str = "en") -> str:
    if x is None:
        return "–"
    s = f"{x:,.{decimals}f}"
    if lang == "de":
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def fmt_eur(x: float | None, lang: str = "en") -> str:
    if x is None:
        return "–"
    sign = "-" if x < 0 else ""
    return f"{sign}{fmt_num(abs(x), 0, lang)} EUR"


def fmt_kwh(x: float, lang: str = "en") -> str:
    ax = abs(x)
    if ax >= 1e6:
        return f"{fmt_num(x / 1e6, 2, lang)} GWh"
    if ax >= 1e3:
        return f"{fmt_num(x / 1e3, 0, lang)} MWh"
    return f"{fmt_num(x, 0, lang)} kWh"


def fmt_range(lo: float, hi: float, f) -> str:
    a, b = sorted((lo, hi))
    return f"{f(a)} … {f(b)}"
