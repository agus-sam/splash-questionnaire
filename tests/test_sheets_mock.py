"""SheetsStore against a fake gspread. Checks our logic, not Google's service."""
import types

import gspread

from splash_app.storage import ANSWER_COLS, SUBMISSION_COLS, SheetsStore, make_record


class FakeWS:
    def __init__(self, title):
        self.title, self.rows, self.calls = title, [], []

    def row_values(self, n):
        return list(self.rows[n - 1]) if len(self.rows) >= n else []

    def append_row(self, row, value_input_option=None):
        self.calls.append(("append_row", value_input_option))
        self.rows.append(list(row))

    def append_rows(self, rows, value_input_option=None):
        self.calls.append(("append_rows", value_input_option))
        self.rows.extend(list(r) for r in rows)

    def findall(self, query, in_column=None):
        return [types.SimpleNamespace(row=i + 1) for i, r in enumerate(self.rows) if r and r[in_column - 1] == query]

    def get_all_records(self, numericise_ignore=None):
        head = self.rows[0]
        return [dict(zip(head, r, strict=False)) for r in self.rows[1:]]


class FakeBook:
    def __init__(self):
        self.sheets = {}

    def worksheets(self):
        return list(self.sheets.values())

    def add_worksheet(self, title, rows, cols):
        self.sheets[title] = FakeWS(title)
        return self.sheets[title]


def _store(monkeypatch):
    book = FakeBook()
    gc = types.SimpleNamespace(open_by_key=lambda key: book)
    monkeypatch.setattr(gspread, "service_account_from_dict", lambda info: gc)
    return SheetsStore("sheet-id", {"type": "service_account"}), book


def test_creates_headers_once_and_appends_raw(monkeypatch):
    store, book = _store(monkeypatch)
    assert set(book.sheets) == {"submissions", "answers", "results", "contacts"}
    assert book.sheets["submissions"].rows[0] == SUBMISSION_COLS
    assert book.sheets["answers"].rows[0] == ANSWER_COLS
    rec = make_record("ABCD-EFGH", "core", {"q1_name": "=1+1", "q7": ["gas"]}, "de", {"k": 1.5})
    store.save(rec)
    assert all(mode == "RAW" for ws in book.sheets.values() for _, mode in ws.calls)
    answers = book.sheets["answers"].rows[1:]
    assert ["q1_name", "=1+1"] in [r[3:5] for r in answers]
    # second instance on the same book must not duplicate headers
    SheetsStore("sheet-id", {"type": "service_account"})
    assert len([r for r in book.sheets["submissions"].rows if r == SUBMISSION_COLS]) == 1


def test_load_returns_latest_row(monkeypatch):
    store, _ = _store(monkeypatch)
    store.save(make_record("ABCD-EFGH", "core", {"q1_name": "alt"}, "de"))
    store.save(make_record("ABCD-EFGH", "final", {"q1_name": "neu"}, "en"))
    got = store.load("abcdefgh")
    assert got["answers"]["q1_name"] == "neu" and got["stage"] == "final" and got["lang"] == "en"
    assert store.load("ZZZZ-ZZZZ") is None
    assert len(store.read_table("submissions")) == 2
    assert store.ping()
