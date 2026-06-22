"""
TradeX-Pro — Trade Journal
PostgreSQL + SQLite universal ticarət gündəliyi
"""

import json
from datetime import datetime, timezone, timedelta
from typing import Optional
from loguru import logger
from sqlalchemy import text

from database.db import get_db, engine, DATABASE_URL


def _is_postgres() -> bool:
    return DATABASE_URL.startswith("postgresql")


def _placeholder(n: int = 1) -> str:
    """PostgreSQL: $1, SQLite: ?"""
    return f"${n}" if _is_postgres() else "?"


class TradeJournal:
    """
    Bütün ticarət tarixini saxlayan mərkəzi qeyd sistemi.
    PostgreSQL (production) və SQLite (lokal) dəstəyi.
    """

    def __init__(self):
        self._ensure_tables()
        logger.info(f"TradeJournal qoşuldu ({'PostgreSQL' if _is_postgres() else 'SQLite'})")

    def _ensure_tables(self):
        """SQLite üçün cədvəlləri yarat (PostgreSQL-də init.sql həll edir)"""
        if _is_postgres():
            return
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS trades (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry_price REAL, exit_price REAL,
                    units REAL, usd_value REAL, risk_usd REAL,
                    pnl_usd REAL, pnl_pct REAL,
                    signal_score REAL, confidence REAL,
                    open_time TEXT, close_time TEXT,
                    duration_minutes REAL, exit_reason TEXT, phase TEXT,
                    indicators_triggered TEXT DEFAULT '[]',
                    market_condition TEXT,
                    reflection TEXT, lesson TEXT, overall_grade TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS phase_state (
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    current_phase TEXT DEFAULT '1',
                    phase_start_date TEXT DEFAULT (datetime('now')),
                    phase_promoted_by TEXT
                )
            """))
            conn.execute(text("""
                INSERT OR IGNORE INTO phase_state (id) VALUES (1)
            """))
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

    # ──────────────────────────────────────────────
    # Ticarət Əlavə Et / Güncəllə
    # ──────────────────────────────────────────────
    def save_trade(self, trade: dict):
        """Bağlanmış ticarəti verilənlər bazasına əlavə et"""
        indicators = json.dumps(trade.get("indicators_triggered", []))
        with get_db() as db:
            db.execute(text("""
                INSERT INTO trades
                (id, symbol, direction, entry_price, exit_price, units, usd_value,
                 risk_usd, pnl_usd, pnl_pct, signal_score, confidence,
                 open_time, close_time, duration_minutes, exit_reason, phase,
                 indicators_triggered, market_condition)
                VALUES (:id,:symbol,:direction,:entry_price,:exit_price,:units,
                        :usd_value,:risk_usd,:pnl_usd,:pnl_pct,:signal_score,
                        :confidence,:open_time,:close_time,:duration_minutes,
                        :exit_reason,:phase,:indicators,:market_condition)
                ON CONFLICT (id) DO UPDATE SET
                    exit_price=EXCLUDED.exit_price,
                    pnl_usd=EXCLUDED.pnl_usd,
                    pnl_pct=EXCLUDED.pnl_pct,
                    close_time=EXCLUDED.close_time,
                    exit_reason=EXCLUDED.exit_reason
            """ if _is_postgres() else """
                INSERT OR REPLACE INTO trades
                (id, symbol, direction, entry_price, exit_price, units, usd_value,
                 risk_usd, pnl_usd, pnl_pct, signal_score, confidence,
                 open_time, close_time, duration_minutes, exit_reason, phase,
                 indicators_triggered, market_condition)
                VALUES (:id,:symbol,:direction,:entry_price,:exit_price,:units,
                        :usd_value,:risk_usd,:pnl_usd,:pnl_pct,:signal_score,
                        :confidence,:open_time,:close_time,:duration_minutes,
                        :exit_reason,:phase,:indicators,:market_condition)
            """), {
                "id": trade["trade_id"], "symbol": trade["symbol"],
                "direction": trade["direction"], "entry_price": trade.get("entry_price"),
                "exit_price": trade.get("exit_price"), "units": trade.get("units"),
                "usd_value": trade.get("usd_value"), "risk_usd": trade.get("risk_usd"),
                "pnl_usd": trade.get("pnl_usd"), "pnl_pct": trade.get("pnl_pct"),
                "signal_score": trade.get("signal_score"), "confidence": trade.get("confidence", 7.0),
                "open_time": trade.get("open_time"), "close_time": trade.get("close_time"),
                "duration_minutes": trade.get("duration_minutes"), "exit_reason": trade.get("exit_reason"),
                "phase": trade.get("phase"), "indicators": indicators,
                "market_condition": trade.get("market_condition", ""),
            })
        logger.debug(f"Ticarət qeyd edildi: {trade.get('trade_id')}")

    def update_trade_reflection(self, trade_id: str, reflection: dict):
        with get_db() as db:
            db.execute(text("""
                UPDATE trades SET reflection=:ref, lesson=:lesson, overall_grade=:grade
                WHERE id=:id
            """), {
                "ref": json.dumps(reflection),
                "lesson": reflection.get("lesson", ""),
                "grade": reflection.get("overall_grade", ""),
                "id": trade_id,
            })

    def get_trade(self, trade_id: str) -> Optional[dict]:
        with get_db() as db:
            row = db.execute(text("SELECT * FROM trades WHERE id=:id"),
                             {"id": trade_id}).mappings().fetchone()
        if row:
            d = dict(row)
            raw = d.get("indicators_triggered")
            d["indicators_triggered"] = json.loads(raw) if isinstance(raw, str) else (raw or [])
            raw_ref = d.get("reflection")
            d["reflection"] = json.loads(raw_ref) if isinstance(raw_ref, str) and raw_ref else raw_ref
            return d
        return None

    # ──────────────────────────────────────────────
    # Sorğular
    # ──────────────────────────────────────────────
    def find_similar_trades(self, symbol: str, direction: str, limit: int = 5) -> list:
        with get_db() as db:
            rows = db.execute(text("""
                SELECT * FROM trades
                WHERE symbol=:sym AND direction=:dir AND pnl_usd IS NOT NULL
                ORDER BY close_time DESC LIMIT :lim
            """), {"sym": symbol, "dir": direction, "lim": limit}).mappings().fetchall()
        result = []
        for row in rows:
            d = dict(row)
            raw = d.get("indicators_triggered")
            d["indicators_triggered"] = json.loads(raw) if isinstance(raw, str) else (raw or [])
            result.append(d)
        return result

    def get_weekly_stats(self, days: int = 7) -> dict:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with get_db() as db:
            rows = db.execute(text("""
                SELECT pnl_usd, pnl_pct, exit_reason, signal_score
                FROM trades
                WHERE close_time >= :cutoff AND pnl_usd IS NOT NULL
            """), {"cutoff": cutoff}).fetchall()

        if not rows:
            return {"total_trades": 0}

        pnls = [r[0] for r in rows]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        total = len(pnls)

        win_rate = len(wins) / total * 100 if total > 0 else 0
        profit_factor = (sum(wins) / abs(sum(losses))) if losses else 9.99

        import statistics
        avg_pnl = sum(pnls) / total
        std_pnl = statistics.stdev(pnls) if total > 1 else 1
        sharpe = (avg_pnl / std_pnl * (252 ** 0.5)) if std_pnl > 0 else 0

        peak = 0; cumulative = 0; max_dd = 0
        for p in pnls:
            cumulative += p
            if cumulative > peak: peak = cumulative
            dd = (peak - cumulative) / peak if peak > 0 else 0
            if dd > max_dd: max_dd = dd

        return {
            "total_trades": total,
            "win_count": len(wins),
            "loss_count": len(losses),
            "win_rate_pct": round(win_rate, 1),
            "total_pnl_usd": round(sum(pnls), 2),
            "avg_win_usd": round(sum(wins) / len(wins), 2) if wins else 0,
            "avg_loss_usd": round(abs(sum(losses) / len(losses)), 2) if losses else 0,
            "profit_factor": round(min(profit_factor, 9.99), 2),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown_pct": round(max_dd * 100, 1),
            "best_trade_usd": round(max(pnls), 2),
            "worst_trade_usd": round(min(pnls), 2),
        }

    def get_phase_stats(self, phase: str) -> dict:
        with get_db() as db:
            rows = db.execute(text("""
                SELECT pnl_usd, pnl_pct, signal_score, exit_reason, duration_minutes
                FROM trades WHERE phase=:phase AND pnl_usd IS NOT NULL
            """), {"phase": phase}).fetchall()

        if not rows:
            return {"total_trades": 0, "phase": phase}

        pnls = [r[0] for r in rows]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        total = len(pnls)

        import statistics
        avg_pnl = sum(pnls) / total if total > 0 else 0
        std_pnl = statistics.stdev(pnls) if total > 1 else 1
        sharpe = avg_pnl / std_pnl * (252 ** 0.5) if std_pnl > 0 else 0
        profit_factor = (sum(wins) / abs(sum(losses))) if losses else 9.99

        return {
            "phase": phase, "total_trades": total,
            "win_rate_pct": round(len(wins) / total * 100, 1),
            "total_pnl_usd": round(sum(pnls), 2),
            "profit_factor": round(min(profit_factor, 9.99), 2),
            "sharpe_ratio": round(sharpe, 2),
            "avg_duration_min": round(sum(r[4] for r in rows if r[4]) / total, 0),
        }

    def get_recent_reflections(self, days: int = 7) -> list:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with get_db() as db:
            rows = db.execute(text("""
                SELECT id, symbol, pnl_pct, lesson, overall_grade
                FROM trades WHERE close_time >= :cutoff AND lesson IS NOT NULL
            """), {"cutoff": cutoff}).fetchall()
        return [{"id": r[0], "symbol": r[1], "pnl_pct": r[2],
                 "lesson": r[3], "grade": r[4]} for r in rows]

    def get_all_lessons(self, limit: int = 20) -> list[str]:
        with get_db() as db:
            rows = db.execute(text("""
                SELECT lesson FROM trades
                WHERE lesson IS NOT NULL AND lesson != ''
                ORDER BY close_time DESC LIMIT :lim
            """), {"lim": limit}).fetchall()
        return [r[0] for r in rows]

    def get_recent_trades(self, limit: int = 20) -> list:
        """Son N bağlanmış ticarəti qaytarır — weight analyzer üçün istifadə edilir."""
        with get_db() as db:
            rows = db.execute(text("""
                SELECT id, symbol, direction, pnl_usd, pnl_pct, indicators_triggered
                FROM trades WHERE pnl_usd IS NOT NULL
                ORDER BY close_time DESC LIMIT :lim
            """), {"lim": limit}).mappings().fetchall()
        result = []
        for row in rows:
            d = dict(row)
            raw = d.get("indicators_triggered")
            d["indicators_triggered"] = json.loads(raw) if isinstance(raw, str) else (raw or [])
            result.append(d)
        return result

    def get_performance_by_hour(self) -> dict:
        hour_fn = "EXTRACT(HOUR FROM open_time::timestamptz)" if _is_postgres() \
                  else "strftime('%H', open_time)"
        with get_db() as db:
            rows = db.execute(text(f"""
                SELECT {hour_fn} as hour,
                       COUNT(*) as trades,
                       SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as wins,
                       AVG(pnl_usd) as avg_pnl
                FROM trades WHERE pnl_usd IS NOT NULL
                GROUP BY {hour_fn} ORDER BY {hour_fn}
            """)).fetchall()
        return {str(int(r[0])): {"trades": r[1],
                "win_rate": r[2]/r[1]*100 if r[1] > 0 else 0,
                "avg_pnl": r[3]} for r in rows}
