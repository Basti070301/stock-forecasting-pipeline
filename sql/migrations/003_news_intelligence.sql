-- M3: additive metadata on the existing document store.


CREATE TABLE IF NOT EXISTS si_news_revisions (
	id VARCHAR(128) NOT NULL,
	mode VARCHAR(8) NOT NULL,
	created_at VARCHAR(40) NOT NULL,
	payload JSON NOT NULL,
	PRIMARY KEY (id)
)

;
CREATE INDEX IF NOT EXISTS ix_si_news_revisions_mode ON si_news_revisions (mode);

CREATE TABLE IF NOT EXISTS si_news_aggregates (
	id VARCHAR(128) NOT NULL,
	mode VARCHAR(8) NOT NULL,
	created_at VARCHAR(40) NOT NULL,
	payload JSON NOT NULL,
	PRIMARY KEY (id)
)

;
CREATE INDEX IF NOT EXISTS ix_si_news_aggregates_mode ON si_news_aggregates (mode);

CREATE TABLE IF NOT EXISTS si_provider_status (
	id VARCHAR(128) NOT NULL,
	mode VARCHAR(8) NOT NULL,
	created_at VARCHAR(40) NOT NULL,
	payload JSON NOT NULL,
	PRIMARY KEY (id)
)

;
CREATE INDEX IF NOT EXISTS ix_si_provider_status_mode ON si_provider_status (mode);

CREATE TABLE IF NOT EXISTS si_news_locks (
	id VARCHAR(128) NOT NULL,
	mode VARCHAR(8) NOT NULL,
	created_at VARCHAR(40) NOT NULL,
	payload JSON NOT NULL,
	PRIMARY KEY (id)
)

;
CREATE INDEX IF NOT EXISTS ix_si_news_locks_mode ON si_news_locks (mode);
