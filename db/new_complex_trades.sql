BEGIN TRANSACTION;

-- 1. SET YOUR VARIABLES HERE
CREATE TEMP TABLE vars(
    new_group_id INTEGER,
    ticker TEXT,
    strat_name TEXT,
    ts DATETIME,
    short_expiry TEXT,
    long_expiry TEXT,
    strike REAL
);

-- Note: 'new_group_id' should be the next available ID in your trade_groups table
INSERT INTO vars VALUES (
    10,                         -- new_group_id
    'TSLA',                       -- ticker
    'Calendar Spread',          -- strat_name
    '2025-10-24 11:00:45',      -- ts (Timestamp for entry)
    '20251031',               -- short_expiry (Front month/week)
    '20260220',               -- long_expiry (Back month)
    440.0                       -- strike
);

-- 2. CREATE THE STRATEGY GROUP
INSERT INTO trade_groups (id, strategy_name, status, notes, created_at, updated_at)
VALUES (
    (SELECT new_group_id FROM vars),
    (SELECT strat_name FROM vars),
    'Open',
	'OTP',
    (SELECT ts FROM vars),
    (SELECT ts FROM vars)
);

-- 3. INSERT THE SHORT LEG (The Front Month)
INSERT INTO legs (
    group_id, symbol, side, quantity, strikeprice, option_type, 
    expiry_dt, entry_date, entry_price, entry_commission, status
) VALUES (
    (SELECT new_group_id FROM vars),
    (SELECT ticker FROM vars),
    'STO',          -- Sell to Open
    -1,             -- Short Quantity
    (SELECT strike FROM vars),
    'C',
    (SELECT short_expiry FROM vars),
    (SELECT ts FROM vars),
    12.10,           -- Example Entry Price (Credit)
    0.70,           -- Commission
    'Active'
);

-- 4. INSERT THE LONG LEG (The Back Month)
INSERT INTO legs (
    group_id, symbol, side, quantity, strikeprice, option_type, 
    expiry_dt, entry_date, entry_price, entry_commission, status
) VALUES (
    (SELECT new_group_id FROM vars),
    (SELECT ticker FROM vars),
    'BTO',          -- Buy to Open
    1,              -- Long Quantity
    (SELECT strike FROM vars),
    'C',
    (SELECT long_expiry FROM vars),
    (SELECT ts FROM vars),
    56.74,           -- Example Entry Price (Debit)
    0.70,           -- Commission
    'Active'
);

-- CLEANUP
DROP TABLE vars;
COMMIT;