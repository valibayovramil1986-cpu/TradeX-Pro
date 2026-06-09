"""
TradeX-Pro — Order Executor
Paper trading + real ticarət icraatı
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from loguru import logger

from core.signal_engine import TradeSignal
from core.risk_manager import RiskManager, PositionSize


@dataclass
class OpenPosition:
    trade_id: str
    symbol: str
    direction: str           # LONG | SHORT
    entry_price: float
    current_price: float
    stop_loss: float
    tp1: float
    tp2: float
    tp3: float
    units: float
    usd_value: float
    risk_usd: float
    signal_score: float
    confidence: float
    open_time: str
    phase: str
    tp1_hit: bool = False
    tp2_hit: bool = False
    unrealized_pnl: float = 0.0
    indicators_triggered: list = field(default_factory=list)


@dataclass
class ClosedTrade:
    trade_id: str
    symbol: str
    direction: str
    entry_price: float
    exit_price: float
    units: float
    usd_value: float
    risk_usd: float
    pnl_usd: float
    pnl_pct: float
    signal_score: float
    confidence: float
    open_time: str
    close_time: str
    duration_minutes: float
    exit_reason: str
    phase: str
    indicators_triggered: list
    market_condition: str


class OrderExecutor:
    """
    Paper trading simülatoru.
    Real ticarət üçün exchange client-i inteqrasiya edilir.
    """

    def __init__(self, risk_manager: RiskManager, mode: str = "paper",
                 initial_balance: float = 1000.0):
        self.risk_manager = risk_manager
        self.mode = mode           # "paper" | "live"
        self.balance = initial_balance
        self.initial_balance = initial_balance
        self.open_positions: dict[str, OpenPosition] = {}
        self.closed_trades: list[ClosedTrade] = []
        logger.info(f"OrderExecutor başladıldı — Mode: {mode}, Balans: ${initial_balance:.2f}")

    # ──────────────────────────────────────────────
    # Mövqe Aç
    # ──────────────────────────────────────────────
    def open_position(self, signal: TradeSignal, pos_size: PositionSize,
                      confidence: float, phase: str) -> Optional[OpenPosition]:
        """
        Ticarəti aç. Paper modda simulyasiya, live modda real order.
        """
        if signal.direction == "NO_TRADE" or not signal.proceed:
            return None

        trade_id = str(uuid.uuid4())[:8]

        position = OpenPosition(
            trade_id=trade_id,
            symbol=signal.symbol,
            direction=signal.direction,
            entry_price=signal.entry_zone_high if signal.direction == "LONG" else signal.entry_zone_low,
            current_price=signal.entry_zone_high,
            stop_loss=signal.stop_loss,
            tp1=signal.tp1,
            tp2=signal.tp2,
            tp3=signal.tp3,
            units=pos_size.units,
            usd_value=pos_size.usd_value,
            risk_usd=pos_size.risk_usd,
            signal_score=signal.final_score,
            confidence=confidence,
            open_time=datetime.now(timezone.utc).isoformat(),
            phase=phase,
            indicators_triggered=signal.indicators_triggered,
        )

        if self.mode == "paper":
            self.open_positions[trade_id] = position
            self.risk_manager.position_opened()
            logger.info(f"[PAPER] Mövqe açıldı: {signal.symbol} {signal.direction} "
                        f"@ {position.entry_price:.4f} | ID: {trade_id}")
        else:
            # Real ticarət — exchange client çağır
            success = self._place_live_order(signal, pos_size)
            if success:
                self.open_positions[trade_id] = position
                self.risk_manager.position_opened()
                logger.info(f"[LIVE] Mövqe açıldı: {signal.symbol} {signal.direction}")
            else:
                logger.error(f"Real order uğursuz oldu: {signal.symbol}")
                return None

        return position

    # ──────────────────────────────────────────────
    # Mövqe Bağla
    # ──────────────────────────────────────────────
    def close_position(self, trade_id: str, exit_price: float,
                       exit_reason: str) -> Optional[ClosedTrade]:
        """Açıq mövqeni bağla və ClosedTrade qaytar"""
        if trade_id not in self.open_positions:
            logger.warning(f"Mövqe tapılmadı: {trade_id}")
            return None

        pos = self.open_positions.pop(trade_id)
        close_time = datetime.now(timezone.utc)
        open_time = datetime.fromisoformat(pos.open_time)
        duration_min = (close_time - open_time).total_seconds() / 60

        # P&L hesabla
        if pos.direction == "LONG":
            pnl_usd = (exit_price - pos.entry_price) * pos.units
        else:
            pnl_usd = (pos.entry_price - exit_price) * pos.units

        pnl_pct = pnl_usd / pos.usd_value * 100 if pos.usd_value > 0 else 0

        # Balansı yenilə
        self.balance += pnl_usd
        self.risk_manager.record_trade_result(pnl_usd)
        self.risk_manager.position_closed()

        closed = ClosedTrade(
            trade_id=pos.trade_id,
            symbol=pos.symbol,
            direction=pos.direction,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            units=pos.units,
            usd_value=pos.usd_value,
            risk_usd=pos.risk_usd,
            pnl_usd=round(pnl_usd, 2),
            pnl_pct=round(pnl_pct, 2),
            signal_score=pos.signal_score,
            confidence=pos.confidence,
            open_time=pos.open_time,
            close_time=close_time.isoformat(),
            duration_minutes=round(duration_min, 1),
            exit_reason=exit_reason,
            phase=pos.phase,
            indicators_triggered=pos.indicators_triggered,
            market_condition="",  # Sonra doldurulacaq
        )

        self.closed_trades.append(closed)
        emoji = "✅" if pnl_usd > 0 else "❌"
        logger.info(f"{emoji} Mövqe bağlandı: {pos.symbol} | P&L: ${pnl_usd:.2f} ({pnl_pct:.2f}%) | Səbəb: {exit_reason}")

        return closed

    # ──────────────────────────────────────────────
    # SL/TP Yoxlama (hər skan zamanı)
    # ──────────────────────────────────────────────
    def check_sl_tp(self, current_prices: dict[str, float]) -> list[ClosedTrade]:
        """
        Bütün açıq mövqelər üçün cari qiymətlərə görə SL/TP yoxla.
        current_prices: {"BTC/USDT": 65000.0, ...}
        """
        closed = []
        for trade_id, pos in list(self.open_positions.items()):
            price = current_prices.get(pos.symbol)
            if price is None:
                continue

            pos.current_price = price
            if pos.direction == "LONG":
                pos.unrealized_pnl = (price - pos.entry_price) * pos.units
                # SL
                if price <= pos.stop_loss:
                    result = self.close_position(trade_id, price, "SL_hit")
                    if result:
                        closed.append(result)
                # TP1 (40% çıxış)
                elif not pos.tp1_hit and price >= pos.tp1:
                    partial = self.close_position(trade_id, price, "TP1_reached_partial")
                    if partial:
                        closed.append(partial)
                        pos.tp1_hit = True
                # TP2
                elif pos.tp1_hit and not pos.tp2_hit and price >= pos.tp2:
                    result = self.close_position(trade_id, price, "TP2_reached")
                    if result:
                        closed.append(result)

            else:  # SHORT
                pos.unrealized_pnl = (pos.entry_price - price) * pos.units
                if price >= pos.stop_loss:
                    result = self.close_position(trade_id, price, "SL_hit")
                    if result:
                        closed.append(result)
                elif not pos.tp1_hit and price <= pos.tp1:
                    partial = self.close_position(trade_id, price, "TP1_reached_partial")
                    if partial:
                        closed.append(partial)
                        pos.tp1_hit = True
                elif pos.tp1_hit and not pos.tp2_hit and price <= pos.tp2:
                    result = self.close_position(trade_id, price, "TP2_reached")
                    if result:
                        closed.append(result)

        return closed

    def close_all_positions(self, current_prices: dict[str, float], reason: str = "manual_close"):
        """Bütün mövqeləri bağla (emergency /close_all)"""
        closed = []
        for trade_id in list(self.open_positions.keys()):
            pos = self.open_positions[trade_id]
            price = current_prices.get(pos.symbol, pos.current_price)
            result = self.close_position(trade_id, price, reason)
            if result:
                closed.append(result)
        logger.warning(f"Bütün mövqelər bağlandı: {len(closed)} mövqe")
        return closed

    def _place_live_order(self, signal: TradeSignal, pos_size: PositionSize) -> bool:
        """Real exchange-ə order göndər — Faza 3-də aktiv edilir"""
        logger.warning("Live order funksiyası hələ aktiv deyil — Faza 3-ü gözləyin")
        return False

    @property
    def portfolio_value(self) -> float:
        unrealized = sum(p.unrealized_pnl for p in self.open_positions.values())
        return self.balance + unrealized

    @property
    def total_pnl(self) -> float:
        return self.portfolio_value - self.initial_balance

    @property
    def total_pnl_pct(self) -> float:
        return self.total_pnl / self.initial_balance * 100
