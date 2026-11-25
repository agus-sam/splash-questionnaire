from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field

import numpy as np

from .. import builder
from ..config import HP_SCENARIOS, Settings
from ..data_loader import SplashData
from ..preprocessing import DAY_TYPES, Timeline, build_units, occupancy_array, weather_arrays
from .dhw import DhwModel, build_dhw

log = logging.getLogger(__name__)
TECHNOLOGIES = ("heat_pump", "resistive")
TECH_SOURCE = {"heat_pump": "heat_pump_plant", "resistive": "electric_boiler_plant"}


@dataclass
class BasinModel:
    basin_id: int
    uid: str
    facility_id: int
    environment: str
    size_class: str
    area_m2: float
    volume_m3: float
    depth_m: float
    t_min: float
    t_max: float
    c_kwh_per_k: float
    active: np.ndarray
    a_kw: np.ndarray
    rate: np.ndarray
    occupancy: np.ndarray
    sink_c: float
    phys: object = field(repr=False, default=None)
    t_air: float | None = None
    flags: dict = field(default_factory=dict)

    @property
    def cap_kwh(self) -> float:
        return self.c_kwh_per_k * (self.t_max - self.t_min)

    def demand_kw(self) -> np.ndarray:
        return np.maximum(self.a_kw, 0.0)

    def loss_at(self, temp_c: float, sl: slice | None = None) -> np.ndarray:
        q = self.phys.net_loss_kw_per_m2(temp_c, self.t_air, sl) * self.area_m2
        act = self.active[:-1] if sl is None else self.active[sl.start : sl.stop]
        return q * act

    def temp_c(self, e_kwh: np.ndarray) -> np.ndarray:
        act = self.active[: len(e_kwh)]
        return np.where(act > 0, self.t_min + e_kwh / self.c_kwh_per_k, np.nan)


@dataclass
class HallModel:
    hall_id: str
    archetype: str
    area_m2: float
    t_air_c: float
    sensible_kw: np.ndarray
    latent_diag_kw: np.ndarray
    fan_kw: np.ndarray | None
    sink_c: float


@dataclass
class FacilityModel:
    facility_id: int
    name: str
    badtyp: str
    model_type: str
    zone: str
    wzone: str
    t_ext: np.ndarray
    basins: list[BasinModel]
    hall: HallModel | None
    avail: np.ndarray
    circuits: dict[str, np.ndarray] = field(default_factory=dict)
    basin_circuit: list[str] = field(default_factory=list)
    hall_circuit: str | None = None
    design: dict = field(default_factory=dict)
    flags: dict = field(default_factory=dict)
    dhw: DhwModel | None = None
    dhw_circuit: str | None = None

    @property
    def n_basins(self) -> int:
        return len(self.basins)

    @property
    def T(self) -> int:
        return len(self.t_ext)

    def hall_kw(self) -> np.ndarray:
        return self.hall.sensible_kw if self.hall is not None else np.zeros(self.T)

    def dhw_kw(self) -> np.ndarray:
        return self.dhw.demand_kw if self.dhw is not None else np.zeros(self.T)

    @property
    def has_load(self) -> bool:
        """True if the facility has a load besides its basins: the hall air or the hot water for bathers."""
        return self.hall is not None or self.dhw is not None

    def load_kw(self) -> np.ndarray:
        """The load served next to the basins (hall air plus hot water for bathers). No storage."""
        return self.hall_kw() + self.dhw_kw()

    def cop_load(self) -> np.ndarray:
        """COP of the load block. Heat-weighted over the hall circuit and the hot water circuit, so that a pro rata
        sharing of a capacity shortage gives the right electricity."""
        if self.dhw is None:
            return self.cop_hall()
        h, d = self.hall_kw(), self.dhw.demand_kw
        cop_h = self.cop_hall() if self.hall is not None else np.ones(self.T)
        cop_d = self.circuits[self.dhw_circuit]
        tot = h + d
        el = h / cop_h + d / cop_d
        return np.where(tot > 1e-12, tot / np.maximum(el, 1e-12), cop_d)

    def basin_demand_kw(self) -> np.ndarray:
        return np.sum([b.demand_kw() for b in self.basins], axis=0)

    def total_demand_kw(self) -> np.ndarray:
        return self.basin_demand_kw() + self.load_kw()

    def cop_basin(self, i: int) -> np.ndarray:
        return self.circuits[self.basin_circuit[i]]

    def cop_hall(self) -> np.ndarray:
        return self.circuits[self.hall_circuit] if self.hall_circuit else np.ones(self.T)

    def electricity_for(self, q_basin: np.ndarray, q_hall: np.ndarray) -> np.ndarray:
        el = np.zeros(self.T)
        for i in range(self.n_basins):
            el += q_basin[i] / self.cop_basin(i)
        if self.has_load:
            el += q_hall / self.cop_load()
        return el


def _hp_cop(hp, t_sink_k, t_air_c: np.ndarray, cop_min: float, cop_max: float) -> np.ndarray:
    T = len(t_air_c)
    t_src = (t_air_c if hp.source == "outdoor_air" else np.full(T, hp.source_temp_c)) + hp.source_offset_k + 273.15
    lift = np.maximum(t_sink_k - t_src, 1.0)
    cop = np.clip(hp.carnot_fraction * t_sink_k / lift, cop_min, cop_max)
    if hp.aux_el_frac_of_heat > 0:
        cop = 1.0 / (1.0 / cop + hp.aux_el_frac_of_heat)
    return cop


def _model_type(envs: set[str]) -> str:
    return "Kombibad" if envs == {"indoor", "outdoor"} else ("Hallenbad" if envs == {"indoor"} else "Freibad")


def _availability(data: SplashData, s: Settings, tl: Timeline, basins: list[BasinModel], typ: dict[str, str]) -> np.ndarray:
    pc = s.facility.plant
    if pc.availability == "always":
        return np.ones(tl.n)
    open_any = np.zeros(tl.n, dtype=bool)
    for key in {typ[b.uid] for b in basins}:
        o = data.occupancy[data.occupancy["typology_key"] == key]
        cube = np.zeros((len(DAY_TYPES), 12, 24))
        di = o["day_type"].map({k: i for i, k in enumerate(DAY_TYPES)}).to_numpy()
        cube[di, o["month"].to_numpy() - 1, o["hour"].to_numpy()] = o["open_flag"].to_numpy()
        open_any |= cube[tl.day_type, tl.month - 1, tl.hour_local] > 0
    av = open_any.copy()
    for k in range(1, pc.preheat_hours + 1):
        av[:-k] |= open_any[k:]
    return av.astype(float)


def _cop(hp, sink_c: float, t_ext: np.ndarray, cmin: float, cmax: float) -> np.ndarray:
    return _hp_cop(hp, sink_c + 273.15, t_ext, cmin, cmax)


def build_facility_models(data: SplashData, s: Settings, tl: Timeline, facility_ids=None) -> dict[int, FacilityModel]:
    if facility_ids is not None:
        keep = set(int(f) for f in facility_ids)
        d = copy.copy(data)
        d.basins = data.basins[data.basins["facility_id"].isin(keep)].reset_index(drop=True)
    else:
        d = data
    units = build_units(d, s, tl)
    prob = builder.build_problem(d, s, tl, units)
    bas = d.basins.set_index("basin_id")
    fac = d.facilities.set_index("facility_id")
    hp = s.system.heat_pump
    out: dict[int, FacilityModel] = {}
    by_fac: dict[int, list[int]] = {}
    for i, u in enumerate(prob.units):
        by_fac.setdefault(int(bas.loc[int(u.uid[1:]), "facility_id"]), []).append(i)
    dhw = build_dhw(d, s, tl, sorted(by_fac)) if s.facility.dhw.enabled else {}
    for fid, idx in sorted(by_fac.items()):
        zone_row = fac.loc[fid]
        wzone = str(zone_row["weather_zone_id"])
        t_ext = weather_arrays(d, wzone, tl)["t_a"]
        bms: list[BasinModel] = []
        typ: dict[str, str] = {}
        for i in idx:
            u, fu = units[i], prob.units[i]
            br = bas.loc[int(u.uid[1:])]
            t_air = None
            if u.environment == "indoor":
                h = prob.halls[u.hall_key]
                t_air = float(h.t_air_a)
            mid = 0.5 * (u.t_min + u.t_max)
            sink = mid + hp.sink_offset_k
            occ = occupancy_array(d, u.typology_key, tl, s.physics.occupancy_scale)
            bms.append(
                BasinModel(
                    basin_id=int(u.uid[1:]),
                    uid=u.uid,
                    facility_id=fid,
                    environment=u.environment,
                    size_class=u.size_class,
                    area_m2=u.area_m2,
                    volume_m3=u.volume_m3,
                    depth_m=u.depth_m,
                    t_min=u.t_min,
                    t_max=u.t_max,
                    c_kwh_per_k=fu.c_kwh_per_k,
                    active=fu.active_frac.copy(),
                    a_kw=fu.a_kw.copy(),
                    rate=fu.rate.copy(),
                    occupancy=occ,
                    sink_c=sink,
                    phys=fu.phys,
                    t_air=t_air,
                    flags={
                        "area_source": br.get("area_source"),
                        "depth_source": br.get("depth_source"),
                        "perimeter_source": br.get("perimeter_source"),
                        "environment_source": br.get("environment_source"),
                    },
                )
            )
            typ[u.uid] = u.typology_key
        envs = {b.environment for b in bms}
        hall = None
        hkeys = sorted({prob.units[i].hall_key for i in idx if prob.units[i].hall_key})
        if hkeys:
            assert len(hkeys) == 1, f"facility {fid} has several halls {hkeys}"
            hi = prob.halls[hkeys[0]]
            sens = np.maximum(hi.air_sens_kw_per_k * (hi.t_air_a - hi.t_ext), 0.0)
            hall = HallModel(
                hall_id=hkeys[0],
                archetype=hi.archetype,
                area_m2=hi.area_m2,
                t_air_c=float(hi.t_air_a),
                sensible_kw=sens,
                latent_diag_kw=_latent_diag(hi, bms),
                fan_kw=_fan_kw(s, hi),
                sink_c=s.system.air_side.sink_c,
            )
        fm = FacilityModel(
            facility_id=fid,
            name=str(zone_row["name"]),
            badtyp=str(zone_row["badtyp"]),
            model_type=_model_type(envs),
            zone=str(zone_row["curtail_zone_id"]),
            wzone=wzone,
            t_ext=t_ext,
            basins=bms,
            hall=hall,
            avail=_availability(d, s, tl, bms, typ),
            dhw=dhw.get(fid),
            flags={
                "temporarily_closed": int(zone_row["temporarily_closed_flag"]),
                "season_applies_to": str(zone_row["season_applies_to"]),
                "season": f"{int(zone_row['season_start_month'])}-{int(zone_row['season_end_month'])}",
            },
        )
        _build_circuits(fm, s, hp, TECHNOLOGIES[0])
        out[fid] = fm
    log.info("%d facilities, %d basins", len(out), sum(f.n_basins for f in out.values()))
    return out


def _latent_diag(hi, bms: list[BasinModel]) -> np.ndarray:
    from ..physics import hall_air as ha

    m = np.zeros(len(hi.t_ext))
    for b in bms:
        if b.environment == "indoor":
            m += b.phys.evap_kg_s_per_m2(b.t_min, b.t_air) * b.area_m2 * b.active[:-1]
    arch = hi.arch
    per_m2 = ha.dehumidification_load_kw_per_m2(
        m / max(hi.area_m2, 1e-9), np.full(len(m), hi.t_air_a), hi.rh_air_pct, hi.t_ext, hi.rh_ext, hi.p_tot, arch
    )
    return per_m2 * hi.area_m2


def _fan_kw(s: Settings, hi) -> np.ndarray | None:
    sfp = s.facility.hvac.fan_sfp_kw_per_m3_s
    if sfp is None:
        return None
    flow_m3_s = hi.arch.air_mass_flow_per_m2() * hi.area_m2 / 1.2
    return np.full(len(hi.t_ext), sfp * flow_m3_s)


def _build_circuits(fm: FacilityModel, s: Settings, hp, tech: str = "heat_pump") -> None:
    cfg = s.facility.plant.configuration
    a = s.system.air_side
    sink: dict[str, float] = {}
    for b in fm.basins:
        c = f"basin_{b.environment}"
        sink[c] = max(sink.get(c, -1e9), b.sink_c)
    if fm.hall is not None:
        if a.heater == "same_as_pool":
            fm.hall_circuit = "basin_indoor"
        else:
            sink["hall_coil"] = a.sink_c
            fm.hall_circuit = "hall_coil"
    if fm.dhw is not None:
        sink["dhw"] = float(fm.dhw.sink_c)
    if tech == "resistive":
        eta = float(s.system.p2h_efficiency) if s.system.p2h_efficiency is not None else 1.0
        fm.circuits = {c: np.full(fm.T, eta) for c in sink}
    elif cfg == "single_supply_temperature":
        top = max(sink.values())
        cop = _cop(hp, top, fm.t_ext, hp.cop_min, hp.cop_max)
        fm.circuits = {c: cop for c in sink}
    else:
        fm.circuits = {
            c: _cop(hp, t, fm.t_ext, a.cop_min if c == "hall_coil" else hp.cop_min, a.cop_max if c == "hall_coil" else hp.cop_max)
            for c, t in sink.items()
        }
    fm.dhw_circuit = "dhw" if fm.dhw is not None else None
    fm.basin_circuit = [f"basin_{b.environment}" for b in fm.basins]
    fm.flags["circuit_sink_c"] = dict(sink)


def set_technology(fms: dict[int, FacilityModel], s: Settings, tech: str) -> None:
    if tech not in TECHNOLOGIES:
        raise ValueError(f"technology must be in {TECHNOLOGIES}")
    for fm in fms.values():
        _build_circuits(fm, s, s.system.heat_pump, tech)
        fm.flags["technology"] = tech
        design_load(fm, s)


def design_load(fm: FacilityModel, s: Settings) -> dict:
    sz = s.facility.sizing
    temp = (lambda b: b.t_min) if sz.design_basin_temp == "t_min" else (lambda b: b.t_max)
    per_basin = [np.maximum(b.loss_at(temp(b)), 0.0) for b in fm.basins]
    dh = s.facility.dhw
    dhw_design = np.zeros(fm.T)
    if fm.dhw is not None and dh.include_in_sizing:
        k = int(dh.sizing_smooth_h)
        dhw_design = np.convolve(fm.dhw.demand_kw, np.ones(k) / k)[: fm.T]
    series = np.sum(per_basin, axis=0) + fm.hall_kw() + dhw_design
    operating = np.any([b.active[:-1] > 0 for b in fm.basins], axis=0)
    ser = series[operating] if operating.any() else series
    q = float(np.percentile(ser, sz.percentile))

    cand = np.flatnonzero(operating & (series >= q - 1e-9))
    t_star = int(cand[0]) if len(cand) else int(np.argmax(series))

    parts = {}
    for i, b in enumerate(fm.basins):
        parts.setdefault(fm.basin_circuit[i], 0.0)
        parts[fm.basin_circuit[i]] += per_basin[i][t_star]
    if fm.hall is not None:
        parts[fm.hall_circuit] = parts.get(fm.hall_circuit, 0.0) + fm.hall_kw()[t_star]
    if dhw_design.max() > 0.0:
        parts[fm.dhw_circuit] = parts.get(fm.dhw_circuit, 0.0) + dhw_design[t_star]
    tot = sum(parts.values())
    el = sum(v / fm.circuits[c][t_star] for c, v in parts.items())
    cop_design = tot / el if el > 0 else 1.0
    peaks = [float(p.max()) for p in per_basin]
    d = {
        "q_design_kw": q,
        "q_design_basins_kw": float(np.sum([p[t_star] for p in per_basin])),
        "q_design_hall_kw": float(fm.hall_kw()[t_star]),
        "q_design_dhw_kw": float(dhw_design[t_star]),
        "design_hour": t_star,
        "cop_design": float(cop_design),
        "sum_individual_basin_peaks_kw": float(np.sum(peaks)),
        "coincidence_factor": q / max(float(np.sum(peaks)) + float(fm.hall_kw().max()) + float(dhw_design.max()), 1e-9),
        "basin_peaks_kw": peaks,
        "method": f"coincident p{sz.percentile:g} at {sz.design_basin_temp}",
    }
    fm.design = d
    return d


def plant_capacity_kw(fm: FacilityModel, scenario: str) -> tuple[float, float]:
    q = HP_SCENARIOS[scenario] * fm.design["q_design_kw"]
    return q, q / fm.design["cop_design"]
