"""Read-only interaction routing diagnostics for OOC playability review.

A valid player attempt is not automatically a valid causal handoff. This module
classifies recent response-expecting attempts as already answered, scheduled,
lawfully routable on the next scheduler reconciliation, legacy-invalid under the
current access contract, or genuinely unrouted. It never schedules work or edits
campaign truth.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sword_runtime.campaign_command_contact import _campaign_cycle_for_attempt
from sword_runtime.campaign_command_decision import campaign_command_follow_on_route
from sword_runtime.campaign_command_requests import _cycle_for_attempt as _campaign_request_cycle
from sword_runtime.campaign_command_requests import _operation_for_cycle as _campaign_operation_for_cycle
from sword_runtime.campaign_command_requests import _request_topics as _campaign_request_topics
from sword_runtime.causal_event_store import get_causal_event_from_reader, iter_causal_events_newest
from sword_runtime.contact_request_flow import (
    _disposition_response_ref,
    _followup_response_ref,
    _response_ref,
    _route_for_attempt,
)
from sword_runtime.message_reply_flow import _source_message


_LEDGER_PATH = "state/index/interaction-attempts.json"
_RESPONSE_ACTIONS = frozenset({"ask", "request", "petition", "seek_contact"})
_HISTORY_WINDOW = 256


def _read_optional(source: Any, path: str) -> Any:
    if hasattr(source, "read_optional"):
        return source.read_optional(path)
    if hasattr(source, "read_json"):
        try:
            return source.read_json(path)
        except FileNotFoundError:
            return None
    raise TypeError("interaction routing audit requires a JSON reader")


def _owner_path(source: Any, ref: str) -> str | None:
    if hasattr(source, "owner_path"):
        try:
            value = source.owner_path(ref)
            return str(value) if isinstance(value, str) and value else None
        except (KeyError, FileNotFoundError, ValueError):
            return None
    index = _read_optional(source, "state/index/owner-index.json")
    owners = index.get("owners") if isinstance(index, Mapping) else None
    value = owners.get(ref) if isinstance(owners, Mapping) else None
    return str(value) if isinstance(value, str) and value else None


def _attempt_rows(source: Any) -> list[dict[str, Any]]:
    ledger = _read_optional(source, _LEDGER_PATH)
    rows = ledger.get("attempts", []) if isinstance(ledger, Mapping) else []
    if not isinstance(rows, list):
        return []
    return [dict(row) for row in rows[-_HISTORY_WINDOW:] if isinstance(row, Mapping)]


def _response_expected_attempt(attempt: Mapping[str, Any]) -> bool:
    """Respect explicit response intent while preserving legacy action inference."""
    if "expects_response" in attempt:
        return attempt.get("expects_response") is True
    return attempt.get("action") in _RESPONSE_ACTIONS


def _pending_for(runtime: Mapping[str, Any], attempt_ref: str) -> bool:
    hosts = runtime.get("hosts") if isinstance(runtime, Mapping) else None
    if not isinstance(hosts, Mapping):
        return False
    for host in hosts.values():
        if not isinstance(host, Mapping) or not isinstance(host.get("next_due"), str):
            continue
        for key in ("contact_ref", "work_ref", "source_event_id", "source_interaction_attempt_ref"):
            if host.get(key) == attempt_ref:
                return True
    return False


def _answered_by_known_ref(source: Any, attempt_ref: str) -> bool:
    for ref in (_response_ref(attempt_ref), _disposition_response_ref(attempt_ref), _followup_response_ref(attempt_ref)):
        if isinstance(get_causal_event_from_reader(source, ref), Mapping):
            return True
    return False


def _answered_by_provenance(source: Any, attempt_ref: str) -> bool:
    for _event_ref, event in iter_causal_events_newest(
        source,
        kinds={"audience_response", "institutional_response", "petition_response", "message"},
    ):
        if not isinstance(event, Mapping):
            continue
        provenance = event.get("provenance") if isinstance(event.get("provenance"), Mapping) else {}
        if (
            event.get("source_interaction_attempt_ref") == attempt_ref
            or event.get("source_event_ref") == attempt_ref
            or provenance.get("source_work_ref") == attempt_ref
        ):
            return True
    return False


def _campaign_follow_on_state(source: Any, attempt: Mapping[str, Any]) -> str | None:
    """Return the exact command-chain state for a follow-on request.

    The ordinary upward report is the authority for superior receipt. A request
    is answered only when a decision order tied to it has itself been physically
    delivered to Tang Wei. Historical generic ``institutional_followup`` review
    events are therefore not treated as substantive answers for this domain.
    """
    route = campaign_command_follow_on_route(source, attempt)
    if route is None:
        return None
    cycle_ref = route.get("cycle_ref")
    attempt_ref = attempt.get("event_id")
    if not isinstance(cycle_ref, str) or not cycle_ref or not isinstance(attempt_ref, str) or not attempt_ref:
        return "routable"
    path = _owner_path(source, cycle_ref)
    cycle = _read_optional(source, path) if isinstance(path, str) else None
    if not isinstance(cycle, Mapping):
        return "routable"

    delivered_orders = {
        str(ref) for ref in cycle.get("delivered_superior_order_refs", [])
        if isinstance(ref, str) and ref
    }
    decisions = cycle.get("campaign_command_decisions") if isinstance(cycle.get("campaign_command_decisions"), list) else []
    for decision in decisions:
        if not isinstance(decision, Mapping):
            continue
        requests = {
            str(ref) for ref in decision.get("follow_on_request_refs", [])
            if isinstance(ref, str) and ref
        }
        if attempt_ref not in requests:
            continue
        order_ref = decision.get("order_ref")
        if isinstance(order_ref, str) and order_ref in delivered_orders:
            return "answered"
        return "pending"

    reports = cycle.get("upward_reports") if isinstance(cycle.get("upward_reports"), list) else []
    for report in reversed(reports):
        if not isinstance(report, Mapping):
            continue
        requests = {
            str(ref) for ref in report.get("follow_on_request_refs", [])
            if isinstance(ref, str) and ref
        }
        if attempt_ref not in requests:
            continue
        status = str(report.get("delivery_status", ""))
        if status in {"in_transit", "delivered"}:
            return "pending"
        if status == "route_unresolved":
            return "routable"
    return "routable"


def _route_available(source: Any, attempt: Mapping[str, Any]) -> bool:
    if _route_for_attempt(source, attempt) is not None:
        return True
    if _campaign_cycle_for_attempt(source, attempt) is not None:
        return True
    # Campaign follow-on requests use one shared physical resolver for public
    # admission and the command-decision owner. Actual outbound receipt travels
    # through the ordinary upward campaign report rather than a second review host.
    if campaign_command_follow_on_route(source, attempt) is not None:
        return True
    topics = _campaign_request_topics(attempt)
    if topics:
        cycle = _campaign_request_cycle(source, attempt)
        if cycle is not None and _campaign_operation_for_cycle(source, cycle) is not None:
            return True
    if _source_message(source, attempt) is not None:
        return True
    return False


def _person_access_legacy_invalid(source: Any, attempt: Mapping[str, Any]) -> bool:
    target_ref = attempt.get("target_ref")
    if not isinstance(target_ref, str):
        return False
    owner_index = _read_optional(source, "state/index/owner-index.json")
    owners = owner_index.get("owners", {}) if isinstance(owner_index, Mapping) else {}
    path = owners.get(target_ref) if isinstance(owners, Mapping) else None
    if not isinstance(path, str):
        return False
    is_person = path == "state/player.json" or path.startswith("state/char/")
    if not is_person and path.startswith("state/person/"):
        row = _read_optional(source, path)
        is_person = isinstance(row, Mapping) and str(row.get("schema", "")) in {"sab_character", "person-lite", "sword-materialized-person"}
    if not is_person:
        return False
    if attempt.get("action") == "seek_contact":
        return False
    if isinstance(attempt.get("scene_session_ref"), str) and attempt.get("scene_session_ref"):
        return False
    process_ref = attempt.get("process_ref")
    if isinstance(process_ref, str):
        process = get_causal_event_from_reader(source, process_ref)
        if isinstance(process, Mapping) and process.get("actor_ref") == target_ref and process.get("kind") in {
            "message", "audience_response", "institutional_response", "petition_response"
        }:
            return False
    return True


def summarize_interaction_routing(source: Any) -> dict[str, Any]:
    """Return bounded diagnostics without changing scheduler or interaction state."""
    runtime = _read_optional(source, "state/runtime.json")
    runtime = runtime if isinstance(runtime, Mapping) else {}
    response_expected = 0
    answered = 0
    pending = 0
    routable = 0
    unrouted: list[str] = []
    legacy_invalid: list[str] = []

    for attempt in _attempt_rows(source):
        if attempt.get("actor_id") != "char_tang_wei" or not _response_expected_attempt(attempt):
            continue
        if attempt.get("thread_status") == "abandoned_with_scene_close":
            continue
        attempt_ref = attempt.get("event_id")
        if not isinstance(attempt_ref, str) or not attempt_ref:
            continue
        response_expected += 1

        campaign_state = _campaign_follow_on_state(source, attempt)
        if campaign_state is not None:
            if campaign_state == "answered":
                answered += 1
            elif campaign_state == "pending":
                pending += 1
            elif _route_available(source, attempt):
                routable += 1
            else:
                unrouted.append(attempt_ref)
            continue

        if isinstance(attempt.get("response_ref"), str) and attempt.get("response_ref"):
            answered += 1
            continue
        if _answered_by_known_ref(source, attempt_ref) or _answered_by_provenance(source, attempt_ref):
            answered += 1
            continue
        if _pending_for(runtime, attempt_ref):
            pending += 1
            continue
        if _route_available(source, attempt):
            routable += 1
            continue
        if _person_access_legacy_invalid(source, attempt):
            legacy_invalid.append(attempt_ref)
        else:
            unrouted.append(attempt_ref)

    diagnostics: list[str] = []
    suggestions: list[str] = []
    if unrouted:
        diagnostics.append("player_interaction_attempt_without_causal_response_route")
        suggestions.append("reject_or_route_response_expectant_interaction_before_treating_it_as_pending")
    if legacy_invalid:
        diagnostics.append("legacy_person_interaction_lacked_established_access")
        suggestions.append("do_not_replay_legacy_access_invalid_attempts; require_present_person_or_exact_remote_channel")
    return {
        "response_expected_attempts": response_expected,
        "answered_attempts": answered,
        "pending_routed_attempts": pending,
        "routable_on_next_scheduler_reconcile": routable,
        "unrouted_attempts": len(unrouted),
        "unrouted_attempt_refs": unrouted[:16],
        "legacy_invalid_access_attempts": len(legacy_invalid),
        "legacy_invalid_access_attempt_refs": legacy_invalid[:16],
        "diagnostics": diagnostics,
        "suggestions": suggestions,
    }


__all__ = ["summarize_interaction_routing"]
