"""
TradeX-Pro — Pattern Memory
İndikatör kombinasiyalarının performans izlənməsi (Layer 2 yaddaş)
"""

import json
import sqlite3
from pathlib import Path
from typing import Optional
from loguru import logger

DB_PATH = Path(__file__).parent.parent / "database" / "tradex.db"


class PatternMemory:
    """
    Hansı indikatör kombinasiyalarının qazandığını/itirdiyini izləyir.
    "Qızıl nümunələr" və "toksik nümunələr" müəyyənləşdirir.
    """

    GOLDEN_WIN_RATE = 0.70
    TOXIC_WIN_RATE = 0.40
    MIN_SAMPLES = 10

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS pattern_stats (
                    pattern TEXT PRIMARY KEY,
                    win_count INTEGER DEFAULT 0,
                    loss_count INTEGER DEFAULT 0,
                    total_pnl REAL DEFAULT 0,
                    last_updated TEXT DEFAULT (datetime('now'))
                );
            """)

    def _conn(self):
        return sqlite3.connect(str(self.db_path))

    def _pattern_key(self, indicators: list) -> str:
        """İndikatör siyahısından unikal açar yarat"""
        return "+".join(sorted(indicators))

    def record_trade(self, indicators: list, pnl_usd: float):
        """Bir ticarətin nəticəsini nümunəyə əlavə et"""
        pattern = self._pattern_key(indicators)
        won = 1 if pnl_usd > 0 else 0
        lost = 0 if pnl_usd > 0 else 1
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO pattern_stats (pattern, win_count, loss_count, total_pnl)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(pattern) DO UPDATE SET
                    win_count = win_count + excluded.win_count,
                    loss_count = loss_count + excluded.loss_count,
                    total_pnl = total_pnl + excluded.total_pnl,
                    last_updated = datetime('now')
            """, (pattern, won, lost, pnl_usd))

    def get_pattern_win_rate(self, indicators: list) -> Optional[float]:
        """Bu indikatör kombinasiyasının tarixdəki qazanma nisbəti"""
        pattern = self._pattern_key(indicators)
        with self._conn() as conn:
            row = conn.execute("""
                SELECT win_count, loss_count FROM pattern_stats WHERE pattern = ?
            """, (pattern,)).fetchone()
        if row and (row[0] + row[1]) >= self.MIN_SAMPLES:
            return row[0] / (row[0] + row[1])
        return None

    def get_golden_patterns(self) -> list:
        """Win rate > 70% olan nümunələri qaytar"""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT pattern, win_count, loss_count, total_pnl
                FROM pattern_stats
                WHERE (win_count + loss_count) >= ?
                ORDER BY (CAST(win_count AS REAL) / (win_count + loss_count)) DESC
                LIMIT 10
            """, (self.MIN_SAMPLES,)).fetchall()
        golden = []
        for r in rows:
            total = r[1] + r[2]
            win_rate = r[1] / total if total > 0 else 0
            if win_rate >= self.GOLDEN_WIN_RATE:
                golden.append({
                    "pattern": r[0], "win_rate": round(win_rate * 100, 1),
                    "total_trades": total, "total_pnl": round(r[3], 2)
                })
        return golden

    def get_toxic_patterns(self) -> list:
        """Win rate < 40% olan nümunələri qaytar"""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT pattern, win_count, loss_count, total_pnl
                FROM pattern_stats
                WHERE (win_count + loss_count) >= ?
            """, (self.MIN_SAMPLES,)).fetchall()
        toxic = []
        for r in rows:
            total = r[1] + r[2]
            win_rate = r[1] / total if total > 0 else 0
            if win_rate <= self.TOXIC_WIN_RATE:
                toxic.append({
                    "pattern": r[0], "win_rate": round(win_rate * 100, 1),
                    "total_trades": total, "total_pnl": round(r[3], 2)
                })
        return sorted(toxic, key=lambda x: x["win_rate"])

    def pattern_score_adjustment(self, indicators: list) -> float:
        """
        Bu nümunəyə əsasən siqnal balına düzəliş qaytarır.
        Qızıl nümunə: +5, Toksik nümunə: -10, Bilinməyən: 0
        """
        win_rate = self.get_pattern_win_rate(indicators)
        if win_rate is None:
            return 0.0
        if win_rate >= self.GOLDEN_WIN_RATE:
            return 5.0
        elif win_rate <= self.TOXIC_WIN_RATE:
            return -10.0
        return 0.0
