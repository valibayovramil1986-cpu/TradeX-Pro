"""
TradeX-Pro — Weight Manager
İndikatör çəkilərinin dinamik idarəetməsi (Layer 3 yaddaş)
PostgreSQL/SQLite dəstəyi — container restart-a davamlı
"""

import json
from typing import Optional
from loguru import logger
from sqlalchemy import text

from core.signal_engine import SignalWeights
from database.db import get_db, engine, DATABASE_URL


def _is_postgres() -> bool:
    return DATABASE_URL.startswith("postgresql")


class WeightManager:
    """
    İndikatör çəkilərini ticarət nəticələrinə görə avtomatik kalibrləndirir.
    Hər 20 ticarətdən sonra analiz aparır.
    """

    DEFAULT_WEIGHTS = {
        "ema_alignment": 20.0,
        "macd_crossover": 15.0,
        "rsi_zone": 15.0,
        "volume_spike": 15.0,
        "support_resistance": 15.0,
        "bollinger_band": 10.0,
        "adx_strength": 10.0,
        "stoch_rsi": 10.0,          # 8-ci indikatör
    }

    MIN_WEIGHT = 5.0
    MAX_WEIGHT = 30.0
    ADJUSTMENT_STEP = 2.0
    MIN_SAMPLES = 15

    def __init__(self):
        self._init_db()
        self.current_weights = self._load_weights()
        logger.info(f"WeightManager işə salındı ({'PostgreSQL' if _is_postgres() else 'SQLite'}) "
                    f"— cari çəkilər: {self.current_weights}")

    def _init_db(self):
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS indicator_weights (
                    id SERIAL PRIMARY KEY,
                    weights_json TEXT NOT NULL,
                    reason TEXT,
                    trades_analyzed INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """ if _is_postgres() else """
                CREATE TABLE IF NOT EXISTS indicator_weights (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    weights_json TEXT NOT NULL,
                    reason TEXT,
                    trades_analyzed INTEGER,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS quarantined_patterns (
                    id SERIAL PRIMARY KEY,
                    pattern TEXT NOT NULL UNIQUE,
                    loss_rate REAL,
                    sample_count INTEGER,
                    quarantined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    active INTEGER DEFAULT 1
                )
            """ if _is_postgres() else """
                CREATE TABLE IF NOT EXISTS quarantined_patterns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern TEXT NOT NULL UNIQUE,
                    loss_rate REAL,
                    sample_count INTEGER,
                    quarantined_at TEXT DEFAULT (datetime('now')),
                    active INTEGER DEFAULT 1
                )
            """))
            conn.commit()

    def _load_weights(self) -> dict:
        with get_db() as db:
            row = db.execute(text("""
                SELECT weights_json FROM indicator_weights
                ORDER BY id DESC LIMIT 1
            """)).fetchone()
        if row:
            from database.db import json_col
            w = json_col(row[0])
            if isinstance(w, dict):
                return w
        return self.DEFAULT_WEIGHTS.copy()

    def get_signal_weights(self) -> SignalWeights:
        w = self.current_weights
        return SignalWeights(
            ema_alignment=w.get("ema_alignment", 20.0),
            macd_crossover=w.get("macd_crossover", 15.0),
            rsi_zone=w.get("rsi_zone", 15.0),
            volume_spike=w.get("volume_spike", 15.0),
            support_resistance=w.get("support_resistance", 15.0),
            bollinger_band=w.get("bollinger_band", 10.0),
            adx_strength=w.get("adx_strength", 10.0),
            stoch_rsi=w.get("stoch_rsi", 10.0),
        )

    def analyze_and_adjust(self, recent_trades: list) -> Optional[dict]:
        """Son N ticarətin nəticələrinə görə çəkiləri analiz et"""
        if len(recent_trades) < self.MIN_SAMPLES:
            logger.debug(f"Çəki analizi üçün kifayət qədər ticarət yoxdur ({len(recent_trades)}/{self.MIN_SAMPLES})")
            return None

        ind_map = {
            "EMA": "ema_alignment",
            "MACD": "macd_crossover",
            "RSI": "rsi_zone",
            "Volume": "volume_spike",
            "SR": "support_resistance",
            "Bollinger": "bollinger_band",
            "ADX": "adx_strength",
            "StochRSI": "stoch_rsi",    # 8-ci indikatör
        }

        ind_stats = {}
        for ind_key, weight_key in ind_map.items():
            trades_with_ind = [t for t in recent_trades if ind_key in t.get("indicators_triggered", [])]
            if len(trades_with_ind) < 5:
                continue
            wins = sum(1 for t in trades_with_ind if t.get("pnl_usd", 0) > 0)
            ind_stats[weight_key] = {
                "win_rate": wins / len(trades_with_ind),
                "sample_count": len(trades_with_ind),
            }

        if not ind_stats:
            return None

        new_weights = self.current_weights.copy()
        changes = {}

        for weight_key, stats in ind_stats.items():
            win_rate = stats["win_rate"]
            current_w = new_weights.get(weight_key, 15.0)

            if win_rate > 0.70 and stats["sample_count"] >= 10:
                new_w = min(current_w + self.ADJUSTMENT_STEP, self.MAX_WEIGHT)
                if new_w != current_w:
                    changes[weight_key] = {"old": current_w, "new": new_w, "reason": f"Win rate: {win_rate:.0%}"}
                    new_weights[weight_key] = new_w
            elif win_rate < 0.40 and stats["sample_count"] >= 10:
                new_w = max(current_w - self.ADJUSTMENT_STEP, self.MIN_WEIGHT)
                if new_w != current_w:
                    changes[weight_key] = {"old": current_w, "new": new_w, "reason": f"Win rate: {win_rate:.0%}"}
                    new_weights[weight_key] = new_w

        if changes:
            self.current_weights = new_weights
            self._save_weights(new_weights, reason=f"Auto-adjustment: {len(changes)} dəyişiklik",
                               trades_analyzed=len(recent_trades))
            logger.info(f"✅ Çəkilər yeniləndi: {changes}")
            return changes

        logger.debug("Çəki dəyişikliyi tələb edilmir")
        return None

    def apply_suggestion(self, indicator: str, direction: str, amount: float = 2.0):
        ind_map = {
            "EMA": "ema_alignment", "MACD": "macd_crossover",
            "RSI": "rsi_zone", "Volume": "volume_spike",
            "SR": "support_resistance", "Bollinger": "bollinger_band", "ADX": "adx_strength"
        }
        weight_key = ind_map.get(indicator, indicator.lower())
        if weight_key not in self.current_weights:
            return

        old = self.current_weights[weight_key]
        new = min(old + amount, self.MAX_WEIGHT) if direction == "increase" \
              else max(old - amount, self.MIN_WEIGHT)

        if new != old:
            self.current_weights[weight_key] = new
            self._save_weights(self.current_weights,
                               reason=f"Refleksiya tövsiyəsi: {indicator} {direction}")
            logger.info(f"Çəki tətbiq edildi: {weight_key}: {old} → {new}")

    def quarantine_pattern(self, pattern: str, loss_rate: float, sample_count: int):
        with get_db() as db:
            db.execute(text("""
                INSERT INTO quarantined_patterns (pattern, loss_rate, sample_count)
                VALUES (:p, :lr, :sc)
                ON CONFLICT (pattern) DO UPDATE SET
                    loss_rate = :lr, sample_count = :sc, active = 1
            """ if _is_postgres() else """
                INSERT OR REPLACE INTO quarantined_patterns (pattern, loss_rate, sample_count)
                VALUES (:p, :lr, :sc)
            """), {"p": pattern, "lr": loss_rate, "sc": sample_count})
        logger.warning(f"Nümunə karantinaya alındı: {pattern} (itki nisbəti: {loss_rate:.0%})")

    def is_quarantined(self, pattern: str) -> bool:
        with get_db() as db:
            row = db.execute(text("""
                SELECT active FROM quarantined_patterns WHERE pattern = :p AND active = 1
            """), {"p": pattern}).fetchone()
        return row is not None

    def _save_weights(self, weights: dict, reason: str = "", trades_analyzed: int = 0):
        with get_db() as db:
            db.execute(text("""
                INSERT INTO indicator_weights (weights_json, reason, trades_analyzed)
                VALUES (:w, :r, :t)
            """), {"w": json.dumps(weights), "r": reason, "t": trades_analyzed})

    def get_weight_history(self, limit: int = 10) -> list:
        with get_db() as db:
            rows = db.execute(text("""
                SELECT weights_json, reason, trades_analyzed, created_at
                FROM indicator_weights ORDER BY id DESC LIMIT :lim
            """), {"lim": limit}).fetchall()
        from database.db import json_col
        return [{"weights": json_col(r[0], {}), "reason": r[1],
                 "trades": r[2], "date": str(r[3])} for r in rows]

    @property
    def weights_display(self) -> str:
        lines = ["📊 *Cari İndikatör Çəkiləri:*"]
        for k, v in self.current_weights.items():
            default = self.DEFAULT_WEIGHTS.get(k, 0)
            change = v - default
            arrow = " ↑" if change > 0 else (" ↓" if change < 0 else "")
            lines.append(f"• {k}: {v:.1f}{arrow}")
        return "\n".join(lines)
