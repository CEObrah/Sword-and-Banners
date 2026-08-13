"""Bounded short-horizon campaign events for the causal scheduler.

Campaign event work targets are routing definitions, not occurrence truth. A
planned target becomes campaign truth only when the causal runtime settles it
and writes the triggered record into the exact routed event-registry owner.
The routing document itself is read-only during gameplay; exact triggered
records, not mutable routing status, prevent duplicate settlement.
"""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from typing import Any

from sword_runtime.sim.calendar import CampaignTime


CAMPAIGN_CAUSAL_WORK_PATH = "state/index/campaign-causal-work.json"
_MAX_CAMPAIGN_WORK_TARGETS = 128
_MAX_SUMMARY_CHARS = 4000


def _work_document(planner: Any) -> dict[str, Any]:
    document = copy.deepcopy(planner.read_optional(CAMPAIGN_CAUSAL_WORK_PATH))
    if document is None:
        return {"authority": False, "targets": []}
    if not isinstance(document, dict) or document.get("authority") is not False:
        raise ValueError("campaign causal work routing must be authority:false")
    targets = document.get("targets")
    if not isinstance(targets, list) or len(targets) > _MAX_CAMPAIGN_WORK_TARGETS:
        raise ValueError("campaign causal work routing is invalid or unbounded")
    return document


def _target_map(document: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    targets: dict[str, dict[str, Any]] = {}
    for raw in document.get("targets", []):
        if not isinstance(raw, dict):
            raise ValueError("campaign causal work target is invalid")
        work_ref = raw.get("work_ref")
        if not isinstance(work_ref, str) or not work_ref or len(work_ref) > 160:
            raise ValueError("campaign causal work_ref is invalid")
        if work_ref in targets:
            raise ValueError("duplicate campaign causal work_ref")
        status = raw.get("status", "pending")
        if status not in {"pending", "cancelled"}:
            raise ValueError("campaign causal work status is invalid")
        targets[work_ref] = raw
    return targets


def _target_fields(target: Mapping[str, Any]) -> tuple[str, str, CampaignTime, int, str, bool]:
    work_ref = target.get("work_ref")
    owner_ref = target.get("source_owner_ref")
    due_at = target.get("due_at")
    priority = target.get("priority", 50)
    effect = target.get("effect")
    wake = target.get("wake", False)
    if not isinstance(work_ref, str) or not work_ref:
        raise ValueError("campaign causal work_ref is invalid")
    if not isinstance(owner_ref, str) or not owner_ref or len(owner_ref) > 160:
        raise ValueError("campaign causal source owner is invalid")
    if not isinstance(due_at, str):
        raise ValueError("campaign causal due_at is invalid")
    if isinstance(priority, bool) or not isinstance(priority, int) or not 0 <= priority <= 1000:
        raise ValueError("campaign causal priority is invalid")
    if not isinstance(effect, Mapping):
        raise ValueError("campaign causal effect is invalid")
    summary = effect.get("summary")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > _MAX_SUMMARY_CHARS:
        raise ValueError("campaign causal player-visible summary is invalid")
    if not isinstance(wake, bool):
        raise ValueError("campaign causal wake flag is invalid")
    return work_ref, owner_ref, CampaignTime.parse(due_at), priority, summary.strip(), wake


def _event_owner(planner: Any, owner_ref: str) -> tuple[str, dict[str, Any]]:
    index = planner.read("state/index/owner-index-gold.json")
    owners = index.get("owners") if isinstance(index, Mapping) else None
    path = owners.get(owner_ref) if isinstance(owners, Mapping) else None
    if not isinstance(path, str) or not path.startswith("state/event/"):
        raise ValueError("campaign causal work must route to an exact event owner")
    owner = copy.deepcopy(planner.read(path))
    if owner.get("owner_id") != owner_ref or owner.get("schema") != "event-registry":
        raise ValueError("campaign causal event owner is invalid")
    return path, owner


def _route_ids(work_ref: str) -> tuple[str, str]:
    digest = hashlib.sha256(work_ref.encode("utf-8")).hexdigest()[:20]
    return f"host_campaign_event_{digest}", f"event_campaign_event_{digest}"


def sync_campaign_work_routes(planner: Any, runtime: dict[str, Any]) -> None:
    """Materialize bounded pending work targets into the authoritative runtime queue."""

    document = _work_document(planner)
    targets = _target_map(document)
    if not targets:
        return
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    current = CampaignTime.parse(str(runtime["world_time"]))
    pending_wake = runtime.get("pending_wake") if isinstance(runtime.get("pending_wake"), Mapping) else None
    event_by_id = {
        str(event.get("event_id")): event
        for event in events
        if isinstance(event, dict) and isinstance(event.get("event_id"), str)
    }

    for work_ref, target in sorted(targets.items()):
        if target.get("status", "pending") != "pending":
            continue
        parsed_ref, owner_ref, due, priority, _summary, _wake = _target_fields(target)
        if parsed_ref != work_ref:
            raise ValueError("campaign causal work routing changed identity")
        _owner_path, owner = _event_owner(planner, owner_ref)
        recorded = owner.get("causal_events") if isinstance(owner.get("causal_events"), Mapping) else {}
        existing_record = recorded.get(work_ref) if isinstance(recorded, Mapping) else None
        if isinstance(existing_record, Mapping) and existing_record.get("status") == "triggered":
            continue

        effective_due = due if due > current else current
        safe_through = effective_due.add_seconds(-1)
        resolved_through = current if current <= safe_through else safe_through
        host_id, scheduler_event_id = _route_ids(work_ref)
        is_active_wake = isinstance(pending_wake, Mapping) and pending_wake.get("target_host") == host_id
        host = hosts.get(host_id)
        if not isinstance(host, dict):
            host = {}
            hosts[host_id] = host
        host.update(
            {
                "host_id": host_id,
                "kind": "campaign_event",
                "owner_ref": owner_ref,
                "work_ref": work_ref,
                "recurrence_seconds": 0,
            }
        )
        if not is_active_wake:
            host["resolved_through"] = str(resolved_through)
            host["safe_through"] = str(safe_through)
            host["next_due"] = str(effective_due)

        scheduler_event = event_by_id.get(scheduler_event_id)
        if scheduler_event is None:
            scheduler_event = {
                "event_id": scheduler_event_id,
                "kind": "campaign_event",
                "priority": priority,
                "target_host": host_id,
                "due_at": str(effective_due),
            }
            events.append(scheduler_event)
            event_by_id[scheduler_event_id] = scheduler_event
        elif not is_active_wake:
            scheduler_event.update(
                {
                    "kind": "campaign_event",
                    "priority": priority,
                    "target_host": host_id,
                    "due_at": str(effective_due),
                }
            )
            scheduler_event.pop("suspended", None)


def settle_campaign_work_target(planner: Any, host: Mapping[str, Any], at: str) -> dict[str, Any] | None:
    """Commit one planned campaign work target into its exact event owner."""

    work_ref = host.get("work_ref")
    owner_ref = host.get("owner_ref")
    if not isinstance(work_ref, str) or not isinstance(owner_ref, str):
        raise ValueError("campaign event host routing is invalid")
    document = _work_document(planner)
    targets = _target_map(document)
    target = targets.get(work_ref)
    if target is None:
        raise ValueError("campaign event host lost its work target")
    parsed_ref, parsed_owner, due, _priority, summary, wake = _target_fields(target)
    if parsed_ref != work_ref or parsed_owner != owner_ref:
        raise ValueError("campaign event host diverged from its work target")
    if target.get("status", "pending") == "cancelled":
        return None

    triggered_at = CampaignTime.parse(at)
    if due > triggered_at:
        raise ValueError("campaign causal work fired before its due time")
    owner_path, owner = _event_owner(planner, owner_ref)
    causal_events = owner.get("causal_events")
    if causal_events is None:
        causal_events = {}
        owner["causal_events"] = causal_events
    if not isinstance(causal_events, dict):
        raise ValueError("event owner causal_events is invalid")
    existing = causal_events.get(work_ref)
    if isinstance(existing, Mapping) and existing.get("status") == "triggered":
        return None

    causal_events[work_ref] = {
        "event_ref": work_ref,
        "kind": str(target.get("kind", "campaign_event")),
        "status": "triggered",
        "due_at": str(due),
        "triggered_at": at,
        "summary": summary,
        "provenance": {
            "kind": "causal_runtime_settlement",
            "source_owner_ref": owner_ref,
            "work_ref": work_ref,
            "late_catch_up": triggered_at > due,
        },
    }
    owner_runtime = owner.get("runtime")
    if not isinstance(owner_runtime, dict):
        raise ValueError("event owner runtime is invalid")
    owner_runtime["last_settled_at"] = at
    planner.put(owner_path, owner)

    if not wake:
        return None
    digest = hashlib.sha256(f"{work_ref}|{at}".encode("utf-8")).hexdigest()[:20]
    return {
        "wake_ref": f"wake.campaign_event.{digest}",
        "kind": "campaign_event",
        "at": at,
        "campaign_event_ref": work_ref,
        "reason": summary,
    }


__all__ = [
    "CAMPAIGN_CAUSAL_WORK_PATH",
    "settle_campaign_work_target",
    "sync_campaign_work_routes",
]
