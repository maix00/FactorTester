"""Platform LaTeX with CJK labels and unescaped placeholders must render.

KaTeX treats Chinese in math mode as LaTeX-incompatible and, with
throwOnError:false, prints the raw source; several published family templates
also write ``$F`` where math mode needs ``\\$F``.  One shared sanitiser keeps
90 real family templates rendering as formulas.
"""

from pathlib import Path
import subprocess


def test_math_latex_safe_js():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["node", "tests/js/test_math_latex_safe.js"],
        cwd=root, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_math_render_goes_through_the_shared_helper():
    root = Path(__file__).resolve().parents[2]
    web = root / "server/manager/web"
    raw = [
        path for path in web.rglob("*.js")
        if "vendor" not in path.parts
        and "katex.render(" in path.read_text(encoding="utf-8")
    ]
    # Only the shared helper may call KaTeX directly.
    assert [path.name for path in raw] == ["shared-ui.js"], [str(p) for p in raw]
