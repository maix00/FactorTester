"""Provider-neutral contract for server-verified usage receipts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .schema import connect_agent_flow
from .validation import require_non_negative, require_text


@dataclass(frozen=True)
class VerifiedProviderUsage:
    provider_id: str
    provider_request_id: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    provider_attestation: str
    launcher_attestation: str

    def validate(self) -> None:
        for field in (
            "provider_id",
            "provider_request_id",
            "provider_attestation",
            "launcher_attestation",
        ):
            require_text(field, getattr(self, field))
        for field in (
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
        ):
            require_non_negative(field, getattr(self, field))
        if self.cache_read_tokens > self.input_tokens:
            raise ValueError(
                "cache_read_tokens cannot exceed input_tokens"
            )


class UsageReceiptVerifier(Protocol):
    """Trusted adapter that verifies one opaque Provider receipt."""

    def verify(
        self,
        receipt: str,
        *,
        reservation: dict[str, Any],
    ) -> VerifiedProviderUsage: ...


_VERIFIERS: dict[str, UsageReceiptVerifier] = {}


def register_usage_receipt_verifier(
    provider_id: str,
    verifier: UsageReceiptVerifier,
) -> None:
    require_text("provider_id", provider_id)
    _VERIFIERS[provider_id] = verifier


def clear_usage_receipt_verifiers() -> None:
    _VERIFIERS.clear()


def usage_receipt_verifier(provider_id: str) -> UsageReceiptVerifier:
    require_text("provider_id", provider_id)
    verifier = _VERIFIERS.get(provider_id)
    if verifier is None:
        raise ValueError(
            f"no trusted usage receipt verifier for provider {provider_id}"
        )
    return verifier


def verify_usage_receipt(
    db_path: Path,
    *,
    owner_user_id: str,
    invocation_id: str,
    receipt: str,
    expected_provider_id: str,
    verifier: UsageReceiptVerifier,
) -> VerifiedProviderUsage:
    """Verify one receipt outside the settlement transaction."""
    require_text("receipt", receipt)
    require_text("expected_provider_id", expected_provider_id)
    with connect_agent_flow(db_path) as conn:
        row = conn.execute(
            """
            SELECT * FROM agent_invocations
            WHERE owner_user_id=? AND invocation_id=?
              AND status='reserved'
            """,
            (owner_user_id, invocation_id),
        ).fetchone()
    if row is None:
        raise ValueError("reserved Agent invocation not found")
    reservation = {
        key: row[key]
        for key in (
            "invocation_id",
            "owner_user_id",
            "agent_id",
            "actor_role",
            "authority_scope",
            "task_ref",
            "runtime_id",
            "model_id",
            "agent_principal_hash",
            "lineage_hash",
            "input_hash",
            "max_input_tokens",
            "max_output_tokens",
            "request_hash",
        )
    }
    usage = verifier.verify(receipt, reservation=reservation)
    if not isinstance(usage, VerifiedProviderUsage):
        raise ValueError(
            "usage verifier must return VerifiedProviderUsage"
        )
    if usage.provider_id != expected_provider_id:
        raise ValueError(
            "usage receipt provider does not match selected verifier"
        )
    usage.validate()
    return usage
