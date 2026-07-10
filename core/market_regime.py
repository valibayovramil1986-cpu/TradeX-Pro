"""
TradeX-Pro — Market Regime Detector
Bazarın cari vəziyyətini müəyyən edir:
  Bull / Bear / Sideways / High-Volatility / Low-Volatility
və strategiyanı buna uyğun tənzimləyir.
"""

from dataclasses import dataclass
from typing import Optional
import pandas as pd
from loguru import logger


@dataclass
class MarketRegime:
    regime: str          # "bull" | "bear" | "sideways" | "high_vol" | "low_vol"
    strength: float      # 0-1: rejimdə əminlik
    description: str
    long_bias: float     # LONG siqnallarına çarpan (0.5 – 1.5)
    short_bias: float    # SHORT siqnallarına çarpan
    vol_multiplier: float  # Risk ölçüsünə çarpan (yüksək vol → kiçik mövqe)
    signal_threshold_adj: int  # Minimum skor həddinə əlavə (bear → +5 = daha çətin keçmək)


class MarketRegimeDetector:
    """
    BTC 4h + 1D məlumatları ilə bazar rejimini müəyyən edir.
    Digər coinlər bu rejimə uyğun davranır.
    """

    # Rejim konfiqurasiyası: long_bias, short_bias, vol_mult, threshold_adj
    REGIMES = {
        "bull_strong": MarketRegime(
            regime="bull_strong", strength=0.9,
            description="Güclü Bull Market — LONG üstünlük",
            long_bias=1.3, short_bias=0.6, vol_multiplier=1.0, signal_threshold_adj=-3,
        ),
        "bull_weak": MarketRegime(
            regime="bull_weak", strength=0.6,
            description="Zəif Bull — ehtiyatlı LONG",
            long_bias=1.1, short_bias=0.8, vol_multiplier=1.0, signal_threshold_adj=0,
        ),
        "bear_strong": MarketRegime(
            regime="bear_strong", strength=0.9,
            description="Güclü Bear — SHORT üstünlük, LONG azalt",
            long_bias=0.5, short_bias=1.3, vol_multiplier=0.8, signal_threshold_adj=7,
        ),
        "bear_weak": MarketRegime(
            regime="bear_weak", strength=0.6,
            description="Zəif Bear — ehtiyatlı SHORT",
            long_bias=0.7, short_bias=1.1, vol_multiplier=0.9, signal_threshold_adj=4,
        ),
        "sideways": MarketRegime(
            regime="sideways", strength=0.7,
            description="Yan hərəkət — mean-reversion strategiyası",
            long_bias=0.9, short_bias=0.9, vol_multiplier=1.0, signal_threshold_adj=2,
        ),
        "high_vol": MarketRegime(
            regime="high_vol", strength=0.8,
            description="Yüksək Uçuculuq — mövqe ölçüsünü azalt",
            long_bias=0.8, short_bias=0.8, vol_multiplier=0.6, signal_threshold_adj=5,
        ),
        "low_vol": MarketRegime(
            regime="low_vol", strength=0.7,
            description="Aşağı Uçuculuq — partlama gözlənilir",
            long_bias=1.0, short_bias=1.0, vol_multiplier=1.2, signal_threshold_adj=0,
        ),
    }

    def detect(self, df_4h: pd.DataFrame, df_1d: Optional[pd.DataFrame] = None) -> MarketRegime:
        """
        OHLCV dataframe-indən rejimi aşkar et.
        df_4h: BTC/USDT 4h (ən azı 50 bar)
        df_1d: BTC/USDT 1D (opsional, daha dəqiq rejim üçün)
        """
        try:
            return self._analyze(df_4h, df_1d)
        except Exception as e:
            logger.warning(f"Rejim aşkarı uğursuz: {e} — sideways qəbul edildi")
            return self.REGIMES["sideways"]

    def _analyze(self, df: pd.DataFrame, df_1d: Optional[pd.DataFrame]) -> MarketRegime:
        import pandas_ta as ta
        close = df["close"]
        n = len(close)

        # ── EMA Trend ──────────────────────────────────────────
        ema20 = ta.ema(close, length=min(20, n-1))
        ema50 = ta.ema(close, length=min(50, n-1))
        ema200 = ta.ema(close, length=min(200, n-1))

        price = float(close.iloc[-1])
        e20  = float(ema20.iloc[-1])  if ema20  is not None and not ema20.isna().all()  else price
        e50  = float(ema50.iloc[-1])  if ema50  is not None and not ema50.isna().all()  else price
        e200 = float(ema200.iloc[-1]) if ema200 is not None and not ema200.isna().all() else price

        above_ema20  = price > e20
        above_ema50  = price > e50
        above_ema200 = price > e200
        ema_bullish  = sum([above_ema20, above_ema50, above_ema200])  # 0-3

        # ── ADX Trend Gücü ─────────────────────────────────────
        adx_df = ta.adx(df["high"], df["low"], close, length=14)
        adx = 0.0
        if adx_df is not None and not adx_df.empty:
            adx = float(adx_df.iloc[-1, 0])

        # ── ATR Uçuculuq ───────────────────────────────────────
        atr_series = ta.atr(df["high"], df["low"], close, length=14)
        atr = float(atr_series.iloc[-1]) if atr_series is not None else 0
        atr_pct = atr / price if price > 0 else 0

        # ── 20 günlük qiymət dəyişimi ──────────────────────────
        lookback = min(20, n - 1)
        price_20_ago = float(close.iloc[-lookback]) if lookback > 0 else price
        price_change_pct = (price - price_20_ago) / price_20_ago if price_20_ago > 0 else 0

        # ── Rejiim qərarı ──────────────────────────────────────
        # Yüksək uçuculuq → hər şeydən üstündür
        if atr_pct > 0.04:   # ATR > 4% = çox yüksək
            return self.REGIMES["high_vol"]
        if atr_pct < 0.008:  # ATR < 0.8% = çox sakit
            return self.REGIMES["low_vol"]

        # Güclü bull: EMA sıralanması + qiymət artımı + güclü ADX
        if ema_bullish == 3 and price_change_pct > 0.05 and adx > 25:
            return self.REGIMES["bull_strong"]

        # Zəif bull: əksər EMA-lar üstündə amma zəif momentum
        if ema_bullish >= 2 and price_change_pct > 0.01:
            return self.REGIMES["bull_weak"]

        # Güclü bear: hamısının altında + güclü düşüş
        if ema_bullish == 0 and price_change_pct < -0.05 and adx > 25:
            return self.REGIMES["bear_strong"]

        # Zəif bear
        if ema_bullish <= 1 and price_change_pct < -0.01:
            return self.REGIMES["bear_weak"]

        # Sideways: hərəkət az, ADX zəif
        return self.REGIMES["sideways"]

    def get_regime_for_signal(self, regime: MarketRegime, direction: str) -> dict:
        """
        Siqnal üçün rejim düzəlişlərini qaytar.
        direction: "LONG" | "SHORT"
        """
        if direction == "LONG":
            bias = regime.long_bias
        else:
            bias = regime.short_bias

        return {
            "bias": bias,
            "vol_multiplier": regime.vol_multiplier,
            "threshold_adj": regime.signal_threshold_adj,
            "description": regime.description,
        }
