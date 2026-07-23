"""Flow declaration for FeeModule."""

from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.modules.engine import EngineModule
from tools.testers.backtest.modules.market_data import MarketDataModule

from .resolution import resolve_fee_cost


def build_fee_flow(module):
    return Flow(
        "resolve_fee_cost",
        inputs=(
            EngineModule.engine_mode, module.fee_mode,
            module.transaction_fee_source, module.fixed_fee_rate,
            MarketDataModule.current_prices,
            MarketDataModule.current_historical_fields,
        ),
        outputs=(), phase=Phase.PER_EVENT, event_kind=EventKind.ORDER,
        order=8, description="计算交易费用",
        event_payload_inputs=("order",), owner=module.__name__,
        compute=resolve_fee_cost,
    )
