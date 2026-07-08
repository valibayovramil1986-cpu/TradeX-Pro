"""
TradeX-Pro — GPT-4 Client
OpenAI API ilə bütün AI əməliyyatları
"""

import os
import json
from typing import Optional
from loguru import logger


class GPT4Client:
    """
    OpenAI GPT-4o API üçün mərkəzi müştəri.
    Bütün AI sorğuları bu sinif vasitəsilə gedir.
    """

    MODEL = "gpt-4o"
    TEMPERATURE_TRADING = 0.15   # Ticarət qərarları — çox ardıcıl olsun
    TEMPERATURE_REFLECTION = 0.3  # Refleksiya — bir az yaradıcı ola bilər
    MAX_TOKENS_SIGNAL = 500
    MAX_TOKENS_REFLECTION = 1500
    MAX_TOKENS_MACRO = 2000

    SYSTEM_PROMPT = """
You are TradeX-Pro, an elite autonomous trading AI with deep expertise in
technical analysis, risk management, and self-improvement. You operate with
institutional-grade precision. Your responses are always structured as JSON.

Core principles:
1. Capital preservation above all
2. Data-driven decisions only — no emotions
3. Honest self-assessment — be brutally honest about mistakes
4. Conservative risk management
5. Continuous learning from every trade outcome

Always output valid JSON. Never hallucinate price levels or percentages.
"""

    def __init__(self, api_key: Optional[str] = None):
        from openai import OpenAI
        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise ValueError("OPENAI_API_KEY tapılmadı! .env faylını yoxlayın.")
        self.client = OpenAI(api_key=key)
        self._call_count = 0
        self._total_tokens = 0
        logger.info("GPT4Client işə salındı ✅")

    def _call(self, user_prompt: str, temperature: float = 0.2,
              max_tokens: int = 800) -> dict:
        """Əsas API çağırışı"""
        try:
            response = self.client.chat.completions.create(
                model=self.MODEL,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            self._call_count += 1
            self._total_tokens += response.usage.total_tokens
            content = response.choices[0].message.content
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"GPT-4 JSON parse xətası: {e}")
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"GPT-4 API xətası: {e}")
            return {"error": str(e)}

    # ──────────────────────────────────────────────
    # Siqnal Kontekstualizasiyası
    # ──────────────────────────────────────────────
    def contextualize_signal(self, signal_data: dict, news_context: str = "",
                              macro_data: dict = None) -> dict:
        """
        Texniki siqnalı makro kontekstlə birləşdir.
        Qaytarır: {adjustment: int, reasoning: str, proceed: bool}
        """
        direction   = signal_data.get("direction", "LONG")
        tech_score  = signal_data.get("technical_score", 60)
        fg          = (macro_data or {}).get("fear_greed_index", {}) or {}
        fg_value    = fg.get("value", 50)
        fg_label    = fg.get("label", "Neutral")
        macro_str   = json.dumps(macro_data or {}, indent=2)

        prompt = f"""
You are a professional crypto trading assistant. Evaluate this signal and give a SPECIFIC adjustment.

SIGNAL:
{json.dumps(signal_data, indent=2)}

MACRO: Fear/Greed = {fg_value} ({fg_label})
NEWS: {news_context or "No significant news"}

STRICT SCORING RULES — read carefully:

A) Technical score already captures price action. Your job is ONLY macro/news overlay.

B) LONG signal adjustments based on Fear/Greed:
   - Greed/Extreme Greed (>60):    +2 to +5  (momentum confirmed)
   - Neutral (40-60):               -1 to +1  (no macro edge)
   - Fear (20-40):                  -2 to -4  (caution, but trend may still hold)
   - Extreme Fear (<20):            -3 to -5  (max penalty for LONG in fear)

   IMPORTANT: Do NOT give -7 or more for LONG. -5 is the absolute max for LONG.
   A technical score of {tech_score} already reflects price weakness if any.

C) SHORT signal adjustments:
   - Fear/Extreme Fear:             0 to +3   (SHORT aligned with sentiment — BONUS)
   - Neutral/Greed:                 -2 to -4  (counter-sentiment caution)

D) proceed=false ONLY if: black swan event, exchange hack, regulatory shutdown, war.
   "Extreme Fear" index alone NEVER justifies proceed=false.

E) If no significant news and macro is neutral/mild fear: adjustment must be between -3 and +3.

Output JSON only:
{{
  "adjustment": <integer, LONG max=-5, SHORT max=+3>,
  "proceed": <boolean, almost always true>,
  "reasoning": "<1-2 sentences, be specific about what factor drove your number>",
  "risk_factors": ["<specific risk if any>"],
  "confidence_boost": <boolean>
}}
"""
        result = self._call(prompt, temperature=self.TEMPERATURE_TRADING,
                           max_tokens=self.MAX_TOKENS_SIGNAL)
        logger.debug(f"Signal kontekstualizasiya: {result}")
        return result

    # ──────────────────────────────────────────────
    # Micro Refleksiya (hər ticarət sonrası)
    # ──────────────────────────────────────────────
    def micro_reflection(self, trade_data: dict, similar_trades: list) -> dict:
        """
        Bir ticarət bağlandıqdan sonra dərhal refleksiya.
        """
        similar_str = json.dumps(similar_trades[:3], indent=2) if similar_trades else "[]"
        prompt = f"""
Perform a micro-reflection on this completed trade. Be brutally honest.

COMPLETED TRADE:
{json.dumps(trade_data, indent=2)}

SIMILAR HISTORICAL TRADES (for pattern comparison):
{similar_str}

Analyze and answer:
1. Was entry timing optimal? What was missed or done well?
2. Was the signal score accurate, or were there false indicators?
3. What pattern does this reveal?
4. What is the single most important lesson?
5. Should any indicator weights be adjusted?
6. Was confidence at entry calibrated correctly?

Output JSON:
{{
  "timing_analysis": "<assessment>",
  "signal_accuracy": "<was score accurate>",
  "pattern_identified": "<pattern or null>",
  "lesson": "<one sentence lesson>",
  "weight_adjustment": {{
    "needed": <boolean>,
    "indicator": "<indicator name or null>",
    "direction": "increase|decrease|null",
    "amount": <0-3>
  }},
  "confidence_calibrated": <boolean>,
  "overall_grade": "<A|B|C|D|F>",
  "summary": "<2 sentence human-readable summary>"
}}
"""
        result = self._call(prompt, temperature=self.TEMPERATURE_REFLECTION,
                           max_tokens=self.MAX_TOKENS_REFLECTION)
        logger.debug(f"Micro refleksiya tamamlandı: {trade_data.get('symbol')} {trade_data.get('pnl_pct')}%")
        return result

    # ──────────────────────────────────────────────
    # Macro Refleksiya (həftəlik)
    # ──────────────────────────────────────────────
    def macro_reflection(self, week_stats: dict, all_reflections: list,
                         strategy_changes: list) -> dict:
        """
        Həftəlik dərin özünü-analiz.
        """
        prompt = f"""
Perform a comprehensive weekly self-analysis as TradeX-Pro trading bot.
Be BRUTALLY HONEST. Your goal is continuous improvement, not self-justification.

WEEKLY PERFORMANCE STATISTICS:
{json.dumps(week_stats, indent=2)}

INDIVIDUAL TRADE REFLECTIONS (this week):
{json.dumps(all_reflections[-20:], indent=2)}

STRATEGY CHANGES MADE THIS WEEK:
{json.dumps(strategy_changes, indent=2)}

Provide comprehensive analysis:

Output JSON:
{{
  "weaknesses": [
    {{"issue": "<weakness 1>", "evidence": "<data supporting this>", "fix": "<specific action>"}},
    {{"issue": "<weakness 2>", "evidence": "<data>", "fix": "<action>"}},
    {{"issue": "<weakness 3>", "evidence": "<data>", "fix": "<action>"}}
  ],
  "strengths": [
    {{"strength": "<what's working>", "evidence": "<data>"}},
    {{"strength": "<what's working>", "evidence": "<data>"}}
  ],
  "next_week_priorities": [
    "<priority 1 — specific and measurable>",
    "<priority 2>",
    "<priority 3>"
  ],
  "performance_score": <1-10>,
  "performance_justification": "<why this score>",
  "phase_goals_met": <boolean>,
  "concerning_patterns": ["<pattern1>", "<pattern2>"],
  "threshold_recommendation": {{
    "change_needed": <boolean>,
    "new_threshold": <55-80 or null>,
    "reason": "<why>"
  }},
  "telegram_summary": "<3-4 paragraph human-readable weekly summary in Azerbaijani>"
}}
"""
        result = self._call(prompt, temperature=self.TEMPERATURE_REFLECTION,
                           max_tokens=self.MAX_TOKENS_MACRO)
        logger.info("Macro refleksiya tamamlandı ✅")
        return result

    # ──────────────────────────────────────────────
    # Faza Qiymətləndirməsi
    # ──────────────────────────────────────────────
    def phase_evaluation(self, phase: str, all_stats: dict,
                         phase_targets: dict) -> dict:
        """
        Faza sonu tam qiymətləndirmə.
        Hazırlıq balı (0-100) hesabla.
        """
        prompt = f"""
Evaluate Phase {phase} completion for TradeX-Pro trading bot.
Determine readiness to advance to the next phase.

PHASE {phase} TARGETS:
{json.dumps(phase_targets, indent=2)}

ACTUAL PERFORMANCE:
{json.dumps(all_stats, indent=2)}

Calculate readiness score and provide detailed analysis.

Output JSON:
{{
  "readiness_score": <0-100>,
  "targets_met": {{
    "win_rate": <boolean>,
    "max_drawdown": <boolean>,
    "sharpe_ratio": <boolean>,
    "profit_factor": <boolean>,
    "min_trades": <boolean>
  }},
  "gaps": [
    {{"metric": "<metric name>", "target": <value>, "actual": <value>, "gap": "<description>"}}
  ],
  "advance_recommended": <boolean>,
  "advance_reason": "<why proceed or not>",
  "improvements_needed": ["<improvement 1>", "<improvement 2>"],
  "telegram_summary": "<comprehensive phase evaluation in Azerbaijani — 4-5 paragraphs>"
}}
"""
        result = self._call(prompt, temperature=0.2, max_tokens=self.MAX_TOKENS_MACRO)
        logger.info(f"Faza {phase} qiymətləndirməsi tamamlandı")
        return result

    # ──────────────────────────────────────────────
    # Anomaliya Aşkarı
    # ──────────────────────────────────────────────
    def detect_anomaly(self, market_data: dict, news: str) -> dict:
        """Qeyri-adi bazar hadisəsini aşkar et"""
        prompt = f"""
Scan for market anomalies that should HALT trading:

MARKET DATA:
{json.dumps(market_data, indent=2)}

RECENT NEWS:
{news}

Check for: flash crashes, circuit breakers, major news events,
extreme volatility spikes, correlation breakdowns, macro shocks.

Output JSON:
{{
  "anomaly_detected": <boolean>,
  "anomaly_type": "<type or null>",
  "severity": "low|medium|high|critical",
  "halt_trading": <boolean>,
  "description": "<what is happening>",
  "estimated_duration": "<how long to wait>"
}}
"""
        return self._call(prompt, temperature=0.1, max_tokens=400)

    @property
    def usage_stats(self) -> dict:
        return {
            "total_calls": self._call_count,
            "total_tokens": self._total_tokens,
            "estimated_cost_usd": self._total_tokens * 0.000005  # ~$5/1M tokens gpt-4o
        }
