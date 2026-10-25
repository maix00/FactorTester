"""Artifact/progress sink used by Celery executors."""

from __future__ import annotations

import gc
import hashlib
import importlib
import multiprocessing
import os
import queue
import resource
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from server.jobs.equity_curve_artifact import receipt_bytes
from server.jobs.json_artifact_writer import (
    write_json_artifact,
    write_json_mapping_artifact,
)
from server.jobs.report_outputs import (
    OUTPUT_DEFINITIONS,
    build_report_artifacts,
    bundle_reports,
    default_output_requests,
    normalize_output_requests,
    source_artifacts_for,
)
from server.jobs.result_projection import (
    _bounded_summary,
    persisted_result_summary,  # noqa: F401 - scheduling compatibility export
)


class WorkerUnavailable(RuntimeError):
    pass


_EXECUTION_PROGRESS_SHARE = 85.0
_REPORT_BUILD_PROGRESS_SHARE = 10.0
_ARTIFACT_PUBLISH_PROGRESS_SHARE = 5.0
_ARTIFACT_PUBLISH_PROGRESS_START = (
    _EXECUTION_PROGRESS_SHARE + _REPORT_BUILD_PROGRESS_SHARE
)
_PROGRESS_PHASE_WEIGHTS = {
    "pre_replay": 5.0,
    "event_replay": 75.0,
    # Native post-replay work owns the first 5%; result derivation and
    # artifact publication continue in this same semantic phase for 15%.
    "post_replay": 20.0,
}
_OUTPUT_PROGRESS_FLOWS = (
    {
        "flow_key": "build_requested_outputs",
        "flow_label": "构建所选结果",
        "display_order": 10_000,
    },
    {
        "flow_key": "publish_artifacts",
        "flow_label": "写入并登记生成物",
        "display_order": 10_001,
    },
)


class _CancelFlag:
    def __init__(self, value: Any) -> None:
        self._value = value

    def is_set(self) -> bool:
        return bool(self._value.value)


class _WorkerSink:
    def __init__(
        self,
        job_id: str,
        output_queue: Any,
        *,
        artifact_job_id: str = "",
        artifact_root: str = "",
        retention_mode: str = "summary",
        output_requests: list[str] | tuple[str, ...] = (),
        control_queue: Any = None,
        cancel_event: Any = None,
    ) -> None:
        self.job_id = str(job_id)
        self.artifact_job_id = str(artifact_job_id or job_id)
        self.output_queue = output_queue
        self.artifact_root = Path(artifact_root) if artifact_root else None
        self.retention_mode = str(retention_mode)
        self.output_requests = tuple(normalize_output_requests(list(output_requests)))
        self._source_artifacts = source_artifacts_for(self.output_requests)
        self._source_payloads: dict[str, Any] = {}
        self.control_queue = control_queue
        self.cancel_event = cancel_event
        self._live_event_interval = 0.5
        self._last_live_emit_at: dict[str, float] = {}
        self._pending_live_events: dict[str, dict[str, Any]] = {}

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        self.output_queue.put({
            "type": "event",
            "job_id": self.job_id,
            "event": str(event),
            "data": dict(data),
            "worker_pid": os.getpid(),
        })

    def _emit_live(self, event: str, data: dict[str, Any]) -> None:
        now = time.monotonic()
        last = self._last_live_emit_at.get(event)
        if last is not None and now - last < self._live_event_interval:
            self._pending_live_events[event] = dict(data)
            return
        self._pending_live_events.pop(event, None)
        self._last_live_emit_at[event] = now
        self._emit(event, data)

    def wants_live_event(self, event: str) -> bool:
        """Return whether constructing a new live payload is useful now."""
        last = self._last_live_emit_at.get(str(event))
        return last is None or time.monotonic() - last >= self._live_event_interval

    def _flush_live_events(self) -> None:
        pending = self._pending_live_events
        self._pending_live_events = {}
        # Activity explains the current work; numeric progress is the final
        # snapshot consumed after reconnect. Preserve both while ensuring the
        # broker's latest_progress points at the measurable event.
        priority = {"activity": 0, "signal_progress": 1, "progress": 2}
        for event, data in sorted(
            pending.items(), key=lambda item: priority.get(item[0], 1),
        ):
            self._last_live_emit_at[event] = time.monotonic()
            self._emit(event, data)

    def emit_start(self, *, total: int, groups: int, phase: str = "init", phases=None, **extra) -> None:
        data: dict[str, Any] = {"total": total, "groups": groups, "phase": phase}
        if phases:
            data["phases"] = phases
        data.update(extra)
        self._emit("start", data)

    def emit_progress(self, completed: int, total: int, phase: str = "eval", **extra) -> None:
        self._emit_live("progress", {
            "completed": completed,
            "total": total,
            "phase": phase,
            **extra,
        })

    def emit_activity_manifest(self, phases: list[dict[str, Any]]) -> None:
        declared: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in phases:
            phase = dict(raw)
            key = str(phase.get("key") or phase.get("phase") or "").strip()
            if not key or key in seen:
                continue
            phase["key"] = key
            phase.setdefault("weight", _PROGRESS_PHASE_WEIGHTS.get(key, 1.0))
            declared.append(phase)
            seen.add(key)
        post_replay = next(
            (phase for phase in declared if phase["key"] == "post_replay"),
            None,
        )
        if post_replay is None:
            post_replay = {
                "key": "post_replay",
                "label": "结果整理",
                "weight": _PROGRESS_PHASE_WEIGHTS["post_replay"],
                "flows": [],
            }
            declared.append(post_replay)
        post_replay["weight"] = _PROGRESS_PHASE_WEIGHTS["post_replay"]
        flows = list(post_replay.get("flows") or [])
        flow_keys = {
            str(item.get("flow_key") or item.get("key") or "")
            for item in flows
        }
        flows.extend(
            dict(item) for item in _OUTPUT_PROGRESS_FLOWS
            if item["flow_key"] not in flow_keys
        )
        post_replay["flows"] = flows
        self._emit("activity_manifest", {"phases": declared})

    def emit_activity(self, **payload: Any) -> None:
        self._emit_live("activity", payload)

    def emit_signal_progress(
        self,
        *,
        completed: int,
        total: int,
        phase: str = "event_replay",
        percent: float | None = None,
    ) -> None:
        percent_scope = "phase"
        if percent is None:
            percent = 100.0 if total <= 0 else completed / total * 100.0
        else:
            # Native execution percentages describe the complete replay. The
            # worker still has to derive, encode, write, and register requested
            # outputs, so execution owns only the leading progress segment.
            percent = float(percent) * _EXECUTION_PROGRESS_SHARE / 100.0
            percent_scope = "global"
        self._emit_live("signal_progress", {
            "completed": completed,
            "total": total,
            "phase": phase,
            "percent": max(0.0, min(100.0, float(percent))),
            "percent_scope": percent_scope,
        })

    def emit_runtime_info(
        self,
        message: str,
        *,
        level: str = "info",
        code: str = "",
        details: dict[str, Any] | None = None,
        **extra,
    ) -> None:
        data: dict[str, Any] = {
            "message": message,
            "level": level,
            "code": code,
            **extra,
        }
        if details is not None:
            data["details"] = details
        self._emit("runtime_info", data)

    def emit_result(self, data: dict[str, Any], *, source: dict[str, Any] | None = None) -> None:
        # Keep the legacy equity report automatic, while allowing a RunSpec to
        # request additional reports without retaining the complete result.
        implicit_default = not self.output_requests
        implicit_ic = implicit_default and any(
            isinstance(item, dict)
            and (
                item.get("ic_series_by_forward_horizon")
                or item.get("ic_series")
            )
            for item in (data.get("factors") or ())
        )
        requested = list(self.output_requests) or (
            default_output_requests(["ic"])
            if implicit_ic else ["equity_curve"]
        )
        merged_source = dict(self._source_payloads)
        merged_source.update(source or {})
        self.emit_activity(
            phase="post_replay",
            phase_label="结果整理",
            flow_key="build_requested_outputs",
            flow_label="构建所选结果",
            message=f"正在派生并编码 {len(requested)} 项所选结果",
        )

        def report_progress(completed: int, total: int, name: str) -> None:
            label = str(OUTPUT_DEFINITIONS.get(name, {}).get("label") or name)
            self.emit_activity(
                phase="post_replay",
                phase_label="结果整理",
                flow_key="build_requested_outputs",
                flow_label="构建所选结果",
                message=f"已构建 {label}",
            )
            percent = (
                _EXECUTION_PROGRESS_SHARE
                + completed / max(1, total) * _REPORT_BUILD_PROGRESS_SHARE
            )
            self.emit_progress(
                completed, max(1, total), "post_replay",
                percent=percent, percent_scope="global",
                message=f"已构建 {completed}/{total} 项结果：{label}",
            )

        reports = build_report_artifacts(
            data,
            source=merged_source,
            requested=requested,
            job_id=self.job_id,
            progress=report_progress,
        )
        has_equity_curve = any(report.name == "equity_curve_report" for report in reports)
        retain_result = self.retention_mode == "full" or "result" in self._source_artifacts
        bundles = bundle_reports(reports)
        publish_total = len(reports) + len(bundles) + int(retain_result)
        self.emit_activity(
            phase="post_replay",
            phase_label="结果整理",
            flow_key="publish_artifacts",
            flow_label="写入并登记生成物",
            message=f"正在写入并登记 {publish_total} 项生成物",
        )
        published = 0
        for report in reports:
            self._write_bytes_artifact(
                report.name,
                report.raw,
                extension=report.extension,
                content_type=report.content_type,
            )
            published += 1
            self.emit_progress(
                published, max(1, publish_total), "post_replay",
                percent=(
                    _ARTIFACT_PUBLISH_PROGRESS_START
                    + published / max(1, publish_total)
                    * _ARTIFACT_PUBLISH_PROGRESS_SHARE
                ),
                percent_scope="global",
                message=f"已登记 {published}/{publish_total} 项生成物",
            )
        for bundle in bundles:
            self._write_bytes_artifact(
                bundle.receipt_name,
                receipt_bytes(bundle.receipt),
                extension="json",
                content_type="application/json",
            )
            published += 1
            self.emit_progress(
                published, max(1, publish_total), "post_replay",
                percent=(
                    _ARTIFACT_PUBLISH_PROGRESS_START
                    + published / max(1, publish_total)
                    * _ARTIFACT_PUBLISH_PROGRESS_SHARE
                ),
                percent_scope="global",
                message=f"已登记 {published}/{publish_total} 项生成物",
            )
        if retain_result:
            self._write_artifact("result", data)
            published += 1
            self.emit_progress(
                published, max(1, publish_total), "post_replay",
                percent=(
                    _ARTIFACT_PUBLISH_PROGRESS_START
                    + published / max(1, publish_total)
                    * _ARTIFACT_PUBLISH_PROGRESS_SHARE
                ),
                percent_scope="global",
                message=f"已登记 {published}/{publish_total} 项生成物",
            )
        if publish_total == 0:
            self.emit_progress(
                1, 1, "post_replay", percent=100.0, percent_scope="global",
                message="无需生成额外文件",
            )
        self._flush_live_events()
        summary = _bounded_summary(data)
        if has_equity_curve:
            summary["equity_curve_artifact_available"] = True
        self._emit("result", summary)

    def emit_plan(self, data: dict[str, Any]) -> None:
        """Return a planning result without invoking execution artifact builders."""
        self._flush_live_events()
        self._emit("result", _bounded_summary(data))

    def emit_error(self, error: str, traceback: str = "", **extra) -> None:
        self._flush_live_events()
        code = str(extra.pop("code", "") or "job_execution_failed")
        self._emit("error", {
            "success": False,
            "code": code,
            "message": error,
            "error": error,
            "traceback": traceback,
            **extra,
        })

    def emit_step(self, step_info: dict[str, Any]) -> None:
        self._emit("step", dict(step_info))

    def emit_artifact(self, name: str, value: Any) -> None:
        if self.retention_mode == "full" or str(name) in self._source_artifacts:
            if str(name) in self._source_artifacts:
                self._source_payloads[str(name)] = value
            self._write_artifact(str(name), value)

    def emit_core_artifact(self, name: str, value: Any) -> None:
        """Persist a bounded Job result index independent of optional outputs.

        Core artifacts back the standard Job result UI.  They are not an
        opt-in report and must remain available under summary retention, while
        large execution traces continue to obey ``output_requests``.
        """
        self._write_artifact(str(name), value)

    def emit_core_artifact_at(
        self, name: str, value: Any, *, relative_path: str,
    ) -> None:
        """Persist a core JSON artifact at one validated Job-relative path."""
        self._write_artifact_at(str(name), value, relative_path=relative_path)

    def emit_bytes_artifact(
        self,
        name: str,
        raw: bytes,
        *,
        extension: str,
        content_type: str,
    ) -> None:
        """Persist one trusted derived output under the Job artifact owner."""
        self._write_bytes_artifact(
            str(name), bytes(raw), extension=str(extension),
            content_type=str(content_type),
        )

    def emit_mapping_artifact(
        self,
        name: str,
        *,
        fields: dict[str, Any],
        mapping_name: str,
        items: Any,
    ) -> None:
        name = str(name)
        if not self.should_retain_artifact(name):
            return
        if name in self._source_artifacts:
            value = {**fields, str(mapping_name): dict(items)}
            self._source_payloads[name] = value
            self._write_artifact(name, value)
            return
        if self.artifact_root is None:
            raise RuntimeError("artifact root is required for full retention")
        safe_name = "".join(
            ch if ch.isalnum() or ch in "-_" else "-"
            for ch in name
        )
        target = self.artifact_root / self.artifact_job_id / f"{safe_name}.json"
        receipt = write_json_mapping_artifact(
            target,
            fields=fields,
            mapping_name=str(mapping_name),
            items=items,
        )
        self._emit("artifact", {
            "name": name,
            "relative_path": f"{self.artifact_job_id}/{target.name}",
            "content_type": "application/json",
            "content_hash": receipt.content_hash,
            "size_bytes": receipt.size_bytes,
        })

    def should_retain_artifact(self, name: str) -> bool:
        return self.retention_mode == "full" or str(name) in self._source_artifacts

    def emit_pause(self, checkpoint: dict[str, Any]) -> dict[str, Any]:
        self._flush_live_events()
        self._emit("paused", {"checkpoint": dict(checkpoint)})
        if self.control_queue is None:
            return {"action": "cancel"}
        while True:
            if self.cancel_event is not None and self.cancel_event.is_set():
                return {"action": "cancel"}
            try:
                command = self.control_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if isinstance(command, dict) and command.get("type") == "step_control":
                return dict(command.get("command") or {})

    def _write_artifact(self, name: str, value: Any) -> None:
        if self.artifact_root is None:
            raise RuntimeError("artifact root is required for full retention")
        safe_name = "".join(
            ch if ch.isalnum() or ch in "-_" else "-"
            for ch in name
        )
        directory = self.artifact_root / self.artifact_job_id
        target = directory / f"{safe_name}.json"
        receipt = write_json_artifact(target, value)
        self._emit("artifact", {
            "name": name,
            "relative_path": f"{self.artifact_job_id}/{target.name}",
            "content_type": "application/json",
            "content_hash": receipt.content_hash,
            "size_bytes": receipt.size_bytes,
        })

    def _write_artifact_at(
        self, name: str, value: Any, *, relative_path: str,
    ) -> None:
        if self.artifact_root is None:
            raise RuntimeError("artifact root is required for full retention")
        relative = Path(str(relative_path))
        if (
            relative.is_absolute() or not relative.parts
            or any(part in {"", ".", ".."} for part in relative.parts)
            or relative.suffix.lower() != ".json"
        ):
            raise ValueError("artifact relative path must be a safe JSON path")
        directory = (self.artifact_root / self.artifact_job_id).resolve()
        target = (directory / relative).resolve()
        if directory not in target.parents:
            raise ValueError("artifact relative path escapes the Job directory")
        receipt = write_json_artifact(target, value)
        self._emit("artifact", {
            "name": name,
            "relative_path": f"{self.artifact_job_id}/{relative.as_posix()}",
            "content_type": "application/json",
            "content_hash": receipt.content_hash,
            "size_bytes": receipt.size_bytes,
        })

    def _write_bytes_artifact(
        self,
        name: str,
        raw: bytes,
        *,
        extension: str,
        content_type: str,
    ) -> None:
        if self.artifact_root is None:
            raise RuntimeError("artifact root is required")
        safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name)
        directory = self.artifact_root / self.artifact_job_id
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{safe_name}.{extension}"
        staging = directory / f".{safe_name}.{os.getpid()}.tmp"
        staging.write_bytes(raw)
        staging.replace(target)
        self._emit("artifact", {
            "name": name,
            "relative_path": f"{self.artifact_job_id}/{target.name}",
            "content_type": content_type,
            "content_hash": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
        })



def env_positive_int(name: str, default: int) -> int:
    """Read a positive integer budget from the environment.

    Invalid or non-positive values fall back to the default so a typo cannot
    silently disable a memory boundary.
    """
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


