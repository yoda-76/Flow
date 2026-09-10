"""
Shared BacktestEngine venue setup. Exists as its own function (not
inlined per-strategy) specifically because of a real bug this caught:
the first two strategies (gex_regime_follower, ma_crossover_futures) both
independently used AccountType.CASH, which silently REJECTS every short
-selling order ("SHORT SELLING not permitted on a CASH account") --
confirmed live via on_order_rejected. Both strategies' target-position
logic re-submits a rejected order on every subsequent bar for as long as
the target stays short, which is why the first MA-crossover run showed
124,005 "flips" for a signal that only actually changes ~170 times over
the same window -- almost all of those were doomed resubmission attempts,
not real trades, and the reported PnL from both early runs never
reflected the short side of either strategy at all.

AccountType.MARGIN with leverage=1 fixes this (supports both long and
short) without introducing artificial leverage -- 1x margin still means
one traded unit costs one unit of capital, same economics as CASH, just
without the short-sale restriction that doesn't reflect how futures/
index-derivative trading actually works (you can go short a NIFTY future
in reality; a CASH-account model that forbids it doesn't match the thing
being backtested).

Also applies a fee model -- Nautilus HAS real fee-model machinery
(nautilus_trader.backtest.models.fee: FeeModel base class plus
FixedFeeModel, PerContractFeeModel, MakerTakerFeeModel, confirmed by
reading the actual source, not assumed), but add_venue's `fee_model`
parameter defaults to None, and neither strategy's first run passed one
-- both backtests silently ran commission-free. Default here is
FixedFeeModel, a flat per-order commission (matches how NSE discount
brokerage actually works -- a fixed amount per order, not scaling with
size), using a clearly-labelled round placeholder value, not a real NSE
cost schedule (that also has STT/GST/exchange charges layered on top --
a real refinement, not attempted here).
"""

from decimal import Decimal

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.backtest.models.fee import FeeModel, FixedFeeModel
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money

# Placeholder flat per-order commission -- a round, clearly-labelled
# approximation of discount-broker NSE F&O brokerage, not a real cost
# schedule. Revisit once a strategy's results are worth costing precisely.
DEFAULT_COMMISSION_PER_ORDER = 20.0


def add_standard_venue(engine: BacktestEngine, venue: Venue, instrument, starting_balance: float,
                        fee_model: FeeModel = None) -> None:
    if fee_model is None:
        fee_model = FixedFeeModel(Money(DEFAULT_COMMISSION_PER_ORDER, instrument.quote_currency))
    engine.add_venue(
        venue=venue, oms_type=OmsType.NETTING, account_type=AccountType.MARGIN,
        base_currency=instrument.quote_currency, starting_balances=[Money(starting_balance, instrument.quote_currency)],
        default_leverage=Decimal(1), fee_model=fee_model,
    )
