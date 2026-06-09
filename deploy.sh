#!/bin/bash
# ══════════════════════════════════════════════════
# TradeX-Pro — DigitalOcean ilk quraşdırma skripti
# DigitalOcean Droplet-də BİR DƏFƏ işlədin:
#   bash deploy.sh
# ══════════════════════════════════════════════════

set -e
echo "🚀 TradeX-Pro server quraşdırması başlayır..."

# ── 1. Sistem yenilənməsi ─────────────────────────
apt-get update && apt-get upgrade -y
apt-get install -y git curl ufw

# ── 2. Docker quraşdırması ───────────────────────
curl -fsSL https://get.docker.com | sh
systemctl enable docker
systemctl start docker

# ── 3. Firewall ──────────────────────────────────
ufw allow OpenSSH
ufw allow 5432/tcp   # DataGrip üçün PostgreSQL portu
ufw --force enable

# ── 4. Layihə klonlanması ────────────────────────
mkdir -p /opt/tradex_pro
cd /opt/tradex_pro

# GitHub repo URL-ni daxil edin
read -p "GitHub repo URL (məs. https://github.com/USERNAME/tradex_pro): " REPO_URL
git clone "$REPO_URL" .

# ── 5. .env faylı ────────────────────────────────
echo ""
echo "📝 .env faylı yaradılır..."
read -p "OPENAI_API_KEY: " OPENAI_KEY
read -p "TELEGRAM_BOT_TOKEN: " TG_TOKEN
read -p "TELEGRAM_CHAT_ID: " TG_CHAT
read -p "POSTGRES_PASSWORD (özünüz seçin, min 12 simvol): " PG_PASS

cat > .env << EOF
OPENAI_API_KEY=${OPENAI_KEY}
OPENAI_MODEL=gpt-4o
TELEGRAM_BOT_TOKEN=${TG_TOKEN}
TELEGRAM_CHAT_ID=${TG_CHAT}
POSTGRES_PASSWORD=${PG_PASS}
DATABASE_URL=postgresql://tradex:${PG_PASS}@postgres:5432/tradex_pro
TRADING_MODE=paper
INITIAL_CAPITAL=1000
MAX_RISK_PER_TRADE=0.02
MAX_OPEN_POSITIONS=3
SIGNAL_THRESHOLD=60
LOG_LEVEL=INFO
EOF

chmod 600 .env
echo "✅ .env yaradıldı (icazə: 600)"

# ── 6. Docker Compose ilə başlat ─────────────────
docker compose up -d --build

echo ""
echo "══════════════════════════════════════"
echo "✅ TradeX-Pro uğurla quraşdırıldı!"
echo "══════════════════════════════════════"
echo ""
echo "Faydalı əmrlər:"
echo "  docker compose logs -f tradex_bot   # Logları izlə"
echo "  docker compose ps                   # Konteyner vəziyyəti"
echo "  docker compose restart tradex_bot   # Botu yenidən başlat"
echo "  docker compose down                 # Dayandır"
echo ""
echo "DataGrip üçün PostgreSQL bağlantısı:"
echo "  Host: $(curl -s ifconfig.me)"
echo "  Port: 5432"
echo "  DB:   tradex_pro"
echo "  User: tradex"
echo "  Pass: [girdiyin şifrə]"
