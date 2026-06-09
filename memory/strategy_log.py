"""
TradeX-Pro — Strategy Log
Strategiya dəyişikliklərinin qeydiyyatı (Layer 4 yaddaş)
"""

import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from loguru import logger

DB_PATH = Path(__file__).parent.parent / "database" / "tradex.db"


class StrategyLog:
    """
    Bütün strategiya dəyişikliklərini, tövsiyələri və faza qiymətləndirmələrini saxlayır.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS strategy_changes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    change_type TEXT,
                    description TEXT,
                    details_json TEXT,
                    triggered_by TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS weekly_reflections_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reflection_json TEXT,
                    performance_score REAL,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS phase_evaluations_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phase TEXT,
                    evaluation_json TEXT,
                    readiness_score REAL,
                    advance_recommended INTEGER,
                    created_at TEXT DEFAULT (datetime('now'))
                );
            """)

    def _conn(self):
        return sqlite3.connect(str(self.db_path))

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
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO weekly_reflections_log (reflection_json, performance_score)
                VALUES (?,?)
            """, (json.dumps(reflection), reflection.get("performance_score", 0)))
        logger.debug("Həftəlik refleksiya loquna əlavə edildi")

    def log_phase_evaluation(self, phase: str, evaluation: dict):
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO phase_evaluations_log
                (phase, evaluation_json, readiness_score, advance_recommended)
                VALUES (?,?,?,?)
            """, (phase, json.dumps(evaluation),
                  evaluation.get("readiness_score", 0),
                  1 if evaluation.get("advance_recommended") else 0))

    def _log_change(self, change_type: str, description: str,
                    details: dict, triggered_by: str):
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO strategy_changes
                (change_type, description, details_json, triggered_by)
                VALUES (?,?,?,?)
            """, (change_type, description, json.dumps(details), triggered_by))

    def get_recent_changes(self, days: int = 7) -> list:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT change_type, description, created_at
                FROM strategy_changes WHERE created_at >= ?
                ORDER BY created_at DESC
            """, (cutoff,)).fetchall()
        return [{"type": r[0], "description": r[1], "date": r[2]} for r in rows]

    def get_latest_phase_evaluation(self, phase: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute("""
                SELECT evaluation_json, readiness_score, advance_recommended
                FROM phase_evaluations_log WHERE phase = ?
                ORDER BY id DESC LIMIT 1
            """, (phase,)).fetchone()
        if row:
            return {"evaluation": json.loads(row[0]),
                    "readiness_score": row[1], "advance": bool(row[2])}
        return None
