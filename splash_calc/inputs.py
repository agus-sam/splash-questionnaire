"""Pool inputs: typed model and the translation from questionnaire answers.

``from_answers`` is the only place that knows the question ids. It returns the
inputs, a provenance map (entered, default or estimated for every tracked
field) and a list of warnings that the interface can translate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .params import Params

# Field names whose provenance counts towards the "data confidence" score.
TRACKED_FIELDS = (
    "heat_consumption",
    "electricity_consumption",
    "water_surface",
    "water_volume",
    "setpoints",
    "hall_area",
    "opening_hours",
    "heat_price",
    "electricity_price",
    "heat_recovery",
    "boiler_efficiency",
    "visitors",
)

CARRIERS = ("gas", "oil", "district_heat", "other_heat")

BASIN_TYPES = ("lap", "teaching", "therapy", "children", "leisure", "diving", "outdoor")


@dataclass
class Basin:
    type: str = "lap"
    length_m: float | None = None
    width_m: float | None = None
    depth_min_m: float | None = None
    depth_max_m: float | None = None
    setpoint_c: float | None = None
    volume_known_m3: float | None = None
    environment: str | None = None      # "indoor" or "outdoor"; used for combined pools only

    def area_m2(self) -> float:
        if self.length_m and self.width_m:
            return float(self.length_m) * float(self.width_m)
        return 0.0

    def volume_m3(self) -> tuple[float, bool]:
        """Return (volume, estimated). Known volume wins, else geometry."""
        if self.volume_known_m3 and self.volume_known_m3 > 0:
            return float(self.volume_known_m3), False
        a = self.area_m2()
        if a <= 0:
            return 0.0, True
        dmin = self.depth_min_m if self.depth_min_m is not None else self.depth_max_m
        dmax = self.depth_max_m if self.depth_max_m is not None else self.depth_min_m
        if dmin is None or dmax is None:
            return 0.0, True
        return a * (float(dmin) + float(dmax)) / 2.0, True


@dataclass
class PoolInputs:
    name: str = ""
    city: str = ""
    postcode: str = ""
    pool_type: str = "indoor"          # indoor | combined | open_air
    legal_form: str = "municipal_operation"
    basins: list[Basin] = field(default_factory=list)
    hall_area_m2: float | None = None
    air_setpoint_c: float | None = None
    heat_recovery: bool | None = None
    operating_weeks: float | None = None
    hours_per_week: float | None = None
    season_year_round: bool | None = None
    season_from: tuple[int, int] | None = None      # (day, month) of opening
    season_to: tuple[int, int] | None = None        # (day, month) of closing
    outdoor_year_round: bool | None = None          # combined pool: opening window of the outdoor basins
    outdoor_from: tuple[int, int] | None = None
    outdoor_to: tuple[int, int] | None = None
    outdoor_weeks: float | None = None
    open_days: list[str] | None = None
    hours_weekday: tuple[float, float] | None = None   # opening and closing hour of the day
    hours_weekend: tuple[float, float] | None = None
    heat_sources: list[str] = field(default_factory=list)
    main_source: str | None = None
    main_capacity_kw: float | None = None
    consumption_kwh: dict[str, float] = field(default_factory=dict)   # entered, per carrier
    electricity_kwh: float | None = None
    heat_cost_eur: float | None = None
    elec_cost_eur: float | None = None
    costs_incl_vat: str | None = None   # yes | no | unknown
    boiler_age_years: float | None = None
    boiler_eta: float | None = None
    allowed_change_k: float | None = None
    hold_hours: float | None = None
    buffer_m3: float | None = None
    pv_kwp: float | None = None
    grid_kw: float | None = None
    dh_contract_binding: str | None = None   # yes | no | unknown
    hp_source: str = "air"                   # air | ground | waste
    visitors_weekday: float | None = None    # people per open weekday (Monday to Friday)
    visitors_weekend: float | None = None    # people per open weekend day
    visitors_year: float | None = None       # people per year, wins over the daily values
    dhw_supply: str = "central"              # central (same plant as the pool) | separate | none
    shower_litres: float | None = None       # shower water per visitor in litres, None = model default
    dhw_tank_m3: float | None = None         # hot water tank volume in m3 (only with central hot water), None = no tank or unknown

    # ------------------------------------------------------------- derived
    def water_surface_m2(self) -> float:
        return sum(b.area_m2() for b in self.basins)

    def water_volume_m3(self) -> float:
        return sum(b.volume_m3()[0] for b in self.basins)

    def annual_visitors(self) -> tuple[float | None, str]:
        """Visitors per year and where the number comes from: "entered" (annual figure), "derived" (daily figures times open
        days and operating weeks) or "default" (nothing entered, the model uses its own occupancy profile)."""
        if self.visitors_year:
            return float(self.visitors_year), "entered"
        wd, we = self.visitors_weekday, self.visitors_weekend
        if not wd and not we:
            return None, "default"
        wd = wd if wd else we                      # a missing group takes the value of the other one
        we = we if we else wd
        days = self.open_days or ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        n_we = sum(1 for d in days if d in ("sat", "sun"))
        n_wd = len(days) - n_we
        weeks = self.operating_weeks or 52.0
        return float(wd * n_wd + we * n_we) * weeks, "derived"

    def to_json_dict(self) -> dict:
        from dataclasses import asdict

        return asdict(self)

    @classmethod
    def from_json_dict(cls, d: dict) -> PoolInputs:
        d = dict(d)
        d["basins"] = [Basin(**b) for b in d.get("basins", [])]
        return cls(**d)


@dataclass
class Parsed:
    inputs: PoolInputs
    provenance: dict[str, str]
    warnings: list[dict]

    def confidence(self) -> tuple[int, int]:
        """(entered, total) over the tracked fields."""
        entered = sum(1 for f in TRACKED_FIELDS if self.provenance.get(f) == "entered")
        return entered, len(TRACKED_FIELDS)


# --------------------------------------------------------------------- helpers
def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def _pos(v: Any) -> float | None:
    f = _num(v)
    return f if f is not None and f > 0 else None


def to_kwh(value: Any, unit: str | None, carrier: str, params: Params) -> float | None:
    """Convert an entered consumption value to kWh. Returns None if unusable."""
    v = _pos(value)
    if v is None:
        return None
    u = (unit or "kwh").lower()
    if u == "kwh":
        return v
    if u == "mwh":
        return v * 1000.0
    if u == "m3" and carrier == "gas":
        return v * float(params.central("gas_kwh_per_m3"))
    if u == "l" and carrier == "oil":
        return v * float(params.central("oil_kwh_per_l"))
    return None


# ----------------------------------------------------------------- main parser
def _md(v) -> tuple[int, int] | None:
    try:
        d, m = int(v[0]), int(v[1])
    except (TypeError, ValueError, IndexError):
        return None
    if not 1 <= m <= 12:
        return None
    days = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[m - 1]
    return (min(max(d, 1), days), m)


def _hour(v) -> float | None:
    try:
        h, m = str(v).split(":")
        return int(h) + int(m) / 60.0
    except (TypeError, ValueError):
        return None


def _span_days(a: tuple[int, int], b: tuple[int, int]) -> int:
    """Days from the opening to the closing date, both included. The season may run over the new year."""
    import datetime as dt

    d0 = dt.date(2025, a[1], min(a[0], 28 if a[1] == 2 else a[0]))
    d1 = dt.date(2025, b[1], min(b[0], 28 if b[1] == 2 else b[0]))
    if d1 < d0:
        d1 = d1.replace(year=2026)
    return (d1 - d0).days + 1


def _parse_operation(inp: PoolInputs, a: dict, warns: list) -> None:
    """Season, open days and opening hours. The season sets the model months, days and hours are kept as data."""
    se = a.get("q4_season") or {}
    if se.get("year_round"):
        inp.season_year_round = True
        inp.operating_weeks = 52.0
    elif se.get("from") and se.get("to"):
        f, t_ = _md(se["from"]), _md(se["to"])
        if f and t_:
            inp.season_year_round, inp.season_from, inp.season_to = False, f, t_
            inp.operating_weeks = round(min(_span_days(f, t_), 365) / 7.0, 1)
    so = a.get("q4_season_outdoor") or {}
    if so.get("year_round"):
        inp.outdoor_year_round, inp.outdoor_weeks = True, 52.0
    elif so.get("from") and so.get("to"):
        f, t_ = _md(so["from"]), _md(so["to"])
        if f and t_:
            inp.outdoor_year_round, inp.outdoor_from, inp.outdoor_to = False, f, t_
            inp.outdoor_weeks = round(min(_span_days(f, t_), 365) / 7.0, 1)
    days = [d for d in (a.get("q4_days") or []) if d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")]
    inp.open_days = days or None
    hrs = a.get("q4_hours") or {}
    for part, attr in (("weekday", "hours_weekday"), ("weekend", "hours_weekend")):
        pair = hrs.get(part)
        if pair and len(pair) == 2:
            o, c = _hour(pair[0]), _hour(pair[1])
            if o is not None and c is not None:
                if c > o:
                    setattr(inp, attr, (o, c))
                else:
                    warns.append({"code": "hours_invalid", "value": part})
    if inp.open_days and (inp.hours_weekday or inp.hours_weekend):
        total = 0.0
        for d in inp.open_days:
            h = inp.hours_weekend if d in ("sat", "sun") else inp.hours_weekday
            if h:
                total += h[1] - h[0]
        inp.hours_per_week = total or None


def from_answers(answers: dict, params: Params) -> Parsed:
    prov: dict[str, str] = {}
    warns: list[dict] = []
    a = answers or {}

    inp = PoolInputs()
    inp.name = str(a.get("q1_name") or "").strip()
    inp.city = str(a.get("q1_city") or "").strip()
    inp.postcode = str(a.get("q1_postcode") or "").strip()
    inp.pool_type = a.get("q1_pool_type") or "indoor"
    inp.legal_form = a.get("q1_legal_form") or "municipal_operation"

    # ---- basins -----------------------------------------------------------
    basin_defaults = params.central("basin_defaults")
    setpoints_entered = True
    for row in a.get("q3_basins") or []:
        if not isinstance(row, dict):
            continue
        b = Basin(
            type=row.get("type") or "lap",
            length_m=_pos(row.get("length_m")),
            width_m=_pos(row.get("width_m")),
            environment=row.get("environment") if row.get("environment") in ("indoor", "outdoor") else None,
            depth_min_m=_pos(row.get("depth_min_m")),
            depth_max_m=_pos(row.get("depth_max_m")),
            setpoint_c=_num(row.get("setpoint_c")),
            volume_known_m3=_pos(row.get("volume_known_m3")),
        )
        if b.area_m2() <= 0:
            continue
        if b.area_m2() > 5000 or (b.length_m or 0) > 150 or (b.width_m or 0) > 100:
            warns.append({"code": "basin_size", "value": b.area_m2()})
        if b.depth_min_m and b.depth_max_m and b.depth_max_m < b.depth_min_m:
            warns.append({"code": "basin_depth_order"})
            b.depth_min_m, b.depth_max_m = b.depth_max_m, b.depth_min_m
        if b.setpoint_c is None:
            b.setpoint_c = float(basin_defaults.get(b.type, 28.0))
            setpoints_entered = False
        inp.basins.append(b)
    if not inp.basins:
        warns.append({"code": "no_basins"})
    prov["water_surface"] = "entered" if inp.basins else "default"
    prov["setpoints"] = "entered" if inp.basins and setpoints_entered else "default"
    if inp.pool_type == "combined" and inp.basins and not any(b.environment == "outdoor" or b.type == "outdoor" for b in inp.basins):
        warns.append({"code": "combined_no_outdoor"})
    vols = [b.volume_m3() for b in inp.basins]
    if inp.basins and all(not est for _, est in vols):
        prov["water_volume"] = "entered"
    elif inp.basins:
        prov["water_volume"] = "estimated"
    else:
        prov["water_volume"] = "default"

    # ---- hall, operation ----------------------------------------------------
    area = _pos(a.get("q3_hall_area"))
    if area is None and inp.water_surface_m2() > 0:
        area = inp.water_surface_m2() * float(params.central("default_hall_area_factor"))
        prov["hall_area"] = "estimated"
    else:
        prov["hall_area"] = "entered" if area else "default"
    inp.hall_area_m2 = area

    inp.air_setpoint_c = _num(a.get("q6_air_setpoint"))
    _parse_operation(inp, a, warns)
    prov["opening_hours"] = "entered" if (inp.season_year_round is not None or inp.season_from) and inp.open_days and (
        inp.hours_weekday or inp.hours_weekend) else "default"

    vent = a.get("q6_ventilation")
    if vent == "mech_hr":
        inp.heat_recovery = True
        prov["heat_recovery"] = "entered"
    elif vent in ("mech_no_hr", "natural"):
        inp.heat_recovery = False
        prov["heat_recovery"] = "entered"
    else:
        inp.heat_recovery = None
        prov["heat_recovery"] = "default"

    # ---- heat supply and consumption ---------------------------------------
    inp.heat_sources = list(a.get("q7_sources") or [])
    inp.main_source = a.get("q7_main_source")
    inp.main_capacity_kw = _pos(a.get("q7_main_capacity_kw"))

    cons = a.get("q8_consumption") or {}
    for carrier in CARRIERS:
        item = cons.get(carrier) or {}
        kwh = to_kwh(item.get("value"), item.get("unit"), carrier, params)
        if kwh:
            inp.consumption_kwh[carrier] = kwh
    elec = cons.get("electricity") or {}
    inp.electricity_kwh = to_kwh(elec.get("value"), elec.get("unit"), "electricity", params)
    prov["heat_consumption"] = "entered" if inp.consumption_kwh else "default"
    prov["electricity_consumption"] = "entered" if inp.electricity_kwh else "default"

    inp.heat_cost_eur = _pos(a.get("q8_heat_cost_eur"))
    inp.elec_cost_eur = _pos(a.get("q8_elec_cost_eur"))
    inp.costs_incl_vat = a.get("q8_costs_incl_vat")
    prov["heat_price"] = "entered" if inp.heat_cost_eur and inp.consumption_kwh else "default"
    prov["electricity_price"] = "entered" if inp.elec_cost_eur and inp.electricity_kwh else "default"

    # ---- optional detail ------------------------------------------------------
    inp.boiler_age_years = _pos(a.get("r_boiler_age"))
    eta = _pos(a.get("r_boiler_eta"))
    inp.boiler_eta = eta / 100.0 if eta and eta > 1.5 else eta
    if inp.boiler_eta is not None and not (0.5 <= inp.boiler_eta <= 1.1):
        warns.append({"code": "boiler_eta_range", "value": inp.boiler_eta})
        inp.boiler_eta = None
    prov["boiler_efficiency"] = "entered" if inp.boiler_eta else "default"

    inp.grid_kw = _pos(a.get("r_grid_kw"))
    inp.dh_contract_binding = a.get("r_dh_contract")
    inp.hp_source = a.get("r_hp_source") or "air"
    # ---- visitors and shower water (hot water demand of the model) -----------------
    inp.visitors_weekday = _pos(a.get("q4_visitors_weekday"))
    inp.visitors_weekend = _pos(a.get("q4_visitors_weekend"))
    inp.visitors_year = _pos(a.get("q4_visitors_year"))
    inp.dhw_supply = a.get("q4_dhw_supply") if a.get("q4_dhw_supply") in ("central", "separate", "none") else "central"
    litres = _pos(a.get("r_shower_litres"))
    inp.shower_litres = litres if litres and 5.0 <= litres <= 200.0 else None
    if litres and inp.shower_litres is None:
        warns.append({"code": "shower_litres_range", "value": litres})
    if a.get("q4_dhw_tank") == "yes" and inp.dhw_supply == "central":
        size = _pos(a.get("q4_dhw_tank_size"))
        if size:
            m3 = size / 1000.0 if a.get("q4_dhw_tank_unit", "l") == "l" else size
            if 0.05 <= m3 <= 100.0:
                inp.dhw_tank_m3 = m3
            else:
                warns.append({"code": "dhw_tank_range", "value": m3})
        else:
            warns.append({"code": "dhw_tank_missing"})
    _, vsrc = inp.annual_visitors()
    prov["visitors"] = {"entered": "entered", "derived": "estimated"}.get(vsrc, "default")
    inp.buffer_m3 = _pos(a.get("q9b_buffer_m3"))
    inp.pv_kwp = _pos(a.get("q9b_pv_kwp"))

    # ---- flexibility tolerance ----------------------------------------------
    inp.allowed_change_k = _num(a.get("q11_change"))
    hold = _num(a.get("q11_hold"))
    inp.hold_hours = hold if hold and hold > 0 else None

    # ---- consistency warnings -------------------------------------------------
    if inp.pool_type == "open_air":
        warns.append({"code": "open_air"})
    if inp.main_source == "heat_pump" or (
        "heat_pump" in inp.heat_sources and inp.main_source in (None, "heat_pump")
    ):
        warns.append({"code": "existing_heat_pump"})
    if inp.dh_contract_binding == "yes":
        warns.append({"code": "dh_binding"})
    if inp.allowed_change_k == 0:
        warns.append({"code": "no_tolerance"})

    return Parsed(inputs=inp, provenance=prov, warnings=warns)
