"""
TradeX-Pro — Signal Contextualizer
GPT-4 ilə siqnala makro kontekst əlavə edir
"""

import os
from typing import Optional
from loguru import logger

from ai.gpt4_client import GPT4Client
from core.signal_engine import TradeSignal, SignalEngine


class SignalContextualizer:
    """
    Texniki siqnalı GPT-4 vasitəsilə geniş kontekstlə zənginləşdirir.
    News API, Fear/Greed indeksi, makro məlumatlar.
    """

    def __init__(self, gpt_client: GPT4Client):
        self.gpt = gpt_client
        self._news_api_key = os.getenv("NEWSAPI_KEY", "")
        logger.info("SignalContextualizer işə salındı ✅")

    async def enrich_signal(self, signal: TradeSignal,
                            signal_engine: SignalEngine,
                            cached_macro: dict = None) -> TradeSignal:
        """
        Texniki siqnalı GPT-4 ilə kontekstualizasiya et.
        cached_macro: MacroAnalystAgent-dən artıq gəlmiş makro data —
                      ikiqat API çağırışının qarşısını alır.
        """
        if signal.direction == "NO_TRADE" or signal.technical_score < 55:
            return signal

        # Xəbərləri çək (simvola görə)
        news = await self._fetch_news(signal.symbol)

        # Makro: keşdən istifadə et, yoxdursa özü çək
        if cached_macro:
            macro = cached_macro
        else:
            macro = await self._fetch_macro_data()

        # Siqnal məlumatını hazırla
        signal_data = {
            "symbol":              signal.symbol,
            "direction":           signal.direction,
            "technical_score":     signal.technical_score,
            "order_flow_score":    signal.order_flow_score,
            "macro_score":         signal.macro_score,
            "mtf_confluence":      signal.mtf_confluence,
            "trend":               signal.trend,
            "volatility":          signal.volatility,
            "indicators_triggered": signal.indicators_triggered,
            "timeframe":           signal.timeframe,
            "reasoning":           signal.reasoning,
        }

        # GPT-4 çağır
        context_result = self.gpt.contextualize_signal(signal_data, news, macro)

        if "error" in context_result:
            logger.warning(f"Kontekstualizasiya xətası: {context_result['error']} — texniki bal saxlanılır")
            return signal

        adjustment = context_result.get("adjustment", 0)
        proceed = context_result.get("proceed", True)
        reasoning = context_result.get("reasoning", "")
        risk_factors = context_result.get("risk_factors", [])

        gpt_context = reasoning
        if risk_factors:
            gpt_context += f" | Risklər: {', '.join(risk_factors)}"

        # Siqnalı yenilə
        enriched = signal_engine.apply_gpt_adjustment(signal, adjustment, gpt_context, proceed)

        logger.info(f"Siqnal zənginləşdirildi: {signal.symbol} | "
                    f"Texniki: {signal.technical_score:.1f} → Final: {enriched.final_score:.1f} "
                    f"(GPT: {adjustment:+.0f})")

        return enriched

    async def _fetch_news(self, symbol: str) -> str:
        """Symbol üçün xəbər başlıqlarını çək"""
        if not self._news_api_key:
            return "News API açarı yoxdur."

        # Simvoldan axtarış açar sözü çıxar
        keyword = symbol.split("/")[0].upper()
        if keyword == "XAU":
            keyword = "gold"
        elif keyword == "EUR" or keyword == "GBP":
            keyword = f"{keyword} forex"

        try:
            import requests
            url = (f"https://newsapi.org/v2/everything?q={keyword}"
                   f"&language=en&pageSize=5&sortBy=publishedAt"
                   f"&apiKey={self._news_api_key}")
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                articles = resp.json().get("articles", [])
                headlines = [a["title"] for a in articles[:5]]
                return "\n".join(f"• {h}" for h in headlines)
        except Exception as e:
            logger.debug(f"Xəbər çəkilə bilmədi: {e}")

        return "Xəbər məlumatı mövcud deyil."

    async def _fetch_macro_data(self) -> dict:
        """Makro məlumatları çək (Fear/Greed, DXY, BTC dominance)"""
        macro = {
            "fear_greed_index": await self._get_fear_greed(),
            "btc_dominance": None,
            "dxy": None,
        }
        return macro

    async def _get_fear_greed(self) -> Optional[dict]:
        """Bitcoin Fear & Greed indeksini çək"""
        try:
            import requests
            resp = requests.get("https://api.alternative.me/fng/", timeout=5)
            if resp.status_code == 200:
                data = resp.json()["data"][0]
                return {
                    "value": int(data["value"]),
                    "label": data["value_classification"],
                }
        except Exception as e:
            logger.debug(f"Fear/Greed çəkilə bilmədi: {e}")
        return None
