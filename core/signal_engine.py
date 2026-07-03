"""
TradeX-Pro — Signal Engine
Siqnal yaratma, ballandırma, filtrləmə
"""

from dataclasses import dataclass, field
from typing import Optional
from loguru import logger

from core.indicators import TechnicalIndicators, FullAnalysis


@dataclass
class TradeSignal:
    """Bir ticarət siqnalının tam təsviri"""
    symbol: str
    direction: str              # "LONG" | "SHORT" | "NO_TRADE"
    technical_score: float      # 0–100 texniki bal
    gpt_adjustment: float       # GPT-4-dən gələn ±20 bal
    final_score: float          # technical_score + gpt_adjustment
    entry_zone_low: float
    entry_zone_high: float
    stop_loss: float
    tp1: float
    tp2: float
    tp3: float
    risk_reward_tp1: float
    risk_reward_tp2: float
    atr: float
    trend: str
    volatility: str
    indicators_triggered: list[str]
    signal_strength: str        # "STRONG" | "MODERATE" | "WEAK" | "NONE"
    reasoning: str              # GPT-4 izahatı
    gpt_context: str            # GPT-4 kontekst izahatı
    timestamp: str
    timeframe: str
    market_condition: str
    proceed: bool               # GPT-4 icazəsi


@dataclass
class SignalWeights:
    """İndikatör çəkiləri (dinamik, WeightManager tərəfindən yenilənir)"""
    ema_alignment: float = 20.0
    macd_crossover: float = 15.0
    rsi_zone: float = 15.0
    volume_spike: float = 15.0
    support_resistance: float = 15.0
    bollinger_band: float = 10.0
    adx_strength: float = 10.0
    stoch_rsi: float = 10.0         # 8-ci indikatör

    def total(self) -> float:
        return (self.ema_alignment + self.macd_crossover + self.rsi_zone +
                self.volume_spike + self.support_resistance +
                self.bollinger_band + self.adx_strength + self.stoch_rsi)


class SignalEngine:
    """
    Əsas siqnal mühərriki.
    Texniki analiz → Bal → Filtr → Siqnal
    """

    STRONG_THRESHOLD = 75.0
    MODERATE_THRESHOLD = 60.0

    def __init__(self, weights: Optional[SignalWeights] = None):
        self.indicators = TechnicalIndicators()
        self.weights = weights or SignalWeights()
        logger.info("SignalEngine işə salındı ✅")

    def update_weights(self, new_weights: SignalWeights):
        """WeightManager-dən gələn yeni çəkiləri tətbiq et"""
        self.weights = new_weights
        logger.info(f"Çəkilər yeniləndi: {new_weights}")

    # ──────────────────────────────────────────────
    # Siqnal Hesablama Əsas Metodu
    # ──────────────────────────────────────────────
    def analyze(self, df, symbol: str, timeframe: str = "1h") -> TradeSignal:
        """
        OHLCV dataframe-i analiz et və TradeSignal qaytar.
        Bu metod GPT-4 çağırışı etmir — yalnız texniki analiz.
        GPT-4 əlavəsi SignalContextualizer tərəfindən edilir.
        """
        import pandas as pd
        from datetime import datetime, timezone

        analysis: FullAnalysis = self.indicators.full_analysis(df, symbol, timeframe)
        current_price = analysis.current_price
        atr = analysis.atr_value

        # İndikatör siqnallarını topla
        bullish_inds = []
        bearish_inds = []
        for name, result in analysis.indicators.items():
            if result.signal == "bullish":
                bullish_inds.append(name)
            elif result.signal == "bearish":
                bearish_inds.append(name)

        # Əsas istiqaməti müəyyənləşdir
        if len(bullish_inds) > len(bearish_inds):
            direction = "LONG"
            triggered = bullish_inds
        elif len(bearish_inds) > len(bullish_inds):
            direction = "SHORT"
            triggered = bearish_inds
        else:
            # Bərabərlik — NO_TRADE
            return self._no_trade_signal(symbol, timeframe, analysis, "Bərabər bullish/bearish siqnallar")

        # Bal hesabla
        raw_score = analysis.raw_score

        # Zəif trend — skoru azalt
        if analysis.adx_value < 15:
            raw_score *= 0.5
            logger.debug(f"{symbol}: ADX çox zəif ({analysis.adx_value:.1f}), bal azaldıldı")

        # Yüksək uçuculuq — ehtiyatlı ol
        if analysis.volatility == "high":
            raw_score *= 0.85

        # Entry zone, SL, TP hesabla
        if direction == "LONG":
            entry_low = current_price * 0.999
            entry_high = current_price * 1.001
            stop_loss = current_price - (1.5 * atr)
            tp1 = current_price + (1.5 * atr * 1.5)   # 1:1.5 RR
            tp2 = current_price + (1.5 * atr * 2.5)   # 1:2.5 RR
            tp3 = current_price + (1.5 * atr * 4.0)   # 1:4.0 RR
        else:  # SHORT
            entry_low = current_price * 0.999
            entry_high = current_price * 1.001
            stop_loss = current_price + (1.5 * atr)
            tp1 = current_price - (1.5 * atr * 1.5)
            tp2 = current_price - (1.5 * atr * 2.5)
            tp3 = current_price - (1.5 * atr * 4.0)

        risk = abs(current_price - stop_loss)
        rr_tp1 = abs(tp1 - current_price) / risk if risk > 0 else 0
        rr_tp2 = abs(tp2 - current_price) / risk if risk > 0 else 0

        # Siqnal gücü
        if raw_score >= self.STRONG_THRESHOLD:
            strength = "STRONG"
        elif raw_score >= self.MODERATE_THRESHOLD:
            strength = "MODERATE"
        else:
            strength = "WEAK"

        # Bazar şəraiti
        market_condition = f"{analysis.trend}_{analysis.volatility}_volatility"

        reasoning = self._build_reasoning(direction, triggered, raw_score, analysis)

        return TradeSignal(
            symbol=symbol,
            direction=direction,
            technical_score=raw_score,
            gpt_adjustment=0.0,         # GPT hələ çağırılmayıb
            final_score=raw_score,
            entry_zone_low=entry_low,
            entry_zone_high=entry_high,
            stop_loss=stop_loss,
            tp1=tp1,
            tp2=tp2,
            tp3=tp3,
            risk_reward_tp1=rr_tp1,
            risk_reward_tp2=rr_tp2,
            atr=atr,
            trend=analysis.trend,
            volatility=analysis.volatility,
            indicators_triggered=triggered,
            signal_strength=strength,
            reasoning=reasoning,
            gpt_context="",             # GPT sonra dolduracaq
            timestamp=datetime.now(timezone.utc).isoformat(),
            timeframe=timeframe,
            market_condition=market_condition,
            proceed=raw_score >= self.MODERATE_THRESHOLD,
        )

    # ──────────────────────────────────────────────
    # Köməkçi Metodlar
    # ──────────────────────────────────────────────
    def _no_trade_signal(self, symbol, timeframe, analysis, reason) -> TradeSignal:
        from datetime import datetime, timezone
        return TradeSignal(
            symbol=symbol,
            direction="NO_TRADE",
            technical_score=0.0,
            gpt_adjustment=0.0,
            final_score=0.0,
            entry_zone_low=0.0,
            entry_zone_high=0.0,
            stop_loss=0.0,
            tp1=0.0, tp2=0.0, tp3=0.0,
            risk_reward_tp1=0.0,
            risk_reward_tp2=0.0,
            atr=analysis.atr_value,
            trend=analysis.trend,
            volatility=analysis.volatility,
            indicators_triggered=[],
            signal_strength="NONE",
            reasoning=reason,
            gpt_context="",
            timestamp=datetime.now(timezone.utc).isoformat(),
            timeframe=timeframe,
            market_condition=f"{analysis.trend}_{analysis.volatility}_volatility",
            proceed=False,
        )

    def _build_reasoning(self, direction: str, triggered: list, score: float,
                         analysis: FullAnalysis) -> str:
        ind_str = ", ".join(triggered)
        return (
            f"{direction} siqnalı | Bal: {score:.1f}/100 | "
            f"Trend: {analysis.trend} | Uçuculuq: {analysis.volatility} | "
            f"ADX: {analysis.adx_value:.1f} | ATR: {analysis.atr_value:.4f} | "
            f"Tetiklənən indikatörler: {ind_str}"
        )

    def apply_gpt_adjustment(self, signal: TradeSignal, adjustment: float,
                             gpt_context: str, proceed: bool) -> TradeSignal:
        """GPT-4-dən gələn düzəlişi siqnala tətbiq et.

        Qərar məntiqi:
        - Giriş qapısı: texniki bal ≥ MODERATE_THRESHOLD AND GPT proceed=True.
        - final_score yalnız display/journal üçün saxlanılır, qapı rolunu oynamır.
        - Bu sayədə makro penaltilər (məs. "Extreme Fear" → -10) texniki cəhətdən
          keçərli siqnalları bloklamır; GPT yalnız açıq "proceed=False" ilə bloklaya bilər.
        """
        signal.gpt_adjustment = adjustment
        signal.final_score = min(max(signal.technical_score + adjustment, 0), 100)
        signal.gpt_context = gpt_context

        # Giriş qapısı: texniki bal keçərsə VƏ GPT açıq "proceed=False" deməyibsə
        signal.proceed = (signal.technical_score >= self.MODERATE_THRESHOLD) and proceed

        # Güc final_score əsasında (göstərmək + journal üçün)
        if signal.final_score >= self.STRONG_THRESHOLD:
            signal.signal_strength = "STRONG"
        elif signal.final_score >= self.MODERATE_THRESHOLD:
            signal.signal_strength = "MODERATE"
        else:
            signal.signal_strength = "WEAK"
        # Not: WEAK görünsə də proceed=True ola bilər

        return signal
