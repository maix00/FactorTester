"""Small stdlib HTTP session used by the separately installed CLI client."""

from __future__ import annotations

import json
import hashlib
import os
from dataclasses import dataclass
from http.cookiejar import CookieJar, LWPCookieJar, LoadError
from http.cookiejar import Cookie
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

from .agent_auth import AgentCapability


DEFAULT_HOME = Path.home() / ".factortester"
CONFIG_ENV = "FACTORTESTER_CONFIG"
HOME_ENV = "FACTORTESTER_HOME"
STREAM_TIMEOUT_ENV = "FACTORTESTER_STREAM_TIMEOUT"
DEFAULT_STREAM_TIMEOUT = 600.0
DEFAULT_BINARY_LIMIT = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ClientConfig:
    base_url: str

    @classmethod
    def from_host_port(cls, host: str, port: int | str) -> "ClientConfig":
        host = host.strip()
        if host.startswith(("http://", "https://")):
            base = host
        else:
            base = f"http://{host}:{port}"
        return cls(base_url=base.rstrip("/"))

    def for_port(self, port: int) -> "ClientConfig":
        parsed = urlsplit(self.base_url)
        if not parsed.hostname:
            raise ValueError(f"无效服务地址: {self.base_url}")
        host = parsed.hostname
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        netloc = host
        if parsed.username:
            netloc = f"{parsed.username}@{netloc}"
        netloc += f":{int(port)}"
        return ClientConfig(urlunsplit((parsed.scheme or "http", netloc, parsed.path, parsed.query, "")).rstrip("/"))


class HttpClientError(RuntimeError):
    def __init__(self, status: int, url: str, body: str) -> None:
        super().__init__(f"HTTP {status} for {url}: {body[:500]}")
        self.status = status
        self.url = url
        self.body = body


@dataclass(frozen=True, slots=True)
class BinaryResponse:
    content: bytes
    content_type: str


def config_path() -> Path:
    configured = os.environ.get(CONFIG_ENV)
    if configured:
        return Path(configured).expanduser()
    return _home_dir() / "config.json"


def cookie_path() -> Path:
    return _home_dir() / "cookies.lwp"


def cookie_path_for(base_url: str) -> Path:
    """Keep credentials isolated when one CLI talks to several ports."""
    key = hashlib.sha256(base_url.rstrip("/").encode()).hexdigest()[:20]
    return _home_dir() / "cookies" / f"{key}.lwp"


def state_path() -> Path:
    return _home_dir() / "state.json"


def _home_dir() -> Path:
    configured = os.environ.get(HOME_ENV)
    return Path(configured).expanduser() if configured else DEFAULT_HOME


def save_config(config: ClientConfig, path: Path | None = None) -> None:
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"base_url": config.base_url}, ensure_ascii=False, indent=2), encoding="utf-8")


def load_config(path: Path | None = None) -> ClientConfig:
    target = path or config_path()
    if not target.exists():
        raise FileNotFoundError(f"FactorTester CLI 尚未配置，请先运行 factortester configure")
    raw = json.loads(target.read_text(encoding="utf-8"))
    base_url = str(raw.get("base_url") or "").strip()
    if not base_url:
        raise ValueError(f"配置文件缺少 base_url: {target}")
    return ClientConfig(base_url=base_url.rstrip("/"))


class HttpSession:
    """Cookie-aware JSON HTTP client.

    The installed CLI runs on machines without server source code, so this class
    intentionally uses real HTTP only and has no Flask/test_client dependency.
    """

    def __init__(
        self,
        base_url: str,
        *,
        cookies: Path | None = None,
        agent_capability: AgentCapability | None = None,
        bearer_token: str = "",
        persist_cookies: bool | None = None,
        timeout: float = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.agent_capability = agent_capability
        self.bearer_token = str(bearer_token or "").strip()
        # A Manager-issued Profile capability already authenticates every
        # request.  It must not depend on the ordinary user's cookie file,
        # which may be absent or read-only inside the isolated Agent runtime.
        self.persist_cookies = (
            bool(persist_cookies)
            if persist_cookies is not None
            else agent_capability is None
        )
        if self.persist_cookies:
            cookie_file = cookies or cookie_path_for(self.base_url)
            self.cookie_jar = LWPCookieJar(str(cookie_file))
        else:
            self.cookie_jar = CookieJar()
        self.timeout = timeout
        if self.persist_cookies:
            try:
                self.cookie_jar.load(ignore_discard=True, ignore_expires=True)
            except FileNotFoundError:
                pass
            except LoadError:
                Path(self.cookie_jar.filename).unlink(missing_ok=True)
                self.cookie_jar = LWPCookieJar(str(cookie_file))
        self._opener = build_opener(HTTPCookieProcessor(self.cookie_jar))

    def get(self, path: str, *, query: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request("GET", path, query=query)

    def post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request("POST", path, payload=payload or {})

    def put(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request("PUT", path, payload=payload or {})

    def patch(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request("PATCH", path, payload=payload or {})

    def delete(self, path: str, *, query: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request("DELETE", path, query=query)

    def stream_post(self, path: str, payload: dict[str, Any] | None = None):
        yield from self.stream_request("POST", path, payload=payload or {})

    def stream_get(self, path: str, *, query: dict[str, Any] | None = None):
        yield from self.stream_request("GET", path, query=query)

    def download(
        self,
        path: str,
        *,
        maximum_bytes: int = DEFAULT_BINARY_LIMIT,
    ) -> BinaryResponse:
        """Read one bounded authenticated artifact without JSON coercion."""
        if maximum_bytes <= 0:
            raise ValueError("binary download limit must be positive")
        url = self._url(path)
        request = Request(
            url,
            headers=self._headers({"Accept": "application/octet-stream, image/*"}),
            method="GET",
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                declared = response.headers.get("Content-Length")
                if declared is not None and int(declared) > maximum_bytes:
                    raise ValueError("artifact exceeds local download limit")
                raw = response.read(maximum_bytes + 1)
                if len(raw) > maximum_bytes:
                    raise ValueError("artifact exceeds local download limit")
                content_type = str(
                    response.headers.get_content_type()
                    or "application/octet-stream"
                )
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if _looks_like_html(body):
                raise ValueError(
                    "服务器返回了 HTML 页面而不是 artifact，可能尚未登录、"
                    "登录已过期，或服务地址配置错误。"
                ) from exc
            raise HttpClientError(exc.code, url, body) from exc
        finally:
            self._save_cookies()
        return BinaryResponse(content=raw, content_type=content_type)

    def capability_download(
        self,
        access: dict[str, Any],
        *,
        maximum_bytes: int = DEFAULT_BINARY_LIMIT,
        expected_sha256: str = "",
        content_type: str = "application/octet-stream",
    ) -> BinaryResponse:
        """Read 7997 bytes through a fresh transport with no session cookies."""

        # Lazy import keeps the small transport value types in this module
        # without creating an import cycle at module initialization time.
        from .capability_download import download_capability

        return download_capability(
            access,
            timeout=self.timeout,
            maximum_bytes=maximum_bytes,
            expected_sha256=expected_sha256,
            content_type=content_type,
        )

    def capability_download_to_path(
        self,
        access: dict[str, Any],
        destination: str | Path,
        *,
        expected_sha256: str,
        content_type: str = "application/octet-stream",
    ) -> dict[str, Any]:
        """Stream 7997 bytes to an atomic file without Manager cookies."""

        from .capability_download import download_capability_to_path

        return download_capability_to_path(
            access,
            destination,
            timeout=self._stream_timeout(),
            expected_sha256=expected_sha256,
            content_type=content_type,
        )

    def stream_request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ):
        url = self._url(path)
        if query:
            url = self._url(path, query=query)
        body = None
        headers = {
            "Accept": "text/event-stream",
            "User-Agent": "FactorTester-CLI/1",
            "X-FactorTester-Client": "cli",
        }
        headers = self._headers(headers)
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(
            url,
            data=body,
            headers=headers,
            method=method.upper(),
        )
        try:
            with self._opener.open(request, timeout=self._stream_timeout()) as response:
                event_name = "message"
                data_lines: list[str] = []
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
                    if not line:
                        if data_lines:
                            yield _parse_sse_event(event_name, data_lines)
                            event_name = "message"
                            data_lines = []
                        continue
                    if line.startswith("event:"):
                        event_name = line.split(":", 1)[1].strip() or "message"
                    elif line.startswith("data:"):
                        data_lines.append(line.split(":", 1)[1].lstrip())
                if data_lines:
                    yield _parse_sse_event(event_name, data_lines)
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            if _looks_like_html(raw):
                raise ValueError(
                    "服务器返回了 HTML 页面而不是 JSON，可能尚未登录、登录已过期，"
                    "或服务地址配置到了网页入口；请先运行 factortester login。"
                ) from exc
            raise HttpClientError(exc.code, url, raw) from exc
        finally:
            self._save_cookies()

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = self._url(path, query=query)
        body = None
        headers = {
            "Accept": "application/json",
            "User-Agent": "FactorTester-CLI/1",
            "X-FactorTester-Client": "cli",
        }
        if extra_headers:
            if any(key.lower() != "idempotency-key" for key in extra_headers):
                raise ValueError("Only Idempotency-Key may be supplied as an extra header")
            headers.update(extra_headers)
        headers = self._headers(headers)
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=body, headers=headers, method=method.upper())
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            if _looks_like_html(raw):
                raise ValueError(
                    "服务器返回了 HTML 页面而不是 JSON，可能尚未登录、登录已过期，"
                    "或服务地址配置到了网页入口；请先运行 factortester login。"
                ) from exc
            raise HttpClientError(exc.code, url, raw) from exc
        finally:
            self._save_cookies()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            if _looks_like_html(raw):
                raise ValueError(
                    "服务器返回了 HTML 页面而不是 JSON，可能尚未登录、登录已过期，"
                    "或服务地址配置到了网页入口；请先运行 factortester login。"
                ) from exc
            raise ValueError("服务器没有返回合法 JSON。") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"服务器 JSON 顶层不是对象: {type(parsed).__name__}")
        return parsed

    def _url(self, path: str, *, query: dict[str, Any] | None = None) -> str:
        if path.startswith(("http://", "https://")):
            base = path
        else:
            base = urljoin(f"{self.base_url}/", path.lstrip("/"))
        if not query:
            return base
        from urllib.parse import urlencode

        return f"{base}?{urlencode({k: v for k, v in query.items() if v is not None}, doseq=True)}"

    def _save_cookies(self) -> None:
        if not self.persist_cookies:
            return
        cookie_file = Path(self.cookie_jar.filename)
        try:
            cookie_file.parent.mkdir(parents=True, exist_ok=True)
            self.cookie_jar.save(ignore_discard=True, ignore_expires=True)
        except OSError:
            # A successful HTTP response must never be lost merely because
            # optional local session persistence is unavailable.  The next
            # request can still use the in-memory jar and bearer capability.
            return

    def _headers(self, headers: dict[str, str]) -> dict[str, str]:
        """Add the Profile capability without changing ordinary CLI cookies."""
        result = dict(headers)
        if self.bearer_token:
            result["Authorization"] = f"Bearer {self.bearer_token}"
        if self.agent_capability is not None:
            result["X-FactorTester-Agent"] = "profile"
            result["X-FactorTester-Agent-Profile"] = self.agent_capability.profile_id
            result["X-FactorTester-Agent-Claim"] = self.agent_capability.claim_id
        return result

    def clear_cookies(self) -> None:
        """Remove the persisted authenticated session from this client."""
        self.cookie_jar.clear()
        self._save_cookies()

    def import_cookies(self, values: list[dict[str, Any]]) -> None:
        self.cookie_jar.clear()
        for value in values:
            domain = str(value.get("domain") or "").strip()
            name = str(value.get("name") or "").strip()
            if not domain or not name:
                raise ValueError("cookie domain and name are required")
            path = str(value.get("path") or "/")
            self.cookie_jar.set_cookie(Cookie(
                version=0,
                name=name,
                value=str(value.get("value") or ""),
                port=None,
                port_specified=False,
                domain=domain,
                domain_specified=True,
                domain_initial_dot=domain.startswith("."),
                path=path,
                path_specified=True,
                secure=bool(value.get("secure")),
                expires=(
                    int(value["expires"])
                    if value.get("expires") is not None else None
                ),
                discard=value.get("expires") is None,
                comment=None,
                comment_url=None,
                rest={},
                rfc2109=False,
            ))
        self._save_cookies()

    def _stream_timeout(self) -> float:
        raw = os.environ.get(STREAM_TIMEOUT_ENV)
        if raw:
            try:
                return max(float(raw), self.timeout)
            except ValueError:
                return DEFAULT_STREAM_TIMEOUT
        return max(DEFAULT_STREAM_TIMEOUT, self.timeout)


def _looks_like_html(raw: str) -> bool:
    text = raw.lstrip().lower()
    return text.startswith("<!doctype html") or text.startswith("<html")


def _parse_sse_event(event_name: str, data_lines: list[str]) -> dict[str, Any]:
    raw_data = "\n".join(data_lines)
    try:
        data: Any = json.loads(raw_data)
    except json.JSONDecodeError:
        data = raw_data
    return {"event": event_name, "data": data}
