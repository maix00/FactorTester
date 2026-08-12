"""Persistent Manager endpoint and credential storage."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import ipaddress
import json
import os
from pathlib import Path
import platform
import subprocess
from urllib.parse import urlparse

from tools.cli.http import DEFAULT_HOME, HOME_ENV


MANAGER_CONFIG_ENV = "FACTORTESTER_MANAGER_CONFIG"
MANAGER_TOKEN_ENV = "FACTORTESTER_MANAGER_TOKEN"
KEYCHAIN_SERVICE = "com.gtht.factortester.manager"


@dataclass(frozen=True, slots=True)
class ManagerConfig:
    base_url: str

    @classmethod
    def from_url(cls, value: str) -> "ManagerConfig":
        url = str(value or "").strip().rstrip("/")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Manager URL must be a complete http(s) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Manager URL must not contain credentials or query data")
        if parsed.scheme != "https" and not _is_loopback(parsed.hostname):
            raise ValueError("remote Manager URL requires HTTPS")
        return cls(base_url=url)


def manager_config_path() -> Path:
    configured = os.environ.get(MANAGER_CONFIG_ENV)
    if configured:
        return Path(configured).expanduser()
    home = Path(os.environ.get(HOME_ENV, str(DEFAULT_HOME))).expanduser()
    return home / "manager.json"


def save_manager_config(
    config: ManagerConfig,
    path: Path | None = None,
) -> None:
    target = path or manager_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"base_url": config.base_url}, indent=2) + "\n",
        encoding="utf-8",
    )
    target.chmod(0o600)


def load_manager_config(path: Path | None = None) -> ManagerConfig:
    target = path or manager_config_path()
    if not target.is_file():
        raise FileNotFoundError(
            "Manager 尚未配置，请先运行 factortester manager configure"
        )
    payload = json.loads(target.read_text(encoding="utf-8"))
    return ManagerConfig.from_url(str(payload.get("base_url") or ""))


class ManagerCredentialStore:
    def __init__(self, config: ManagerConfig) -> None:
        self.config = config
        self.account = sha256(config.base_url.encode()).hexdigest()

    def read(self) -> str:
        environment = os.environ.get(MANAGER_TOKEN_ENV, "").strip()
        if environment:
            return environment
        if platform.system() == "Darwin":
            result = subprocess.run(
                [
                    "security", "find-generic-password", "-w",
                    "-s", KEYCHAIN_SERVICE, "-a", self.account,
                ],
                capture_output=True,
                text=True,
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        path = self._fallback_path()
        return path.read_text(encoding="utf-8").strip() if path.is_file() else ""

    def write(self, token: str) -> None:
        value = str(token or "").strip()
        if not value:
            raise ValueError("Manager session token is empty")
        if platform.system() == "Darwin":
            subprocess.run(
                [
                    "security", "add-generic-password", "-U",
                    "-s", KEYCHAIN_SERVICE, "-a", self.account, "-w", value,
                ],
                check=True,
                capture_output=True,
            )
            return
        path = self._fallback_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value + "\n", encoding="utf-8")
        path.chmod(0o600)

    def clear(self) -> None:
        if platform.system() == "Darwin":
            subprocess.run(
                [
                    "security", "delete-generic-password",
                    "-s", KEYCHAIN_SERVICE, "-a", self.account,
                ],
                capture_output=True,
            )
            return
        self._fallback_path().unlink(missing_ok=True)

    def _fallback_path(self) -> Path:
        return manager_config_path().with_name(
            f"manager-token-{self.account[:12]}"
        )


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
