"""Lease and execute durable node Inbox commands independently of SSE."""

from __future__ import annotations

import threading
import time

from server.manager.storage.transfers import TransferInboxStore


class TransferCommandExecutor:
    def __init__(
        self,
        *,
        inbox: TransferInboxStore,
        source_push,
        claimant: str,
        retry_delay: float = 2.0,
    ) -> None:
        self.inbox = inbox
        self.source_push = source_push
        self.claimant = str(claimant or "").strip()
        self.retry_delay = max(0.1, float(retry_delay))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run_once(self) -> int:
        claimed = self.inbox.claim(claimant=self.claimant, limit=1)
        if not claimed:
            return 0
        command = claimed[0]
        try:
            if command.command_type == "source.push":
                self.source_push.execute(command)
            else:
                raise ValueError(
                    f"unsupported transfer command: {command.command_type}"
                )
        except Exception as exc:
            self.inbox.retry(
                command.command_id,
                claimant=self.claimant,
                error=str(exc),
                delay=self.retry_delay,
            )
            raise
        self.inbox.complete(command.command_id, claimant=self.claimant)
        return 1

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="factor-transfer-command-executor",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                if not self.run_once():
                    self._stop.wait(self.retry_delay)
            except (OSError, PermissionError, RuntimeError, ValueError):
                self._stop.wait(self.retry_delay)
