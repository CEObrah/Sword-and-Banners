"""Causal institutional contact, disposition, and follow-up routing."""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from typing import Any

from sword_runtime.api.interaction_surface import parse_interaction_attempt_summary
from sword_runtime.causal_event_store import (
    get_causal_event_from_reader,
    read_causal_event_owner,
    write_causal_event_owner,
)
from sword_runtime.history_store import recent_history_events
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.transaction_invalidations import invalidated_request_ids

_RUNTIME_PATH = "state/runtime.json"
_RULES_PATH = "game/data/politics/contact-routes.json"
_HISTORY_WINDOW = 256


def _digest(prefix: str, request_id: str) -> str:
    return hashlib.sha256(f"{prefix}|{request_id}".encode("utf-8")).hexdigest()[:20]


def _request_ids(request_id: str) -> tuple[str, str]:
    d = _digest("institutional-contact", request_id)
    return f"host_contact_request_{d}", f"event_contact_request_{d}"


def _response_ref(request_id: str) -> str:
    return f"event_contact_audience_{_digest('institutional-contact-response', request_id)}"


def _disposition_ids(request_id: str) -> tuple[str, str]:
    d = _digest("institutional-disposition", request_id)
    return f"host_audience_disposition_{d}", f"event_audience_disposition_{d}"


def _disposition_response_ref(request_id: str) -> str:
    return f"event_petition_response_{_digest('institutional-disposition-response', request_id)}"


def _followup_ids(request_id: str) -> tuple[str, str]:
    d = _digest("institutional-followup", request_id)
    return f"host_institutional_followup_{d}", f"event_institutional_followup_{d}"


def _followup_response_ref(request_id: str) -> str:
    return f"event_institutional_followup_response_{_digest('institutional-followup-response', request_id)}"


def _routes(planner: Any) -> list[Mapping[str, Any]]:
    rules = planner.read(_RULES_PATH)
    rows = rules.get("routes", []) if isinstance(rules, Mapping) else []
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise ValueError("institutional contact route registry is invalid")
    return rows


def _followup_specs(planner: Any) -> list[Mapping[str, Any]]:
    rules = planner.read(_RULES_PATH)
    rows = rules.get("followup_requests", []) if isinstance(rules, Mapping) else []
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise ValueError("institutional follow-up registry is invalid")
    return rows


def _route_for_attempt(planner: Any, attempt: Mapping[str, Any]) -> Mapping[str, Any] | None:
    if attempt.get("actor_id") != "char_tang_wei" or attempt.get("action") != "seek_contact":
        return None
    location_ref, process_ref = attempt.get("target_ref"), attempt.get("process_ref")
    if not isinstance(location_ref, str) or not location_ref.startswith("loc_") or not isinstance(process_ref, str):
        return None
    process = get_causal_event_from_reader(planner, process_ref)
    arc_ref = process.get("arc_ref") if isinstance(process, Mapping) else None
    if not isinstance(arc_ref, str):
        return None
    for route in _routes(planner):
        if route.get("location_ref") == location_ref and route.get("arc_ref") == arc_ref:
            if not isinstance(route.get("institution_ref"), str) or not isinstance(route.get("delay_seconds"), int):
                raise ValueError("institutional contact route is incomplete")
            return route
    return None


def _match_disposition(planner: Any, attempt: Mapping[str, Any]):
    if attempt.get("actor_id") != "char_tang_wei" or not isinstance(attempt.get("process_ref"), str):
        return None
    process = get_causal_event_from_reader(planner, str(attempt["process_ref"]))
    if not isinstance(process, Mapping) or process.get("kind") != "audience_response" or process.get("status") != "triggered":
        return None
    if process.get("target_ref") != "char_tang_wei" or not isinstance(process.get("actor_ref"), str):
        return None
    source = get_causal_event_from_reader(planner, str(process.get("source_event_ref", "")))
    arc_ref = source.get("arc_ref") if isinstance(source, Mapping) else None
    statement = attempt.get("player_statement")
    if not isinstance(statement, str):
        return None
    text = " ".join(statement.lower().split())
    for route in _routes(planner):
        if route.get("institution_ref") != process.get("actor_ref"):
            continue
        if isinstance(arc_ref, str) and route.get("arc_ref") != arc_ref:
            continue
        specs = route.get("audience_dispositions", [])
        if not isinstance(specs, list):
            raise ValueError("audience disposition registry is invalid")
        for spec in specs:
            if not isinstance(spec, Mapping) or attempt.get("action") not in spec.get("actions", []):
                continue
            required = spec.get("statement_all_terms", [])
            alternatives = spec.get("statement_any_phrases", [])
            if not isinstance(required, list) or not isinstance(alternatives, list):
                raise ValueError("audience disposition matcher is invalid")
            if any(not isinstance(v, str) for v in [*required, *alternatives]):
                raise ValueError("audience disposition matcher is invalid")
            if any(v.lower() not in text for v in required):
                continue
            if alternatives and not any(v.lower() in text for v in alternatives):
                continue
            return route, spec, process
    return None


def _match_followup(planner: Any, attempt: Mapping[str, Any]):
    if attempt.get("actor_id") != "char_tang_wei" or not isinstance(attempt.get("process_ref"), str):
        return None
    process_ref = str(attempt["process_ref"])
    process = get_causal_event_from_reader(planner, process_ref)
    if not isinstance(process, Mapping) or process.get("kind") != "institutional_response" or process.get("status") != "triggered":
        return None
    statement = attempt.get("player_statement")
    if not isinstance(statement, str):
        return None
    text = " ".join(statement.lower().split())
    for spec in _followup_specs(planner):
        actions = spec.get("actions", [])
        if not isinstance(actions, list) or any(not isinstance(v, str) for v in actions):
            raise ValueError("institutional follow-up actions are invalid")
        if attempt.get("action") not in actions:
            continue
        exact_source = spec.get("source_event_ref")
        if isinstance(exact_source, str) and exact_source and process_ref != exact_source:
            continue
        process_kind = spec.get("source_process_kind")
        if isinstance(process_kind, str) and process_kind and process.get("process_kind") != process_kind:
            continue
        process_stage = spec.get("source_process_stage")
        if isinstance(process_stage, str) and process_stage and process.get("process_stage") != process_stage:
            continue
        actor_ref = spec.get("source_actor_ref")
        if isinstance(actor_ref, str) and actor_ref and process.get("actor_ref") != actor_ref:
            continue
        required = spec.get("statement_all_terms", [])
        alternatives = spec.get("statement_any_terms", [])
        if not isinstance(required, list) or not isinstance(alternatives, list):
            raise ValueError("institutional follow-up matcher is invalid")
        if any(not isinstance(v, str) for v in [*required, *alternatives]):
            raise ValueError("institutional follow-up matcher is invalid")
        if any(v.lower() not in text for v in required):
            continue
        if alternatives and not any(v.lower() in text for v in alternatives):
            continue
        return spec, process
    return None


def _prior_present_count(planner: Any, process_ref: str) -> int:
    invalidated = invalidated_request_ids(planner)
    count = 0
    for event in recent_history_events(planner, _HISTORY_WINDOW):
        attempt = parse_interaction_attempt_summary(event.get("summary")) if isinstance(event, Mapping) else None
        if not isinstance(attempt, Mapping) or attempt.get("request_id") in invalidated:
            continue
        if attempt.get("actor_id") == "char_tang_wei" and attempt.get("process_ref") == process_ref and attempt.get("action") == "present":
            count += 1
    return count


def _score_disposition(planner: Any, process_ref: str, spec: Mapping[str, Any]) -> tuple[str, int, int]:
    scoring = spec.get("scoring")
    if not isinstance(scoring, Mapping):
        raise ValueError("audience disposition scoring is invalid")
    player = planner.read("state/player.json")
    attrs = player.get("attributes", {}) if isinstance(player, Mapping) else {}
    skills = player.get("skills", {}) if isinstance(player, Mapping) else {}
    attr_keys, skill_keys = scoring.get("attributes", []), scoring.get("skills", [])
    if not isinstance(attr_keys, list) or not isinstance(skill_keys, list):
        raise ValueError("audience disposition scoring keys are invalid")

    def mean(src: Mapping[str, Any], keys: list[str]) -> float:
        vals = [
            float(src[key]) for key in keys
            if isinstance(src.get(key), (int, float)) and not isinstance(src.get(key), bool)
        ]
        return sum(vals) / len(vals) if vals else 0.0

    aw, sw = int(scoring.get("attribute_weight", 1)), int(scoring.get("skill_weight", 1))
    if aw < 0 or sw < 0 or aw + sw <= 0:
        raise ValueError("audience disposition scoring weights are invalid")
    raw = (mean(attrs, attr_keys) * aw + mean(skills, skill_keys) * sw) / (aw + sw)
    score = max(0, min(1000, int(round(raw * 5))))
    prior = _prior_present_count(planner, process_ref)
    recommend = int(scoring.get("recommend_threshold", 1001))
    refer = int(scoring.get("refer_threshold", 1001))
    minimum = int(spec.get("minimum_prior_present_attempts", 0))
    if prior >= minimum and score >= recommend:
        return "recommended", score, prior
    if score >= refer:
        return "referred", score, prior
    return "declined", score, prior


def _precommit_disposition(planner: Any, process_ref: str, spec: Mapping[str, Any]) -> tuple[str, str]:
    outcome, _score, _prior = _score_disposition(planner, process_ref, spec)
    summary = spec.get(f"{outcome}_summary")
    if not isinstance(summary, str) or not summary:
        raise ValueError("audience disposition outcome summary is missing")
    return outcome, summary[:4000]


def _write_player_event(planner: Any, event_ref: str, row: Mapping[str, Any], at: str) -> str:
    if get_causal_event_from_reader(planner, event_ref) is not None:
        return event_ref
    _path, owner = read_causal_event_owner(planner)
    owner["causal_events"][event_ref] = dict(row)
    owner.setdefault("runtime", {})["last_settled_at"] = at
    write_causal_event_owner(planner, owner)
    return event_ref


def _settle_contact_request(planner: Any, host: Mapping[str, Any], at: str) -> str:
    required = ("request_id", "institution_ref", "route_ref", "source_process_ref", "audience_summary", "delivery_route")
    if any(not isinstance(host.get(k), str) or not host.get(k) for k in required):
        raise ValueError("institutional contact host is invalid")
    player = planner.read("state/player.json")
    location_ref = player.get("location")
    if not isinstance(location_ref, str):
        raise ValueError("institutional contact delivery lost player location")
    event_ref = _response_ref(str(host["request_id"]))
    return _write_player_event(planner, event_ref, {
        "event_ref": event_ref,
        "kind": "audience_response",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "actor_ref": host["institution_ref"],
        "target_ref": "char_tang_wei",
        "route_ref": host["route_ref"],
        "route_domain": str(host.get("route_domain") or "institutional_contact"),
        "basis_goal": f"Receiving access for player contact request {host['request_id']}"[:500],
        "process_kind": "institutional_contact",
        "process_stage": "audience_ready",
        "source_event_ref": host["source_process_ref"],
        "summary": str(host["audience_summary"])[:4000],
        "delivery": {"target_ref": "char_tang_wei", "location_ref": location_ref, "route": str(host["delivery_route"])[:1000]},
        "provenance": {"kind": "causal_runtime_settlement", "source_owner_ref": host["institution_ref"], "work_ref": event_ref, "late_catch_up": False},
    }, at)


def _settle_audience_disposition(planner: Any, host: Mapping[str, Any], at: str) -> str:
    outcome = host.get("disposition_outcome")
    summary = host.get("response_summary")
    if not isinstance(outcome, str) or outcome not in {"recommended", "referred", "declined"} or not isinstance(summary, str) or not summary:
        spec = host.get("disposition_spec")
        if not isinstance(spec, Mapping):
            raise ValueError("audience disposition host is invalid")
        outcome, summary = _precommit_disposition(planner, str(host.get("source_process_ref", "")), spec)
    institution_ref = host.get("institution_ref")
    source_process_ref = host.get("source_process_ref")
    if not isinstance(institution_ref, str) or not institution_ref or not isinstance(source_process_ref, str) or not source_process_ref:
        raise ValueError("audience disposition host lost its exact institutional identity")
    player = planner.read("state/player.json")
    location_ref = player.get("location")
    if not isinstance(location_ref, str) or not location_ref:
        raise ValueError("audience disposition delivery lost player location")
    event_ref = _disposition_response_ref(str(host.get("request_id", "")))
    return _write_player_event(planner, event_ref, {
        "event_ref": event_ref,
        "kind": "institutional_response",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "actor_ref": institution_ref,
        "target_ref": "char_tang_wei",
        "basis_goal": f"Qin Military Bureau responds to Tang Wei's service recommendation request"[:500],
        "process_kind": "institutional_disposition",
        "process_stage": outcome,
        "summary": summary[:4000],
        "source_event_ref": source_process_ref,
        "delivery": {
            "target_ref": "char_tang_wei",
            "location_ref": location_ref,
            "route": str(host.get("delivery_route", "Qin Military Bureau receiving office in Kanyou"))[:1000],
        },
        "provenance": {
            "kind": "causal_runtime_settlement",
            "source_owner_ref": institution_ref,
            "work_ref": event_ref,
            "late_catch_up": False,
        },
    }, at)


def _settle_institutional_followup(planner: Any, host: Mapping[str, Any], at: str) -> str:
    required = ("request_id", "source_process_ref", "source_owner_ref", "response_summary", "delivery_route", "response_stage")
    if any(not isinstance(host.get(k), str) or not host.get(k) for k in required):
        raise ValueError("institutional follow-up host is invalid")
    player = planner.read("state/player.json")
    location_ref = player.get("location")
    if not isinstance(location_ref, str) or not location_ref:
        raise ValueError("institutional follow-up delivery lost player location")
    event_ref = _followup_response_ref(str(host["request_id"]))
    row: dict[str, Any] = {
        "event_ref": event_ref,
        "kind": "institutional_response",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "target_ref": "char_tang_wei",
        "basis_goal": f"Institutional answer to Tang Wei follow-up request {host['request_id']}"[:500],
        "process_kind": "institutional_followup",
        "process_stage": str(host["response_stage"])[:120],
        "source_event_ref": host["source_process_ref"],
        "summary": str(host["response_summary"])[:4000],
        "delivery": {
            "target_ref": "char_tang_wei",
            "location_ref": location_ref,
            "route": str(host["delivery_route"])[:1000],
        },
        "provenance": {
            "kind": "causal_runtime_settlement",
            "source_owner_ref": str(host["source_owner_ref"]),
            "work_ref": event_ref,
            "late_catch_up": bool(host.get("late_catch_up", False)),
        },
    }
    actor_ref = host.get("actor_ref")
    if isinstance(actor_ref, str) and actor_ref:
        row["actor_ref"] = actor_ref
    return _write_player_event(planner, event_ref, row, at)


class ContactRequestFlowMixin:
    """Schedule institution-owned contact, disposition, and follow-up responses."""

    def _schedule_one_shot(self, runtime: dict[str, Any], *, host_id: str, event_id: str, kind: str, priority: int, due: CampaignTime, row: dict[str, Any]) -> None:
        hosts, events = runtime.get("hosts"), runtime.get("events")
        if not isinstance(hosts, dict) or not isinstance(events, list):
            raise ValueError("runtime causal queue is invalid")
        if host_id in hosts:
            return
        row.update({"host_id": host_id, "kind": kind, "event_id": event_id, "recurrence_seconds": 0, "next_due": str(due), "safe_through": str(due.add_seconds(-1))})
        hosts[host_id] = row
        if not any(isinstance(e, Mapping) and e.get("event_id") == event_id for e in events):
            events.append({"event_id": event_id, "kind": kind, "priority": priority, "target_host": host_id, "due_at": str(due)})

    def _sync_contact_request_routes(self, runtime: dict[str, Any]) -> None:
        current_text = runtime.get("world_time")
        hosts = runtime.get("hosts")
        if not isinstance(current_text, str) or not isinstance(hosts, dict):
            raise ValueError("runtime causal queue is invalid")
        current = CampaignTime.parse(current_text)
        invalidated = invalidated_request_ids(self)
        for event in recent_history_events(self, _HISTORY_WINDOW):
            attempt = parse_interaction_attempt_summary(event.get("summary")) if isinstance(event, Mapping) else None
            if not isinstance(attempt, Mapping) or attempt.get("request_id") in invalidated:
                continue
            request_id, requested_at = attempt.get("request_id"), event.get("at")
            if not isinstance(request_id, str) or not isinstance(requested_at, str):
                continue
            route = _route_for_attempt(self, attempt)
            if route is not None and get_causal_event_from_reader(self, _response_ref(request_id)) is None:
                due = max(current, CampaignTime.parse(requested_at).add_seconds(int(route["delay_seconds"])))
                h, e = _request_ids(request_id)
                self._schedule_one_shot(runtime, host_id=h, event_id=e, kind="contact_request", priority=46, due=due, row={
                    "owner_ref": route["institution_ref"], "request_id": request_id, "source_event_id": event.get("event_id"),
                    "source_process_ref": attempt.get("process_ref"), "route_ref": route.get("route_ref"), "route_domain": "institutional_contact", "institution_ref": route["institution_ref"],
                    "receiving_role": route.get("receiving_role"), "audience_summary": route.get("audience_summary"), "delivery_route": route.get("delivery_route"),
                    "resolved_through": str(current if current < due else due.add_seconds(-1)),
                })

            match = _match_disposition(self, attempt)
            if match is not None and get_causal_event_from_reader(self, _disposition_response_ref(request_id)) is None:
                droute, spec, _process = match
                delay = spec.get("delay_seconds")
                if isinstance(delay, bool) or not isinstance(delay, int) or delay <= 0:
                    raise ValueError("audience disposition delay is invalid")
                process_ref = str(attempt.get("process_ref", ""))
                outcome, response_summary = _precommit_disposition(self, process_ref, spec)
                due = max(current, CampaignTime.parse(requested_at).add_seconds(delay))
                h, e = _disposition_ids(request_id)
                existing = hosts.get(h)
                if isinstance(existing, dict):
                    if not isinstance(existing.get("disposition_outcome"), str):
                        existing["disposition_outcome"] = outcome
                    if not isinstance(existing.get("response_summary"), str):
                        existing["response_summary"] = response_summary
                else:
                    self._schedule_one_shot(runtime, host_id=h, event_id=e, kind="audience_disposition", priority=47, due=due, row={
                        "owner_ref": droute["institution_ref"], "request_id": request_id, "source_event_id": event.get("event_id"),
                        "source_process_ref": process_ref, "route_ref": droute.get("route_ref"), "route_domain": "institutional_contact", "institution_ref": droute["institution_ref"],
                        "disposition_ref": spec.get("disposition_ref"), "disposition_spec": copy.deepcopy(dict(spec)), "delivery_route": droute.get("delivery_route"),
                        "disposition_outcome": outcome, "response_summary": response_summary,
                        "resolved_through": str(current if current < due else due.add_seconds(-1)),
                    })

            followup = _match_followup(self, attempt)
            if followup is None or get_causal_event_from_reader(self, _followup_response_ref(request_id)) is not None:
                continue
            spec, process = followup
            delay = spec.get("delay_seconds")
            if isinstance(delay, bool) or not isinstance(delay, int) or delay <= 0:
                raise ValueError("institutional follow-up delay is invalid")
            summary = spec.get("response_summary")
            source_owner_ref = spec.get("source_owner_ref")
            delivery_route = spec.get("delivery_route")
            response_stage = spec.get("response_stage", "answered")
            if any(not isinstance(value, str) or not value for value in (summary, source_owner_ref, delivery_route, response_stage)):
                raise ValueError("institutional follow-up response registry is incomplete")
            due_raw = CampaignTime.parse(requested_at).add_seconds(delay)
            due = max(current, due_raw)
            h, e = _followup_ids(request_id)
            self._schedule_one_shot(runtime, host_id=h, event_id=e, kind="institutional_followup", priority=48, due=due, row={
                "owner_ref": source_owner_ref,
                "request_id": request_id,
                "source_event_id": event.get("event_id"),
                "source_process_ref": str(attempt.get("process_ref", "")),
                "followup_ref": spec.get("followup_ref"),
                "source_owner_ref": source_owner_ref,
                "actor_ref": spec.get("actor_ref"),
                "response_summary": summary,
                "response_stage": response_stage,
                "delivery_route": delivery_route,
                "late_catch_up": due_raw < current,
                "source_process_kind": process.get("process_kind"),
                "source_process_stage": process.get("process_stage"),
                "resolved_through": str(current if current < due else due.add_seconds(-1)),
            })

    def _advance_runtime(self, target_text: str) -> dict[str, Any]:
        if getattr(self, "_central_scheduler_reconciliation_active", False):
            return super()._advance_runtime(target_text)
        runtime = copy.deepcopy(self.read(_RUNTIME_PATH))
        self._sync_contact_request_routes(runtime)
        self.put(_RUNTIME_PATH, runtime)
        return super()._advance_runtime(target_text)

    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        if host.get("kind") == "contact_request":
            _settle_contact_request(self, host, due_text)
            self._pending_wake_created = None
            return
        if host.get("kind") == "audience_disposition":
            _settle_audience_disposition(self, host, due_text)
            self._pending_wake_created = None
            return
        if host.get("kind") == "institutional_followup":
            _settle_institutional_followup(self, host, due_text)
            self._pending_wake_created = None
            return
        super()._run_due_host(host, due_text)


__all__ = [
    "ContactRequestFlowMixin", "_disposition_response_ref", "_followup_response_ref",
    "_match_disposition", "_match_followup", "_response_ref", "_route_for_attempt",
    "_settle_audience_disposition", "_settle_contact_request", "_settle_institutional_followup",
]
