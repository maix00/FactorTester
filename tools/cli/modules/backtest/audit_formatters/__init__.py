"""Audit value formatters for backtest step-mode output.

This package is the extraction point for field/value-kind specific rendering
that used to accumulate inside ``controller.py``.  Keep terminal mechanics
behind small callables so field owners can declare value semantics later
without importing click or CLI table code.
"""

