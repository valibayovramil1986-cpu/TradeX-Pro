"""
TradeX-Pro — Market Scanner
Hər 3 saatdan bir bütün aktivləri skan edir
"""

import asyncio
import pandas as pd
from datetime import datetime, timezone
from typing import Optional
from loguru import logger

from core.signal_engine import SignalEngine, TradeSignal
from core.risk_manager import RiskManager
from core.order_executor import OrderExecutor


# Skan ediləcək aktivlər — yalnız Binance-də olan simvollar
DEFAULT_SYMBOLS = {
    "crypto": [
        "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT",
        "ADA/USDT", "XRP/USDT", "DOGE/USDT", "POL/USDT",
        "AVAX/USDT", "LINK/USDT", "DOT/USDT", "TRX/USDT",
    ],
    # Forex Binance-də dəstəklənmir — gələcəkdə ayrı exchange əlavə olunacaq
}

TIMEFRAMES = ["1h", "4h"]   # Çox timeframe analiz


class MarketScanner:
    """
    Hər 3 saatdan bir bütün aktivləri skan edir,
    siqnalları toplayır, tapşırıqları icra edir.
    """

    def __init__(self, signal_engine: SignalEngine,
                 risk_manager: RiskManager,
                 executor: OrderExecutor,
                 exchange_client=None):
        self.signal_engine = signal_engine
        self.risk_manager = risk_manager
        self.executor = executor
        self.exchange = exchange_client
        self.last_scan_time: Optional[datetime] = None
        self.last_scan_results: list[TradeSignal] = []
        logger.info("MarketScanner işə salındı ✅")

    async def run_scan(self, phase: str = "1") -> list[TradeSignal]:
        """
        Tam bazar skanını icra et.
        Siqnalları topla, AI kontekstini əlavə et, icra et.
        """
        scan_start = datetime.now(timezone.utc)
        logger.info(f"🔍 Bazar skanı başlandı: {scan_start.strftime('%H:%M UTC')}")

        all_signals = []

        for category, symbols in DEFAULT_SYMBOLS.items():
            for symbol in symbols:
                try:
                    signals = await self._analyze_symbol(symbol, category, phase)
                    all_signals.extend(signals)
                except Exception as e:
                    logger.error(f"{symbol} analiz xətası: {e}")
                    continue

        # Siqnalları bala görə sırala
        actionable = [s for s in all_signals if s.proceed and s.direction != "NO_TRADE"]
        actionable.sort(key=lambda x: x.final_score, reverse=True)

        self.last_scan_results = all_signals
        self.last_scan_time = scan_start

        duration = (datetime.now(timezone.utc) - scan_start).total_seconds()
        logger.info(f"✅ Skan tamamlandı: {len(all_signals)} aktiv analiz edildi, "
                    f"{len(actionable)} siqnal tapıldı | {duration:.1f}s")

        return all_signals

    async def _analyze_symbol(self, symbol: str, category: str,
                              phase: str) -> list[TradeSignal]:
        """Bir simvolu bütün timeframe-lərdə analiz et.
        Qeyd: Risk yoxlaması BURADA edilmir — yalnız icra anında yoxlanılır.
        Bu sayədə risk dayandırıldıqda belə texniki siqnallar görünür.
        """
        signals = []

        for timeframe in TIMEFRAMES:
            try:
                df = await self._fetch_ohlcv(symbol, timeframe)
                if df is None or len(df) < 50:
                    logger.debug(f"{symbol} {timeframe}: kifayət qədər data yoxdur")
                    continue

                signal = self.signal_engine.analyze(df, symbol, timeframe)
                signals.append(signal)

            except Exception as e:
                logger.error(f"{symbol} {timeframe} xəta: {e}")

        return signals

    async def _fetch_ohlcv(self, symbol: str, timeframe: str,
                           limit: int = 200) -> Optional[pd.DataFrame]:
        """
        Exchange-dən OHLCV məlumatı çək.
        Exchange qoşulmayıbsa, demo məlumat qaytar.
        """
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
            # Demo/test məlumatı
            return self._generate_demo_data(symbol, 200)

    def _generate_demo_data(self, symbol: str, n: int = 200) -> pd.DataFrame:
        """Test üçün sintetik OHLCV məlumatı"""
        import numpy as np
        np.random.seed(hash(symbol) % 2**31)

        base = 65000 if "BTC" in symbol else 3000 if "ETH" in symbol else 100
        returns = np.random.normal(0.0002, 0.015, n)
        closes = base * (1 + returns).cumprod()

        df = pd.DataFrame({
            "timestamp": pd.date_range(end=datetime.now(), periods=n, freq="1h"),
            "open": closes * (1 + np.random.normal(0, 0.002, n)),
            "high": closes * (1 + abs(np.random.normal(0, 0.005, n))),
            "low": closes * (1 - abs(np.random.normal(0, 0.005, n))),
            "close": closes,
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
                else:
                    # Demo qiymət
                    prices[symbol] = self._demo_price(symbol)
        return prices

    def _demo_price(self, symbol: str) -> float:
        import random
        base = {"BTC/USDT": 65000, "ETH/USDT": 3000, "BNB/USDT": 580,
                "SOL/USDT": 170, "EUR/USD": 1.08, "XAU/USD": 2320}.get(symbol, 100)
        return base * (1 + random.uniform(-0.01, 0.01))
