from __future__ import annotations

import typing
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

import yaml

WALL_MODES = ("follow_air_offset", "fixed")
HP_SOURCES = ("outdoor_air", "constant")
PLANT_CONFIGS = ("dual_temperature_circuit", "single_supply_temperature")
HP_AVAIL = ("always", "public_hours")
HP_SCENARIOS = {"HP75": 0.75, "HP100": 1.00, "HP125": 1.25}
ZONE_MODES = ("hysteresis_addon", "hysteresis_replace", "hysteresis_optimised")
OPT_SIZE = "OPT"
FAC_TECHNOLOGIES = ("heat_pump", "resistive")


class ConfigError(ValueError):
    pass


@dataclass
class TimeWindow:
    start: str | None = None
    end: str | None = None


@dataclass
class RunCfg:
    run_id: str = "auto"
    output_dir: str = "results"
    time_window: TimeWindow = field(default_factory=TimeWindow)
    log_level: str = "INFO"


@dataclass
class DataCfg:
    root: str = "data"


@dataclass
class PhysicsCfg:
    outdoor: dict[str, Any] = field(default_factory=dict)
    indoor: dict[str, Any] = field(default_factory=dict)
    occupancy_scale: float = 1.0


@dataclass
class HallAirCfg:
    air_temp_c: float | None = None
    rh_pct: float | None = None
    wall_mode: str = "follow_air_offset"
    hall_volume_m3_per_m2_water: float = 12.0


@dataclass
class HeatPumpCfg:
    carnot_fraction: float = 0.35
    sink_offset_k: float = 10.0
    source: str = "outdoor_air"
    source_temp_c: float = 10.0
    source_offset_k: float = -5.0
    cop_min: float = 1.5
    cop_max: float = 4.5
    aux_el_frac_of_heat: float = 0.0


@dataclass
class AirSideCfg:
    heater: str = "heat_pump"
    sink_c: float = 40.0
    cop_min: float = 1.5
    cop_max: float = 4.0


@dataclass
class SystemCfg:
    heat_pump: HeatPumpCfg = field(default_factory=HeatPumpCfg)
    air_side: AirSideCfg = field(default_factory=AirSideCfg)
    p2h_efficiency: float = 1.0
    band_shift_k: float = 0.0
    band_width_k: float | None = None


@dataclass
class CurtailmentCfg:
    access_share: Any = None


@dataclass
class SolverCfg:
    name: str = "highs"
    time_limit_s: float = 900.0
    verbose: bool = False


@dataclass
class InvestmentCfg:
    discount_rate: float = 0.05
    capex_subsidy_pct: float = 0.0


@dataclass
class EconomicsCfg:
    co2_price_eur_per_t: float = 65.0
    include_co2_cost: bool = True
    grid_price_eur_per_mwh: float | None = None
    curtailed_price_eur_per_mwh: float | None = None
    price_overrides: dict[str, float] = field(default_factory=dict)
    reference_source: str = "facility_mix"
    capex_overrides: dict[str, float] = field(default_factory=dict)
    investment: InvestmentCfg = field(default_factory=InvestmentCfg)


@dataclass
class OutputCfg:
    figures: bool = True
    dpi: int = 150


@dataclass
class PlantCfg:
    configuration: str = "dual_temperature_circuit"
    availability: str = "always"
    preheat_hours: int = 0
    shortage_priority: str = "hall"


@dataclass
class SizingCfg:
    percentile: float = 100.0
    design_basin_temp: str = "t_min"
    primary_scenario: str = "HP100"
    scenarios: list[str] = field(default_factory=lambda: ["HP100"])


@dataclass
class HvacCfg:
    fan_sfp_kw_per_m3_s: float | None = None


@dataclass
class FacilityEconomicsCfg:
    include_controller: bool = True


@dataclass
class OptSizingCfg:
    min_size_factor: float = 0.0
    max_size_factor: float = 3.0
    tail_h: Any = "auto"
    max_tail_h: int = 168
    allow_zero: bool = True
    time_limit_s: float | None = None


@dataclass
class DhwCfg:
    """Hot water for bathers (showers), proportional to the number of visitors.

    Per visitor, the shower water demand is `shower_water_m3_per_visitor` at `t_mix_c`, heated from the monthly mains
    temperature. Visitors per hour follow from the occupancy profiles (Little's law with `stay_in_water_h`) unless a
    facility has `annual_visitors` in data/inputs/dhw_facility.csv. All values here are defaults; the per facility table overrides them.
    """

    enabled: bool = False
    shower_water_m3_per_visitor: float = 0.05
    t_mix_c: float = 40.0
    stay_in_water_h: float = 1.0
    loss_share: float = 0.0
    hot_shower_share: float = 1.0
    sink_c: float = 60.0
    include_in_sizing: bool = True
    sizing_smooth_h: int = 1


@dataclass
class FacilityCfg:
    technologies: list[str] = field(default_factory=lambda: ["heat_pump"])
    zone_modes: list[str] = field(default_factory=lambda: ["hysteresis_addon", "hysteresis_replace"])
    facilities: Any = None
    reference_facility: Any = "Campusbad Flensburg"
    sample_facilities: Any = None
    exclude_temporarily_closed: bool = False
    charge_depth: float = 1.0
    hold_margin_k: float = 0.0
    indoor_evaporation: str = "ashrae"
    plant: PlantCfg = field(default_factory=PlantCfg)
    sizing: SizingCfg = field(default_factory=SizingCfg)
    hvac: HvacCfg = field(default_factory=HvacCfg)
    economics: FacilityEconomicsCfg = field(default_factory=FacilityEconomicsCfg)
    optimised_sizing: OptSizingCfg = field(default_factory=OptSizingCfg)
    dhw: DhwCfg = field(default_factory=DhwCfg)


@dataclass
class Settings:
    run: RunCfg = field(default_factory=RunCfg)
    data: DataCfg = field(default_factory=DataCfg)
    physics: PhysicsCfg = field(default_factory=PhysicsCfg)
    hall_air: HallAirCfg = field(default_factory=HallAirCfg)
    system: SystemCfg = field(default_factory=SystemCfg)
    curtailment: CurtailmentCfg = field(default_factory=CurtailmentCfg)
    solver: SolverCfg = field(default_factory=SolverCfg)
    economics: EconomicsCfg = field(default_factory=EconomicsCfg)
    output: OutputCfg = field(default_factory=OutputCfg)
    facility: FacilityCfg = field(default_factory=FacilityCfg)

    @classmethod
    def from_yaml(cls, path: str | Path, overrides: list[str] | None = None) -> "Settings":
        path = Path(path)
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        for item in overrides or []:
            if "=" not in item:
                raise ConfigError(f"override must look like a.b.c=value, got {item!r}")
            key, val = item.split("=", 1)
            _set_path(raw, key.strip().split("."), yaml.safe_load(val))
        s = _build(cls, raw, "settings")
        s.validate()
        s._base_dir = path.resolve().parent
        return s

    @property
    def base_dir(self) -> Path:
        return getattr(self, "_base_dir", Path.cwd())

    def data_root(self) -> Path:
        p = Path(self.data.root)
        return p if p.is_absolute() else (self.base_dir / p).resolve()

    def output_root(self) -> Path:
        p = Path(self.run.output_dir)
        return p if p.is_absolute() else (self.base_dir / p).resolve()

    def to_dict(self) -> dict[str, Any]:
        return _to_plain(self)

    def validate(self) -> None:
        def need(cond: bool, msg: str) -> None:
            if not cond:
                raise ConfigError(msg)

        ha = self.hall_air
        need(ha.wall_mode in WALL_MODES, f"hall_air.wall_mode must be in {WALL_MODES}")
        need(self.physics.occupancy_scale >= 0.0, "physics.occupancy_scale must not be negative")
        need(0 < self.system.p2h_efficiency <= 5, "system.p2h_efficiency invalid")
        hp = self.system.heat_pump
        need(hp.source in HP_SOURCES, f"system.heat_pump.source must be in {HP_SOURCES}")
        need(0 < hp.carnot_fraction <= 1 and 1.0 <= hp.cop_min <= hp.cop_max, "system.heat_pump COP settings invalid")
        need(hp.sink_offset_k >= 0, "system.heat_pump.sink_offset_k must not be negative")
        need(hp.aux_el_frac_of_heat >= 0, "system.heat_pump.aux_el_frac_of_heat must not be negative")
        a = self.system.air_side
        need(a.heater in ("heat_pump", "same_as_pool"), "system.air_side.heater must be heat_pump or same_as_pool")
        need(1.0 <= a.cop_min <= a.cop_max, "system.air_side COP limits invalid")
        need(self.system.band_width_k is None or self.system.band_width_k > 0, "system.band_width_k must be positive or null")
        cs = self.curtailment.access_share
        need(
            cs is None or isinstance(cs, (int, float)) and 0 <= cs <= 1 or isinstance(cs, dict) and all(0 <= v <= 1 for v in cs.values()),
            "curtailment.access_share must be null, a number or a mapping of zone to a share in [0, 1]",
        )
        ec = self.economics
        need(ec.co2_price_eur_per_t >= 0, "economics.co2_price_eur_per_t must not be negative")
        need(all(v >= 0 for v in ec.price_overrides.values()), "economics.price_overrides must not be negative")
        need(ec.grid_price_eur_per_mwh is None or ec.grid_price_eur_per_mwh >= 0, "economics.grid_price_eur_per_mwh invalid")
        need(ec.curtailed_price_eur_per_mwh is None or ec.curtailed_price_eur_per_mwh >= 0, "economics.curtailed_price_eur_per_mwh invalid")
        iv = ec.investment
        need(0.0 <= iv.discount_rate < 1.0, "economics.investment.discount_rate must be in [0, 1)")
        need(0.0 <= iv.capex_subsidy_pct < 1.0, "economics.investment.capex_subsidy_pct must be in [0, 1)")
        fc = self.facility
        need(0.0 < fc.charge_depth <= 1.0, "facility.charge_depth must be in (0, 1]")
        need(fc.hold_margin_k >= 0.0, "facility.hold_margin_k must not be negative")
        need(fc.plant.configuration in PLANT_CONFIGS, f"facility.plant.configuration must be in {PLANT_CONFIGS}")
        need(fc.plant.availability in HP_AVAIL, f"facility.plant.availability must be in {HP_AVAIL}")
        need(fc.plant.shortage_priority in ("hall", "basins"), "facility.plant.shortage_priority must be hall or basins")
        need(
            bool(fc.technologies) and set(fc.technologies) <= set(FAC_TECHNOLOGIES),
            f"facility.technologies must be a non empty subset of {FAC_TECHNOLOGIES}",
        )
        need(
            set(fc.sizing.scenarios) <= set(HP_SCENARIOS) and bool(fc.sizing.scenarios) and fc.sizing.primary_scenario in fc.sizing.scenarios,
            "facility.sizing: scenarios must be a non empty subset of HP_SCENARIOS and contain primary_scenario",
        )
        need(bool(fc.zone_modes), "facility.zone_modes: select at least one scenario besides the baseline")
        need(fc.sizing.design_basin_temp in ("t_min", "t_max") and 0 < fc.sizing.percentile <= 100, "facility.sizing invalid")
        need(set(fc.zone_modes) <= set(ZONE_MODES), f"facility.zone_modes must be in {ZONE_MODES}")
        oz = fc.optimised_sizing
        need(0.0 <= oz.min_size_factor < oz.max_size_factor, "facility.optimised_sizing: 0 <= min_size_factor < max_size_factor")
        need(
            oz.tail_h == "auto" or (isinstance(oz.tail_h, (int, float)) and oz.tail_h >= 0),
            "facility.optimised_sizing.tail_h must be auto or a number of hours",
        )
        need(oz.max_tail_h >= 1, "facility.optimised_sizing.max_tail_h must be positive")
        dh = fc.dhw
        need(dh.shower_water_m3_per_visitor >= 0.0, "facility.dhw.shower_water_m3_per_visitor must not be negative")
        need(0.0 < dh.t_mix_c <= 100.0, "facility.dhw.t_mix_c must be in (0, 100]")
        need(dh.stay_in_water_h > 0.0, "facility.dhw.stay_in_water_h must be positive")
        need(dh.loss_share >= 0.0, "facility.dhw.loss_share must not be negative")
        need(0.0 <= dh.hot_shower_share <= 1.0, "facility.dhw.hot_shower_share must be in [0, 1]")
        need(dh.sink_c >= dh.t_mix_c, "facility.dhw.sink_c must not be below facility.dhw.t_mix_c")
        need(isinstance(dh.sizing_smooth_h, int) and dh.sizing_smooth_h >= 1, "facility.dhw.sizing_smooth_h must be a whole number of hours, at least 1")
        need(self.solver.name in ("highs",), "solver.name supports highs only")

    def access_share(self, zone: str, coordinator: dict | None = None) -> float:
        cs = self.curtailment.access_share
        if isinstance(cs, dict):
            return float(cs.get(zone, 1.0))
        if cs is not None:
            return float(cs)
        if zone == "T6" and coordinator and "T6_hamburg_share" in coordinator:
            return float(coordinator["T6_hamburg_share"])
        return 1.0


def _set_path(d: dict, keys: list[str], val: Any) -> None:
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = val


def _to_plain(obj: Any) -> Any:
    if is_dataclass(obj):
        return {f.name: _to_plain(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, dict):
        return {k: _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_plain(v) for v in obj]
    return obj


def _build(cls: type, raw: Any, where: str) -> Any:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{where} must be a mapping")
    hints = typing.get_type_hints(cls)
    known = {f.name for f in fields(cls)}
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(f"unknown setting(s) in {where}: {sorted(unknown)}; allowed: {sorted(known)}")
    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        if f.name not in raw:
            continue
        val = raw[f.name]
        ftype = hints[f.name]
        if is_dataclass(ftype):
            kwargs[f.name] = _build(ftype, val, f"{where}.{f.name}")
        else:
            kwargs[f.name] = val
    return cls(**kwargs)
