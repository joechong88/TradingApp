import pytest
import pandas as pd
from utils.formatters import format_currency, format_percentage, format_datetime, format_pnl

def test_format_currency_valid():
    assert format_currency(31.63) == "$31.63"
    assert format_currency(2000) == "$2,000.00"
    assert format_currency(0) == "$0.00"

def test_format_currency_none_or_nan():
    assert format_currency(None) == ""
    assert format_currency(float("nan")) == ""

def test_format_percentage_valid():
    assert format_percentage(12.3456) == "12.35%"
    assert format_percentage(0) == "0.00%"

def test_format_percentage_none_or_nan():
    assert format_percentage(None) == ""
    assert format_percentage(float("nan")) == ""

def test_format_datetime_valid():
    ts = pd.Timestamp("2025-12-07 16:32:00")
    assert format_datetime(ts) == "2025-12-07 16:32:00"

def test_format_datetime_none_or_nat():
    assert format_datetime(None) == ""
    assert format_datetime(pd.NaT) == ""

def test_format_pnl_positive():
    assert format_pnl(125.5) == "$125.50"

def test_format_pnl_negative():
    assert format_pnl(-42.75) == "-$42.75"

def test_format_pnl_none_or_nan():
    assert format_pnl(None) == ""
    assert format_pnl(float("nan")) == ""