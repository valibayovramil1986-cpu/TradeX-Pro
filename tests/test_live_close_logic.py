"""
K1 testləri — live rejimdə bağlanış birjaya göndərilir,
uğursuz olduqda daxili qeydlər DƏYİŞMİR.
Mock exchange ilə yoxlanılır (real API çağırışı yoxdur).
"""

from datetime import datetime, timezone

from core.risk_manager import RiskManager, RiskParams, PositionSize
from core.order_executor import OrderExecutor
from tests.test_order_executor import make_signal, open_pos


class MockExchange:
    """ccxt.binance-in minimal mock-u"""

    def __init__(self, fail_orders=False):
        self.fail_orders = fail_orders
        self.orders = []          # göndərilən orderlərin qeydiyyatı
        self.cancelled = []
        self.options = {"defaultType": "future"}
        self._oid = 0

    def create_order(self, symbol, type, side, amount, price=None, params=None):
        if self.fail_orders:
            raise Exception("Mock: exchange xətası")
        self._oid += 1
        order = {"id": f"mock_{self._oid}", "symbol": symbol, "type": type,
                 "side": side, "amount": amount, "status": "closed",
                 "average": 100.5, "price": price}
        self.orders.append(order)
        return order

    def fetch_order(self, order_id, symbol):
        return {"id": order_id, "status": "open"}

    def cancel_order(self, order_id, symbol):
        self.cancelled.append(order_id)


def make_live_executor(exchange) -> OrderExecutor:
    rm = RiskManager(RiskParams())
    return OrderExecutor(risk_manager=rm, mode="live",
                         initial_balance=1000.0, exchange=exchange)


class TestLiveClose:
    def test_live_open_uses_fill_price(self):
        """Y3: giriş qiyməti siqnaldan yox, real fill-dən götürülür"""
        mex = MockExchange()
        ex = make_live_executor(mex)
        pos = open_pos(ex)
        assert pos is not None
        assert pos.entry_price == 100.5          # mock fill (average)
        assert pos.sl_order_id != ""             # birjaya SL qoyulub
        # 2 order: market entry + SL
        assert len(mex.orders) == 2
        assert mex.orders[1]["type"] == "stop_market"

    def test_live_close_sends_exchange_order(self):
        """K1: SL vurulduqda birjaya real bağlanış orderi gedir"""
        mex = MockExchange()
        ex = make_live_executor(mex)
        open_pos(ex, units=10.0)
        orders_before = len(mex.orders)

        closed = ex.check_sl_tp({"BTC/USDT": 94.0})
        assert len(closed) == 1
        # Bağlanış üçün əlavə market order göndərilib
        close_orders = [o for o in mex.orders[orders_before:] if o["type"] == "market"]
        assert len(close_orders) == 1
        assert close_orders[0]["side"] == "sell"   # LONG bağlanışı = sell
        # Köhnə SL orderi ləğv edilib
        assert len(mex.cancelled) == 1

    def test_live_close_failure_keeps_position(self):
        """K1-in əsas qorunması: birja bağlanışı alınmasa mövqe silinmir"""
        mex = MockExchange()
        ex = make_live_executor(mex)
        open_pos(ex, units=10.0)
        balance_before = ex.balance

        mex.fail_orders = True   # bundan sonra bütün orderlər uğursuz
        closed = ex.check_sl_tp({"BTC/USDT": 94.0})

        assert len(closed) == 0, "Uğursuz birja bağlanışı 'bağlandı' sayılmamalıdır!"
        assert len(ex.open_positions) == 1, "Mövqe daxili qeydlərdən silinməməlidir!"
        assert ex.balance == balance_before, "Balans dəyişməməlidir!"

    def test_paper_mode_never_touches_exchange(self):
        mex = MockExchange()
        rm = RiskManager(RiskParams())
        ex = OrderExecutor(risk_manager=rm, mode="paper",
                           initial_balance=1000.0, exchange=mex)
        open_pos(ex, units=10.0)
        ex.check_sl_tp({"BTC/USDT": 94.0})
        assert len(mex.orders) == 0   # paper rejimdə heç bir real order yoxdur

    def test_alert_callback_on_live_close_failure(self):
        """Live bağlanış uğursuz olduqda Telegram alert callback-i çağırılır"""
        import asyncio

        alerts = []

        async def fake_alert(alert_type, details):
            alerts.append((alert_type, details))

        async def scenario():
            mex = MockExchange()
            ex = make_live_executor(mex)
            ex.alert_callback = fake_alert
            open_pos(ex, units=10.0)

            mex.fail_orders = True
            ex.check_sl_tp({"BTC/USDT": 94.0})   # bağlanış uğursuz → alert
            await asyncio.sleep(0)               # yaradılmış task-ın işləməsi üçün

        asyncio.run(scenario())

        assert len(alerts) == 1
        assert "UĞURSUZ" in alerts[0][0]
        assert "BTC/USDT" in alerts[0][1]

    def test_no_alert_without_callback(self):
        """Callback qoşulmayıbsa xəta atmır (paper/test rejimi)"""
        mex = MockExchange()
        ex = make_live_executor(mex)
        open_pos(ex, units=10.0)
        mex.fail_orders = True
        closed = ex.check_sl_tp({"BTC/USDT": 94.0})   # crash olmamalıdır
        assert closed == []

    def test_tp1_syncs_exchange_sl(self):
        """Y3: TP1-dən sonra birjadakı SL cancel+replace olunur"""
        mex = MockExchange()
        ex = make_live_executor(mex)
        pos = open_pos(ex, units=10.0)
        old_sl_id = pos.sl_order_id

        ex.check_sl_tp({"BTC/USDT": 110.0})   # TP1 → breakeven + sync

        assert old_sl_id in mex.cancelled      # köhnə SL ləğv edildi
        assert pos.sl_order_id != old_sl_id    # yenisi qoyuldu
        # Yeni SL orderi qalan miqdar üçündür (10 - 4 = 6)
        new_sl = [o for o in mex.orders if o["id"] == pos.sl_order_id][0]
        assert abs(new_sl["amount"] - 6.0) < 1e-6
