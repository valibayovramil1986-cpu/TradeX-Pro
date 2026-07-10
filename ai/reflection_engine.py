"""
TradeX-Pro — Reflection Engine
Micro + Macro özünü-analiz sistemi
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional
from loguru import logger

from ai.gpt4_client import GPT4Client
from memory.trade_journal import TradeJournal
from memory.strategy_log import StrategyLog


class ReflectionEngine:
    """
    TradeX-Pro-nun daxili özünü-analiz mühərriki.
    Hər ticarət bağlandıqdan sonra micro-refleksiya,
    hər həftə macro-refleksiya aparır.
    """

    def __init__(self, gpt_client: GPT4Client, trade_journal: TradeJournal,
                 strategy_log: StrategyLog):
        self.gpt = gpt_client
        self.journal = trade_journal
        self.strategy_log = strategy_log
        logger.info("ReflectionEngine işə salındı ✅")

    # ──────────────────────────────────────────────
    # Micro Refleksiya
    # ──────────────────────────────────────────────
    async def reflect_on_trade(self, trade_id: str) -> Optional[dict]:
        """
        Ticarət bağlandıqdan sonra dərhal çağırılır.
        GPT-4 istifadə edərək dərin analiz aparır.
        """
        trade = self.journal.get_trade(trade_id)
        if not trade:
            logger.warning(f"Ticarət tapılmadı: {trade_id}")
            return None

        # Oxşar ticarətləri tap (eyni simvol + eyni istiqamət)
        similar = self.journal.find_similar_trades(
            symbol=trade["symbol"],
            direction=trade["direction"],
            limit=5
        )

        logger.info(f"Micro refleksiya başlandı: {trade['symbol']} {trade['pnl_pct']}%")

        reflection = await asyncio.to_thread(self.gpt.micro_reflection, trade, similar)  # Y4

        if "error" in reflection:
            logger.error(f"Refleksiya xətası: {reflection['error']}")
            return None

        # Refleksiyanı ticarət qeydinə əlavə et
        self.journal.update_trade_reflection(trade_id, reflection)

        # Çəki düzəlişi tövsiyyə edilibsə qeydə al
        weight_adj = reflection.get("weight_adjustment", {})
        if weight_adj.get("needed") and weight_adj.get("indicator"):
            self.strategy_log.log_weight_suggestion(
                indicator=weight_adj["indicator"],
                direction=weight_adj["direction"],
                amount=weight_adj.get("amount", 1),
                reason=reflection.get("lesson", ""),
                trade_id=trade_id,
            )
            logger.info(f"Çəki düzəlişi təklif edildi: {weight_adj['indicator']} {weight_adj['direction']}")

        logger.info(f"✅ Micro refleksiya tamamlandı: Qiymət {reflection.get('overall_grade', '?')}")
        return reflection

    # ──────────────────────────────────────────────
    # Macro Refleksiya (Həftəlik)
    # ──────────────────────────────────────────────
    async def weekly_macro_reflection(self) -> Optional[dict]:
        """
        Həftəlik dərin özünü-analiz.
        Hər bazar ertəsı 08:00 UTC çağırılır.
        """
        logger.info("📋 Həftəlik macro refleksiya başlandı...")

        # Son 7 günün statistikası
        week_stats = self.journal.get_weekly_stats()
        if not week_stats or week_stats.get("total_trades", 0) == 0:
            logger.warning("Bu həftə ticarət yoxdur — macro refleksiya keçildi")
            return None

        # Bu həftənin bütün ticarət refleksiyaları
        recent_reflections = self.journal.get_recent_reflections(days=7)

        # Bu həftə edilən strategiya dəyişiklikləri
        strategy_changes = self.strategy_log.get_recent_changes(days=7)

        reflection = await asyncio.to_thread(
            self.gpt.macro_reflection, week_stats, recent_reflections, strategy_changes
        )  # Y4

        if "error" in reflection:
            logger.error(f"Macro refleksiya xətası: {reflection['error']}")
            return None

        # Strategiya loquna əlavə et
        self.strategy_log.log_weekly_reflection(reflection)

        # Əgər eşik dəyişikliyi tövsiyyə edilibsə
        threshold_rec = reflection.get("threshold_recommendation", {})
        if threshold_rec.get("change_needed") and threshold_rec.get("new_threshold"):
            self.strategy_log.log_threshold_change_suggestion(
                new_threshold=threshold_rec["new_threshold"],
                reason=threshold_rec.get("reason", ""),
            )

        logger.info(f"✅ Macro refleksiya tamamlandı — Bal: {reflection.get('performance_score', '?')}/10")
        return reflection

    # ──────────────────────────────────────────────
    # Faza Qiymətləndirməsi
    # ──────────────────────────────────────────────
    async def evaluate_phase(self, phase: str, phase_targets: dict) -> dict:
        """
        Faza sonu tam qiymətləndirmə.
        Hazırlıq balı hesabla, irəlilə və ya geri qal.
        """
        logger.info(f"🎓 Faza {phase} qiymətləndirməsi başlandı...")

        all_stats = self.journal.get_phase_stats(phase)
        evaluation = await asyncio.to_thread(
            self.gpt.phase_evaluation, phase, all_stats, phase_targets
        )  # Y4

        if "error" not in evaluation:
            self.strategy_log.log_phase_evaluation(phase, evaluation)

        readiness = evaluation.get("readiness_score", 0)
        advance = evaluation.get("advance_recommended", False)

        logger.info(f"Faza {phase} qiymətləndirməsi: Bal={readiness}/100, "
                    f"İrəliləmə={'BƏLI' if advance else 'XEYR'}")

        return evaluation

    def build_trade_close_message(self, trade: dict, reflection: dict) -> str:
        """Ticarət bağlandıqda Telegram mesajı üçün mətn"""
        pnl = trade.get("pnl_usd", 0)
        pnl_pct = trade.get("pnl_pct", 0)
        emoji = "✅" if pnl > 0 else "❌"
        grade = reflection.get("overall_grade", "?")
        lesson = reflection.get("lesson", "")
        summary = reflection.get("summary", "")

        return (
            f"{emoji} *MÖVQEBağlandı*\n"
            f"• Aktiv: {trade.get('symbol')} | {trade.get('direction')}\n"
            f"• Nəticə: {'+' if pnl > 0 else ''}{pnl:.2f}$ ({'+' if pnl_pct > 0 else ''}{pnl_pct:.2f}%)\n"
            f"• Müddət: {trade.get('duration_minutes', 0):.0f} dəqiqə\n"
            f"• Çıxış: {trade.get('exit_reason', '?')}\n\n"
            f"🧠 *AI Refleksiya* (Qiymət: {grade})\n"
            f"_{summary}_\n\n"
            f"💡 *Dərs:* {lesson}"
        )
