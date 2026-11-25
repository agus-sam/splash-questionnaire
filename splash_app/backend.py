"""Connects the app to a storage backend using Streamlit secrets."""
from __future__ import annotations

import os

import streamlit as st

from .storage import Store, make_store


def _secrets_section(name: str) -> dict | None:
    try:
        sec = st.secrets.get(name)
    except Exception:  # no secrets file at all
        return None
    return dict(sec) if sec is not None else None


@st.cache_resource(show_spinner=False)
def get_store() -> Store:
    """Sheets in production (secrets present), local SQLite only when nothing is configured.

    A configured backend that cannot be reached is an error: the app does not write personal data
    to the temporary disk of the server. ``get_store`` is not cached on failure, so the next
    request tries again.
    """
    cfg = _secrets_section("storage")
    if cfg is None and os.environ.get("SPLASH_SQLITE_PATH"):
        cfg = {"backend": "sqlite", "path": os.environ["SPLASH_SQLITE_PATH"]}
    return make_store(cfg)


def store_ok() -> bool:
    """True if the store can be opened. Used by the interface to warn before data is entered."""
    try:
        get_store()
        return True
    except Exception:
        return False


def admin_password() -> str | None:
    try:
        v = st.secrets.get("admin_password")
    except Exception:
        return None
    return str(v) if v else None


