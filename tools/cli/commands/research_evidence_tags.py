"""Native Agent-tag commands for reusable Evidence."""

from __future__ import annotations

from pathlib import Path

import click

from tools.cli.core.context import client_from_config

from .research_evidence_common import (
    emit,
    library_for_profile,
    profile_options,
)


def register_tag_commands(group: click.Group) -> None:
    group.add_command(tag)


@click.group("tag")
def tag() -> None:
    """List, propose and maintain user-scoped Agent tags."""


@tag.command("list")
@click.option("--include-retired", is_flag=True)
@click.option("--profile-id")
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True)
def list_command(
    include_retired: bool,
    profile_id: str | None,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    tags = client_from_config().list_research_evidence_tags(
        include_retired=include_retired,
    )
    if profile_id:
        library = library_for_profile(
            release_profile=release_profile, profile_id=profile_id,
        )
        for item in tags:
            library.record_tag(item)
        library.rebuild_index()
    emit({"tags": tags}, as_json)


@tag.command("propose")
@click.option("--title-zh", required=True)
@click.option("--description-zh", required=True)
@click.option("--distinct-reason", default="")
@profile_options
@click.option("--json", "as_json", is_flag=True)
def propose(
    title_zh: str,
    description_zh: str,
    distinct_reason: str,
    profile_id: str,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    value = client_from_config().propose_research_evidence_tag({
        "title_zh": title_zh,
        "description_zh": description_zh,
        "created_by_profile_ref": f"profile:{profile_id}",
        "distinct_reason": distinct_reason,
    })
    emit(value, as_json)


@tag.command("create")
@click.option("--proposal-token", required=True)
@profile_options
@click.option("--json", "as_json", is_flag=True)
def create(
    proposal_token: str,
    profile_id: str,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    value = client_from_config().create_research_evidence_tag(
        proposal_token
    )
    library = library_for_profile(
        release_profile=release_profile, profile_id=profile_id,
    )
    library.record_tag(value)
    library.rebuild_index()
    emit(value, as_json)


@tag.command("update")
@click.argument("tag_ref")
@click.option("--title-zh", required=True)
@click.option("--description-zh", required=True)
@profile_options
@click.option("--json", "as_json", is_flag=True)
def update(
    tag_ref: str,
    title_zh: str,
    description_zh: str,
    profile_id: str,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    value = client_from_config().update_research_evidence_tag(
        tag_ref, title_zh=title_zh, description_zh=description_zh,
    )
    library_for_profile(
        release_profile=release_profile, profile_id=profile_id,
    ).record_tag(value)
    emit(value, as_json)


@tag.command("retire")
@click.argument("tag_ref")
@profile_options
@click.option("--json", "as_json", is_flag=True)
def retire(
    tag_ref: str,
    profile_id: str,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    value = client_from_config().retire_research_evidence_tag(tag_ref)
    library_for_profile(
        release_profile=release_profile, profile_id=profile_id,
    ).record_tag(value)
    emit(value, as_json)


@tag.command("attach")
@click.argument("evidence_ref")
@click.argument("tag_ref")
@profile_options
@click.option("--json", "as_json", is_flag=True)
def attach(
    evidence_ref: str,
    tag_ref: str,
    profile_id: str,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    value = client_from_config().attach_research_evidence_tag(
        evidence_ref, tag_ref,
    )
    emit(value, as_json)


@tag.command("detach")
@click.argument("evidence_ref")
@click.argument("tag_ref")
@profile_options
@click.option("--json", "as_json", is_flag=True)
def detach(
    evidence_ref: str,
    tag_ref: str,
    profile_id: str,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    value = client_from_config().detach_research_evidence_tag(
        evidence_ref, tag_ref,
    )
    emit(value, as_json)
