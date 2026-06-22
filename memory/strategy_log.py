"""
TradeX-Pro — Strategy Log
Strategiya dəyişikliklərinin qeydiyyatı (Layer 4 yaddaş)
PostgreSQL/SQLite dəstəyi — container restart-a davamlı
"""

import json
from datetime import datetime, timezone, timedelta
from typing import Optional
from loguru import logger
from sqlalchemy import text

from database.db import get_db, engine, DATABASE_URL


def _is_postgres() -> bool:
    return DATABASE_URL.startswith("postgresql")


class StrategyLog:
    """
    Bütün strategiya dəyişikliklərini, tövsiyələri və faza qiymətləndirmələrini saxlayır.
    """

    def __init__(self):
        self._init_db()
        logger.info(f"StrategyLog qoşuldu ({'PostgreSQL' if _is_postgres() else 'SQLite'})")

    def _init_db(self):
        """Cədvəlləri yarat (PostgreSQL-də init.sql işi görür, SQLite üçün burada)"""
        if _is_postgres():
            # PostgreSQL-də init.sql bu cədvəlləri artıq yaradır
            # Yoxsa yarat (əlavə təhlükəsizlik)
            with engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS strategy_changes (
                        id SERIAL PRIMARY KEY,
                        change_type TEXT,
                        description TEXT,
                        details_json TEXT,
                        triggered_by TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS weekly_reflections_log (
                        id SERIAL PRIMARY KEY,
                        reflection_json TEXT,
                        performance_score REAL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS phase_evaluations_log (
                        id SERIAL PRIMARY KEY,
                        phase TEXT,
                        evaluation_json TEXT,
                        readiness_score REAL,
                        advance_recommended INTEGER,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                conn.commit()
        else:
            with engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS strategy_changes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        change_type TEXT, description TEXT,
                        details_json TEXT, triggered_by TEXT,
                        created_at TEXT DEFAULT (datetime('now'))
                    )
                """))
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS weekly_reflections_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        reflection_json TEXT, performance_score REAL,
                        created_at TEXT DEFAULT (datetime('now'))
                    )
                """))
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS phase_evaluations_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        phase TEXT, evaluation_json TEXT,
                        readiness_score REAL, advance_recommended INTEGER,
                        created_at TEXT DEFAULT (datetime('now'))
                    )
                """))
                conn.commit()

    def log_weight_suggestion(self, indicator: str, direction: str,
                              amount: float, reason: str, trade_id: str):
        self._log_change(
            change_type="weight_suggestion",
            description=f"{indicator} çəkisi {direction} ({amount} bal)",
            details={"indicator": indicator, "direction": direction,
                     "amount": amount, "trade_id": trade_id},
            triggered_by=f"micro_reflection:{trade_id}",
        )

    def log_threshold_change_suggestion(self, new_threshold: float, reason: str):
        self._log_change(
            change_type="threshold_change",
            description=f"Siqnal eşiyi → {new_threshold}",
            details={"new_threshold": new_threshold, "reason": reason},
            triggered_by="macro_reflection",
        )

    def log_weekly_reflection(self, reflection: dict):
        with get_db() as db:
            db.execute(text("""
                INSERT INTO weekly_reflections_log (reflection_json, performance_score)
                VALUES (:r, :s)
            """), {"r": json.dumps(reflection), "s": reflection.get("performance_score", 0)})
        logger.debug("Həftəlik refleksiya loquna əlavə edildi")

    def log_phase_evaluation(self, phase: str, evaluation: dict):
        with get_db() as db:
            db.execute(text("""
                INSERT INTO phase_evaluations_log
                (phase, evaluation_json, readiness_score, advance_recommended)
                VALUES (:ph, :ev, :rs, :ar)
            """), {
                "ph": phase,
                "ev": json.dumps(evaluation),
                "rs": evaluation.get("readiness_score", 0),
                "ar": 1 if evaluation.get("advance_recommended") else 0,
            })

    def _log_change(self, change_type: str, description: str,
                    details: dict, triggered_by: str):
        with get_db() as db:
            db.execute(text("""
                INSERT INTO strategy_changes
                (change_type, description, details_json, triggered_by)
                VALUES (:ct, :desc, :det, :by)
            """), {
                "ct": change_type, "desc": description,
                "det": json.dumps(details), "by": triggered_by,
            })

    def get_recent_changes(self, days: int = 7) -> list:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with get_db() as db:
            rows = db.execute(text("""
                SELECT change_type, description, created_at
                FROM strategy_changes WHERE created_at >= :cutoff
                ORDER BY created_at DESC
            """), {"cutoff": cutoff}).fetchall()
        return [{"type": r[0], "description": r[1], "date": str(r[2])} for r in rows]

    def get_latest_phase_evaluation(self, phase: str) -> Optional[dict]:
        with get_db() as db:
            row = db.execute(text("""
                SELECT evaluation_json, readiness_score, advance_recommended
                FROM phase_evaluations_log WHERE phase = :ph
                ORDER BY id DESC LIMIT 1
            """), {"ph": phase}).fetchone()
        if row:
            return {"evaluation": json.loads(row[0]),
                    "readiness_score": row[1], "advance": bool(row[2])}
        return None
