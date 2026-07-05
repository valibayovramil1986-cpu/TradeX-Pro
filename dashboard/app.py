"""
TradeX-Pro — Streamlit Monitoring Dashboard
Real-time trading performance tracker
"""

import os
import time
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from sqlalchemy import create_engine, text
from datetime import datetime, timezone

# ── Konfiqurasiya ──────────────────────────────────────────────
st.set_page_config(
    page_title="TradeX-Pro Dashboard",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="collapsed",
)

DATABASE_URL = os.getenv("DATABASE_URL", "")
REFRESH_INTERVAL = 60  # saniyə


# ── DB Bağlantısı ──────────────────────────────────────────────
@st.cache_resource
def get_engine():
    url = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://")
    return create_engine(url, pool_pre_ping=True)


def query(sql: str, params: dict = None) -> pd.DataFrame:
    try:
        with get_engine().connect() as conn:
            return pd.read_sql(text(sql), conn, params=params)
    except Exception as e:
        st.error(f"DB xəta: {e}")
        return pd.DataFrame()


# ── Məlumat Funksiyaları ───────────────────────────────────────
def load_trades() -> pd.DataFrame:
    return query("""
        SELECT id, symbol, direction, entry_price, exit_price,
               pnl_usd, pnl_pct, exit_reason, phase,
               open_time, close_time, duration_minutes, signal_score
        FROM trades
        WHERE pnl_usd IS NOT NULL
        ORDER BY close_time DESC
    """)


def load_open_positions() -> pd.DataFrame:
    return query("""
        SELECT trade_id, symbol, direction, entry_price,
               stop_loss, tp1, tp2,
               usd_value, open_time
        FROM open_positions
        ORDER BY open_time DESC
    """)


def load_balance() -> dict:
    df = query("SELECT balance, initial_balance FROM balance_state WHERE id = 1")
    if df.empty:
        return {"balance": 1000.0, "initial_balance": 1000.0}
    return df.iloc[0].to_dict()


def load_phase() -> dict:
    df = query("SELECT current_phase, phase_start_date FROM phase_state WHERE id = 1")
    if df.empty:
        return {"current_phase": "1", "phase_start_date": None}
    return df.iloc[0].to_dict()


# ── Başlıq ─────────────────────────────────────────────────────
st.title("🤖 TradeX-Pro Dashboard")
st.caption(f"Son yenilənmə: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")

# ── Yüklə ──────────────────────────────────────────────────────
trades_df = load_trades()
open_df = load_open_positions()
bal = load_balance()
phase = load_phase()

# Faza günü hesabla
phase_start = phase.get("phase_start_date")
if phase_start:
    if hasattr(phase_start, "tzinfo") and phase_start.tzinfo is None:
        phase_start = phase_start.replace(tzinfo=timezone.utc)
    days_in = (datetime.now(timezone.utc) - phase_start).days
else:
    days_in = 0

# ── KPI Kartları ───────────────────────────────────────────────
balance = float(bal.get("balance", 1000))
initial = float(bal.get("initial_balance", 1000))
total_pnl = balance - initial
total_pnl_pct = (total_pnl / initial * 100) if initial else 0

col1, col2, col3, col4, col5 = st.columns(5)

col1.metric("💰 Balans", f"${balance:,.2f}",
            f"{'+' if total_pnl >= 0 else ''}{total_pnl:.2f}$")
col2.metric("📈 Ümumi P&L", f"{'+' if total_pnl_pct >= 0 else ''}{total_pnl_pct:.2f}%")
col3.metric("📋 Faza", f"{phase.get('current_phase', '1')} — Gün {days_in}/14")
col4.metric("🔓 Açıq Mövqe", len(open_df))
col5.metric("📊 Ticarət", len(trades_df))

st.divider()

# ── Açıq Mövqelər ──────────────────────────────────────────────
st.subheader(f"🔓 Açıq Mövqelər ({len(open_df)})")

if open_df.empty:
    st.info("Hazırda açıq mövqe yoxdur.")
else:
    open_display = open_df.copy()
    if "open_time" in open_display.columns:
        open_display["open_time"] = pd.to_datetime(open_display["open_time"]).dt.strftime("%d.%m %H:%M")
    open_display["direction"] = open_display["direction"].map(
        {"LONG": "🟢 LONG", "SHORT": "🔴 SHORT"})
    st.dataframe(open_display, use_container_width=True, hide_index=True)

st.divider()

# ── Performans Statistikası ─────────────────────────────────────
st.subheader("📊 Performans Statistikası")

if trades_df.empty:
    st.info("Hələ bağlanmış ticarət yoxdur.")
else:
    wins = trades_df[trades_df["pnl_usd"] > 0]
    losses = trades_df[trades_df["pnl_usd"] < 0]
    win_rate = len(wins) / len(trades_df) * 100 if len(trades_df) > 0 else 0
    profit_factor = (wins["pnl_usd"].sum() / abs(losses["pnl_usd"].sum())
                     if len(losses) > 0 and losses["pnl_usd"].sum() != 0 else 9.99)
    avg_win = wins["pnl_usd"].mean() if len(wins) > 0 else 0
    avg_loss = losses["pnl_usd"].mean() if len(losses) > 0 else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("✅ Win Rate", f"{win_rate:.1f}%", f"{len(wins)}W / {len(losses)}L")
    c2.metric("⚖️ Profit Factor", f"{min(profit_factor, 9.99):.2f}")
    c3.metric("📈 Ort. Qazanc", f"${avg_win:.2f}")
    c4.metric("📉 Ort. İtki", f"${avg_loss:.2f}")

    # ── P&L Grafiki ────────────────────────────────────────────
    st.subheader("📈 Kumulyativ P&L")
    pnl_series = trades_df.sort_values("close_time")["pnl_usd"].cumsum()
    fig_pnl = px.line(
        x=range(1, len(pnl_series) + 1),
        y=pnl_series.values,
        labels={"x": "Ticarət №", "y": "Kumulyativ P&L ($)"},
        color_discrete_sequence=["#00C896"],
    )
    fig_pnl.add_hline(y=0, line_dash="dash", line_color="gray")
    fig_pnl.update_layout(height=300, margin=dict(t=20, b=20))
    st.plotly_chart(fig_pnl, use_container_width=True)

    # ── Ticarət Tarixçəsi ───────────────────────────────────────
    st.subheader("📋 Son Ticarətlər")
    display = trades_df.head(20).copy()

    def color_pnl(val):
        try:
            v = float(val)
            return "color: #00C896" if v > 0 else "color: #FF4B4B"
        except Exception:
            return ""

    if "close_time" in display.columns:
        display["close_time"] = pd.to_datetime(display["close_time"]).dt.strftime("%d.%m %H:%M")
    if "open_time" in display.columns:
        display["open_time"] = pd.to_datetime(display["open_time"]).dt.strftime("%d.%m %H:%M")
    display["direction"] = display["direction"].map(
        {"LONG": "🟢 LONG", "SHORT": "🔴 SHORT"}).fillna(display["direction"])
    display["pnl_usd"] = display["pnl_usd"].apply(
        lambda x: f"+${x:.2f}" if x > 0 else f"-${abs(x):.2f}")

    cols_show = [c for c in [
        "symbol", "direction", "entry_price", "exit_price",
        "pnl_usd", "exit_reason", "signal_score", "close_time"
    ] if c in display.columns]
    st.dataframe(display[cols_show], use_container_width=True, hide_index=True)

    # ── Win/Loss Pie ────────────────────────────────────────────
    col_pie, col_dir = st.columns(2)
    with col_pie:
        st.subheader("🥧 Win/Loss Nisbəti")
        fig_pie = go.Figure(go.Pie(
            labels=["Qazanc", "İtki"],
            values=[len(wins), len(losses)],
            marker_colors=["#00C896", "#FF4B4B"],
            hole=0.4,
        ))
        fig_pie.update_layout(height=280, margin=dict(t=20, b=20))
        st.plotly_chart(fig_pie, use_container_width=True)

    with col_dir:
        st.subheader("📊 Simvol üzrə P&L")
        sym_pnl = trades_df.groupby("symbol")["pnl_usd"].sum().reset_index()
        sym_pnl.columns = ["Symbol", "P&L ($)"]
        sym_pnl = sym_pnl.sort_values("P&L ($)", ascending=False)
        fig_sym = px.bar(sym_pnl, x="Symbol", y="P&L ($)",
                         color="P&L ($)",
                         color_continuous_scale=["#FF4B4B", "#00C896"])
        fig_sym.update_layout(height=280, margin=dict(t=20, b=20), showlegend=False)
        st.plotly_chart(fig_sym, use_container_width=True)

# ── Avtomatik Yenilənmə ─────────────────────────────────────────
st.divider()
st.caption(f"🔄 Hər {REFRESH_INTERVAL} saniyədə avtomatik yenilənir")
time.sleep(REFRESH_INTERVAL)
st.rerun()
