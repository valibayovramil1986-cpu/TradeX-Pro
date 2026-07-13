"""
TradeX-Pro — Signal Engine (v2 — Multi-Agent)
Siqnal yaratma, ballandırma, filtrləmə

5 faktorlu skor (Point 1):
  Technical(40%) + OrderFlow(15%) + Sentiment(15%) + OnChain(10%) + AI(20%)
"""

from dataclasses import dataclass, field
from typing import Optional
from loguru import logger

from core.indicators import (
    TechnicalIndicators, FullAnalysis,
    calculate_order_flow_score, get_coin_reputation_adj,
)


@dataclass
class TradeSignal:
    """Bir ticarət siqnalının tam təsviri"""
    symbol: str
    direction: str              # "LONG" | "SHORT" | "NO_TRADE"
    technical_score: float      # 0–100 texniki bal
    gpt_adjustment: float       # GPT-4-dən gələn ±20 bal
    final_score: float          # 5-faktorlu birləşik skor
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
    reasoning: str
    gpt_context: str
    timestamp: str
    timeframe: str
    market_condition: str
    proceed: bool
    # Yeni çox-faktorlu sahələr (v2)
    order_flow_score: float = 50.0
    macro_score: float = 50.0
    confidence_score: float = 0.0
    position_tier: str = "skip"    # skip | watchlist | small | normal | aggressive
    mtf_confluence: bool = False
    market_regime: str = "sideways"
    coin_reputation: int = 75


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

    def __init__(self, weights: Optional[SignalWeights] = None,
                 moderate_threshold: float = None,
                 strong_threshold: float = None):
        self.indicators = TechnicalIndicators()
        self.weights = weights or SignalWeights()
        # Eşiklər .env-dən idarə oluna bilər (SIGNAL_THRESHOLD / STRONG_SIGNAL_THRESHOLD)
        if moderate_threshold is not None:
            self.MODERATE_THRESHOLD = float(moderate_threshold)
        if strong_threshold is not None:
            self.STRONG_THRESHOLD = float(strong_threshold)
        logger.info(f"SignalEngine işə salındı ✅ "
                    f"(eşiklər: moderate={self.MODERATE_THRESHOLD:.0f}, "
                    f"strong={self.STRONG_THRESHOLD:.0f})")

    def update_weights(self, new_weights: SignalWeights):
        """WeightManager-dən gələn yeni çəkiləri tətbiq et"""
        self.weights = new_weights
        logger.info(f"Çəkilər yeniləndi: {new_weights}")

    # ──────────────────────────────────────────────
    # Siqnal Hesablama Əsas Metodu
    # ──────────────────────────────────────────────
    def analyze(self, df, symbol: str, timeframe: str = "1h",
                order_book: Optional[dict] = None) -> TradeSignal:
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

        # ── Order Flow hesabla (Point 9, 10) ──────────────────────
        of_result = calculate_order_flow_score(df, order_book=order_book)
        order_flow_score = of_result.get("order_flow_score", 50.0)

        # ── Coin reputasiya düzəlişi (Point 12) ───────────────────
        coin_rep_adj = get_coin_reputation_adj(symbol)
        coin_reputation = 60 + coin_rep_adj * 10  # proxy reputasiya dəyəri

        # İndikatör siqnallarını topla
        bullish_inds = []
        bearish_inds = []
        for name, result in analysis.indicators.items():
            if result.signal == "bullish":
                bullish_inds.append(name)
            elif result.signal == "bearish":
                bearish_inds.append(name)

        # Order flow siqnalını hesaba qat
        of_direction = of_result.get("direction", "neutral")
        if of_direction == "bullish":
            bullish_inds.append("OrderFlow")
        elif of_direction == "bearish":
            bearish_inds.append("OrderFlow")

        # Əsas istiqaməti müəyyənləşdir
        if len(bullish_inds) > len(bearish_inds):
            direction = "LONG"
            triggered = bullish_inds
        elif len(bearish_inds) > len(bullish_inds):
            direction = "SHORT"
            triggered = bearish_inds
        else:
            return self._no_trade_signal(symbol, timeframe, analysis, "Bərabər bullish/bearish siqnallar")

        # ── Texniki skor ───────────────────────────────────────────
        raw_score = analysis.raw_score

        if analysis.adx_value < 15:
            raw_score *= 0.5
        if analysis.volatility == "high":
            raw_score *= 0.85

        # Coin reputasiya düzəlişi (maks ±3)
        raw_score = max(0, min(100, raw_score + coin_rep_adj))

        # ── ATR-based Dinamik TP (Point 14) ─────────────────────────
        # Trend güclüdürsə TP uzaqlaşdır, zəifsə yaxınlaşdır
        adx_val = analysis.adx_value
        if adx_val >= 30:      # Güclü trend → TP uzaq
            tp_mult1, tp_mult2, tp_mult3 = 1.8, 3.0, 5.0
        elif adx_val >= 20:    # Normal trend
            tp_mult1, tp_mult2, tp_mult3 = 1.5, 2.5, 4.0
        else:                  # Zəif trend → TP yaxın
            tp_mult1, tp_mult2, tp_mult3 = 1.2, 1.8, 2.5

        if direction == "LONG":
            entry_low  = current_price * 0.999
            entry_high = current_price * 1.001
            stop_loss  = current_price - (1.5 * atr)
            tp1 = current_price + (1.5 * atr * tp_mult1)
            tp2 = current_price + (1.5 * atr * tp_mult2)
            tp3 = current_price + (1.5 * atr * tp_mult3)
        else:
            entry_low  = current_price * 0.999
            entry_high = current_price * 1.001
            stop_loss  = current_price + (1.5 * atr)
            tp1 = current_price - (1.5 * atr * tp_mult1)
            tp2 = current_price - (1.5 * atr * tp_mult2)
            tp3 = current_price - (1.5 * atr * tp_mult3)

        risk = abs(current_price - stop_loss)
        rr_tp1 = abs(tp1 - current_price) / risk if risk > 0 else 0
        rr_tp2 = abs(tp2 - current_price) / risk if risk > 0 else 0

        # Siqnal gücü
        strength = (
            "STRONG" if raw_score >= self.STRONG_THRESHOLD
            else "MODERATE" if raw_score >= self.MODERATE_THRESHOLD
            else "WEAK"
        )

        market_condition = f"{analysis.trend}_{analysis.volatility}_volatility"
        reasoning = self._build_reasoning(direction, triggered, raw_score, analysis, of_result)

        return TradeSignal(
            symbol=symbol,
            direction=direction,
            technical_score=raw_score,
            gpt_adjustment=0.0,
            final_score=raw_score,
            entry_zone_low=entry_low,
            entry_zone_high=entry_high,
            stop_loss=stop_loss,
            tp1=tp1, tp2=tp2, tp3=tp3,
            risk_reward_tp1=rr_tp1,
            risk_reward_tp2=rr_tp2,
            atr=atr,
            trend=analysis.trend,
            volatility=analysis.volatility,
            indicators_triggered=triggered,
            signal_strength=strength,
            reasoning=reasoning,
            gpt_context="",
            timestamp=datetime.now(timezone.utc).isoformat(),
            timeframe=timeframe,
            market_condition=market_condition,
            proceed=raw_score >= self.MODERATE_THRESHOLD,
            order_flow_score=order_flow_score,
            macro_score=50.0,       # MacroAgent sonra dolduracaq
            confidence_score=0.0,   # ChiefAgent sonra hesablayacaq
            position_tier="skip",
            mtf_confluence=False,
            market_regime="sideways",
            coin_reputation=coin_reputation,
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
                         analysis: FullAnalysis, of_result: dict = None) -> str:
        ind_str = ", ".join(triggered)
        of_str = ""
        if of_result:
            of_str = (f" | VWAP={of_result.get('vwap', {}).get('signal', 'n/a')} "
                      f"OBV={of_result.get('obv', {}).get('signal', 'n/a')} "
                      f"Delta={of_result.get('delta_volume', {}).get('signal', 'n/a')}")
        return (
            f"{direction} siqnalı | Bal: {score:.1f}/100 | "
            f"Trend: {analysis.trend} | Uçuculuq: {analysis.volatility} | "
            f"ADX: {analysis.adx_value:.1f} | ATR: {analysis.atr_value:.4f}{of_str} | "
            f"Tetiklənən: {ind_str}"
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
