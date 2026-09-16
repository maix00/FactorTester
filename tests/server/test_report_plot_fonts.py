"""Chinese chart titles must not render as tofu boxes.

The release image ships Debian's `fonts-noto-cjk`, which registers the shared
CJK faces under language suffixes (only the JP faces are installed), so a font
list that only names `Noto Sans CJK SC` falls back to DejaVu Sans and every
Chinese title becomes empty boxes.
"""

from __future__ import annotations

import warnings
from io import BytesIO

from server.jobs.report_outputs.plot_format import PLOT_RC


def test_cjk_families_cover_the_registered_release_faces():
    families = PLOT_RC["font.sans-serif"]
    # fonts-noto-cjk in the release image registers these faces.
    assert "Noto Sans CJK JP" in families
    assert "Noto Sans CJK SC" in families


def test_chinese_title_renders_without_missing_glyphs():
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    from matplotlib import rc_context

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with rc_context(PLOT_RC):
            figure, axis = plt.subplots(1, 1, figsize=(4.0, 2.0))
            axis.plot([0.0, 1.0], [0.0, 1.0])
            axis.set_title("阈值层 · 当日差持续期 · 持仓量")
            figure.tight_layout()
            buffer = BytesIO()
            figure.savefig(buffer, format="svg")
            plt.close(figure)

    missing = [
        str(warning.message) for warning in caught
        if "missing" in str(warning.message).lower()
        and "glyph" in str(warning.message).lower()
    ]
    assert not missing, missing
