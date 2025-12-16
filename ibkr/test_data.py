# test_data.py
from ib_insync import *
import time

# Adjust these to match your actual connection
HOST = "127.0.0.1"
PORT = 4001
CLIENTID = 8
generic_ticks = 106

ib = IB()
ib.connect(HOST, PORT, clientId=CLIENTID)

def test_symbol(contract):
    print("\n==============================")
    print("Testing:", contract)
    print("==============================")

    # Request live data
    ib.reqMarketDataType(1)
    ticker = ib.reqMktData(contract, generic_ticks, snapshot=False)

     # Wait up to 2 seconds for data
    for _ in range(20):
        ib.sleep(0.1)
        if any([
            ticker.last is not None,
            ticker.bid is not None,
            ticker.ask is not None,
            ticker.close is not None
        ]):
            break

    print("\n==============================")
    print("Request Market Data Type - LIVE")
    print("==============================")
    print("last :", ticker.last)
    print("bid  :", ticker.bid)
    print("ask  :", ticker.ask)
    print("close:", ticker.close)
    print("modelGreeks:", ticker.modelGreeks)

    # Request post data
    ib.reqMarketDataType(2)
    ticker = ib.reqMktData(contract, generic_ticks, snapshot=False)

     # Wait up to 2 seconds for data
    for _ in range(20):
        ib.sleep(0.1)
        if any([
            ticker.last is not None,
            ticker.bid is not None,
            ticker.ask is not None,
            ticker.close is not None
        ]):
            break

    print("\n==============================")
    print("Request Market Data Type - FROZEN")
    print("==============================")
    print("last :", ticker.last)
    print("bid  :", ticker.bid)
    print("ask  :", ticker.ask)
    print("close:", ticker.close)
    print("modelGreeks:", ticker.modelGreeks)

    # Request delayed data
    ib.reqMarketDataType(3)
    ticker = ib.reqMktData(contract, generic_ticks, snapshot=False)

     # Wait up to 2 seconds for data
    for _ in range(20):
        ib.sleep(0.1)
        if any([
            ticker.last is not None,
            ticker.bid is not None,
            ticker.ask is not None,
            ticker.close is not None
        ]):
            break

    print("\n==============================")
    print("Request Market Data Type - DELAYED")
    print("==============================")
    print("last :", ticker.last)
    print("bid  :", ticker.bid)
    print("ask  :", ticker.ask)
    print("close:", ticker.close)
    print("modelGreeks:", ticker.modelGreeks)


exchange = "SMART"
currency = "USD"
multiplier = 100.0

# ✅ Test a known liquid stock
symbol = "NVDA"
test_symbol(Stock(symbol, exchange, currency))

# ✅ Test a known liquid option
strikeprice = 200.0
expiry_dt = "20260116"
right = "C"
test_symbol(Option(symbol, expiry_dt, strikeprice, right, exchange, multiplier, currency))

# ✅ Test one of your symbols
symbol = "ORCL"
strikeprice = 190
expiry_dt = "20260102"
test_symbol(Stock(symbol, exchange, currency))
test_symbol(Option(symbol, expiry_dt, strikeprice, right, exchange, multiplier, currency))

# ✅ Test one of your symbols
symbol = "TSLA"
strikeprice = 450
expiry_dt = "20260109"
test_symbol(Stock(symbol, exchange, currency))
test_symbol(Option(symbol, expiry_dt, strikeprice, right, exchange, multiplier, currency))