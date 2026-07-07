"""
TradeX-Pro — Modern Monitoring Dashboard v3
Faza sistemi silindi, 25 simvol, saatlıq skan, paper/live göstəricisi
"""

import os, time
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from sqlalchemy import create_engine, text
from datetime import datetime, timezone

# ── Səhifə konfiqurasiyası ─────────────────────────────────────
st.set_page_config(
    page_title="TradeX-Pro",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS ────────────────────────────────────────────────────────
st.markdown("""
<style>
  .stApp { background-color: #0e1117; }
  .kpi-card {
    background: linear-gradient(135deg, #1a1f2e, #252b3b);
    border: 1px solid #2d3548;
    border-radius: 16px;
    padding: 20px 24px;
    text-align: center;
    height: 110px;
    display: flex; flex-direction: column; justify-content: center;
  }
  .kpi-label { color:#8892a4; font-size:11px; font-weight:600; letter-spacing:1px; text-transform:uppercase; margin-bottom:6px; }
  .kpi-value { color:#ffffff; font-size:26px; font-weight:700; line-height:1.2; }
  .kpi-sub-pos { color:#00d4aa; font-size:12px; margin-top:4px; }
  .kpi-sub-neg { color:#ff4b6e; font-size:12px; margin-top:4px; }
  .kpi-sub-neu { color:#8892a4; font-size:12px; margin-top:4px; }
  .section-title {
    color:#c9d1e0; font-size:14px; font-weight:600; letter-spacing:0.5px;
    margin:20px 0 10px 0; padding-bottom:6px; border-bottom:1px solid #2d3548;
  }
  .pos-card {
    background:#1a1f2e; border:1px solid #2d3548; border-radius:12px;
    padding:14px 16px; margin-bottom:10px;
  }
  .live-dot { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:6px; animation:pulse 2s infinite; }
  .dot-green { background:#00d4aa; }
  .dot-red   { background:#ff4b6e; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
</style>
""", unsafe_allow_html=True)

DATABASE_URL = os.getenv("DATABASE_URL", "")
REFRESH_SEC  = 30   # 30 saniyədə bir yenilə

# ── DB — keş yoxdur, hər dəfə təzə bağlantı ─────────────────
def get_engine():
    url = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://")
    return create_engine(url, pool_pre_ping=True,
                         connect_args={"options": "-c statement_timeout=5000"})

# TTL=25s — hər rerun-da 25 saniyə keçibsə təzə data çəkir
@st.cache_data(ttl=25)
def load_all():
    eng = get_engine()
    def q(sql):
        try:
            with eng.connect() as c:
                # READ COMMITTED — stale read olmur
                c.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
                return pd.read_sql(text(sql), c)
        except Exception as e:
            return pd.DataFrame()

    return {
        "trades":   q("SELECT * FROM trades WHERE pnl_usd IS NOT NULL ORDER BY close_time DESC"),
        "opens":    q("SELECT * FROM open_positions ORDER BY open_time DESC"),
        "bal":      q("SELECT balance, initial_balance FROM balance_state WHERE id=1"),
        "risk":     q("SELECT trading_halted, consecutive_losses, today_pnl_usd FROM risk_state WHERE id=1"),
    }

# ── Məlumat yüklə ────────────────────────────────────────────
data     = load_all()
trades   = data["trades"]
opens    = data["opens"]
bal_row  = data["bal"]
risk_row = data["risk"]

balance  = float(bal_row["balance"].iloc[0])        if not bal_row.empty  else 1000.0
initial  = float(bal_row["initial_balance"].iloc[0]) if not bal_row.empty  else 1000.0
pnl_usd  = balance - initial
pnl_pct  = pnl_usd / initial * 100

halted   = bool(risk_row["trading_halted"].iloc[0])        if not risk_row.empty else False
consec   = int(risk_row["consecutive_losses"].iloc[0])     if not risk_row.empty else 0
today_pnl= float(risk_row["today_pnl_usd"].iloc[0])       if not risk_row.empty else 0.0

wins     = trades[trades["pnl_usd"] > 0] if not trades.empty else pd.DataFrame()
losses   = trades[trades["pnl_usd"] < 0] if not trades.empty else pd.DataFrame()
total    = len(trades)
win_rate = len(wins)/total*100 if total > 0 else 0
pf       = (wins["pnl_usd"].sum() / abs(losses["pnl_usd"].sum())
            if len(losses)>0 and losses["pnl_usd"].sum()!=0 else 0.0)
avg_win  = wins["pnl_usd"].mean()  if len(wins)>0  else 0.0
avg_loss = losses["pnl_usd"].mean() if len(losses)>0 else 0.0

# Trading mode — env-dən ox (dashboard containerinda da var)
mode_raw   = os.getenv("TRADING_MODE", "paper").upper()
is_live    = mode_raw == "LIVE"
mode_label = "🔴 LIVE" if is_live else "📋 PAPER"
now_str    = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
status_dot = "dot-red" if is_live else "dot-green"
status_lbl = "Canlı Ticarət" if is_live else "Test Rejimi"

# ── Header ────────────────────────────────────────────────────
hcol1, hcol2 = st.columns([5, 1])
with hcol1:
    st.markdown(f"""
    <div style="margin-bottom:16px;">
      <div style="color:#fff; font-size:22px; font-weight:700;">🤖 TradeX-Pro Dashboard</div>
      <div style="color:#8892a4; font-size:13px; margin-top:4px;">
        <span class="live-dot {status_dot}"></span>{status_lbl} &nbsp;|&nbsp;
        {mode_label} &nbsp;|&nbsp; Son yeniləmə: {now_str}
      </div>
    </div>
    """, unsafe_allow_html=True)
with hcol2:
    if st.button("🔄 Yenilə", use_container_width=True):
        load_all.clear()
        st.rerun()

# ── KPI Kartları ──────────────────────────────────────────────
def kpi(col, label, value, sub=None, sub_type="neu"):
    sub_html = f'<div class="kpi-sub-{sub_type}">{sub}</div>' if sub else ""
    col.markdown(f"""
    <div class="kpi-card">
      <div class="kpi-label">{label}</div>
      <div class="kpi-value">{value}</div>
      {sub_html}
    </div>""", unsafe_allow_html=True)

c1,c2,c3,c4,c5,c6 = st.columns(6)
kpi(c1,"💰 Balans", f"${balance:,.2f}",
    f"{'▲' if pnl_usd>=0 else '▼'} ${abs(pnl_usd):.2f}", "pos" if pnl_usd>=0 else "neg")
kpi(c2,"📈 Ümumi P&L", f"{'+' if pnl_pct>=0 else ''}{pnl_pct:.2f}%",
    f"${pnl_usd:+.2f}", "pos" if pnl_usd>=0 else "neg")
kpi(c3,"🎯 Bu gün P&L", f"${today_pnl:+.2f}",
    "Gündəlik limit: -5%", "pos" if today_pnl>=0 else "neg")
kpi(c4,"✅ Win Rate", f"{win_rate:.1f}%",
    f"{len(wins)}W / {len(losses)}L", "pos" if win_rate>=55 else "neg")
kpi(c5,"⚖️ Profit Factor", f"{min(pf,9.9):.2f}" if pf else "—",
    "Hədəf ≥ 1.5", "pos" if pf>=1.5 else "neg")
kpi(c6,"📊 Ticarət",  str(total),
    f"Açıq: {len(opens)} | Ardıcıl itki: {consec}",
    "neg" if consec>=3 else "neu")

st.markdown("<div style='margin:12px 0;'></div>", unsafe_allow_html=True)

# Risk xəbərdarlığı
if halted:
    st.error("⛔ Ticarət DAYANDIRILIB — risk limiti keçildi. Telegram-da `/resume` yaz.")
elif consec >= 3:
    st.warning(f"⚠️ {consec} ardıcıl itki — risk azaldılıb (50%)")

# ── Əsas layout ──────────────────────────────────────────────
left, right = st.columns([3, 2], gap="large")

with left:
    # P&L qrafiki
    st.markdown('<div class="section-title">📈 Kumulyativ P&L</div>', unsafe_allow_html=True)
    if not trades.empty:
        st_t = trades.sort_values("close_time")
        cum  = st_t["pnl_usd"].cumsum().values
        xs   = list(range(1, len(cum)+1))
        clr  = "#00d4aa" if cum[-1]>=0 else "#ff4b6e"
        fig  = go.Figure()
        fig.add_trace(go.Scatter(
            x=xs, y=cum.tolist(), mode="lines+markers",
            fill="tozeroy", fillcolor=f"{'rgba(0,212,170,0.08)' if cum[-1]>=0 else 'rgba(255,75,110,0.08)'}",
            line=dict(color=clr, width=2.5), marker=dict(size=5, color=clr),
            hovertemplate="Ticarət %{x}<br>P&L: $%{y:.2f}<extra></extra>",
        ))
        fig.add_hline(y=0, line_dash="dot", line_color="#2d3548", line_width=1)
        fig.update_layout(
            height=250, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=5,b=5,l=0,r=0),
            xaxis=dict(showgrid=False, color="#8892a4", title="Ticarət №"),
            yaxis=dict(showgrid=True, gridcolor="#1e2435", color="#8892a4", title="P&L ($)"),
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar":False})
    else:
        st.info("Hələ ticarət yoxdur — bot işləyir, siqnal gözlənilir.")

    # Statistika cədvəli
    st.markdown('<div class="section-title">📊 Ətraflı Statistika</div>', unsafe_allow_html=True)
    s1,s2,s3,s4 = st.columns(4)
    s1.metric("Orta Qazanc",  f"${avg_win:.2f}"  if avg_win  else "—")
    s2.metric("Orta Zərər",   f"${avg_loss:.2f}" if avg_loss else "—")
    s3.metric("Ən Yaxşı",
              f"${trades['pnl_usd'].max():.2f}"  if not trades.empty else "—")
    s4.metric("Ən Pis",
              f"${trades['pnl_usd'].min():.2f}"  if not trades.empty else "—")

    # Son ticarətlər
    st.markdown('<div class="section-title">📋 Son Ticarətlər</div>', unsafe_allow_html=True)
    if not trades.empty:
        disp = trades.head(20).copy()
        disp["Vaxt"]      = pd.to_datetime(disp["close_time"]).dt.strftime("%d.%m %H:%M")
        disp["İstiqamət"] = disp["direction"].map({"LONG":"🟢 LONG","SHORT":"🔴 SHORT"})
        disp["Giriş"]     = disp["entry_price"].apply(lambda x: f"{x:.4f}")
        disp["Çıxış"]     = disp["exit_price"].apply(lambda x:  f"{x:.4f}")
        disp["P&L"]       = disp["pnl_usd"].apply(lambda x: f"+${x:.2f}" if x>0 else f"-${abs(x):.2f}")
        disp["Bal"]       = disp["signal_score"].apply(lambda x: f"{x:.0f}" if x else "—")
        disp["Səbəb"]     = disp["exit_reason"].fillna("—")
        show = disp[["Vaxt","symbol","İstiqamət","Giriş","Çıxış","P&L","Bal","Səbəb"]]
        show.columns = ["Vaxt","Simvol","İstiqamət","Giriş","Çıxış","P&L","Bal","Çıxış Səbəbi"]
        st.dataframe(show, use_container_width=True, hide_index=True)
    else:
        st.info("Ticarət yoxdur.")

with right:
    # Açıq mövqelər
    st.markdown(f'<div class="section-title">🔓 Açıq Mövqelər ({len(opens)})</div>',
                unsafe_allow_html=True)
    if not opens.empty:
        for _, pos in opens.iterrows():
            direction = pos.get("direction","")
            symbol    = pos.get("symbol","")
            entry     = float(pos.get("entry_price",0))
            sl        = float(pos.get("stop_loss",0))
            tp1       = float(pos.get("tp1",0))
            tp2       = float(pos.get("tp2",0))
            usd_val   = float(pos.get("usd_value",0))
            score     = float(pos.get("signal_score",0))
            open_t    = str(pos.get("open_time",""))[:16]
            emoji     = "🟢" if direction=="LONG" else "🔴"
            st.markdown(f"""
            <div class="pos-card">
              <div style="display:flex;justify-content:space-between;margin-bottom:8px;">
                <span style="color:#fff;font-weight:700;font-size:15px;">{emoji} {symbol}</span>
                <span style="color:#8892a4;font-size:11px;">{open_t} UTC</span>
              </div>
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:5px;font-size:12px;color:#8892a4;">
                <div>Giriş: <span style="color:#c9d1e0;">{entry:.4f}</span></div>
                <div>Ölçü: <span style="color:#c9d1e0;">${usd_val:.0f}</span></div>
                <div>SL: <span style="color:#ff4b6e;">{sl:.4f}</span></div>
                <div>TP1: <span style="color:#00d4aa;">{tp1:.4f}</span></div>
                <div>TP2: <span style="color:#00d4aa;">{tp2:.4f}</span></div>
                <div>Bal: <span style="color:#c9d1e0;">{score:.0f}/100</span></div>
              </div>
            </div>""", unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="pos-card" style="text-align:center;color:#8892a4;padding:24px;">
          Açıq mövqe yoxdur — növbəti skan gözlənilir
        </div>""", unsafe_allow_html=True)

    # Win/Loss donut
    if not trades.empty:
        st.markdown('<div class="section-title">🥧 Win / Loss</div>', unsafe_allow_html=True)
        fig_d = go.Figure(go.Pie(
            labels=["Qazanc","İtki"],
            values=[max(len(wins),0), max(len(losses),0)],
            hole=0.58,
            marker_colors=["#00d4aa","#ff4b6e"],
            textinfo="percent+value", textfont_size=12,
        ))
        fig_d.update_layout(
            height=210, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=0,b=0,l=0,r=0),
            legend=dict(font_color="#8892a4", bgcolor="rgba(0,0,0,0)"),
            annotations=[dict(text=f"{win_rate:.0f}%<br>Win",
                              x=0.5,y=0.5,font_size=16,font_color="#ffffff",showarrow=False)],
        )
        st.plotly_chart(fig_d, use_container_width=True, config={"displayModeBar":False})

        # Simvol P&L
        st.markdown('<div class="section-title">📊 Simvol üzrə P&L</div>', unsafe_allow_html=True)
        sym = trades.groupby("symbol")["pnl_usd"].sum().reset_index()
        sym.columns = ["symbol","pnl"]
        sym = sym.sort_values("pnl")
        colors = ["#00d4aa" if v>=0 else "#ff4b6e" for v in sym["pnl"]]
        fig_s = go.Figure(go.Bar(
            x=sym["pnl"], y=sym["symbol"], orientation="h",
            marker_color=colors,
            text=sym["pnl"].apply(lambda x: f"+${x:.2f}" if x>=0 else f"-${abs(x):.2f}"),
            textposition="outside", textfont_color="#8892a4",
            hovertemplate="%{y}: $%{x:.2f}<extra></extra>",
        ))
        fig_s.add_vline(x=0, line_color="#2d3548", line_width=1)
        fig_s.update_layout(
            height=max(160, len(sym)*35),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=0,b=5,l=0,r=40),
            xaxis=dict(showgrid=False, color="#8892a4", zeroline=False),
            yaxis=dict(showgrid=False, color="#8892a4"),
        )
        st.plotly_chart(fig_s, use_container_width=True, config={"displayModeBar":False})

# ── Footer ────────────────────────────────────────────────────
st.markdown(f"""
<div style="text-align:center;color:#3d4558;font-size:11px;margin-top:24px;">
  TradeX-Pro v2.0 &nbsp;|&nbsp; {mode_label} &nbsp;|&nbsp;
  25 simvol &nbsp;|&nbsp; Saatlıq skan &nbsp;|&nbsp;
  Hər {REFRESH_SEC}s yenilənir
</div>""", unsafe_allow_html=True)

# Auto-refresh: keş TTL (25s) + yenilənmə dövrü (30s)
time.sleep(REFRESH_SEC)
load_all.clear()   # keşi zorla sil — təzə data gəlsin
st.rerun()
