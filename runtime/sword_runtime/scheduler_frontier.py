"""Global causal frontier and scheduler-reconciliation utilities.

The ordinary causal host/event registry remains the execution authority.  This
module adds one durable proof around it:

* ``world_time`` is the currently reached campaign instant;
* ``scheduler.causal_settled_through`` is the instant through which all due
  registered causal work has been chronologically settled;
* one recurring scheduler-reconciliation host periodically proves that all
  route-owning subsystems have had a chance to register current work;
* route-affecting commands mark reconciliation dirty so the next time advance
  reconciles immediately instead of waiting for the periodic safety boundary.

It owns no domain outcomes and never scans state directories.  Coverage reads
only explicit routing/index authorities and the scheduler registry itself.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from sword_runtime.sim.calendar import CampaignTime

RUNTIME_PATH = "state/runtime.json"
RECONCILE_HOST_ID = "host_scheduler_reconciliation"
RECONCILE_EVENT_ID = "event_scheduler_reconciliation"
RECONCILE_SECONDS = 7 * 86400
RECONCILE_PRIORITY = 1

# Commands capable of changing which causal owners/routes must exist.  Ordinary
# movement/combat can change due work, but their persistent owners already exist;
# these commands can create, destroy, reassign or reclassify scheduler-visible
# owners and therefore invalidate routing coverage.
ROUTE_AFFECTING_COMMANDS = frozenset(
    {
        "person_materialize",
        "formation_create",
        "formation_reconstitute",
        "formation_split",
        "formation_merge",
        "formation_dissolve",
        "formation_assign",
        "force_assignment",
        "command_assign",
        "command_transfer",
        "operation_create",
        "operation_transition",
        "institution_project",
        "house_action",
        "state_action",
        "polity_action",
        "family_event",
        "career_event",
        "mercenary_contract",
        "organization_action",
        "custody_action",
        "scheme_action",
        "settlement_civic_action",
        "recruitment",
        "recruitment_campaign_finalize",
        "recruitment_campaign_cancel",
    }
)


def _event_map(runtime: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    events = runtime.get("events")
    if not isinstance(events, list):
        raise ValueError("runtime causal events are invalid")
    for row in events:
        if not isinstance(row, Mapping):
            raise ValueError("runtime causal event is invalid")
        event_id = row.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("runtime causal event lost event_id")
        if event_id in result:
            raise ValueError("duplicate runtime causal event_id")
        result[event_id] = row
    return result


def next_global_due(runtime: Mapping[str, Any]) -> str | None:
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, Mapping) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    due: CampaignTime | None = None
    for event in events:
        if not isinstance(event, Mapping) or event.get("suspended") is True:
            continue
        host_id = event.get("target_host")
        host = hosts.get(host_id) if isinstance(host_id, str) else None
        if not isinstance(host, Mapping) or host.get("next_due") is None:
            continue
        due_text = event.get("due_at")
        if not isinstance(due_text, str) or due_text != host.get("next_due"):
            raise ValueError("runtime event and host due time diverged")
        value = CampaignTime.parse(due_text)
        if due is None or value < due:
            due = value
    return str(due) if due is not None else None


def ensure_scheduler_state(runtime: dict[str, Any]) -> dict[str, Any]:
    now_text = runtime.get("world_time")
    if not isinstance(now_text, str):
        raise ValueError("runtime world_time is invalid")
    now = CampaignTime.parse(now_text)
    scheduler = runtime.setdefault("scheduler", {})
    if not isinstance(scheduler, dict):
        raise ValueError("runtime scheduler state is invalid")
    scheduler.setdefault("causal_settled_through", now_text)
    scheduler.setdefault("last_reconciled_at", now_text)
    scheduler.setdefault("next_safety_reconcile_at", str(now.add_seconds(RECONCILE_SECONDS)))
    scheduler.setdefault("dirty", False)
    scheduler.setdefault("dirty_reasons", [])
    scheduler.setdefault("registry_revision", 1)
    scheduler.setdefault("last_coverage", {})
    scheduler["next_global_due"] = next_global_due(runtime)
    return scheduler


def ensure_reconciliation_host(runtime: dict[str, Any]) -> None:
    now_text = runtime.get("world_time")
    if not isinstance(now_text, str):
        raise ValueError("runtime world_time is invalid")
    now = CampaignTime.parse(now_text)
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    host = hosts.get(RECONCILE_HOST_ID)
    if host is None:
        due = now.add_seconds(RECONCILE_SECONDS)
        host = {
            "kind": "scheduler_reconcile",
            "owner_ref": "runtime_scheduler_registry",
            "recurrence_seconds": RECONCILE_SECONDS,
            "resolved_through": now_text,
            "next_due": str(due),
            "safe_through": str(due.add_seconds(-1)),
        }
        hosts[RECONCILE_HOST_ID] = host
    if not isinstance(host, dict) or host.get("kind") != "scheduler_reconcile":
        raise ValueError("scheduler reconciliation host is invalid")
    matching = [row for row in events if isinstance(row, Mapping) and row.get("target_host") == RECONCILE_HOST_ID]
    if len(matching) > 1:
        raise ValueError("scheduler reconciliation host has duplicate events")
    if not matching:
        events.append(
            {
                "event_id": RECONCILE_EVENT_ID,
                "kind": "scheduler_reconcile",
                "priority": RECONCILE_PRIORITY,
                "target_host": RECONCILE_HOST_ID,
                "due_at": str(host["next_due"]),
            }
        )
    else:
        event = matching[0]
        if not isinstance(event, dict):
            raise ValueError("scheduler reconciliation event is invalid")
        event["event_id"] = RECONCILE_EVENT_ID
        event["kind"] = "scheduler_reconcile"
        event["priority"] = RECONCILE_PRIORITY
        event["due_at"] = str(host["next_due"])
        event.pop("suspended", None)


def mark_scheduler_dirty(runtime: dict[str, Any], reason: str) -> None:
    scheduler = ensure_scheduler_state(runtime)
    scheduler["dirty"] = True
    reasons = scheduler.setdefault("dirty_reasons", [])
    if not isinstance(reasons, list):
        raise ValueError("scheduler dirty reasons are invalid")
    if reason not in reasons:
        reasons.append(str(reason)[:160])
        del reasons[:-32]


def reconciliation_due(runtime: Mapping[str, Any], target_text: str) -> bool:
    scheduler = runtime.get("scheduler")
    if not isinstance(scheduler, Mapping):
        return True
    if scheduler.get("dirty") is True:
        return True
    boundary = scheduler.get("next_safety_reconcile_at")
    if not isinstance(boundary, str):
        return True
    return CampaignTime.parse(target_text) >= CampaignTime.parse(boundary)


def record_reconciliation(runtime: dict[str, Any], at: str, *, coverage: Mapping[str, Any]) -> None:
    scheduler = ensure_scheduler_state(runtime)
    now = CampaignTime.parse(at)
    scheduler["last_reconciled_at"] = at
    scheduler["next_safety_reconcile_at"] = str(now.add_seconds(RECONCILE_SECONDS))
    scheduler["dirty"] = False
    scheduler["dirty_reasons"] = []
    scheduler["registry_revision"] = int(scheduler.get("registry_revision", 0)) + 1
    scheduler["last_coverage"] = copy.deepcopy(dict(coverage))
    scheduler["next_global_due"] = next_global_due(runtime)


def assert_frontier_consistent(runtime: Mapping[str, Any]) -> None:
    world = runtime.get("world_time")
    scheduler = runtime.get("scheduler")
    if not isinstance(world, str) or not isinstance(scheduler, Mapping):
        raise ValueError("runtime scheduler frontier is missing")
    settled = scheduler.get("causal_settled_through")
    if not isinstance(settled, str):
        raise ValueError("runtime causal_settled_through is missing")
    if CampaignTime.parse(settled) != CampaignTime.parse(world):
        raise ValueError("runtime world_time and causal_settled_through diverged")


def set_causal_frontier(runtime: dict[str, Any], reached: str) -> None:
    scheduler = ensure_scheduler_state(runtime)
    prior = CampaignTime.parse(str(scheduler["causal_settled_through"]))
    value = CampaignTime.parse(reached)
    if value < prior:
        raise ValueError("causal settled frontier may not move backward")
    runtime["world_time"] = reached
    scheduler["causal_settled_through"] = reached
    scheduler["next_global_due"] = next_global_due(runtime)



def repair_core_autonomous_routes(planner: Any, runtime: dict[str, Any]) -> list[str]:
    """Repair missing standing hosts from the explicit owner index.

    Only domains with a stable generic cadence live here.  Factions, polities,
    world arcs, careers and other specialized domains retain their own routers.
    A historical owner whose next review is already overdue fails closed instead
    of silently erasing missed chronology.
    """
    owners_doc = planner.read("state/index/owner-index.json")
    owners = owners_doc.get("owners") if isinstance(owners_doc, Mapping) else None
    if not isinstance(owners, Mapping):
        raise ValueError("owner index is invalid")
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    now_text = runtime.get("world_time")
    if not isinstance(hosts, dict) or not isinstance(events, list) or not isinstance(now_text, str):
        raise ValueError("runtime causal queue is invalid")
    now = CampaignTime.parse(now_text)
    routed = {
        (str(host.get("kind")), str(host.get("owner_ref")))
        for host in hosts.values()
        if isinstance(host, Mapping) and isinstance(host.get("kind"), str) and isinstance(host.get("owner_ref"), str)
    }
    specs = {
        "state": (30 * 86400, "state_review", 100),
        "population": (365 * 86400, "population_review", 100),
        "house": (120 * 86400, "house_review", 100),
        "institution": (60 * 86400, "institution_review", 100),
        "mercenary": (90 * 86400, None, 75),
    }
    repaired: list[str] = []
    states = {
        ref.removeprefix("state_")
        for ref, route in owners.items()
        if isinstance(ref, str) and str(route).split("#", 1)[0].startswith("state/states/")
    }
    for owner_ref, route in sorted(owners.items()):
        if not isinstance(owner_ref, str) or not isinstance(route, str):
            continue
        base = route.split("#", 1)[0]
        kind = None
        if base.startswith("state/states/"):
            kind = "state"
        elif base.startswith("state/institutions/"):
            kind = "institution"
        elif base.startswith("state/houses/"):
            kind = "house"
        elif base.startswith("state/merc/") and owner_ref.startswith("merc_"):
            kind = "mercenary"
        elif base.startswith("state/population/") and owner_ref.removeprefix("population_") in states:
            kind = "population"
        if kind is None or (kind, owner_ref) in routed:
            continue
        recurrence, event_kind, priority = specs[kind]
        try:
            owner = planner.read(route)
        except (FileNotFoundError, KeyError, ValueError):
            continue
        anchor_text = owner.get("last_review") if isinstance(owner, Mapping) else None
        if isinstance(anchor_text, str):
            try:
                due = CampaignTime.parse(anchor_text).add_seconds(recurrence)
            except ValueError:
                due = now.add_seconds(recurrence)
        else:
            due = now.add_seconds(recurrence)
        if due <= now:
            raise ValueError(f"missing {kind} scheduler route has overdue historical work: {owner_ref}")
        if kind == "mercenary":
            host_id = f"host_merc_{owner_ref}"
            event_id = f"event_merc_{owner_ref}"
        else:
            host_id = f"host_{owner_ref}"
            event_id = f"event_host_{owner_ref}_review"
        hosts[host_id] = {
            "kind": kind,
            "owner_ref": owner_ref,
            "quiet_run_count": 0,
            "recurrence_seconds": recurrence,
            "resolved_through": anchor_text if isinstance(anchor_text, str) else now_text,
            "next_due": str(due),
            "safe_through": str(due.add_seconds(-1)),
            "route_repaired_at": now_text,
        }
        event = {
            "event_id": event_id,
            "priority": priority,
            "target_host": host_id,
            "due_at": str(due),
        }
        if event_kind is not None:
            event["kind"] = event_kind
        events.append(event)
        routed.add((kind, owner_ref))
        repaired.append(owner_ref)
    return repaired

def runtime_route_integrity(runtime: Mapping[str, Any]) -> dict[str, Any]:
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, Mapping) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    by_host: dict[str, list[Mapping[str, Any]]] = {}
    event_ids: set[str] = set()
    errors: list[str] = []
    for event in events:
        if not isinstance(event, Mapping):
            errors.append("event_not_object")
            continue
        event_id = event.get("event_id")
        host_id = event.get("target_host")
        if not isinstance(event_id, str) or not isinstance(host_id, str):
            errors.append("event_missing_route")
            continue
        if event_id in event_ids:
            errors.append(f"duplicate_event:{event_id}")
        event_ids.add(event_id)
        by_host.setdefault(host_id, []).append(event)
        if host_id not in hosts:
            errors.append(f"missing_host:{host_id}")
    overdue: list[str] = []
    now = CampaignTime.parse(str(runtime.get("world_time")))
    for host_id, host in hosts.items():
        if not isinstance(host_id, str) or not isinstance(host, Mapping):
            errors.append("host_not_object")
            continue
        nxt = host.get("next_due")
        if nxt is None:
            continue
        rows = by_host.get(host_id, [])
        if len(rows) != 1:
            errors.append(f"event_count:{host_id}:{len(rows)}")
            continue
        if rows[0].get("due_at") != nxt:
            errors.append(f"due_mismatch:{host_id}")
        if CampaignTime.parse(str(nxt)) < now:
            overdue.append(host_id)
    return {
        "host_count": len(hosts),
        "event_count": len(events),
        "errors": errors[:64],
        "overdue_host_refs": overdue[:64],
        "complete": not errors and not overdue,
    }
