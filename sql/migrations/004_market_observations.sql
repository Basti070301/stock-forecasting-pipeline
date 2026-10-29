-- Additive M4.2a document history; same Store contract, no historical backfill.
CREATE TABLE IF NOT EXISTS si_market_runs (
    id VARCHAR(128) PRIMARY KEY, mode VARCHAR(8) NOT NULL,
    created_at VARCHAR(40) NOT NULL, payload JSON NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_si_market_runs_mode ON si_market_runs (mode);
CREATE TABLE IF NOT EXISTS si_market_observations (
    id VARCHAR(128) PRIMARY KEY, mode VARCHAR(8) NOT NULL,
    created_at VARCHAR(40) NOT NULL, payload JSON NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_si_market_observations_mode ON si_market_observations (mode);
CREATE TABLE IF NOT EXISTS si_price_revisions (
    id VARCHAR(128) PRIMARY KEY, mode VARCHAR(8) NOT NULL,
    created_at VARCHAR(40) NOT NULL, payload JSON NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_si_price_revisions_mode ON si_price_revisions (mode);
