"""Causal exact-parent counsel for player-authored family conversations.

This layer closes a narrow social-flow gap without weakening the interaction
firewall. Tang Wei still authors only his own question. When that question asks
one of his exact parents for counsel about an exact player-visible process, the
runtime schedules that parent's own advisory response as a later causal event.
The response may recommend actions, but it never spends money, moves troops,
accepts obligations, creates House policy, or converts advice into a commitment.

The causal response itself is the exact durable owner.  Its ``advisory_record``
is explicitly nonbinding and preserves the speaker, interaction process, request,
topics, and advisory positions so a later scene reconstruction does not have to
rely on presentation-only dialogue memory.
"""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from sword_runtime.api.interaction_surface import interaction_attempt_ref, recent_interaction_attempts
from sword_runtime.campaign_communications import (
    command_endpoint_location,
    command_message_route,
    ensure_player_message_delivery,
    player_command_location,
)
from sword_runtime.causal_event_store import (
    get_causal_event,
    read_causal_event_owner,
    write_causal_event_owner,
)
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
    "do you think",
    "what would you do",
    "should we",
    "your counsel",
    "your advice",
    "your view",
    "advise me",
    "counsel me",
)
_TOPIC_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "field_doctrine",
        (
            "doctrine",
            "field army",
            "command by intent",
            "subordinate initiative",
        ),
    ),
    (
        "northern_wei_situation",
        (
            "northern wei",
            "wei situation",
            "qin operation",
            "qin-wei",
            "wei campaign",
        ),
    ),
    (
        "house_growth",
        (
            "house tang should grow",
            "house tang grow",
            "gain power",
            "gain greater influence",
            "grow stronger",
            "ambition for the house",
            "ambitions for it",
        ),
    ),
    (
        "sovereignty_and_diplomacy",
        (
            "declare independence",
            "independence from qin",
            "independent from qin",
            "break with qin",
            "secede",
            "sovereign",
            "alliance",
            "treaty",
        ),
    ),
)


def _ids(attempt_ref: str) -> tuple[str, str, str]:
    digest = hashlib.sha256(("family-counsel|" + attempt_ref).encode("utf-8")).hexdigest()[:20]
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


def _counsel_topics(question_text: object) -> tuple[str, ...]:
    text = str(question_text or "").strip().lower()
    topics = [
        topic
        for topic, patterns in _TOPIC_PATTERNS
        if any(pattern in text for pattern in patterns)
    ]
    return tuple(topics or ["general_counsel"])


def _counsel_positions(parent_ref: str, topics: Sequence[str]) -> list[str]:
    requested = set(str(topic) for topic in topics)
    positions: list[str] = []

    if parent_ref == "char_tang_ling":
        if "field_doctrine" in requested:
            positions.append(
                "Tang Ling favors the doctrine's clear division between Wei's reserved strategic decisions and subordinate initiative, but advises keeping Qin authority, House authority, expenditure, and responsibility separately legible so battlefield freedom does not blur political obligation."
            )
        if "northern_wei_situation" in requested:
            positions.append(
                "Tang Ling advises treating reports of a divided Qin court and a checked northern operation as potential leverage and potential danger at the same time: first verify which authorities, resources, and factions actually control the matter before House Tang binds itself to any interpretation of the campaign."
            )
        if "house_growth" in requested:
            positions.append(
                "Tang Ling favors diversified House power rather than simple numerical expansion: treasury resilience, productive workshops, remounts, stores, administration, logistics, commercial relationships, and political options should grow alongside military strength so House Tang is not dependent on one patron, one campaign, or one exceptional heir."
            )
        if "sovereignty_and_diplomacy" in requested:
            positions.append(
                "Tang Ling advises that comparative troop strength alone is not sovereignty. Independence would also require durable revenue, administration, territorial control, political legitimacy, external recognition or toleration, and the ability to survive retaliation or isolation. A negotiated treaty or alliance is potentially more reversible, but only if its exact military, fiscal, territorial, and diplomatic obligations are defined before acceptance."
            )
        if not positions:
            positions.append(
                "Tang Ling advises separating preparation from commitment: verify which authority owns the matter and what formal request, if any, actually reaches House Tang before spending new House silver or binding House forces. She favors preserving existing obligations while gathering firmer political and logistical information."
            )
    elif parent_ref == "char_tang_zhu":
        if "field_doctrine" in requested:
            positions.append(
                "Tang Zhu favors command by intent if the middle command echelons are trained hard enough to act without constant supervision while still recognizing the strategic decisions reserved to Wei. He advises judging the doctrine by whether officers can preserve cohesion, reserves, and assigned roles under pressure rather than by how elegant the written method appears."
            )
        if "northern_wei_situation" in requested:
            positions.append(
                "Tang Zhu advises not mistaking reports that an operation is blocked for proof of a battlefield opening. Before committing force, identify whether the real obstacle is command, route, supply, timing, enemy disposition, or some other concrete military problem, then solve that problem rather than merely seeking visible action."
            )
        if "house_growth" in requested:
            positions.append(
                "Tang Zhu favors military depth before breadth: more reliable commanders, training cadres, engineers, logistics, recovery capacity, and formations that remain coherent through repeated campaigning are more valuable than adding bodies faster than the House can command and sustain them."
            )
        if "sovereignty_and_diplomacy" in requested:
            positions.append(
                "Tang Zhu advises against treating a favorable troop comparison as sufficient reason for an irreversible break with Qin. Before independence, House Tang would need to prove it can hold and supply its forces, protect the territory and command structure that sustain them, and absorb the military response a break might provoke. If greater freedom can be won by negotiated terms without forcing that test immediately, he would examine those terms before choosing rupture."
            )
        if not positions:
            positions.append(
                "Tang Zhu advises preparing without pretending preparation is deployment: keep House military readiness in hand, clarify command, route, supply, timing, and the strength actually required, and do not march House forces into a state campaign merely because reports say an operation is forming."
            )
    else:
        raise ValueError("unsupported House Tang family-counsel parent")

    return positions


def _counsel_summary(parent_ref: str, source_summary: str, question_text: object = None) -> str:
    """Return bounded, topic-aware advice that creates no external commitment.

    ``source_summary`` is accepted only so the caller must have resolved one exact
    player-visible report/process first. Its content is deliberately not echoed,
    because the interaction attempt may not authorize disclosure of any hidden
    facts beyond the player-visible process itself.
    """
    del source_summary
    topics = _counsel_topics(question_text)
    return " ".join(_counsel_positions(parent_ref, topics))


def _settle_family_counsel(planner: Any, host: Mapping[str, Any], at: str) -> None:
    if not ensure_player_message_delivery(planner, host, at):
        return
    parent_ref = str(host.get("parent_ref", ""))
    process_ref = str(host.get("process_ref", ""))
    attempt_ref = str(host.get("attempt_ref", ""))
    if parent_ref not in _PARENT_REFS or not process_ref or not attempt_ref:
        raise ValueError("family counsel host lost its exact request identity")

    source = get_causal_event(planner, process_ref)
    if not isinstance(source, Mapping):
        raise ValueError("family counsel lost its exact source report")
    if source.get("status") != "triggered" or str(source.get("kind", "")) not in _ALLOWED_REPORT_KINDS:
        raise ValueError("family counsel source is not a triggered player-facing report")

    _host_id, _event_id, response_ref = _ids(attempt_ref)
    _path, owner = read_causal_event_owner(planner)
    if response_ref in owner["causal_events"]:
        return

    player = planner.read(_PLAYER_PATH)
    location_ref = str(player.get("location", "")) if isinstance(player, Mapping) else ""
    if not location_ref:
        raise ValueError("family counsel cannot resolve Tang Wei's delivery location")

    question_text = str(host.get("question_text", "") or "")
    topic_values = host.get("topic_tags")
    if isinstance(topic_values, Sequence) and not isinstance(topic_values, (str, bytes, bytearray)):
        topics = tuple(str(topic) for topic in topic_values if isinstance(topic, str) and topic)
    else:
        topics = ()
    if not topics:
        topics = _counsel_topics(question_text)
    positions = _counsel_positions(parent_ref, topics)
    parent_name = _PARENT_NAMES[parent_ref]
    advice = " ".join(positions)
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
        "advisory_record": {
            "schema": "sword-nonbinding-counsel.v1",
            "speaker_ref": parent_ref,
            "audience_ref": "char_tang_wei",
            "process_ref": process_ref,
            "topics": list(topics),
            "positions": positions,
            "binding": False,
            "creates_policy": False,
            "creates_commitment": False,
            "creates_authority": False,
        },
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

        attempts, _ = recent_interaction_attempts(self, "char_tang_wei", limit=_HISTORY_WINDOW)
        for attempt in attempts:
            if not _classify_family_counsel(attempt):
                continue
            process_ref = attempt.get("process_ref")
            parent_ref = attempt.get("target_ref")
            requested_at = attempt.get("at")
            if not all(isinstance(value, str) and value for value in (process_ref, parent_ref, requested_at)):
                continue
            attempt_ref = interaction_attempt_ref(attempt)

            host_id, event_id, response_ref = _ids(attempt_ref)
            if get_causal_event(self, response_ref) is not None or host_id in hosts:
                continue
            origin_location = attempt.get("origin_location_ref")
            if not isinstance(origin_location, str) or not origin_location:
                origin_location = player_command_location(self)
            parent_location = command_endpoint_location(self, parent_ref)
            if not origin_location or not parent_location:
                raise ValueError("family counsel request lacks exact physical communication endpoints")
            route = command_message_route(self.read, origin_location, parent_location, round_trip=True)
            travel_seconds = max(0, int(route.get("travel_seconds", 0) or 0))
            due = CampaignTime.parse(requested_at).add_seconds(travel_seconds + _COUNSEL_DELAY_SECONDS)
            if due < current:
                due = current
            question_text = str(attempt.get("player_statement", "") or "")[:2000]
            hosts[host_id] = {
                "host_id": host_id,
                "kind": "family_counsel",
                "owner_ref": parent_ref,
                "attempt_ref": attempt_ref,
                "parent_ref": parent_ref,
                "process_ref": process_ref,
                "question_text": question_text,
                "topic_tags": list(_counsel_topics(question_text)),
                "event_id": event_id,
                "request_origin_location_ref": origin_location,
                "parent_location_ref": parent_location,
                "response_target_location_ref": origin_location,
                "communication_travel_seconds": travel_seconds,
                "family_processing_seconds": _COUNSEL_DELAY_SECONDS,
                "courier_route": copy.deepcopy(dict(route)),
                "communication_rule": "request and counsel are not co-present unless geography says so; remote counsel requires physical round-trip delivery",
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

    # Due-host settlement is centrally dispatched by time_integration.py.


__all__ = [
    "FamilyCounselMixin",
    "_classify_family_counsel",
    "_counsel_positions",
    "_counsel_summary",
    "_counsel_topics",
]
