"""Small, fail-closed supervisor for the server-local Mihomo process."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


class MihomoError(RuntimeError):
    """A safe, user-facing Mihomo lifecycle error."""


class MihomoSupervisor:
    """Own one optional Mihomo process without exposing its control port."""

    def __init__(
        self,
        state_root: Path,
        *,
        binary: str | None = None,
        source_config: str | None = None,
        api_host: str = "127.0.0.1",
        api_port: int = 9090,
        proxy_port: int = 7890,
    ) -> None:
        self.state_root = Path(state_root).expanduser().resolve() / "mihomo"
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.binary = str(binary or os.environ.get(
            "FACTORTESTER_MIHOMO_BIN", "/usr/local/bin/mihomo",
        )).strip()
        self.source_config = str(source_config or os.environ.get(
            "FACTORTESTER_MIHOMO_CONFIG_FILE",
            "/run/secrets/manager-state/mihomo.yaml",
        )).strip()
        self.api_host = str(api_host or "127.0.0.1").strip()
        self.api_port = int(api_port)
        self.proxy_port = int(proxy_port)
        self._process: subprocess.Popen[bytes] | None = None
        self._state_path = self.state_root / "state.json"
        self._runtime_config = self.state_root / "config.yaml"
        self._log_path = self.state_root / "mihomo.log"
        self._state = self._read_state()

    def status(self) -> dict[str, object]:
        running = self._running()
        error = str(self._state.get("last_error") or "")
        version = str(self._state.get("version") or "")
        if running and not version:
            version = self._version()
        return {
            # Mihomo is deliberately not auto-started after Manager restart;
            # report the live process state instead of a stale previous action.
            "enabled": running,
            "running": running,
            "configured": Path(self.source_config).is_file(),
            "version": version,
            "api": "same-origin",
            "proxy_port": self.proxy_port if running else None,
            "last_error": error,
        }

    def start(self) -> dict[str, object]:
        if self._running():
            return self.status()
        binary = Path(self.binary)
        source = Path(self.source_config)
        if not binary.is_file() or not os.access(binary, os.X_OK):
            return self._failed("Mihomo binary is unavailable")
        if not source.is_file():
            return self._failed("Mihomo configuration is unavailable")
        try:
            self._write_runtime_config(source)
            log = self._log_path.open("ab")
            self._process = subprocess.Popen(
                [str(binary), "-d", str(self.state_root), "-f", str(self._runtime_config)],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                close_fds=True,
                start_new_session=True,
            )
            log.close()
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                if self._process.poll() is not None:
                    raise MihomoError("Mihomo exited during startup")
                if self._version() and self._proxy_ready():
                    self._state.update({"enabled": True, "last_error": ""})
                    self._save_state()
                    return self.status()
                time.sleep(0.1)
            raise MihomoError("Mihomo did not become ready")
        except (MihomoError, OSError, ValueError) as exc:
            self.stop()
            return self._failed(str(exc))

    def stop(self) -> dict[str, object]:
        process = self._process
        self._process = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        self._state.update({"enabled": False, "last_error": ""})
        self._save_state()
        return self.status()

    def restart(self) -> dict[str, object]:
        self.stop()
        return self.start()

    def close(self) -> None:
        self.stop()

    def api_endpoint(self) -> tuple[str, int]:
        if not self._running():
            raise MihomoError("Mihomo is not running")
        return self.api_host, self.api_port

    def proxy_url(self) -> str:
        """Return the loopback proxy URL for an Agent child, if enabled."""
        if not self._running():
            return ""
        return f"http://{self.api_host}:{self.proxy_port}"

    def _running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _version(self) -> str:
        try:
            with urlopen(
                f"http://{self.api_host}:{self.api_port}/version",
                timeout=0.35,
            ) as response:
                value = json.loads(response.read(64 * 1024).decode("utf-8"))
            return str(value.get("version") or "") if isinstance(value, dict) else ""
        except (OSError, URLError, ValueError, json.JSONDecodeError):
            return ""

    def _proxy_ready(self) -> bool:
        """Return whether the mixed proxy listener accepts local connections."""
        try:
            with socket.create_connection(
                (self.api_host, self.proxy_port),
                timeout=0.35,
            ):
                return True
        except OSError:
            return False

    def _read_state(self) -> dict[str, object]:
        try:
            value = json.loads(self._state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError, json.JSONDecodeError):
            return {}

    def _save_state(self) -> None:
        temporary = self._state_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self._state, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary, self._state_path)

    def _failed(self, message: str) -> dict[str, object]:
        self._state.update({"enabled": False, "last_error": message[:240]})
        self._save_state()
        return self.status()

    def _write_runtime_config(self, source: Path) -> None:
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - deployment dependency
            raise MihomoError("Mihomo YAML support is unavailable") from exc
        try:
            value = yaml.safe_load(source.read_text(encoding="utf-8"))
        except (OSError, ValueError, yaml.YAMLError) as exc:
            raise MihomoError("Mihomo configuration is invalid") from exc
        if not isinstance(value, dict):
            raise MihomoError("Mihomo configuration must be an object")
        # The source file may contain a subscription's external settings. The
        # Manager owns the safety boundary and always forces loopback-only
        # controller/proxy listeners, with no TUN or LAN exposure.
        value["external-controller"] = f"{self.api_host}:{self.api_port}"
        value["secret"] = ""
        value["allow-lan"] = False
        value["bind-address"] = self.api_host
        value["mixed-port"] = self.proxy_port
        value["socks-port"] = 0
        value["redir-port"] = 0
        value["tproxy-port"] = 0
        if isinstance(value.get("tun"), dict):
            value["tun"] = {**value["tun"], "enable": False}
        else:
            value["tun"] = {"enable": False}
        self._runtime_config.write_text(
            yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        self._runtime_config.chmod(0o600)


__all__ = ["MihomoError", "MihomoSupervisor"]
