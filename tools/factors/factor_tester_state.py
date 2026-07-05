"""FactorTesterState -- the actual per-session state a FactorTester page
object carries (products/factors/results cache, time range, group-calendar
settings, product-selection metadata). Pulled out of FactorTester itself so
FactorTester can become a thin task-dispatch wrapper (see
tools/factors/factor_tester_tasks.py) -- this class has no behavior of its
own, just the data.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any, Optional

from tools.data.types import DataFreq

if TYPE_CHECKING:
    from tools.data.account_manage import User
    from tools.data.types import DataTime
    from tools.factors.Factors import Factor
    from tools.factors.FactorRunResult import FactorRunResult
    from tools.products.Product import Product
    from tools.testers.backtest.engines.native.state import BacktestRunState


class FactorTesterState:
    def __init__(
        self,
        products,
        alias: Optional[str] = None,
        start_dt: Optional["DataTime"] = None,
        end_dt: Optional["DataTime"] = None,
        group_calendar_freq: Optional[Any] = None,
        user: Optional["User"] = None,
    ) -> None:
        self.alias = alias
        self.user = user
        self.logger = logging.getLogger("factortester.factor_tester")

        self.products: set["Product"] = set(products)
        self.all_products: set["Product"] = set(products)
        self.group_calendar_freq = DataFreq(group_calendar_freq or DataFreq.MIN1)
        self.selected_paths: list = []
        self.sift_product_by_empty_data_bool = False
        self.factors: list["Factor"] = []
        self.sync_signal_index = None
        self.sync_signal_index_replaced = None
        self._sync_lock = threading.Lock()
        self.results: dict["Factor", "FactorRunResult"] = {}
        self._results_lock = threading.RLock()
        self.last_group_factor: Optional["Factor"] = None

        self.start_dt: Optional["DataTime"] = None
        self.end_dt: Optional["DataTime"] = None
        self.start_date: Any = None
        self.end_date: Any = None
        if start_dt is not None and end_dt is not None:
            from tools.factors.factor_tester_tasks import update_time_range
            update_time_range(self, start_dt, end_dt)

        # Product-path-selection metadata, set post-construction by
        # factor_tester_runtime.create_factor_tester_for_run -- not used by
        # the constructor itself, just declared here so attribute access
        # never falls through to AttributeError.
        self.label = ""
        self.product_group = ""
        self.product_group_template_id = ""
        self.selection_source_type = ""
        self.selection_source_key = ""
        self.product_selection = None
        self._page_uuid = None

        # Set once a "backtest" task has run against this state -- lets a
        # later request (snapshot/detail routes) read back the same
        # BacktestRunState instead of re-running anything.
        self.account: Optional["BacktestRunState"] = None

        self.logger.info(
            "factor_tester_initialized",
            extra={"tester_alias": self.alias, "product_count": len(self.products)},
        )
