"""Shared setting registration helpers used across multiple applications.

These base registration functions are NOT application-specific — they are
imported by application registrations (group_test, ic_test, etc.).
"""

from .category import (
    CATEGORY_CANDIDATE_KEYS,
    CATEGORY_SELECTION_KEYS,
    register_category_candidate_list_base,
    register_category_selection_base,
)
from .factor import (
    FACTOR_CANDIDATE_KEYS,
    FACTOR_SELECTION_KEYS,
    FACTOR_SELECTIONS_KEYS,
    FACTOR_SET_SELECTION_KEYS,
    FACTOR_SOURCE_SELECTION_KEYS,
    register_factor_candidate_list_base,
    register_factor_execution_base,
    register_factor_selection_base,
    register_factor_selections_base,
    register_factor_set_selections_base,
    register_factor_source_selections_base,
)
from .market_data import (
    MARKET_DATA_SELECTION_KEYS,
    register_market_data_base,
)
from .product_path import (
    PRODUCT_PATH_CANDIDATE_KEYS,
    PRODUCT_PATH_SELECTION_KEYS,
    PRODUCT_PATH_SELECTIONS_KEYS,
    register_product_path_candidate_list_base,
    register_product_path_selection_base,
    register_product_path_selections_base,
)
from .run_inputs import register_run_inputs_base
from .run_window import (
    RUN_WINDOW_KEYS,
    register_run_window_base,
)
from .scope_chips import register_factor_product_scope_chips
from .template import register_test_template_base
