"""Authenticated Manager summaries for the local 7997 transfer plane."""

from __future__ import annotations

import time
import sqlite3
from urllib.parse import parse_qs

from server.manager.http.responses import json_response


_METRICS_PATH = "/api/transfers/metrics"
_DEFAULT_WINDOW_SECONDS = 24 * 60 * 60
_MIN_WINDOW_SECONDS = 60
_MAX_WINDOW_SECONDS = 7 * 24 * 60 * 60


class TransferMetricsRoutesMixin:
    """Expose bounded, local transfer telemetry to server administrators."""

    def _get_transfer_metrics(self, parsed) -> bool:
        if parsed.path != _METRICS_PATH:
            return False
        if not self._require_super_admin_session():
            return True
        query = parse_qs(parsed.query, keep_blank_values=True)
        try:
            window = _window_seconds(query.get("window_seconds", [""])[0])
            object_kind = _query_value(query, "object_kind")
            operation = _query_value(query, "operation")
            now = time.time()
            metrics = self.state.transfer_telemetry.summary(
                object_kind=object_kind,
                operation=operation,
                since=now - window,
                until=now,
                now=now,
            )
        except ValueError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return True
        except (OSError, RuntimeError, sqlite3.Error) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 503)
            return True
        json_response(
            self,
            {"success": True, "metrics": metrics},
            headers={"Cache-Control": "no-store"},
        )
        return True


def _window_seconds(value: object) -> float:
    raw = str(value or "").strip()
    if not raw:
        return float(_DEFAULT_WINDOW_SECONDS)
    try:
        selected = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("window_seconds must be a number") from exc
    if not _MIN_WINDOW_SECONDS <= selected <= _MAX_WINDOW_SECONDS:
        raise ValueError(
            f"window_seconds must be between {_MIN_WINDOW_SECONDS} and "
            f"{_MAX_WINDOW_SECONDS}"
        )
    return selected


def _query_value(query: dict[str, list[str]], name: str) -> str:
    value = str(query.get(name, [""])[0] or "").strip()
    if len(value) > 128:
        raise ValueError(f"{name} must be at most 128 characters")
    return value


__all__ = ["TransferMetricsRoutesMixin"]
