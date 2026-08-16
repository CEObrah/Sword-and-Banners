"""Player-safe handoff policy for generic world-arc reports.

World arcs may observe exact domain work, but a generic arc result is not itself
player knowledge. This adapter sits between the low-level report propagator and
the information ledger. It permits only evidence shapes whose public meaning is
explicitly bounded, rewrites them into intelligible player-facing language, and
suppresses opaque material bookkeeping before it can wake standing activity or
enter Tang Wei's knowledge ledger.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from sword_runtime.causal_event_store import (
    get_causal_event,
    read_causal_event_owner,
    write_causal_event_owner,
)
from sword_runtime.world_arcs import settle_world_arc_report


_RUNTIME_PATH = "state/runtime.json"
_SAFE_EVIDENCE_KINDS = frozenset({"exact_operation_created"})


def _arc_basis(planner: Any, arc_ref: str) -> str:
    document = planner.read("state/arc/kingdom-arcs.json")
    for row in document.get("records", []) if isinstance(document, Mapping) else []:
        if not isinstance(row, Mapping) or row.get("record_id") != arc_ref:
            continue
        facts = row.get("facts") if isinstance(row.get("facts"), Mapping) else {}
        basis = facts.get("current_basis")
        if isinstance(basis, str) and basis.strip():
            return basis.strip()
        label = row.get("label")
        if isinstance(label, str) and label.strip():
            return label.strip()
        break
    return "the reported campaign development"


def _safe_material_evidence(source: Mapping[str, Any]) -> Mapping[str, Any] | None:
    provenance = source.get("provenance") if isinstance(source.get("provenance"), Mapping) else {}
    evidence = provenance.get("material_evidence") if isinstance(provenance.get("material_evidence"), Mapping) else None
    if not isinstance(evidence, Mapping):
        return None
    if str(evidence.get("kind", "")) not in _SAFE_EVIDENCE_KINDS:
        return None
    if str(evidence.get("kind")) == "exact_operation_created":
        operation_ref = evidence.get("operation_ref")
        formation_ref = evidence.get("formation_ref")
        if not isinstance(operation_ref, str) or not operation_ref.startswith("operation_"):
            return None
        if not isinstance(formation_ref, str) or not formation_ref.startswith("formation_"):
            return None
    return evidence


def source_has_player_safe_world_arc_report(source: Mapping[str, Any]) -> bool:
    """Return whether a material arc source has bounded public meaning.

    This deliberately does not infer player knowledge from arbitrary exact domain
    evidence. New evidence kinds must be opted in here only after their public
    semantics are defined.
    """
    return str(source.get("result", "")) == "material_action_settled" and _safe_material_evidence(source) is not None


def _summary(planner: Any, host: Mapping[str, Any], source: Mapping[str, Any]) -> str:
    evidence = _safe_material_evidence(source)
    if evidence is None:
        raise ValueError("opaque world-arc source cannot be rendered for the player")
    arc_ref = str(host.get("arc_ref", source.get("arc_ref", "")))
    route = str(host.get("route", "ordinary reports"))
    basis = _arc_basis(planner, arc_ref)
    if str(evidence.get("kind")) == "exact_operation_created":
        return (
            f"Reports reaching Tang Wei through {route} concern {basis}. "
            "They now establish a concrete escalation: the reported campaign has produced "
            "an active military operation, rather than remaining only preparation, intent, "
            "or a queued directive. The reports do not by themselves establish its exact "
            "force, route, commander, or immediate objective beyond the already-known campaign basis."
        )
    raise ValueError("unsupported player-safe world-arc evidence kind")


def _terminate_opaque_route(planner: Any, host: Mapping[str, Any]) -> None:
    """Retire a non-reportable route without fabricating or deleting history."""
    runtime = copy.deepcopy(planner.read(_RUNTIME_PATH))
    hosts = runtime.get("hosts")
    runtime_host = hosts.get(host.get("host_id")) if isinstance(hosts, dict) else None
    if not isinstance(runtime_host, dict):
        raise ValueError("world arc report lost its scheduler host")
    runtime_host["recurrence_seconds"] = 0
    planner.put(_RUNTIME_PATH, runtime)


def settle_player_safe_world_arc_report(
    planner: Any,
    host: Mapping[str, Any],
    at: str,
) -> dict[str, Any] | None:
    """Settle one report route and retain only intelligible player-safe results."""
    source_event_ref = host.get("source_event_ref")
    if not isinstance(source_event_ref, str):
        raise ValueError("world arc report host is invalid")
    source = get_causal_event(planner, source_event_ref)
    if not isinstance(source, Mapping) or source.get("status") != "triggered":
        raise ValueError("world arc report lost its source event")

    # Do not even perform a delivery/exposure roll for material bookkeeping whose
    # public meaning is undefined. Retire the transport route before it can create
    # a vague report, a wake, or a searchable information claim.
    if not source_has_player_safe_world_arc_report(source):
        _terminate_opaque_route(planner, host)
        return None

    wake = settle_world_arc_report(planner, host, at)
    report_ref = f"{source_event_ref}.report"
    report = get_causal_event(planner, report_ref)
    if not isinstance(report, Mapping):
        return None

    summary = _summary(planner, host, source)
    _path, owner = read_causal_event_owner(planner)
    current = owner.get("causal_events", {}).get(report_ref)
    if not isinstance(current, Mapping):
        return None
    updated = copy.deepcopy(owner)
    updated["causal_events"][report_ref]["summary"] = summary
    updated["causal_events"][report_ref].setdefault("provenance", {})["player_safe_evidence_kind"] = str(
        _safe_material_evidence(source).get("kind")
    )
    write_causal_event_owner(planner, updated)
    if isinstance(wake, dict):
        wake["reason"] = summary
    return wake


__all__ = [
    "settle_player_safe_world_arc_report",
    "source_has_player_safe_world_arc_report",
]
