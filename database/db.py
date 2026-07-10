"""
TradeX-Pro — Database Connection
SQLite (lokal dev) və PostgreSQL (production) dəstəyi
"""

import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from loguru import logger


def get_database_url() -> str:
    """
    DATABASE_URL varsa PostgreSQL, yoxdursa SQLite istifadə et.
    """
    url = os.getenv("DATABASE_URL")
    if url:
        # DigitalOcean bəzən postgres:// qaytarır, SQLAlchemy postgresql:// istəyir
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        db_type = "PostgreSQL" if url.startswith("postgresql") else url.split(":")[0]
        logger.info(f"{db_type} istifadə edilir ✅ (DATABASE_URL)")
        return url
    else:
        from pathlib import Path
        db_path = Path(__file__).parent / "tradex.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"SQLite istifadə edilir: {db_path}")
        return f"sqlite:///{db_path}"


DATABASE_URL = get_database_url()

# Engine
_engine_kwargs = {}
if DATABASE_URL.startswith("postgresql"):
    _engine_kwargs = {
        "pool_size": 5,
        "max_overflow": 10,
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }

engine = create_engine(DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@contextmanager
def get_db() -> Session:
    """Context manager ilə verilənlər bazası sessiyası"""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def execute_raw(sql: str, params: dict = None):
    """Raw SQL icraatı (migration, init üçün)"""
    with engine.connect() as conn:
        conn.execute(text(sql), params or {})
        conn.commit()


def test_connection() -> bool:
    """Verilənlər bazası bağlantısını yoxla"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Verilənlər bazası bağlantısı OK ✅")
        return True
    except Exception as e:
        logger.error(f"Verilənlər bazası bağlantı xətası: {e}")
        return False
