-- Row counts per pipeline layer
SELECT 'stocks' AS dataset, COUNT(*) AS row_count FROM dim_stock
UNION ALL
SELECT 'prices', COUNT(*) FROM fact_stock_price
UNION ALL
SELECT 'features', COUNT(*) FROM fact_stock_features;

-- Coverage and calendar-quality check per ticker
SELECT
    s.ticker,
    COUNT(*) AS price_rows,
    MIN(p.trade_date) AS first_trade_date,
    MAX(p.trade_date) AS last_trade_date,
    COUNT(*) FILTER (
        WHERE EXTRACT(ISODOW FROM p.trade_date) IN (6, 7)
    ) AS weekend_rows
FROM fact_stock_price AS p
JOIN dim_stock AS s USING (stock_id)
GROUP BY s.ticker
ORDER BY s.ticker;

-- Latest prices and engineered features
SELECT
    s.ticker,
    p.trade_date,
    p.close_price,
    f.daily_return,
    f.moving_average_7,
    f.moving_average_30,
    f.volatility_30,
    f.momentum_7,
    f.volume_change,
    f.target_next_day_up
FROM fact_stock_price AS p
JOIN dim_stock AS s USING (stock_id)
LEFT JOIN fact_stock_features AS f
    ON f.stock_id = p.stock_id
   AND f.trade_date = p.trade_date
ORDER BY p.trade_date DESC, s.ticker
LIMIT 25;

-- Target balance (rows without a known next day are excluded)
SELECT
    target_next_day_up,
    COUNT(*) AS observations,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS percentage
FROM fact_stock_features
WHERE target_next_day_up IS NOT NULL
GROUP BY target_next_day_up
ORDER BY target_next_day_up;

-- Thirty-day average return by ticker
SELECT
    s.ticker,
    AVG(f.daily_return) AS average_daily_return,
    AVG(f.volatility_30) AS average_volatility_30
FROM fact_stock_features AS f
JOIN dim_stock AS s USING (stock_id)
WHERE f.trade_date >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY s.ticker
ORDER BY s.ticker;
