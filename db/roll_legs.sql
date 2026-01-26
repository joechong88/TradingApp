BEGIN TRANSACTION;

-- 0. Prepare the temp table for common variables
CREATE TEMP TABLE vars(update_ts DATETIME);
INSERT INTO vars VALUES ('2026-01-21 09:38:15.000000');


-- 1. Close the existing short leg (the one you are rolling)
-- We set the exit price and mark it as 'Rolled'
UPDATE legs 
SET 
    status = 'Rolled', 
    exit_price = 0.04,         -- Replace with your actual buy-back price
    exit_commission = 1.05,    -- Replace with actual commission
    exit_date = (SELECT update_ts FROM vars) -- Current ET timestamp
WHERE id = 72;

INSERT INTO legs (
    group_id, 
    symbol, 
    side, 
    quantity, 
    strikeprice, 
    option_type, 
    expiry_dt, 
	entry_date,
    entry_price, 
    entry_commission,
    status
) VALUES (
    12,              -- Keep the same Group ID
    'NVDA',                    -- Example Ticker
    'STO',                    -- Rolling a short leg
    -1, -- Quantity (negative for Short)
    185, -- New Strike
    'Call', -- Call
    '20260123', -- New Expiry
	(SELECT update_ts FROM vars),	-- Entry date
    0.60, -- New Entry Price (Credit received)
    1.05, -- New Entry Commission
    'Active'
);

-- 3. Update the Group's 'updated_at' timestamp
UPDATE trade_groups 
SET updated_at = (SELECT update_ts FROM vars) 
WHERE id = 12;

-- 4. Cleanup
DROP TABLE vars;

COMMIT;