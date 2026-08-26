#!/usr/bin/env python3
"""Squash the repaired current world into a fresh revision-1 campaign baseline.

This is intentionally not a historical rewind. It preserves present physical
world truth (people, forces, formations, equipment, Houses, population,
territory, economy, and command hierarchy) while deleting accumulated gameplay
history/routing: operations, reports, information claims, interaction attempts,
investigations, causal-event history, diplomatic proposals, war-intent work,
and scheduler execution history. The causal scheduler is then rebuilt from the
remaining exact current owners at the snapshot instant.
"""
from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"


def read(rel: str) -> Any:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def write(rel: str, value: Any) -> None:
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def delete(rel: str) -> None:
    path = ROOT / rel
    if path.exists():
        path.unlink()


def scrub_exact_refs(value: Any, removed: set[str]) -> Any:
    """Remove exact deleted-owner refs from keys, scalar values, and lists."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key in removed:
                continue
            cleaned = scrub_exact_refs(item, removed)
            if isinstance(item, str) and item in removed:
                continue
            out[key] = cleaned
        return out
    if isinstance(value, list):
        return [scrub_exact_refs(item, removed) for item in value if not (isinstance(item, str) and item in removed)]
    if isinstance(value, str) and value in removed:
        return None
    return value


def main() -> None:
    meta = read("state/meta.json")
    now = str(meta["time"])
    original_runtime = read("state/runtime.json")

    # Collect dynamic owner refs before deleting their authorities.
    operation_index = read("state/operations/index.json")
    operation_refs = set(str(x) for x in operation_index.get("operations", {}))

    information_index = read("state/information/index.json")
    information_refs = set(str(x) for x in information_index.get("claims", {}))

    investigation_index = read("state/investigations/index.json")
    investigation_refs = set(str(x) for x in investigation_index.get("investigations", {}))

    event_owner = read("state/event/events-messages-and-movement.json")
    event_refs = set(str(x) for x in event_owner.get("causal_events", {}))

    history = read("state/history/events/index.json")
    history_refs = {
        str(row.get("event_id")) for row in history.get("events", [])
        if isinstance(row, dict) and isinstance(row.get("event_id"), str)
    }

    interaction_path = "state/index/interaction-attempts.json"
    interaction = read(interaction_path)
    interaction_refs = {
        str(row.get("event_id")) for row in interaction.get("attempts", [])
        if isinstance(row, dict) and isinstance(row.get("event_id"), str)
    }

    proposal_dir = ROOT / "state/politics/diplomatic-proposals"
    proposal_refs: set[str] = set()
    if proposal_dir.exists():
        for path in proposal_dir.glob("*.json"):
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for key in ("proposal_ref", "owner_id", "id"):
                ref = row.get(key)
                if isinstance(ref, str) and ref:
                    proposal_refs.add(ref)
                    break

    removed_refs = operation_refs | information_refs | investigation_refs | event_refs | history_refs | interaction_refs | proposal_refs

    # 1. New campaign identity boundary. Keep the campaign ID so references and
    # deployment wiring do not need a second migration, but discard its revision trail.
    meta["revision"] = 1
    meta["campaign_started"] = True
    write("state/meta.json", meta)
    write("state/scene.json", {
        "schema": "scene",
        "world_time": now,
        "projection_revision": 1,
    })

    # 2. Exact histories / player-facing knowledge / processes become empty authorities.
    history["events"] = []
    history["archives"] = []
    history["archived_event_count"] = 0
    write("state/history/events/index.json", history)

    for ref, rel in list(information_index.get("claims", {}).items()):
        if isinstance(rel, str): delete(rel)
    information_index["claims"] = {}
    information_index["by_holder"] = {}
    write("state/information/index.json", information_index)
    subject_index = read("state/information/subject-index.json")
    subject_index["subjects"] = {}
    write("state/information/subject-index.json", subject_index)

    for ref, rel in list(operation_index.get("operations", {}).items()):
        if isinstance(rel, str): delete(rel)
    operation_index["operations"] = {}
    operation_index["active_battlefield_operation_refs"] = []
    write("state/operations/index.json", operation_index)

    for ref, rel in list(investigation_index.get("investigations", {}).items()):
        if isinstance(rel, str): delete(rel)
    investigation_index["investigations"] = {}
    investigation_index["by_actor"] = {}
    investigation_index["active_by_actor"] = {}
    investigation_index["by_status"] = {}
    write("state/investigations/index.json", investigation_index)

    commissions = read("state/commissions/index.json")
    commissions["commissions"] = {}
    commissions["requests"] = {}
    write("state/commissions/index.json", commissions)
    commitments = read("state/commitments/index.json")
    commitments["commitments"] = {}
    write("state/commitments/index.json", commitments)

    event_owner["causal_events"] = {}
    event_owner["archives"] = []
    event_owner["archived_event_count"] = 0
    event_owner["next_archive_seq"] = 1
    event_owner["records"] = []
    event_owner["runtime"] = {"last_settled_at": now}
    write("state/event/events-messages-and-movement.json", event_owner)

    interaction["attempts"] = []
    interaction["total_recorded"] = 0
    write(interaction_path, interaction)
    qin_delivery = read("state/index/qin-command-support-delivery.json")
    qin_delivery["by_operation"] = {}
    write("state/index/qin-command-support-delivery.json", qin_delivery)

    campaign_work = read("state/index/campaign-causal-work.json")
    campaign_work["targets"] = []
    write("state/index/campaign-causal-work.json", campaign_work)
    institutional = read("state/index/institutional-process-routing.json")
    institutional["processes"] = []
    write("state/index/institutional-process-routing.json", institutional)

    # 3. Remove transient interstate decisions and proposals while preserving
    # current diplomacy/territory/economic snapshot as baseline truth.
    if proposal_dir.exists():
        for path in proposal_dir.glob("*.json"):
            path.unlink()
    interstate = read("state/politics/interstate-history.json")
    interstate["last_review"] = now
    theaters = interstate.get("theaters", {})
    if isinstance(theaters, dict):
        for theater in theaters.values():
            if not isinstance(theater, dict):
                continue
            theater["cycle"] = 0
            theater["cooldown_reviews"] = 0
            theater["history"] = []
            theater.pop("last_peace_review", None)
            # Do not preserve a war phase whose exact operation/history has been removed.
            if str(theater.get("phase", "peace")) not in {"peace", "ceasefire"}:
                theater["phase"] = "peace"
            theater["pressure"] = 0
    write("state/politics/interstate-history.json", interstate)

    for path in sorted((ROOT / "state/states").glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["war_intents"] = []
        doc["strategic_directives"] = []
        doc["known_threats"] = {}
        doc["outgoing_diplomatic_proposal_refs"] = []
        doc.pop("last_war_intent_review", None)
        doc.pop("political_pressure", None)
        if isinstance(doc.get("frontier_runtime"), dict):
            doc["frontier_runtime"] = {"incident_count": 0}
        path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # 4. Reset arc execution history but retain the current scenario facts. Arc
    # drivers and cadence are recomputed from current exact owners on first review.
    arcs = read("state/arc/kingdom-arcs.json")
    for row in arcs.get("records", []):
        if not isinstance(row, dict):
            continue
        runtime = row.get("runtime")
        cadence = runtime.get("review_seconds") if isinstance(runtime, dict) else None
        row.pop("runtime", None)
        if isinstance(cadence, int) and cadence > 0:
            row["runtime"] = {"review_seconds": cadence}
    arcs["runtime"] = {"last_settled_at": now}
    write("state/arc/kingdom-arcs.json", arcs)

    # 5. Remove exact references to deleted transient owners from all remaining
    # state documents. This also clears command-group active_context_ref links,
    # appointment operation provenance, stale report refs, and proposal links.
    skip_prefixes = {
        "state/runtime.json",
        "state/meta.json",
        "state/scene.json",
    }
    for path in sorted(STATE.rglob("*.json")):
        rel = path.relative_to(ROOT).as_posix()
        if rel in skip_prefixes:
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        cleaned = scrub_exact_refs(doc, removed_refs)
        path.write_text(json.dumps(cleaned, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Explicitly remove active operation context even if a ref was encoded by a
    # future migration rather than one of the just-deleted operation IDs.
    for path in sorted((ROOT / "state/cmd/command-groups").glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc.pop("active_context_ref", None)
        path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Operation-owned mobilization should not survive the operation itself. Only
    # formations actually referenced by deleted operations are normalized.
    operation_formation_refs: set[str] = set()
    # Use the old refs still available from the in-memory operation index paths by
    # reading the original ZIP is unnecessary; the formation set is also encoded
    # in current formations via operation links, which were scrubbed above. To be
    # conservative, normalize only obviously expeditionary statuses globally while
    # preserving garrison/fortified statuses.
    for path in sorted((ROOT / "state/formations").glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("mobilized") is True and str(doc.get("status", "")) in {"mobilized", "deployed", "marching"}:
            doc["mobilized"] = False
            doc["status"] = "ready"
        path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # 6. Owner routing must not retain deleted exact owners.
    owner_index = read("state/index/owner-index.json")
    owners = owner_index.get("owners", {})

    def owner_route_exists(route: str) -> bool:
        base = route.split("#", 1)[0]
        return (ROOT / base).exists()

    if isinstance(owners, dict):
        for ref in list(owners):
            rel = owners.get(ref)
            if ref in removed_refs or (isinstance(rel, str) and not owner_route_exists(rel)):
                owners.pop(ref, None)
    write("state/index/owner-index.json", owner_index)

    # A fresh campaign baseline must not retain polity-local world-arc work or
    # settled campaign action history. The polity itself remains starting-world truth.
    for path in sorted((ROOT / "state/politics/polities").glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if "world_arc_priorities" in doc:
            doc["world_arc_priorities"] = []
            path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # 7. Fresh scheduler/recovery-facing runtime. Preserve the complete current
    # recurring route topology (which is not gameplay history), but discard every
    # old due/resolved cursor and all one-shot/transient routes. This avoids losing
    # exact-person and person-lite life/activity hosts that are intentionally routed
    # through bounded indexes rather than recreated by a directory scan.
    sys.path.insert(0, str(ROOT / "runtime"))
    from sword_runtime.sim.calendar import CampaignTime
    from sword_runtime.scheduler_frontier import next_global_due

    current = CampaignTime.parse(now)
    original_hosts = original_runtime.get("hosts", {}) if isinstance(original_runtime, dict) else {}
    original_events = original_runtime.get("events", []) if isinstance(original_runtime, dict) else []
    old_event_by_host = {
        str(row.get("target_host")): row
        for row in original_events
        if isinstance(row, dict) and isinstance(row.get("target_host"), str)
    }

    def contains_removed(value: Any) -> bool:
        if isinstance(value, str): return value in removed_refs
        if isinstance(value, list): return any(contains_removed(x) for x in value)
        if isinstance(value, dict): return any(k in removed_refs or contains_removed(v) for k, v in value.items())
        return False

    hosts: dict[str, Any] = {}
    events: list[dict[str, Any]] = []
    for host_id, raw in sorted(original_hosts.items() if isinstance(original_hosts, dict) else []):
        if not isinstance(host_id, str) or not isinstance(raw, dict) or contains_removed(raw):
            continue
        recurrence = raw.get("recurrence_seconds")
        if isinstance(recurrence, bool) or not isinstance(recurrence, int) or recurrence <= 0:
            continue
        host = copy.deepcopy(raw)
        due = current.add_seconds(recurrence)
        host["resolved_through"] = now
        host["next_due"] = str(due)
        host["safe_through"] = str(due.add_seconds(-1))
        if isinstance(host.get("activity_route"), dict):
            host["activity_route"]["classified_at"] = now
        hosts[host_id] = host
        event = copy.deepcopy(old_event_by_host.get(host_id) or {})
        event_id = event.get("event_id") or host.get("event_id") or f"event_reset_{host_id}"
        kind = event.get("kind") or host.get("kind")
        events.append({
            "event_id": str(event_id),
            "kind": str(kind),
            "priority": int(event.get("priority", 100)),
            "target_host": host_id,
            "due_at": str(due),
        })

    routing = copy.deepcopy(original_runtime.get("person_activity_routing", {})) if isinstance(original_runtime, dict) else {}
    if not isinstance(routing, dict): routing = {}
    routing["last_route_scan_at"] = now

    runtime = {
        "schema": "sword-runtime-state",
        "owner_id": "runtime",
        "world_time": now,
        "hosts": hosts,
        "events": events,
        "metrics": {
            "events_processed": 0,
            "global_faction_scans": 0,
            "global_force_scans": 0,
            "global_house_scans": 0,
            "global_person_scans": 0,
            "hosts_woken": 0,
            "person_activity_route_classifications": 0,
            "person_activity_route_registrations": 0,
            "planning_reads": 0,
            "writes": 0,
        },
        "pending_wake": None,
        "person_activity_routing": routing,
        "scheduler": {
            "causal_settled_through": now,
            "last_reconciled_at": now,
            "next_safety_reconcile_at": str(current.add_seconds(7 * 86400)),
            "next_global_due": None,
            "dirty": True,
            "dirty_reasons": ["fresh_campaign_snapshot"],
            "registry_revision": 1,
            "last_coverage": {},
        },
    }
    runtime["scheduler"]["next_global_due"] = next_global_due(runtime)
    write("state/runtime.json", runtime)

    from sword_runtime.service_runtime import CommandRoutedProductionPlanner
    planner = CommandRoutedProductionPlanner(ROOT)
    planner._reset()
    coverage = planner._reconcile_all_scheduler_domains(now)
    if not coverage.get("complete"):
        raise RuntimeError(f"fresh scheduler coverage incomplete: {coverage}")
    for rel, value in planner._writes.items():
        write(rel, value)
    for rel in planner._deletes:
        delete(rel)

    assert read("state/operations/index.json").get("operations") == {}
    assert read("state/information/index.json").get("claims") == {}
    assert read("state/history/events/index.json").get("events") == []
    assert read(interaction_path).get("attempts") == []
    assert read("state/meta.json")["revision"] == 1

    print(json.dumps({
        "status": "fresh_revision_1_snapshot",
        "time": now,
        "removed_operations": len(operation_refs),
        "removed_information_claims": len(information_refs),
        "removed_investigations": len(investigation_refs),
        "removed_causal_events": len(event_refs),
        "removed_history_events": len(history_refs),
        "removed_interaction_attempts": len(interaction_refs),
        "removed_diplomatic_proposals": len(proposal_refs),
        "scheduler_hosts": len(read("state/runtime.json").get("hosts", {})),
        "scheduler_events": len(read("state/runtime.json").get("events", [])),
    }, indent=2))


if __name__ == "__main__":
    main()
