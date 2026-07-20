"""Resolve opaque local-profile references for one adapter invocation."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

from ..local_profile import LocalProfileStore


def adapter_binding(
    client_root: Path,
    profile_id: str,
    adapter_id: str,
) -> dict[str, str]:
    if not profile_id:
        return {}
    profile = LocalProfileStore(client_root).load(profile_id)
    for descriptor in profile["adapters"]:
        if descriptor["adapter_id"] == adapter_id:
            if not descriptor["enabled"]:
                raise ValueError(
                    f"adapter is disabled in profile: {profile_id}/{adapter_id}"
                )
            return {
                "FACTORTESTER_ADAPTER_PROFILE_ID": profile_id,
                "FACTORTESTER_ADAPTER_CREDENTIAL_REF": descriptor[
                    "credential_ref"
                ],
                "FACTORTESTER_ADAPTER_CONFIGURATION_REF": _configuration(
                    descriptor["configuration_ref"]
                ),
            }
    raise ValueError(
        f"adapter is not configured in profile: {profile_id}/{adapter_id}"
    )


def _configuration(reference: str) -> str:
    if not reference:
        return ""
    parsed = urlparse(reference)
    if parsed.scheme == "file":
        path = Path(unquote(parsed.path)).expanduser().resolve()
        if not path.is_file():
            raise ValueError(f"adapter configuration not found: {path}")
        return str(path)
    return reference
