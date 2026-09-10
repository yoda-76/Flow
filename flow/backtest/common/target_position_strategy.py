"""
Generic Nautilus Strategy adapter shared by every strategy whose entire
decision reduces to "what's my target position (+1/-1/0) for this bar",
computed upstream by that strategy's own signal.py. On each bar, look up
the precomputed target for that bar's timestamp and submit whatever
market order is needed to reach it -- no strategy-specific logic lives
here at all.

Extracted here (not left duplicated per-strategy) once a second strategy
(ma_crossover_futures) needed the exact same order-execution shape as the
first (gex_regime_follower) -- a real second case, not a speculative one
(CLAUDE.md: don't over-abstract ahead of a second real case).

If a future strategy needs something this shape can't express (multi-leg
orders, stops, position sizing beyond a fixed quantity), it gets its OWN
strategy.py in its own folder rather than forcing a special case in here.

`target_positions` is set as a plain instance attribute after
construction (strategy.target_positions = {...}), not threaded through
StrategyConfig -- avoids relying on msgspec's serialization behavior for
a large timestamp-keyed mapping that never needs to survive a restart in
a backtest-only context.
"""

from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy, StrategyConfig


class TargetPositionStrategyConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    trade_quantity: int = 1


class TargetPositionStrategy(Strategy):
    def __init__(self, config: TargetPositionStrategyConfig):
        super().__init__(config)
        self.target_positions = {}  # bar.ts_event (ns, UTC) -> int, set by the runner before starting
        self.bars_seen = 0
        self.bars_with_signal = 0
        self.flips = 0

    def on_start(self):
        instrument = self.cache.instrument(self.config.instrument_id)
        if instrument is None:
            self.log.error(f"Instrument {self.config.instrument_id} not found, stopping.")
            self.stop()
            return
        self.instrument = instrument
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar):
        self.bars_seen += 1
        target = self.target_positions.get(bar.ts_event, 0)
        if target != 0:
            self.bars_with_signal += 1

        current = self.portfolio.net_position(self.config.instrument_id)
        current_side = 0 if current == 0 else (1 if current > 0 else -1)
        if target == current_side:
            return

        qty = Quantity.from_int(self.config.trade_quantity)
        if current_side != 0:
            self.close_all_positions(self.config.instrument_id)
        if target != 0:
            side = OrderSide.BUY if target > 0 else OrderSide.SELL
            order = self.order_factory.market(instrument_id=self.config.instrument_id, order_side=side, quantity=qty)
            self.submit_order(order)
            self.flips += 1

    def on_stop(self):
        self.close_all_positions(self.config.instrument_id)
        self.log.info(f"bars_seen={self.bars_seen} bars_with_signal={self.bars_with_signal} flips={self.flips}")
