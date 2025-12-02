from pydantic import BaseModel
from typing import Literal


class Order(BaseModel):
    symbol: str
    qty: float
    side: Literal["buy", "sell"]
    price: float | None = None


class Trade(BaseModel):
    order: Order
    executed_price: float
    executed_qty: float
