import pytest
import pandas as pd
from utils.cleaners import clean_numeric, clean_datetime, clean_bool, clean_str

def test_clean_numeric_valid_float():
    assert clean_numeric("31.63") == 31.63
    assert clean_numeric("$31.63") == 31.63
    assert clean_numeric("2,000.00") == 2000.0
    assert clean_numeric(42.0) == 42.0

def test_clean_numeric_blank_or_invalid():
    assert clean_numeric("") is None
    assert clean_numeric(None) is None
    assert clean_numeric(float("nan")) is None
    assert clean_numeric("abc") is None

def test_clean_datetime_combined():
    dt = clean_datetime("10/29/2025", "9:38:45 AM")
    assert isinstance(dt, pd.Timestamp)
    assert dt.year == 2025 and dt.month == 10 and dt.day == 29

def test_clean_datetime_date_only():
    dt = clean_datetime("10/29/2025")
    assert isinstance(dt, pd.Timestamp)
    assert dt.year == 2025

def test_clean_datetime_blank():
    assert clean_datetime(None, None) is None

def test_clean_bool_variants():
    assert clean_bool("OPEN") is True
    assert clean_bool("True") is True
    assert clean_bool("1") is True
    assert clean_bool("false") is False
    assert clean_bool(None) is True  # default open

def test_clean_str_valid():
    assert clean_str(" SOFI ") == "SOFI"

def test_clean_str_blank_or_nan():
    assert clean_str("") == ""
    assert clean_str(None) is None
    assert clean_str(float("nan")) is None