"""
TradeX-Pro — Konfiqurasiya
Bütün parametrlərin mərkəzi idarəetməsi
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# .env faylını yüklə
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)


class Settings:
    # ── AI ─────────────────────────────────────
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")
    OPENAI_DAILY_TOKEN_LIMIT: int = int(os.getenv("OPENAI_DAILY_TOKEN_LIMIT", "50000"))

    # ── Telegram ───────────────────────────────
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # ── Birjalar ───────────────────────────────
    BINANCE_API_KEY: str = os.getenv("BINANCE_API_KEY", "")
    BINANCE_SECRET: str = os.getenv("BINANCE_SECRET", "")
    BINANCE_FUTURES: bool = os.getenv("BINANCE_FUTURES", "false").lower() == "true"
    # BINANCE_FUTURES=false → Spot (yalnız LONG)
    # BINANCE_FUTURES=true  → USD-M Futures (LONG + SHORT, leverage)
    ALPACA_API_KEY: str = os.getenv("ALPACA_API_KEY", "")
    ALPACA_SECRET: str = os.getenv("ALPACA_SECRET", "")

    # ── Xəbər API ──────────────────────────────
    NEWSAPI_KEY: str = os.getenv("NEWSAPI_KEY", "")

    # ── Ticarət Rejimi ─────────────────────────
    TRADING_MODE: str = os.getenv("TRADING_MODE", "paper")   # paper | live
    INITIAL_CAPITAL: float = float(os.getenv("INITIAL_CAPITAL", "1000"))

    # ── Risk Parametrləri ──────────────────────
    MAX_RISK_PER_TRADE: float = float(os.getenv("MAX_RISK_PER_TRADE", "0.02"))
    MAX_OPEN_POSITIONS: int = int(os.getenv("MAX_OPEN_POSITIONS", "3"))
    DAILY_DRAWDOWN_LIMIT: float = float(os.getenv("DAILY_DRAWDOWN_LIMIT", "0.05"))
    WEEKLY_DRAWDOWN_LIMIT: float = float(os.getenv("WEEKLY_DRAWDOWN_LIMIT", "0.10"))

    # ── Siqnal Parametrləri ────────────────────
    SIGNAL_THRESHOLD: int = int(os.getenv("SIGNAL_THRESHOLD", "60"))
    STRONG_SIGNAL_THRESHOLD: int = int(os.getenv("STRONG_SIGNAL_THRESHOLD", "75"))
    # ChiefAI-ın mövqe açması üçün minimum konfidans (small tier qapısı)
    CONFIDENCE_THRESHOLD: int = int(os.getenv("CONFIDENCE_THRESHOLD", "60"))

    # ── Zamanlayıcı ────────────────────────────
    # O7: bu parametr artıq scheduler-də real istifadə olunur.
    # Default 1 saat — əvvəlki davranış qorunur; .env ilə dəyişin.
    SCAN_INTERVAL_HOURS: int = int(os.getenv("SCAN_INTERVAL_HOURS", "1"))

    # ── Qeydiyyat ──────────────────────────────
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = "logs/tradex_pro.log"

    @classmethod
    def validate(cls) -> list[str]:
        """Tələb olunan API açarlarını yoxla"""
        errors = []
        if not cls.OPENAI_API_KEY:
            errors.append("❌ OPENAI_API_KEY tapılmadı")
        if not cls.TELEGRAM_BOT_TOKEN:
            errors.append("❌ TELEGRAM_BOT_TOKEN tapılmadı")
        if not cls.TELEGRAM_CHAT_ID:
            errors.append("❌ TELEGRAM_CHAT_ID tapılmadı")
        return errors

    @classmethod
    def display(cls) -> str:
        return (
            f"Mode: {cls.TRADING_MODE} | "
            f"Kapital: ${cls.INITIAL_CAPITAL:,.0f} | "
            f"Risk/Trade: {cls.MAX_RISK_PER_TRADE*100:.1f}% | "
            f"Siqnal Eşiyi: {cls.SIGNAL_THRESHOLD}"
        )
