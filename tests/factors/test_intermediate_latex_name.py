r"""A Chinese intermediate name must be emitted as text, not as math.

The family templates embed Chinese names (``as_intermediate('差持续期')``).
``\mathrm`` keeps them inside math mode, which KaTeX treats as
LaTeX-incompatible and then prints as raw source.
"""

from __future__ import annotations

from tools.factors.FactorExpr import CLOSE


def test_chinese_intermediate_renders_as_text():
    expr = (CLOSE - CLOSE.shift(1)).as_intermediate("差持续期")
    latex = expr.to_latex()
    assert "\\text{差持续期}" in latex
    assert "\\mathrm{差持续期}" not in latex


def test_ascii_intermediate_keeps_mathrm():
    expr = (CLOSE - CLOSE.shift(1)).as_intermediate("spread")
    latex = expr.to_latex()
    assert "\\mathrm{spread}" in latex
