"""Causal exact-parent counsel for player-authored family conversations.

This layer closes a narrow social-flow gap without weakening the interaction
firewall. Tang Wei still authors only his own question. When that question asks
one of his exact parents for counsel about an exact player-visible report, the
runtime schedules that parent's own advisory response as a later causal event.
The response may recommend actions, but it never spends money, moves troops,
accepts obligations, or converts advice into House policy.
"""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from typing import Any

from sword_runtime.api.interaction_surface import parse_interaction_attempt_summary
from sword_runtime.causal_event_store import (
    get_causal_event,
    read_causal_event_owner,
    write_causal_event_owner,
)
from sword_runtime.history_store import recent_history_events
from sword_runtime.sim.calendar import CampaignTime

_RUNTIME_PATH = "state/runtime.json"
_PLAYER_PATH = "state/player.json"
_PARENT_NAMES = {
    "char_tang_ling": "Tang Ling",
    "char_tang_zhu": "Tang Zhu",
}
_PARENT_REFS = frozenset(_PARENT_NAMES)
_HISTORY_WINDOW = 256
_COUNSEL_DELAY_SECONDS = 15 * 60
_ALLOWED_REPORT_KINDS = frozenset({
    "world_arc_report",
    "institutional_response",
    "message",
    "petition_response",
    "audience_response",
})
_COUNSEL_PHRASES = (
    "what could we do",
    "what can we do",
    "what should we do",
    "what do you think",
    "what would you do",
    "your counsel",
    "your advice",
    "advise me",
    "counsel me",
)


def _ids(request_id: str) -> tuple[str, str, str]:
    digest = hashlib.sha256(("family-counsel|" + request_id).encode("utf-8")).hexdigest()[:20]
    return (
        f"host_family_counsel_{digest}",
        f"event_family_counsel_{digest}",
        f"event_family_counsel_response_{digest}",
    )


def _classify_family_counsel(attempt: Mapping[str, Any]) -> bool:
    if attempt.get("actor_id") != "char_tang_wei":
        return False
    if attempt.get("target_ref") not in _PARENT_REFS:
        return False
    if attempt.get("action") not in {"ask", "present", "request"}:
        return False
    process_ref = attempt.get("process_ref")
    if not isinstance(process_ref, str) or not process_ref:
        return False
    text = str(attempt.get("player_statement", "")).strip().lower()
    return bool(text) and any(phrase in text for phrase in _COUNSEL_PHRASES)


def _counsel_summary(parent_ref: str, source_summary: str) -> str:
    """Return bounded advice that creates no external commitment.

    The source summary is accepted only so the caller must have resolved one exact
    player-visible report first. The advice intentionally does not extrapolate
    hidden campaign truth from it.
    """
    del source_summary
    if parent_ref == "char_tang_ling":
        return (
            "Tang Ling advises separating preparation from commitment: verify which Qin authority owns the matter and what formal request, if any, actually reaches House Tang before spending new House silver or binding House forces. In the meantime she recommends preserving the House's existing obligations and gathering firmer political and logistical information rather than treating preparations as a settled campaign result."
        )
    if parent_ref == "char_tang_zhu":
        return (
            "Tang Zhu advises preparing without pretending preparation is deployment: keep House military readiness in hand, clarify command, route, supply, timing, and the strength Qin actually requires, and do not march House forces into a state campaign merely because reports say an operation is forming. He recommends acting once a lawful command or a deliberate House decision gives the effort a concrete objective."
        )
    raise ValueError("unsupported House Tang family-counsel parent")


def _settle_family_counsel(planner: Any, host: Mapping[str, Any], at: str) -> None:
    parent_ref = str(host.get("parent_ref", ""))
    process_ref = str(host.get("process_ref", ""))
    request_id = str(host.get("request_id", ""))
    if parent_ref not in _PARENT_REFS or not process_ref or not request_id:
        raise ValueError("family counsel host lost its exact request identity")

    source = get_causal_event(planner, process_ref)
    if not isinstance(source, Mapping):
        raise ValueError("family counsel lost its exact source report")
    if source.get("status") != "triggered" or str(source.get("kind", "")) not in _ALLOWED_REPORT_KINDS:
        raise ValueError("family counsel source is not a triggered player-facing report")

    _host_id, _event_id, response_ref = _ids(request_id)
    _path, owner = read_causal_event_owner(planner)
    if response_ref in owner["causal_events"]:
        return

    player = planner.read(_PLAYER_PATH)
    location_ref = str(player.get("location", "")) if isinstance(player, Mapping) else ""
    if not location_ref:
        raise ValueError("family counsel cannot resolve Tang Wei's delivery location")

    parent_name = _PARENT_NAMES[parent_ref]
    advice = _counsel_summary(parent_ref, str(source.get("summary", "")))
    owner["causal_events"][response_ref] = {
        "event_ref": response_ref,
        "kind": "institutional_response",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "actor_ref": parent_ref,
        "target_ref": "char_tang_wei",
        "basis_goal": f"{parent_name} responds to Tang Wei's request for counsel"[:500],
        "process_kind": "house_tang_family_counsel",
        "process_stage": "responded",
        "summary": advice[:4000],
        "source_event_ref": process_ref,
        "delivery": {
            "target_ref": "char_tang_wei",
            "location_ref": location_ref,
            "route": "House Tang family counsel",
        },
        "provenance": {
            "kind": "causal_runtime_settlement",
            "source_owner_ref": parent_ref,
            "work_ref": response_ref,
            "late_catch_up": False,
        },
    }
    owner.setdefault("runtime", {})["last_settled_at"] = at
    write_causal_event_owner(planner, owner)


class FamilyCounselMixin:
    """Schedule exact-parent advisory responses from typed interaction history."""

    def _sync_family_counsel_routes(self, runtime: dict[str, Any]) -> None:
        hosts = runtime.get("hosts")
        events = runtime.get("events")
        if not isinstance(hosts, dict) or not isinstance(events, list):
            raise ValueError("runtime causal queue is invalid")
        current = CampaignTime.parse(str(runtime["world_time"]))

        for event in recent_history_events(self, _HISTORY_WINDOW):
            if not isinstance(event, Mapping):
                continue
            attempt = parse_interaction_attempt_summary(event.get("summary"))
            if not isinstance(attempt, Mapping) or not _classify_family_counsel(attempt):
                continue
            request_id = attempt.get("request_id")
            process_ref = attempt.get("process_ref")
            parent_ref = attempt.get("target_ref")
            requested_at = event.get("at")
            if not all(isinstance(value, str) and value for value in (request_id, process_ref, parent_ref, requested_at)):
                continue

            host_id, event_id, response_ref = _ids(request_id)
            if get_causal_event(self, response_ref) is not None or host_id in hosts:
                continue
            due = CampaignTime.parse(requested_at).add_seconds(_COUNSEL_DELAY_SECONDS)
            if due < current:
                due = current
            hosts[host_id] = {
                "host_id": host_id,
                "kind": "family_counsel",
                "owner_ref": parent_ref,
                "request_id": request_id,
                "parent_ref": parent_ref,
                "process_ref": process_ref,
                "event_id": event_id,
                "recurrence_seconds": 0,
                "next_due": str(due),
                "resolved_through": str(current if current < due else due.add_seconds(-1)),
                "safe_through": str(due.add_seconds(-1)),
            }
            events.append({
                "event_id": event_id,
                "kind": "family_counsel",
                "priority": 47,
                "target_host": host_id,
                "due_at": str(due),
            })

    def _advance_runtime(self, target_text: str) -> dict[str, Any]:
        runtime = copy.deepcopy(self.read(_RUNTIME_PATH))
        self._sync_family_counsel_routes(runtime)
        self.put(_RUNTIME_PATH, runtime)
        return super()._advance_runtime(target_text)

    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        if host.get("kind") == "family_counsel":
            _settle_family_counsel(self, host, due_text)
            self._pending_wake_created = None
            return
        super()._run_due_host(host, due_text)


__all__ = [
    "FamilyCounselMixin",
    "_classify_family_counsel",
    "_counsel_summary",
]
