#!/usr/bin/env python3
"""Persist one bounded exact-person activity/life routing reconciliation.

The 2026-08-26 recovery materialized many exact 500+ commanders after the saved
person-activity scan.  Their life hosts were present, but the old routing
frontier could suppress another scan at the same world time.  Re-run the
production routing owner once and atomically persist only semantic changes.
This creates no people, manpower, training hours, or elapsed campaign time.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from sword_runtime.service_runtime import CommandRoutedProductionPlanner
from sword_runtime.store.repository import atomic_replace_bytes


def _pretty_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def main() -> int:
    planner = CommandRoutedProductionPlanner(ROOT)
    planner._reset()
    planner._ensure_activity_routes()

    changed: list[str] = []
    for rel, value in sorted(planner._writes.items()):
        path = ROOT / rel
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            old = None
        if old == value:
            continue
        atomic_replace_bytes(path, _pretty_bytes(value))
        changed.append(rel)

    if planner._deletes:
        raise RuntimeError(f"activity-route reconciliation unexpectedly requested deletes: {sorted(planner._deletes)}")

    print(f"reconcile_exact_activity_routes_20260826: persisted {len(changed)} semantic JSON updates")
    print(f"  exact-character updates: {sum(1 for path in changed if path.startswith('state/char/'))}")
    print(f"  runtime updated: {'state/runtime.json' in changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
