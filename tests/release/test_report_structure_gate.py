from __future__ import annotations

import pytest

from tools.cli.release.research_reporting.authoring.structure_gate import (
    current_chapter_structure,
    validate_current_chapter_structure,
)


def test_direct_ordinary_section_satisfies_the_structure_gate() -> None:
    value = current_chapter_structure(
        _snapshot([("special", "special"), ("analysis", "section")]),
        chapter_component_id="chapter",
    )

    assert validate_current_chapter_structure(value) == value
    assert value["direct_ordinary_component_ids"] == ["analysis"]


@pytest.mark.parametrize("children", [[], [("special", "special")]])
def test_empty_or_special_only_chapter_is_never_advanceable(children) -> None:
    value = current_chapter_structure(
        _snapshot(children),
        chapter_component_id="chapter",
    )

    with pytest.raises(ValueError, match="direct ordinary research section"):
        validate_current_chapter_structure(value)


def _snapshot(children):
    return {
        "head": {"schema_version": 2, "generation": 7, "root_ref": "a" * 64},
        "components": [{
            "component_id": "chapter", "kind": "chapter", "parent_id": None,
        }, *[
            {"component_id": component_id, "kind": kind, "parent_id": "chapter"}
            for component_id, kind in children
        ]],
    }
