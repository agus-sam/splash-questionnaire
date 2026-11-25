"""Versioned parameter file: loading, cases and overrides.

Every uncertain parameter has a pessimistic, central and optimistic value.
Pessimistic and optimistic always describe the effect on the operator's NPV.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_PARAMS_PATH = DATA_DIR / "parameters.yaml"

CASES = ("pessimistic", "central", "optimistic")


@lru_cache(maxsize=4)
def _read_yaml(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _fmt(v: Any) -> str:
    return f"{v:.4g}" if isinstance(v, float) else str(v)


class Params:
    """Read access to the parameter file with cases, pins and overrides.

    * ``case`` selects the value set for all uncertain parameters.
    * ``pins`` fixes single parameters to another case (used for tornado charts).
    * ``overrides`` replaces a parameter by a fixed value (operator input).
      An overridden parameter has no uncertainty range.
    * ``shifts`` sets a new *central* value for an uncertain parameter and keeps
      the distance of its pessimistic and optimistic value (operator input that
      keeps the range).
    """

    def __init__(
        self,
        raw: dict,
        case: str = "central",
        pins: dict[str, str] | None = None,
        overrides: dict[str, Any] | None = None,
        shifts: dict[str, Any] | None = None,
    ) -> None:
        if case not in CASES:
            raise ValueError(f"unknown case: {case}")
        self.raw = raw
        self.case = case
        self.pins = dict(pins or {})
        self.overrides = dict(overrides or {})
        self.shifts = dict(shifts or {})

    # ------------------------------------------------------------------ load
    @classmethod
    def load(cls, path: str | Path | None = None, overrides: dict | None = None) -> Params:
        p = Path(path) if path else DEFAULT_PARAMS_PATH
        raw = _read_yaml(str(p.resolve()))
        if "parameters" not in raw or "meta" not in raw:
            raise ValueError("parameter file needs the keys 'meta' and 'parameters'")
        return cls(raw, overrides=overrides)

    # ----------------------------------------------------------------- views
    @property
    def meta(self) -> dict:
        return self.raw["meta"]

    @property
    def version(self) -> str:
        return str(self.meta["version"])

    @property
    def is_draft(self) -> bool:
        """True while the project team has not signed the parameter set off (meta.status != validated)."""
        return self.meta.get("status") != "validated"

    def names(self) -> list[str]:
        return list(self.raw["parameters"].keys())

    def entry(self, name: str) -> dict:
        try:
            return self.raw["parameters"][name]
        except KeyError as exc:
            raise KeyError(f"unknown parameter: {name}") from exc

    def is_uncertain(self, name: str) -> bool:
        e = self.entry(name)
        return "central" in e and ("pessimistic" in e or "optimistic" in e)

    def uncertain_names(self) -> list[str]:
        return [n for n in self.names() if self.is_uncertain(n) and n not in self.overrides]

    def default_central(self, name: str) -> Any:
        """Central value from the file, ignoring all operator input."""
        e = self.entry(name)
        return deepcopy(e["value"]) if "value" in e else e["central"]

    # ------------------------------------------------------------------- get
    def get(self, name: str) -> Any:
        if name in self.overrides:
            return self.overrides[name]
        e = self.entry(name)
        if "value" in e:
            return deepcopy(e["value"])
        case = self.pins.get(name, self.case)
        if name in self.shifts:
            offset = (e[case] - e["central"]) if case in e else 0.0
            return self.shifts[name] + offset
        if case in e:
            return e[case]
        return e["central"]

    def central(self, name: str) -> Any:
        """Central value, ignoring the current case and pins (operator input still applies)."""
        if name in self.overrides:
            return self.overrides[name]
        if name in self.shifts:
            return self.shifts[name]
        return self.default_central(name)

    # --------------------------------------------------------------- derived
    def at_case(self, case: str) -> Params:
        return Params(self.raw, case=case, pins=self.pins, overrides=self.overrides, shifts=self.shifts)

    def pinned(self, name: str, case: str) -> Params:
        pins = dict(self.pins)
        pins[name] = case
        return Params(self.raw, case=self.case, pins=pins, overrides=self.overrides, shifts=self.shifts)

    def with_overrides(self, **kw: Any) -> Params:
        """Fix parameters to one value. The parameter then has no range."""
        ov = dict(self.overrides)
        ov.update({k: v for k, v in kw.items() if v is not None})
        for k in ov:
            self.entry(k)  # raises on unknown names
        return Params(self.raw, case=self.case, pins=self.pins, overrides=ov, shifts=self.shifts)

    def with_central(self, **kw: Any) -> Params:
        """Move the central value of uncertain parameters. Pessimistic and optimistic keep their distance."""
        sh = dict(self.shifts)
        for k, v in kw.items():
            if v is None:
                continue
            if not self.is_uncertain(k):
                raise ValueError(f"{k} has no range, use with_overrides")
            sh[k] = v
        return Params(self.raw, case=self.case, pins=self.pins, overrides=self.overrides, shifts=sh)

    def apply_input(self, values: dict[str, Any]) -> Params:
        """Apply operator input: ranges are kept where the parameter has one."""
        central = {k: v for k, v in values.items() if v is not None and self.is_uncertain(k)}
        fixed = {k: v for k, v in values.items() if v is not None and not self.is_uncertain(k)}
        return self.with_overrides(**fixed).with_central(**central)

    # ----------------------------------------------------------------- table
    def table(self, lang: str = "en") -> list[dict]:
        """Rows for the assumptions table in the app."""
        rows = []
        for name in self.names():
            e = self.entry(name)
            label = e.get(f"label_{lang}") or e.get("label_en") or name
            if "value" in e:
                value = e["value"]
                rng = ""
            else:
                value = self.central(name)
                lo = self.at_case("pessimistic").get(name)
                hi = self.at_case("optimistic").get(name)
                rng = f"{_fmt(lo)} / {_fmt(hi)}"
            if name in self.overrides:
                value = self.overrides[name]
                rng = ""
            rows.append(
                {
                    "id": name,
                    "edited": name in self.overrides or name in self.shifts,
                    "label": label,
                    "value": value,
                    "range": rng,
                    "unit": e.get("unit", ""),
                    "status": e.get("status", ""),
                    "source": e.get("source", ""),
                }
            )
        return rows

    def status_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for name in self.names():
            s = self.entry(name).get("status", "unknown")
            out[s] = out.get(s, 0) + 1
        return out
