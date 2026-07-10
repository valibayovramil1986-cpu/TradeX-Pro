"""
TradeX-Pro — Order Executor
Paper trading + real ticarət icraatı
PostgreSQL-dəki açıq mövqelər restart-a davamlıdır.
TP1=40%, TP2=40%, TP3=20% trailing stop kısmi çıxış sistemi.
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from loguru import logger
from sqlalchemy import text

from core.signal_engine import TradeSignal
from core.risk_manager import RiskManager, PositionSize
from database.db import get_db, engine, DATABASE_URL


def _is_postgres() -> bool:
    return DATABASE_URL.startswith("postgresql")


@dataclass
class OpenPosition:
    trade_id: str
    symbol: str
    direction: str
    entry_price: float
    current_price: float
    stop_loss: float
    tp1: float
    tp2: float
    tp3: float
    units: float
    original_units: float       # ilk açılışdakı tam ölçü (kısmi çıxış üçün)
    usd_value: float
    risk_usd: float
    signal_score: float
    confidence: float
    open_time: str
    phase: str
    tp1_hit: bool = False
    tp2_hit: bool = False
    unrealized_pnl: float = 0.0
    peak_price: float = 0.0     # trailing stop üçün ən yüksək/aşağı qiymət
    trailing_stop: float = 0.0  # TP3 trailing stop səviyyəsi
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
    Paper trading simülatoru + PostgreSQL persistency.
    Real ticarət üçün exchange client-i Faza 3-də aktiv edilir.
    """

    TRAILING_PCT = 0.015    # TP3 trailing: qiymət zirvədən 1.5% geri çəkilərsə çıx

    def __init__(self, risk_manager: RiskManager, mode: str = "paper",
                 initial_balance: float = 1000.0):
        self.risk_manager = risk_manager
        self.mode = mode
        self.initial_balance = initial_balance
        self.open_positions: dict[str, OpenPosition] = {}
        self.closed_trades: list[ClosedTrade] = []

        self._init_db()
        self.balance = self._load_balance(initial_balance)
        self._load_positions()

        logger.info(f"OrderExecutor başladıldı — Mode: {mode}, Balans: ${self.balance:.2f}, "
                    f"Açıq mövqe: {len(self.open_positions)}")

    # ──────────────────────────────────────────────
    # DB Init & Persistence
    # ──────────────────────────────────────────────
    def _init_db(self):
        """open_positions + balance_state cədvəllərini yarat"""
        serial = "SERIAL" if _is_postgres() else "INTEGER"
        ts = "TIMESTAMP DEFAULT CURRENT_TIMESTAMP" if _is_postgres() else "TEXT DEFAULT (datetime('now'))"
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS open_positions (
                    trade_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry_price REAL, current_price REAL,
                    stop_loss REAL, tp1 REAL, tp2 REAL, tp3 REAL,
                    units REAL, original_units REAL,
                    usd_value REAL, risk_usd REAL,
                    signal_score REAL, confidence REAL,
                    open_time TEXT, phase TEXT,
                    tp1_hit INTEGER DEFAULT 0, tp2_hit INTEGER DEFAULT 0,
                    unrealized_pnl REAL DEFAULT 0,
                    peak_price REAL DEFAULT 0, trailing_stop REAL DEFAULT 0,
                    indicators_triggered TEXT DEFAULT '[]',
                    created_at {ts}
                )
            """))
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS balance_state (
                    id INTEGER PRIMARY KEY,
                    balance REAL NOT NULL,
                    initial_balance REAL NOT NULL,
                    updated_at {ts}
                )
            """))
            conn.commit()

    def _load_balance(self, default: float) -> float:
        """DB-dən saxlanılmış balansı yüklə"""
        with engine.connect() as conn:
            row = conn.execute(text("SELECT balance FROM balance_state WHERE id=1")).fetchone()
        if row:
            logger.info(f"Balans DB-dən yükləndi: ${row[0]:.2f}")
            return row[0]
        # İlk dəfə — DB-yə yaz
        self._save_balance(default)
        return default

    def _save_balance(self, balance: float):
        """Balansı DB-yə yaz"""
        upsert = """
            INSERT INTO balance_state (id, balance, initial_balance)
            VALUES (1, :bal, :init)
            ON CONFLICT (id) DO UPDATE SET balance=:bal, updated_at=CURRENT_TIMESTAMP
        """ if _is_postgres() else """
            INSERT OR REPLACE INTO balance_state (id, balance, initial_balance)
            VALUES (1, :bal, :init)
        """
        with engine.connect() as conn:
            conn.execute(text(upsert), {"bal": balance, "init": self.initial_balance})
            conn.commit()

    def _save_position(self, pos: OpenPosition):
        """Açıq mövqeni DB-yə yaz"""
        upsert = """
            INSERT INTO open_positions
            (trade_id, symbol, direction, entry_price, current_price,
             stop_loss, tp1, tp2, tp3, units, original_units,
             usd_value, risk_usd, signal_score, confidence,
             open_time, phase, tp1_hit, tp2_hit, unrealized_pnl,
             peak_price, trailing_stop, indicators_triggered)
            VALUES
            (:tid,:sym,:dir,:ep,:cp,:sl,:tp1,:tp2,:tp3,:units,:orig_units,
             :usd,:risk,:score,:conf,:ot,:phase,:t1,:t2,:upnl,:peak,:trail,:inds)
            ON CONFLICT (trade_id) DO UPDATE SET
                current_price=:cp, stop_loss=:sl, units=:units,
                usd_value=:usd, tp1_hit=:t1, tp2_hit=:t2,
                unrealized_pnl=:upnl, peak_price=:peak,
                trailing_stop=:trail
        """ if _is_postgres() else """
            INSERT OR REPLACE INTO open_positions
            (trade_id, symbol, direction, entry_price, current_price,
             stop_loss, tp1, tp2, tp3, units, original_units,
             usd_value, risk_usd, signal_score, confidence,
             open_time, phase, tp1_hit, tp2_hit, unrealized_pnl,
             peak_price, trailing_stop, indicators_triggered)
            VALUES
            (:tid,:sym,:dir,:ep,:cp,:sl,:tp1,:tp2,:tp3,:units,:orig_units,
             :usd,:risk,:score,:conf,:ot,:phase,:t1,:t2,:upnl,:peak,:trail,:inds)
        """
        with engine.connect() as conn:
            conn.execute(text(upsert), {
                "tid": pos.trade_id, "sym": pos.symbol, "dir": pos.direction,
                "ep": pos.entry_price, "cp": pos.current_price,
                "sl": pos.stop_loss, "tp1": pos.tp1, "tp2": pos.tp2, "tp3": pos.tp3,
                "units": pos.units, "orig_units": pos.original_units,
                "usd": pos.usd_value, "risk": pos.risk_usd,
                "score": pos.signal_score, "conf": pos.confidence,
                "ot": pos.open_time, "phase": pos.phase,
                "t1": 1 if pos.tp1_hit else 0, "t2": 1 if pos.tp2_hit else 0,
                "upnl": pos.unrealized_pnl, "peak": pos.peak_price,
                "trail": pos.trailing_stop,
                "inds": json.dumps(pos.indicators_triggered),
            })
            conn.commit()

    def _remove_position(self, trade_id: str):
        """Bağlanmış mövqeni DB-dən sil"""
        with engine.connect() as conn:
            conn.execute(text("DELETE FROM open_positions WHERE trade_id=:tid"),
                         {"tid": trade_id})
            conn.commit()

    def _load_positions(self):
        """Startup-da DB-dən açıq mövqeləri yüklə"""
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT * FROM open_positions")).mappings().fetchall()
        for row in rows:
            d = dict(row)
            inds = d.get("indicators_triggered", "[]")
            pos = OpenPosition(
                trade_id=d["trade_id"], symbol=d["symbol"], direction=d["direction"],
                entry_price=d["entry_price"], current_price=d["current_price"],
                stop_loss=d["stop_loss"], tp1=d["tp1"], tp2=d["tp2"], tp3=d["tp3"],
                units=d["units"], original_units=d.get("original_units", d["units"]),
                usd_value=d["usd_value"], risk_usd=d["risk_usd"],
                signal_score=d["signal_score"], confidence=d["confidence"],
                open_time=d["open_time"], phase=d["phase"],
                tp1_hit=bool(d["tp1_hit"]), tp2_hit=bool(d["tp2_hit"]),
                unrealized_pnl=d.get("unrealized_pnl", 0.0),
                peak_price=d.get("peak_price", 0.0),
                trailing_stop=d.get("trailing_stop", 0.0),
                indicators_triggered=json.loads(inds) if isinstance(inds, str) else (inds or []),
            )
            self.open_positions[pos.trade_id] = pos
            self.risk_manager.position_opened()
        if self.open_positions:
            logger.info(f"DB-dən {len(self.open_positions)} açıq mövqe yükləndi ✅")

    # ──────────────────────────────────────────────
    # Mövqe Aç
    # ──────────────────────────────────────────────
    def open_position(self, signal: TradeSignal, pos_size: PositionSize,
                      confidence: float, phase: str) -> Optional[OpenPosition]:
        if signal.direction == "NO_TRADE" or not signal.proceed:
            return None
        if pos_size.units <= 0:
            return None

        trade_id = str(uuid.uuid4())[:8]
        entry = signal.entry_zone_high if signal.direction == "LONG" else signal.entry_zone_low

        position = OpenPosition(
            trade_id=trade_id,
            symbol=signal.symbol,
            direction=signal.direction,
            entry_price=entry,
            current_price=entry,
            stop_loss=signal.stop_loss,
            tp1=signal.tp1,
            tp2=signal.tp2,
            tp3=signal.tp3,
            units=pos_size.units,
            original_units=pos_size.units,
            usd_value=pos_size.usd_value,
            risk_usd=pos_size.risk_usd,
            signal_score=signal.final_score,
            confidence=confidence,
            open_time=datetime.now(timezone.utc).isoformat(),
            phase=phase,
            peak_price=entry,
            indicators_triggered=signal.indicators_triggered,
        )

        if self.mode == "paper":
            self.open_positions[trade_id] = position
            self._save_position(position)
            self.risk_manager.position_opened()
            logger.info(f"[PAPER] Mövqe açıldı: {signal.symbol} {signal.direction} "
                        f"@ {entry:.4f} | ID: {trade_id}")
        else:
            success = self._place_live_order(signal, pos_size)
            if success:
                self.open_positions[trade_id] = position
                self._save_position(position)
                self.risk_manager.position_opened()
                logger.info(f"[LIVE] Mövqe açıldı: {signal.symbol} {signal.direction}")
            else:
                logger.error(f"Real order uğursuz: {signal.symbol}")
                return None

        return position

    # ──────────────────────────────────────────────
    # Mövqe Bağla (tam çıxış)
    # ──────────────────────────────────────────────
    def close_position(self, trade_id: str, exit_price: float,
                       exit_reason: str,
                       units_override: float = None) -> Optional[ClosedTrade]:
        """
        Mövqeni tam və ya kısmi bağla.
        units_override: kısmi çıxışda bağlanan unit miqdarı (None=tam bağla)
        """
        if trade_id not in self.open_positions:
            logger.warning(f"Mövqe tapılmadı: {trade_id}")
            return None

        pos = self.open_positions[trade_id]
        close_time = datetime.now(timezone.utc)
        open_time_dt = datetime.fromisoformat(pos.open_time)
        if open_time_dt.tzinfo is None:
            open_time_dt = open_time_dt.replace(tzinfo=timezone.utc)
        duration_min = (close_time - open_time_dt).total_seconds() / 60

        closed_units = units_override if units_override is not None else pos.units
        usd_val = closed_units * pos.entry_price

        if pos.direction == "LONG":
            pnl_usd = (exit_price - pos.entry_price) * closed_units
        else:
            pnl_usd = (pos.entry_price - exit_price) * closed_units

        pnl_pct = pnl_usd / usd_val * 100 if usd_val > 0 else 0

        # Balansı yenilə
        self.balance += pnl_usd
        self._save_balance(self.balance)

        closed = ClosedTrade(
            trade_id=pos.trade_id + (f"_{exit_reason}" if units_override else ""),
            symbol=pos.symbol,
            direction=pos.direction,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            units=closed_units,
            usd_value=round(usd_val, 2),
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
            market_condition="",
        )

        # Tam çıxışsa mövqeni sil, kısmi çıxışsa yenilə
        if units_override is None or (pos.units - closed_units) <= 0.000001:
            self.open_positions.pop(trade_id)
            self._remove_position(trade_id)
            self.risk_manager.record_trade_result(pnl_usd)
            self.risk_manager.position_closed()
        else:
            # Kısmi çıxış — qalan units-i yenilə
            pos.units -= closed_units
            pos.usd_value = pos.units * pos.entry_price
            self._save_position(pos)
            # Kısmi P&L-i risk sayğacına yaz (yalnız SL vurulduqda tam hesab)

        self.closed_trades.append(closed)
        emoji = "✅" if pnl_usd > 0 else "❌"
        logger.info(f"{emoji} {'Kısmi' if units_override else 'Tam'} çıxış: "
                    f"{pos.symbol} | P&L: ${pnl_usd:.2f} ({pnl_pct:.2f}%) | {exit_reason}")
        return closed

    # ──────────────────────────────────────────────
    # SL/TP Yoxlama — Tam yenidən yazılmış
    # ──────────────────────────────────────────────
    def check_sl_tp(self, current_prices: dict[str, float]) -> list[ClosedTrade]:
        """
        Bütün açıq mövqelər üçün SL/TP yoxla.
        TP1 → 40% çıxış, SL → breakeven
        TP2 → 40% çıxış, trailing stop başlar
        TP3 → trailing stop 20% çıxış
        SL  → tam çıxış
        """
        closed = []

        for trade_id, pos in list(self.open_positions.items()):
            price = current_prices.get(pos.symbol)
            if price is None:
                continue

            pos.current_price = price

            if pos.direction == "LONG":
                pos.unrealized_pnl = (price - pos.entry_price) * pos.units

                # ── SL ──
                if price <= pos.stop_loss:
                    result = self.close_position(trade_id, price, "SL_hit")
                    if result:
                        closed.append(result)

                # ── TP2 bağlandıqdan sonra trailing stop ──
                elif pos.tp2_hit:
                    if price > pos.peak_price:
                        pos.peak_price = price
                        pos.trailing_stop = price * (1 - self.TRAILING_PCT)
                        self._save_position(pos)
                    elif price <= pos.trailing_stop:
                        result = self.close_position(trade_id, price, "TP3_trailing")
                        if result:
                            closed.append(result)

                # ── TP2 ──
                elif pos.tp1_hit and not pos.tp2_hit and price >= pos.tp2:
                    units_to_close = pos.original_units * 0.40
                    result = self.close_position(trade_id, price, "TP2_partial", units_to_close)
                    if result:
                        closed.append(result)
                    # Trailing stop başlat
                    pos.tp2_hit = True
                    pos.peak_price = price
                    pos.trailing_stop = price * (1 - self.TRAILING_PCT)
                    self._save_position(pos)
                    logger.info(f"TP2 ✅ {pos.symbol} — Trailing stop başladı @ {pos.trailing_stop:.4f}")

                # ── TP1 ──
                elif not pos.tp1_hit and price >= pos.tp1:
                    units_to_close = pos.original_units * 0.40
                    result = self.close_position(trade_id, price, "TP1_partial", units_to_close)
                    if result:
                        closed.append(result)
                    # SL-i breakeven-ə çək
                    pos.tp1_hit = True
                    pos.stop_loss = pos.entry_price
                    self._save_position(pos)
                    logger.info(f"TP1 ✅ {pos.symbol} — SL breakeven-ə çəkildi @ {pos.entry_price:.4f}")

            else:  # SHORT
                pos.unrealized_pnl = (pos.entry_price - price) * pos.units

                # ── SL ──
                if price >= pos.stop_loss:
                    result = self.close_position(trade_id, price, "SL_hit")
                    if result:
                        closed.append(result)

                # ── Trailing stop (TP2 sonrası) ──
                elif pos.tp2_hit:
                    if price < pos.peak_price:
                        pos.peak_price = price
                        pos.trailing_stop = price * (1 + self.TRAILING_PCT)
                        self._save_position(pos)
                    elif price >= pos.trailing_stop:
                        result = self.close_position(trade_id, price, "TP3_trailing")
                        if result:
                            closed.append(result)

                # ── TP2 ──
                elif pos.tp1_hit and not pos.tp2_hit and price <= pos.tp2:
                    units_to_close = pos.original_units * 0.40
                    result = self.close_position(trade_id, price, "TP2_partial", units_to_close)
                    if result:
                        closed.append(result)
                    pos.tp2_hit = True
                    pos.peak_price = price
                    pos.trailing_stop = price * (1 + self.TRAILING_PCT)
                    self._save_position(pos)

                # ── TP1 ──
                elif not pos.tp1_hit and price <= pos.tp1:
                    units_to_close = pos.original_units * 0.40
                    result = self.close_position(trade_id, price, "TP1_partial", units_to_close)
                    if result:
                        closed.append(result)
                    pos.tp1_hit = True
                    pos.stop_loss = pos.entry_price
                    self._save_position(pos)

        return closed

    def close_all_positions(self, current_prices: dict[str, float],
                            reason: str = "manual_close") -> list[ClosedTrade]:
        """Bütün mövqeləri bağla (/close_all)"""
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
