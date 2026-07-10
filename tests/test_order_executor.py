"""
OrderExecutor testləri — paper trading, qismən çıxışlar (Y1),
SL/TP məntiqi, balans persistensiyası.
"""

from datetime import datetime, timezone

from core.risk_manager import RiskManager, RiskParams, PositionSize
from core.order_executor import OrderExecutor
from core.signal_engine import TradeSignal


def make_signal(symbol="BTC/USDT", direction="LONG",
                entry=100.0, sl=95.0, tp1=110.0, tp2=120.0, tp3=140.0) -> TradeSignal:
    return TradeSignal(
        symbol=symbol, direction=direction,
        technical_score=70.0, gpt_adjustment=0.0, final_score=70.0,
        entry_zone_low=entry, entry_zone_high=entry,
        stop_loss=sl, tp1=tp1, tp2=tp2, tp3=tp3,
        risk_reward_tp1=2.0, risk_reward_tp2=4.0,
        atr=2.0, trend="uptrend", volatility="medium",
        indicators_triggered=["EMA", "MACD"],
        signal_strength="STRONG", reasoning="test",
        gpt_context="", timestamp=datetime.now(timezone.utc).isoformat(),
        timeframe="1h", market_condition="uptrend_medium_volatility",
        proceed=True,
    )


def make_executor(balance=1000.0) -> OrderExecutor:
    rm = RiskManager(RiskParams())
    return OrderExecutor(risk_manager=rm, mode="paper", initial_balance=balance)


def open_pos(ex: OrderExecutor, signal=None, units=10.0):
    signal = signal or make_signal()
    ps = PositionSize(units=units, usd_value=units * signal.entry_zone_high,
                      risk_usd=units * abs(signal.entry_zone_high - signal.stop_loss),
                      risk_pct=2.0, sl_distance_pct=5.0)
    return ex.open_position(signal, ps, confidence=7.5, phase="1")


# ──────────────────────────────────────────────
# Əsas axın
# ──────────────────────────────────────────────
class TestBasicFlow:
    def test_open_paper_position(self):
        ex = make_executor()
        pos = open_pos(ex)
        assert pos is not None
        assert len(ex.open_positions) == 1
        assert pos.entry_price == 100.0
        assert len(pos.trade_id) == 36   # O9: tam UUID

    def test_position_persists_after_restart(self):
        ex = make_executor()
        open_pos(ex)
        # Restart simulyasiyası — yeni executor DB-dən yükləyir
        ex2 = make_executor()
        assert len(ex2.open_positions) == 1

    def test_sl_full_loss(self):
        ex = make_executor()
        open_pos(ex, units=10.0)
        closed = ex.check_sl_tp({"BTC/USDT": 94.0})
        assert len(closed) == 1
        assert closed[0].exit_reason == "SL_hit"
        assert closed[0].pnl_usd == -60.0          # (94-100)*10
        assert ex.risk_manager.status["consecutive_losses"] == 1
        assert ex.risk_manager.status["today_pnl"] == -60.0
        assert len(ex.open_positions) == 0

    def test_balance_updated_and_persisted(self):
        ex = make_executor()
        open_pos(ex, units=10.0)
        ex.check_sl_tp({"BTC/USDT": 94.0})
        assert ex.balance == 940.0
        ex2 = make_executor()
        assert ex2.balance == 940.0                # O5: DB-dən yüklənir


# ──────────────────────────────────────────────
# Qismən çıxışlar — TP1/TP2/Trailing
# ──────────────────────────────────────────────
class TestPartialExits:
    def test_tp1_partial_and_breakeven(self):
        ex = make_executor()
        pos = open_pos(ex, units=10.0)
        closed = ex.check_sl_tp({"BTC/USDT": 110.0})

        assert len(closed) == 1
        assert closed[0].exit_reason == "TP1_partial"
        assert abs(closed[0].pnl_usd - 40.0) < 1e-6      # 4 unit × $10
        assert pos.tp1_hit
        assert pos.stop_loss == 100.0                    # breakeven
        assert abs(pos.units - 6.0) < 1e-6
        assert abs(pos.realized_pnl - 40.0) < 1e-6       # Y1: mövqedə yığılır
        # Y1: qismən P&L dərhal gündəlik sayğaca düşür
        assert ex.risk_manager.status["today_pnl"] == 40.0
        # Y1: qismən çıxış win/loss sayğacına toxunmur
        assert ex.risk_manager.status["consecutive_losses"] == 0
        assert ex.risk_manager.status["win_streak"] == 0

    def test_tp2_starts_trailing(self):
        ex = make_executor()
        pos = open_pos(ex, units=10.0)
        ex.check_sl_tp({"BTC/USDT": 110.0})   # TP1
        closed = ex.check_sl_tp({"BTC/USDT": 120.0})   # TP2
        assert closed[0].exit_reason == "TP2_partial"
        assert pos.tp2_hit
        assert pos.trailing_stop > 0
        assert abs(pos.units - 2.0) < 1e-6    # 10 - 4 - 4

    def test_y1_overall_win_despite_negative_last_chunk(self):
        """
        Y1-in əsas ssenarisi: TP1 qazancı (+40), sonra qiymət breakeven-in
        altına düşür (-6 son hissə). Məcmu +34 → WIN sayılmalıdır,
        köhnə kod bunu LOSS kimi qeyd edirdi.
        """
        ex = make_executor()
        open_pos(ex, units=10.0)
        ex.check_sl_tp({"BTC/USDT": 110.0})        # TP1: +40, SL→100
        closed = ex.check_sl_tp({"BTC/USDT": 99.0})  # SL_hit @99: 6×(-1) = -6

        assert closed[0].exit_reason == "SL_hit"
        assert abs(closed[0].pnl_usd - (-6.0)) < 1e-6
        # Məcmu +34 → win; ardıcıl itki artmamalıdır
        assert ex.risk_manager.status["consecutive_losses"] == 0, \
            "Qazanclı trade yalançı LOSS kimi qeyd edildi (Y1 reqressiyası)!"
        assert ex.risk_manager.status["win_streak"] == 1
        assert abs(ex.risk_manager.status["today_pnl"] - 34.0) < 1e-6

    def test_short_position_flow(self):
        ex = make_executor()
        sig = make_signal(direction="SHORT", entry=100.0, sl=105.0,
                          tp1=90.0, tp2=80.0, tp3=60.0)
        pos = open_pos(ex, signal=sig, units=10.0)
        closed = ex.check_sl_tp({"BTC/USDT": 90.0})   # TP1
        assert closed[0].exit_reason == "TP1_partial"
        assert abs(closed[0].pnl_usd - 40.0) < 1e-6   # SHORT: (100-90)×4
        assert pos.stop_loss == 100.0                 # breakeven

    def test_trailing_stop_close(self):
        ex = make_executor()
        pos = open_pos(ex, units=10.0)
        ex.check_sl_tp({"BTC/USDT": 110.0})   # TP1
        ex.check_sl_tp({"BTC/USDT": 120.0})   # TP2 → trail = 120×0.985 = 118.2
        ex.check_sl_tp({"BTC/USDT": 125.0})   # peak yenilənir → trail = 123.125
        closed = ex.check_sl_tp({"BTC/USDT": 123.0})  # trail vuruldu
        assert closed[0].exit_reason == "TP3_trailing"
        assert len(ex.open_positions) == 0
        # Məcmu: 40 + 80 + 2×23 = 166 → win
        assert ex.risk_manager.status["win_streak"] == 1


# ──────────────────────────────────────────────
# close_all
# ──────────────────────────────────────────────
class TestCloseAll:
    def test_close_all_positions(self):
        ex = make_executor()
        open_pos(ex, make_signal(symbol="BTC/USDT"), units=5.0)
        open_pos(ex, make_signal(symbol="ETH/USDT"), units=5.0)
        closed = ex.close_all_positions({"BTC/USDT": 101.0, "ETH/USDT": 99.0},
                                        "emergency_close_all")
        assert len(closed) == 2
        assert len(ex.open_positions) == 0
