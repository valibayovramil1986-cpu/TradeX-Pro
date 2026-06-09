"""
TradeX-Pro — Risk Manager
Pozisiya ölçüsü, drawdown limiti, circuit breaker
"""

from dataclasses import dataclass
from typing import Optional
from loguru import logger


@dataclass
class RiskParams:
    """Risk parametrləri (faza əsasında dəyişir)"""
    max_risk_per_trade_pct: float = 0.02     # 2% kapitaldan
    max_open_positions: int = 3
    daily_drawdown_limit_pct: float = 0.05   # 5%
    weekly_drawdown_limit_pct: float = 0.10  # 10%
    max_portfolio_exposure_pct: float = 0.30 # 30% bir aktiv sinfindən
    consecutive_loss_threshold: int = 3
    hard_stop_losses: int = 5


@dataclass
class PositionSize:
    units: float         # neçə unit al/sat
    usd_value: float     # dollar dəyəri
    risk_usd: float      # maksimum itki (dollarla)
    risk_pct: float      # kapitalın neçə %-i risk altında
    sl_distance_pct: float


@dataclass
class RiskCheck:
    allowed: bool
    reason: str
    circuit_breaker: bool = False
    halt_trading: bool = False


class RiskManager:
    """
    Bütün risk qaydalarını idarə edir.
    Ticarətdən əvvəl RiskCheck, ticarətdən sonra limit yenilənməsi.
    """

    def __init__(self, params: Optional[RiskParams] = None):
        self.params = params or RiskParams()
        self._consecutive_losses = 0
        self._today_pnl_usd = 0.0
        self._week_pnl_usd = 0.0
        self._open_positions_count = 0
        self._trading_halted = False
        logger.info("RiskManager işə salındı ✅")

    # ──────────────────────────────────────────────
    # Pozisiya Ölçüsü Hesablama
    # ──────────────────────────────────────────────
    def calculate_position_size(self, account_balance: float, entry_price: float,
                                stop_loss_price: float) -> PositionSize:
        """
        Klassik 1%/2% risk qaydası.
        risk_amount = balance × max_risk_pct
        units = risk_amount / |entry - sl|
        """
        if entry_price <= 0 or stop_loss_price <= 0:
            logger.error("Etibarsız qiymət dəyərləri")
            return PositionSize(0, 0, 0, 0, 0)

        risk_amount = account_balance * self.params.max_risk_per_trade_pct
        sl_distance = abs(entry_price - stop_loss_price)

        if sl_distance == 0:
            logger.warning("SL məsafəsi sıfır — pozisiya açılmır")
            return PositionSize(0, 0, 0, 0, 0)

        units = risk_amount / sl_distance
        usd_value = units * entry_price
        sl_distance_pct = sl_distance / entry_price

        # Maksimum pozisiya yoxla (kapitalın 20%-dən çox olmasın)
        max_position_usd = account_balance * 0.20
        if usd_value > max_position_usd:
            units = max_position_usd / entry_price
            usd_value = max_position_usd
            risk_amount = units * sl_distance
            logger.debug(f"Pozisiya ölçüsü məhdudlaşdırıldı: ${usd_value:.2f}")

        return PositionSize(
            units=round(units, 6),
            usd_value=round(usd_value, 2),
            risk_usd=round(risk_amount, 2),
            risk_pct=round(risk_amount / account_balance * 100, 2),
            sl_distance_pct=round(sl_distance_pct * 100, 2),
        )

    # ──────────────────────────────────────────────
    # Ticarət İcazəsi Yoxlama
    # ──────────────────────────────────────────────
    def check_trade_allowed(self, account_balance: float,
                            initial_balance: float) -> RiskCheck:
        """Ticarəti açmadan əvvəl bütün risk limitlərini yoxla"""

        # 1. Ticarət dayandırılıbsa
        if self._trading_halted:
            return RiskCheck(False, "⛔ Ticarət dayandırılıb — manual yenidən başlatma tələb olunur",
                             halt_trading=True)

        # 2. Açıq mövqe limiti
        if self._open_positions_count >= self.params.max_open_positions:
            return RiskCheck(False,
                             f"Maksimum açıq mövqe sayına çatıldı ({self.params.max_open_positions})")

        # 3. Gündəlik drawdown limiti
        daily_drawdown_pct = abs(self._today_pnl_usd) / initial_balance if self._today_pnl_usd < 0 else 0
        if daily_drawdown_pct >= self.params.daily_drawdown_limit_pct:
            self._trading_halted = True
            return RiskCheck(False,
                             f"🚨 Gündəlik drawdown limiti ({self.params.daily_drawdown_limit_pct*100:.0f}%) keçildi! "
                             f"Ticarət DAYANDIRILIB.",
                             circuit_breaker=True, halt_trading=True)

        # 4. Həftəlik drawdown limiti
        weekly_drawdown_pct = abs(self._week_pnl_usd) / initial_balance if self._week_pnl_usd < 0 else 0
        if weekly_drawdown_pct >= self.params.weekly_drawdown_limit_pct:
            self._trading_halted = True
            return RiskCheck(False,
                             f"🚨 Həftəlik drawdown limiti ({self.params.weekly_drawdown_limit_pct*100:.0f}%) keçildi! "
                             f"Ticarət DAYANDIRILIB.",
                             circuit_breaker=True, halt_trading=True)

        # 5. Ardıcıl itki circuit breaker
        if self._consecutive_losses >= self.params.hard_stop_losses:
            self._trading_halted = True
            return RiskCheck(False,
                             f"🚨 {self.params.hard_stop_losses} ardıcıl itki! Ticarət DAYANDIRILIB.",
                             circuit_breaker=True, halt_trading=True)

        if self._consecutive_losses >= self.params.consecutive_loss_threshold:
            logger.warning(f"⚠️ {self._consecutive_losses} ardıcıl itki — pozisiya ölçüsü azaldılır")

        return RiskCheck(True, "✅ Risk limitləri daxilindədir")

    # ──────────────────────────────────────────────
    # Ticarət Nəticəsi Yenilənməsi
    # ──────────────────────────────────────────────
    def record_trade_result(self, pnl_usd: float):
        """Ticarət bağlandıqdan sonra risk sayğaclarını yenilə"""
        self._today_pnl_usd += pnl_usd
        self._week_pnl_usd += pnl_usd

        if pnl_usd < 0:
            self._consecutive_losses += 1
            logger.warning(f"İtki qeydə alındı: ${pnl_usd:.2f} | Ardıcıl itkiler: {self._consecutive_losses}")
        else:
            self._consecutive_losses = 0
            logger.info(f"Qazanc qeydə alındı: ${pnl_usd:.2f}")

    def position_opened(self):
        self._open_positions_count += 1

    def position_closed(self):
        self._open_positions_count = max(0, self._open_positions_count - 1)

    def reset_daily_stats(self):
        """Hər gün gecəyarısı çağır"""
        self._today_pnl_usd = 0.0
        logger.info("Gündəlik risk sayğacları sıfırlandı")

    def reset_weekly_stats(self):
        """Hər həftə bazar ertəsi çağır"""
        self._week_pnl_usd = 0.0
        logger.info("Həftəlik risk sayğacları sıfırlandı")

    def resume_trading(self):
        """Manual yenidən başlatma (/resume komandası)"""
        self._trading_halted = False
        self._consecutive_losses = 0
        logger.info("Ticarət yenidən başladıldı ✅")

    def get_adjusted_risk_pct(self) -> float:
        """
        Ardıcıl itkilər varsa risk faizini azalt
        3+ itki: 50% azalt, 4+ itki: 75% azalt
        """
        if self._consecutive_losses >= 4:
            return self.params.max_risk_per_trade_pct * 0.25
        elif self._consecutive_losses >= 3:
            return self.params.max_risk_per_trade_pct * 0.50
        return self.params.max_risk_per_trade_pct

    @property
    def status(self) -> dict:
        return {
            "trading_halted": self._trading_halted,
            "consecutive_losses": self._consecutive_losses,
            "today_pnl": self._today_pnl_usd,
            "week_pnl": self._week_pnl_usd,
            "open_positions": self._open_positions_count,
        }
