"""Bridge delivered causal reports into the durable information authority.

Causal events own occurrence truth.  The information ledger owns what exact
people know and what investigations may lawfully search.  A delivered report
must therefore create a knowledge claim without copying hidden world truth from
its source event.  This module records only the already player-visible report
summary and holder provenance. The causal report remains the sole owner of the
actual delivery journey.
"""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from typing import Any

from sword_runtime.causal_event_store import get_causal_event

_INFO_INDEX_PATH = "state/information/index.json"
_INFO_SUBJECT_INDEX_PATH = "state/information/subject-index.json"
_PLAYER_REF = "char_tang_wei"


def _information_ref(report_ref: str) -> str:
    digest = hashlib.sha256(report_ref.encode("utf-8")).hexdigest()[:20]
    return f"information.world_arc_report.{digest}"


def record_delivered_world_arc_report_information(
    planner: Any,
    host: Mapping[str, Any],
    at: str,
) -> str | None:
    """Persist one delivered world-arc report as player-known information.

    The causal report remains the authority for what was delivered. The claim
    deliberately stores only its public summary, never hidden source-event
    fields, material evidence, or a second invented transport record. Subject
    aliases let an investigation opened from the latest report search the report
    dossier accumulated for that arc.
    """

    source_event_ref = host.get("source_event_ref")
    arc_ref = host.get("arc_ref")
    if not isinstance(source_event_ref, str) or not isinstance(arc_ref, str):
        return None
    report_ref = f"{source_event_ref}.report"
    report = get_causal_event(planner, report_ref)
    if not isinstance(report, Mapping) or report.get("status") != "triggered":
        return None
    delivery = report.get("delivery") if isinstance(report.get("delivery"), Mapping) else {}
    if delivery.get("target_ref") != _PLAYER_REF:
        return None
    summary = report.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("delivered world-arc report lacks a player-visible summary")

    information_ref = _information_ref(report_ref)
    path = f"state/information/{information_ref}.json"
    index = copy.deepcopy(planner.read(_INFO_INDEX_PATH))
    existing_path = index.get("claims", {}).get(information_ref) if isinstance(index, Mapping) else None
    if isinstance(existing_path, str):
        # Preserve idempotency for historical claims that were already committed
        # before the player-safe handoff marker existed. This gate controls new
        # knowledge creation; it does not rewrite previously committed knowledge.
        return information_ref

    report_provenance = report.get("provenance") if isinstance(report.get("provenance"), Mapping) else {}
    safe_evidence_kind = report_provenance.get("player_safe_evidence_kind")
    if not isinstance(safe_evidence_kind, str) or not safe_evidence_kind.strip():
        # A causal `.report` row alone is no longer sufficient to create player
        # knowledge. Production report settlement must first attest that its
        # public meaning passed the bounded player-safe evidence policy.
        return None

    route = str(delivery.get("route", "world_arc_report"))
    location_ref = delivery.get("location_ref")
    visibility = str(host.get("visibility", "discoverable"))
    confidence = 950 if visibility == "direct" else 800
    claim = {
        "schema": "sword-information",
        "owner_id": information_ref,
        "information_ref": information_ref,
        "subject_ref": report_ref,
        "fact": summary.strip(),
        "claim": summary.strip(),
        "epistemic_kind": "report",
        "confidence_milli": confidence,
        "confidence": f"{confidence / 1000:.3f}",
        "provenance": f"world_arc_report:{report_ref}",
        "evidence_refs": [report_ref],
        "classification": "ordinary",
        "location_ref": location_ref,
        "discoverability_milli": 0,
        "investigation_discoverable": True,
        "origin_authority": "runtime_established",
        "world_truth_authority": False,
        "claim_status": "runtime_established",
        "knowers": [_PLAYER_REF],
        "holder_states": {
            _PLAYER_REF: {
                "epistemic_kind": "report",
                "confidence_milli": confidence,
                "source_ref": report_ref,
                "channel": route,
                "learned_at": at,
            }
        },
        "created_at": at,
    }
    planner.put(path, claim)

    claims = index.setdefault("claims", {})
    claims[information_ref] = path
    holder_refs = index.setdefault("by_holder", {}).setdefault(_PLAYER_REF, [])
    if information_ref not in holder_refs:
        holder_refs.append(information_ref)
        holder_refs.sort()
    planner.put(_INFO_INDEX_PATH, index)
    planner._register_owner(information_ref, path)

    subject_index = copy.deepcopy(
        planner.read_optional(_INFO_SUBJECT_INDEX_PATH)
        or {"schema": "sword-information-subject-index", "authority": False, "subjects": {}}
    )
    subjects = subject_index.setdefault("subjects", {})
    arc_dossier = subjects.setdefault(arc_ref, [])
    if information_ref not in arc_dossier:
        arc_dossier.append(information_ref)
        arc_dossier.sort()
    # Investigations are commonly opened from the newest delivered report.
    # Point that exact report subject at the accumulated arc dossier rather than
    # an empty one-off bucket, without changing any claim's truth authority.
    subjects[report_ref] = list(arc_dossier)
    source_refs = subjects.setdefault(source_event_ref, [])
    if information_ref not in source_refs:
        source_refs.append(information_ref)
        source_refs.sort()
    planner.put(_INFO_SUBJECT_INDEX_PATH, subject_index)
    return information_ref


__all__ = ["record_delivered_world_arc_report_information"]
