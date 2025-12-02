from __future__ import annotations
from .models.trade import Order, Trade


class Executor:
    """Simulated executor that 'executes' orders and returns trades."""

    def __init__(self):
        self._history: list[Trade] = []

    def execute(self, order: Order) -> Trade:
        # naive: use order.price if provided, else simulate immediate fill with small slippage
        price = order.price or 100.0
        executed_price = price * (1 + (0.0001 if order.side == "buy" else -0.0001))
        trade = Trade(order=order, executed_price=executed_price, executed_qty=order.qty)
        self._history.append(trade)
        return trade

    def history(self) -> list[Trade]:
        return list(self._history)
