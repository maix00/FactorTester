"""Isolated, read-only subprocess adapter for Tiger market-data probes."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from tools.data.availability.schema import availability_dimensions


PYTHON_ENV = "FACTORTESTER_TIGER_PYTHON"
PROPS_ENV = "FACTORTESTER_TIGEROPEN_PROPS_PATH"
SDK_PROPS_ENV = "TIGEROPEN_PROPS_PATH"
OSE_L2_PERMISSION = "OSEFuturesQuoteLv2"


class TigerConnectorError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class TigerConnectorConfig:
    python_path: str
    props_path: str
    bridge_path: str
    timeout_seconds: float = 15.0

    @classmethod
    def from_env(cls) -> "TigerConnectorConfig":
        return cls(
            python_path=os.environ.get(PYTHON_ENV, "").strip(),
            props_path=(
                os.environ.get(PROPS_ENV)
                or os.environ.get(SDK_PROPS_ENV)
                or ""
            ).strip(),
            bridge_path=str(Path(__file__).with_name("bridge.py")),
            timeout_seconds=_timeout_from_env(),
        )

    def readiness_gaps(self) -> tuple[str, ...]:
        gaps = []
        if not _executable_file(self.python_path):
            gaps.append("runtime_not_configured")
        if not _readable_file(self.props_path):
            gaps.append("properties_not_configured")
        if not _readable_file(self.bridge_path):
            gaps.append("bridge_missing")
        return tuple(gaps)


class TigerConnector:
    key = "Tiger"

    def __init__(self, config: TigerConnectorConfig | None = None):
        self.config = config or TigerConnectorConfig.from_env()

    def inspect(
        self,
        products: Iterable[Any],
        *,
        probe: bool,
        expanded: bool,
    ) -> list[dict[str, Any]]:
        product_list = list(products)
        gaps = self.config.readiness_gaps()
        if not probe or gaps:
            status = "unavailable" if gaps else "not_probed"
            return [
                self._base_entry(product, status=status, gaps=gaps)
                for product in product_list
            ]

        request_products = [
            {
                "name": _product_name(product),
                "identifier": str(getattr(product, "tiger_identifier", "")),
            }
            for product in product_list
        ]
        try:
            payload = self._invoke({
                "operation": "availability",
                "products": request_products,
                "expanded": bool(expanded),
            })
        except TigerConnectorError as exc:
            return [
                {
                    **self._base_entry(product, status="unavailable"),
                    "connection": "failed",
                    "reason": exc.code,
                }
                for product in product_list
            ]
        return self._entries_from_probe(product_list, payload, expanded=expanded)

    def _invoke(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        env = os.environ.copy()
        env[SDK_PROPS_ENV] = self.config.props_path
        try:
            completed = subprocess.run(
                [self.config.python_path, self.config.bridge_path],
                input=json.dumps(request_payload, ensure_ascii=False),
                text=True,
                capture_output=True,
                timeout=self.config.timeout_seconds,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise TigerConnectorError("connector_timeout") from exc
        except OSError as exc:
            raise TigerConnectorError("connector_launch_failed") from exc
        if completed.returncode != 0:
            raise TigerConnectorError("connector_process_failed")
        try:
            payload = json.loads(completed.stdout)
        except (TypeError, json.JSONDecodeError) as exc:
            raise TigerConnectorError("connector_invalid_json") from exc
        if not isinstance(payload, dict) or payload.get("status") != "ok":
            raise TigerConnectorError("connector_probe_failed")
        return payload

    def _entries_from_probe(
        self,
        products: list[Any],
        payload: dict[str, Any],
        *,
        expanded: bool,
    ) -> list[dict[str, Any]]:
        permissions = payload.get("permissions") or []
        permission = next(
            (
                item for item in permissions
                if isinstance(item, dict) and item.get("name") == OSE_L2_PERMISSION
            ),
            None,
        )
        entitled = permission is not None
        quotes = {
            str(item.get("identifier")): item
            for item in (payload.get("quotes") or [])
            if isinstance(item, dict) and item.get("identifier")
        }
        received_at = _integer_or_none(payload.get("received_at_ms"))
        entries = []
        for product in products:
            identifier = str(getattr(product, "tiger_identifier", ""))
            quote = quotes.get(identifier)
            available = entitled and quote is not None
            entry = self._base_entry(
                product,
                status="available" if available else "unavailable",
            )
            entry.update({
                "connection": "reachable",
                "entitled_realtime": entitled,
                "latency_class": "unverified",
            })
            latest_time = _integer_or_none(
                quote.get("latest_time") if quote is not None else None
            )
            if latest_time is not None:
                entry["last_event_time"] = _millisecond_iso(latest_time)
            if latest_time is not None and received_at is not None:
                entry["observed_age_ms"] = max(received_at - latest_time, 0)
            if permission and permission.get("expire_at") not in (None, -1):
                entry["entitlement_expires_at"] = _millisecond_iso(
                    int(permission["expire_at"])
                )
            if not entitled:
                entry["reason"] = "ose_l2_entitlement_missing"
            elif quote is None:
                entry["reason"] = "product_quote_missing"
            if expanded:
                entry["provider_identifier"] = identifier
                entry["permission"] = OSE_L2_PERMISSION if entitled else None
            entries.append(entry)
        return entries

    def _base_entry(
        self,
        product: Any,
        *,
        status: str,
        gaps: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "product": _product_name(product),
            "source": self.key,
            "status": status,
            **availability_dimensions(
                sampling_mode="snapshot",
                frequency=None,
                data_kind="order_book",
                market_depth="l2",
                delivery_mode="live_stream",
            ),
            "connection": "not_probed",
            "entitled_realtime": None,
            "latency_class": "unverified",
            "replayable": False,
        }
        if gaps:
            entry["reason"] = ",".join(gaps)
        return entry


def _product_name(product: Any) -> str:
    return str(getattr(product, "name", getattr(product, "alias", product)))


def _integer_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _millisecond_iso(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()


def _executable_file(value: str) -> bool:
    return bool(value) and Path(value).is_file() and os.access(value, os.X_OK)


def _readable_file(value: str) -> bool:
    return bool(value) and Path(value).is_file() and os.access(value, os.R_OK)


def _timeout_from_env() -> float:
    try:
        return max(float(os.environ.get("FACTORTESTER_TIGER_TIMEOUT", "15")), 1.0)
    except ValueError:
        return 15.0
