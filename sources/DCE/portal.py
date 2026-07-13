"""DCE official portal access.

DCE's public data endpoints are protected by a browser challenge.  FieldHistory
already treats DCE as a special case: callers must enter through the portal and
issue API calls from a real browser context, not with naked ``requests`` or an
AKShare wrapper around the same URL.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd


_BASE_URL = "http://www.dce.com.cn"
_PORTAL_URL = f"{_BASE_URL}/frontend/dcereport/#/zh/contractinfo"
_DEFAULT_TIMEOUT_SECONDS = 12.0
_PROFILE_ENV = "GTHT_DCE_PORTAL_PROFILE"
_HEADLESS_ENV = "GTHT_DCE_PORTAL_HEADLESS"
_CHANNEL_ENV = "GTHT_DCE_PORTAL_CHANNEL"


class DcePortalError(RuntimeError):
    """Raised when the DCE portal cannot return the requested data."""


def fetch_contract_info(*, timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS) -> pd.DataFrame:
    """Fetch current DCE futures contract lifecycle through the official portal.

    Returns an AKShare-compatible frame with Chinese column names consumed by
    ``sources.ContractLifecycle.lifecycle.normalize_dce``.  The source provenance is
    carried in ``DataFrame.attrs["source_function"]``.
    """

    payload = {"varietyId": "all", "tradeType": "1", "lang": "zh"}
    data = _post_publicweb("/dcereport/publicweb/tradepara/contractInfo", payload, timeout_seconds=timeout_seconds)
    frame = _contract_info_frame(data)
    frame.attrs["source_function"] = "official_dce_portal_contract_info"
    return frame


def fetch_new_contract_info(
    trade_date: str,
    *,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> pd.DataFrame:
    """Fetch DCE official "期货/期权合约增挂" rows for one YYYYMMDD date."""

    payload = {"tradeDate": str(trade_date), "tradeType": "1", "lang": "zh"}
    data = _post_publicweb(
        "/dcereport/publicweb/tradepara/newContractInfo",
        payload,
        timeout_seconds=timeout_seconds,
    )
    frame = pd.DataFrame(data)
    if not frame.empty:
        frame = frame.rename(columns={
            "contractId": "合约",
            "variety": "品种名称",
            "varietyOrder": "品种代码",
            "startTradeDate": "开始交易日",
            "refPriceUnit": "挂牌基准价单位",
            "noRiseLimit": "涨停板幅度",
            "noFallLimit": "跌停板幅度",
        })
        for column in ("开始交易日",):
            frame[column] = pd.to_datetime(frame[column], format="%Y%m%d", errors="coerce").dt.date
    frame.attrs["source_function"] = "official_dce_portal_new_contract_info"
    frame.attrs["source_query_date"] = str(trade_date)
    return frame


def _post_publicweb(endpoint: str, payload: dict[str, Any], *, timeout_seconds: float) -> list[dict[str, Any]]:
    response = _browser_post_json(endpoint, payload, timeout_seconds=timeout_seconds)
    if not response.get("ok"):
        raise DcePortalError(
            f"DCE portal request failed status={response.get('status')} endpoint={endpoint}: "
            f"{str(response.get('text') or '')[:240]}"
        )
    body = response.get("data")
    if not isinstance(body, dict):
        raise DcePortalError(f"DCE portal response was not JSON object for endpoint={endpoint}")
    if body.get("success") is False:
        raise DcePortalError(f"DCE portal rejected endpoint={endpoint}: {body.get('msg') or body.get('code')}")
    data = body.get("data")
    if data is None:
        return []
    if not isinstance(data, list):
        raise DcePortalError(f"DCE portal data was not a list for endpoint={endpoint}")
    return [row for row in data if isinstance(row, dict)]


def _browser_post_json(endpoint: str, payload: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    profile = Path(os.environ.get(_PROFILE_ENV) or "/tmp/gtht-dce-portal-profile").expanduser()
    profile.mkdir(parents=True, exist_ok=True)
    headless = _env_bool(_HEADLESS_ENV, default=False)
    channel = os.environ.get(_CHANNEL_ENV) or "chrome"
    timeout_ms = max(1, int(timeout_seconds * 1000))
    script = """
    async ({url, payload, timeoutMs}) => {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      try {
        const response = await fetch(url, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(payload),
          signal: controller.signal,
        });
        const text = await response.text();
        let data = null;
        try { data = JSON.parse(text); } catch (error) {}
        return {ok: response.ok, status: response.status, url: response.url, text, data};
      } finally {
        clearTimeout(timer);
      }
    }
    """
    with sync_playwright() as playwright:
        try:
            context = playwright.chromium.launch_persistent_context(
                str(profile),
                headless=headless,
                channel=channel,
                args=["--disable-blink-features=AutomationControlled"],
            )
        except Exception:
            context = playwright.chromium.launch_persistent_context(
                str(profile),
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
        try:
            page = context.new_page()
            page.set_default_timeout(timeout_ms)
            try:
                page.goto(_PORTAL_URL, wait_until="domcontentloaded", timeout=timeout_ms)
            except Exception:
                # A 412 challenge document can still leave the browser context
                # with the cookies/tokens needed for same-origin fetches.
                pass
            page.wait_for_timeout(min(3000, max(250, timeout_ms // 4)))
            return page.evaluate(
                script,
                {"url": endpoint, "payload": payload, "timeoutMs": timeout_ms},
            )
        finally:
            context.close()


def _contract_info_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=["品种名称", "品种代码", "合约", "交易单位", "最小变动价位", "开始交易日", "最后交易日", "最后交割日"])
    frame = frame.rename(columns={
        "contractId": "合约",
        "variety": "品种名称",
        "varietyOrder": "品种代码",
        "unit": "交易单位",
        "tick": "最小变动价位",
        "startTradeDate": "开始交易日",
        "endTradeDate": "最后交易日",
        "endDeliveryDate": "最后交割日",
    })
    preferred = ["品种名称", "品种代码", "合约", "交易单位", "最小变动价位", "开始交易日", "最后交易日", "最后交割日"]
    for column in preferred:
        if column not in frame.columns:
            frame[column] = None
    frame = frame[preferred]
    frame["交易单位"] = pd.to_numeric(frame["交易单位"], errors="coerce")
    frame["最小变动价位"] = pd.to_numeric(frame["最小变动价位"], errors="coerce")
    for column in ("开始交易日", "最后交易日", "最后交割日"):
        frame[column] = pd.to_datetime(frame[column], format="%Y%m%d", errors="coerce").dt.date
    return frame


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
