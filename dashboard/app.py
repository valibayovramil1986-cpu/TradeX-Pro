"""
TradeX-Pro — Futuristik Monitoring Dashboard v4
Neon/cyber tema: glassmorphism, glow effektləri, Orbitron tipoqrafiyası
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
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Rəng palitri ───────────────────────────────────────────────
CYAN    = "#00e5ff"
GREEN   = "#00ffa3"
RED     = "#ff2e6a"
AMBER   = "#ffb830"
MUTED   = "#6b7a99"
GRIDCLR = "rgba(0,229,255,0.07)"

# ── CSS — Futuristik tema ──────────────────────────────────────
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;900&family=Rajdhani:wght@400;500;600;700&display=swap');

  .stApp {
    background:
      radial-gradient(ellipse 80% 50% at 50% -10%, rgba(0,229,255,0.09), transparent),
      radial-gradient(ellipse 60% 40% at 90% 110%, rgba(157,78,255,0.08), transparent),
      #05070f;
    font-family: 'Rajdhani', sans-serif;
  }
  /* İncə cyber-grid fon xətti */
  .stApp::before {
    content:""; position:fixed; inset:0; pointer-events:none; z-index:0;
    background-image:
      linear-gradient(rgba(0,229,255,0.025) 1px, transparent 1px),
      linear-gradient(90deg, rgba(0,229,255,0.025) 1px, transparent 1px);
    background-size: 44px 44px;
  }

  .hero-title {
    font-family:'Orbitron',sans-serif; font-weight:900; font-size:26px;
    background: linear-gradient(90deg, #00e5ff 0%, #9d4eff 60%, #ff2e88 100%);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    letter-spacing: 2px;
  }
  .hero-sub { color:#6b7a99; font-size:14px; margin-top:4px; letter-spacing:1px; }

  .kpi-card {
    position:relative;
    background: linear-gradient(160deg, rgba(13,20,38,0.85), rgba(9,13,26,0.9));
    border: 1px solid rgba(0,229,255,0.18);
    border-radius: 14px;
    padding: 18px 20px;
    text-align: center;
    height: 118px;
    display:flex; flex-direction:column; justify-content:center;
    backdrop-filter: blur(8px);
    box-shadow: 0 0 24px rgba(0,229,255,0.05), inset 0 1px 0 rgba(255,255,255,0.04);
    transition: border-color .25s, box-shadow .25s, transform .25s;
    overflow:hidden;
  }
  .kpi-card:hover {
    border-color: rgba(0,229,255,0.55);
    box-shadow: 0 0 32px rgba(0,229,255,0.18);
    transform: translateY(-2px);
  }
  /* Künc aksenti */
  .kpi-card::before {
    content:""; position:absolute; top:0; left:0; width:34px; height:34px;
    border-top:2px solid rgba(0,229,255,0.6); border-left:2px solid rgba(0,229,255,0.6);
    border-top-left-radius:14px;
  }
  .kpi-card::after {
    content:""; position:absolute; bottom:0; right:0; width:34px; height:34px;
    border-bottom:2px solid rgba(157,78,255,0.5); border-right:2px solid rgba(157,78,255,0.5);
    border-bottom-right-radius:14px;
  }
  .kpi-label {
    color:#6b7a99; font-size:11px; font-weight:600; letter-spacing:2.5px;
    text-transform:uppercase; margin-bottom:7px; font-family:'Rajdhani',sans-serif;
  }
  .kpi-value {
    color:#eaf6ff; font-size:25px; font-weight:700; line-height:1.15;
    font-family:'Orbitron',sans-serif;
    text-shadow: 0 0 14px rgba(0,229,255,0.35);
  }
  .kpi-sub-pos { color:#00ffa3; font-size:13px; margin-top:5px; font-weight:600; text-shadow:0 0 10px rgba(0,255,163,0.4); }
  .kpi-sub-neg { color:#ff2e6a; font-size:13px; margin-top:5px; font-weight:600; text-shadow:0 0 10px rgba(255,46,106,0.4); }
  .kpi-sub-neu { color:#6b7a99; font-size:13px; margin-top:5px; }

  .section-title {
    color:#bfe9ff; font-size:14px; font-weight:700; letter-spacing:2.5px;
    text-transform:uppercase; font-family:'Orbitron',sans-serif;
    margin:22px 0 12px 0; padding-bottom:8px; position:relative;
  }
  .section-title::after {
    content:""; position:absolute; left:0; bottom:0; height:2px; width:100%;
    background: linear-gradient(90deg, rgba(0,229,255,0.7), rgba(157,78,255,0.35), transparent 70%);
    box-shadow: 0 0 10px rgba(0,229,255,0.5);
  }

  .pos-card {
    background: linear-gradient(160deg, rgba(13,20,38,0.85), rgba(9,13,26,0.9));
    border: 1px solid rgba(0,229,255,0.14);
    border-left: 3px solid rgba(0,229,255,0.7);
    border-radius: 12px;
    padding: 14px 16px; margin-bottom: 10px;
    backdrop-filter: blur(6px);
    box-shadow: 0 0 18px rgba(0,229,255,0.05);
    transition: border-color .25s, box-shadow .25s;
  }
  .pos-card:hover { border-color: rgba(0,229,255,0.45); box-shadow: 0 0 26px rgba(0,229,255,0.14); }

  .live-dot { display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:7px; animation:pulse 1.6s infinite; }
  .dot-green { background:#00ffa3; box-shadow: 0 0 10px #00ffa3; }
  .dot-red   { background:#ff2e6a; box-shadow: 0 0 10px #ff2e6a; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.25} }

  /* Streamlit elementləri temaya uyğunlaşdır */
  div[data-testid="stMetric"] {
    background: linear-gradient(160deg, rgba(13,20,38,0.7), rgba(9,13,26,0.8));
    border: 1px solid rgba(0,229,255,0.12); border-radius: 10px;
    padding: 10px 14px;
  }
  div[data-testid="stMetric"] label { color:#6b7a99 !important; letter-spacing:1px; }
  div[data-testid="stMetric"] div { color:#eaf6ff !important; font-family:'Orbitron',sans-serif; }
  .stDataFrame { border:1px solid rgba(0,229,255,0.15); border-radius:10px; }
  .stButton>button {
    background: linear-gradient(90deg, rgba(0,229,255,0.12), rgba(157,78,255,0.12));
    color:#00e5ff; border:1px solid rgba(0,229,255,0.4); border-radius:8px;
    font-family:'Orbitron',sans-serif; font-size:12px; letter-spacing:1px;
    transition: all .25s;
  }
  .stButton>button:hover {
    border-color:#00e5ff; box-shadow:0 0 16px rgba(0,229,255,0.35); color:#eaf6ff;
  }
  .stAlert { border:1px solid rgba(0,229,255,0.2); border-radius:10px; }
</style>
""", unsafe_allow_html=True)

DATABASE_URL = os.getenv("DATABASE_URL", "")
REFRESH_SEC  = 30   # 30 saniyədə bir yenilə

# ── DB ───────────────────────────────────────────────────────
@st.cache_resource
def get_engine():
    """Engine bir dəfə yaradılır — hər cache miss-də yenidən qurulmur."""
    url = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://")
    return create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=0)


@st.cache_data(ttl=25)
def load_all():
    """Hər 25 saniyədə bir DB-dən təzə data çəkir."""
    eng = get_engine()

    def q(sql):
        try:
            with eng.connect() as c:
                return pd.read_sql(text(sql), c)
        except Exception as e:
            st.error(f"DB xəta: {e}")
            return pd.DataFrame()

    result = {
        "trades": q("SELECT * FROM trades WHERE pnl_usd IS NOT NULL ORDER BY close_time DESC"),
        "opens":  q("SELECT * FROM open_positions ORDER BY open_time DESC"),
        "bal":    q("SELECT balance, initial_balance FROM balance_state WHERE id=1"),
        "risk":   q("SELECT trading_halted, consecutive_losses, today_pnl_usd FROM risk_state WHERE id=1"),
        "memory": q("SELECT symbol, trades, wins, losses, total_pnl FROM coin_memory ORDER BY trades DESC LIMIT 15")
                  if q("SELECT to_regclass('coin_memory')").iloc[0,0] is not None
                  else pd.DataFrame(),
    }
    return result

# ── Məlumat yüklə ────────────────────────────────────────────
data     = load_all()
trades   = data["trades"]
opens    = data["opens"]
bal_row  = data["bal"]
risk_row = data["risk"]
memory   = data.get("memory", pd.DataFrame())

balance  = float(bal_row["balance"].iloc[0])        if not bal_row.empty  else 1000.0
initial  = float(bal_row["initial_balance"].iloc[0]) if not bal_row.empty  else 1000.0
pnl_usd  = balance - initial
pnl_pct  = pnl_usd / initial * 100 if initial else 0

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

# Trading mode — env-dən oxu (dashboard containerində də var)
mode_raw   = os.getenv("TRADING_MODE", "paper").upper()
is_live    = mode_raw == "LIVE"
mode_label = "🔴 LIVE" if is_live else "📋 PAPER"
now_str    = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
status_dot = "dot-red" if is_live else "dot-green"
status_lbl = "CANLI TİCARƏT" if is_live else "TEST REJİMİ"

# ── Header ────────────────────────────────────────────────────
hcol1, hcol2 = st.columns([5, 1])
with hcol1:
    st.markdown(f"""
    <div style="margin-bottom:18px;">
      <div class="hero-title">⚡ TRADEX-PRO</div>
      <div class="hero-sub">
        <span class="live-dot {status_dot}"></span>{status_lbl} &nbsp;·&nbsp;
        {mode_label} &nbsp;·&nbsp; MULTI-AGENT AI &nbsp;·&nbsp; {now_str}
      </div>
    </div>
    """, unsafe_allow_html=True)
with hcol2:
    if st.button("⟳ YENİLƏ", use_container_width=True):
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
kpi(c1,"Balans", f"${balance:,.2f}",
    f"{'▲' if pnl_usd>=0 else '▼'} ${abs(pnl_usd):.2f}", "pos" if pnl_usd>=0 else "neg")
kpi(c2,"Ümumi P&L", f"{'+' if pnl_pct>=0 else ''}{pnl_pct:.2f}%",
    f"${pnl_usd:+.2f}", "pos" if pnl_usd>=0 else "neg")
kpi(c3,"Bu gün P&L", f"${today_pnl:+.2f}",
    "Gündəlik limit: -5%", "pos" if today_pnl>=0 else "neg")
kpi(c4,"Win Rate", f"{win_rate:.1f}%",
    f"{len(wins)}W / {len(losses)}L", "pos" if win_rate>=55 else "neg")
kpi(c5,"Profit Factor", f"{min(pf,9.9):.2f}" if pf else "—",
    "Hədəf ≥ 1.5", "pos" if pf>=1.5 else "neg")
kpi(c6,"Ticarət",  str(total),
    f"Açıq: {len(opens)} · Ardıcıl itki: {consec}",
    "neg" if consec>=3 else "neu")

st.markdown("<div style='margin:14px 0;'></div>", unsafe_allow_html=True)

# Risk xəbərdarlığı
if halted:
    st.error("⛔ Ticarət DAYANDIRILIB — risk limiti keçildi. Telegram-da `/resume` yaz.")
elif consec >= 3:
    st.warning(f"⚠️ {consec} ardıcıl itki — risk azaldılıb (50%)")

# ── Əsas layout ──────────────────────────────────────────────
left, right = st.columns([3, 2], gap="large")

with left:
    # P&L qrafiki
    st.markdown('<div class="section-title">Kumulyativ P&L</div>', unsafe_allow_html=True)
    if not trades.empty:
        st_t = trades.sort_values("close_time")
        cum  = st_t["pnl_usd"].cumsum().values
        xs   = list(range(1, len(cum)+1))
        clr  = GREEN if cum[-1]>=0 else RED
        fillc = "rgba(0,255,163,0.10)" if cum[-1]>=0 else "rgba(255,46,106,0.10)"
        fig  = go.Figure()
        fig.add_trace(go.Scatter(
            x=xs, y=cum.tolist(), mode="lines+markers",
            fill="tozeroy", fillcolor=fillc,
            line=dict(color=clr, width=2.5, shape="spline"),
            marker=dict(size=5, color=clr,
                        line=dict(color="rgba(255,255,255,0.4)", width=1)),
            hovertemplate="Ticarət %{x}<br>P&L: $%{y:.2f}<extra></extra>",
        ))
        fig.add_hline(y=0, line_dash="dot", line_color="rgba(0,229,255,0.3)", line_width=1)
        fig.update_layout(
            height=250, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=5,b=5,l=0,r=0),
            font=dict(family="Rajdhani"),
            xaxis=dict(showgrid=False, color=MUTED, title="Ticarət №"),
            yaxis=dict(showgrid=True, gridcolor=GRIDCLR, color=MUTED, title="P&L ($)"),
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar":False})
    else:
        st.info("Hələ ticarət yoxdur — bot işləyir, siqnal gözlənilir.")

    # Statistika cədvəli
    st.markdown('<div class="section-title">Ətraflı Statistika</div>', unsafe_allow_html=True)
    s1,s2,s3,s4 = st.columns(4)
    s1.metric("Orta Qazanc",  f"${avg_win:.2f}"  if avg_win  else "—")
    s2.metric("Orta Zərər",   f"${avg_loss:.2f}" if avg_loss else "—")
    s3.metric("Ən Yaxşı",
              f"${trades['pnl_usd'].max():.2f}"  if not trades.empty else "—")
    s4.metric("Ən Pis",
              f"${trades['pnl_usd'].min():.2f}"  if not trades.empty else "—")

    # Son ticarətlər
    st.markdown('<div class="section-title">Son Ticarətlər</div>', unsafe_allow_html=True)
    if not trades.empty:
        disp = trades.head(20).copy()
        disp["Vaxt"]      = pd.to_datetime(disp["close_time"]).dt.strftime("%d.%m %H:%M")
        disp["İstiqamət"] = disp["direction"].map({"LONG":"🟢 LONG","SHORT":"🔴 SHORT"})
        disp["Giriş"]     = disp["entry_price"].apply(lambda x: f"{x:.4f}")
        disp["Çıxış"]     = disp["exit_price"].apply(lambda x:  f"{x:.4f}")
        disp["P&L"]       = disp["pnl_usd"].apply(lambda x: f"+${x:.2f}" if x>0 else f"-${abs(x):.2f}")
        disp["Bal"]       = disp["signal_score"].apply(lambda x: f"{x:.0f}" if x else "—")
        disp["Conf"]  = disp["confidence_score"].apply(lambda x: f"{x:.0f}%") \
                        if "confidence_score" in disp.columns else "—"
        disp["Tier"]  = disp["position_tier"].str.upper() \
                        if "position_tier" in disp.columns else "—"
        disp["Səbəb"] = disp["exit_reason"].fillna("—")
        show_cols = ["Vaxt","symbol","İstiqamət","Giriş","Çıxış","P&L","Bal","Conf","Tier","Səbəb"]
        show_hdrs = ["Vaxt","Simvol","İstiqamət","Giriş","Çıxış","P&L","Bal","Conf","Tier","Çıxış Səbəbi"]
        show = disp[[c for c in show_cols if c in disp.columns]].copy()
        show.columns = show_hdrs[:len(show.columns)]
        st.dataframe(show, use_container_width=True, hide_index=True)
    else:
        st.info("Ticarət yoxdur.")

with right:
    # Açıq mövqelər
    st.markdown(f'<div class="section-title">Açıq Mövqelər ({len(opens)})</div>',
                unsafe_allow_html=True)
    if not opens.empty:
        for _, pos in opens.iterrows():
            direction  = pos.get("direction","")
            symbol     = pos.get("symbol","")
            entry      = float(pos.get("entry_price",0))
            sl         = float(pos.get("stop_loss",0))
            tp1        = float(pos.get("tp1",0))
            tp2        = float(pos.get("tp2",0))
            usd_val    = float(pos.get("usd_value",0))
            score      = float(pos.get("signal_score",0))
            open_t     = str(pos.get("open_time",""))[:16]
            confidence = float(pos.get("confidence_score",0)) if "confidence_score" in pos.index else 0.0
            tier       = str(pos.get("position_tier","—"))    if "position_tier" in pos.index else "—"
            regime     = str(pos.get("market_regime","—"))    if "market_regime" in pos.index else "—"
            emoji      = "🟢" if direction=="LONG" else "🔴"
            side_clr   = GREEN if direction=="LONG" else RED
            tier_color = {"aggressive":AMBER,"normal":GREEN,"small":MUTED,"watchlist":"#5b6478"}.get(tier,MUTED)
            conf_color = GREEN if confidence>=75 else (AMBER if confidence>=60 else RED)
            st.markdown(f"""
            <div class="pos-card" style="border-left-color:{side_clr};">
              <div style="display:flex;justify-content:space-between;margin-bottom:8px;">
                <span style="color:#eaf6ff;font-weight:700;font-size:15px;font-family:'Orbitron',sans-serif;">{emoji} {symbol}</span>
                <span style="color:#6b7a99;font-size:11px;">{open_t} UTC</span>
              </div>
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:5px;font-size:13px;color:#6b7a99;">
                <div>Giriş: <span style="color:#bfe9ff;">{entry:.4f}</span></div>
                <div>Ölçü: <span style="color:#bfe9ff;">${usd_val:.0f}</span></div>
                <div>SL: <span style="color:{RED};">{sl:.4f}</span></div>
                <div>TP1: <span style="color:{GREEN};">{tp1:.4f}</span></div>
                <div>TP2: <span style="color:{GREEN};">{tp2:.4f}</span></div>
                <div>Bal: <span style="color:#bfe9ff;">{score:.0f}/100</span></div>
                <div>Konfidans: <span style="color:{conf_color};font-weight:600;">{confidence:.0f}%</span></div>
                <div>Tier: <span style="color:{tier_color};font-weight:600;">{tier.upper()}</span></div>
                <div style="grid-column:1/-1;">Rejim: <span style="color:#bfe9ff;">{regime.replace("_"," ").title()}</span></div>
              </div>
            </div>""", unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="pos-card" style="text-align:center;color:#6b7a99;padding:26px;border-left-color:rgba(0,229,255,0.3);">
          Açıq mövqe yoxdur — növbəti skan gözlənilir
        </div>""", unsafe_allow_html=True)

    # Win/Loss donut
    if not trades.empty:
        st.markdown('<div class="section-title">Win / Loss</div>', unsafe_allow_html=True)
        fig_d = go.Figure(go.Pie(
            labels=["Qazanc","İtki"],
            values=[max(len(wins),0), max(len(losses),0)],
            hole=0.62,
            marker=dict(colors=[GREEN, RED],
                        line=dict(color="#05070f", width=3)),
            textinfo="percent+value", textfont_size=12,
        ))
        fig_d.update_layout(
            height=210, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=0,b=0,l=0,r=0),
            font=dict(family="Rajdhani"),
            legend=dict(font_color=MUTED, bgcolor="rgba(0,0,0,0)"),
            annotations=[dict(text=f"{win_rate:.0f}%<br>WIN",
                              x=0.5,y=0.5,font_size=17,font_color="#eaf6ff",
                              font_family="Orbitron",showarrow=False)],
        )
        st.plotly_chart(fig_d, use_container_width=True, config={"displayModeBar":False})

        # Simvol P&L
        st.markdown('<div class="section-title">Simvol üzrə P&L</div>', unsafe_allow_html=True)
        sym = trades.groupby("symbol")["pnl_usd"].sum().reset_index()
        sym.columns = ["symbol","pnl"]
        sym = sym.sort_values("pnl")
        colors = [GREEN if v>=0 else RED for v in sym["pnl"]]
        fig_s = go.Figure(go.Bar(
            x=sym["pnl"], y=sym["symbol"], orientation="h",
            marker_color=colors,
            text=sym["pnl"].apply(lambda x: f"+${x:.2f}" if x>=0 else f"-${abs(x):.2f}"),
            textposition="outside", textfont_color=MUTED,
            hovertemplate="%{y}: $%{x:.2f}<extra></extra>",
        ))
        fig_s.add_vline(x=0, line_color="rgba(0,229,255,0.3)", line_width=1)
        fig_s.update_layout(
            height=max(160, len(sym)*35),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=0,b=5,l=0,r=40),
            font=dict(family="Rajdhani"),
            xaxis=dict(showgrid=False, color=MUTED, zeroline=False),
            yaxis=dict(showgrid=False, color=MUTED),
        )
        st.plotly_chart(fig_s, use_container_width=True, config={"displayModeBar":False})

# ── AI Memory (Coin Memory) ───────────────────────────────────
st.markdown('<div class="section-title">🧠 AI Yaddaş — Simvol Reputasiyası</div>', unsafe_allow_html=True)
if memory is not None and not memory.empty:
    mem = memory.copy()
    mem["Win Rate"] = mem.apply(
        lambda r: f"{r['wins']/r['trades']*100:.1f}%" if r['trades'] > 0 else "—", axis=1
    )
    mem["Total P&L"] = mem["total_pnl"].apply(lambda x: f"+${x:.2f}" if x>=0 else f"-${abs(x):.2f}")
    mem["Ticarət"]   = mem["trades"].astype(int)
    mem["Qazanc"]    = mem["wins"].astype(int)
    mem["İtki"]      = mem["losses"].astype(int)
    show_mem = mem[["symbol","Ticarət","Qazanc","İtki","Win Rate","Total P&L"]].copy()
    show_mem.columns = ["Simvol","Ticarət","Qazanc","İtki","Win Rate","Ümumi P&L"]
    st.dataframe(show_mem, use_container_width=True, hide_index=True)

    # Mini bar chart — win rate per coin
    mem["wr_num"] = mem.apply(lambda r: r["wins"]/r["trades"]*100 if r["trades"]>0 else 0, axis=1)
    fig_mem = go.Figure(go.Bar(
        x=mem["symbol"], y=mem["wr_num"],
        marker_color=[GREEN if v>=55 else (AMBER if v>=45 else RED) for v in mem["wr_num"]],
        text=mem["wr_num"].apply(lambda x: f"{x:.0f}%"),
        textposition="outside", textfont_color=MUTED,
        hovertemplate="%{x}: %{y:.1f}% win rate<extra></extra>",
    ))
    fig_mem.add_hline(y=55, line_dash="dot", line_color=GREEN, line_width=1,
                      annotation_text="55% hədəf", annotation_font_color=GREEN, annotation_font_size=10)
    fig_mem.update_layout(
        height=200, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=5,b=5,l=0,r=0),
        font=dict(family="Rajdhani"),
        xaxis=dict(showgrid=False, color=MUTED),
        yaxis=dict(showgrid=True, gridcolor=GRIDCLR, color=MUTED, title="Win Rate %", range=[0,105]),
    )
    st.plotly_chart(fig_mem, use_container_width=True, config={"displayModeBar":False})
else:
    st.info("AI yaddaş hələ boşdur — ticarətlər başladıqca simvol statistikası burada görünəcək.")

# ── Footer ────────────────────────────────────────────────────
st.markdown(f"""
<div style="text-align:center;color:#3d4a66;font-size:11px;margin-top:26px;
            font-family:'Orbitron',sans-serif;letter-spacing:2px;">
  TRADEX-PRO v4 &nbsp;·&nbsp; {mode_label} &nbsp;·&nbsp;
  25 SİMVOL &nbsp;·&nbsp; 4TF SKAN &nbsp;·&nbsp; MULTI-AGENT AI &nbsp;·&nbsp;
  HƏR {REFRESH_SEC}s YENİLƏNİR
</div>""", unsafe_allow_html=True)

# Auto-refresh: keş TTL (25s) + yenilənmə dövrü (30s)
time.sleep(REFRESH_SEC)
load_all.clear()   # keşi zorla sil — təzə data gəlsin
st.rerun()
