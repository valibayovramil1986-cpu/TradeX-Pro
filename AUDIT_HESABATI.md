# TradeX-Pro — Dərin Kod Auditi

**Tarix:** 2026-07-10 | **Əhatə:** ~6,800 sətir Python (venv istisna), Docker/deploy konfiqurasiyası, git tarixçəsi

---

## Xülasə

TradeX-Pro yaxşı strukturlaşdırılmış layihədir: modul bölgüsü (core/ai/memory/tgbot) məntiqlidir, risk idarəetməsi düşünülüb, paper→live faza sistemi düzgün yanaşmadır. **Amma layihə hazırkı vəziyyətdə LIVE rejimə buraxıla bilməz** — live icra yolunda mövqe bağlanması birjaya heç vaxt göndərilmir, bu real pul itkisi ilə nəticələnə bilər. Aşağıda tapıntılar prioritet üzrə sıralanıb.

---

## 🔴 KRİTİK (dərhal düzəldilməli)

### K1. Live rejimdə SL/TP bağlanması birjaya göndərilmir
`core/order_executor.py` — `check_sl_tp()` və `close_all_positions()` yalnız `close_position()` çağırır, bu isə ancaq daxili DB/balans yeniləyir. `close_live_position()` metodu **kodun heç bir yerində çağırılmır**.

**Nəticə:** Live rejimdə bot "SL vuruldu, mövqe bağlandı" hesab edir, amma Binance-də real mövqe açıq qalır. Qiymət düşməyə davam edərsə itki limitsizdir. `/close_all` (emergency) də eyni problemi daşıyır.

**Düzəliş:** `close_position()`-a `mode=="live"` yoxlaması əlavə edin və `close_live_position()`-u çağırın; order icra təsdiqini gözləyin, uğursuzluqda retry + Telegram alert.

### K2. Docker image-ə real API açarları kopyalanır
`.dockerignore` faylı **yoxdur**, `Dockerfile`-da `COPY . .` var. `config/.env`-də real OpenAI, Telegram, Binance açarları saxlanılır → hamısı image layer-inə düşür. Image registry-yə push olunsa açarlar sızır. Əlavə olaraq `.git`, `logs/`, `TradeX-Pro/venv` (14MB) də image-ə kopyalanır.

**Düzəliş:** `.dockerignore` yaradın (`.env`, `*.env`, `.git`, `venv/`, `logs/`, `*.db`, `TradeX-Pro/`). Açarlar yalnız `docker-compose` environment ilə ötürülsün (artıq belədir — sadəcə COPY-dən qoruyun).

### K3. PostgreSQL və Dashboard internetə açıqdır
`docker-compose.yml`: `ports: 5432:5432` və `8501:8501`. `deploy.sh`: `ufw allow 5432`. Üstəlik **Docker ufw qaydalarını bypass edir** (iptables-ə birbaşa yazır) — yəni ufw bağlasanız belə portlar açıq qalır. Streamlit dashboard-da heç bir autentifikasiya yoxdur — ticarət məlumatlarınız hamıya görünür; Postgres brute-force hədəfidir.

**Düzəliş:** `ports`-u `127.0.0.1:5432:5432` və `127.0.0.1:8501:8501` edin. DataGrip/dashboard üçün SSH tunel istifadə edin (`ssh -L 5432:localhost:5432 root@server`).

### K4. `.gitignore`-da həll olunmamış merge konflikti
Faylda `<<<<<<< HEAD`, `=======`, `>>>>>>> 129583e...` markerləri qalıb. Hazırda pattern-lər təsadüfən işləyir (hər sətir ayrıca pattern sayılır), amma bu, kobud repo pozuntusudur və gələcək dəyişikliklərdə `.env`-in commit olunma riskini yaradır.

**Düzəliş:** Konflikti həll edin — iki bölməni birləşdirib markerləri silin.

---

## 🟠 YÜKSƏK (live-dan əvvəl mütləq)

### Y1. Qismən çıxışların P&L-i risk sayğacına düşmür + son hissə "trade nəticəsi" sayılır
`close_position()`-da `record_trade_result()` yalnız tam bağlanışda çağırılır və **yalnız son hissənin** P&L-i ilə. Ssenari: TP1+TP2 vurulub (80% qazancla bağlanıb), qalan 20% trailing-də cüzi minusla çıxıb → risk sistemi bunu **itki** kimi qeydə alır → `consecutive_losses` yalandan artır → circuit breaker səhv işə düşür. Əksi də mümkündür: gün ərzində TP1/TP2 qazancları `today_pnl`-ə yazılmır → drawdown hesabı təhrif olunur.

**Düzəliş:** Hər qismən çıxışda P&L-i `today/week_pnl`-ə əlavə edin; win/loss qərarını isə mövqenin **məcmu** P&L-i üzərində, tam bağlananda verin.

### Y2. Gündəlik reset həftəlik drawdown halt-ını da ləğv edir
`reset_daily_stats()` hər gecə `trading_halted`-i şərtsiz `False` edir. Həftəlik drawdown limiti (10%) keçilib bot dayandırılıbsa, səhəri gün avtomatik yenidən ticarətə başlayır — həftəlik limit praktikada 1 günlük limitə çevrilir.

**Düzəliş:** Halt səbəbini (`daily`/`weekly`/`consec_loss`) saxlayın; gündəlik reset yalnız daily-mənşəli halt-ı açsın.

### Y3. Live giriş qiyməti və birja SL orderi sinxron deyil
`_place_live_order()`: (a) market order göndərilir amma **real fill qiyməti** oxunmur — mövqe `signal.entry_zone_high` ilə qeydə alınır, slippage görünməz qalır; (b) TP1-dən sonra software SL breakeven-ə çəkilir, amma **birjadakı stop order köhnə səviyyədə qalır** → hər ikisi işləyə bilər (ikiqat satış); (c) qismən çıxışlarda birja SL orderinin miqdarı yenilənmir; (d) Spot rejimdə `stop_market` order tipi Binance spot-da yoxdur — SL order həmişə uğursuz olur (yalnız software SL qalır, bot offline olsa müdafiəsizsiniz).

**Düzəliş:** `order["average"]`-dən fill qiymətini götürün; SL dəyişəndə birjadakı orderi cancel+replace edin; spot üçün `STOP_LOSS_LIMIT` istifadə edin.

### Y4. Sinxron çağırışlar event loop-u bloklayır
`get_current_prices()` 25 simvolu **ardıcıl** `fetch_ticker` ilə çəkir (rate limit ilə ~25–50 saniyə) və sync işləyir; GPT `_call()` də sync-dir. Bu müddətdə Telegram bot donur, scheduler jobları gecikir.

**Düzəliş:** `fetch_tickers()` (bir çağırışda hamısı!) istifadə edin + `run_in_executor`/`asyncio.to_thread`; OpenAI üçün `AsyncOpenAI`.

### Y5. `/close_all` Telegram-dan heç vaxt işləmir
`_cmd_close_all` "təsdiq üçün /confirm_close yazın" deyir, amma `confirm_close` handler-i **qeydiyyatdan keçirilməyib**. Fövqəladə halda bütün mövqeləri bağlamaq mümkün deyil — ən kritik komanda ölü koddur.

**Düzəliş:** `CommandHandler("confirm_close", ...)` əlavə edin və `_on_close_all` callback-inə bağlayın (timeout-lu təsdiq state-i ilə).

### Y6. Faza 3-ə keçid crash verir
`main.py _promote_phase()`: Faza 3-də `virtual_capital=None` → `f"${new_capital:,.0f}"` `TypeError` atır. Məhz live-a keçid anında bot xəta verir.

---

## 🟡 ORTA

- **O1. Testlər yoxdur.** Sıfır unit/integration test. Ən azı `risk_manager`, `order_executor.check_sl_tp` (partial exit ssenariləri!) və `signal_engine` üçün pytest yazılmalıdır — Y1 kimi bugları məhz testlər tutur.
- **O2. Backtest yoxdur.** Strategiya yalnız canlı paper-lə yoxlanır (yavaş öyrənmə dövrü). `vectorbt`/`backtesting.py` requirements-də şərhə alınıb — aktivləşdirib tarixi data ilə strategiyanı validasiya edin.
- **O3. `TradeX-Pro/` qalıq qovluğu:** boş .py fayllar + 14MB venv + köhnə `.env`. Silin.
- **O4. `OPENAI_DAILY_TOKEN_LIMIT` heç yerdə enforce olunmur** — konfiqurasiya var, yoxlama yoxdur. GPT xərci nəzarətsizdir (hər skanda 25-ə qədər siqnal × enrichment çağırışı mümkündür).
- **O5. `initial_balance` uyğunsuzluğu:** balans DB-dən yüklənir, `initial_balance` isə hər restart-da Settings-dən götürülür → `total_pnl`/drawdown % səhv hesablana bilər. `balance_state.initial_balance` sütunu var amma oxunmur.
- **O6. Simvol siyahısı köhnəlib:** `MATIC/USDT` Binance-də delist olunub (POL-a keçib) — hər skanda boş yerə xəta verir.
- **O7. Ölü konfiqurasiya:** `SCAN_INTERVAL_HOURS=3` və `SCAN_HOURS_UTC` heç yerdə istifadə olunmur — scheduler hardcoded 1 saatdır. `exchanges/` qovluğu boşdur.
- **O8. Docker:** healthcheck faydasızdır (`sys.exit(0)` həmişə keçir — məsələn DB bağlantısını yoxlasın); konteyner root ilə işləyir (`USER` direktivi əlavə edin); deploy GitHub Actions-da `root` SSH ilə gedir (ayrıca deploy useri yaradın).
- **O9. `trade_id = uuid4()[:8]`** — kolliziya ehtimalı az amma mümkündür; tam UUID saxlayın.
- **O10. Korrelyasiya filtri yalnız BTC/ETH/BNB-dir** — SOL, AVAX, NEAR və s. altcoinlər arasında korrelyasiya real bazarda 0.8+ olur; 3 alt mövqe eyni anda açılsa faktiki tək bet-dir. Dinamik korrelyasiya matrisi (30 günlük returns) daha düzgündür.

---

## Güclü tərəflər

Risk qatı düşünülüb (position sizing, circuit breaker, dinamik risk, 20% mövqe tavanı); PostgreSQL persistence restart-a davamlılıq verir; Telegram autentifikasiyası (`chat_id` yoxlaması) düzgündür; secrets git-ə commit olunmayıb (tarixçə də təmizdir); GPT prompt-larında adjustment limitləri ağıllı qoyulub; MTF confluence + regime bias arxitekturası peşəkardır.

---

## Tövsiyə olunan iş sırası

1. **Bu gün:** K2 (.dockerignore), K3 (portları localhost-a bağla), K4 (.gitignore konflikti), O3 (qalıq qovluq)
2. **Bu həftə:** K1 (live close yolu), Y1–Y2 (risk sayğacı bugları), Y5 (confirm_close), Y6 (promote crash)
3. **Live-dan əvvəl:** Y3 (fill qiyməti + birja SL sinxronu), Y4 (async), O1 (testlər), O4 (token limiti)
4. **Sonra:** O2 (backtest), O10 (korrelyasiya matrisi), qalan orta səviyyəli maddələr

> Qeyd: Bu, texniki kod auditidir — ticarət strategiyasının gəlirliliyi barədə fikir bildirmir və maliyyə məsləhəti deyil.
