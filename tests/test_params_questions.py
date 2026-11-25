import re
from pathlib import Path

import pytest

from splash_app.i18n import load_questions
from splash_calc import Params

ROOT = Path(__file__).resolve().parent.parent
TYPES = {"text", "number", "single", "multi", "scale", "textarea", "checkbox", "basins", "consumption", "season", "weekdays", "hours"}


# ------------------------------------------------------------------- params
def test_params_all_entries_documented(params):
    for name in params.names():
        e = params.entry(name)
        assert e.get("status") in {"sourced", "project", "illustrative"}, name
        assert e.get("source"), name
        assert e.get("unit") is not None, name
        assert e.get("label_en") and e.get("label_de"), name
        assert ("value" in e) != ("central" in e), name


def test_params_cases_ordered_for_npv(params):
    # pessimistic is the worse case for the operator
    assert params.at_case("pessimistic").get("price_electricity") > params.get("price_electricity")
    assert params.at_case("optimistic").get("hp_capex_per_kw_th") < params.at_case("pessimistic").get("hp_capex_per_kw_th")
    assert params.at_case("pessimistic").get("price_escalation_fuel") < params.at_case("optimistic").get("price_escalation_fuel")


def test_params_overrides_and_pins(params):
    p = params.with_overrides(price_gas=0.2)
    assert p.get("price_gas") == 0.2 and p.at_case("pessimistic").get("price_gas") == 0.2
    assert "price_gas" not in p.uncertain_names()
    pin = params.pinned("price_gas", "optimistic")
    assert pin.get("price_gas") == params.entry("price_gas")["optimistic"]
    assert pin.get("price_oil") == params.entry("price_oil")["central"]
    with pytest.raises(KeyError):
        params.with_overrides(not_a_parameter=1)
    with pytest.raises(ValueError):
        Params(params.raw, case="bogus")


def test_params_draft_flag(params):
    assert params.is_draft
    assert params.entry("bench_heat_kwh_per_m2")["value"]["median"] == 2013.60


# ---------------------------------------------------------------- questions
def test_questions_structure():
    data = load_questions()
    qs = data["questions"]
    ids = [q["id"] for q in qs]
    assert len(ids) == len(set(ids))
    for q in qs:
        assert q["type"] in TYPES, q["id"]
        assert q["step"] in data["steps"], q["id"]
        assert q["origin"] in {"draft", "added"}, q["id"]
        assert q["label_de"] and q["label_en"], q["id"]
        for o in q.get("options", []):
            assert isinstance(o["value"], str), (q["id"], o["value"])
            assert o["label_de"] and o["label_en"], (q["id"], o["value"])
        if q["type"] == "scale":
            assert [s["value"] for s in q["scale"]] == [1, 2, 3, 4, 5]
        if q["type"] in ("single", "multi"):
            vals = [o["value"] for o in q["options"]]
            assert len(vals) == len(set(vals)), q["id"]


def test_show_if_references_exist():
    qs = load_questions()["questions"]
    ids = {q["id"] for q in qs}
    for q in qs:
        cond = q.get("show_if")
        if cond:
            assert cond["id"] in ids, q["id"]
            target = next(x for x in qs if x["id"] == cond["id"])
            for v in cond.get("in", []):
                if "options" in target:
                    assert v in [o["value"] for o in target["options"]], (q["id"], v)


def test_all_draft_questions_present():
    qs = load_questions()["questions"]
    draft_numbers = {q["label_en"].split(".")[0] for q in qs if q["origin"] == "draft" and q["label_en"][0].isdigit()}
    assert {str(i) for i in range(1, 15)} <= draft_numbers


def test_calc_reads_only_defined_question_ids():
    src = (ROOT / "splash_calc" / "inputs.py").read_text(encoding="utf-8")
    used = set(re.findall(r'a\.get\("([a-z0-9_]+)"', src))
    ids = {q["id"] for q in load_questions()["questions"]}
    assert used <= ids, used - ids


def test_option_values_match_calc_expectations():
    qs = {q["id"]: q for q in load_questions()["questions"]}
    vent = {o["value"] for o in qs["q6_ventilation"]["options"]}
    assert {"mech_hr", "mech_no_hr", "natural"} <= vent
    assert {o["value"] for o in qs["q1_pool_type"]["options"]} == {"indoor", "combined", "open_air"}
    from splash_calc.params import Params

    forms = set(Params.load().central("vat_deductible_by_legal_form"))
    assert {o["value"] for o in qs["q1_legal_form"]["options"]} == forms
    assert {o["value"] for o in qs["r_hp_source"]["options"]} == {"air", "ground", "waste"}
