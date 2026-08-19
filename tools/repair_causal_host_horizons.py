#!/usr/bin/env python3
"""Repair only stale scheduler safe-horizon metadata in the current campaign.

This is an explicit OOC maintenance tool. It does not advance world time, run a
causal host, add an event, award progression, or alter campaign-domain truth.
It only raises a recurring host's already-proven safe horizon to the instant
before its existing future ``next_due`` event when the saved horizon is behind
the committed world time.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from sword_runtime.sim.calendar import CampaignTime


def main() -> int:
    path = ROOT / "state/runtime.json"
    runtime = json.loads(path.read_text(encoding="utf-8"))
    now = CampaignTime.parse(str(runtime["world_time"]))
    events_by_host = {
        str(row.get("target_host")): row
        for row in runtime.get("events", [])
        if isinstance(row, dict) and isinstance(row.get("target_host"), str)
    }
    repaired: list[str] = []
    for host_id, host in sorted(runtime.get("hosts", {}).items()):
        if not isinstance(host, dict) or host.get("next_due") is None:
            continue
        next_due = CampaignTime.parse(str(host["next_due"]))
        safe = CampaignTime.parse(str(host["safe_through"]))
        event = events_by_host.get(str(host_id))
        if event is None or str(event.get("due_at")) != str(host["next_due"]):
            raise ValueError(f"causal route mismatch for {host_id}; refusing metadata repair")
        if next_due <= now:
            raise ValueError(f"overdue causal host {host_id}; scheduler execution is required, not metadata repair")
        if safe < now:
            host["safe_through"] = str(next_due.add_seconds(-1))
            repaired.append(str(host_id))
    if repaired:
        path.write_text(json.dumps(runtime, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"causal_host_horizon_repair: repaired={len(repaired)}")
    for host_id in repaired:
        print(host_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
