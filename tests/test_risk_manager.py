"""RiskManager testləri — position sizing, circuit breaker, halt səbəbləri (Y2)."""

from core.risk_manager import RiskManager, RiskParams


def make_rm(**kwargs) -> RiskManager:
    params = RiskParams(**kwargs) if kwargs else RiskParams()
    return RiskManager(params)


# ──────────────────────────────────────────────
# Position sizing
# ──────────────────────────────────────────────
class TestPositionSize:
    def test_basic_2pct_risk(self):
        rm = make_rm()
        # balans 1000, giriş 100, SL 95 → risk $20, məsafə $5 → 4 unit ($400)
        # amma 20% tavan ($200) → 2 unit
        ps = rm.calculate_position_size(1000, 100, 95)
        assert ps.units == 2.0
        assert ps.usd_value == 200.0
        assert ps.risk_usd == 10.0     # 2 unit × $5 SL məsafəsi

    def test_no_cap_when_small(self):
        rm = make_rm()
        # giriş 100, SL 90 → risk $20, məsafə $10 → 2 unit ($200) = tavan həddində
        ps = rm.calculate_position_size(1000, 100, 90)
        assert ps.units == 2.0
        assert ps.risk_usd == 20.0

    def test_zero_sl_distance(self):
        rm = make_rm()
        ps = rm.calculate_position_size(1000, 100, 100)
        assert ps.units == 0

    def test_invalid_prices(self):
        rm = make_rm()
        assert rm.calculate_position_size(1000, 0, 95).units == 0
        assert rm.calculate_position_size(1000, 100, -5).units == 0


# ──────────────────────────────────────────────
# Y1: P&L və nəticə ayrılığı
# ──────────────────────────────────────────────
class TestPnlAccounting:
    def test_record_pnl_does_not_touch_streaks(self):
        rm = make_rm()
        rm.record_pnl(-50)
        assert rm.status["today_pnl"] == -50
        assert rm.status["consecutive_losses"] == 0   # yalnız outcome sayır

    def test_outcome_win_resets_losses(self):
        rm = make_rm()
        rm.record_trade_outcome(False, -10)
        rm.record_trade_outcome(False, -10)
        assert rm.status["consecutive_losses"] == 2
        rm.record_trade_outcome(True, 5)
        assert rm.status["consecutive_losses"] == 0
        assert rm.status["win_streak"] == 1

    def test_legacy_record_trade_result(self):
        rm = make_rm()
        rm.record_trade_result(-25)
        assert rm.status["today_pnl"] == -25
        assert rm.status["consecutive_losses"] == 1


# ──────────────────────────────────────────────
# Y2: Halt səbəbləri və reset məntiqi
# ──────────────────────────────────────────────
class TestHaltReasons:
    def test_daily_dd_halt_and_daily_reset(self):
        rm = make_rm()
        rm.record_pnl(-60)   # 6% > 5% gündəlik limit
        check = rm.check_trade_allowed(940, 1000)
        assert not check.allowed and check.halt_trading
        assert rm.status["halt_reason"] == "daily_dd"

        rm.reset_daily_stats()
        assert not rm.status["trading_halted"]   # gündəlik halt açıldı

    def test_weekly_halt_survives_daily_reset(self):
        rm = make_rm()
        # Həftəlik: -110 (11% > 10%), gündəlik: -30 (3% < 5% — keçir)
        rm.record_pnl(-80)
        rm.reset_daily_stats()          # today=0, week=-80 qalır
        rm.record_pnl(-30)              # today=-30, week=-110
        check = rm.check_trade_allowed(890, 1000)
        assert not check.allowed
        assert rm.status["halt_reason"] == "weekly_dd"

        # KRİTİK: gündəlik reset həftəlik halt-ı AÇMAMALIDIR
        rm.reset_daily_stats()
        assert rm.status["trading_halted"], "weekly_dd halt gündəlik reset-lə açılmamalıdır!"

        # Həftəlik reset açır
        rm.reset_weekly_stats()
        assert not rm.status["trading_halted"]

    def test_consecutive_loss_halt(self):
        rm = make_rm()
        for _ in range(5):
            rm.record_trade_outcome(False, -1)
        check = rm.check_trade_allowed(995, 1000)
        assert not check.allowed
        assert rm.status["halt_reason"] == "consec_loss"

        rm.reset_daily_stats()   # consec_loss halt gündəlik reset-lə açılır
        assert not rm.status["trading_halted"]

    def test_halt_reason_persists_in_db(self):
        rm = make_rm()
        rm.record_pnl(-80)
        rm.reset_daily_stats()
        rm.record_pnl(-30)
        rm.check_trade_allowed(890, 1000)   # weekly_dd halt

        # Yeni instans DB-dən yükləyir (restart simulyasiyası)
        rm2 = make_rm()
        assert rm2.status["trading_halted"]
        assert rm2.status["halt_reason"] == "weekly_dd"

    def test_max_open_positions(self):
        rm = make_rm(max_open_positions=2)
        rm.position_opened()
        rm.position_opened()
        check = rm.check_trade_allowed(1000, 1000)
        assert not check.allowed

    def test_resume_clears_everything(self):
        rm = make_rm()
        rm.record_pnl(-60)
        rm.check_trade_allowed(940, 1000)
        rm.resume_trading()
        assert not rm.status["trading_halted"]
        assert rm.status["halt_reason"] == ""
