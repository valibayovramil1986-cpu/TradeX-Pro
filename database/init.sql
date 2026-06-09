-- TradeX-Pro PostgreSQL Sxemi
-- Docker ilk dəfə başladıqda avtomatik icra olunur

CREATE TABLE IF NOT EXISTS trades (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_price DOUBLE PRECISION,
    exit_price DOUBLE PRECISION,
    units DOUBLE PRECISION,
    usd_value DOUBLE PRECISION,
    risk_usd DOUBLE PRECISION,
    pnl_usd DOUBLE PRECISION,
    pnl_pct DOUBLE PRECISION,
    signal_score DOUBLE PRECISION,
    confidence DOUBLE PRECISION,
    open_time TIMESTAMPTZ,
    close_time TIMESTAMPTZ,
    duration_minutes DOUBLE PRECISION,
    exit_reason TEXT,
    phase TEXT,
    indicators_triggered JSONB DEFAULT '[]',
    market_condition TEXT,
    reflection JSONB,
    lesson TEXT,
    overall_grade TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS indicator_weights (
    id SERIAL PRIMARY KEY,
    weights_json JSONB NOT NULL,
    reason TEXT,
    trades_analyzed INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pattern_stats (
    pattern TEXT PRIMARY KEY,
    win_count INTEGER DEFAULT 0,
    loss_count INTEGER DEFAULT 0,
    total_pnl DOUBLE PRECISION DEFAULT 0,
    last_updated TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS quarantined_patterns (
    id SERIAL PRIMARY KEY,
    pattern TEXT NOT NULL UNIQUE,
    loss_rate DOUBLE PRECISION,
    sample_count INTEGER,
    quarantined_at TIMESTAMPTZ DEFAULT NOW(),
    active BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS strategy_changes (
    id SERIAL PRIMARY KEY,
    change_type TEXT,
    description TEXT,
    details_json JSONB,
    triggered_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS weekly_reflections_log (
    id SERIAL PRIMARY KEY,
    reflection_json JSONB,
    performance_score DOUBLE PRECISION,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS phase_evaluations_log (
    id SERIAL PRIMARY KEY,
    phase TEXT,
    evaluation_json JSONB,
    readiness_score DOUBLE PRECISION,
    advance_recommended BOOLEAN,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS phase_state (
    id INTEGER PRIMARY KEY CHECK(id=1),
    current_phase TEXT DEFAULT '1',
    phase_start_date TIMESTAMPTZ DEFAULT NOW(),
    phase_promoted_by TEXT
);

INSERT INTO phase_state (id, current_phase, phase_start_date)
VALUES (1, '1', NOW())
ON CONFLICT (id) DO NOTHING;

-- İndekslər
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_phase ON trades(phase);
CREATE INDEX IF NOT EXISTS idx_trades_close_time ON trades(close_time);
CREATE INDEX IF NOT EXISTS idx_trades_direction ON trades(direction);
