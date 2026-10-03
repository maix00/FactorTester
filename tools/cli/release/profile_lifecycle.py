"""Provider-neutral, receipt-backed local Profile lifecycle."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .local_profile import LocalProfileStore, new_local_profile
from .local_profile_contracts import validate_local_identifier
from .locations import validate_client_root
from .storage import json_hash, read_json, utc_now, write_json
from .strategy_workspace import initialize_strategy_repo
from .user_layout import default_user_profile_root, default_user_strategy_library


class ProfileLifecycle:
    def __init__(self, client_root: Path) -> None:
        self.client_root = validate_client_root(client_root)
        self.store = LocalProfileStore(self.client_root)

    def create(
        self,
        *,
        profile_id: str,
        display_name: str,
        server_url: str | None = None,
        agent_id: str = "",
        role: str = "research",
        principal_ref: str = "",
    ) -> dict[str, Any]:
        del server_url
        validate_local_identifier(profile_id, "profile_id")
        if not principal_ref:
            raise ValueError(
                "principal_ref is required for the profile layout"
            )
        workspace_root = default_user_profile_root(
            principal_ref, profile_id
        )
        tombstone = self._tombstone(profile_id)
        if tombstone.exists():
            raise ValueError("deleted profile must be purged before reuse")
        candidate = new_local_profile(
            profile_id=profile_id,
            display_name=display_name,
            workspace_root=workspace_root,
            principal_ref=principal_ref,
        )
        if agent_id:
            validate_local_identifier(agent_id, "agent_id")
            if role not in {"planning", "research"}:
                raise ValueError("profile Agent role is unsupported")
            candidate["agents"] = [{
                "agent_id": agent_id,
                "role": role,
                "scope": {"workspace_id": "unbound"},
                "status": "needs_scope",
                "next_action": (
                    "Bind an authorized research workspace before execution."
                ),
            }]
        try:
            existing = self.store.load(profile_id)
        except ValueError:
            profile = self.store.save(candidate)
        else:
            stable = (
                "display_name", "workspace_root",
                "session_binding", "agents",
            )
            if any(existing[key] != candidate[key] for key in stable):
                raise ValueError("existing profile differs from create request")
            profile = existing
        workspace = self.store.ensure_workspace_root(profile_id)
        strategy_library = default_user_strategy_library(principal_ref)
        initialize_strategy_repo(strategy_library, owner_ref=principal_ref)
        return self._receipt("create", "active", profile_id, profile=profile, extra={
            "recommended_factor_worktree": {
                "branch": f"agent/{profile_id}",
                "worktree_path": str(workspace / "factor-worktree"),
            },
            "recommended_strategy_worktree": {
                "branch": f"strategy/{profile_id}",
                "worktree_path": str(workspace / "strategy-worktree"),
            },
            "strategy_library": str(strategy_library),
        })

    def deactivate(self, profile_id: str) -> dict[str, Any]:
        profile = self.store.load(profile_id)
        if profile["status"] != "inactive":
            profile["status"] = "inactive"
            self.store.save(profile)
        return self._receipt(
            "deactivate", "inactive", profile_id, profile=profile
        )

    def delete(self, profile_id: str) -> dict[str, Any]:
        existing_receipt = self._load_receipt(profile_id, "delete")
        if existing_receipt is not None and self._tombstone(profile_id).is_file():
            return existing_receipt
        profile = self.store.load(profile_id)
        if profile["status"] != "inactive":
            raise ValueError("profile must be inactive before delete")
        raise ValueError(
            "profile delete is disabled until authoritative server reference "
            "clearance is available; deactivate or unbind the profile instead"
        )

    def purge(self, profile_id: str) -> dict[str, Any]:
        existing_receipt = self._load_receipt(profile_id, "purge")
        tombstone = self._tombstone(profile_id)
        if existing_receipt is not None and not tombstone.exists():
            return existing_receipt
        value = read_json(tombstone)
        if not isinstance(value, dict):
            raise ValueError("deleted profile tombstone not found")
        workspace = Path(str(value["workspace_root"]))
        if workspace.exists():
            if not workspace.is_dir() or any(workspace.iterdir()):
                raise ValueError(
                    "profile workspace is not empty; purge refused"
                )
            workspace.rmdir()
        tombstone.unlink()
        return self._receipt("purge", "purged", profile_id)

    def _receipt(
        self,
        action: str,
        status: str,
        profile_id: str,
        *,
        profile: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing = self._load_receipt(profile_id, action)
        if existing is not None:
            return existing
        body = {
            "schema_version": 1,
            "action": action,
            "status": status,
            "profile_id": profile_id,
            "branch_retained": True,
            "commits_retained": True,
            "created_at": utc_now(),
            **(extra or {}),
        }
        if profile is not None:
            body["profile"] = profile
        receipt = {**body, "receipt_hash": json_hash(body)}
        path = self._receipt_path(profile_id, action)
        write_json(path, receipt)
        path.chmod(0o600)
        return {**receipt, "receipt_ref": path.resolve().as_uri()}

    def _load_receipt(
        self,
        profile_id: str,
        action: str,
    ) -> dict[str, Any] | None:
        value = read_json(self._receipt_path(profile_id, action))
        if value is None:
            return None
        declared = str(value.get("receipt_hash") or "")
        body = dict(value)
        body.pop("receipt_hash", None)
        body.pop("receipt_ref", None)
        if declared != json_hash(body):
            raise ValueError("profile lifecycle receipt is corrupt")
        path = self._receipt_path(profile_id, action)
        return {**value, "receipt_ref": path.resolve().as_uri()}

    def _receipt_path(self, profile_id: str, action: str) -> Path:
        validate_local_identifier(profile_id, "profile_id")
        return (
            self.store.root
            / "lifecycle-receipts"
            / profile_id
            / f"{action}.json"
        )

    def _tombstone(self, profile_id: str) -> Path:
        validate_local_identifier(profile_id, "profile_id")
        return self.store.root / "deleted" / f"{profile_id}.json"
