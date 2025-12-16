import pandas as pd
from utils.cleaners import clean_numeric, clean_datetime, clean_bool, clean_str

def test_dataframe_row_cleaning():
    # Simulate messy Excel rows
    data = [
        {
            "symbol": "SOFI",
            "strategy": "Long",
            "entry_date": "10/29/2025",
            "entry_time": "9:38:45 AM",
            "entry_price": "$31.63",
            "units": "2,000.00",
            "strikeprice": None,
            "expiry_dt": None,
            "expected_rr": None,
            "entry_commissions": None,
            "is_open": "OPEN",
            "exit_price": None,
            "exit_date": None,
            "exit_time": None,
            "exit_commissions": None,
            "notes": None,
        },
        {
            "symbol": "NVDA",
            "strategy": "Long",
            "entry_date": "11/10/2025",
            "entry_time": "9:52:06 AM",
            "entry_price": "210.1",
            "units": 240,
            "strikeprice": float("nan"),  # messy NaN
            "expiry_dt": float("nan"),
            "expected_rr": None,
            "entry_commissions": "1.05",
            "is_open": None,
            "exit_price": None,
            "exit_date": None,
            "exit_time": None,
            "exit_commissions": None,
            "notes": " Earnings play ",
        },
    ]

    df = pd.DataFrame(data)

    # Clean first row (SOFI)
    row = df.iloc[0]
    assert clean_str(row["symbol"]) == "SOFI"
    assert clean_str(row["strategy"]) == "Long"
    dt = clean_datetime(row["entry_date"], row["entry_time"])
    assert dt.year == 2025 and dt.month == 10 and dt.day == 29
    assert clean_numeric(row["entry_price"]) == 31.63
    assert clean_numeric(row["units"]) == 2000.0
    assert clean_bool(row["is_open"]) is True

    # Clean second row (NVDA)
    row = df.iloc[1]
    assert clean_str(row["symbol"]) == "NVDA"
    assert clean_numeric(row["entry_price"]) == 210.1
    assert clean_numeric(row["units"]) == 240.0
    assert clean_numeric(row["strikeprice"]) is None  # NaN → None
    assert clean_str(row["expiry_dt"]) is None        # NaN → None
    assert clean_numeric(row["entry_commissions"]) == 1.05
    assert clean_bool(row["is_open"]) is True         # default True when None
    assert clean_str(row["notes"]) == "Earnings play"