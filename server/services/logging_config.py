"""Process-level logging configuration for server and backtest components."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path


_configure_lock = threading.Lock()
_configured = False


class JsonLineFormatter(logging.Formatter):
    _context_fields = (
        "run_id", "user_id", "page_uuid", "session_id", "tester_alias",
        "factor_alias", "strategy_id", "portfolio_id", "event_id",
        "causation_id", "event_topic", "event_sequence", "event_succeeded",
        "event_error_type", "product_count",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in self._context_fields:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(log_dir: str | Path, *, level: int = logging.INFO) -> None:
    """Configure the `factortester` hierarchy once for this process."""
    global _configured
    with _configure_lock:
        if _configured:
            return
        directory = Path(log_dir)
        directory.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger("factortester")
        logger.setLevel(level)
        logger.propagate = False

        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        ))
        file_handler = RotatingFileHandler(
            directory / "factortester.jsonl",
            maxBytes=20 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(JsonLineFormatter())
        logger.addHandler(console)
        logger.addHandler(file_handler)
        _configured = True
