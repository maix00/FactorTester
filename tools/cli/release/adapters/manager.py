"""File-backed, zero-LLM lifecycle for installed client adapters."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..locations import validate_client_root
from ..storage import read_json, write_json
from .contracts import AdapterAction, AdapterContract, validate_adapter_contract
from .execution import (
    AdapterActionRunner,
    pid_alive,
    terminate_process_group,
)
from .profile_binding import adapter_binding


class ClientAdapterManager:
    def __init__(self, root: Path, *, profile_id: str = "") -> None:
        self.root = validate_client_root(root)
        self.profile_id = profile_id
        self.state_root = self.root / "state" / "adapters"

    def list(self) -> list[dict[str, Any]]:
        return [
            self.status(contract.adapter_id)
            for contract, _ in self._contracts()
        ]

    def status(self, adapter_id: str) -> dict[str, Any]:
        contract, adapter_root = self._find(adapter_id)
        state = self._state(adapter_id)
        running = pid_alive(int(state.get("pid") or 0))
        health = None
        if "health" in contract.actions:
            health = self._runner(adapter_root, adapter_id).foreground(
                contract.actions["health"],
                pid=int(state.get("pid") or 0),
                check=False,
            )
        return {
            "adapter_id": adapter_id,
            "display_name": contract.display_name,
            "version": contract.version,
            "ui_url": contract.ui_url,
            "running": running,
            "healthy": health is None or health["returncode"] == 0,
            "health": health,
        }

    def start(self, adapter_id: str) -> dict[str, Any]:
        contract, adapter_root = self._find(adapter_id)
        state = self._state(adapter_id)
        if pid_alive(int(state.get("pid") or 0)):
            return self.status(adapter_id)
        action = _required_action(contract, "start")
        log_path = self.state_root / f"{adapter_id}.log"
        pid = self._runner(
            adapter_root, adapter_id, bind=True
        ).background(
            action,
            log_path=log_path,
        )
        write_json(self._state_path(adapter_id), {
            "schema_version": 1,
            "pid": pid,
            "release_version": self._release_version(),
        })
        return self.status(adapter_id)

    def stop(self, adapter_id: str) -> dict[str, Any]:
        contract, adapter_root = self._find(adapter_id)
        pid = int(self._state(adapter_id).get("pid") or 0)
        if not pid_alive(pid):
            self._clear_state(adapter_id)
            return self.status(adapter_id)
        if "stop" in contract.actions:
            self._runner(adapter_root, adapter_id).foreground(
                contract.actions["stop"],
                pid=pid,
                check=False,
            )
        terminate_process_group(pid)
        self._clear_state(adapter_id)
        return self.status(adapter_id)

    def open(self, adapter_id: str) -> dict[str, Any]:
        contract, adapter_root = self._find(adapter_id)
        return self._runner(adapter_root, adapter_id).foreground(
            _required_action(contract, "open"),
            pid=int(self._state(adapter_id).get("pid") or 0),
            check=True,
        )

    def _runner(
        self,
        adapter_root: Path,
        adapter_id: str,
        *,
        bind: bool = False,
    ) -> AdapterActionRunner:
        return AdapterActionRunner(
            adapter_root=adapter_root,
            adapter_id=adapter_id,
            binding=(
                adapter_binding(self.root, self.profile_id, adapter_id)
                if bind else {}
            ),
        )

    def _contracts(self) -> list[tuple[AdapterContract, Path]]:
        if not self._release_version():
            return []
        adapters = self._release_root() / "adapters"
        if not adapters.is_dir():
            return []
        result = []
        for manifest in sorted(adapters.glob("*/adapter.json")):
            value = json.loads(manifest.read_text(encoding="utf-8"))
            result.append((validate_adapter_contract(value), manifest.parent))
        return result

    def _find(self, adapter_id: str) -> tuple[AdapterContract, Path]:
        for contract, root in self._contracts():
            if contract.adapter_id == adapter_id:
                return contract, root
        raise ValueError(f"client adapter is not installed: {adapter_id}")

    def _release_version(self) -> str:
        return str((read_json(self.root / "current.json") or {}).get("version") or "")

    def _release_root(self) -> Path:
        version = self._release_version()
        if not version:
            raise ValueError("no client release is installed")
        return self.root / "releases" / version

    def _state_path(self, adapter_id: str) -> Path:
        return self.state_root / f"{adapter_id}.json"

    def _state(self, adapter_id: str) -> dict[str, Any]:
        return read_json(self._state_path(adapter_id)) or {}

    def _clear_state(self, adapter_id: str) -> None:
        self._state_path(adapter_id).unlink(missing_ok=True)


def _required_action(contract: AdapterContract, name: str) -> AdapterAction:
    if name not in contract.actions:
        raise ValueError(f"adapter action is unsupported: {name}")
    return contract.actions[name]
