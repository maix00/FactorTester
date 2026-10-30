from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from scripts.docs.build_project_pdf import (
    namespace_source_anchors,
    normalize_inline_code,
    normalize_status_symbols,
    rewrite_registered_links,
)


ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "scripts" / "docs" / "build_project_pdf.py"


class ProjectPdfManifestTests(unittest.TestCase):
    def test_curated_manifest_and_current_implementation_paths_validate(self) -> None:
        result = subprocess.run(
            [sys.executable, str(BUILDER), "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("document manifest check: passed", result.stdout)
        self.assertIn("sections, 43 documents", result.stdout)

    def test_inline_code_can_be_used_with_listings_without_verbatim_macro_error(self) -> None:
        source = r"\passthrough{\lstinline!product\_docs/foo.md!}"
        self.assertEqual(
            normalize_inline_code(source),
            r"\texttt{product\_\allowbreak{}docs/\allowbreak{}foo.\allowbreak{}md}",
        )

    def test_inline_code_escapes_math_delimiters(self) -> None:
        self.assertEqual(
            normalize_inline_code(r"\passthrough{\lstinline!$F & {x}!}"),
            r"\texttt{\$F \& \{\allowbreak{}x\}\allowbreak{}}",
        )

    def test_inline_code_math_relation_uses_a_pdf_glyph(self) -> None:
        self.assertEqual(
            normalize_inline_code(r"\passthrough{\lstinline!a ≡ b!}"),
            r"\texttt{a \ensuremath{\equiv} b}",
        )

    def test_status_emojis_become_readable_labels(self) -> None:
        self.assertEqual(
            normalize_status_symbols("✅ pass / ❌ fail / ⚠️ note / ⚠ review"),
            "[通过] pass / [失败] fail / [注意] note / [注意] review",
        )

    def test_latex_normalization_makes_longtable_without_caption_valid(self) -> None:
        self.assertEqual(
            normalize_inline_code(r"\def\LTcaptype{none}\begin{longtable}"),
            r"\def\LTcaptype{}\begin{longtable}",
        )

    def test_source_anchors_are_namespaced_and_local_links_follow_them(self) -> None:
        self.assertEqual(
            namespace_source_anchors(
                "## Duty {#responsibility}\n\nSee [the section](#responsibility).",
                "system-overview",
            ),
            "## Duty {#system-overview-responsibility}\n\n"
            "See [the section](#system-overview-responsibility).",
        )

    def test_registered_document_link_preserves_namespaced_section_fragment(self) -> None:
        source = "product_docs/guides/getting-started.md"
        self.assertEqual(
            rewrite_registered_links(
                "[system overview](../implementation/system-overview.md#responsibility)",
                source,
                {"product_docs/implementation/system-overview.md": "system-overview"},
                {},
            ),
            "[system overview](#system-overview-responsibility)",
        )


if __name__ == "__main__":
    unittest.main()
