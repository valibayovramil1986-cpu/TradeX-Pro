"""
TradeX-Pro — Pattern Memory
İndikatör kombinasiyalarının performans izlənməsi (Layer 2 yaddaş)
PostgreSQL/SQLite dəstəyi — container restart-a davamlı
"""

from typing import Optional
from loguru import logger
from sqlalchemy import text

from database.db import get_db, engine, DATABASE_URL


def _is_postgres() -> bool:
    return DATABASE_URL.startswith("postgresql")


class PatternMemory:
    """
    Hansı indikatör kombinasiyalarının qazandığını/itirdiyini izləyir.
    "Qızıl nümunələr" və "toksik nümunələr" müəyyənləşdirir.
    """

    GOLDEN_WIN_RATE = 0.70
    TOXIC_WIN_RATE = 0.40
    MIN_SAMPLES = 10

    def __init__(self):
        self._init_db()
        logger.info(f"PatternMemory qoşuldu ({'PostgreSQL' if _is_postgres() else 'SQLite'})")

    def _init_db(self):
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS pattern_stats (
                    pattern TEXT PRIMARY KEY,
                    win_count INTEGER DEFAULT 0,
                    loss_count INTEGER DEFAULT 0,
                    total_pnl REAL DEFAULT 0,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.commit()

    def _pattern_key(self, indicators: list) -> str:
        return "+".join(sorted(indicators)) if indicators else "unknown"

    def record_trade(self, indicators: list, pnl_usd: float):
        """Bir ticarətin nəticəsini nümunəyə əlavə et"""
        pattern = self._pattern_key(indicators)
        won = 1 if pnl_usd > 0 else 0
        lost = 0 if pnl_usd > 0 else 1

        upsert_sql = """
            INSERT INTO pattern_stats (pattern, win_count, loss_count, total_pnl)
            VALUES (:pattern, :won, :lost, :pnl)
            ON CONFLICT (pattern) DO UPDATE SET
                win_count = pattern_stats.win_count + :won,
                loss_count = pattern_stats.loss_count + :lost,
                total_pnl = pattern_stats.total_pnl + :pnl,
                last_updated = CURRENT_TIMESTAMP
        """ if _is_postgres() else """
            INSERT INTO pattern_stats (pattern, win_count, loss_count, total_pnl)
            VALUES (:pattern, :won, :lost, :pnl)
            ON CONFLICT (pattern) DO UPDATE SET
                win_count = pattern_stats.win_count + :won,
                loss_count = pattern_stats.loss_count + :lost,
                total_pnl = pattern_stats.total_pnl + :pnl,
                last_updated = CURRENT_TIMESTAMP
        """

        with get_db() as db:
            db.execute(text(upsert_sql), {
                "pattern": pattern, "won": won, "lost": lost, "pnl": pnl_usd
            })

    def get_pattern_win_rate(self, indicators: list) -> Optional[float]:
        pattern = self._pattern_key(indicators)
        with get_db() as db:
            row = db.execute(text("""
                SELECT win_count, loss_count FROM pattern_stats WHERE pattern = :p
            """), {"p": pattern}).fetchone()
        if row and (row[0] + row[1]) >= self.MIN_SAMPLES:
            return row[0] / (row[0] + row[1])
        return None

    def get_golden_patterns(self) -> list:
        """Win rate > 70% olan nümunələri qaytar"""
        with get_db() as db:
            rows = db.execute(text("""
                SELECT pattern, win_count, loss_count, total_pnl
                FROM pattern_stats
                WHERE (win_count + loss_count) >= :min
                ORDER BY (CAST(win_count AS FLOAT) / (win_count + loss_count)) DESC
                LIMIT 10
            """), {"min": self.MIN_SAMPLES}).fetchall()

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
        with get_db() as db:
            rows = db.execute(text("""
                SELECT pattern, win_count, loss_count, total_pnl
                FROM pattern_stats
                WHERE (win_count + loss_count) >= :min
            """), {"min": self.MIN_SAMPLES}).fetchall()

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
        win_rate = self.get_pattern_win_rate(indicators)
        if win_rate is None:
            return 0.0
        if win_rate >= self.GOLDEN_WIN_RATE:
            return 5.0
        elif win_rate <= self.TOXIC_WIN_RATE:
            return -10.0
        return 0.0
