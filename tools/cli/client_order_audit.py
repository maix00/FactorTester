"""Retained order-audit artifact client."""

from __future__ import annotations

import json
from typing import Any

from .client_base import ClientMixinBase


class OrderAuditClientMixin(ClientMixinBase):
    def job_order_audit(self, job_id: str) -> dict[str, Any]:
        response = self.job_artifact(job_id, "order_audit")
        if response.content_type != "application/json":
            raise ValueError("order_audit artifact is not JSON")
        value = json.loads(response.content.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("order_audit artifact root must be an object")
        return value
