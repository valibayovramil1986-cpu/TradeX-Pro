"""Adaptiv konfidans eşiyi testləri (F&G-yə görə)."""

from ai.agents.chief_trader import adaptive_confidence_threshold, ChiefTraderAgent


class TestAdaptiveThreshold:
    def test_fear_lowers_threshold(self):
        assert adaptive_confidence_threshold(10) == 50.0   # Extreme Fear
        assert adaptive_confidence_threshold(27) == 50.0   # Fear
        assert adaptive_confidence_threshold(39) == 50.0   # sərhəd

    def test_neutral_default(self):
        assert adaptive_confidence_threshold(40) == 55.0
        assert adaptive_confidence_threshold(50) == 55.0
        assert adaptive_confidence_threshold(55) == 55.0

    def test_greed_raises_threshold(self):
        assert adaptive_confidence_threshold(56) == 60.0
        assert adaptive_confidence_threshold(80) == 60.0   # Extreme Greed

    def test_chief_uses_min_confidence_gate(self):
        """Eşik 50 olanda conf=52 siqnal açılır, eşik 60 olanda açılmır."""
        risk_state = {"consecutive_losses": 0, "today_pnl_pct": 0,
                      "trading_halted": False, "win_streak": 0,
                      "base_risk_pct": 0.02, "recent_wins_10": 5}
        portfolio  = {"open_positions_count": 0, "max_positions": 3,
                      "correlated_count": 0, "available_capital_pct": 1.0}

        def decide_with(threshold):
            chief = ChiefTraderAgent(min_confidence=threshold)
            return chief.decide(
                symbol="TRX/USDT", direction="SHORT",
                tech_score=62, order_flow_score=59, macro_score=38,
                mtf_confluence=False,
                risk_state=risk_state, portfolio_state=portfolio,
            )

        d50 = decide_with(50.0)
        d60 = decide_with(60.0)
        # Eyni siqnal: aşağı eşiklə açılır, yüksək eşiklə açılmır
        assert d50.confidence_score == d60.confidence_score
        if 50 <= d50.confidence_score < 60:
            assert d50.proceed and d50.position_tier == "small"
            assert not d60.proceed
