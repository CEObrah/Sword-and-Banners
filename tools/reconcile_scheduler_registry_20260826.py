#!/usr/bin/env python3
"""Persist one zero-time production scheduler reconciliation for the recovered save."""
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
    runtime = planner.read("state/runtime.json")
    at = str(runtime["world_time"])
    scheduler = runtime.get("scheduler", {}) if isinstance(runtime, dict) else {}
    if not isinstance(scheduler, dict):
        raise RuntimeError("scheduler state is invalid")
    if scheduler.get("dirty") is True:
        coverage = planner._reconcile_all_scheduler_domains(at)
        if not coverage.get("complete"):
            raise RuntimeError(f"scheduler reconciliation incomplete: {coverage}")

    # Reconciliation may register one-shot hosts exactly at the current frontier.
    # Settle those due-now hosts without advancing campaign time so the packaged
    # save never begins with an overdue causal event.
    planner._active_command_type = "advance_time"
    planner._advance_runtime(at)

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
        raise RuntimeError(f"scheduler reconciliation unexpectedly requested deletes: {sorted(planner._deletes)}")

    saved = json.loads((ROOT / "state/runtime.json").read_text(encoding="utf-8"))
    scheduler = saved["scheduler"]
    print(f"reconcile_scheduler_registry_20260826: persisted {len(changed)} semantic JSON updates")
    print(f"  registry_revision: {scheduler['registry_revision']}")
    print(f"  dirty: {scheduler['dirty']}")
    print(f"  last_reconciled_at: {scheduler['last_reconciled_at']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
