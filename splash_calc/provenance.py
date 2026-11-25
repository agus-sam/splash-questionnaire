"""Central provenance resolver.

Every input that enters the calculation gets one record: where does the value come from?
Hierarchy (highest first): measured > operator estimate > derived from operator inputs >
documented SPLASH default or benchmark > parameter-file fallback. A valid operator value is
never replaced. This module only describes; it does not change any number.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .inputs import TRACKED_FIELDS, Parsed

# six classes shown to the user
ENTERED, ESTIMATED_OP, CALCULATED, DEFAULT, BENCHMARK, MODEL = (
    "entered", "estimated_op", "calculated", "default", "benchmark", "model")
CLASSES = (ENTERED, ESTIMATED_OP, CALCULATED, DEFAULT, BENCHMARK, MODEL)
OPERATOR_CLASSES = (ENTERED, ESTIMATED_OP, CALCULATED)

# fields whose fallback is a benchmark (UBA / literature) rather than a SPLASH default
BENCHMARK_FIELDS = {"heat_consumption", "electricity_consumption", "heat_price", "electricity_price",
                    "boiler_efficiency"}
# fields that are only ever derived when not entered
DERIVED_FIELDS = {"water_volume", "hall_area"}

LABEL = {
    "water_surface": {"de": "Wasserfläche", "en": "Water surface"},
    "water_volume": {"de": "Wasservolumen", "en": "Water volume"},
    "setpoints": {"de": "Beckentemperaturen", "en": "Basin temperatures"},
    "hall_area": {"de": "Hallenfläche", "en": "Hall floor area"},
    "opening_hours": {"de": "Betriebszeiten", "en": "Operating hours"},
    "heat_recovery": {"de": "Wärmerückgewinnung", "en": "Heat recovery"},
    "heat_consumption": {"de": "Wärmeverbrauch", "en": "Heat consumption"},
    "electricity_consumption": {"de": "Stromverbrauch", "en": "Electricity consumption"},
    "heat_price": {"de": "Wärmepreis", "en": "Heat price"},
    "electricity_price": {"de": "Strompreis", "en": "Electricity price"},
    "boiler_efficiency": {"de": "Kesselwirkungsgrad", "en": "Boiler efficiency"},
    "visitors": {"de": "Besucherzahl (Warmwasser)", "en": "Visitors (hot water)"},
}
EXTRA_LABEL = {
    "tolerance": {"de": "Zulässige Temperaturerhöhung", "en": "Allowed temperature rise"},
    "grid": {"de": "Netzanschlussleistung", "en": "Grid connection"},
    "buffer": {"de": "Pufferspeicher", "en": "Buffer tank"},
    "dhw_tank": {"de": "Warmwasserspeicher", "en": "Hot water tank"},
    "hp_source": {"de": "Wärmequelle Wärmepumpe", "en": "Heat pump source"},
    "demand": {"de": "Wärmebedarf (Modell)", "en": "Heat demand (model)"},
    "weather": {"de": "Wetter (TMY)", "en": "Weather (TMY)"},
}
BADGE = {
    ENTERED: {"de": "Ihre Angabe", "en": "Based on your input"},
    ESTIMATED_OP: {"de": "Ihre Schätzung", "en": "Your estimate"},
    CALCULATED: {"de": "Aus Ihren Angaben berechnet", "en": "Calculated from your inputs"},
    DEFAULT: {"de": "SPLASH-Standardwert", "en": "SPLASH default used"},
    BENCHMARK: {"de": "Benchmark (UBA) angewendet", "en": "UBA benchmark applied"},
    MODEL: {"de": "Modellgeneriert", "en": "Model-generated"},
}
CLASS_NAME = {
    ENTERED: {"de": "Vom Betreiber eingegeben", "en": "Entered by operator"},
    ESTIMATED_OP: {"de": "Vom Betreiber geschätzt", "en": "Estimated by operator"},
    CALCULATED: {"de": "Aus Betreiberangaben berechnet", "en": "Calculated from operator inputs"},
    DEFAULT: {"de": "SPLASH-Standardwert", "en": "SPLASH default"},
    BENCHMARK: {"de": "Benchmark-basierte Schätzung", "en": "Benchmark-based estimate"},
    MODEL: {"de": "Modellgeneriert", "en": "Model-generated"},
}
PDF_GROUP = {
    ENTERED: "operator", ESTIMATED_OP: "operator", CALCULATED: "derived",
    DEFAULT: "splash", BENCHMARK: "benchmark", MODEL: "derived",
}


@dataclass
class Item:
    key: str
    cls: str
    value: float | str | None = None
    unit: str = ""

    def label(self, lg: str) -> str:
        return (LABEL.get(self.key) or EXTRA_LABEL.get(self.key, {"de": self.key, "en": self.key}))[lg]

    def badge(self, lg: str) -> str:
        return BADGE[self.cls][lg]


def classify(field: str, raw: str, estimated_flag: bool) -> str:
    """Map the legacy three-way value to one of the six classes."""
    if raw == "entered":
        return ESTIMATED_OP if estimated_flag and field in {
            "heat_consumption", "electricity_consumption", "heat_price", "electricity_price"} else ENTERED
    if raw == "estimated":
        return CALCULATED
    if field in DERIVED_FIELDS:
        return DEFAULT
    return BENCHMARK if field in BENCHMARK_FIELDS else DEFAULT


def resolve(parsed: Parsed, answers: dict) -> dict[str, Item]:
    """One record per tracked input plus the optional ones used by the scenarios."""
    inp = parsed.inputs
    flag = answers.get("q8_quality") == "estimated"
    items: dict[str, Item] = {}
    vals = {
        "water_surface": (inp.water_surface_m2(), "m²"),
        "water_volume": (sum(b.volume_m3()[0] for b in inp.basins), "m³"),
        "hall_area": (inp.hall_area_m2, "m²"),
        "heat_consumption": (sum(inp.consumption_kwh.values()) or None, "kWh/a"),
        "electricity_consumption": (inp.electricity_kwh, "kWh/a"),
        "boiler_efficiency": (inp.boiler_eta, ""),
        "visitors": (inp.annual_visitors()[0], "persons/a"),
    }
    for f in TRACKED_FIELDS:
        raw = parsed.provenance.get(f, "default")
        v, u = vals.get(f, (None, ""))
        items[f] = Item(f, classify(f, raw, flag), v, u)
    items["tolerance"] = Item("tolerance", ENTERED if inp.allowed_change_k is not None else DEFAULT,
                              inp.allowed_change_k, "K")
    items["grid"] = Item("grid", ENTERED if inp.grid_kw else DEFAULT, inp.grid_kw, "kW")
    items["buffer"] = Item("buffer", ENTERED if inp.buffer_m3 else DEFAULT, inp.buffer_m3, "m³")
    items["dhw_tank"] = Item("dhw_tank", ENTERED if inp.dhw_tank_m3 else DEFAULT, inp.dhw_tank_m3, "m³")
    items["hp_source"] = Item("hp_source", ENTERED if answers.get("r_hp_source") else DEFAULT, inp.hp_source)
    items["demand"] = Item("demand", MODEL, None, "kWh/a")
    items["weather"] = Item("weather", DEFAULT, "TMY")
    return items


def counts(items: dict[str, Item]) -> dict[str, int]:
    out = {c: 0 for c in CLASSES}
    for it in items.values():
        out[it.cls] += 1
    return out


def completeness(items: dict[str, Item]) -> tuple[int, int]:
    """Operator-supported tracked inputs out of all tracked inputs."""
    tracked = [items[f] for f in TRACKED_FIELDS if f in items]
    return sum(1 for i in tracked if i.cls in OPERATOR_CLASSES), len(tracked)


def as_records(items: dict[str, Item]) -> list[dict]:
    return [asdict(i) for i in items.values()]
