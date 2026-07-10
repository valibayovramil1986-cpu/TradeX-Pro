"""
TradeX-Pro — Telegram Bot
Bütün bildirişlər və komandalar üçün mərkəzi interfeys
"""

import os
import asyncio
from datetime import datetime, timezone
from typing import Optional, Callable
from loguru import logger

from telegram import Update, Bot
from telegram.ext import (
    Application, CommandHandler, ContextTypes, CallbackContext
)
from telegram.constants import ParseMode


class TradexBot:
    """
    TradeX-Pro Telegram botu.
    Bütün bildirişlər, komandalar, planlaşdırılmış hesabatlar.
    """

    def __init__(self, token: str, chat_id: str,
                 on_pause: Callable = None,
                 on_resume: Callable = None,
                 on_close_all: Callable = None,
                 on_set_risk: Callable = None,
                 on_promote: Callable = None,
                 get_status: Callable = None,
                 get_signals: Callable = None,
                 get_performance: Callable = None,
                 get_reflection: Callable = None,
                 get_memory: Callable = None,
                 get_lessons: Callable = None,
                 get_weights: Callable = None,
                 get_phase: Callable = None,
                 get_patterns: Callable = None):

        self.token = token
        self.chat_id = chat_id
        self.app: Optional[Application] = None
        self.bot: Optional[Bot] = None
        self._close_all_pending_at: Optional[datetime] = None  # Y5: təsdiq pəncərəsi

        # Callback funksiyaları (main.py-dan gəlir)
        self._on_pause = on_pause
        self._on_resume = on_resume
        self._on_close_all = on_close_all
        self._on_set_risk = on_set_risk
        self._on_promote = on_promote
        self._get_status = get_status
        self._get_signals = get_signals
        self._get_performance = get_performance
        self._get_reflection = get_reflection
        self._get_memory = get_memory
        self._get_lessons = get_lessons
        self._get_weights = get_weights
        self._get_phase = get_phase
        self._get_patterns = get_patterns

    async def initialize(self):
        """Botu işə sal və komandaları qeydiyyatdan keçir"""
        self.app = Application.builder().token(self.token).build()
        self.bot = self.app.bot

        # Komanda işləyiciləri
        handlers = [
            CommandHandler("start", self._cmd_start),
            CommandHandler("status", self._cmd_status),
            CommandHandler("signals", self._cmd_signals),
            CommandHandler("performance", self._cmd_performance),
            CommandHandler("reflect", self._cmd_reflect),
            CommandHandler("memory", self._cmd_memory),
            CommandHandler("lessons", self._cmd_lessons),
            CommandHandler("weights", self._cmd_weights),
            CommandHandler("phase", self._cmd_phase),
            CommandHandler("patterns", self._cmd_patterns),
            CommandHandler("pause", self._cmd_pause),
            CommandHandler("resume", self._cmd_resume),
            CommandHandler("close_all", self._cmd_close_all),
            CommandHandler("confirm_close", self._cmd_confirm_close),  # Y5
            CommandHandler("risk", self._cmd_risk),
            CommandHandler("promote", self._cmd_promote),
            CommandHandler("help", self._cmd_help),
        ]

        for h in handlers:
            self.app.add_handler(h)

        logger.info("Telegram bot işə salındı ✅")

    def _is_authorized(self, update: Update) -> bool:
        """Yalnız sahibin mesajlarını qəbul et"""
        return str(update.effective_chat.id) == str(self.chat_id)

    async def _auth_check(self, update: Update) -> bool:
        if not self._is_authorized(update):
            await update.message.reply_text("⛔ İcazəsiz giriş.")
            return False
        return True

    # ──────────────────────────────────────────────
    # Komanda İşləyiciləri
    # ──────────────────────────────────────────────
    async def _cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._auth_check(update):
            return
        msg = (
            "🤖 *TradeX-Pro v3.0 Multi-Agent* aktivdir!\n\n"
            "OpenAI GPT-4o + Multi-Agent Consensus + Self-Reflection + Memory sistemi ilə "
            "tam avtomatik ticarət botu.\n\n"
            "Komandalar üçün /help yazın."
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    async def _cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._auth_check(update):
            return
        help_text = (
            "📚 *TradeX-Pro Komandaları*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "📊 *Məlumat*\n"
            "/status — Portfolio vəziyyəti\n"
            "/signals — Son skan nəticəsi\n"
            "/performance — P&L statistika\n"
            "/phase — Faza vəziyyəti\n\n"
            "🧠 *AI & Yaddaş*\n"
            "/reflect — Son AI refleksiya\n"
            "/memory — Yaddaş statistikası\n"
            "/lessons — Son 10 dərs\n"
            "/weights — İndikatör çəkiləri\n"
            "/patterns — Qızıl/Toksik nümunələr\n\n"
            "⚙️ *İdarəetmə*\n"
            "/pause — Ticarəti dayandır\n"
            "/resume — Ticarəti davam etdir\n"
            "/close\\_all — Bütün mövqeləri bağla\n"
            "/risk [low/medium/high] — Risk səviyyəsi\n"
            "/promote — Növbəti fazaya keç\n"
        )
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

    async def _cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._auth_check(update):
            return
        msg = await self._get_status() if self._get_status else "Status məlumatı mövcud deyil."
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    async def _cmd_signals(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._auth_check(update):
            return
        msg = await self._get_signals() if self._get_signals else "Siqnal məlumatı mövcud deyil."
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    async def _cmd_performance(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._auth_check(update):
            return
        msg = await self._get_performance() if self._get_performance else "Performans məlumatı yoxdur."
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    async def _cmd_reflect(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._auth_check(update):
            return
        msg = await self._get_reflection() if self._get_reflection else "Refleksiya məlumatı yoxdur."
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    async def _cmd_memory(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._auth_check(update):
            return
        msg = await self._get_memory() if self._get_memory else "Yaddaş məlumatı yoxdur."
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    async def _cmd_lessons(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._auth_check(update):
            return
        msg = await self._get_lessons() if self._get_lessons else "Dərs məlumatı yoxdur."
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    async def _cmd_weights(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._auth_check(update):
            return
        msg = await self._get_weights() if self._get_weights else "Çəki məlumatı yoxdur."
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    async def _cmd_phase(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._auth_check(update):
            return
        msg = await self._get_phase() if self._get_phase else "Faza məlumatı yoxdur."
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    async def _cmd_patterns(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._auth_check(update):
            return
        msg = await self._get_patterns() if self._get_patterns else "Nümunə məlumatı yoxdur."
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    async def _cmd_pause(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._auth_check(update):
            return
        if self._on_pause:
            await self._on_pause()
        await update.message.reply_text("⏸ *Ticarət dayandırıldı.* Siqnallar davam edir.",
                                        parse_mode=ParseMode.MARKDOWN)

    async def _cmd_resume(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._auth_check(update):
            return
        if self._on_resume:
            await self._on_resume()
        await update.message.reply_text("▶️ *Ticarət davam etdirildi.*",
                                        parse_mode=ParseMode.MARKDOWN)

    async def _cmd_close_all(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._auth_check(update):
            return
        self._close_all_pending_at = datetime.now(timezone.utc)
        await update.message.reply_text("⚠️ *Bütün mövqelər bağlanacaq!* Əminsinizmi?\n"
                                        "Təsdiq üçün 60 saniyə ərzində /confirm\\_close yazın.",
                                        parse_mode=ParseMode.MARKDOWN)

    async def _cmd_confirm_close(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Y5: /close_all təsdiqi — 60 saniyəlik pəncərə"""
        if not await self._auth_check(update):
            return
        if self._close_all_pending_at is None:
            await update.message.reply_text("Aktiv təsdiq sorğusu yoxdur. Əvvəlcə /close\\_all yazın.",
                                            parse_mode=ParseMode.MARKDOWN)
            return
        elapsed = (datetime.now(timezone.utc) - self._close_all_pending_at).total_seconds()
        self._close_all_pending_at = None
        if elapsed > 60:
            await update.message.reply_text("⏱ Təsdiq müddəti bitib (60s). Yenidən /close\\_all yazın.",
                                            parse_mode=ParseMode.MARKDOWN)
            return
        if self._on_close_all:
            await update.message.reply_text("🚨 Bütün mövqelər bağlanır...")
            await self._on_close_all()
            await update.message.reply_text("✅ *Bütün mövqelər bağlandı.*",
                                            parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("Close funksiyası aktiv deyil.")

    async def _cmd_risk(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._auth_check(update):
            return
        args = ctx.args
        level = args[0].lower() if args else "medium"
        if level not in ["low", "medium", "high"]:
            await update.message.reply_text("İstifadə: /risk [low/medium/high]")
            return
        if self._on_set_risk:
            await self._on_set_risk(level)
        risk_map = {"low": "0.5%", "medium": "1.5%", "high": "2.5%"}
        await update.message.reply_text(f"⚙️ Risk səviyyəsi: *{level.upper()}* ({risk_map[level]} per trade)",
                                        parse_mode=ParseMode.MARKDOWN)

    async def _cmd_promote(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._auth_check(update):
            return
        if self._on_promote:
            result = await self._on_promote()
            await update.message.reply_text(result, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("Promote funksiyası aktiv deyil.")

    # ──────────────────────────────────────────────
    # Bildiriş Göndərməsi
    # ──────────────────────────────────────────────
    async def send(self, message: str, parse_mode: str = ParseMode.MARKDOWN):
        """Mərkəzləşdirilmiş mesaj göndərmə"""
        if not self.bot:
            logger.error("Bot işə salınmayıb — mesaj göndərilmədi")
            return
        try:
            # 4096 simvol limitini keç
            if len(message) > 4000:
                chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
                for chunk in chunks:
                    await self.bot.send_message(
                        chat_id=self.chat_id, text=chunk, parse_mode=parse_mode
                    )
            else:
                await self.bot.send_message(
                    chat_id=self.chat_id, text=message, parse_mode=parse_mode
                )
        except Exception as e:
            logger.error(f"Telegram mesaj xətası: {e}")

    async def send_scan_report(self, report: str):
        await self.send(report)

    async def send_trade_opened(self, position_info: dict, mode: str = "PAPER"):
        direction_emoji = "🟢" if position_info.get("direction") == "LONG" else "🔴"
        msg = (
            f"{'✅' if mode == 'PAPER' else '💰'} *MÖVQEAçıldı* [{mode}]\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{direction_emoji} {position_info.get('symbol')} | {position_info.get('direction')}\n"
            f"• Giriş: {position_info.get('entry_price', 0):.4f}\n"
            f"• Ölçü: ${position_info.get('usd_value', 0):.2f}\n"
            f"• SL: {position_info.get('stop_loss', 0):.4f}\n"
            f"• TP1: {position_info.get('tp1', 0):.4f} | TP2: {position_info.get('tp2', 0):.4f}\n"
            f"• Siqnal Balı: {position_info.get('signal_score', 0):.1f}/100\n"
            f"• ID: `{position_info.get('trade_id', '?')}`"
        )
        await self.send(msg)

    async def send_trade_closed(self, trade_data: dict, reflection_summary: str = ""):
        pnl = trade_data.get("pnl_usd", 0)
        pnl_pct = trade_data.get("pnl_pct", 0)
        emoji = "✅" if pnl > 0 else "❌"
        msg = (
            f"{emoji} *MÖVQEBağlandı*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• Aktiv: {trade_data.get('symbol')} | {trade_data.get('direction')}\n"
            f"• Nəticə: {'+' if pnl >= 0 else ''}{pnl:.2f}$ ({'+' if pnl_pct >= 0 else ''}{pnl_pct:.2f}%)\n"
            f"• Giriş: {trade_data.get('entry_price', 0):.4f} → {trade_data.get('exit_price', 0):.4f}\n"
            f"• Müddət: {trade_data.get('duration_minutes', 0):.0f} dəq\n"
            f"• Çıxış: {trade_data.get('exit_reason', '?')}"
        )
        if reflection_summary:
            msg += f"\n\n🧠 *AI:* _{reflection_summary}_"
        await self.send(msg)

    async def send_risk_alert(self, alert_type: str, details: str):
        msg = f"🚨 *RİSK XƏBƏRDARLIĞİ*\n{alert_type}\n{details}"
        await self.send(msg)

    async def send_weekly_reflection(self, summary: str):
        msg = f"📋 *HƏFTƏLIK ÖZÜNÜ-ANALİZ*\n━━━━━━━━━━━━━━━━━━━━━━\n{summary}"
        await self.send(msg)

    async def run(self):
        """Botu polling rejimində işlət"""
        await self.initialize()
        logger.info("Telegram bot polling başladı...")
        await self.app.run_polling(drop_pending_updates=True)
