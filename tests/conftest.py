"""
Test konfiqurasiyası — SQLite temp DB istifadə edir.
QEYD: DATABASE_URL importlardan ƏVVƏL set olunmalıdır,
çünki database/db.py onu modul səviyyəsində oxuyur.
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_tmpdir = tempfile.mkdtemp(prefix="tradex_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmpdir}/test_tradex.db"

import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402


@pytest.fixture(autouse=True)
def clean_db():
    """Hər testdən əvvəl cədvəlləri təmizlə (varsa)."""
    from database.db import engine
    for table in ["open_positions", "balance_state", "risk_state"]:
        try:
            with engine.connect() as conn:
                conn.execute(text(f"DELETE FROM {table}"))
                conn.commit()
        except Exception:
            pass
    yield
