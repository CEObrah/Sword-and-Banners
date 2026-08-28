"""Player-safe handoff policy for generic world-arc reports.

World arcs may observe exact domain work, but a generic arc result is not itself
player knowledge. This adapter sits between the low-level report propagator and
the information ledger. It permits only evidence shapes whose public meaning is
explicitly bounded, rewrites them into intelligible player-facing language, and
suppresses opaque or semantically duplicate material bookkeeping before it can
enter Tang Wei's knowledge ledger.
"""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from typing import Any

from sword_runtime.causal_event_store import (
    get_causal_event,
    read_causal_event_owner,
    write_causal_event_owner,
)
from sword_runtime.world_arcs import settle_world_arc_report


_RUNTIME_PATH = "state/runtime.json"
_SAFE_EVIDENCE_KINDS = frozenset({"exact_operation_created", "controlled_operation_stall"})
_CLAIM_CACHE_KEY = "player_safe_world_arc_claims"
_CLAIM_CACHE_LIMIT = 64


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
        evidence = provenance.get("controlled_operation_evidence") if isinstance(provenance.get("controlled_operation_evidence"), Mapping) else None
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
    if str(evidence.get("kind")) == "controlled_operation_stall":
        operation_ref = evidence.get("operation_ref")
        if not isinstance(operation_ref, str) or not operation_ref.startswith("operation_"):
            return None
    return evidence


def source_has_player_safe_world_arc_report(source: Mapping[str, Any]) -> bool:
    """Return whether a material arc source has bounded public meaning.

    This deliberately does not infer player knowledge from arbitrary exact domain
    evidence. New evidence kinds must be opted in here only after their public
    semantics are defined.
    """
    result = str(source.get("result", ""))
    evidence = _safe_material_evidence(source)
    if evidence is None:
        return False
    if result == "material_action_settled" and str(evidence.get("kind")) == "exact_operation_created":
        return True
    return result == "work_blocked" and str(evidence.get("kind")) == "controlled_operation_stall"


def _operation_claim_fingerprint(evidence: Mapping[str, Any]) -> str | None:
    """Return an opaque identity for one exact-operation-created public claim.

    The hidden exact operation ref is used only to decide whether the same claim
    has already been delivered. It is never copied into player-facing report
    prose or claim-cache rows.
    """
    if str(evidence.get("kind", "")) != "exact_operation_created":
        return None
    operation_ref = evidence.get("operation_ref")
    if not isinstance(operation_ref, str) or not operation_ref:
        return None
    return hashlib.sha256(f"exact_operation_created|{operation_ref}".encode("utf-8")).hexdigest()


def _claim_cache(planner: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    runtime = copy.deepcopy(planner.read(_RUNTIME_PATH))
    claims = runtime.setdefault(_CLAIM_CACHE_KEY, [])
    if not isinstance(claims, list):
        raise ValueError("player-safe world-arc claim cache is invalid")
    return runtime, claims


def _bootstrap_operation_claims(
    planner: Any,
    owner: Mapping[str, Any],
    arc_ref: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Rehydrate recent delivered claims without treating prose as authority.

    The durable source event remains the semantic evidence authority. This cache
    stores only opaque fingerprints and bounded delivery metadata so a deployment
    can recognize already-delivered recent operation claims without exposing
    hidden operation or formation identities.
    """
    runtime, claims = _claim_cache(planner)
    known = {
        (str(row.get("arc_ref", "")), str(row.get("evidence_kind", "")), str(row.get("fingerprint", "")))
        for row in claims
        if isinstance(row, Mapping)
    }
    causal = owner.get("causal_events") if isinstance(owner.get("causal_events"), Mapping) else {}
    for report in causal.values():
        if not isinstance(report, Mapping):
            continue
        if report.get("kind") != "world_arc_report" or report.get("status") != "triggered":
            continue
        if str(report.get("arc_ref", "")) != arc_ref:
            continue
        source_ref = report.get("source_event_ref")
        if not isinstance(source_ref, str):
            continue
        source = causal.get(source_ref)
        if not isinstance(source, Mapping):
            source = get_causal_event(planner, source_ref)
        if not isinstance(source, Mapping):
            continue
        evidence = _safe_material_evidence(source)
        if evidence is None:
            continue
        fingerprint = _operation_claim_fingerprint(evidence)
        if fingerprint is None:
            continue
        key = (arc_ref, str(evidence.get("kind")), fingerprint)
        if key in known:
            continue
        claims.append(
            {
                "arc_ref": arc_ref,
                "evidence_kind": str(evidence.get("kind")),
                "fingerprint": fingerprint,
                "delivered_at": str(report.get("triggered_at", report.get("due_at", ""))),
            }
        )
        known.add(key)
    del claims[:-_CLAIM_CACHE_LIMIT]
    planner.put(_RUNTIME_PATH, runtime)
    return runtime, claims


def _summary(
    planner: Any,
    host: Mapping[str, Any],
    source: Mapping[str, Any],
    *,
    prior_same_kind_deliveries: int = 0,
) -> str:
    evidence = _safe_material_evidence(source)
    if evidence is None:
        raise ValueError("opaque world-arc source cannot be rendered for the player")
    arc_ref = str(host.get("arc_ref", source.get("arc_ref", "")))
    route = str(host.get("route", "ordinary reports"))
    basis = _arc_basis(planner, arc_ref)
    if str(evidence.get("kind")) == "exact_operation_created":
        if prior_same_kind_deliveries > 0:
            return (
                f"Reports reaching Tang Wei through {route} concern {basis}. "
                "They now establish a further military commitment: another active military "
                "operation has been opened and an existing formation assigned to it. This is "
                "additional material action beyond the operation already reported. The reports "
                "do not by themselves establish the new operation's exact force, route, commander, "
                "supply state, combat contact, result, or immediate objective beyond the already-known campaign basis."
            )
        return (
            f"Reports reaching Tang Wei through {route} concern {basis}. "
            "They now establish a concrete escalation: the reported campaign has produced "
            "an active military operation, rather than remaining only preparation, intent, "
            "or a queued directive. The reports do not by themselves establish its exact "
            "force, route, commander, or immediate objective beyond the already-known campaign basis."
        )
    if str(evidence.get("kind")) == "controlled_operation_stall":
        return (
            f"Reports reaching Tang Wei through {route} concern {basis}. "
            "Tang Wei's current controlled operation attempted to advance but was blocked by "
            "material, informational, or institutional constraints. The dispatch establishes "
            "the stall in his own command without exposing hidden opposing state or exact backend causes."
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
    # a vague report, a notice, or a searchable information claim.
    if not source_has_player_safe_world_arc_report(source):
        _terminate_opaque_route(planner, host)
        return None

    evidence = _safe_material_evidence(source)
    if evidence is None:
        _terminate_opaque_route(planner, host)
        return None
    arc_ref = str(host.get("arc_ref", source.get("arc_ref", "")))
    fingerprint = _operation_claim_fingerprint(evidence)

    # A report route is information transport, not world-event authority. Preserve
    # every exact source event, but suppress another delivery of the same exact
    # operation-created claim. Distinct exact operations remain distinct material
    # evidence and are rendered as an additional player-safe commitment instead.
    _path, owner_before = read_causal_event_owner(planner)
    indexed_owner = copy.deepcopy(owner_before)
    _claims_runtime, claims_before = _bootstrap_operation_claims(planner, indexed_owner, arc_ref)
    same_kind_claims = [
        row
        for row in claims_before
        if isinstance(row, Mapping)
        and str(row.get("arc_ref", "")) == arc_ref
        and str(row.get("evidence_kind", "")) == str(evidence.get("kind"))
    ]
    if fingerprint is not None and any(str(row.get("fingerprint", "")) == fingerprint for row in same_kind_claims):
        _terminate_opaque_route(planner, host)
        return None

    prior_same_kind_deliveries = len({
        str(row.get("fingerprint", ""))
        for row in same_kind_claims
        if isinstance(row, Mapping) and str(row.get("fingerprint", ""))
    })

    # The low-level propagator may return a campaign_event-shaped handoff for an
    # acute direct delivery. The causal scheduler treats that shape as a nonblocking
    # campaign_event_notice and never persists it as pending_wake. Keep returning it
    # so the command result can surface the information without stopping time.
    wake = settle_world_arc_report(planner, host, at)
    report_ref = f"{source_event_ref}.report"
    report = get_causal_event(planner, report_ref)
    if not isinstance(report, Mapping):
        return None

    summary = _summary(
        planner,
        host,
        source,
        prior_same_kind_deliveries=prior_same_kind_deliveries,
    )
    _path, owner = read_causal_event_owner(planner)
    current = owner.get("causal_events", {}).get(report_ref)
    if not isinstance(current, Mapping):
        return None
    updated = copy.deepcopy(owner)
    updated["causal_events"][report_ref]["summary"] = summary
    provenance = updated["causal_events"][report_ref].setdefault("provenance", {})
    provenance["player_safe_evidence_kind"] = str(evidence.get("kind"))
    claims_runtime, claims = _bootstrap_operation_claims(planner, updated, arc_ref)
    if fingerprint is not None and not any(
        isinstance(row, Mapping)
        and str(row.get("arc_ref", "")) == arc_ref
        and str(row.get("evidence_kind", "")) == str(evidence.get("kind"))
        and str(row.get("fingerprint", "")) == fingerprint
        for row in claims
    ):
        claims.append(
            {
                "arc_ref": arc_ref,
                "evidence_kind": str(evidence.get("kind")),
                "fingerprint": fingerprint,
                "delivered_at": at,
            }
        )
        del claims[:-_CLAIM_CACHE_LIMIT]
        planner.put(_RUNTIME_PATH, claims_runtime)
    write_causal_event_owner(planner, updated)
    if isinstance(wake, dict):
        wake["reason"] = summary
    return wake


__all__ = [
    "settle_player_safe_world_arc_report",
    "source_has_player_safe_world_arc_report",
]
