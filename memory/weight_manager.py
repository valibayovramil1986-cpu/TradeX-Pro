"""
TradeX-Pro — Weight Manager
İndikatör çəkilərinin dinamik idarəetməsi (Layer 3 yaddaş)
"""

import json
import sqlite3
from pathlib import Path
from typing import Optional
from loguru import logger

from core.signal_engine import SignalWeights

DB_PATH = Path(__file__).parent.parent / "database" / "tradex.db"


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
    }

    MIN_WEIGHT = 5.0
    MAX_WEIGHT = 30.0
    ADJUSTMENT_STEP = 2.0
    MIN_SAMPLES = 15          # Analiz üçün minimum ticarət sayı

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self.current_weights = self._load_weights()
        logger.info(f"WeightManager işə salındı — cari çəkilər: {self.current_weights}")

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS indicator_weights (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    weights_json TEXT NOT NULL,
                    reason TEXT,
                    trades_analyzed INTEGER,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS quarantined_patterns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern TEXT NOT NULL UNIQUE,
                    loss_rate REAL,
                    sample_count INTEGER,
                    quarantined_at TEXT DEFAULT (datetime('now')),
                    active INTEGER DEFAULT 1
                );
            """)

    def _conn(self):
        return sqlite3.connect(str(self.db_path))

    def _load_weights(self) -> dict:
        """Verilənlər bazasından ən son çəkiləri yüklə"""
        with self._conn() as conn:
            row = conn.execute("""
                SELECT weights_json FROM indicator_weights
                ORDER BY id DESC LIMIT 1
            """).fetchone()
        if row:
            return json.loads(row[0])
        return self.DEFAULT_WEIGHTS.copy()

    def get_signal_weights(self) -> SignalWeights:
        """SignalEngine üçün SignalWeights obyekti qaytar"""
        w = self.current_weights
        return SignalWeights(
            ema_alignment=w.get("ema_alignment", 20.0),
            macd_crossover=w.get("macd_crossover", 15.0),
            rsi_zone=w.get("rsi_zone", 15.0),
            volume_spike=w.get("volume_spike", 15.0),
            support_resistance=w.get("support_resistance", 15.0),
            bollinger_band=w.get("bollinger_band", 10.0),
            adx_strength=w.get("adx_strength", 10.0),
        )

    def analyze_and_adjust(self, recent_trades: list) -> Optional[dict]:
        """
        Son N ticarətin nəticələrinə görə çəkiləri analiz et və lazım olsa düzəlt.
        """
        if len(recent_trades) < self.MIN_SAMPLES:
            logger.debug(f"Çəki analizi üçün kifayət qədər ticarət yoxdur ({len(recent_trades)}/{self.MIN_SAMPLES})")
            return None

        # Hər indikatör üçün qazanma/itirmə nisbəti hesabla
        ind_stats = {}
        indicator_names = list(self.DEFAULT_WEIGHTS.keys())

        ind_map = {
            "EMA": "ema_alignment",
            "MACD": "macd_crossover",
            "RSI": "rsi_zone",
            "Volume": "volume_spike",
            "SR": "support_resistance",
            "Bollinger": "bollinger_band",
            "ADX": "adx_strength",
        }

        for ind_key, weight_key in ind_map.items():
            trades_with_ind = [t for t in recent_trades if ind_key in t.get("indicators_triggered", [])]
            if len(trades_with_ind) < 5:
                continue
            wins = sum(1 for t in trades_with_ind if t.get("pnl_usd", 0) > 0)
            win_rate = wins / len(trades_with_ind)
            ind_stats[weight_key] = {
                "win_rate": win_rate,
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
                # Güclü indikatör — çəkini artır
                new_w = min(current_w + self.ADJUSTMENT_STEP, self.MAX_WEIGHT)
                if new_w != current_w:
                    changes[weight_key] = {"old": current_w, "new": new_w, "reason": f"Win rate: {win_rate:.0%}"}
                    new_weights[weight_key] = new_w

            elif win_rate < 0.40 and stats["sample_count"] >= 10:
                # Zəif indikatör — çəkini azalt
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
        """Refleksiya motorundan gələn tövsiyəni tətbiq et"""
        ind_map = {
            "EMA": "ema_alignment", "MACD": "macd_crossover",
            "RSI": "rsi_zone", "Volume": "volume_spike",
            "SR": "support_resistance", "Bollinger": "bollinger_band", "ADX": "adx_strength"
        }
        weight_key = ind_map.get(indicator, indicator.lower())
        if weight_key not in self.current_weights:
            return

        old = self.current_weights[weight_key]
        if direction == "increase":
            new = min(old + amount, self.MAX_WEIGHT)
        else:
            new = max(old - amount, self.MIN_WEIGHT)

        if new != old:
            self.current_weights[weight_key] = new
            self._save_weights(self.current_weights, reason=f"Refleksiya tövsiyəsi: {indicator} {direction}")
            logger.info(f"Çəki tətbiq edildi: {weight_key}: {old} → {new}")

    def quarantine_pattern(self, pattern: str, loss_rate: float, sample_count: int):
        """Zəif nümunəni karantina götür"""
        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO quarantined_patterns (pattern, loss_rate, sample_count)
                VALUES (?,?,?)
            """, (pattern, loss_rate, sample_count))
        logger.warning(f"Nümunə karantinaya alındı: {pattern} (itki nisbəti: {loss_rate:.0%})")

    def is_quarantined(self, pattern: str) -> bool:
        with self._conn() as conn:
            row = conn.execute("""
                SELECT active FROM quarantined_patterns WHERE pattern = ? AND active = 1
            """, (pattern,)).fetchone()
        return row is not None

    def _save_weights(self, weights: dict, reason: str = "", trades_analyzed: int = 0):
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO indicator_weights (weights_json, reason, trades_analyzed)
                VALUES (?,?,?)
            """, (json.dumps(weights), reason, trades_analyzed))

    def get_weight_history(self, limit: int = 10) -> list:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT weights_json, reason, trades_analyzed, created_at
                FROM indicator_weights ORDER BY id DESC LIMIT ?
            """, (limit,)).fetchall()
        return [{"weights": json.loads(r[0]), "reason": r[1],
                 "trades": r[2], "date": r[3]} for r in rows]

    @property
    def weights_display(self) -> str:
        lines = ["📊 *Cari İndikatör Çəkiləri:*"]
        defaults = self.DEFAULT_WEIGHTS
        for k, v in self.current_weights.items():
            default = defaults.get(k, 0)
            change = v - default
            arrow = " ↑" if change > 0 else (" ↓" if change < 0 else "")
            lines.append(f"• {k}: {v:.1f}{arrow}")
        return "\n".join(lines)
