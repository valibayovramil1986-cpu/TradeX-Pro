#!/bin/bash
# ══════════════════════════════════════════════
# TradeX-Pro — Universal İdarəetmə Skripti
# İstifadə: bash start.sh [komanda]
#
# Komandalar:
#   bash start.sh          → botu başlat (default)
#   bash start.sh start    → botu başlat
#   bash start.sh stop     → botu dayandır
#   bash start.sh restart  → yenidən başlat
#   bash start.sh update   → GitHub-dan yenilə + restart
#   bash start.sh logs     → canlı loglar
#   bash start.sh status   → konteyner vəziyyəti
#   bash start.sh backup   → DB backup
# ══════════════════════════════════════════════

set -e
DIR="/opt/tradex_pro"
COMPOSE="docker compose"
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[TradeX]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1"; }

# ── Yoxlamalar ────────────────────────────────
check_docker() {
    if ! command -v docker &>/dev/null; then
        err "Docker tapılmadı. Quraşdırın: curl -fsSL https://get.docker.com | sh"
        exit 1
    fi
    if ! docker info &>/dev/null; then
        err "Docker işləmir. Başladın: systemctl start docker"
        exit 1
    fi
}

check_env() {
    if [ ! -f "$DIR/.env" ]; then
        err ".env faylı tapılmadı: $DIR/.env"
        warn "Nümunə: cp $DIR/config/.env.example $DIR/.env && nano $DIR/.env"
        exit 1
    fi
    # Əsas açarları yoxla
    source "$DIR/.env"
    missing=()
    [ -z "$OPENAI_API_KEY" ]      && missing+=("OPENAI_API_KEY")
    [ -z "$TELEGRAM_BOT_TOKEN" ]  && missing+=("TELEGRAM_BOT_TOKEN")
    [ -z "$TELEGRAM_CHAT_ID" ]    && missing+=("TELEGRAM_CHAT_ID")
    [ -z "$POSTGRES_PASSWORD" ]   && missing+=("POSTGRES_PASSWORD")

    if [ ${#missing[@]} -gt 0 ]; then
        err ".env faylında bu açarlar boşdur:"
        for k in "${missing[@]}"; do echo "  ❌ $k"; done
        warn "nano $DIR/.env ilə doldurun"
        exit 1
    fi
}

# ── Komandalar ────────────────────────────────
cmd_start() {
    log "TradeX-Pro başladılır..."
    check_docker
    check_env
    cd "$DIR"
    $COMPOSE up -d
    sleep 3
    cmd_status
    log "✅ Bot işləyir! Loglar üçün: bash start.sh logs"
}

cmd_stop() {
    log "TradeX-Pro dayandırılır..."
    cd "$DIR"
    $COMPOSE down
    log "✅ Dayandırıldı."
}

cmd_restart() {
    log "TradeX-Pro yenidən başladılır..."
    cd "$DIR"
    $COMPOSE restart tradex_bot
    sleep 2
    cmd_status
}

cmd_update() {
    log "GitHub-dan son kod çəkilir..."
    cd "$DIR"
    git pull origin main
    log "Docker image yenilənir..."
    $COMPOSE down
    $COMPOSE up -d --build
    sleep 3
    cmd_status
    log "✅ Yeniləmə tamamlandı!"
}

cmd_logs() {
    log "Loglar (çıxmaq üçün Ctrl+C):"
    cd "$DIR"
    $COMPOSE logs -f tradex_bot
}

cmd_status() {
    echo ""
    echo "═══════════════════════════════════"
    echo "  TradeX-Pro Konteyner Vəziyyəti"
    echo "═══════════════════════════════════"
    cd "$DIR"
    $COMPOSE ps
    echo ""
    # PostgreSQL yoxla
    if docker exec tradex_postgres pg_isready -U tradex -d tradex_pro &>/dev/null; then
        echo -e "  🗄️  PostgreSQL: ${GREEN}✅ Aktiv${NC}"
    else
        echo -e "  🗄️  PostgreSQL: ${RED}❌ Problem var${NC}"
    fi
    echo "═══════════════════════════════════"
}

cmd_backup() {
    BACKUP_DIR="$DIR/backups"
    mkdir -p "$BACKUP_DIR"
    FILENAME="tradex_backup_$(date +%Y%m%d_%H%M%S).sql"
    log "Backup başladılır: $FILENAME"
    docker exec tradex_postgres pg_dump -U tradex tradex_pro > "$BACKUP_DIR/$FILENAME"
    gzip "$BACKUP_DIR/$FILENAME"
    log "✅ Backup saxlandı: $BACKUP_DIR/$FILENAME.gz"
    # 7 gündən köhnə backupları sil
    find "$BACKUP_DIR" -name "*.gz" -mtime +7 -delete
    log "Köhnə backuplar silindi (7 gündən artıq)"
}

# ── Ana məntiq ────────────────────────────────
COMMAND="${1:-start}"

case "$COMMAND" in
    start)   cmd_start   ;;
    stop)    cmd_stop    ;;
    restart) cmd_restart ;;
    update)  cmd_update  ;;
    logs)    cmd_logs    ;;
    status)  cmd_status  ;;
    backup)  cmd_backup  ;;
    *)
        echo "İstifadə: bash start.sh [start|stop|restart|update|logs|status|backup]"
        exit 1
        ;;
esac
