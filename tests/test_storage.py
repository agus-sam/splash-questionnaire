import pytest

from splash_app.storage import (
    MemoryStore,
    SqliteStore,
    build_rows,
    make_record,
    make_store,
    new_submission_id,
    normalise_code,
)


def _rec(sid, stage, answers, contact=None, results=None):
    return make_record(sid, stage, answers, "de", results, contact, {"questionnaire": "1", "params": "p", "app": "a"})


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    return MemoryStore() if request.param == "memory" else SqliteStore(tmp_path / "t.db")


def test_codes():
    c = new_submission_id()
    assert len(c) == 9 and c[4] == "-"
    assert normalise_code(c.lower().replace("-", " ")) == c
    assert len({new_submission_id() for _ in range(500)}) == 500


def test_roundtrip_latest_wins(store):
    store.save(_rec("AAAA-BBBB", "core", {"q1_name": "Alt", "q3_basins": [{"type": "lap"}]}))
    store.save(_rec("AAAA-BBBB", "results", {"q1_name": "Neu"}, results={"hp_npv_cen": 123.0}))
    loaded = store.load("aaaabbbb")
    assert loaded["answers"]["q1_name"] == "Neu" and loaded["stage"] == "results"
    assert store.load("ZZZZ-ZZZZ") is None
    # append-only: both stages are kept
    assert len(store.read_table("submissions")) == 2
    assert {r["kpi"] for r in store.read_table("results")} == {"hp_npv_cen"}


def test_lists_and_dicts_are_flattened(store):
    store.save(_rec("CCCC-DDDD", "core", {"q7_sources": ["gas", "oil"], "q8_consumption": {"gas": {"value": 1}}, "flag": True}))
    vals = {r["question_id"]: r["value"] for r in store.read_table("answers")}
    assert vals["q7_sources"] == '["gas", "oil"]'
    assert vals["flag"] == "TRUE"
    assert vals["q8_consumption"].startswith("{")


def test_formula_text_is_stored_exactly_and_neutralised_on_export():
    from splash_app.storage import export_safe

    rows = build_rows(_rec("EEEE-FFFF", "core", {"q1_name": "=HYPERLINK(\"x\")", "q5": "+1+1", "n": "-5", "ok": "text"}))
    cells = {r[3]: r[4] for r in rows["answers"]}
    assert cells["q1_name"] == '=HYPERLINK("x")' and cells["q5"] == "+1+1"
    assert export_safe(cells["q1_name"]).startswith("'=") and export_safe(cells["q5"]).startswith("'+")
    assert cells["n"] == "-5" and cells["ok"] == "text"


def test_contacts_separate_and_only_with_data(store):
    store.save(_rec("GGGG-HHHH", "final", {"q1_name": "X"}, contact={"name": "A B", "contact": "a@b.de", "method": "email",
                                                                       "consent": True, "summary": True}))
    store.save(_rec("IIII-JJJJ", "final", {"q1_name": "Y"}, contact={}))
    contacts = store.read_table("contacts")
    assert len(contacts) == 1 and contacts[0]["name"] == "A B"
    assert all("a@b.de" not in r["value"] for r in store.read_table("answers"))


def test_make_store_defaults(tmp_path):
    assert make_store({"backend": "memory"}).name == "memory"
    s = make_store(None, tmp_path / "x.db")
    assert s.name == "sqlite" and s.is_test
    with pytest.raises(ValueError):
        make_store({"backend": "sheets"})
