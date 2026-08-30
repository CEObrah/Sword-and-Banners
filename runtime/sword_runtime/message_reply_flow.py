"""Causal receipt for Tang Wei replies to exact delivered personal messages.

A delivered message is an established remote communication channel. When Tang
Wei answers that exact message, the sender can lawfully receive the reply after
a bounded courier delay. Receipt is deliberately narrower than compliance: it
does not move the sender, accept a promise, spend resources, or perform a
requested external action.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from sword_runtime.causal_event_store import get_causal_event_from_reader
from sword_runtime.contact_request_flow import _followup_response_ref
from sword_runtime.sim.calendar import CampaignTime


_LEDGER_PATH = "state/index/interaction-attempts.json"
_PLAYER_REF = "char_tang_wei"
_HISTORY_WINDOW = 256
_RECEIPT_DELAY_SECONDS = 30 * 60
_PRIORITY = 48
_REPLY_ACTIONS = frozenset({"ask", "request", "petition", "present", "report", "comply", "decline"})


def _digest(value: str) -> str:
    return hashlib.sha256(("message-reply|" + value).encode("utf-8")).hexdigest()[:20]


def _attempts(planner: Any) -> list[dict[str, Any]]:
    ledger = planner.read_optional(_LEDGER_PATH)
    rows = ledger.get("attempts", []) if isinstance(ledger, Mapping) else []
    if not isinstance(rows, list):
        return []
    return [dict(row) for row in rows[-_HISTORY_WINDOW:] if isinstance(row, Mapping) and row.get("actor_id") == _PLAYER_REF]


def _source_message(planner: Any, attempt: Mapping[str, Any]) -> Mapping[str, Any] | None:
    if attempt.get("action") not in _REPLY_ACTIONS:
        return None
    candidates = [attempt.get("target_ref"), attempt.get("process_ref")]
    for ref in candidates:
        if not isinstance(ref, str) or not ref:
            continue
        event = get_causal_event_from_reader(planner, ref)
        if not isinstance(event, Mapping):
            continue
        if event.get("kind") != "message" or event.get("status") != "triggered" or event.get("target_ref") != _PLAYER_REF:
            continue
        actor_ref = event.get("actor_ref")
        if isinstance(actor_ref, str) and actor_ref:
            return event
    return None


class MessageReplyFlowMixin:
    """Schedule sender receipt for replies made through exact delivered messages."""

    def _sync_contact_request_routes(self, runtime: dict[str, Any]) -> None:
        super()._sync_contact_request_routes(runtime)
        hosts = runtime.get("hosts")
        events = runtime.get("events")
        current_text = runtime.get("world_time")
        if not isinstance(hosts, dict) or not isinstance(events, list) or not isinstance(current_text, str):
            raise ValueError("runtime causal queue is invalid")
        current = CampaignTime.parse(current_text)
        for attempt in _attempts(self):
            attempt_ref = attempt.get("event_id")
            requested_at = attempt.get("at")
            if not isinstance(attempt_ref, str) or not attempt_ref or not isinstance(requested_at, str):
                continue
            if isinstance(attempt.get("response_ref"), str) and attempt.get("response_ref"):
                continue
            if isinstance(get_causal_event_from_reader(self, _followup_response_ref(attempt_ref)), Mapping):
                continue
            message = _source_message(self, attempt)
            if message is None:
                continue
            actor_ref = str(message["actor_ref"])
            source_ref = str(message.get("event_ref") or attempt.get("target_ref") or attempt.get("process_ref"))
            due = max(current, CampaignTime.parse(requested_at).add_seconds(_RECEIPT_DELAY_SECONDS))
            token = _digest(attempt_ref)
            host_id = f"host_message_reply_{token}"
            event_id = f"event_message_reply_due_{token}"
            if host_id in hosts:
                continue
            hosts[host_id] = {
                "host_id": host_id,
                "kind": "institutional_followup",
                "event_id": event_id,
                "owner_ref": actor_ref,
                "route_domain": "message_reply_receipt",
                "contact_ref": attempt_ref,
                "source_interaction_attempt_ref": attempt_ref,
                "source_event_id": attempt_ref,
                "source_process_ref": source_ref,
                "source_owner_ref": actor_ref,
                "actor_ref": actor_ref,
                "response_stage": "reply_received",
                "response_summary": (
                    "The sender has received Tang Wei's reply through the established message channel. "
                    "This receipt does not by itself move the sender, accept a promise, spend resources, "
                    "or establish that any requested travel or other external action has occurred."
                ),
                "delivery_route": "return household or institutional courier through the source message channel",
                "recurrence_seconds": 0,
                "next_due": str(due),
                "resolved_through": str(current if current < due else due.add_seconds(-1)),
                "safe_through": str(due.add_seconds(-1)),
            }
            events.append({
                "event_id": event_id,
                "kind": "institutional_followup",
                "priority": _PRIORITY,
                "target_host": host_id,
                "due_at": str(due),
            })


__all__ = ["MessageReplyFlowMixin"]
