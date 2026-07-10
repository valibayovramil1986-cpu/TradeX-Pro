"""
TradeX-Pro — Macro Analyst Agent
Sentiment (Fear/Greed) + News Intelligence + Whale Tracking → Macro Score

18-nöqtəli planın Point 7, 8 implementasiyası:
  Point 7: Fed, CPI, ETF, SEC, Trump, Powell, BlackRock, Binance, Bybit, Hack, Whale xəbərləri
  Point 8: 100M+ USDT mübadilə daxili = risk; BTC mübadilədən çıxışı = bullish
"""

import asyncio
import re
from datetime import datetime, timezone
from typing import Optional
from loguru import logger

# ── Kritik Xəbər Açar Sözlər (Point 7) ───────────────────────────────────────
BULLISH_KEYWORDS = [
    "etf approved", "etf launch", "institutional adoption", "bitcoin reserve",
    "blackrock", "spot etf", "fed pause", "rate cut", "liquidity injection",
    "binance listing", "coinbase listing", "regulatory clarity",
    "whale accumulation", "exchange outflow", "btc leaving exchange",
]

BEARISH_KEYWORDS = [
    "sec lawsuit", "sec charges", "ban", "hack", "exploit", "rug pull",
    "exchange down", "binance hack", "bybit hack", "ftx", "bankrupt",
    "rate hike", "cpi inflation", "quantitative tightening",
    "whale dump", "large transfer to exchange", "exchange inflow spike",
    "trump tariff", "powell hawkish", "china ban",
]

HALT_KEYWORDS = [
    "exchange hack", "exchange bankrupt", "circuit breaker",
    "flash crash", "war declared", "nuclear", "massive exploit",
    "binance down", "bybit bankrupt",
]


class NewsIntelligence:
    """
    Xəbər mənbələrini analiz edir.
    NewsAPI, CryptoPanic, Twitter/X (mövcud olduqda) istifadə edir.
    """

    def __init__(self, newsapi_key: str = ""):
        self.newsapi_key = newsapi_key
        self._last_fetch: Optional[datetime] = None
        self._cache: list = []
        self._cache_ttl_minutes = 30

    async def fetch_crypto_news(self, limit: int = 20) -> list[dict]:
        """Kripto xəbərlərini əldə et (NewsAPI + CryptoPanic)."""
        articles = []

        # CryptoPanic (açıq API, key lazım deyil)
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    "https://cryptopanic.com/api/v1/posts/",
                    params={"auth_token": "anonymous", "public": "true",
                            "currencies": "BTC,ETH,SOL", "kind": "news"},
                )
                if r.status_code == 200:
                    data = r.json()
                    for item in data.get("results", [])[:limit]:
                        articles.append({
                            "title": item.get("title", ""),
                            "source": item.get("source", {}).get("title", "CryptoPanic"),
                            "url": item.get("url", ""),
                            "published": item.get("published_at", ""),
                            "sentiment": item.get("votes", {}).get("positive", 0) -
                                         item.get("votes", {}).get("negative", 0),
                        })
        except Exception as e:
            logger.debug(f"CryptoPanic xəbər xətası: {e}")

        # NewsAPI (key mövcuddursa)
        if self.newsapi_key:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.get(
                        "https://newsapi.org/v2/everything",
                        params={
                            "q": "bitcoin crypto SEC ETF BlackRock Fed CPI whale",
                            "sortBy": "publishedAt",
                            "language": "en",
                            "pageSize": limit,
                            "apiKey": self.newsapi_key,
                        },
                    )
                    if r.status_code == 200:
                        data = r.json()
                        for item in data.get("articles", []):
                            articles.append({
                                "title": item.get("title", ""),
                                "source": item.get("source", {}).get("name", "NewsAPI"),
                                "url": item.get("url", ""),
                                "published": item.get("publishedAt", ""),
                                "sentiment": 0,
                            })
            except Exception as e:
                logger.debug(f"NewsAPI xətası: {e}")

        self._cache = articles
        self._last_fetch = datetime.now(timezone.utc)
        return articles

    def classify_news(self, articles: list[dict]) -> dict:
        """
        Xəbərləri klassifikasiya et.
        Qaytarır: {score: -10..+10, signals: [...], halt: bool, summary: str}
        """
        if not articles:
            return {"score": 0, "signals": [], "halt": False, "summary": "Xəbər tapılmadı"}

        bullish_hits, bearish_hits, halt_hits = [], [], []

        for a in articles:
            title_lower = a.get("title", "").lower()

            for kw in HALT_KEYWORDS:
                if kw in title_lower:
                    halt_hits.append(a["title"])

            for kw in BULLISH_KEYWORDS:
                if kw in title_lower:
                    bullish_hits.append({"keyword": kw, "title": a["title"]})

            for kw in BEARISH_KEYWORDS:
                if kw in title_lower:
                    bearish_hits.append({"keyword": kw, "title": a["title"]})

        # Xal hesabla
        bull_score = min(len(bullish_hits) * 2, 8)
        bear_score = min(len(bearish_hits) * 2, 8)
        net_score = bull_score - bear_score
        net_score = max(-10, min(10, net_score))

        halt = len(halt_hits) > 0

        summary_parts = []
        if bullish_hits:
            summary_parts.append(f"Bullish: {', '.join([h['keyword'] for h in bullish_hits[:3]])}")
        if bearish_hits:
            summary_parts.append(f"Bearish: {', '.join([h['keyword'] for h in bearish_hits[:3]])}")
        if halt_hits:
            summary_parts.append(f"⚠️ HALT: {halt_hits[0][:80]}")

        return {
            "score": net_score,
            "bullish_count": len(bullish_hits),
            "bearish_count": len(bearish_hits),
            "signals": bullish_hits[:3] + bearish_hits[:3],
            "halt": halt,
            "halt_reason": halt_hits[0] if halt_hits else None,
            "summary": " | ".join(summary_parts) if summary_parts else "Neytral xəbər mühiti",
        }


class WhaleTracker:
    """
    Balina hərəkətlərini izlər (Point 8).
    Whale Alert API (açıq endpoint məhdud, subscription olan endpoint daha dəqiq).
    Alternativ: Glassnode, CryptoQuant kimi on-chain data.
    """

    def __init__(self):
        self._recent_signals: list = []

    async def fetch_whale_alerts(self, min_usd: int = 10_000_000) -> list[dict]:
        """
        Whale Alert API-dan böyük köçürmələri əldə et.
        $10M+ transferlər izlənir, $100M+ kritik hesab edilir.
        """
        signals = []
        try:
            import httpx
            # Whale Alert publik endpoint (limited)
            async with httpx.AsyncClient(timeout=8) as client:
                r = await client.get(
                    "https://api.whale-alert.io/v1/transactions",
                    params={"api_key": "free", "min_value": min_usd,
                            "currency": "usdt,btc,eth", "limit": 20},
                )
                if r.status_code == 200:
                    data = r.json()
                    for tx in data.get("transactions", []):
                        amount_usd = tx.get("amount_usd", 0)
                        from_addr = tx.get("from", {})
                        to_addr = tx.get("to", {})
                        is_to_exchange = to_addr.get("owner_type") == "exchange"
                        is_from_exchange = from_addr.get("owner_type") == "exchange"

                        signals.append({
                            "amount_usd": amount_usd,
                            "currency": tx.get("symbol", "").upper(),
                            "to_exchange": is_to_exchange,
                            "from_exchange": is_from_exchange,
                            "timestamp": tx.get("timestamp", 0),
                        })
        except Exception as e:
            logger.debug(f"Whale Alert xətası: {e}")

        self._recent_signals = signals
        return signals

    def analyze_whale_flow(self, transactions: list[dict]) -> dict:
        """
        Point 8 qaydaları:
        - 100M+ USDT mübadilə daxili → RISK (satış təzyiqi)
        - BTC mübadilədən çıxışı → BULLISH (saxlama, satış deyil)
        """
        if not transactions:
            return {"signal": "neutral", "score_adj": 0, "summary": "Balina məlumatı yoxdur"}

        to_exchange_usd = sum(
            t["amount_usd"] for t in transactions if t.get("to_exchange", False)
        )
        from_exchange_usd = sum(
            t["amount_usd"] for t in transactions if t.get("from_exchange", False)
        )
        btc_outflow = sum(
            t["amount_usd"] for t in transactions
            if t.get("from_exchange") and t.get("currency") == "BTC"
        )

        # Kritik: 100M+ USDT birjaya daxil → satış riski
        if to_exchange_usd >= 100_000_000:
            signal, score_adj = "high_risk", -6
            summary = f"⚠️ ${to_exchange_usd/1e6:.0f}M birjaya daxil — satış riski"
        elif to_exchange_usd >= 50_000_000:
            signal, score_adj = "moderate_risk", -3
            summary = f"${to_exchange_usd/1e6:.0f}M birjaya daxil — ehtiyatlı ol"
        elif btc_outflow >= 50_000_000:
            signal, score_adj = "bullish", 4
            summary = f"🟢 ${btc_outflow/1e6:.0f}M BTC birjadan çıxdı — saxlama siqnalı"
        elif from_exchange_usd > to_exchange_usd * 1.5:
            signal, score_adj = "slightly_bullish", 2
            summary = "BTC/ETH mübadilədən çıxır — bullish"
        else:
            signal, score_adj = "neutral", 0
            summary = "Balina fəaliyyəti normal"

        return {
            "signal": signal,
            "score_adj": score_adj,
            "to_exchange_usd": round(to_exchange_usd, 0),
            "from_exchange_usd": round(from_exchange_usd, 0),
            "btc_outflow_usd": round(btc_outflow, 0),
            "summary": summary,
        }


class FearGreedAnalyzer:
    """
    Alternative.me Fear & Greed Index ilə işləyir.
    """

    async def fetch(self) -> dict:
        """Cari Fear & Greed İndeksini əldə et."""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=8) as client:
                r = await client.get("https://api.alternative.me/fng/?limit=2")
                if r.status_code == 200:
                    data = r.json()
                    entries = data.get("data", [])
                    if entries:
                        current = entries[0]
                        prev    = entries[1] if len(entries) > 1 else entries[0]
                        return {
                            "value": int(current.get("value", 50)),
                            "label": current.get("value_classification", "Neutral"),
                            "prev_value": int(prev.get("value", 50)),
                            "trend": "rising" if int(current["value"]) > int(prev["value"]) else "falling",
                        }
        except Exception as e:
            logger.warning(f"Fear/Greed API xətası: {e}")
        return {"value": 50, "label": "Neutral", "prev_value": 50, "trend": "stable"}

    def score_adjustment(self, fg: dict, direction: str) -> int:
        """
        Fear/Greed dəyərinə görə skor düzəlişi.
        LONG: qorxu pisdir; SHORT: qorxu yaxşıdır.
        """
        val = fg.get("value", 50)
        if direction == "LONG":
            if val >= 75:   return 4   # Extreme Greed — momentum
            elif val >= 55: return 2
            elif val >= 40: return 0
            elif val >= 25: return -3
            else:           return -5  # Extreme Fear — max -5 for LONG
        else:  # SHORT
            if val <= 25:   return 3   # SHORT in Extreme Fear — bonus
            elif val <= 40: return 2
            elif val <= 55: return 0
            elif val <= 75: return -2
            else:           return -4  # SHORT in Extreme Greed — risk


class MacroAnalystAgent:
    """
    Makro analiz agenti.
    Sentiment + News + Whale → ümumi Macro Score (0-100)
    """

    def __init__(self, newsapi_key: str = ""):
        self.news = NewsIntelligence(newsapi_key=newsapi_key)
        self.whale = WhaleTracker()
        self.fg = FearGreedAnalyzer()

    async def analyze(self, direction: str = "LONG") -> dict:
        """
        Tam makro analiz apar.
        direction: "LONG" | "SHORT" — sentiment düzəlişi üçün lazım
        """
        # Paralel əldə et
        try:
            fg_data, articles, whale_txs = await asyncio.gather(
                self.fg.fetch(),
                self.news.fetch_crypto_news(limit=15),
                self.whale.fetch_whale_alerts(min_usd=10_000_000),
                return_exceptions=True,
            )
            # Xəta yoxla
            if isinstance(fg_data, Exception):
                fg_data = {"value": 50, "label": "Neutral", "prev_value": 50, "trend": "stable"}
            if isinstance(articles, Exception):
                articles = []
            if isinstance(whale_txs, Exception):
                whale_txs = []
        except Exception as e:
            logger.error(f"Makro analiz toplama xətası: {e}")
            fg_data = {"value": 50, "label": "Neutral", "prev_value": 50, "trend": "stable"}
            articles, whale_txs = [], []

        # Analiz
        news_result  = self.news.classify_news(articles)
        whale_result = self.whale.analyze_whale_flow(whale_txs)
        fg_adj       = self.fg.score_adjustment(fg_data, direction)

        # Birləşik xal (hər komponent 0-dən -10 / +10-a qədər)
        # Çəkilər: Fear/Greed 40%, News 35%, Whale 25%
        raw = fg_adj * 4.0 + news_result["score"] * 3.5 + whale_result["score_adj"] * 2.5

        # −100..+100 → 0..100 normallaşdır
        normalized = max(0, min(100, 50 + raw))

        halt = news_result.get("halt", False)

        result = {
            "macro_score": round(normalized, 1),
            "fear_greed": fg_data,
            "fg_adjustment": fg_adj,
            "news": news_result,
            "whale": whale_result,
            "halt_trading": halt,
            "halt_reason": news_result.get("halt_reason"),
            "direction": "bullish" if normalized > 55 else ("bearish" if normalized < 45 else "neutral"),
            "summary": (
                f"F&G={fg_data['value']}({fg_data['label']}) | "
                f"Xəbər={news_result['score']:+d} | "
                f"Balina: {whale_result['summary']}"
            ),
        }

        if halt:
            logger.warning(f"⚠️ Makro agent TİCARƏT DAYANDIRMASI tövsiyyə edir: {news_result.get('halt_reason')}")

        logger.info(f"Makro analiz: skor={normalized:.1f}, {result['summary']}")
        return result
