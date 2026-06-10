"""Core factor test implementations.

Flask routes and FactorTester methods should stay as thin orchestration layers;
test logic lives in this package.
"""

from tools.factors.tests.CrossSectionIC import CrossSectionIC
from tools.factors.tests.NextReturns import NextReturns

__all__ = ["CrossSectionIC", "NextReturns"]
