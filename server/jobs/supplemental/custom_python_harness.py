"""Trusted child-process harness. Executed only inside an OS sandbox."""

from __future__ import annotations

import json
import math
import statistics
import sys


class _Artifacts:
    def __init__(self, paths, limit):
        self._paths = dict(paths)
        self._limit = int(limit)

    def list(self):
        return sorted(self._paths)

    def path(self, name):
        self._require(name)
        return f"/artifacts/{name}"

    def load_bytes(self, name):
        path = self._require(name)
        with open(path, "rb") as stream:
            value = stream.read(self._limit + 1)
        if len(value) > self._limit:
            raise ValueError(f"artifact is too large: {name}")
        return value

    def load_text(self, name, encoding="utf-8"):
        return self.load_bytes(name).decode(encoding)

    def load_json(self, name):
        return json.loads(self.load_bytes(name))

    def _require(self, name):
        key = str(name)
        if key not in self._paths:
            raise KeyError(f"artifact was not found: {key}")
        return self._paths[key]


def _main():
    payload = json.load(sys.stdin)
    logs = []

    def safe_print(*values, sep=" ", end="\n"):
        if len(logs) < 200:
            logs.append(sep.join(str(value) for value in values) + end.rstrip("\n"))

    safe_builtins = {
        "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
        "enumerate": enumerate, "Exception": Exception, "filter": filter,
        "float": float, "int": int, "isinstance": isinstance, "len": len,
        "list": list, "map": map, "max": max, "min": min, "print": safe_print,
        "range": range, "reversed": reversed, "round": round, "set": set,
        "sorted": sorted, "str": str, "sum": sum, "tuple": tuple,
        "ValueError": ValueError, "zip": zip,
    }
    namespace = {
        "__builtins__": safe_builtins,
        "artifacts": _Artifacts(
            payload.get("artifacts") or {}, payload.get("max_artifact_bytes") or 0,
        ),
        "json": json, "math": math, "statistics": statistics,
    }
    try:
        exec(compile(payload["source"], "custom_analysis.py", "exec"), namespace)
        result = namespace.get("result")
        json.dumps(result, allow_nan=False)
        output = {"success": True, "result": result, "logs": logs}
    except BaseException as exc:
        output = {"success": False, "error": f"{type(exc).__name__}: {exc}"}
    sys.stdout.write(json.dumps(output, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    _main()
