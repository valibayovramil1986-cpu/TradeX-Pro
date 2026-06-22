"""
TradeX-Pro — Phase Manager
3 Fazalı inkişaf planının idarəetməsi
PostgreSQL/SQLite dəstəyi (database/db.py vasitəsilə)
"""

from datetime import datetime, timezone
from typing import Optional
from loguru import logger
from sqlalchemy import text

from database.db import get_db, engine


PHASE_TARGETS = {
    "1": {
        "name": "İlkin Sınaq",
        "duration_days": 14,
        "virtual_capital": 1000.0,
        "mode": "paper",
        "win_rate_min": 55.0,
        "max_drawdown_pct": 10.0,
        "sharpe_min": 1.0,
        "profit_factor_min": 1.2,
        "min_trades": 40,
        "readiness_threshold": 65,
        "max_risk_per_trade": 0.02,
        "max_open_positions": 3,
    },
    "2": {
        "name": "Peşəkar Sınaq",
        "duration_days": 14,
        "virtual_capital": 5000.0,
        "mode": "paper",
        "win_rate_min": 60.0,
        "max_drawdown_pct": 8.0,
        "sharpe_min": 1.4,
        "profit_factor_min": 1.5,
        "min_trades": 60,
        "readiness_threshold": 80,
        "max_risk_per_trade": 0.015,
        "max_open_positions": 4,
    },
    "3": {
        "name": "Real Ticarət",
        "duration_days": 999,
        "virtual_capital": None,
        "mode": "live",
        "win_rate_min": 60.0,
        "max_drawdown_pct": 8.0,
        "sharpe_min": 1.4,
        "profit_factor_min": 1.5,
        "min_trades": 0,
        "readiness_threshold": 100,
        "max_risk_per_trade": 0.005,
        "max_open_positions": 3,
    },
}


class PhaseManager:
    """
    Faza keçidlərini idarə edir.
    Məlumatlar PostgreSQL/SQLite-da saxlanılır (container restart-a davamlı).
    """

    def __init__(self):
        self._init_db()
        self.current_phase = self._load_current_phase()
        self.phase_start_date = self._load_phase_start_date()
        logger.info(f"PhaseManager: Cari faza = {self.current_phase} | "
                    f"Başlama: {self.phase_start_date.strftime('%Y-%m-%d %H:%M UTC')}")

    def _init_db(self):
        """phase_state cədvəlini yarat (yoxdursa)"""
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS phase_state (
                    id INTEGER PRIMARY KEY,
                    current_phase TEXT DEFAULT '1',
                    phase_start_date TIMESTAMP WITH TIME ZONE,
                    phase_promoted_by TEXT
                )
            """))
            # İlk sətri yalnız bir dəfə əlavə et
            result = conn.execute(text("SELECT id FROM phase_state WHERE id = 1")).fetchone()
            if not result:
                conn.execute(text("""
                    INSERT INTO phase_state (id, current_phase, phase_start_date)
                    VALUES (1, '1', :now)
                """), {"now": datetime.now(timezone.utc)})
            conn.commit()

    def _load_current_phase(self) -> str:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT current_phase FROM phase_state WHERE id = 1")
            ).fetchone()
        return row[0] if row else "1"

    def _load_phase_start_date(self) -> datetime:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT phase_start_date FROM phase_state WHERE id = 1")
            ).fetchone()
        if row and row[0]:
            dt = row[0]
            if isinstance(dt, str):
                dt = datetime.fromisoformat(dt)
            # timezone-aware et
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        return datetime.now(timezone.utc)

    def promote_to_next_phase(self, promoted_by: str = "manual") -> dict:
        """Növbəti fazaya keç"""
        current = int(self.current_phase)
        next_phase = str(current + 1)

        if next_phase not in PHASE_TARGETS:
            return {"success": False, "message": "Artıq son fazadasınız (Faza 3 — Real Ticarət)"}

        old_phase = self.current_phase
        self.current_phase = next_phase
        self.phase_start_date = datetime.now(timezone.utc)

        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE phase_state SET
                    current_phase = :phase,
                    phase_start_date = :start,
                    phase_promoted_by = :by
                WHERE id = 1
            """), {
                "phase": next_phase,
                "start": self.phase_start_date,
                "by": promoted_by,
            })
            conn.commit()

        phase_info = PHASE_TARGETS[next_phase]
        logger.info(f"🎓 Faza keçidi: {old_phase} → {next_phase} | {promoted_by}")

        return {
            "success": True,
            "old_phase": old_phase,
            "new_phase": next_phase,
            "phase_name": phase_info["name"],
            "capital": phase_info.get("virtual_capital"),
            "mode": phase_info["mode"],
            "message": f"✅ Faza {next_phase} başladı: {phase_info['name']}",
        }

    @property
    def current_targets(self) -> dict:
        return PHASE_TARGETS.get(self.current_phase, PHASE_TARGETS["1"])

    @property
    def days_in_phase(self) -> int:
        now = datetime.now(timezone.utc)
        start = self.phase_start_date
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        delta = now - start
        return max(0, delta.days)

    @property
    def days_remaining(self) -> int:
        return max(0, self.current_targets["duration_days"] - self.days_in_phase)

    def is_phase_complete(self) -> bool:
        return self.days_in_phase >= self.current_targets["duration_days"]

    def get_status_message(self, stats: dict) -> str:
        targets = self.current_targets
        phase = self.current_phase
        days_in = self.days_in_phase
        days_total = targets["duration_days"]
        days_left = self.days_remaining

        lines = [
            f"🎯 *Faza {phase}: {targets['name']}*",
            f"━━━━━━━━━━━━━━━━━━━━━━",
            f"• Gün: {days_in}/{days_total} ({days_left} gün qaldı)",
            f"• Mode: {'📋 PAPER' if targets['mode'] == 'paper' else '💰 LIVE'}",
            f"• Kapital: ${targets.get('virtual_capital') or 'Real':,}",
            f"",
            f"📊 *Hədəflər vs Nəticə:*",
            f"• Win Rate: {stats.get('win_rate_pct', 0):.1f}% "
            f"{'✅' if stats.get('win_rate_pct', 0) >= targets['win_rate_min'] else '❌'} "
            f"(hədəf: ≥{targets['win_rate_min']}%)",
            f"• Max DD: {stats.get('max_drawdown_pct', 0):.1f}% "
            f"{'✅' if stats.get('max_drawdown_pct', 0) <= targets['max_drawdown_pct'] else '❌'} "
            f"(hədəf: ≤{targets['max_drawdown_pct']}%)",
            f"• Sharpe: {stats.get('sharpe_ratio', 0):.2f} "
            f"{'✅' if stats.get('sharpe_ratio', 0) >= targets['sharpe_min'] else '❌'} "
            f"(hədəf: ≥{targets['sharpe_min']})",
            f"• Profit Factor: {stats.get('profit_factor', 0):.2f} "
            f"{'✅' if stats.get('profit_factor', 0) >= targets['profit_factor_min'] else '❌'} "
            f"(hədəf: ≥{targets['profit_factor_min']})",
            f"• Ticarətlər: {stats.get('total_trades', 0)} "
            f"{'✅' if stats.get('total_trades', 0) >= targets['min_trades'] else '❌'} "
            f"(min: {targets['min_trades']})",
        ]

        if self.is_phase_complete():
            lines += [f"", f"⏰ *Faza müddəti dolub — /promote ilə keçid edin*"]

        return "\n".join(lines)
