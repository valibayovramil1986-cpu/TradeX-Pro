"""
TradeX-Pro — Technical Indicators Module
Bütün texniki indikatörlərin hesablanması
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional
from loguru import logger


@dataclass
class IndicatorResult:
    """Bir indikatörün nəticəsi"""
    name: str
    value: float
    signal: str          # "bullish" | "bearish" | "neutral"
    strength: float      # 0.0 – 1.0
    description: str


@dataclass
class FullAnalysis:
    """Bütün indikatörlərin tam nəticəsi"""
    symbol: str
    timeframe: str
    timestamp: str
    trend: str           # "uptrend" | "downtrend" | "sideways"
    volatility: str      # "low" | "medium" | "high"
    indicators: dict
    raw_score: float     # 0–100 texniki bal (GPT düzəlişindən əvvəl)
    adx_value: float
    atr_value: float
    current_price: float
    support_level: float
    resistance_level: float


class TechnicalIndicators:
    """
    Professional texniki analiz kitabxanası.
    pandas_ta istifadə edir.
    """

    def __init__(self):
        try:
            import pandas_ta as ta
            self.ta = ta
            logger.info("pandas_ta yükləndi ✅")
        except ImportError:
            logger.error("pandas_ta tapılmadı. 'pip install pandas-ta' işlədin.")
            raise

    # ──────────────────────────────────────────────
    # EMA — Trend İndikatoru
    # ──────────────────────────────────────────────
    def ema(self, df: pd.DataFrame, periods: list[int] = [9, 21, 50, 200]) -> dict:
        result = {}
        for p in periods:
            col = f"EMA_{p}"
            df[col] = self.ta.ema(df["close"], length=p)
            result[col] = float(df[col].iloc[-1]) if not df[col].isna().all() else None
        return result

    def ema_signal(self, ema_values: dict) -> IndicatorResult:
        """EMA xətt sıralama siqnalı (9>21>50>200 = tam bullish)"""
        vals = {k: v for k, v in ema_values.items() if v is not None}
        if len(vals) < 2:
            return IndicatorResult("EMA_Alignment", 0, "neutral", 0.0, "Kifayət qədər data yoxdur")

        ordered = ["EMA_9", "EMA_21", "EMA_50", "EMA_200"]
        available = [v for k, v in sorted(vals.items(), key=lambda x: int(x[0].split("_")[1]))]

        bullish_count = sum(1 for i in range(len(available) - 1) if available[i] > available[i + 1])
        bearish_count = sum(1 for i in range(len(available) - 1) if available[i] < available[i + 1])
        total = len(available) - 1

        if bullish_count == total:
            return IndicatorResult("EMA_Alignment", 20, "bullish", 1.0,
                                   "Tam bullish sıralama (9>21>50>200)")
        elif bearish_count == total:
            return IndicatorResult("EMA_Alignment", 20, "bearish", 1.0,
                                   "Tam bearish sıralama (9<21<50<200)")
        elif bullish_count > bearish_count:
            strength = bullish_count / total
            return IndicatorResult("EMA_Alignment", 10, "bullish", strength,
                                   f"Qismən bullish ({bullish_count}/{total})")
        elif bearish_count > bullish_count:
            strength = bearish_count / total
            return IndicatorResult("EMA_Alignment", 10, "bearish", strength,
                                   f"Qismən bearish ({bearish_count}/{total})")
        else:
            return IndicatorResult("EMA_Alignment", 0, "neutral", 0.0, "Qarışıq EMA siqnalı")

    # ──────────────────────────────────────────────
    # MACD
    # ──────────────────────────────────────────────
    def macd(self, df: pd.DataFrame) -> tuple[dict, dict]:
        """MACD hesabla. (cari_data, əvvəlki_data) tuple-u qaytar.
        Bu ikinci dəyər crossover aşkarı üçün macd_signal()-a ötürülür."""
        macd_df = self.ta.macd(df["close"], fast=12, slow=26, signal=9)
        empty = {"macd": None, "signal": None, "histogram": None}
        if macd_df is None or macd_df.empty or len(macd_df) < 2:
            return empty, empty
        current = {
            "macd": float(macd_df.iloc[-1, 0]),
            "signal": float(macd_df.iloc[-1, 1]),
            "histogram": float(macd_df.iloc[-1, 2]),
        }
        prev = {
            "macd": float(macd_df.iloc[-2, 0]),
            "signal": float(macd_df.iloc[-2, 1]),
            "histogram": float(macd_df.iloc[-2, 2]),
        }
        return current, prev

    def macd_signal(self, macd_data: dict, prev_macd_data: Optional[dict] = None) -> IndicatorResult:
        if macd_data["macd"] is None:
            return IndicatorResult("MACD", 0, "neutral", 0.0, "MACD data yoxdur")

        macd_val = macd_data["macd"]
        signal_val = macd_data["signal"]
        hist = macd_data["histogram"]

        # Crossover yoxla
        if prev_macd_data and prev_macd_data.get("macd") and prev_macd_data.get("signal"):
            prev_above = prev_macd_data["macd"] > prev_macd_data["signal"]
            curr_above = macd_val > signal_val
            if not prev_above and curr_above:
                return IndicatorResult("MACD", 15, "bullish", 1.0, "Bullish crossover! MACD signal xəttini kəsdi")
            elif prev_above and not curr_above:
                return IndicatorResult("MACD", 15, "bearish", 1.0, "Bearish crossover! MACD signal xəttini aşağı kəsdi")

        # Crossover yoxdursa momentum yoxla
        if macd_val > signal_val and hist > 0:
            strength = min(abs(hist) / 0.01, 1.0)
            return IndicatorResult("MACD", 10, "bullish", strength, f"MACD signal üstündə (histogram: {hist:.4f})")
        elif macd_val < signal_val and hist < 0:
            strength = min(abs(hist) / 0.01, 1.0)
            return IndicatorResult("MACD", 10, "bearish", strength, f"MACD signal altında (histogram: {hist:.4f})")
        else:
            return IndicatorResult("MACD", 0, "neutral", 0.0, "MACD neytral vəziyyətdə")

    # ──────────────────────────────────────────────
    # RSI
    # ──────────────────────────────────────────────
    def rsi(self, df: pd.DataFrame, period: int = 14) -> float:
        rsi_series = self.ta.rsi(df["close"], length=period)
        return float(rsi_series.iloc[-1]) if rsi_series is not None and not rsi_series.isna().all() else 50.0

    def rsi_signal(self, rsi_value: float) -> IndicatorResult:
        if rsi_value <= 30:
            strength = (30 - rsi_value) / 30
            return IndicatorResult("RSI", 15, "bullish", strength,
                                   f"RSI oversold zonasında ({rsi_value:.1f}) — güclü alış siqnalı")
        elif rsi_value >= 70:
            strength = (rsi_value - 70) / 30
            return IndicatorResult("RSI", 15, "bearish", strength,
                                   f"RSI overbought zonasında ({rsi_value:.1f}) — güclü satış siqnalı")
        elif 30 < rsi_value <= 45:
            return IndicatorResult("RSI", 10, "bullish", 0.5,
                                   f"RSI əlverişli alış zonasında ({rsi_value:.1f})")
        elif 55 <= rsi_value < 70:
            return IndicatorResult("RSI", 10, "bearish", 0.5,
                                   f"RSI əlverişli satış zonasında ({rsi_value:.1f})")
        else:
            return IndicatorResult("RSI", 0, "neutral", 0.0,
                                   f"RSI neytral zonada ({rsi_value:.1f})")

    # ──────────────────────────────────────────────
    # ADX — Trend Gücü Filtri
    # ──────────────────────────────────────────────
    def adx(self, df: pd.DataFrame, period: int = 14) -> dict:
        adx_df = self.ta.adx(df["high"], df["low"], df["close"], length=period)
        if adx_df is None or adx_df.empty:
            return {"adx": 0, "dmp": 0, "dmn": 0}
        cols = adx_df.columns.tolist()
        return {
            "adx": float(adx_df[cols[0]].iloc[-1]),
            "dmp": float(adx_df[cols[1]].iloc[-1]),
            "dmn": float(adx_df[cols[2]].iloc[-1]),
        }

    def adx_signal(self, adx_data: dict) -> IndicatorResult:
        adx_val = adx_data.get("adx", 0)
        dmp = adx_data.get("dmp", 0)
        dmn = adx_data.get("dmn", 0)

        if adx_val >= 40:
            direction = "bullish" if dmp > dmn else "bearish"
            return IndicatorResult("ADX", 10, direction, 1.0,
                                   f"Çox güclü trend (ADX={adx_val:.1f})")
        elif adx_val >= 25:
            direction = "bullish" if dmp > dmn else "bearish"
            return IndicatorResult("ADX", 10, direction, 0.7,
                                   f"Güclü trend (ADX={adx_val:.1f})")
        elif adx_val >= 20:
            direction = "bullish" if dmp > dmn else "bearish"
            return IndicatorResult("ADX", 5, direction, 0.4,
                                   f"Orta trend (ADX={adx_val:.1f})")
        else:
            return IndicatorResult("ADX", 0, "neutral", 0.0,
                                   f"Zəif/yoxsuz trend (ADX={adx_val:.1f}) — trade tövsiyyə edilmir")

    # ──────────────────────────────────────────────
    # Bollinger Bands
    # ──────────────────────────────────────────────
    def bollinger_bands(self, df: pd.DataFrame) -> dict:
        bb_df = self.ta.bbands(df["close"], length=20, std=2.0)
        if bb_df is None or bb_df.empty:
            return {"upper": None, "mid": None, "lower": None, "bandwidth": None}
        cols = bb_df.columns.tolist()
        lower = float(bb_df[cols[0]].iloc[-1])
        mid = float(bb_df[cols[1]].iloc[-1])
        upper = float(bb_df[cols[2]].iloc[-1])
        bandwidth = (upper - lower) / mid if mid != 0 else 0
        return {"upper": upper, "mid": mid, "lower": lower, "bandwidth": bandwidth}

    def bollinger_signal(self, bb_data: dict, current_price: float) -> IndicatorResult:
        if bb_data["upper"] is None:
            return IndicatorResult("Bollinger", 0, "neutral", 0.0, "BB data yoxdur")

        upper, mid, lower = bb_data["upper"], bb_data["mid"], bb_data["lower"]
        band_range = upper - lower

        if band_range == 0:
            return IndicatorResult("Bollinger", 0, "neutral", 0.0, "BB sıxılmış vəziyyətdə")

        position = (current_price - lower) / band_range  # 0=alt, 1=üst

        if current_price <= lower:
            return IndicatorResult("Bollinger", 10, "bullish", 1.0,
                                   f"Qiymət alt banda toxundu — geri dönüş ehtimalı yüksək")
        elif current_price >= upper:
            return IndicatorResult("Bollinger", 10, "bearish", 1.0,
                                   f"Qiymət üst banda toxundu — geri dönüş ehtimalı yüksək")
        elif position < 0.2:
            return IndicatorResult("Bollinger", 7, "bullish", 0.6,
                                   f"Qiymət alt banda yaxın (pozisiya: {position:.0%})")
        elif position > 0.8:
            return IndicatorResult("Bollinger", 7, "bearish", 0.6,
                                   f"Qiymət üst banda yaxın (pozisiya: {position:.0%})")
        else:
            return IndicatorResult("Bollinger", 0, "neutral", 0.0,
                                   f"Qiymət BB ortasında (pozisiya: {position:.0%})")

    # ──────────────────────────────────────────────
    # Volume Analizi
    # ──────────────────────────────────────────────
    def volume_signal(self, df: pd.DataFrame) -> IndicatorResult:
        if "volume" not in df.columns or len(df) < 20:
            return IndicatorResult("Volume", 0, "neutral", 0.0, "Volume data yoxdur")

        avg_volume = df["volume"].rolling(20).mean().iloc[-1]
        current_volume = df["volume"].iloc[-1]
        ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
        price_change = df["close"].iloc[-1] - df["close"].iloc[-2]

        if ratio >= 2.5:
            direction = "bullish" if price_change > 0 else "bearish"
            return IndicatorResult("Volume", 15, direction, 1.0,
                                   f"Həcm partlaması! {ratio:.1f}x ortalama")
        elif ratio >= 1.5:
            direction = "bullish" if price_change > 0 else "bearish"
            return IndicatorResult("Volume", 10, direction, 0.7,
                                   f"Yüksək həcm ({ratio:.1f}x ortalama)")
        elif ratio >= 1.2:
            direction = "bullish" if price_change > 0 else "bearish"
            return IndicatorResult("Volume", 5, direction, 0.4,
                                   f"Orta-yüksək həcm ({ratio:.1f}x)")
        else:
            return IndicatorResult("Volume", 0, "neutral", 0.0,
                                   f"Normal həcm ({ratio:.1f}x ortalama)")

    # ──────────────────────────────────────────────
    # ATR — Uçuculuq Ölçümü
    # ──────────────────────────────────────────────
    def atr(self, df: pd.DataFrame, period: int = 14) -> float:
        atr_series = self.ta.atr(df["high"], df["low"], df["close"], length=period)
        return float(atr_series.iloc[-1]) if atr_series is not None and not atr_series.isna().all() else 0.0

    # ──────────────────────────────────────────────
    # Support / Resistance (Pivot Nöqtələri)
    # ──────────────────────────────────────────────
    def support_resistance(self, df: pd.DataFrame, lookback: int = 20) -> dict:
        if len(df) < lookback:
            return {"support": df["low"].min(), "resistance": df["high"].max()}

        recent = df.tail(lookback)
        current_price = df["close"].iloc[-1]

        # Dəstək: son minimumlar
        lows = recent["low"].nsmallest(3).values
        support = float(np.mean(lows[lows < current_price]) if any(lows < current_price) else lows.min())

        # Müqavimət: son maksimumlar
        highs = recent["high"].nlargest(3).values
        resistance = float(np.mean(highs[highs > current_price]) if any(highs > current_price) else highs.max())

        return {"support": support, "resistance": resistance}

    def sr_signal(self, current_price: float, sr_data: dict) -> IndicatorResult:
        support = sr_data["support"]
        resistance = sr_data["resistance"]
        sr_range = resistance - support

        if sr_range == 0:
            return IndicatorResult("Support_Resistance", 0, "neutral", 0.0, "S/R aralığı sıfır")

        position = (current_price - support) / sr_range

        # Dəstəyə yaxın = alış fürsəti
        if position <= 0.1:
            return IndicatorResult("Support_Resistance", 15, "bullish", 1.0,
                                   f"Güclü dəstək zonasında (${support:,.2f})")
        elif position <= 0.2:
            return IndicatorResult("Support_Resistance", 10, "bullish", 0.6,
                                   f"Dəstəyə yaxın (${support:,.2f})")
        # Müqavimətə yaxın = satış fürsəti
        elif position >= 0.9:
            return IndicatorResult("Support_Resistance", 15, "bearish", 1.0,
                                   f"Güclü müqavimət zonasında (${resistance:,.2f})")
        elif position >= 0.8:
            return IndicatorResult("Support_Resistance", 10, "bearish", 0.6,
                                   f"Müqavimətə yaxın (${resistance:,.2f})")
        else:
            return IndicatorResult("Support_Resistance", 0, "neutral", 0.0,
                                   f"S/R aralığının ortasında ({position:.0%})")

    # ──────────────────────────────────────────────
    # Stochastic RSI
    # ──────────────────────────────────────────────
    def stoch_rsi(self, df: pd.DataFrame) -> dict:
        stoch_df = self.ta.stochrsi(df["close"])
        if stoch_df is None or stoch_df.empty:
            return {"k": 50.0, "d": 50.0}
        cols = stoch_df.columns.tolist()
        return {
            "k": float(stoch_df[cols[0]].iloc[-1]),
            "d": float(stoch_df[cols[1]].iloc[-1]) if len(cols) > 1 else 50.0,
        }

    def stoch_rsi_signal(self, stoch_data: dict) -> IndicatorResult:
        """
        Stochastic RSI siqnalı.
        K < 20 + D < 20 = oversold (bullish), K > 80 + D > 80 = overbought (bearish).
        K > D crossover = momentum siqnalı.
        """
        k = stoch_data.get("k", 50.0)
        d = stoch_data.get("d", 50.0)

        # Oversold zonada hər ikisi
        if k <= 20 and d <= 20:
            strength = (20 - min(k, d)) / 20
            return IndicatorResult("StochRSI", 10, "bullish", min(strength, 1.0),
                                   f"StochRSI oversold zonada ({k:.1f}/{d:.1f}) — alış siqnalı")
        # Overbought zonada hər ikisi
        elif k >= 80 and d >= 80:
            strength = (max(k, d) - 80) / 20
            return IndicatorResult("StochRSI", 10, "bearish", min(strength, 1.0),
                                   f"StochRSI overbought zonada ({k:.1f}/{d:.1f}) — satış siqnalı")
        # Bullish crossover (K aşağıdan D-ni kəsdi, 50-dən aşağıda)
        elif k > d and k <= 50:
            return IndicatorResult("StochRSI", 5, "bullish", 0.5,
                                   f"StochRSI bullish momentum ({k:.1f} > {d:.1f})")
        # Bearish crossover (K yuxarıdan D-ni kəsdi, 50-dən yuxarıda)
        elif k < d and k >= 50:
            return IndicatorResult("StochRSI", 5, "bearish", 0.5,
                                   f"StochRSI bearish momentum ({k:.1f} < {d:.1f})")
        else:
            return IndicatorResult("StochRSI", 0, "neutral", 0.0,
                                   f"StochRSI neytral zonada ({k:.1f}/{d:.1f})")

    # ──────────────────────────────────────────────
    # Tam Analiz — Bütün İndikatörləri Birləşdir
    # ──────────────────────────────────────────────
    def full_analysis(self, df: pd.DataFrame, symbol: str, timeframe: str,
                      weight_overrides: Optional[dict] = None) -> FullAnalysis:
        """
        Bütün indikatörləri hesabla və FullAnalysis obyekti qaytar.
        weight_overrides: WeightManager-dən gələn dinamik çəkilər
        """
        if len(df) < 50:
            logger.warning(f"{symbol} üçün kifayət qədər data yoxdur ({len(df)} bar)")

        current_price = float(df["close"].iloc[-1])

        # Hesablamalar
        ema_vals = self.ema(df)
        macd_vals, prev_macd_vals = self.macd(df)   # cari + əvvəlki (crossover üçün)
        rsi_val = self.rsi(df)
        adx_vals = self.adx(df)
        bb_vals = self.bollinger_bands(df)
        sr_vals = self.support_resistance(df)
        atr_val = self.atr(df)
        stoch_vals = self.stoch_rsi(df)             # 8-ci indikatör

        # Siqnallar
        ema_res = self.ema_signal(ema_vals)
        macd_res = self.macd_signal(macd_vals, prev_macd_vals)  # crossover işlənir
        rsi_res = self.rsi_signal(rsi_val)
        adx_res = self.adx_signal(adx_vals)
        bb_res = self.bollinger_signal(bb_vals, current_price)
        vol_res = self.volume_signal(df)
        sr_res = self.sr_signal(current_price, sr_vals)
        stoch_res = self.stoch_rsi_signal(stoch_vals)

        indicators = {
            "EMA": ema_res,
            "MACD": macd_res,
            "RSI": rsi_res,
            "ADX": adx_res,
            "Bollinger": bb_res,
            "Volume": vol_res,
            "SR": sr_res,
            "StochRSI": stoch_res,              # 8-ci indikatör aktiv edildi
        }

        # Siqnal sayı (bullish vs bearish)
        bullish = sum(1 for r in indicators.values() if r.signal == "bullish")
        bearish = sum(1 for r in indicators.values() if r.signal == "bearish")

        # Əsas bal hesabla
        total_score = 0.0
        for ind_result in indicators.values():
            # Uyğun direction-a görə bal ver
            dominant = "bullish" if bullish >= bearish else "bearish"
            if ind_result.signal == dominant:
                total_score += ind_result.value

        # ADX filteri — ADX < 20 isə balı 30% azalt
        if adx_vals.get("adx", 0) < 20:
            total_score *= 0.7

        # Trend müəyyənləşdir
        if bullish > bearish + 1:
            trend = "uptrend"
        elif bearish > bullish + 1:
            trend = "downtrend"
        else:
            trend = "sideways"

        # Volatilliyi müəyyənləşdir
        if atr_val > current_price * 0.03:
            volatility = "high"
        elif atr_val > current_price * 0.01:
            volatility = "medium"
        else:
            volatility = "low"

        return FullAnalysis(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=pd.Timestamp.now(tz="UTC").isoformat(),
            trend=trend,
            volatility=volatility,
            indicators=indicators,
            raw_score=min(total_score, 100.0),
            adx_value=adx_vals.get("adx", 0),
            atr_value=atr_val,
            current_price=current_price,
            support_level=sr_vals["support"],
            resistance_level=sr_vals["resistance"],
        )
