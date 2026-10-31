"""Internal transport from the desktop host to the local Research catalog.

The native host verifies the Manager session and supplies the binding; this is
not a remotely exposed API. Requests, including identity, travel on stdin so
credentials and document content are never command-line arguments.
"""
from __future__ import annotations

import json
import sys

import click

from tools.cli.release.locations import default_client_root
from tools.cli.release.research_reporting.local_rpc import LocalResearchRPC


@click.command("local-research-request", hidden=True)
def local_research_request() -> None:
    """Execute one host-scoped local Research request from standard input."""
    raw = sys.stdin.read(32769)
    if len(raw) > 32768:
        raise click.ClickException("local research request exceeds the size limit")
    try:
        envelope = json.loads(raw)
        if not isinstance(envelope, dict) or set(envelope) != {"binding", "profile", "request"}:
            raise ValueError("invalid host envelope")
        binding, profile = envelope["binding"], envelope["profile"]
        if not isinstance(binding, dict) or set(binding) != {"issuer", "identity_id"}:
            raise ValueError("invalid host identity")
        if not isinstance(profile, dict) or set(profile) != {"profile_id", "display_name"}:
            raise ValueError("invalid host profile")
        # The host's current user is the only supported local owner. No Profile
        # is created and legacy username-bound Profiles are never adopted here.
        if profile["profile_id"] != "self":
            raise ValueError("invalid host profile")
        rpc = LocalResearchRPC(default_client_root(), issuer=binding["issuer"],
                               identity_id=binding["identity_id"], profiles=[profile])
        result = rpc.request(envelope["request"])
    except (ValueError, TypeError, PermissionError, KeyError, json.JSONDecodeError) as exc:
        raise click.ClickException("invalid local research request") from exc
    click.echo(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
