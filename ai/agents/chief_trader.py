"""
TradeX-Pro — Chief Trader Agent (Point 17)
Analyst AI + Risk AI + Macro AI → Chief AI final qərar

İş axını:
  1. AnalystAI: texniki analiz + order flow → "BUY/SELL/HOLD" + confidence
  2. RiskAI:    risk analizi + portfolio vəziyyəti → "APPROVE/REDUCE/REJECT"
  3. MacroAI:   makro/sentiment → "FAVORABLE/NEUTRAL/UNFAVORABLE"
  4. ChiefAI:   3 agentin nəticəsini birləşdirir → final qərar + izah
"""

import json
from dataclasses import dataclass
from typing import Optional
from loguru import logger

from ai.gpt4_client import GPT4Client


@dataclass
class AgentVote:
    agent: str       # "analyst" | "risk" | "macro"
    verdict: str     # "BUY" | "SELL" | "HOLD" | "APPROVE" | "REJECT" | "REDUCE" | etc.
    confidence: float  # 0-1
    reasoning: str
    score_contribution: float  # Bu agentin final skora töhfəsi


@dataclass
class ChiefDecision:
    final_action: str        # "OPEN_LONG" | "OPEN_SHORT" | "SKIP" | "WATCHLIST"
    confidence_score: float  # 0-100
    position_tier: str       # "aggressive" | "normal" | "small" | "watchlist" | "skip"
    votes: list              # AgentVote list
    reasoning: str
    override_reason: Optional[str]  # Chief-in veto səbəbi (əgər varsa)
    proceed: bool


class AnalystAI:
    """
    Texniki analiz + order flow analiz edən agent.
    GPT istifadə etmir — qaydaya əsaslı deterministik.
    """

    def evaluate(self, tech_score: float, order_flow_score: float,
                  mtf_confluence: bool, direction: str) -> AgentVote:
        """
        Texniki + order flow xallarını birləşdirir.
        mtf_confluence: 4 zaman çərçivəsinin hamısı eyni istiqamətdə?
        """
        combined = tech_score * 0.6 + order_flow_score * 0.4

        if mtf_confluence:
            combined = min(100, combined + 10)  # +10 bonus (Point 6)

        if combined >= 78:
            verdict, conf = "STRONG_BUY" if direction == "LONG" else "STRONG_SELL", 0.9
        elif combined >= 65:
            verdict, conf = "BUY" if direction == "LONG" else "SELL", 0.7
        elif combined >= 55:
            verdict, conf = "WEAK_BUY" if direction == "LONG" else "WEAK_SELL", 0.5
        else:
            verdict, conf = "HOLD", 0.3

        mtf_note = " (MTF uyğunluq bonusu +10)" if mtf_confluence else ""
        return AgentVote(
            agent="analyst",
            verdict=verdict,
            confidence=conf,
            reasoning=f"Tech={tech_score:.0f}, OrderFlow={order_flow_score:.0f}, "
                      f"Combined={combined:.0f}{mtf_note}",
            score_contribution=combined,
        )


class RiskAI:
    """
    Risk qiymətləndirən agent.
    Mövqe ölçüsü, portfel korrelyasiyası, ardıcıl zərər, drawdown yoxlayır.
    """

    def evaluate(self, risk_state: dict, portfolio_state: dict,
                 direction: str, symbol: str, regime_vol_multiplier: float = 1.0) -> AgentVote:
        """
        risk_state: {consecutive_losses, today_pnl_pct, trading_halted, win_streak, base_risk_pct}
        portfolio_state: {open_positions_count, correlated_count, available_capital_pct}
        """
        issues = []
        score = 100.0

        # Ticarət dayandırıldı?
        if risk_state.get("trading_halted", False):
            return AgentVote(
                agent="risk", verdict="REJECT", confidence=1.0,
                reasoning="Risk sistemi ticarəti dayandırıb",
                score_contribution=0,
            )

        # Gündəlik drawdown limiti
        today_pnl = risk_state.get("today_pnl_pct", 0)
        if today_pnl < -0.04:
            issues.append(f"Günlük P&L {today_pnl*100:.1f}%")
            score -= 40

        # Ardıcıl zərər
        consec_losses = risk_state.get("consecutive_losses", 0)
        if consec_losses >= 4:
            issues.append(f"{consec_losses} ardıcıl zərər")
            score -= 30
        elif consec_losses >= 2:
            issues.append(f"{consec_losses} ardıcıl zərər — ehtiyatlı")
            score -= 10

        # Açıq mövqe sayı
        open_count = portfolio_state.get("open_positions_count", 0)
        max_positions = portfolio_state.get("max_positions", 3)
        if open_count >= max_positions:
            issues.append(f"Maksimum mövqe ({open_count}/{max_positions})")
            score -= 50

        # Korrelyasiya (Point 13): çox oxşar coin eyni istiqamətdə
        corr_count = portfolio_state.get("correlated_count", 0)
        if corr_count >= 3:
            issues.append(f"{corr_count} korrele mövqe var")
            score -= 25

        # Yüksək uçuculuq rejiminde risk azalt
        if regime_vol_multiplier < 0.7:
            issues.append("Yüksək uçuculuq rejimi")
            score -= 15

        score = max(0, score)

        if score >= 75:
            verdict, conf = "APPROVE", 0.9
        elif score >= 50:
            verdict, conf = "REDUCE", 0.6   # Mövqe ölçüsünü azalt
        else:
            verdict, conf = "REJECT", 0.8

        return AgentVote(
            agent="risk",
            verdict=verdict,
            confidence=conf,
            reasoning=f"Risk xalı={score:.0f}. " + ("; ".join(issues) if issues else "Risk normal"),
            score_contribution=score,
        )


class MacroAI:
    """
    Makro analiz agenti görüşünü formalaşdırır.
    MacroAnalystAgent nəticəsini qiymətləndirir.
    """

    def evaluate(self, macro_score: float, direction: str) -> AgentVote:
        """
        macro_score: 0-100 (50 = neytral)
        """
        if direction == "LONG":
            if macro_score >= 65:
                verdict, conf, contribution = "FAVORABLE", 0.85, macro_score
            elif macro_score >= 50:
                verdict, conf, contribution = "NEUTRAL", 0.6, macro_score
            elif macro_score >= 35:
                verdict, conf, contribution = "UNFAVORABLE", 0.7, macro_score
            else:
                verdict, conf, contribution = "STRONGLY_UNFAVORABLE", 0.9, macro_score
        else:  # SHORT
            if macro_score <= 35:
                verdict, conf, contribution = "FAVORABLE", 0.85, (100 - macro_score)
            elif macro_score <= 50:
                verdict, conf, contribution = "NEUTRAL", 0.6, (100 - macro_score)
            elif macro_score <= 65:
                verdict, conf, contribution = "UNFAVORABLE", 0.7, (100 - macro_score)
            else:
                verdict, conf, contribution = "STRONGLY_UNFAVORABLE", 0.9, (100 - macro_score)

        return AgentVote(
            agent="macro",
            verdict=verdict,
            confidence=conf,
            reasoning=f"Makro skor={macro_score:.1f} — {verdict}",
            score_contribution=contribution,
        )


class ChiefTraderAgent:
    """
    Chief AI — 3 agendin nəticəsini birləşdirir (Point 17).

    Qarar məntiqi:
    - Risk REJECT → avtomatik SKIP (veto)
    - 2+ agent HOLD/UNFAVORABLE → SKIP
    - Bütün 3 agent agree BUY/SELL → AGGRESSIVE
    - 2 agent agree → NORMAL
    - Zəif uyğunluq → SMALL or WATCHLIST

    Point 4 (Confidence Score → Position sizing):
      0-40  → skip
      40-60 → watchlist
      60-75 → small
      75-90 → normal
      90+   → aggressive
    """

    def __init__(self, gpt_client: Optional[GPT4Client] = None):
        self.analyst_ai = AnalystAI()
        self.risk_ai    = RiskAI()
        self.macro_ai   = MacroAI()
        self.gpt        = gpt_client  # AI reasoning üçün (Point 1: 20% AI Reasoning)
        self._decisions_log: list = []

    def decide(
        self,
        symbol: str,
        direction: str,
        tech_score: float,
        order_flow_score: float,
        macro_score: float,
        mtf_confluence: bool,
        risk_state: dict,
        portfolio_state: dict,
        regime_vol_multiplier: float = 1.0,
        coin_rep_adj: int = 0,
        ai_adjustment: int = 0,        # GPT-dən gələn düzəliş (Point 1: 20%)
        macro_halt: bool = False,
    ) -> ChiefDecision:
        """
        3 agentin qiymətləndirməsi əsasında final qərar.
        """
        # Makro dayandırma
        if macro_halt:
            return ChiefDecision(
                final_action="SKIP", confidence_score=0,
                position_tier="skip", votes=[],
                reasoning="Makro agent kritik hadisə aşkar etdi — ticarət dayandırıldı",
                override_reason="MACRO_HALT", proceed=False,
            )

        # 3 agentin qiymətləndirməsi
        analyst_vote = self.analyst_ai.evaluate(tech_score, order_flow_score, mtf_confluence, direction)
        risk_vote    = self.risk_ai.evaluate(risk_state, portfolio_state, direction, symbol, regime_vol_multiplier)
        macro_vote   = self.macro_ai.evaluate(macro_score, direction)

        votes = [analyst_vote, risk_vote, macro_vote]

        # Risk veto
        if risk_vote.verdict == "REJECT":
            return ChiefDecision(
                final_action="SKIP", confidence_score=0,
                position_tier="skip", votes=votes,
                reasoning=f"Risk AI vetoed: {risk_vote.reasoning}",
                override_reason="RISK_VETO", proceed=False,
            )

        # ── 5 faktorlu konfidans skoru (Point 1) ──────────────────
        # Technical (40%) + OrderFlow (15%) + Sentiment (15%) + OnChain (10%) + AI (20%)
        # Burada: tech_score=Technical, order_flow=OrderFlow, macro_score≈Sentiment
        # OnChain proxy: whale data (makro skor içərisindədir)
        # AI Reasoning: GPT-dən gələn ai_adjustment

        technical_component  = tech_score       * 0.40
        orderflow_component  = order_flow_score * 0.15
        sentiment_component  = macro_score      * 0.15
        onchain_component    = macro_score      * 0.10  # Whale data makro skor içərisindədir
        # AI adjustment: -10..+10 → 40..60 arası normallaşdır
        ai_component_raw     = 50 + (ai_adjustment * 2)
        ai_component         = max(0, min(100, ai_component_raw)) * 0.20

        base_confidence = (
            technical_component +
            orderflow_component +
            sentiment_component +
            onchain_component +
            ai_component
        )

        # Coin reputasiyası
        base_confidence += coin_rep_adj

        # Risk AI REDUCE → confidence -10
        if risk_vote.verdict == "REDUCE":
            base_confidence -= 10

        # Rejim bias: analyst score_contribution-dan
        base_confidence = max(0, min(100, base_confidence))

        # ── Final qərar ───────────────────────────────────────────
        # Point 4 confidence tier-ləri
        if base_confidence >= 90:
            final_action = f"OPEN_{direction}"
            position_tier = "aggressive"
        elif base_confidence >= 75:
            final_action = f"OPEN_{direction}"
            position_tier = "normal"
        elif base_confidence >= 60:
            final_action = f"OPEN_{direction}"
            position_tier = "small"
        elif base_confidence >= 40:
            final_action = "WATCHLIST"
            position_tier = "watchlist"
        else:
            final_action = "SKIP"
            position_tier = "skip"

        # Əlavə veto: makro çox zəifdirsə LONG açma
        if direction == "LONG" and macro_score < 25 and base_confidence < 80:
            return ChiefDecision(
                final_action="SKIP", confidence_score=base_confidence,
                position_tier="skip", votes=votes,
                reasoning=f"Makro çox zəif ({macro_score:.0f}) — LONG SKIP",
                override_reason="MACRO_TOO_WEAK", proceed=False,
            )

        # Əlavə veto: makro çox güclüsə SHORT açma
        if direction == "SHORT" and macro_score > 75 and base_confidence < 80:
            return ChiefDecision(
                final_action="SKIP", confidence_score=base_confidence,
                position_tier="skip", votes=votes,
                reasoning=f"Makro çox güclü ({macro_score:.0f}) — SHORT SKIP",
                override_reason="MACRO_TOO_STRONG_FOR_SHORT", proceed=False,
            )

        proceed = final_action not in ("SKIP", "WATCHLIST")

        reasoning = (
            f"[Analyst: {analyst_vote.verdict}({analyst_vote.confidence:.0%})] "
            f"[Risk: {risk_vote.verdict}({risk_vote.confidence:.0%})] "
            f"[Macro: {macro_vote.verdict}({macro_vote.confidence:.0%})] "
            f"→ Confidence={base_confidence:.1f} → {position_tier.upper()}"
        )

        decision = ChiefDecision(
            final_action=final_action,
            confidence_score=round(base_confidence, 1),
            position_tier=position_tier,
            votes=votes,
            reasoning=reasoning,
            override_reason=None,
            proceed=proceed,
        )

        self._decisions_log.append({
            "symbol": symbol,
            "direction": direction,
            "confidence": base_confidence,
            "tier": position_tier,
            "action": final_action,
        })

        logger.info(f"ChiefAI [{symbol}] {direction}: {final_action} | {position_tier} | conf={base_confidence:.1f}")
        return decision

    def get_position_size_multiplier(self, tier: str) -> float:
        """
        Mövqe ölçüsü çarpanı (Point 4 + Point 5 dinamik risk):
        skip → 0, watchlist → 0, small → 0.5, normal → 1.0, aggressive → 1.5
        """
        return {
            "skip": 0.0,
            "watchlist": 0.0,
            "small": 0.5,
            "normal": 1.0,
            "aggressive": 1.5,
        }.get(tier, 0.0)

    def get_dynamic_risk_pct(self, base_risk: float, risk_state: dict) -> float:
        """
        Point 5: Dinamik risk faizi.
        8/10 qalib → 1% → 1.5%
        4 ardıcıl zərər → 1% → 0.4%
        """
        win_streak   = risk_state.get("win_streak", 0)
        consec_loss  = risk_state.get("consecutive_losses", 0)
        recent_wins  = risk_state.get("recent_wins_10", 5)

        if consec_loss >= 4:
            return base_risk * 0.4   # Çox zəifləmiş
        elif consec_loss >= 2:
            return base_risk * 0.7
        elif recent_wins >= 8:
            return min(base_risk * 1.5, 0.02)   # Max 2% hard limit
        elif win_streak >= 5:
            return min(base_risk * 1.2, 0.015)
        else:
            return base_risk
