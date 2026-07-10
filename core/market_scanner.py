"""
TradeX-Pro — Market Scanner (v2 — Multi-Agent)
4 Timeframe: 15m + 1h + 4h + 1D
MTF Confluence: hamısı eyni istiqamət → +10 bonus (Point 6)
Market Regime: BTC 4h ilə ümumi bazar vəziyyəti (Point 2)
"""

import asyncio
import pandas as pd
from datetime import datetime, timezone
from typing import Optional
from loguru import logger

from core.signal_engine import SignalEngine, TradeSignal
from core.risk_manager import RiskManager
from core.order_executor import OrderExecutor
from core.market_regime import MarketRegimeDetector, MarketRegime


# Skan ediləcək aktivlər — Binance yüksək likvidli cütlər
DEFAULT_SYMBOLS = {
    "crypto": [
        # Tier 1 — Ən yüksək likvidlik
        "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT",
        # Tier 2 — Yüksək həcm
        "ADA/USDT", "DOGE/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
        "TRX/USDT", "MATIC/USDT", "UNI/USDT", "ATOM/USDT", "LTC/USDT",
        # Tier 3 — Orta həcm, yüksək uçuculuq
        "INJ/USDT", "ARB/USDT", "OP/USDT", "SUI/USDT", "APT/USDT",
        "FET/USDT", "WLD/USDT", "NEAR/USDT", "FIL/USDT", "AAVE/USDT",
    ],
}

# 4 zaman çərçivəsi (Point 6)
TIMEFRAMES = ["15m", "1h", "4h", "1d"]

# Ən azı bu qədər bar lazımdır
MIN_BARS = {
    "15m": 100,
    "1h": 100,
    "4h": 60,
    "1d": 50,
}

# MTF çəkiləri (daha uzun TF daha ağırlıqlı)
MTF_WEIGHTS = {
    "15m": 0.15,
    "1h": 0.30,
    "4h": 0.35,
    "1d": 0.20,
}


class MarketScanner:
    """
    4 timeframe-də bazar skanı, MTF confluence, Market Regime.
    """

    def __init__(self, signal_engine: SignalEngine,
                 risk_manager: RiskManager,
                 executor: OrderExecutor,
                 exchange_client=None):
        self.signal_engine  = signal_engine
        self.risk_manager   = risk_manager
        self.executor       = executor
        self.exchange       = exchange_client
        self.regime_detector = MarketRegimeDetector()
        self.last_scan_time: Optional[datetime] = None
        self.last_scan_results: list[TradeSignal] = []
        self.current_regime: Optional[MarketRegime] = None
        logger.info("MarketScanner v2 işə salındı ✅ (4 TF: 15m+1h+4h+1D)")

    async def run_scan(self) -> list[TradeSignal]:
        """
        Tam bazar skanını icra et.
        Əvvəlcə Market Regime təyin et (BTC ilə),
        sonra hər simvolu 4 TF-də analiz et.
        """
        scan_start = datetime.now(timezone.utc)
        total_symbols = sum(len(s) for s in DEFAULT_SYMBOLS.values())
        logger.info(f"🔍 Bazar skanı başlandı: {scan_start.strftime('%H:%M UTC')} | "
                    f"{total_symbols} aktiv × {len(TIMEFRAMES)} TF")

        # ── 1. Market Regime Aşkar (Point 2) ─────────────────────
        await self._detect_market_regime()

        all_signals = []
        for category, symbols in DEFAULT_SYMBOLS.items():
            for symbol in symbols:
                try:
                    signal = await self._analyze_symbol_mtf(symbol)
                    if signal:
                        all_signals.append(signal)
                except Exception as e:
                    logger.error(f"{symbol} analiz xətası: {e}")

        # Confidence skoru əsasında sırala
        actionable = [s for s in all_signals if s.proceed and s.direction != "NO_TRADE"]
        actionable.sort(key=lambda x: x.confidence_score, reverse=True)

        self.last_scan_results = all_signals
        self.last_scan_time    = scan_start

        duration = (datetime.now(timezone.utc) - scan_start).total_seconds()
        regime_name = self.current_regime.regime if self.current_regime else "unknown"
        logger.info(f"✅ Skan tamamlandı: {len(all_signals)} analiz, "
                    f"{len(actionable)} əməliyyat siqnalı | "
                    f"Rejim={regime_name} | {duration:.1f}s")

        return all_signals

    async def _detect_market_regime(self):
        """BTC/USDT 4h məlumatı ilə ümumi bazar rejimini aşkar et (Point 2)."""
        try:
            df_btc_4h = await self._fetch_ohlcv("BTC/USDT", "4h", limit=250)
            df_btc_1d = await self._fetch_ohlcv("BTC/USDT", "1d", limit=100)

            if df_btc_4h is not None and len(df_btc_4h) >= 50:
                self.current_regime = self.regime_detector.detect(df_btc_4h, df_btc_1d)
                logger.info(f"📊 Bazar Rejimi: {self.current_regime.regime} — "
                            f"{self.current_regime.description}")
            else:
                self.current_regime = self.regime_detector.REGIMES["sideways"]
                logger.warning("BTC data kifayət deyil — sideways qəbul edildi")
        except Exception as e:
            logger.error(f"Market regime aşkar xətası: {e}")
            self.current_regime = self.regime_detector.REGIMES["sideways"]

    async def _analyze_symbol_mtf(self, symbol: str) -> Optional[TradeSignal]:
        """
        Simvolu 4 zaman çərçivəsində analiz et.
        MTF confluence hesabla → ən güclü siqnalı qaytar.
        """
        tf_signals: dict[str, TradeSignal] = {}

        # Bütün TF-ləri paralel çək
        fetch_tasks = {
            tf: self._fetch_ohlcv(symbol, tf, limit=max(200, MIN_BARS[tf] + 50))
            for tf in TIMEFRAMES
        }
        dfs = {}
        for tf, task in fetch_tasks.items():
            try:
                df = await task
                if df is not None and len(df) >= MIN_BARS[tf]:
                    dfs[tf] = df
            except Exception as e:
                logger.debug(f"{symbol} {tf} fetch xətası: {e}")

        if not dfs:
            return None

        # Hər TF üçün siqnal hesabla
        for tf, df in dfs.items():
            try:
                signal = self.signal_engine.analyze(df, symbol, tf)
                tf_signals[tf] = signal
            except Exception as e:
                logger.debug(f"{symbol} {tf} analiz xətası: {e}")

        if not tf_signals:
            return None

        # ── MTF Confluence (Point 6) ──────────────────────────────
        directions = [s.direction for s in tf_signals.values()
                      if s.direction != "NO_TRADE"]

        if not directions:
            return None

        # Çoxluq istiqaməti
        long_count  = directions.count("LONG")
        short_count = directions.count("SHORT")
        total_tf    = len(directions)

        if long_count > short_count:
            consensus_direction = "LONG"
        elif short_count > long_count:
            consensus_direction = "SHORT"
        else:
            return None  # Heç bir konsensus yoxdur

        # MTF uyğunluq faizi
        mtf_agree_count = max(long_count, short_count)
        mtf_confluence  = mtf_agree_count == total_tf  # Hamısı eyni istiqamət

        # Ağırlıqlı texniki skor
        weighted_tech_score = 0.0
        weighted_of_score   = 0.0
        total_weight = 0.0

        for tf, signal in tf_signals.items():
            if signal.direction == consensus_direction:
                w = MTF_WEIGHTS.get(tf, 0.25)
                weighted_tech_score += signal.technical_score * w
                weighted_of_score   += signal.order_flow_score * w
                total_weight += w

        if total_weight == 0:
            return None

        weighted_tech_score /= total_weight
        weighted_of_score   /= total_weight

        # MTF bonus: hamısı agree isə +10
        if mtf_confluence:
            weighted_tech_score = min(100, weighted_tech_score + 10)

        # Rejim bias tətbiq et (Point 2)
        best_signal = tf_signals.get("1h") or tf_signals.get("4h") or list(tf_signals.values())[0]

        if self.current_regime:
            regime_info = self.regime_detector.get_regime_for_signal(
                self.current_regime, consensus_direction
            )
            bias = regime_info.get("bias", 1.0)
            weighted_tech_score = min(100, weighted_tech_score * bias)
            regime_name = self.current_regime.regime
        else:
            regime_name = "unknown"

        # Yeni siqnal yarat
        from dataclasses import replace
        mtf_signal = TradeSignal(
            symbol=symbol,
            direction=consensus_direction,
            technical_score=round(weighted_tech_score, 1),
            gpt_adjustment=0.0,
            final_score=round(weighted_tech_score, 1),
            entry_zone_low=best_signal.entry_zone_low,
            entry_zone_high=best_signal.entry_zone_high,
            stop_loss=best_signal.stop_loss,
            tp1=best_signal.tp1,
            tp2=best_signal.tp2,
            tp3=best_signal.tp3,
            risk_reward_tp1=best_signal.risk_reward_tp1,
            risk_reward_tp2=best_signal.risk_reward_tp2,
            atr=best_signal.atr,
            trend=best_signal.trend,
            volatility=best_signal.volatility,
            indicators_triggered=best_signal.indicators_triggered,
            signal_strength=best_signal.signal_strength,
            reasoning=(
                f"MTF({','.join(dfs.keys())}) | "
                f"{'✅Confluence' if mtf_confluence else f'{mtf_agree_count}/{total_tf} TF uyğun'} | "
                f"Rejim={regime_name} | "
                + best_signal.reasoning
            ),
            gpt_context="",
            timestamp=best_signal.timestamp,
            timeframe="+".join(dfs.keys()),
            market_condition=best_signal.market_condition,
            proceed=weighted_tech_score >= self.signal_engine.MODERATE_THRESHOLD,
            order_flow_score=round(weighted_of_score, 1),
            macro_score=50.0,
            confidence_score=0.0,
            position_tier="skip",
            mtf_confluence=mtf_confluence,
            market_regime=regime_name,
            coin_reputation=best_signal.coin_reputation,
        )

        return mtf_signal

    async def _fetch_ohlcv(self, symbol: str, timeframe: str,
                           limit: int = 200) -> Optional[pd.DataFrame]:
        """Exchange-dən OHLCV məlumatı çək."""
        if self.exchange is not None:
            try:
                ohlcv = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
                )
                df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
                return df
            except Exception as e:
                logger.error(f"OHLCV çəkilə bilmədi ({symbol} {timeframe}): {e}")
                return None
        else:
            return self._generate_demo_data(symbol, limit, timeframe)

    def _generate_demo_data(self, symbol: str, n: int = 200,
                            timeframe: str = "1h") -> pd.DataFrame:
        """Test üçün sintetik OHLCV məlumatı"""
        import numpy as np
        np.random.seed(hash(symbol + timeframe) % 2**31)

        base = 65000 if "BTC" in symbol else 3000 if "ETH" in symbol else 100
        vol_map = {"15m": 0.005, "1h": 0.015, "4h": 0.025, "1d": 0.04}
        vol = vol_map.get(timeframe, 0.015)

        returns = np.random.normal(0.0002, vol, n)
        closes  = base * (1 + returns).cumprod()

        freq_map = {"15m": "15min", "1h": "1h", "4h": "4h", "1d": "1D"}
        freq = freq_map.get(timeframe, "1h")

        df = pd.DataFrame({
            "timestamp": pd.date_range(end=datetime.now(), periods=n, freq=freq),
            "open":   closes * (1 + np.random.normal(0, vol * 0.1, n)),
            "high":   closes * (1 + abs(np.random.normal(0, vol * 0.3, n))),
            "low":    closes * (1 - abs(np.random.normal(0, vol * 0.3, n))),
            "close":  closes,
            "volume": np.random.uniform(100, 10000, n),
        })
        return df

    def get_current_prices(self) -> dict[str, float]:
        """Bütün aktivlərin cari qiymətlərini qaytar"""
        prices = {}
        for category, symbols in DEFAULT_SYMBOLS.items():
            for symbol in symbols:
                if self.exchange:
                    try:
                        ticker = self.exchange.fetch_ticker(symbol)
                        prices[symbol] = ticker["last"]
                    except Exception:
                        pass
        return prices
