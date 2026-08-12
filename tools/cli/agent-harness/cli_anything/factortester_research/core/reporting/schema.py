"""Compatibility alias for the public local reporting implementation."""

import sys
from tools.cli.release.research_reporting import schema as _implementation

sys.modules[__name__] = _implementation
