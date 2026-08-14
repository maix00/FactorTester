"""Runtime ports between IC core results and auxiliary-analysis adapters."""

from __future__ import annotations

from typing import Any, Mapping, Protocol


class ICAnalysisRuntimeAdapter(Protocol):
    analysis_type: str
    input_kinds: tuple[str, ...]
    output_kind: str

    def execute(
        self,
        inputs: tuple[Mapping[str, Any], ...],
        parameters: Mapping[str, Any],
    ) -> Any: ...


class ICAnalysisResultStore:
    """Typed runtime values keyed by producing graph ref and output kind."""

    def __init__(self) -> None:
        self._values: dict[tuple[str, str], Any] = {}

    def publish(self, producer_ref: str, output_kind: str, value: Any) -> None:
        key = (_text(producer_ref, "producer_ref"), _text(output_kind, "output_kind"))
        if key in self._values:
            raise ValueError(
                f"output kind {key[1]} is already published for {key[0]}"
            )
        self._values[key] = value

    def contains(self, producer_ref: str, output_kind: str) -> bool:
        return (producer_ref, output_kind) in self._values

    def require(self, producer_ref: str, output_kind: str) -> Any:
        key = (producer_ref, output_kind)
        if key not in self._values:
            raise ValueError(
                f"analysis target {producer_ref} requires output kind {output_kind}"
            )
        return self._values[key]


def _text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must be non-empty text")
    return text


__all__ = ["ICAnalysisResultStore", "ICAnalysisRuntimeAdapter"]
