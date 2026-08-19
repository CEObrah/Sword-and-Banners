#!/usr/bin/env python3
"""Idempotently install the global scheduler frontier/reconciliation host."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from sword_runtime.scheduler_frontier import (
    ensure_reconciliation_host,
    ensure_scheduler_state,
    runtime_route_integrity,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    path = ROOT / "state/runtime.json"
    runtime = json.loads(path.read_text(encoding="utf-8"))
    before = json.dumps(runtime, sort_keys=True, separators=(",", ":"))
    ensure_reconciliation_host(runtime)
    scheduler = ensure_scheduler_state(runtime)
    coverage = runtime_route_integrity(runtime)
    scheduler["last_coverage"] = coverage
    after = json.dumps(runtime, sort_keys=True, separators=(",", ":"))
    changed = before != after
    if args.apply and changed:
        path.write_text(json.dumps(runtime, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "changed": changed,
        "applied": bool(args.apply and changed),
        "world_time": runtime.get("world_time"),
        "causal_settled_through": scheduler.get("causal_settled_through"),
        "next_safety_reconcile_at": scheduler.get("next_safety_reconcile_at"),
        "next_global_due": scheduler.get("next_global_due"),
        "coverage": coverage,
    }, indent=2))
    return 0 if coverage.get("complete") else 1


if __name__ == "__main__":
    raise SystemExit(main())
