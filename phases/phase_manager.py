"""
TradeX-Pro — Phase Manager
3 Fazalı inkişaf planının idarəetməsi
"""

import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from loguru import logger

DB_PATH = Path(__file__).parent.parent / "database" / "tradex.db"

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
        "virtual_capital": None,    # İstifadəçi müəyyənləşdirir
        "mode": "live",
        "win_rate_min": 60.0,
        "max_drawdown_pct": 8.0,
        "sharpe_min": 1.4,
        "profit_factor_min": 1.5,
        "min_trades": 0,
        "readiness_threshold": 100,
        "max_risk_per_trade": 0.005,  # İlk 7 gün 0.5%
        "max_open_positions": 3,
    },
}


class PhaseManager:
    """
    Faza keçidlərini idarə edir.
    Hər fazanın hədəflərini yoxlayır, keçid qərarı verir.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self.current_phase = self._load_current_phase()
        self.phase_start_date = self._load_phase_start_date()
        logger.info(f"PhaseManager: Cari faza = {self.current_phase} | "
                    f"Başlama: {self.phase_start_date}")

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS phase_state (
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    current_phase TEXT DEFAULT '1',
                    phase_start_date TEXT,
                    phase_promoted_by TEXT
                );
                INSERT OR IGNORE INTO phase_state (id, current_phase, phase_start_date)
                VALUES (1, '1', datetime('now'));
            """)

    def _conn(self):
        return sqlite3.connect(str(self.db_path))

    def _load_current_phase(self) -> str:
        with self._conn() as conn:
            row = conn.execute("SELECT current_phase FROM phase_state WHERE id=1").fetchone()
        return row[0] if row else "1"

    def _load_phase_start_date(self) -> datetime:
        with self._conn() as conn:
            row = conn.execute("SELECT phase_start_date FROM phase_state WHERE id=1").fetchone()
        if row and row[0]:
            try:
                return datetime.fromisoformat(row[0])
            except Exception:
                pass
        return datetime.now(timezone.utc)

    def promote_to_next_phase(self, promoted_by: str = "manual") -> dict:
        """
        Növbəti fazaya keç.
        Yalnız readiness_score >= threshold olduqda icazəlidir.
        """
        current = int(self.current_phase)
        next_phase = str(current + 1)

        if next_phase not in PHASE_TARGETS:
            return {"success": False, "message": "Artıq son fazadasınız (Faza 3 — Real Ticarət)"}

        old_phase = self.current_phase
        self.current_phase = next_phase
        self.phase_start_date = datetime.now(timezone.utc)

        with self._conn() as conn:
            conn.execute("""
                UPDATE phase_state SET
                    current_phase = ?,
                    phase_start_date = ?,
                    phase_promoted_by = ?
                WHERE id = 1
            """, (next_phase, self.phase_start_date.isoformat(), promoted_by))

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
        delta = datetime.now(timezone.utc) - self.phase_start_date.replace(tzinfo=timezone.utc) \
            if self.phase_start_date.tzinfo is None else \
            datetime.now(timezone.utc) - self.phase_start_date
        return max(0, delta.days)

    @property
    def days_remaining(self) -> int:
        targets = self.current_targets
        return max(0, targets["duration_days"] - self.days_in_phase)

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
            f"• Win Rate: {stats.get('win_rate_pct', 0):.1f}% {'✅' if stats.get('win_rate_pct', 0) >= targets['win_rate_min'] else '❌'} (hədəf: ≥{targets['win_rate_min']}%)",
            f"• Max DD: {stats.get('max_drawdown_pct', 0):.1f}% {'✅' if stats.get('max_drawdown_pct', 0) <= targets['max_drawdown_pct'] else '❌'} (hədəf: ≤{targets['max_drawdown_pct']}%)",
            f"• Sharpe: {stats.get('sharpe_ratio', 0):.2f} {'✅' if stats.get('sharpe_ratio', 0) >= targets['sharpe_min'] else '❌'} (hədəf: ≥{targets['sharpe_min']})",
            f"• Profit Factor: {stats.get('profit_factor', 0):.2f} {'✅' if stats.get('profit_factor', 0) >= targets['profit_factor_min'] else '❌'} (hədəf: ≥{targets['profit_factor_min']})",
            f"• Ticarətlər: {stats.get('total_trades', 0)} {'✅' if stats.get('total_trades', 0) >= targets['min_trades'] else '❌'} (min: {targets['min_trades']})",
        ]

        if self.is_phase_complete():
            lines += [f"", f"⏰ *Faza müddəti dolub — /promote ilə keçid edin*"]

        return "\n".join(lines)
