"""
TradeX-Pro — Risk Manager
Pozisiya ölçüsü, drawdown limiti, circuit breaker
Risk sayğacları PostgreSQL-də saxlanılır (restart-a davamlı).
"""

from dataclasses import dataclass
from typing import Optional
from loguru import logger
from sqlalchemy import text

from database.db import get_db, engine, DATABASE_URL


def _is_postgres() -> bool:
    return DATABASE_URL.startswith("postgresql")


@dataclass
class RiskParams:
    max_risk_per_trade_pct: float = 0.02
    max_open_positions: int = 3
    daily_drawdown_limit_pct: float = 0.05
    weekly_drawdown_limit_pct: float = 0.10
    max_portfolio_exposure_pct: float = 0.30
    consecutive_loss_threshold: int = 3
    hard_stop_losses: int = 5


@dataclass
class PositionSize:
    units: float
    usd_value: float
    risk_usd: float
    risk_pct: float
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
    Risk sayğacları PostgreSQL-də saxlanılır — bot restart olanda circuit breakerlər qorunur.
    """

    def __init__(self, params: Optional[RiskParams] = None):
        self.params = params or RiskParams()
        self._consecutive_losses = 0
        self._today_pnl_usd = 0.0
        self._week_pnl_usd = 0.0
        self._open_positions_count = 0
        self._trading_halted = False
        self._halt_reason = ""         # Y2: halt mənşəyi — daily_dd | weekly_dd | consec_loss
        self._win_streak = 0           # Ardıcıl qazanc sayı (Point 5)
        self._recent_results: list = []  # Son 10 nəticə (True=qazanc, False=itki)

        self._init_db()
        self._load_state()
        logger.info("RiskManager işə salındı ✅")

    def _init_db(self):
        ts = "TIMESTAMP DEFAULT CURRENT_TIMESTAMP" if _is_postgres() else "TEXT DEFAULT (datetime('now'))"
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS risk_state (
                    id INTEGER PRIMARY KEY,
                    consecutive_losses INTEGER DEFAULT 0,
                    today_pnl_usd REAL DEFAULT 0,
                    week_pnl_usd REAL DEFAULT 0,
                    trading_halted INTEGER DEFAULT 0,
                    halt_reason TEXT DEFAULT '',
                    updated_at {ts}
                )
            """))
            # Miqrasiya: mövcud DB-lərdə halt_reason olmaya bilər
            try:
                conn.execute(text("ALTER TABLE risk_state ADD COLUMN halt_reason TEXT DEFAULT ''"))
            except Exception:
                pass
            conn.commit()

    def _load_state(self):
        """DB-dən risk sayğaclarını yüklə"""
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT consecutive_losses, today_pnl_usd, week_pnl_usd, trading_halted, halt_reason "
                     "FROM risk_state WHERE id=1")
            ).fetchone()
        if row:
            self._consecutive_losses = row[0] or 0
            self._today_pnl_usd = row[1] or 0.0
            self._week_pnl_usd = row[2] or 0.0
            self._trading_halted = bool(row[3])
            self._halt_reason = row[4] or ""
            logger.info(f"Risk sayğacları DB-dən yükləndi — "
                        f"Ardıcıl itki: {self._consecutive_losses}, "
                        f"Bugün P&L: ${self._today_pnl_usd:.2f}, "
                        f"Dayandırılıb: {self._trading_halted}")

    def _save_state(self):
        """Risk sayğaclarını DB-yə yaz"""
        upsert = """
            INSERT INTO risk_state (id, consecutive_losses, today_pnl_usd, week_pnl_usd, trading_halted, halt_reason)
            VALUES (1, :cl, :td, :wk, :halt, :hr)
            ON CONFLICT (id) DO UPDATE SET
                consecutive_losses=:cl, today_pnl_usd=:td,
                week_pnl_usd=:wk, trading_halted=:halt, halt_reason=:hr,
                updated_at=CURRENT_TIMESTAMP
        """ if _is_postgres() else """
            INSERT OR REPLACE INTO risk_state
            (id, consecutive_losses, today_pnl_usd, week_pnl_usd, trading_halted, halt_reason)
            VALUES (1, :cl, :td, :wk, :halt, :hr)
        """
        with engine.connect() as conn:
            conn.execute(text(upsert), {
                "cl": self._consecutive_losses,
                "td": self._today_pnl_usd,
                "wk": self._week_pnl_usd,
                "halt": 1 if self._trading_halted else 0,
                "hr": self._halt_reason,
            })
            conn.commit()

    # ──────────────────────────────────────────────
    # Pozisiya Ölçüsü Hesablama
    # ──────────────────────────────────────────────
    def calculate_position_size(self, account_balance: float, entry_price: float,
                                stop_loss_price: float,
                                risk_pct_override: float = None) -> PositionSize:
        """
        Klassik 1%/2% risk qaydası.
        risk_pct_override: ardıcıl itkidə azaldılmış risk faizi
        """
        if entry_price <= 0 or stop_loss_price <= 0:
            return PositionSize(0, 0, 0, 0, 0)

        effective_risk_pct = risk_pct_override or self.params.max_risk_per_trade_pct
        risk_amount = account_balance * effective_risk_pct
        sl_distance = abs(entry_price - stop_loss_price)

        if sl_distance == 0:
            return PositionSize(0, 0, 0, 0, 0)

        units = risk_amount / sl_distance
        usd_value = units * entry_price
        sl_distance_pct = sl_distance / entry_price

        max_position_usd = account_balance * 0.20
        if usd_value > max_position_usd:
            units = max_position_usd / entry_price
            usd_value = max_position_usd
            risk_amount = units * sl_distance

        return PositionSize(
            units=round(units, 6),
            usd_value=round(usd_value, 2),
            risk_usd=round(risk_amount, 2),
            risk_pct=round(risk_amount / account_balance * 100, 2),
            sl_distance_pct=round(sl_distance_pct * 100, 2),
        )

    def get_adjusted_risk_pct(self) -> float:
        """
        Ardıcıl itkiyə görə risk faizini azalt:
        3+ itki → 50%, 4+ itki → 25% normal risk
        """
        if self._consecutive_losses >= 4:
            return self.params.max_risk_per_trade_pct * 0.25
        elif self._consecutive_losses >= 3:
            return self.params.max_risk_per_trade_pct * 0.50
        return self.params.max_risk_per_trade_pct

    # ──────────────────────────────────────────────
    # Ticarət İcazəsi Yoxlama
    # ──────────────────────────────────────────────
    def check_trade_allowed(self, account_balance: float,
                            initial_balance: float) -> RiskCheck:
        if self._trading_halted:
            return RiskCheck(False, "⛔ Ticarət dayandırılıb — /resume ilə yenidən başladın",
                             halt_trading=True)

        if self._open_positions_count >= self.params.max_open_positions:
            return RiskCheck(False,
                             f"Maksimum açıq mövqe: {self.params.max_open_positions}")

        daily_dd = abs(self._today_pnl_usd) / initial_balance if self._today_pnl_usd < 0 else 0
        if daily_dd >= self.params.daily_drawdown_limit_pct:
            self._trading_halted = True
            self._halt_reason = "daily_dd"
            self._save_state()
            return RiskCheck(False,
                             f"🚨 Gündəlik drawdown limiti keçildi! Ticarət DAYANDIRILIB.",
                             circuit_breaker=True, halt_trading=True)

        weekly_dd = abs(self._week_pnl_usd) / initial_balance if self._week_pnl_usd < 0 else 0
        if weekly_dd >= self.params.weekly_drawdown_limit_pct:
            self._trading_halted = True
            self._halt_reason = "weekly_dd"
            self._save_state()
            return RiskCheck(False,
                             f"🚨 Həftəlik drawdown limiti keçildi! Ticarət DAYANDIRILIB.",
                             circuit_breaker=True, halt_trading=True)

        if self._consecutive_losses >= self.params.hard_stop_losses:
            self._trading_halted = True
            self._halt_reason = "consec_loss"
            self._save_state()
            return RiskCheck(False,
                             f"🚨 {self.params.hard_stop_losses} ardıcıl itki! Ticarət DAYANDIRILIB.",
                             circuit_breaker=True, halt_trading=True)

        if self._consecutive_losses >= self.params.consecutive_loss_threshold:
            logger.warning(f"⚠️ {self._consecutive_losses} ardıcıl itki — risk azaldıldı")

        return RiskCheck(True, "✅ Risk limitləri daxilindədir")

    # ──────────────────────────────────────────────
    # Nəticə Yenilənməsi
    # ──────────────────────────────────────────────
    def record_pnl(self, pnl_usd: float):
        """
        Y1: Hər çıxışın (qismən və ya tam) P&L-ini gündəlik/həftəlik
        sayğaclara dərhal əlavə et. Win/loss qərarı vermir.
        """
        self._today_pnl_usd += pnl_usd
        self._week_pnl_usd += pnl_usd
        self._save_state()

    def record_trade_outcome(self, win: bool, total_pnl_usd: float = 0.0):
        """
        Y1: Mövqe TAM bağlananda MƏCMU nəticə əsasında win/loss qeyd et.
        Qismən çıxışların cəmi müsbətdirsə trade qazanc sayılır —
        son kiçik hissənin mənfi olması yalançı 'itki' yaratmır.
        """
        self._recent_results.append(win)
        if len(self._recent_results) > 10:
            self._recent_results.pop(0)

        if not win:
            self._consecutive_losses += 1
            self._win_streak = 0
            logger.warning(f"İtki (məcmu): ${total_pnl_usd:.2f} | "
                           f"Ardıcıl itki: {self._consecutive_losses}")
        else:
            self._consecutive_losses = 0
            self._win_streak += 1
            logger.info(f"Qazanc (məcmu): ${total_pnl_usd:.2f} | "
                        f"Ardıcıl qazanc: {self._win_streak}")
        self._save_state()

    def record_trade_result(self, pnl_usd: float):
        """Köhnə API ilə uyğunluq — P&L + nəticəni birlikdə qeyd edir."""
        self.record_pnl(pnl_usd)
        self.record_trade_outcome(pnl_usd > 0, pnl_usd)

    def position_opened(self):
        self._open_positions_count += 1

    def position_closed(self):
        self._open_positions_count = max(0, self._open_positions_count - 1)

    def reset_daily_stats(self):
        self._today_pnl_usd = 0.0
        # Ardıcıl itki sayğacını hər gün sıfırla — köhnə itkilər yeni günü
        # bloklamasın.
        if self._consecutive_losses > 0:
            logger.info(f"Gündəlik sıfırlama: ardıcıl itki sayğacı {self._consecutive_losses} → 0")
            self._consecutive_losses = 0
        # Y2: yalnız GÜNDƏLİK mənşəli halt-ı aç.
        # weekly_dd halt-ı həftəlik reset-ə qədər qüvvədə qalır!
        if self._trading_halted and self._halt_reason in ("daily_dd", "consec_loss"):
            self._trading_halted = False
            self._halt_reason = ""
            logger.info("Gündəlik sıfırlama: ticarət yenidən aktivləşdirildi")
        elif self._trading_halted:
            logger.warning(f"Halt qüvvədə qalır (səbəb: {self._halt_reason})")
        self._save_state()
        logger.info("Gündəlik risk sayğacları sıfırlandı")

    def reset_weekly_stats(self):
        self._week_pnl_usd = 0.0
        # Y2: həftəlik drawdown halt-ı yalnız burada açılır
        if self._trading_halted and self._halt_reason == "weekly_dd":
            self._trading_halted = False
            self._halt_reason = ""
            logger.info("Həftəlik sıfırlama: weekly_dd halt-ı ləğv edildi")
        self._save_state()
        logger.info("Həftəlik risk sayğacları sıfırlandı")

    def resume_trading(self):
        self._trading_halted = False
        self._halt_reason = ""
        self._consecutive_losses = 0
        self._save_state()
        logger.info("Ticarət yenidən başladıldı ✅")

    @property
    def status(self) -> dict:
        recent_wins = sum(1 for r in self._recent_results if r)
        return {
            "trading_halted":    self._trading_halted,
            "halt_reason":       self._halt_reason,
            "consecutive_losses": self._consecutive_losses,
            "today_pnl":         self._today_pnl_usd,
            "week_pnl":          self._week_pnl_usd,
            "open_positions":    self._open_positions_count,
            "win_streak":        self._win_streak,
            "recent_wins_10":    recent_wins,
        }
