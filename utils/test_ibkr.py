import asyncio
from ib_insync import IB, Option, util

async def test_delayed_attributes():
    ib = IB()
    try:
        # Connect to your TWS/Gateway
        await ib.connectAsync('127.0.0.1', 4001, clientId=99)
        
        # 1. Force Delayed Data Mode
        ib.reqMarketDataType(3) 
        
        # 2. Define the exact contract from your screenshot
        # (Replace with your actual symbol/expiry if different)
        contract = Option('HOOD', '20251226', 120, 'P', 'SMART')
        await ib.qualifyContractsAsync(contract)
        
        # 3. Request Data
        ticker = ib.reqMktData(contract, genericTickList='106', snapshot=False)
        
        print(f"Waiting for data for {contract.symbol}...")
        for i in range(10):  # Wait up to 5 seconds
            await asyncio.sleep(0.5)
            
            # Explicitly check the delayed attributes
            d_last = getattr(ticker, 'delayedLast', 'N/A')
            d_bid = getattr(ticker, 'delayedBid', 'N/A')
            d_ask = getattr(ticker, 'delayedAsk', 'N/A')
            d_close = getattr(ticker, 'delayedClose', 'N/A')
            
            print(f"[{i}] Standard Last: {ticker.last} | Delayed Last: {d_last}")
            print(f"    Delayed Bid/Ask: {d_bid} / {d_ask} | Delayed Close: {d_close}")
            
            if d_last != 'N/A' and not util.isNan(d_last):
                print(f"\n✅ SUCCESS: Found delayedLast = {d_last}")
                break
                
    finally:
        ib.disconnect()

if __name__ == "__main__":
    asyncio.run(test_delayed_attributes())