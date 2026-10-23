"""NautilusTrader integration boundary for FactorTester business services.

No NautilusTrader module is imported during Manager or Flask application startup.
The package is optional until a dedicated execution service enables this bridge.
"""

from .capabilities import native_capabilities
from .reports import export_backtest_reports

__all__ = ["native_capabilities", "export_backtest_reports"]
