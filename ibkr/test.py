from ib_insync import IB, Stock

ib = IB()

try:
    ib.connect('127.0.0.1', 4001, clientId=1)
    print("Connected to IB Gateway on port 4001")
except Exception as e1:
    print("IB Gateway not available:", e1)
    try:
        ib.connect('127.0.0.1', 7694, clientId=1)
        print("Connected to TWS on port 7694")
    except Exception as e2:
        raise ConnectionError(
            f"Could not connect to IB Gateway (4001) or TWS (7694): {e2}"
        )

stock = 'TSLA'
exchange = 'SMART'
currency = 'USD'

contract = Stock(stock, exchange, currency)
md = ib.reqMktData(contract)

ib.sleep(2)  # wait for data
print("Stock:", stock, "Last:", md.last, "Bid:", md.bid, "Ask:", md.ask)