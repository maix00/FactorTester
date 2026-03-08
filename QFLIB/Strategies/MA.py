from qf_lib.common.enums.frequency import Frequency
from qf_lib.common.enums.price_field import PriceField
from qf_lib.common.tickers.tickers import Ticker
from qf_lib.backtesting.strategies.abstract_strategy import AbstractStrategy
from qf_lib.backtesting.order.execution_style import MarketOrder
from qf_lib.backtesting.order.time_in_force import TimeInForce
from qf_lib.backtesting.trading_session.backtest_trading_session import BacktestTradingSession

from Factor import get_price_series

class SimpleMAStrategy(AbstractStrategy):
    """
    Strategy which computes two simple moving averages (long - 20 minutes, short - 5 minutes)
    between start and end market events, and creates a buy order in case if the short moving average is
    greater or equal to the long moving average.
    """
    def __init__(self, ts: BacktestTradingSession, ticker: Ticker, long_ma_len: int = 20, short_ma_len: int = 5):
        super().__init__(ts)
        self.broker = ts.broker
        self.order_factory = ts.order_factory
        self.data_provider = ts.data_provider
        self.ticker = ticker
        self.long_ma_len = long_ma_len
        self.short_ma_len = short_ma_len

    def calculate_and_place_orders(self):
        
        # Use data handler to download last 20 minutes close prices and use them to compute the moving averages
        long_ma_series = get_price_series(self.data_provider, self.ticker, PriceField.Close, self.long_ma_len, frequency=Frequency.MIN_1)
        # print(long_ma_series)
        if long_ma_series is None:
            return  # Not enough data to compute the long MA yet
        
        long_ma_price = long_ma_series.mean()
        short_ma_series = long_ma_series.tail(self.short_ma_len)
        short_ma_price = short_ma_series.mean()

        if short_ma_price >= long_ma_price:
            # Place a buy Market Order, adjusting the position to a value equal to 100% of the portfolio
            orders = self.order_factory.target_percent_orders({self.ticker: 1.0}, MarketOrder(), TimeInForce.DAY)
        else:
            orders = self.order_factory.target_percent_orders({self.ticker: 0.0}, MarketOrder(), TimeInForce.DAY)

        # Cancel any open orders and place the newly created ones
        self.broker.cancel_all_open_orders()
        self.broker.place_orders(orders)

class IntradayMomemtumStrategy(AbstractStrategy):
    """
    Strategy which computes intraday momentum based on close prices and creates a buy order in case if the momentum is positive.
    """
    def __init__(self, ts: BacktestTradingSession, ticker: Ticker, lookback_period: int = 10):
        super().__init__(ts)
        self.broker = ts.broker
        self.order_factory = ts.order_factory
        self.data_provider = ts.data_provider
        self.ticker = ticker
        self.lookback_period = lookback_period

    def calculate_and_place_orders(self):
        
        # Use data handler to download last 'lookback_period' close prices and use them to compute the momentum
        price_series = get_price_series(self.data_provider, self.ticker, PriceField.Close, self.lookback_period, frequency=Frequency.MIN_1)
        if price_series is None:
            return  # Not enough data to compute the momentum yet
        
        momentum = price_series.iloc[-1] - price_series.iloc[0]

        if momentum > 0:
            # Place a buy Market Order, adjusting the position to a value equal to 100% of the portfolio
            orders = self.order_factory.target_percent_orders({self.ticker: 1.0}, MarketOrder(), TimeInForce.DAY)
        else:
            orders = self.order_factory.target_percent_orders({self.ticker: 0.0}, MarketOrder(), TimeInForce.DAY)

        # Cancel any open orders and place the newly created ones
        self.broker.cancel_all_open_orders()
        self.broker.place_orders(orders)