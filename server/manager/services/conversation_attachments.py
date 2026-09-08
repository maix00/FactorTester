"""Attachment references travel in the Provider's canonical user message.

Files stay in the Profile workspace; no second transcript store is introduced.
The UI removes this machine-readable suffix and renders its file references.
"""
from __future__ import annotations
import json
import re

START = "\n\n<factortester-attachments>\n"
END = "\n</factortester-attachments>"
PATH = re.compile(r"^uploads/\d{4}-\d{2}-\d{2}/[a-f0-9]{32}/[^/\\]+$")


def split_attachments(text: str) -> tuple[str, list[dict]]:
    if START not in text or not text.endswith(END):
        return text, []
    body, encoded = text.rsplit(START, 1)
    try:
        entries = json.loads(encoded[:-len(END)])
        if not isinstance(entries, list) or len(entries) > 10:
            return text, []
        result = []
        for entry in entries:
            path = str(entry.get("workspacePath") or "")
            if not PATH.fullmatch(path) or path.rsplit("/", 1)[-1] in {".", ".."}:
                return text, []
            result.append({"id": path, "fileId": path, "workspacePath": path,
                "originalName": path.rsplit("/", 1)[-1],
                "mimeType": str(entry.get("mimeType") or "application/octet-stream"),
                "sha256": str(entry.get("sha256") or ""),
                "size": max(0, int(entry.get("size") or 0))})
        return body, result
    except (ValueError, TypeError, AttributeError):
        return text, []
