"""Platform LaTeX with CJK labels and unescaped placeholders must render.

KaTeX treats Chinese in math mode as LaTeX-incompatible and, with
throwOnError:false, prints the raw source; several published family templates
also write ``$F`` where math mode needs ``\\$F``. One shared sanitiser keeps
the real public family templates rendering as formulas.
"""

import json
import os
from pathlib import Path
import sqlite3
import subprocess


def test_math_latex_safe_js(tmp_path):
    root = Path(__file__).resolve().parents[2]
    from server.modules.custom_factors.catalog import _load_factor_family_from_source
    import settings

    fixture = tmp_path / "families.json"
    families = []
    with sqlite3.connect(settings.CACHE_DB_PATH) as database:
        sources = database.execute(
            "SELECT factor_id, source_code FROM factor_family_sources "
            "WHERE source_kind='public' AND owner_username='' ORDER BY factor_id"
        ).fetchall()
    assert len(sources) >= 50, "expected the real public family source set"
    for factor_id, source_code in sources:
        factor_id = str(factor_id or "")
        family_class, _ = _load_factor_family_from_source(
            str(source_code or ""), factor_id,
        )
        if family_class is not None:
            family = family_class()
            families.append({
                "factor_family_alias": factor_id,
                "math_expr": str(getattr(family, "math_expr", "") or ""),
            })
    fixture.write_text(
        json.dumps({"families": families}, ensure_ascii=False),
        encoding="utf-8",
    )
    result = subprocess.run(
        ["node", "tests/js/test_math_latex_safe.js"],
        cwd=root,
        env={**os.environ, "FT_FAMILIES_FIXTURE": str(fixture)},
        capture_output=True, text=True, timeout=60,
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
