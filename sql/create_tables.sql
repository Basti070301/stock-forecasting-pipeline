-- ============================================================
-- Database schema for stock forecasting pipeline
-- ============================================================

-- Optional: Drop tables if they already exist
-- DROP TABLE IF EXISTS fact_stock_features;
-- DROP TABLE IF EXISTS fact_stock_price;
-- DROP TABLE IF EXISTS dim_stock;

-- ============================================================
-- Dimension table: Stock master data
-- ============================================================

CREATE TABLE dim_stock (
    stock_id SERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL UNIQUE,
    company_name VARCHAR(255),
    sector VARCHAR(100),
    industry VARCHAR(150),
    country VARCHAR(100),
    currency VARCHAR(10),
    exchange VARCHAR(50),
    market_cap BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- Fact table: Historical stock prices
-- ============================================================

CREATE TABLE fact_stock_price (
    price_id SERIAL PRIMARY KEY,
    stock_id INT NOT NULL,
    trade_date DATE NOT NULL,
    open_price NUMERIC(14, 4),
    high_price NUMERIC(14, 4),
    low_price NUMERIC(14, 4),
    close_price NUMERIC(14, 4),
    volume BIGINT,
    dividends NUMERIC(14, 6),
    stock_splits NUMERIC(14, 6),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_stock_price_stock
        FOREIGN KEY (stock_id)
        REFERENCES dim_stock(stock_id)
        ON DELETE CASCADE,

    CONSTRAINT uq_stock_price
        UNIQUE (stock_id, trade_date)
);

-- ============================================================
-- Fact table: Engineered stock features
-- ============================================================

CREATE TABLE fact_stock_features (
    feature_id SERIAL PRIMARY KEY,
    stock_id INT NOT NULL,
    trade_date DATE NOT NULL,
    daily_return NUMERIC(14, 8),
    moving_average_7 NUMERIC(14, 4),
    moving_average_30 NUMERIC(14, 4),
    volatility_30 NUMERIC(14, 8),
    momentum_7 NUMERIC(14, 8),
    volume_change NUMERIC(14, 8),
    target_next_day_up BOOLEAN,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_stock_features_stock
        FOREIGN KEY (stock_id)
        REFERENCES dim_stock(stock_id)
        ON DELETE CASCADE,

    CONSTRAINT uq_stock_features
        UNIQUE (stock_id, trade_date)
);

-- ============================================================
-- Indexes for better query performance
-- ============================================================

CREATE INDEX idx_stock_price_stock_date
ON fact_stock_price (stock_id, trade_date);

CREATE INDEX idx_stock_features_stock_date
ON fact_stock_features (stock_id, trade_date);