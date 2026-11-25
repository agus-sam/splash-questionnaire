"""Storage backends. No Streamlit imports, so everything here is testable.

Records are append-only: every save adds a row with a ``stage`` (for example
``core``, ``results``, ``final``). The latest row per submission wins when a
submission is reloaded with its resume code.

Backends
    memory   process memory only (tests, demos)
    sqlite   local file (default for local development, flagged as test mode)
    sheets   Google Sheets through a service account (production)
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SUBMISSION_COLS = [
    "submission_id", "timestamp_utc", "stage", "lang", "questionnaire_version",
    "params_version", "app_version", "pool_token", "answers_json",
]
ANSWER_COLS = ["submission_id", "timestamp_utc", "stage", "question_id", "value"]
RESULT_COLS = ["submission_id", "timestamp_utc", "stage", "kpi", "value"]
CONTACT_COLS = ["submission_id", "timestamp_utc", "name", "contact", "method", "consent", "summary"]

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I


def new_submission_id() -> str:
    """Short resume code, e.g. ``K7QX-4M2D`` (about 40 bits)."""
    raw = uuid.uuid4().int
    chars = []
    for _ in range(8):
        raw, i = divmod(raw, len(ALPHABET))
        chars.append(ALPHABET[i])
    s = "".join(chars)
    return f"{s[:4]}-{s[4:]}"


def normalise_code(code: str) -> str:
    c = "".join(ch for ch in (code or "").upper() if ch.isalnum())
    return f"{c[:4]}-{c[4:]}" if len(c) == 8 else (code or "").strip().upper()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cell(v: Any) -> str:
    """Flatten any value to a text cell. Lists and dicts become JSON."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    return str(v)


def export_safe(v: Any) -> Any:
    """Neutralise formula injection in a text cell that leaves the system as CSV or Excel.

    Stored data stays exact (Sheets is written with RAW, so nothing is evaluated there). Only exports
    get the leading apostrophe, and only for text that a spreadsheet could read as a formula.
    A phone number that starts with + is text and is kept readable by a leading apostrophe.
    """
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def sanitise_frame(df):
    """Apply ``export_safe`` to every text cell of a DataFrame."""
    return df.apply(lambda col: col.map(export_safe)) if len(df) else df


def build_rows(rec: dict) -> dict[str, list[list[str]]]:
    """Turn one record into the rows of the four tables."""
    ts = rec.get("timestamp_utc") or _now()
    sid, stage = rec["submission_id"], rec.get("stage", "")
    answers = rec.get("answers") or {}
    sub = [[
        sid, ts, stage, rec.get("lang", ""), rec.get("questionnaire_version", ""),
        rec.get("params_version", ""), rec.get("app_version", ""), rec.get("pool_token", ""),
        json.dumps(answers, ensure_ascii=False, sort_keys=True),
    ]]
    ans = [[sid, ts, stage, k, _cell(v)] for k, v in sorted(answers.items())]
    res = [[sid, ts, stage, k, _cell(v)] for k, v in sorted((rec.get("results") or {}).items())]
    contact = rec.get("contact") or {}
    con = []
    if contact and any(contact.get(k) for k in ("name", "contact")):
        con = [[
            sid, ts, _cell(contact.get("name")), _cell(contact.get("contact")),
            _cell(contact.get("method")), _cell(contact.get("consent")), _cell(contact.get("summary")),
        ]]
    return {"submissions": sub, "answers": ans, "results": res, "contacts": con}


class Store(ABC):
    name = "abstract"
    is_test = True

    @abstractmethod
    def save(self, rec: dict) -> None: ...

    @abstractmethod
    def load(self, code: str) -> dict | None:
        """Latest saved answers of a submission, or None."""

    @abstractmethod
    def read_table(self, table: str) -> list[dict]: ...

    def ping(self) -> bool:
        return True


# --------------------------------------------------------------------- memory
class MemoryStore(Store):
    name = "memory"
    is_test = True

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.tables: dict[str, list[list[str]]] = {"submissions": [], "answers": [], "results": [], "contacts": []}

    def save(self, rec: dict) -> None:
        rows = build_rows(rec)
        with self._lock:
            for t, r in rows.items():
                self.tables[t].extend(r)

    def load(self, code: str) -> dict | None:
        code = normalise_code(code)
        with self._lock:
            matches = [r for r in self.tables["submissions"] if r[0] == code]
        if not matches:
            return None
        last = sorted(matches, key=lambda r: r[1])[-1]
        return {"submission_id": code, "stage": last[2], "lang": last[3], "answers": json.loads(last[8])}

    def read_table(self, table: str) -> list[dict]:
        cols = {"submissions": SUBMISSION_COLS, "answers": ANSWER_COLS, "results": RESULT_COLS, "contacts": CONTACT_COLS}[table]
        with self._lock:
            return [dict(zip(cols, r, strict=False)) for r in self.tables[table]]


# ---------------------------------------------------------------------- sqlite
class SqliteStore(Store):
    name = "sqlite"
    is_test = True

    def __init__(self, path: str | Path = "data/local_submissions.db") -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            for t, cols in (("submissions", SUBMISSION_COLS), ("answers", ANSWER_COLS),
                            ("results", RESULT_COLS), ("contacts", CONTACT_COLS)):
                c.execute(f"CREATE TABLE IF NOT EXISTS {t} ({', '.join(f'{col} TEXT' for col in cols)})")
            c.execute("CREATE INDEX IF NOT EXISTS ix_sub ON submissions(submission_id)")

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def save(self, rec: dict) -> None:
        rows = build_rows(rec)
        cols = {"submissions": SUBMISSION_COLS, "answers": ANSWER_COLS, "results": RESULT_COLS, "contacts": CONTACT_COLS}
        with self._lock, self._conn() as c:
            for t, r in rows.items():
                if r:
                    ph = ",".join("?" * len(cols[t]))
                    c.executemany(f"INSERT INTO {t} VALUES ({ph})", r)

    def load(self, code: str) -> dict | None:
        code = normalise_code(code)
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT stage, lang, answers_json FROM submissions WHERE submission_id=? "
                "ORDER BY timestamp_utc DESC, rowid DESC LIMIT 1", (code,)
            ).fetchone()
        if not row:
            return None
        return {"submission_id": code, "stage": row[0], "lang": row[1], "answers": json.loads(row[2])}

    def read_table(self, table: str) -> list[dict]:
        if table not in ("submissions", "answers", "results", "contacts"):
            raise ValueError(table)
        with self._lock, self._conn() as c:
            cur = c.execute(f"SELECT * FROM {table}")
            names = [d[0] for d in cur.description]
            return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


# ---------------------------------------------------------------------- sheets
def _retry(fn, attempts: int = 5, base_s: float = 1.5):
    """Call ``fn``; retry quota (429) and server errors with exponential backoff."""
    import time

    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:  # gspread.exceptions.APIError and network errors
            code = getattr(getattr(exc, "response", None), "status_code", None)
            if code is not None and code not in (429, 500, 502, 503, 504):
                raise
            last = exc
            time.sleep(base_s * (2**i))
    raise StorageError(f"storage write failed after {attempts} attempts: {last}")


class StorageError(RuntimeError):
    """Raised when the configured storage cannot be reached. The app does not fall back silently."""


class SheetsStore(Store):
    name = "sheets"
    is_test = False

    def __init__(self, spreadsheet_id: str, service_account_info: dict) -> None:
        import gspread  # imported lazily: not needed for local runs

        self._lock = threading.Lock()
        gc = gspread.service_account_from_dict(service_account_info)
        self.book = gc.open_by_key(spreadsheet_id)
        self._ws: dict[str, Any] = {}
        heads = {"submissions": SUBMISSION_COLS, "answers": ANSWER_COLS, "results": RESULT_COLS, "contacts": CONTACT_COLS}
        existing = {w.title: w for w in self.book.worksheets()}
        for title, cols in heads.items():
            ws = existing.get(title) or self.book.add_worksheet(title=title, rows=1000, cols=len(cols))
            if not ws.row_values(1):
                ws.append_row(cols, value_input_option="RAW")
            self._ws[title] = ws

    def save(self, rec: dict) -> None:
        rows = build_rows(rec)
        with self._lock:
            for t, r in rows.items():
                if r:
                    _retry(lambda ws=self._ws[t], r=r: ws.append_rows(r, value_input_option="RAW"))

    def load(self, code: str) -> dict | None:
        code = normalise_code(code)
        with self._lock:
            ws = self._ws["submissions"]
            cell = ws.findall(code, in_column=1)
            if not cell:
                return None
            row = ws.row_values(cell[-1].row)
        row += [""] * (len(SUBMISSION_COLS) - len(row))
        return {"submission_id": code, "stage": row[2], "lang": row[3], "answers": json.loads(row[8] or "{}")}

    def read_table(self, table: str) -> list[dict]:
        with self._lock:
            return _retry(lambda: self._ws[table].get_all_records(numericise_ignore=["all"]))

    def ping(self) -> bool:
        try:
            self.book.worksheets()
            return True
        except Exception:
            return False


# --------------------------------------------------------------------- factory
def make_store(config: dict | None, sqlite_path: str | Path = "data/local_submissions.db") -> Store:
    """Build the backend from a config dict (``st.secrets["storage"]``).

    No config: local SQLite (test mode). ``backend = "sheets"`` needs
    ``spreadsheet_id`` and ``service_account`` (the JSON key as a table).
    """
    cfg = dict(config or {})
    backend = cfg.get("backend", "sqlite")
    if backend == "memory":
        return MemoryStore()
    if backend == "sheets":
        sa = cfg.get("service_account")
        if not sa or not cfg.get("spreadsheet_id"):
            raise ValueError("sheets backend needs 'spreadsheet_id' and 'service_account'")
        return SheetsStore(str(cfg["spreadsheet_id"]), dict(sa))
    return SqliteStore(cfg.get("path", sqlite_path))


def make_record(
    submission_id: str, stage: str, answers: dict, lang: str, results: dict | None = None,
    contact: dict | None = None, versions: dict | None = None, pool_token: str = "",
) -> dict:
    v = versions or {}
    return {
        "submission_id": submission_id,
        "timestamp_utc": _now(),
        "stage": stage,
        "lang": lang,
        "answers": answers,
        "results": results or {},
        "contact": contact or {},
        "questionnaire_version": v.get("questionnaire", ""),
        "params_version": v.get("params", ""),
        "app_version": v.get("app", ""),
        "pool_token": pool_token,
    }
