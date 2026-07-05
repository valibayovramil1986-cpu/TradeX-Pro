"""
TradeX-Pro — Modern Monitoring Dashboard v2
"""

import os, time
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from sqlalchemy import create_engine, text
from datetime import datetime, timezone

# ── Səhifə konfiqurasiyası ─────────────────────────────────────
st.set_page_config(
    page_title="TradeX-Pro",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Xüsusi CSS ────────────────────────────────────────────────
st.markdown("""
<style>
  /* Ümumi fon */
  .stApp { background-color: #0e1117; }

  /* KPI kartları */
  .kpi-card {
    background: linear-gradient(135deg, #1a1f2e, #252b3b);
    border: 1px solid #2d3548;
    border-radius: 16px;
    padding: 20px 24px;
    text-align: center;
    height: 110px;
    display: flex;
    flex-direction: column;
    justify-content: center;
  }
  .kpi-label {
    color: #8892a4;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 1px;
    text-transform: uppercase;
    margin-bottom: 6px;
  }
  .kpi-value {
    color: #ffffff;
    font-size: 26px;
    font-weight: 700;
    line-height: 1.2;
  }
  .kpi-delta-pos { color: #00d4aa; font-size: 13px; margin-top: 4px; }
  .kpi-delta-neg { color: #ff4b6e; font-size: 13px; margin-top: 4px; }
  .kpi-delta-neu { color: #8892a4; font-size: 13px; margin-top: 4px; }

  /* Bölmə başlıqları */
  .section-title {
    color: #c9d1e0;
    font-size: 15px;
    font-weight: 600;
    letter-spacing: 0.5px;
    margin: 24px 0 12px 0;
    padding-bottom: 8px;
    border-bottom: 1px solid #2d3548;
  }

  /* Cədvəl */
  .dataframe { background-color: #1a1f2e !important; }

  /* Faza progress bar */
  .phase-bar-bg {
    background: #2d3548;
    border-radius: 8px;
    height: 10px;
    width: 100%;
    margin-top: 8px;
  }
  .phase-bar-fill {
    background: linear-gradient(90deg, #00d4aa, #0099ff);
    border-radius: 8px;
    height: 10px;
    transition: width 0.5s ease;
  }

  /* Ticarət rəngi */
  .win-badge {
    background: rgba(0, 212, 170, 0.15);
    color: #00d4aa;
    border: 1px solid #00d4aa40;
    padding: 2px 8px;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 600;
  }
  .loss-badge {
    background: rgba(255, 75, 110, 0.15);
    color: #ff4b6e;
    border: 1px solid #ff4b6e40;
    padding: 2px 8px;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 600;
  }

  /* Divider */
  hr { border-color: #2d3548 !important; margin: 20px 0 !important; }

  /* Header */
  .header-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 24px;
  }
  .header-title {
    color: #ffffff;
    font-size: 24px;
    font-weight: 700;
    letter-spacing: -0.5px;
  }
  .header-sub {
    color: #8892a4;
    font-size: 13px;
    margin-top: 4px;
  }
  .live-dot {
    display: inline-block;
    width: 8px; height: 8px;
    background: #00d4aa;
    border-radius: 50%;
    margin-right: 6px;
    animation: pulse 2s infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.3; }
  }
</style>
""", unsafe_allow_html=True)

DATABASE_URL = os.getenv("DATABASE_URL", "")
REFRESH = 60

# ── DB ────────────────────────────────────────────────────────
@st.cache_resource
def get_engine():
    url = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://")
    return create_engine(url, pool_pre_ping=True)

def q(sql, params=None):
    try:
        with get_engine().connect() as conn:
            return pd.read_sql(text(sql), conn, params=params)
    except Exception as e:
        return pd.DataFrame()

def scalar(sql, default=None):
    df = q(sql)
    if df.empty: return default
    return df.iloc[0, 0]

# ── Data ──────────────────────────────────────────────────────
trades   = q("SELECT * FROM trades WHERE pnl_usd IS NOT NULL ORDER BY close_time DESC")
opens    = q("SELECT * FROM open_positions ORDER BY open_time DESC")
bal_row  = q("SELECT balance, initial_balance FROM balance_state WHERE id=1")
phase_row= q("SELECT current_phase, phase_start_date FROM phase_state WHERE id=1")

balance  = float(bal_row["balance"].iloc[0]) if not bal_row.empty else 1000.0
initial  = float(bal_row["initial_balance"].iloc[0]) if not bal_row.empty else 1000.0
pnl_usd  = balance - initial
pnl_pct  = pnl_usd / initial * 100

cur_phase = phase_row["current_phase"].iloc[0] if not phase_row.empty else "1"
phase_start = None
if not phase_row.empty:
    ps = phase_row["phase_start_date"].iloc[0]
    if ps is not None:
        if hasattr(ps, "tzinfo"):
            phase_start = ps.replace(tzinfo=timezone.utc) if ps.tzinfo is None else ps
        else:
            phase_start = datetime.fromisoformat(str(ps)).replace(tzinfo=timezone.utc)
days_in = (datetime.now(timezone.utc) - phase_start).days if phase_start else 0
phase_duration = 14

wins   = trades[trades["pnl_usd"] > 0] if not trades.empty else pd.DataFrame()
losses = trades[trades["pnl_usd"] < 0] if not trades.empty else pd.DataFrame()
total  = len(trades)
win_rate = len(wins)/total*100 if total > 0 else 0
pf = (wins["pnl_usd"].sum() / abs(losses["pnl_usd"].sum())
      if len(losses) > 0 and losses["pnl_usd"].sum() != 0 else 0.0)

now_str = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")

# ── Header ────────────────────────────────────────────────────
st.markdown(f"""
<div class="header-row">
  <div>
    <div class="header-title">🤖 TradeX-Pro Dashboard</div>
    <div class="header-sub">
      <span class="live-dot"></span>Canlı • Faza {cur_phase} — Gün {days_in}/{phase_duration} • {now_str}
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── KPI Kartları ──────────────────────────────────────────────
c1, c2, c3, c4, c5, c6 = st.columns(6)

def kpi(col, label, value, delta=None, delta_positive=None):
    if delta is not None:
        if delta_positive is True:
            d_class = "kpi-delta-pos"
        elif delta_positive is False:
            d_class = "kpi-delta-neg"
        else:
            d_class = "kpi-delta-neu"
        delta_html = f'<div class="{d_class}">{delta}</div>'
    else:
        delta_html = ""
    col.markdown(f"""
    <div class="kpi-card">
      <div class="kpi-label">{label}</div>
      <div class="kpi-value">{value}</div>
      {delta_html}
    </div>
    """, unsafe_allow_html=True)

kpi(c1, "💰 Balans", f"${balance:,.2f}",
    f"{'▲' if pnl_usd>=0 else '▼'} ${abs(pnl_usd):.2f}", pnl_usd >= 0)
kpi(c2, "📈 P&L", f"{'+' if pnl_pct>=0 else ''}{pnl_pct:.2f}%",
    f"${'+' if pnl_usd>=0 else ''}{pnl_usd:.2f}", pnl_usd >= 0)
kpi(c3, "✅ Win Rate", f"{win_rate:.1f}%",
    f"{len(wins)}W / {len(losses)}L", win_rate >= 50 if total > 0 else None)
kpi(c4, "⚖️ Profit Factor", f"{min(pf,9.99):.2f}" if pf else "—",
    "Hədəf ≥ 1.2", pf >= 1.2 if pf else None)
kpi(c5, "📊 Ticarət", str(total),
    f"Açıq: {len(opens)}", None)
kpi(c6, "🎯 Faza {cur_phase}", f"{days_in}/{phase_duration} gün",
    f"{phase_duration - days_in} gün qaldı", None)

# Faza progress bar
phase_pct = min(days_in / phase_duration * 100, 100)
st.markdown(f"""
<div style="margin: 16px 0 24px 0;">
  <div style="color:#8892a4; font-size:11px; margin-bottom:4px;">
    Faza {cur_phase} irəliləməsi: {phase_pct:.0f}%
  </div>
  <div class="phase-bar-bg">
    <div class="phase-bar-fill" style="width:{phase_pct}%;"></div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── İki sütunlu əsas bölmə ────────────────────────────────────
left, right = st.columns([3, 2], gap="large")

with left:
    # P&L Grafiki
    st.markdown('<div class="section-title">📈 Kumulyativ P&L</div>', unsafe_allow_html=True)
    if not trades.empty:
        sorted_t = trades.sort_values("close_time")
        cum = sorted_t["pnl_usd"].cumsum().values
        xs  = list(range(1, len(cum)+1))

        fig = go.Figure()
        # Fill area
        fill_color = "rgba(0,212,170,0.08)" if cum[-1] >= 0 else "rgba(255,75,110,0.08)"
        line_color  = "#00d4aa" if cum[-1] >= 0 else "#ff4b6e"
        fig.add_trace(go.Scatter(
            x=xs, y=cum.tolist(),
            mode="lines+markers",
            fill="tozeroy",
            fillcolor=fill_color,
            line=dict(color=line_color, width=2.5),
            marker=dict(size=6, color=line_color),
            hovertemplate="Ticarət %{x}<br>P&L: $%{y:.2f}<extra></extra>",
        ))
        fig.add_hline(y=0, line_dash="dot", line_color="#2d3548", line_width=1)
        fig.update_layout(
            height=280,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=10, b=10, l=0, r=0),
            xaxis=dict(showgrid=False, color="#8892a4",
                       title="Ticarət №", title_font_color="#8892a4"),
            yaxis=dict(showgrid=True, gridcolor="#1e2435", color="#8892a4",
                       title="P&L ($)", title_font_color="#8892a4"),
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    else:
        st.info("Hələ bağlanmış ticarət yoxdur.")

    # Son ticarətlər
    st.markdown('<div class="section-title">📋 Son Ticarətlər</div>', unsafe_allow_html=True)
    if not trades.empty:
        disp = trades.head(15).copy()
        disp["Vaxt"] = pd.to_datetime(disp["close_time"]).dt.strftime("%d.%m %H:%M")
        disp["İstiqamət"] = disp["direction"].map({"LONG":"🟢 LONG","SHORT":"🔴 SHORT"})
        disp["Giriş"]  = disp["entry_price"].apply(lambda x: f"{x:.4f}" if x else "—")
        disp["Çıxış"]  = disp["exit_price"].apply(lambda x: f"{x:.4f}" if x else "—")
        disp["P&L"]    = disp["pnl_usd"].apply(
            lambda x: f"+${x:.2f}" if x > 0 else f"-${abs(x):.2f}")
        disp["Səbəb"]  = disp["exit_reason"].fillna("—")
        disp["Bal"]    = disp["signal_score"].apply(
            lambda x: f"{x:.0f}" if x else "—")

        show = disp[["Vaxt","symbol","İstiqamət","Giriş","Çıxış","P&L","Səbəb","Bal"]]
        show.columns = ["Vaxt","Simvol","İstiqamət","Giriş","Çıxış","P&L","Çıxış Səbəbi","Bal"]

        st.dataframe(
            show,
            use_container_width=True,
            hide_index=True,
            column_config={
                "P&L": st.column_config.TextColumn("P&L ($)"),
            }
        )
    else:
        st.info("Ticarət yoxdur.")

with right:
    # Açıq mövqelər
    st.markdown(f'<div class="section-title">🔓 Açıq Mövqelər ({len(opens)})</div>',
                unsafe_allow_html=True)
    if not opens.empty:
        for _, pos in opens.iterrows():
            direction = pos.get("direction", "")
            symbol    = pos.get("symbol", "")
            entry     = pos.get("entry_price", 0)
            sl        = pos.get("stop_loss", 0)
            tp1       = pos.get("tp1", 0)
            tp2       = pos.get("tp2", 0)
            usd_val   = pos.get("usd_value", 0)
            open_t    = pos.get("open_time", "")
            emoji     = "🟢" if direction == "LONG" else "🔴"

            st.markdown(f"""
            <div style="background:#1a1f2e; border:1px solid #2d3548; border-radius:12px;
                        padding:14px 16px; margin-bottom:10px;">
              <div style="display:flex; justify-content:space-between; margin-bottom:8px;">
                <span style="color:#fff; font-weight:700; font-size:15px;">
                  {emoji} {symbol}
                </span>
                <span style="color:#8892a4; font-size:12px;">{str(open_t)[:16]}</span>
              </div>
              <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px;
                          font-size:12px; color:#8892a4;">
                <div>Giriş: <span style="color:#c9d1e0;">{entry:.4f}</span></div>
                <div>Ölçü: <span style="color:#c9d1e0;">${float(usd_val):.0f}</span></div>
                <div>SL: <span style="color:#ff4b6e;">{sl:.4f}</span></div>
                <div>TP1: <span style="color:#00d4aa;">{tp1:.4f}</span></div>
                <div>TP2: <span style="color:#00d4aa;">{tp2:.4f}</span></div>
              </div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div style="background:#1a1f2e; border:1px solid #2d3548; border-radius:12px;
                    padding:24px; text-align:center; color:#8892a4;">
          Hazırda açıq mövqe yoxdur
        </div>
        """, unsafe_allow_html=True)

    # Win/Loss donut + Simvol bar
    if not trades.empty:
        st.markdown('<div class="section-title">🥧 Win / Loss</div>', unsafe_allow_html=True)
        fig_d = go.Figure(go.Pie(
            labels=["Qazanc","İtki"],
            values=[max(len(wins),0), max(len(losses),0)],
            hole=0.55,
            marker_colors=["#00d4aa","#ff4b6e"],
            textinfo="percent",
            textfont_size=13,
        ))
        fig_d.update_layout(
            height=220,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=0, b=0, l=0, r=0),
            legend=dict(font_color="#8892a4", bgcolor="rgba(0,0,0,0)"),
            annotations=[dict(
                text=f"{win_rate:.0f}%<br><span style='font-size:10px'>Win</span>",
                x=0.5, y=0.5, font_size=18, font_color="#ffffff",
                showarrow=False,
            )],
        )
        st.plotly_chart(fig_d, use_container_width=True, config={"displayModeBar": False})

        st.markdown('<div class="section-title">📊 Simvol üzrə P&L</div>', unsafe_allow_html=True)
        sym = trades.groupby("symbol")["pnl_usd"].sum().reset_index()
        sym.columns = ["symbol","pnl"]
        sym = sym.sort_values("pnl")
        colors = ["#00d4aa" if v >= 0 else "#ff4b6e" for v in sym["pnl"]]
        fig_s = go.Figure(go.Bar(
            x=sym["pnl"], y=sym["symbol"],
            orientation="h",
            marker_color=colors,
            text=sym["pnl"].apply(lambda x: f"+${x:.1f}" if x >= 0 else f"-${abs(x):.1f}"),
            textposition="outside",
            textfont_color="#8892a4",
            hovertemplate="%{y}: $%{x:.2f}<extra></extra>",
        ))
        fig_s.add_vline(x=0, line_color="#2d3548", line_width=1)
        fig_s.update_layout(
            height=max(150, len(sym)*40),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=0, b=10, l=0, r=40),
            xaxis=dict(showgrid=False, color="#8892a4", zeroline=False),
            yaxis=dict(showgrid=False, color="#8892a4"),
        )
        st.plotly_chart(fig_s, use_container_width=True, config={"displayModeBar": False})

# ── Footer ────────────────────────────────────────────────────
st.markdown(f"""
<div style="text-align:center; color:#3d4558; font-size:11px; margin-top:32px;">
  TradeX-Pro v2.0 • Hər {REFRESH}s yenilənir • Mode: PAPER
</div>
""", unsafe_allow_html=True)

time.sleep(REFRESH)
st.rerun()
