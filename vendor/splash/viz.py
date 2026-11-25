from __future__ import annotations

import logging
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

log = logging.getLogger(__name__)

LEVEL_DIR = {"sh": "1_schleswig_holstein", "fac": "2_facility"}
LEVEL_NAME = {"sh": "Schleswig-Holstein", "fac": "Facility"}
THEME_NAME = {"D": "Demand", "O": "Operation", "F": "Flexibility", "E": "Economics", "C": "Comparison", "T": "Thermal state", "B": "Heat balance"}


COMP_COLOR = {
    "evaporation": "#0072B2",
    "make-up water": "#56B4E9",
    "conduction": "#999999",
    "radiation": "#CC79A7",
    "convection": "#E69F00",
    "solar gain": "#009E73",
    "hall air (sensible)": "#7B3F98",
    "hot water (showers)": "#B8860B",
}
COL = {
    "total": "#000000",
    "grid": "#4d4d4d",
    "curt": "#D55E00",
    "band": "#CC79A7",
    "base": "#7f7f7f",
    "floor": "#56B4E9",
    "rule": "#E69F00",
    "lp": "#009E73",
    "lp2": "#0072B2",
    "memo": "#444444",
    "temp": "#888888",
    "conv": "#8B5A2B",
}


MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

_CTX: dict = {"synthetic": []}


def set_context(synthetic: list[str] | None = None) -> None:
    if synthetic is not None:
        _CTX["synthetic"] = list(synthetic)


def style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.alpha": 0.25,
            "font.size": 9,
            "axes.titlesize": 10,
            "axes.titleweight": "bold",
            "legend.frameon": False,
            "timezone": "Europe/Berlin",
        }
    )


def slug(name: str) -> str:
    t = name.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        t = t.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


def sh_path(figdir: Path, theme: str, n: int, topic: str, suffix: str = "", sub: str = "") -> Path:
    d = Path(figdir) / LEVEL_DIR["sh"] / sub
    d.mkdir(parents=True, exist_ok=True)
    return d / f"sh_{theme}{n}_{topic}{suffix}.png"


def fac_path(figdir: Path, fid: int, name: str, theme: str, topic: str) -> Path:
    d = Path(figdir) / LEVEL_DIR["fac"]
    d.mkdir(parents=True, exist_ok=True)
    return d / f"fac_{fid:03d}_{slug(name)}_{theme}_{topic}.png"


def _tag(path: Path) -> str:
    n = Path(path).name
    m = re.match(r"sh_([DOFECTB])", n)
    if m:
        return f"{LEVEL_NAME['sh']} | {THEME_NAME[m.group(1)]}"
    m = re.search(r"_([DOFECTB])_[a-z0-9_]+\.png$", n)
    if n.startswith("fac_") and m:
        return f"{LEVEL_NAME['fac']} | {THEME_NAME[m.group(1)]}"
    return "SPLASH"


def footer_text(path: Path) -> str:
    t = f"SPLASH | {_tag(path)}"
    if _CTX["synthetic"]:
        t += f" | SYNTHETIC INPUTS: {', '.join(_CTX['synthetic'])}. Results are for method development only."
    return t


def save(fig, path: Path, dpi: int, bottom: float = 0.035, tight: bool = True) -> None:
    if tight:
        fig.tight_layout(rect=(0, bottom, 1, 1))
    fig.text(0.005, 0.004, footer_text(path), fontsize=6.5, color="#555555", ha="left", va="bottom")
    fig.savefig(path, dpi=dpi)
    plt.close(fig)
    log.info("figure %s", Path(path).name)
