"""
TradeX-Pro v3.0 — Multi-Agent Orkestrator
18-nöqtəli plan: Technical(40%)+OrderFlow(15%)+Sentiment(15%)+OnChain(10%)+AI(20%)
Market Regime | AI Memory | Dynamic Risk | 4 TF | Chief Trader Consensus
"""

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from loguru import logger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# Path düzəltməsi
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import Settings
from core.signal_engine import SignalEngine
from core.risk_manager import RiskManager, RiskParams
from core.order_executor import OrderExecutor
from core.market_scanner import MarketScanner
from ai.gpt4_client import GPT4Client
from ai.signal_contextualizer import SignalContextualizer
from ai.reflection_engine import ReflectionEngine
from ai.agents.macro_analyst import MacroAnalystAgent
from ai.agents.chief_trader import ChiefTraderAgent
from memory.trade_journal import TradeJournal
from memory.weight_manager import WeightManager
from memory.pattern_memory import PatternMemory
from memory.strategy_log import StrategyLog
from tgbot.bot import TradexBot
from phases.phase_manager import PhaseManager


class TradeXPro:
    """
    TradeX-Pro-nun əsas orkestratoru.
    Bütün komponentləri birləşdirir, 3 saatlıq skanı idarə edir.
    """

    def __init__(self):
        self._trading_paused = False
        self._initialized = False

        # Qeydiyyat konfiqurasyonu
        logger.remove()
        logger.add(sys.stdout, level=Settings.LOG_LEVEL,
                   format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}")
        # Log faylı yazıla bilməsə (icazə/disk problemi) bot ÇÖKMƏMƏLİDİR —
        # stdout + docker logs onsuz da mövcuddur.
        try:
            logger.add(Settings.LOG_FILE, rotation="10 MB", retention="30 days",
                       level="DEBUG", encoding="utf-8")
        except Exception as e:
            logger.warning(f"Log faylı açıla bilmədi ({Settings.LOG_FILE}): {e} — "
                           f"yalnız stdout logging aktiv")

    async def initialize(self):
        """Bütün komponentləri işə sal"""
        logger.info("🤖 TradeX-Pro v3.0 (Multi-Agent) başladılır...")

        # Konfiqurasiya yoxlaması
        errors = Settings.validate()
        if errors:
            for e in errors:
                logger.error(e)
            logger.warning("Bəzi API açarları tapılmadı — Demo rejimdə işləyir")

        # ── Yaddaş Sistemi ──
        self.trade_journal = TradeJournal()
        self.weight_manager = WeightManager()
        self.pattern_memory = PatternMemory()
        self.strategy_log = StrategyLog()

        # ── Exchange client — əvvəlcə yaradılır ki, Executor-a ötürülsün (K1) ──
        self._exchange_client = self._init_exchange()

        # ── Risk & Executor ──
        risk_params = RiskParams(
            max_risk_per_trade_pct=Settings.MAX_RISK_PER_TRADE,
            max_open_positions=Settings.MAX_OPEN_POSITIONS,
            daily_drawdown_limit_pct=Settings.DAILY_DRAWDOWN_LIMIT,
            weekly_drawdown_limit_pct=Settings.WEEKLY_DRAWDOWN_LIMIT,
        )
        self.risk_manager = RiskManager(risk_params)
        self.executor = OrderExecutor(
            risk_manager=self.risk_manager,
            mode=Settings.TRADING_MODE,
            initial_balance=Settings.INITIAL_CAPITAL,
            exchange=self._exchange_client,   # K1: live bağlanışlar üçün
        )

        # ── AI Sistemi ──
        if Settings.OPENAI_API_KEY:
            self.gpt_client = GPT4Client(
                Settings.OPENAI_API_KEY,
                daily_token_limit=Settings.OPENAI_DAILY_TOKEN_LIMIT,  # O4
            )
            self.contextualizer = SignalContextualizer(self.gpt_client)
            self.reflection_engine = ReflectionEngine(
                self.gpt_client, self.trade_journal, self.strategy_log
            )
        else:
            self.gpt_client = None
            self.contextualizer = None
            self.reflection_engine = None
            logger.warning("OpenAI API açarı yoxdur — AI funksiyaları deaktivdir")

        # ── Multi-Agent Sistemi (v3.0) ──
        self.macro_agent  = MacroAnalystAgent(newsapi_key=Settings.NEWSAPI_KEY)
        self.chief_agent  = ChiefTraderAgent(
            gpt_client=self.gpt_client,
            min_confidence=Settings.CONFIDENCE_THRESHOLD,   # .env-dən idarə olunur
        )
        # AI Memory (Point 11): simvol üzrə statistika — DB-dən yüklə
        self._coin_stats: dict = self._load_coin_stats()
        logger.info(f"Multi-Agent sistem işə salındı ✅ (MacroAnalyst + ChiefTrader) | "
                    f"AI Memory: {len(self._coin_stats)} coin")

        # ── Signal & Scanner ──
        weights = self.weight_manager.get_signal_weights()
        self.signal_engine = SignalEngine(
            weights=weights,
            moderate_threshold=Settings.SIGNAL_THRESHOLD,        # .env-dən idarə olunur
            strong_threshold=Settings.STRONG_SIGNAL_THRESHOLD,
        )

        self.scanner = MarketScanner(
            signal_engine=self.signal_engine,
            risk_manager=self.risk_manager,
            executor=self.executor,
            exchange_client=self._exchange_client,
        )

        # ── Faza Meneceri ──
        self.phase_manager = PhaseManager()

        # ── Telegram Botu ──
        self.telegram = None
        if Settings.TELEGRAM_BOT_TOKEN and Settings.TELEGRAM_CHAT_ID:
            self.telegram = TradexBot(
                token=Settings.TELEGRAM_BOT_TOKEN,
                chat_id=Settings.TELEGRAM_CHAT_ID,
                on_pause=self._pause_trading,
                on_resume=self._resume_trading,
                on_close_all=self._emergency_close_all,
                on_set_risk=self._set_risk_level,
                on_promote=self._promote_phase,
                get_status=self._get_status_message,
                get_signals=self._get_signals_message,
                get_performance=self._get_performance_message,
                get_reflection=self._get_reflection_message,
                get_memory=self._get_memory_message,
                get_lessons=self._get_lessons_message,
                get_weights=self._get_weights_message,
                get_phase=self._get_phase_message,
                get_patterns=self._get_patterns_message,
            )
            await self.telegram.initialize()
            # Executor-un kritik xəbərdarlıqlarını Telegram-a bağla
            # (live bağlanış uğursuzluğu, SL order xətası və s.)
            self.executor.alert_callback = self.telegram.send_risk_alert

        # ── Zamanlayıcı ──
        self.scheduler = AsyncIOScheduler(timezone="UTC")
        self._setup_scheduler()

        self._initialized = True
        logger.info(f"✅ TradeX-Pro hazırdır | {Settings.display()}")

    def _init_exchange(self):
        """CCXT exchange client-i işə sal.
        BINANCE_FUTURES=true  → USD-M Futures (LONG+SHORT, 1x leverage default)
        BINANCE_FUTURES=false → Spot (yalnız LONG siqnalları icra edilir)
        API key olmasa belə public OHLCV üçün qoşulur.
        """
        try:
            import ccxt
            base_cfg = {
                "apiKey": Settings.BINANCE_API_KEY or None,
                "secret": Settings.BINANCE_SECRET or None,
                "enableRateLimit": True,
            }

            if Settings.BINANCE_FUTURES:
                base_cfg["options"] = {"defaultType": "future"}
                exchange = ccxt.binance(base_cfg)
                if Settings.BINANCE_API_KEY:
                    # Leverage 1x — Futures-də borclama yoxdur, yalnız hedging
                    logger.info("Binance USD-M Futures qoşuldu ✅ (LONG+SHORT aktiv)")
                else:
                    logger.info("Binance Futures public rejim (yalnız bazar datası) ✅")
            else:
                exchange = ccxt.binance(base_cfg)
                if Settings.BINANCE_API_KEY:
                    logger.info("Binance Spot qoşuldu ✅ (yalnız LONG siqnalları icra ediləcək)")
                else:
                    logger.info("Binance Spot public rejim (yalnız bazar datası) ✅")

            return exchange
        except Exception as e:
            logger.error(f"Exchange qoşulması uğursuz: {e} — demo data istifadə edilir")
            return None

    def _setup_scheduler(self):
        """Skan zamanlayıcısı — intervalı SCAN_INTERVAL_HOURS idarə edir (O7)"""
        self.scheduler.add_job(
            self._scheduled_scan,
            "interval",
            hours=Settings.SCAN_INTERVAL_HOURS,
            id="market_scan",
            name=f"{Settings.SCAN_INTERVAL_HOURS}-Saatlıq Bazar Skanı",
            coalesce=True,
            max_instances=1,
            misfire_grace_time=120,
        )

        # Hər 5 dəqiqədə SL/TP qiymət yoxlaması
        self.scheduler.add_job(
            self._price_check,
            "interval",
            minutes=5,
            id="price_check",
            name="5-Dəqiqəlik SL/TP Yoxlaması",
            coalesce=True,
            max_instances=1,
        )

        # Gündəlik risk sıfırlanması (gecəyarısı UTC)
        self.scheduler.add_job(
            self.risk_manager.reset_daily_stats,
            CronTrigger(hour=0, minute=0, timezone="UTC"),
            id="daily_reset",
        )

        # Həftəlik macro refleksiya (bazar ertəsi 08:00 UTC)
        self.scheduler.add_job(
            self._weekly_reflection,
            CronTrigger(day_of_week="mon", hour=8, minute=0, timezone="UTC"),
            id="weekly_reflection",
        )

        # Həftəlik risk sıfırlanması
        self.scheduler.add_job(
            self.risk_manager.reset_weekly_stats,
            CronTrigger(day_of_week="mon", hour=0, minute=0, timezone="UTC"),
            id="weekly_reset",
        )

        # Gündəlik faza yoxlaması (hər gün 09:00 UTC)
        # 14 gün (və ya faza müddəti) dolubsa GPT qiymətləndirməsi işlənir
        self.scheduler.add_job(
            self._daily_phase_check,
            CronTrigger(hour=9, minute=0, timezone="UTC"),
            id="daily_phase_check",
            coalesce=True,
            max_instances=1,
        )

        logger.info("Zamanlayıcı konfiqasiya edildi ✅")

    # ──────────────────────────────────────────────
    # Əsas Skan Prosesi
    # ──────────────────────────────────────────────
    async def _scheduled_scan(self):
        """
        Saatlıq əsas skan — Multi-Agent Orkestrasiya (v3.0)

        Axın:
        1. MarketScanner → 4 TF MTF + Regime aşkar
        2. MacroAnalystAgent → Sentiment + News + Whale (1 dəfə bütün skan üçün)
        3. Hər siqnal üçün ChiefTraderAgent → 3-agent consensus + confidence tier
        4. Dinamik risk + mövqe açma
        """
        if self._trading_paused:
            logger.info("Ticarət dayandırılıb — skan keçildi")
            return

        logger.info(f"⏰ Planlaşdırılmış skan: {datetime.now(timezone.utc).strftime('%H:%M UTC')}")

        # ── 1. Texniki Skan (4 TF + MTF confluence + Regime) ─────
        signals = await self.scanner.run_scan()

        if not signals:
            logger.info("Skan siqnal qaytarmadı")
            return

        # ── 2. Makro Analiz — 1 dəfə, bütün skan üçün ─────────────
        # Point 7+8: News + Whale + Fear/Greed
        # Əvvəlcə dominant istiqaməti müəyyən et (çoxluq)
        long_count  = sum(1 for s in signals if s.direction == "LONG")
        short_count = sum(1 for s in signals if s.direction == "SHORT")
        dominant_direction = "LONG" if long_count >= short_count else "SHORT"

        try:
            macro_result = await self.macro_agent.analyze(direction=dominant_direction)
        except Exception as e:
            logger.error(f"Makro analiz xətası: {e}")
            macro_result = {"macro_score": 50, "halt_trading": False,
                           "summary": "Makro analiz əldə edilə bilmədi",
                           "fear_greed": {"value": 50, "label": "Neutral"}}

        macro_score = macro_result.get("macro_score", 50.0)
        macro_halt  = macro_result.get("halt_trading", False)

        if macro_halt:
            halt_reason = macro_result.get("halt_reason", "Kritik hadisə")
            logger.warning(f"⚠️ Makro HALT: {halt_reason}")
            if self.telegram:
                await self.telegram.send_risk_alert("MAKRO HALT", halt_reason)
            return

        # ── 3. GPT Kontekstualizasiya (AI Reasoning = 20%) ─────────
        raw_actionable = []
        for signal in signals:
            if not signal.proceed or signal.direction == "NO_TRADE":
                continue
            if signal.technical_score < 50:
                continue

            signal.macro_score = macro_score

            if self.contextualizer:
                try:
                    # cached_macro ötürülür — ikiqat API çağırışı olmur
                    signal = await self.contextualizer.enrich_signal(
                        signal, self.signal_engine, cached_macro=macro_result
                    )
                except Exception as e:
                    logger.debug(f"GPT enrichment xətası ({signal.symbol}): {e}")
            raw_actionable.append(signal)

        # ── 4. ChiefTrader — 3-Agent Consensus (Point 17) ──────────
        is_spot_live = (Settings.TRADING_MODE == "live" and not Settings.BINANCE_FUTURES)
        risk_status  = self.risk_manager.status
        open_symbols = {p.symbol for p in self.executor.open_positions.values()}

        # Risk state for ChiefAgent
        risk_state = {
            "consecutive_losses": risk_status.get("consecutive_losses", 0),
            "today_pnl_pct":      risk_status.get("today_pnl", 0) / max(self.executor.initial_balance, 1),
            "trading_halted":     risk_status.get("trading_halted", False),
            "win_streak":         risk_status.get("win_streak", 0),
            "base_risk_pct":      Settings.MAX_RISK_PER_TRADE,
            "recent_wins_10":     risk_status.get("recent_wins_10", 5),
        }

        # Portfolio state for ChiefAgent (Point 13: korrelyasiya, O10: genişləndirilmiş qruplar)
        correlation_groups = [
            {"BTC/USDT", "ETH/USDT", "BNB/USDT"},                       # Majors
            {"SOL/USDT", "AVAX/USDT", "NEAR/USDT", "APT/USDT", "SUI/USDT"},  # L1 altlar
        ]
        correlated_set = correlation_groups[0]  # ChiefAgent üçün əsas qrup
        corr_count = max(len(g & open_symbols) for g in correlation_groups)
        portfolio_state = {
            "open_positions_count": len(open_symbols),
            "max_positions":        Settings.MAX_OPEN_POSITIONS,
            "correlated_count":     corr_count,
            "available_capital_pct": 1 - (len(open_symbols) / max(Settings.MAX_OPEN_POSITIONS, 1)),
        }

        # Rejim vol multiplier
        regime = self.scanner.current_regime
        vol_mult = regime.vol_multiplier if regime else 1.0

        actionable_decisions = []
        for signal in raw_actionable:
            if signal.symbol in open_symbols:
                logger.debug(f"⏭ {signal.symbol} — artıq açıq mövqe var")
                continue

            # Spot live-da SHORT mümkün deyil
            if is_spot_live and signal.direction == "SHORT":
                continue

            # AI Memory düzəlişi (Point 11): coin statistikası
            coin_mem = self._coin_stats.get(signal.symbol, {})
            coin_rep_adj = 0
            if coin_mem.get("trades", 0) >= 5:
                wr = coin_mem.get("wins", 0) / coin_mem["trades"]
                if wr >= 0.7:   coin_rep_adj = 2
                elif wr >= 0.6: coin_rep_adj = 1
                elif wr <= 0.3: coin_rep_adj = -3

            # ChiefTrader qərarı
            decision = self.chief_agent.decide(
                symbol=signal.symbol,
                direction=signal.direction,
                tech_score=signal.technical_score,
                order_flow_score=signal.order_flow_score,
                macro_score=signal.macro_score,
                mtf_confluence=signal.mtf_confluence,
                risk_state=risk_state,
                portfolio_state=portfolio_state,
                regime_vol_multiplier=vol_mult,
                coin_rep_adj=coin_rep_adj,
                ai_adjustment=int(signal.gpt_adjustment),
                macro_halt=False,
            )

            signal.confidence_score = decision.confidence_score
            signal.position_tier    = decision.position_tier

            logger.info(
                f"🧠 ChiefAI [{signal.symbol}] {signal.direction}: "
                f"{decision.final_action} | tier={decision.position_tier} | "
                f"conf={decision.confidence_score:.1f} | {decision.reasoning[:80]}"
            )

            if decision.proceed:
                actionable_decisions.append((signal, decision))

        # Confidence-ə görə sırala
        actionable_decisions.sort(key=lambda x: x[1].confidence_score, reverse=True)

        # ── 5. Ticarətləri İcra Et ──────────────────────────────────
        opened_trades = []
        for signal, decision in actionable_decisions:
            risk_check = self.risk_manager.check_trade_allowed(
                self.executor.balance, self.executor.initial_balance
            )
            if not risk_check.allowed:
                if risk_check.halt_trading and self.telegram:
                    await self.telegram.send_risk_alert("Ticarət DAYANDIRILIB", risk_check.reason)
                break

            # Korrelyasiya filtri (Point 13 + O10): hər qrupdan max 2 eyni anda
            open_symbols_now = {p.symbol for p in self.executor.open_positions.values()}
            corr_blocked = any(
                signal.symbol in grp and len(grp & open_symbols_now) >= 2
                for grp in correlation_groups
            )
            if corr_blocked:
                logger.info(f"⏭ {signal.symbol} — Korrelyasiya limiti (qrupda max 2 mövqe)")
                continue

            # Dinamik risk (Point 5) + Position tier multiplier (Point 4)
            base_risk = self.chief_agent.get_dynamic_risk_pct(
                Settings.MAX_RISK_PER_TRADE, risk_state
            )
            tier_mult = self.chief_agent.get_position_size_multiplier(decision.position_tier)
            final_risk = base_risk * tier_mult * vol_mult

            pos_size = self.risk_manager.calculate_position_size(
                self.executor.balance, signal.entry_zone_high, signal.stop_loss,
                risk_pct_override=final_risk,
            )

            position = self.executor.open_position(
                signal, pos_size,
                confidence=decision.confidence_score / 10,
                phase="live",
                exchange=self._exchange_client,
            )

            if position and self.telegram:
                msg = (
                    f"🤖 *ChiefAI Qərarı* | {decision.position_tier.upper()}\n"
                    f"Conf={decision.confidence_score:.0f} | Risk={final_risk*100:.2f}%\n"
                    f"{decision.reasoning[:120]}"
                )
                await self.telegram.send_trade_opened(vars(position), Settings.TRADING_MODE.upper())
                opened_trades.append(position)

        # ── 6. SL/TP Yoxla + Post-Trade Refleksiya ─────────────────
        prices = await self.scanner.get_current_prices()
        closed = self.executor.check_sl_tp(prices)

        for trade in closed:
            self.trade_journal.save_trade(vars(trade))
            self.pattern_memory.record_trade(trade.indicators_triggered, trade.pnl_usd)

            # AI Memory yenilə (Point 11, 18) — RAM + DB
            sym = trade.symbol
            if sym not in self._coin_stats:
                self._coin_stats[sym] = {"trades": 0, "wins": 0, "losses": 0, "total_pnl": 0}
            self._coin_stats[sym]["trades"] += 1
            if trade.pnl_usd > 0:
                self._coin_stats[sym]["wins"] += 1
            else:
                self._coin_stats[sym]["losses"] += 1
            self._coin_stats[sym]["total_pnl"] += trade.pnl_usd
            # DB-yə yaz (restart-a davamlı)
            self._save_coin_stat(sym, self._coin_stats[sym])

            # Post-trade refleksiya (Point 15: AI Trade Journal)
            reflection_summary = ""
            if self.reflection_engine:
                try:
                    base_trade_id = trade.trade_id.split("_")[0]
                    reflection = await self.reflection_engine.reflect_on_trade(base_trade_id)
                    if reflection:
                        reflection_summary = reflection.get("summary", "")
                except Exception as e:
                    logger.debug(f"Refleksiya xətası: {e}")

            if self.telegram:
                await self.telegram.send_trade_closed(vars(trade), reflection_summary)

        # ── 7. Çəki Analizi (hər 20 ticarətdən sonra) ──────────────
        all_trades = self.trade_journal.get_weekly_stats(days=30)
        total_t = all_trades.get("total_trades", 0)
        if total_t > 0 and total_t % 20 == 0:
            recent = self.trade_journal.get_recent_trades(limit=20)
            changes = self.weight_manager.analyze_and_adjust(recent)
            if changes:
                new_weights = self.weight_manager.get_signal_weights()
                self.signal_engine.update_weights(new_weights)
                logger.info(f"✅ İndikatör çəkiləri yeniləndi: {list(changes.keys())}")

        # ── 8. Scan Hesabatı ────────────────────────────────────────
        report = await self._build_scan_report(signals, actionable_decisions, opened_trades, macro_result)
        if self.telegram:
            await self.telegram.send_scan_report(report)

    async def _price_check(self):
        """
        Hər 5 dəqiqədə bir SL/TP yoxla.
        Tam skan aparmır — yalnız açıq mövqelərin qiymətlərini yoxlayır.
        """
        if not self.executor.open_positions:
            return

        try:
            prices = await self.scanner.get_current_prices()
            closed = self.executor.check_sl_tp(prices)

            for trade in closed:
                self.trade_journal.save_trade(vars(trade))
                self.pattern_memory.record_trade(
                    trade.indicators_triggered, trade.pnl_usd
                )
                reflection_summary = ""
                if self.reflection_engine and "SL" in trade.exit_reason:
                    # Yalnız SL vurduqda refleksiya et (TP-lər çox tez-tez baş verir)
                    reflection = await self.reflection_engine.reflect_on_trade(
                        trade.trade_id.split("_")[0]
                    )
                    if reflection:
                        reflection_summary = reflection.get("summary", "")

                if self.telegram:
                    await self.telegram.send_trade_closed(vars(trade), reflection_summary)

        except Exception as e:
            logger.error(f"Qiymət yoxlama xətası: {e}")

    async def _weekly_reflection(self):
        """Həftəlik macro refleksiya"""
        if self.reflection_engine:
            reflection = await self.reflection_engine.weekly_macro_reflection()
            if reflection and self.telegram:
                summary = reflection.get("telegram_summary", "Refleksiya məlumatı")
                await self.telegram.send_weekly_reflection(summary)

    async def _daily_phase_check(self):
        """
        Hər gün 09:00 UTC-də çağırılır.

        Faza keçid məntiqi:
        1. Müddət (14 gün) dolmalıdır VƏ
        2. Min ticarət sayı (40) əldə edilməlidir.
        Əgər müddət dolub amma ticarət sayı çatmırsa, faza uzadılır (tıxanmır).
        """
        current_phase = self.phase_manager.current_phase
        if current_phase == "3":
            return

        days = self.phase_manager.days_in_phase
        targets = self.phase_manager.current_targets
        required_days = targets.get("duration_days", 14)
        min_trades = targets.get("min_trades", 40)

        # Ticarət statistikasını al
        stats = self.trade_journal.get_phase_stats(current_phase)
        total_trades = stats.get("total_trades", 0)

        if days < required_days:
            logger.debug(f"Faza {current_phase}: {days}/{required_days} gün — hələ vaxt dolmayıb")
            return

        # Müddət dolub — amma min ticarət sayı yetərsizdirsə uzat
        if total_trades < min_trades:
            logger.info(
                f"⏳ Faza {current_phase} müddəti dolub ({days} gün) amma "
                f"ticarət sayı ({total_trades}/{min_trades}) çatışmır — faza uzadılır"
            )
            if self.telegram:
                await self.telegram.send(
                    f"⏳ *Faza {current_phase} uzadıldı*\n"
                    f"• Gün: {days} (14 gün dolub)\n"
                    f"• Ticarət: {total_trades}/{min_trades} ❌\n"
                    f"Minimum {min_trades} ticarətə çatana kimi Faza {current_phase} davam edir."
                )
            return

        # Hər iki şərt yerinə yetirilib — GPT qiymətləndirməsi
        last_eval = self.strategy_log.get_latest_phase_evaluation(current_phase)
        if last_eval:
            logger.debug(f"Faza {current_phase} artıq qiymətləndirilib — keçildi")
            return

        logger.info(f"🎓 Faza {current_phase} tamamlandı ({days} gün, {total_trades} ticarət) — qiymətləndirmə başlanır")

        if not self.reflection_engine:
            logger.warning("ReflectionEngine yoxdur — GPT qiymətləndirməsi keçildi")
            return

        evaluation = await self.reflection_engine.evaluate_phase(current_phase, targets)
        if not evaluation or "error" in evaluation:
            return

        readiness = evaluation.get("readiness_score", 0)
        advance = evaluation.get("advance_recommended", False)
        summary = evaluation.get("telegram_summary", "")
        threshold = targets.get("readiness_threshold", 65)

        msg = (
            f"🎓 *Faza {current_phase} Avtomatik Qiymətləndirməsi*\n\n"
            f"📅 Keçən gün: {days} | Ticarət: {total_trades}/{min_trades}\n"
            f"📊 Hazırlıq Balı: *{readiness}/100* (Tələb: {threshold}+)\n"
            f"{'✅ İrəliləmə tövsiyə edilir!' if advance else '⚠️ Hələ irəliləmə tövsiyə edilmir'}\n\n"
            f"{summary}\n\n"
            f"_İrəliləmək üçün /promote əmrini istifadə edin._"
        )

        if self.telegram:
            await self.telegram.send_weekly_reflection(msg)

    # ──────────────────────────────────────────────
    # Telegram Callback Funksiyaları
    # ──────────────────────────────────────────────
    async def _pause_trading(self):
        self._trading_paused = True
        logger.info("⏸ Ticarət dayandırıldı")

    async def _resume_trading(self):
        self._trading_paused = False
        self.risk_manager.resume_trading()
        logger.info("▶️ Ticarət davam etdirildi")

    async def _emergency_close_all(self):
        prices = await self.scanner.get_current_prices()
        closed = self.executor.close_all_positions(prices, "emergency_close_all")
        for trade in closed:
            self.trade_journal.save_trade(vars(trade))
        logger.warning(f"🚨 Bütün mövqelər bağlandı: {len(closed)}")

    async def _set_risk_level(self, level: str):
        risk_map = {"low": 0.005, "medium": 0.015, "high": 0.025}
        self.risk_manager.params.max_risk_per_trade_pct = risk_map.get(level, 0.015)
        logger.info(f"Risk səviyyəsi: {level} ({risk_map.get(level)*100:.1f}%)")

    async def _promote_phase(self) -> str:
        """Faza keçid əmri"""
        current = self.phase_manager.current_phase
        targets = self.phase_manager.current_targets

        # Hazırlıq balını hesabla
        stats = self.trade_journal.get_phase_stats(current)
        if self.reflection_engine:
            evaluation = await self.reflection_engine.evaluate_phase(current, targets)
            readiness = evaluation.get("readiness_score", 0)
            if readiness < targets["readiness_threshold"]:
                return (f"⚠️ Hazırlıq balı: {readiness}/100 "
                        f"(minimum: {targets['readiness_threshold']})\n"
                        f"Hədəflər hələ əldə edilməyib. Davam edin.")

        result = self.phase_manager.promote_to_next_phase("user_command")
        if result["success"]:
            # Kapitalı yenilə (Y6: Faza 3-də capital=None — real balans istifadə olunur)
            new_capital = result.get("capital")
            if new_capital:
                self.executor.balance = new_capital
                self.executor.initial_balance = new_capital
                capital_str = f"Yeni kapital: ${new_capital:,.0f}"
            else:
                capital_str = "Kapital: real birja balansı"
            return (f"🎓 *{result['message']}*\n"
                    f"{capital_str}\n"
                    f"Mode: {result['mode'].upper()}")
        return result["message"]

    # ──────────────────────────────────────────────
    # Telegram Məlumat Funksiyaları
    # ──────────────────────────────────────────────
    async def _get_status_message(self) -> str:
        risk = self.risk_manager.status
        phase = self.phase_manager.current_phase
        pnl = self.executor.total_pnl
        pnl_pct = self.executor.total_pnl_pct
        mode = Settings.TRADING_MODE.upper()

        lines = [
            f"📊 *TradeX-Pro Status* [{mode}]",
            f"━━━━━━━━━━━━━━━━━━━━━━",
            f"• Balans: ${self.executor.balance:,.2f}",
            f"• Ümumi P&L: {'+' if pnl >= 0 else ''}{pnl:.2f}$ ({'+' if pnl_pct >= 0 else ''}{pnl_pct:.2f}%)",
            f"• Açıq Mövqe: {risk['open_positions']}",
            f"• Faza: {phase}",
            f"• Ticarət: {'⏸ Dayandırılıb' if self._trading_paused else '▶️ Aktiv'}",
            f"• Ardıcıl İtki: {risk['consecutive_losses']}",
            f"• Bu gün P&L: ${risk['today_pnl']:+.2f}",
        ]
        if self.gpt_client:
            usage = self.gpt_client.usage_stats
            lines.append(f"• GPT-4 Çağırış: {usage['total_calls']} (~${usage['estimated_cost_usd']:.3f})")
        return "\n".join(lines)

    async def _get_signals_message(self) -> str:
        if not self.scanner.last_scan_results:
            return "Hələ skan aparılmayıb. Gözləyin..."
        signals = [s for s in self.scanner.last_scan_results if s.direction != "NO_TRADE"]
        if not signals:
            return "Son skanda ticarət siqnalı tapılmadı."
        lines = [f"📡 *Son Skan Siqnalları* ({len(signals)} ədəd):", "━━━━━━━━━━━━━━━━━━━━━━"]
        for s in sorted(signals, key=lambda x: x.final_score, reverse=True)[:5]:
            emoji = "🟢" if s.direction == "LONG" else "🔴"
            lines.append(f"{emoji} {s.symbol} | {s.direction} | Bal: {s.final_score:.0f}/100 | {s.signal_strength}")
        return "\n".join(lines)

    async def _get_performance_message(self) -> str:
        stats = self.trade_journal.get_weekly_stats(days=7)
        if stats.get("total_trades", 0) == 0:
            return "Bu həftə ticarət yoxdur."
        return (
            f"📈 *Həftəlik Performans*\n━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• Ticarət: {stats['total_trades']} ({stats['win_count']}W/{stats['loss_count']}L)\n"
            f"• Win Rate: {stats['win_rate_pct']:.1f}%\n"
            f"• P&L: ${stats['total_pnl_usd']:+.2f}\n"
            f"• Profit Factor: {stats['profit_factor']:.2f}\n"
            f"• Sharpe: {stats['sharpe_ratio']:.2f}\n"
            f"• Max DD: {stats['max_drawdown_pct']:.1f}%"
        )

    async def _get_reflection_message(self) -> str:
        recent = self.strategy_log.get_recent_changes(days=7)
        if not recent:
            return "Son 7 gündə strategiya dəyişikliyi yoxdur."
        lines = ["🧠 *Son Strategiya Dəyişiklikləri:*", "━━━━━━━━━━━━━━━━━━━━━━"]
        for c in recent[:5]:
            lines.append(f"• [{c['type']}] {c['description']} ({c['date'][:10]})")
        return "\n".join(lines)

    async def _get_memory_message(self) -> str:
        stats = self.trade_journal.get_weekly_stats(days=30)
        hour_perf = self.trade_journal.get_performance_by_hour()
        best_hours = sorted(hour_perf.items(), key=lambda x: x[1]["win_rate"], reverse=True)[:3]
        lines = [
            "💾 *Yaddaş Statistikası (30 gün)*",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"• Ümumi Ticarət: {stats.get('total_trades', 0)}",
            f"• Win Rate: {stats.get('win_rate_pct', 0):.1f}%",
            "",
            "⏰ *Ən Yaxşı Saatlar (UTC):*",
        ]
        for hour, data in best_hours:
            lines.append(f"• {hour}:00 — Win: {data['win_rate']:.0f}% ({data['trades']} ticarət)")
        return "\n".join(lines)

    async def _get_lessons_message(self) -> str:
        lessons = self.trade_journal.get_all_lessons(10)
        if not lessons:
            return "Hələ dərs qeydə alınmayıb."
        lines = ["📚 *Son 10 Öyrənilmiş Dərs:*", "━━━━━━━━━━━━━━━━━━━━━━"]
        for i, lesson in enumerate(lessons, 1):
            lines.append(f"{i}. {lesson}")
        return "\n".join(lines)

    async def _get_weights_message(self) -> str:
        return self.weight_manager.weights_display

    async def _get_phase_message(self) -> str:
        stats = self.trade_journal.get_phase_stats(self.phase_manager.current_phase)
        return self.phase_manager.get_status_message(stats)

    async def _get_patterns_message(self) -> str:
        golden = self.pattern_memory.get_golden_patterns()
        toxic = self.pattern_memory.get_toxic_patterns()
        lines = ["🏆 *Qızıl Nümunələr (Win Rate >70%):*"]
        if golden:
            for p in golden[:3]:
                lines.append(f"• {p['pattern']} — {p['win_rate']}% ({p['total_trades']} ticarət)")
        else:
            lines.append("• Hələ yoxdur (minimum 10 ticarət lazımdır)")
        lines += ["", "⚠️ *Toksik Nümunələr (Win Rate <40%):*"]
        if toxic:
            for p in toxic[:3]:
                lines.append(f"• {p['pattern']} — {p['win_rate']}% ({p['total_trades']} ticarət)")
        else:
            lines.append("• Hələ yoxdur")
        return "\n".join(lines)

    # ──────────────────────────────────────────────
    # AI Memory — DB persist (Point 11)
    # ──────────────────────────────────────────────
    def _load_coin_stats(self) -> dict:
        """coin_memory cədvəlindən AI Memory yüklə."""
        from database.db import engine
        from sqlalchemy import text
        try:
            with engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS coin_memory (
                        symbol TEXT PRIMARY KEY,
                        trades INTEGER DEFAULT 0,
                        wins INTEGER DEFAULT 0,
                        losses INTEGER DEFAULT 0,
                        total_pnl REAL DEFAULT 0,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                conn.commit()
                rows = conn.execute(text("SELECT symbol, trades, wins, losses, total_pnl FROM coin_memory")).fetchall()
            result = {}
            for r in rows:
                result[r[0]] = {"trades": r[1], "wins": r[2], "losses": r[3], "total_pnl": r[4]}
            logger.info(f"AI Memory yükləndi: {len(result)} coin")
            return result
        except Exception as e:
            logger.warning(f"AI Memory yükləmə xətası: {e}")
            return {}

    def _save_coin_stat(self, symbol: str, stat: dict):
        """Bir coinin statistikasını DB-yə yaz."""
        from database.db import engine
        from sqlalchemy import text
        try:
            with engine.connect() as conn:
                conn.execute(text("""
                    INSERT INTO coin_memory (symbol, trades, wins, losses, total_pnl)
                    VALUES (:sym, :t, :w, :l, :p)
                    ON CONFLICT (symbol) DO UPDATE SET
                        trades=:t, wins=:w, losses=:l,
                        total_pnl=:p, updated_at=CURRENT_TIMESTAMP
                """), {"sym": symbol, "t": stat["trades"], "w": stat["wins"],
                       "l": stat["losses"], "p": stat["total_pnl"]})
                conn.commit()
        except Exception as e:
            logger.debug(f"AI Memory saxlama xətası ({symbol}): {e}")

    async def _build_scan_report(self, all_signals, actionable_decisions,
                                  opened, macro_result: dict = None) -> str:
        """Saatlıq Telegram hesabatı (Multi-Agent v3.0)"""
        now    = datetime.now(timezone.utc).strftime("%H:%M UTC")
        stats  = self.trade_journal.get_weekly_stats(days=7)
        mode   = "PAPER 📄" if Settings.TRADING_MODE == "paper" else "🔴 LIVE"
        regime = self.scanner.current_regime
        # QEYD: "_" Telegram Markdown-u pozur (bull_weak və s.) → "-" ilə əvəzlə
        regime_str = (f"{regime.regime.replace('_', '-')}({regime.description[:20]})"
                      if regime else "unknown")

        # Makro özet
        macro_str = ""
        if macro_result:
            fg    = macro_result.get("fear_greed", {})
            whale = macro_result.get("whale", {})
            macro_str = (
                f"\n📊 *Makro:* F&G={fg.get('value',50)}({fg.get('label','?')}) | "
                f"Xəbər={macro_result.get('news', {}).get('score', 0):+d} | "
                f"{whale.get('summary', '')[:50]}"
            )

        lines = [
            f"🤖 *TradeX-Pro v3.0* | {mode}",
            f"⏰ {now} | Rejim: {regime_str}",
            macro_str,
            f"━━━━━━━━━━━━━━━━━━━━━━",
            f"📡 Analiz: {len(all_signals)} | Əməliyyat: {len(actionable_decisions)} | Açılan: {len(opened)}",
            "",
        ]

        if actionable_decisions:
            lines.append("🚦 *ChiefAI Qərarları (Top 3):*")
            top3 = sorted(actionable_decisions, key=lambda x: x[1].confidence_score, reverse=True)[:3]
            for sig, dec in top3:
                emoji = "🟢" if sig.direction == "LONG" else "🔴"
                tier_badge = {"aggressive": "⚡", "normal": "✅", "small": "🔵",
                              "watchlist": "👁"}.get(dec.position_tier, "")
                lines += [
                    f"{emoji}{tier_badge} *{sig.direction}* — {sig.symbol} | Tier: {dec.position_tier.upper()}",
                    f"• Conf={dec.confidence_score:.0f} | Tech={sig.technical_score:.0f} | "
                    f"OF={sig.order_flow_score:.0f} | {'✅MTF' if sig.mtf_confluence else 'MTF--'}",
                    f"• SL={sig.stop_loss:.4f} | TP1={sig.tp1:.4f} | TP2={sig.tp2:.4f}",
                    "",
                ]

        # AI Memory özet (Point 11)
        if self._coin_stats:
            top_coins = sorted(
                [(sym, d) for sym, d in self._coin_stats.items() if d["trades"] >= 3],
                key=lambda x: x[1]["wins"] / x[1]["trades"], reverse=True
            )[:3]
            if top_coins:
                lines.append("🧠 *AI Yaddaş (ən yaxşı coinlər):*")
                for sym, d in top_coins:
                    wr = d["wins"] / d["trades"] * 100
                    lines.append(f"• {sym.split('/')[0]}: {d['trades']}t, {wr:.0f}%WR, ${d['total_pnl']:+.1f}")
                lines.append("")

        lines += [
            f"━━━━━━━━━━━━━━━━━━━━━━",
            f"💼 *Portfolio:*",
            f"• Balans: ${self.executor.balance:,.2f}",
            f"• Bu həftə: {stats.get('win_rate_pct', 0):.0f}% WR | ${stats.get('total_pnl_usd', 0):+.2f}",
            f"• Risk: {'⏸ DAYANDIRILMIŞ' if self._trading_paused or self.risk_manager.status.get('trading_halted') else '✅ Aktiv'}",
        ]

        return "\n".join(lines)

    # ──────────────────────────────────────────────
    # Başlatma
    # ──────────────────────────────────────────────
    async def run(self):
        """TradeX-Pro-nu işə sal"""
        await self.initialize()

        # Başlama mesajı
        if self.telegram:
            startup_msg = (
                f"🚀 *TradeX-Pro v3.0 Multi-Agent!*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• Mode: {Settings.TRADING_MODE.upper()}\n"
                f"• Kapital: ${Settings.INITIAL_CAPITAL:,.0f}\n"
                f"• AI: {'✅ GPT-4o Aktiv' if self.gpt_client else '⚠️ Demo Rejimdə'}\n"
                f"• Agentlər: MacroAnalyst ✅ | ChiefTrader ✅\n"
                f"• Timeframe: 15m+1h+4h+1D (4 TF MTF)\n"
                f"• Siqnal Formula: Tech(40%)+OF(15%)+Sent(15%)+OnChain(10%)+AI(20%)\n"
                f"• İlk skan: növbəti planlaşdırılmış saatda\n\n"
                f"Komandalar üçün /help yazın"
            )
            await self.telegram.send(startup_msg)

        # Zamanlayıcını başlat
        self.scheduler.start()
        logger.info("Zamanlayıcı başladı ✅")

        # Telegram bot-u işə sal (blocking)
        if self.telegram and self.telegram.app:
            async with self.telegram.app:
                await self.telegram.app.start()
                await self.telegram.app.updater.start_polling(
                    drop_pending_updates=True,
                    allowed_updates=["message"],
                )
                logger.info("Bot aktiv — Dayandırmaq üçün Ctrl+C")
                try:
                    await asyncio.Event().wait()
                except (KeyboardInterrupt, SystemExit):
                    pass
                finally:
                    await self.telegram.app.updater.stop()
                    await self.telegram.app.stop()
                    self.scheduler.shutdown()
        else:
            logger.warning("Telegram konfiqurasiya edilməyib — yalnız zamanlayıcı işləyir")
            try:
                await asyncio.Event().wait()
            except (KeyboardInterrupt, SystemExit):
                self.scheduler.shutdown()


async def main():
    bot = TradeXPro()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
