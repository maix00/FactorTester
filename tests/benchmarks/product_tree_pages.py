"""Isolated metadata-only catalog benchmark; never connects to a Manager.

Run in GTHT: PYTHONPATH=. python tests/benchmarks/product_tree_pages.py
  --objects 100000 --sources 20 --overlap 90 --samples 20
All provider work is stubbed. Timings are not HTTP/browser/production p95.
Each invocation is an independent process to make peak RSS interpretable.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import platform
import resource
import statistics
import time
from types import SimpleNamespace

from server.services.product_tree_pages import ProductTreePages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--objects", type=int, default=100_000, choices=(1000, 10_000, 100_000))
    parser.add_argument("--sources", type=int, default=20, choices=(1, 5, 20))
    parser.add_argument("--overlap", type=int, default=90, choices=(0, 50, 90))
    parser.add_argument("--samples", type=int, default=20)
    args = parser.parse_args()
    if not 2 <= args.samples <= 100:
        parser.error("samples must be between 2 and 100")
    sources = tuple(f"node-{i % 3}/bundle-{i}/minute" for i in range(args.sources))
    objects = tuple(SimpleNamespace(ref=f"Product/Exchange/P{i:06d}", name=f"P{i:06d}")
                    for i in range(args.objects))
    index = ProductTreePages()
    calls = 0

    def project(item, path):
        nonlocal calls
        calls += 1
        number = int(item.name[1:])
        bindings = sources if number % 100 < args.overlap else (sources[number % args.sources],)
        return {"title": item.name, "product_name": item.name, "key": path,
                "product_path": path, "product_code": item.name,
                "source_ids": list(bindings), "source_family_ids": list(bindings),
                "desc": "测试产品", "description": "测试产品", "exchange": "TEST",
                "product_type": "product", "has_data": True, "lazy": False,
                "folder": False, "checkbox": False}

    def run(query):
        return index.page(scope=("local-manager", "principal", "revision"),
                          objects=objects, object_path=lambda p: p.ref,
                          project=project, query=query, page=2, limit=50)

    def timings(action):
        values = []
        for _ in range(args.samples):
            start = time.perf_counter()
            action()
            values.append((time.perf_counter() - start) * 1000)
        return {"samples": len(values), "median_ms": statistics.median(values),
                "p95_ms": sorted(values)[int(.95 * (len(values) - 1))]}

    # Reference baseline deliberately repeats the old full projection on every
    # search. Same projection, ordering and substring matching; no I/O is faked.
    def baseline():
        matches = []
        for item in sorted(objects, key=lambda p: p.name):
            row = project(item, item.ref)
            text = " ".join(str(row.get(key) or "") for key in (
                "title", "product_name", "product_code", "desc", "exchange",
                "product_path", "source_ids",
            )).casefold()
            if "bundle" in text:
                matches.append(row)
        return len(matches), [row["key"] for row in matches[50:100]]

    try:
        before = timings(baseline)
        calls = 0
        rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        start = time.perf_counter()
        first = run("bundle")
        cold_ms = (time.perf_counter() - start) * 1000
        cold_calls = calls
        warm_search = timings(lambda: run("bundle"))
        warm_page = timings(lambda: run(""))
        assert calls == cold_calls == args.objects
        assert first["total"] == args.objects
        assert [row["key"] for row in first["nodes"]] == [p.ref for p in objects[50:100]]
        db = index._db
        # The payload is reconstructed once per returned row, never shared.
        full_ref_hash = hashlib.sha256("\n".join(p.ref for p in objects).encode()).hexdigest()
        actual_refs = hashlib.sha256()
        for ordinal, (payload,) in enumerate(db.execute("SELECT payload FROM leaves ORDER BY ordinal")):
            if ordinal:
                actual_refs.update(b"\n")
            actual_refs.update(json.loads(payload)["key"].encode())
        assert actual_refs.hexdigest() == full_ref_hash
        binding_count = db.execute(
            "SELECT sum(json_array_length(s.bindings,'$.source_ids')) "
            "FROM leaves l JOIN source_sets s ON s.id=l.sources"
        ).fetchone()[0]
        assert binding_count == sum(args.sources if i % 100 < args.overlap else 1
                                    for i in range(args.objects))
        result = {"objects": args.objects, "sources": args.sources,
                  "overlap_percent": args.overlap, "runtime": platform.python_version(),
                  "machine": platform.machine(), "sqlite": __import__("sqlite3").sqlite_version,
                  "fixture": "in-process metadata stubs; no network/provider latency/real browser",
                  "serialized_sample_bytes": len(json.dumps(first, ensure_ascii=False).encode()),
                  "unique_ref_sha256": full_ref_hash, "source_binding_count": binding_count,
                  "before_search": before,
                  "cold_search_ms": cold_ms, "cold_source_projections": cold_calls,
                  "warm_source_projections": calls - cold_calls,
                  "warm_search": warm_search, "warm_page": warm_page,
                  "cache_disk_bytes": db.execute("PRAGMA page_count").fetchone()[0] * 4096,
                  "rss_before_cold": rss_before,
                  "peak_rss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  "rss_unit": "bytes" if platform.system() == "Darwin" else "KiB"}
        print(json.dumps(result))
    finally:
        index.clear()


if __name__ == "__main__":
    main()
