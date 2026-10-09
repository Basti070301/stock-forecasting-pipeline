-- Additive platform tables; immutable migration.


CREATE TABLE IF NOT EXISTS si_backtests (
	id VARCHAR(128) NOT NULL, 
	mode VARCHAR(8) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	payload JSON NOT NULL, 
	PRIMARY KEY (id)
)

;
CREATE INDEX IF NOT EXISTS ix_si_backtests_mode ON si_backtests (mode);

CREATE TABLE IF NOT EXISTS si_forecasts (
	id VARCHAR(128) NOT NULL, 
	mode VARCHAR(8) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	payload JSON NOT NULL, 
	PRIMARY KEY (id)
)

;
CREATE INDEX IF NOT EXISTS ix_si_forecasts_mode ON si_forecasts (mode);

CREATE TABLE IF NOT EXISTS si_instruments (
	id VARCHAR(128) NOT NULL, 
	mode VARCHAR(8) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	payload JSON NOT NULL, 
	PRIMARY KEY (id)
)

;
CREATE INDEX IF NOT EXISTS ix_si_instruments_mode ON si_instruments (mode);

CREATE TABLE IF NOT EXISTS si_intraday_prices (
	id VARCHAR(128) NOT NULL, 
	mode VARCHAR(8) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	payload JSON NOT NULL, 
	PRIMARY KEY (id)
)

;
CREATE INDEX IF NOT EXISTS ix_si_intraday_prices_mode ON si_intraday_prices (mode);

CREATE TABLE IF NOT EXISTS si_jobs (
	id VARCHAR(128) NOT NULL, 
	mode VARCHAR(8) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	payload JSON NOT NULL, 
	PRIMARY KEY (id)
)

;
CREATE INDEX IF NOT EXISTS ix_si_jobs_mode ON si_jobs (mode);

CREATE TABLE IF NOT EXISTS si_models (
	id VARCHAR(128) NOT NULL, 
	mode VARCHAR(8) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	payload JSON NOT NULL, 
	PRIMARY KEY (id)
)

;
CREATE INDEX IF NOT EXISTS ix_si_models_mode ON si_models (mode);

CREATE TABLE IF NOT EXISTS si_news (
	id VARCHAR(128) NOT NULL, 
	mode VARCHAR(8) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	payload JSON NOT NULL, 
	PRIMARY KEY (id)
)

;
CREATE INDEX IF NOT EXISTS ix_si_news_mode ON si_news (mode);

CREATE TABLE IF NOT EXISTS si_news_links (
	id VARCHAR(128) NOT NULL, 
	mode VARCHAR(8) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	payload JSON NOT NULL, 
	PRIMARY KEY (id)
)

;
CREATE INDEX IF NOT EXISTS ix_si_news_links_mode ON si_news_links (mode);

CREATE TABLE IF NOT EXISTS si_outcomes (
	id VARCHAR(128) NOT NULL, 
	mode VARCHAR(8) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	payload JSON NOT NULL, 
	PRIMARY KEY (id)
)

;
CREATE INDEX IF NOT EXISTS ix_si_outcomes_mode ON si_outcomes (mode);

CREATE TABLE IF NOT EXISTS si_provider_calls (
	id VARCHAR(128) NOT NULL, 
	mode VARCHAR(8) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	payload JSON NOT NULL, 
	PRIMARY KEY (id)
)

;
CREATE INDEX IF NOT EXISTS ix_si_provider_calls_mode ON si_provider_calls (mode);

CREATE TABLE IF NOT EXISTS si_schema_versions (
	id VARCHAR(128) NOT NULL, 
	mode VARCHAR(8) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	payload JSON NOT NULL, 
	PRIMARY KEY (id)
)

;
CREATE INDEX IF NOT EXISTS ix_si_schema_versions_mode ON si_schema_versions (mode);

CREATE TABLE IF NOT EXISTS si_sentiments (
	id VARCHAR(128) NOT NULL, 
	mode VARCHAR(8) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	payload JSON NOT NULL, 
	PRIMARY KEY (id)
)

;
CREATE INDEX IF NOT EXISTS ix_si_sentiments_mode ON si_sentiments (mode);
