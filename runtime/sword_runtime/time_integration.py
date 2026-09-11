"""Single production chronology orchestration authority.

This module coordinates route reconciliation and chronological advancement for
the hosted Sword runtime.  Domain mechanics remain with their owning modules:
military supply is derived at activity boundaries, Qin support settles in
``qin_command_support_flow``, battlefields settle in ``battlefield``, and so on.
The orchestrator only makes those owners causally reachable, proves scheduler
coverage, and advances the shared clock.
"""
from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from typing import Any

from sword_runtime.campaign_closure import settle_war_ceremony, sync_war_ceremony_routes
from sword_runtime.campaign_command_cycle import settle_campaign_command_host, sync_campaign_command_cycle
from sword_runtime.campaign_march_lifecycle import settle_campaign_march_host, sync_campaign_march_routes
from sword_runtime.campaign_subordinate_orders import sync_campaign_subordinate_orders
from sword_runtime.civil_world import sync_faction_routes, sync_polity_routes
from sword_runtime.house_field_preparation_gate import sync_explicit_house_field_preparation
from sword_runtime.institutional_processes import sync_institutional_process_routes
from sword_runtime.player_story_flow import sync_player_story_flow
from sword_runtime.qin_command_assumption_flow import sync_qin_command_assumption_flow
from sword_runtime.qin_command_briefing_flow import sync_qin_command_briefings
from sword_runtime.qin_command_support_flow import sync_qin_command_support
from sword_runtime.settlement_civic_depth import sync_outbreak_routes
from sword_runtime.scheduler_frontier import (
    ROUTE_AFFECTING_COMMANDS,
    assert_frontier_consistent,
    compact_scheduler_routes,
    ensure_reconciliation_host,
    ensure_scheduler_state,
    mark_scheduler_dirty,
    record_reconciliation,
    repair_core_autonomous_routes,
    runtime_route_integrity,
)
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.systems.campaign_events import sync_campaign_work_routes
from sword_runtime.world_arcs import sync_world_arc_routes


HOST_KIND_SPECS: dict[str, dict[str, str]] = {
    "scheduler_reconcile": {"owner": "chronology", "wake": "never"},
    "war_closure_ceremony": {"owner": "campaign_closure", "wake": "player_presence"},
    "person_activity": {"owner": "activity_living_world", "wake": "never"},
    "army_staff": {"owner": "army_staff", "wake": "never"},
    "prisoner_custody": {"owner": "prisoner_system", "wake": "never"},
    "military_career": {"owner": "military_career", "wake": "domain"},
    "military_career_petition_delivery": {"owner": "military_career", "wake": "never"},
    "military_personnel_transfer": {"owner": "military_career", "wake": "never"},
    "military_reconnaissance": {"owner": "military_reconnaissance", "wake": "never"},
    "commitment_due": {"owner": "campaign_depth", "wake": "on_due"},
    "commission_settlement": {"owner": "campaign_depth", "wake": "never"},
    "commission": {"owner": "campaign_depth", "wake": "never"},
    "world_arc": {"owner": "world_arcs", "wake": "never"},
    "world_arc_report": {"owner": "world_arcs", "wake": "domain"},
    "institutional_process": {"owner": "institutional_processes", "wake": "domain"},
    "campaign_event": {"owner": "campaign_events", "wake": "domain"},
    "settlement_development_project": {"owner": "settlement_development", "wake": "never"},
    "settlement_outbreak": {"owner": "settlement_civic_depth", "wake": "never"},
    "world_arc_priority": {"owner": "civil_world", "wake": "never"},
    "contact_request": {"owner": "contact_request_flow", "wake": "never"},
    "audience_disposition": {"owner": "contact_request_flow", "wake": "never"},
    "institutional_followup": {"owner": "contact_request_flow", "wake": "never"},
    "family_counsel": {"owner": "family_counsel", "wake": "never"},
    "household_request": {"owner": "household_request_flow", "wake": "never"},
    "household_recruitment_watch": {"owner": "household_request_flow", "wake": "never"},
    "house_field_preparation_reply": {"owner": "house_field_preparation", "wake": "never"},
    "house_development_request": {"owner": "house_tang_development", "wake": "never"},
    "house_development_completion": {"owner": "house_tang_development", "wake": "never"},
    "qin_command_receiving": {"owner": "qin_command_assumption", "wake": "never"},
    "qin_command_assumption": {"owner": "qin_command_assumption", "wake": "never"},
    "qin_command_briefing_reply": {"owner": "qin_command_briefing", "wake": "never"},
    "qin_command_support_review": {"owner": "qin_command_support", "wake": "never"},
    "campaign_march": {"owner": "campaign_march_lifecycle", "wake": "never"},
    "campaign_command_council": {"owner": "campaign_command_cycle", "wake": "player_event"},
    "campaign_command_council_return": {"owner": "campaign_command_cycle", "wake": "never"},
    "campaign_command_superior_order": {"owner": "campaign_command_cycle", "wake": "player_event"},
    "campaign_command_after_action": {"owner": "campaign_command_cycle", "wake": "player_event"},
    "campaign_command_dawn": {"owner": "campaign_command_cycle", "wake": "never"},
    "campaign_command_evening": {"owner": "campaign_command_cycle", "wake": "never"},
    "campaign_command_report_delivery": {"owner": "campaign_command_cycle", "wake": "never"},
    "story_appointment_reply": {"owner": "player_story_flow", "wake": "never"},
    "player_story_review": {"owner": "player_story_flow", "wake": "never"},
    "player_story_message_delivery": {"owner": "player_story_flow", "wake": "never"},
    "state": {"owner": "core_living_world", "wake": "domain"},
    "population": {"owner": "core_living_world", "wake": "domain"},
    "population_mobility": {"owner": "core_living_world", "wake": "domain"},
    "population_mobility_arrival": {"owner": "core_living_world", "wake": "domain"},
    "house": {"owner": "core_living_world", "wake": "domain"},
    "institution": {"owner": "core_living_world", "wake": "domain"},
    "institution_bundle": {"owner": "core_living_world", "wake": "domain"},
    "faction": {"owner": "core_living_world", "wake": "domain"},
    "polity": {"owner": "core_living_world", "wake": "domain"},
    "mercenary": {"owner": "core_living_world", "wake": "domain"},
    "interstate": {"owner": "core_living_world", "wake": "domain"},
    "person": {"owner": "core_living_world", "wake": "domain"},
    "house_tang_training": {"owner": "core_living_world", "wake": "domain"},
}
SUPPORTED_HOST_KINDS = frozenset(HOST_KIND_SPECS)


def dispatch_due_host(planner: Any, host: Mapping[str, Any], due_text: str) -> None:
    """Settle one registered causal host through explicit domain ownership.

    This is the single due-host dispatcher for every planner that uses the causal
    scheduler. Domain modules continue to own their mechanics; chronology merely
    routes a registered host to the one lawful settlement path. No cooperative
    ``super()._run_due_host`` chain is involved.
    """
    kind = str(host.get("kind", ""))
    if kind not in SUPPORTED_HOST_KINDS:
        raise ValueError(f"unsupported causal host kind: {kind or '<missing>'}")

    # Chronology-owned infrastructure.
    if kind == "scheduler_reconcile":
        planner._reconcile_all_scheduler_domains(due_text)
        planner._pending_wake_created = None
        return
    if kind == "war_closure_ceremony":
        ceremony_ref = str(host.get("ceremony_ref", ""))
        if not ceremony_ref:
            raise ValueError("war ceremony scheduler host lacks ceremony_ref")
        already_held = any(
            isinstance(row, Mapping) and str(row.get("event_id", "")) == f"{ceremony_ref}.held"
            for row in planner.read("state/history/events/index.json").get("events", [])
        )
        event = settle_war_ceremony(planner, ceremony_ref, at=due_text)
        planner._pending_wake_created = None
        if not already_held and planner.PLAYER_ACTOR in set(event.get("present_person_refs", [])):
            planner._pending_wake_created = {
                "wake_ref": f"wake_{ceremony_ref}",
                "kind": "war_closure_ceremony",
                "at": due_text,
                "ceremony_ref": ceremony_ref,
                "closure_event_ref": event.get("closure_event_ref"),
                "state_ref": event.get("state_ref"),
                "location_ref": event.get("venue_ref"),
                "reason": "formal_war_ceremony_convened",
                "target_host": planner._active_host_id,
                "event_id": planner._active_event_id,
            }
        return

    # Exact domain hosts. Import locally so chronology does not create module
    # initialization cycles with the production planner composition.
    if kind == "settlement_outbreak":
        outbreak_ref = str(host.get("owner_ref", ""))
        if not outbreak_ref:
            raise ValueError("outbreak scheduler host lacks outbreak_ref")
        result = planner._review_outbreak_once(outbreak_ref, due_text)
        if str(result.get("status", "")) != "active":
            runtime = copy.deepcopy(planner.read("state/runtime.json"))
            active_host_id = getattr(planner, "_active_host_id", None)
            active_host = runtime.get("hosts", {}).get(active_host_id) if isinstance(runtime.get("hosts"), Mapping) else None
            if isinstance(active_host, dict):
                active_host["recurrence_seconds"] = 0
            planner.put("state/runtime.json", runtime)
        planner._pending_wake_created = None
        return
    if kind == "person_activity":
        planner._settle_activity_host(host, due_text)
        planner._pending_wake_created = None
        return
    if kind == "army_staff":
        planner._settle_army_staff_host(host, due_text)
        planner._pending_wake_created = None
        return
    if kind == "prisoner_custody":
        refs = host.get("routed_group_refs", []) if isinstance(host.get("routed_group_refs"), list) else []
        for ref in refs:
            if isinstance(ref, str):
                planner._custody_daily_review(ref, due_text)
        planner._pending_wake_created = None
        return
    if kind == "military_career":
        planner._settle_military_career_host(host, due_text)
        planner._pending_wake_created = None
        return
    if kind == "military_career_petition_delivery":
        planner._settle_player_petition_delivery(host, due_text)
        planner._pending_wake_created = None
        return
    if kind == "military_personnel_transfer":
        planner._settle_transfer_order(host, due_text)
        planner._pending_wake_created = None
        return
    if kind == "military_reconnaissance":
        planner._settle_military_reconnaissance_host(host, due_text)
        planner._pending_wake_created = None
        return
    if kind == "campaign_march":
        settle_campaign_march_host(planner, host, due_text)
        planner._pending_wake_created = None
        return

    if kind in {"commitment_due", "commission_settlement", "commission"}:
        import hashlib
        if kind == "commitment_due":
            result = planner._autonomy_commitment_due(host, due_text)
            if isinstance(result, Mapping) and result.get("commitment_ref"):
                digest = hashlib.sha256(f"{result['commitment_ref']}:{due_text}".encode()).hexdigest()[:16]
                planner._pending_wake_created = {
                    "wake_ref": f"wake.campaign_event.commitment.{digest}",
                    "kind": "campaign_event",
                    "at": due_text,
                    "campaign_event_ref": str(result["commitment_ref"]),
                    "reason": "A durable commitment has reached its due time without recorded fulfillment.",
                    "target_host": getattr(planner, "_active_host_id", None),
                    "event_id": getattr(planner, "_active_event_id", None),
                }
            return
        if kind == "commission_settlement":
            planner._autonomy_commission_settlement(host, due_text)
            # Evidence review is a durable informational result, not a hard
            # scheduler interruption. The commission owner carries the result.
            planner._pending_wake_created = None
            return
        planner._autonomy_commission(host, 1, due_text)
        # An offered commission is a voluntary durable decision. It remains
        # discoverable/actionable through the commission owner without freezing
        # unrelated chronology as a campaign-event wake.
        planner._pending_wake_created = None
        return

    if kind in {"world_arc", "world_arc_report", "institutional_process", "campaign_event"}:
        from sword_runtime.campaign_event_planner import (
            record_delivered_world_arc_report_information,
        )
        from sword_runtime.institutional_processes import settle_institutional_process_followup
        from sword_runtime.systems.campaign_events import settle_campaign_work_target
        from sword_runtime.world_arc_report_handoff import settle_player_safe_world_arc_report
        from sword_runtime.world_arcs import settle_world_arc_review
        if kind == "world_arc":
            settle_world_arc_review(planner, host, due_text)
            planner._pending_wake_created = None
            return
        if kind == "world_arc_report":
            wake = settle_player_safe_world_arc_report(planner, host, due_text)
            record_delivered_world_arc_report_information(planner, host, due_text)
            if wake is not None:
                wake["target_host"] = planner._active_host_id
                wake["event_id"] = planner._active_event_id
            planner._pending_wake_created = wake
            source_event_ref = host.get("source_event_ref")
            if isinstance(source_event_ref, str) and hasattr(planner, "_enrich_world_arc_report"):
                planner._enrich_world_arc_report(source_event_ref)
            return
        if kind == "institutional_process":
            wake = settle_institutional_process_followup(planner, host, due_text)
            if wake is not None:
                wake["target_host"] = planner._active_host_id
                wake["event_id"] = planner._active_event_id
            planner._pending_wake_created = wake
            return
        wake = settle_campaign_work_target(planner, host, due_text)
        if wake is not None:
            wake["target_host"] = planner._active_host_id
            wake["event_id"] = planner._active_event_id
        planner._pending_wake_created = wake
        return

    if kind == "settlement_development_project":
        from sword_runtime.civil_world import settle_development_project
        settle_development_project(planner, host, due_text)
        planner._pending_wake_created = None
        return
    if kind == "world_arc_priority":
        planner._settle_world_arc_priority_host(host, due_text)
        planner._pending_wake_created = None
        return

    if kind in {"contact_request", "audience_disposition", "institutional_followup"}:
        from sword_runtime.contact_request_flow import (
            _settle_audience_disposition,
            _settle_contact_request,
            _settle_institutional_followup,
        )
        if kind == "contact_request":
            _settle_contact_request(planner, host, due_text)
        elif kind == "audience_disposition":
            _settle_audience_disposition(planner, host, due_text)
        else:
            _settle_institutional_followup(planner, host, due_text)
        planner._pending_wake_created = None
        return
    if kind == "family_counsel":
        from sword_runtime.family_counsel import _settle_family_counsel
        _settle_family_counsel(planner, host, due_text)
        planner._pending_wake_created = None
        return
    if kind in {"household_request", "household_recruitment_watch"}:
        from sword_runtime.household_request_flow import _settle_household_request, _settle_recruitment_watch
        if kind == "household_request":
            _settle_household_request(planner, host, due_text)
        else:
            _settle_recruitment_watch(planner, host, due_text)
        planner._pending_wake_created = None
        return

    if kind == "house_field_preparation_reply":
        from sword_runtime.house_field_preparation_flow import settle_house_field_preparation
        from sword_runtime.house_field_preparation_issue import issue_house_field_preparation_package
        from sword_runtime.house_field_preparation_outfitting import project_house_production_into_field_preparation
        notice = settle_house_field_preparation(planner, host, due_text)
        if isinstance(notice, Mapping):
            response_ref = str(host.get("response_event_ref", ""))
            if response_ref:
                issue_house_field_preparation_package(
                    planner, response_event_ref=response_ref, at=due_text
                )
                project_house_production_into_field_preparation(planner, response_ref)
            notice = copy.deepcopy(dict(notice))
            notice["target_host"] = planner._active_host_id
            notice["event_id"] = planner._active_event_id
        # Procedural completion is nonblocking, but it must remain visible as a
        # campaign-event notice. The causal loop demotes this kind from wake to
        # notice and continues chronology automatically.
        planner._pending_wake_created = notice
        return

    if kind == "house_development_request":
        planner._settle_expansion_request(host, due_text)
        planner._pending_wake_created = None
        return
    if kind == "house_development_completion":
        planner._settle_expansion_completion(host, due_text)
        planner._pending_wake_created = None
        return

    if kind in {"qin_command_receiving", "qin_command_assumption"}:
        from sword_runtime.qin_command_assumption_flow import _settle_assumption, _write_receiving_event
        if kind == "qin_command_receiving":
            _write_receiving_event(planner, host, due_text)
        else:
            _settle_assumption(planner, host, due_text)
        # Receiving and assumption are results of already-declared procedural
        # intent. Their durable events may be surfaced naturally, but they never
        # become hard scheduler wakes.
        planner._pending_wake_created = None
        return

    if kind == "qin_command_briefing_reply":
        from sword_runtime.qin_command_briefing_flow import settle_qin_command_briefing
        notice = settle_qin_command_briefing(planner, host, due_text)
        if isinstance(notice, Mapping):
            notice = copy.deepcopy(dict(notice))
            notice["target_host"] = planner._active_host_id
            notice["event_id"] = planner._active_event_id
        planner._pending_wake_created = notice
        return

    if kind == "qin_command_support_review":
        from sword_runtime.qin_command_support_flow import settle_qin_command_support
        notice = settle_qin_command_support(planner, host, due_text)
        if isinstance(notice, Mapping):
            notice = copy.deepcopy(dict(notice))
            notice["target_host"] = planner._active_host_id
            notice["event_id"] = planner._active_event_id
        planner._pending_wake_created = notice
        return

    if kind in {
        "campaign_command_council", "campaign_command_council_return",
        "campaign_command_superior_order", "campaign_command_after_action",
        "campaign_command_dawn", "campaign_command_evening",
        "campaign_command_report_delivery",
    }:
        settle_campaign_command_host(planner, host, due_text)
        # A campaign command settlement may make a projected staff assignment into
        # an exact NPC subordinate order. Register any resulting march routes at
        # the same causal frontier so a broad advance can enqueue them immediately.
        sync_campaign_subordinate_orders(planner, at=due_text)
        runtime = copy.deepcopy(planner.read("state/runtime.json"))
        sync_campaign_march_routes(planner, runtime, at=due_text)
        planner.put("state/runtime.json", runtime)
        # Campaign command briefings/councils are delivered player-facing events,
        # not hard scheduler wakes. Event-bounded downtime will stop on the new
        # handle without persisting an invalid campaign_event wake.
        planner._pending_wake_created = None
        return

    if kind == "story_appointment_reply":
        from sword_runtime.player_story_flow import settle_appointment_reply
        from sword_runtime.qin_command_progression import _OFFER_KIND, _offer_details, settle_probationary_reply
        offer_ref = str(host.get("offer_ref", ""))
        player = planner.read("state/player.json")
        details = _offer_details(player, offer_ref) if isinstance(player, Mapping) else None
        if isinstance(details, Mapping) and details.get("offer_kind") == _OFFER_KIND:
            settle_probationary_reply(planner, host, due_text)
        else:
            settle_appointment_reply(planner, host, due_text)
        planner._pending_wake_created = None
        return

    if kind == "player_story_review":
        # Weekly review is background administration. It can dispatch physical
        # messages and close stale decisions, but review cadence is never itself
        # a player turn boundary.
        from sword_runtime.qin_command_assumption_flow import _safe_story_review
        _safe_story_review(planner, due_text)
        planner._pending_wake_created = None
        return

    if kind == "player_story_message_delivery":
        from sword_runtime.player_story_flow import settle_player_story_message_delivery
        settle_player_story_message_delivery(planner, host, due_text)
        planner._pending_wake_created = None
        return

    # The core living-world kinds remain domain methods on the causal planner.
    if kind in {
        "state", "population", "population_mobility", "population_mobility_arrival",
        "house", "institution", "institution_bundle", "faction", "polity",
        "mercenary", "interstate", "person", "house_tang_training",
    }:
        # The core domain may create a hard causal wake, most importantly an
        # interstate contact involving a player-commanded formation.  The
        # scheduler clears _pending_wake_created before dispatch, so preserve
        # whatever the domain deliberately sets here instead of erasing it.
        planner._settle_core_due_host(host, due_text)
        if kind == "state":
            # State autonomy can issue or retask a Qin operational order at this
            # exact frontier. Register a newly pending staff briefing here so the
            # causal heap can enqueue and settle it inside the same broad advance.
            runtime = copy.deepcopy(planner.read("state/runtime.json"))
            sync_qin_command_support(planner, runtime)
            planner.put("state/runtime.json", runtime)
        return

    raise ValueError(f"unsupported causal host kind: {kind or '<missing>'}")


class ProductionTimeIntegrationMixin:
    """Own production chronology orchestration without owning domain mechanics."""

    _central_scheduler_reconciliation_active = False
    _ACTIVITY_ROUTE_SAFETY_SECONDS = 30 * 86400
    _CAUSAL_HEAP_WINDOW_SECONDS = 7 * 86400

    def _next_scheduler_event_boundary(
        self,
        current: CampaignTime,
        target: CampaignTime,
        *,
        host_kinds: set[str] | frozenset[str] | None = None,
    ) -> tuple[CampaignTime | None, dict[str, Any] | None]:
        """Return the earliest registered causal host due inside ``(current, target]``.

        This is a read-only chronology query for domains such as persistent
        battlefield contact planning.  It does not settle the host and it does
        not decide what the host means.  The caller owns the relevance filter;
        ``time_integration`` only exposes the already-registered causal frontier.
        """
        if target <= current:
            return None, None
        runtime = self.read("state/runtime.json")
        hosts = runtime.get("hosts")
        events = runtime.get("events")
        if not isinstance(hosts, Mapping) or not isinstance(events, list):
            raise ValueError("runtime causal queue is invalid")
        allowed = None if host_kinds is None else {str(kind) for kind in host_kinds}
        candidates: list[tuple[CampaignTime, int, str, str, str]] = []
        for event in events:
            if not isinstance(event, Mapping):
                raise ValueError("runtime causal event is invalid")
            if event.get("suspended") is True:
                continue
            event_id = event.get("event_id")
            host_id = event.get("target_host")
            if not isinstance(event_id, str) or not isinstance(host_id, str):
                raise ValueError("runtime causal event routing is invalid")
            host = hosts.get(host_id)
            if not isinstance(host, Mapping) or host.get("next_due") is None:
                continue
            host_kind = host.get("kind")
            if not isinstance(host_kind, str):
                raise ValueError("runtime causal host kind is invalid")
            if allowed is not None and host_kind not in allowed:
                continue
            due_text = event.get("due_at")
            if not isinstance(due_text, str) or due_text != host.get("next_due"):
                raise ValueError("runtime event and host due time diverged")
            due = CampaignTime.parse(due_text)
            if not current < due <= target:
                continue
            priority = event.get("priority", 100)
            if isinstance(priority, bool) or not isinstance(priority, int):
                raise ValueError("runtime causal event priority is invalid")
            candidates.append((due, priority, event_id, host_id, host_kind))
        if not candidates:
            return None, None
        due, priority, event_id, host_id, host_kind = min(
            candidates, key=lambda row: (row[0], row[1], row[2], row[3], row[4])
        )
        return due, {
            "kind": "scheduler_event",
            "event_id": event_id,
            "host_id": host_id,
            "host_kind": host_kind,
            "priority": priority,
        }

    def _activity_route_reconcile_required(self, runtime: Mapping[str, Any], at: str) -> bool:
        scheduler = runtime.get("scheduler")
        if not isinstance(scheduler, Mapping) or scheduler.get("dirty") is True:
            return True
        routing = runtime.get("person_activity_routing")
        last_text = routing.get("last_route_scan_at") if isinstance(routing, Mapping) else None
        if not isinstance(last_text, str):
            return True
        try:
            last = CampaignTime.parse(last_text)
            current = CampaignTime.parse(at)
        except (TypeError, ValueError):
            return True
        return current >= last.add_seconds(self._ACTIVITY_ROUTE_SAFETY_SECONDS)

    def _reconcile_all_scheduler_domains(self, at: str) -> dict[str, Any]:
        """Repair route registration only; each subsystem settles itself later."""
        routing_runtime = self.read("state/runtime.json")
        reconcile_activity_routes = self._activity_route_reconcile_required(routing_runtime, at)
        self._ensure_army_staff_hosts()
        if self.read_optional("state/custody/index.json"):
            self._custody_ensure_review_host()
        self._ensure_military_career_routes()
        if reconcile_activity_routes:
            self._ensure_activity_routes()

        if hasattr(self, "_active_organization_records"):
            for ref, _path, _org in self._active_organization_records():
                self._ensure_organization_host(ref, at)
        else:
            org_index = self.read_optional("state/organizations/index.json") or {}
            if isinstance(org_index, Mapping):
                for ref in sorted(str(x) for x in org_index.get("active_refs", []) if isinstance(x, str)):
                    self._ensure_organization_host(ref, at)

        runtime = copy.deepcopy(self.read("state/runtime.json"))
        compact_scheduler_routes(self, runtime)
        repair_core_autonomous_routes(self, runtime)
        hosts = runtime.get("hosts")
        if not isinstance(hosts, dict):
            raise ValueError("runtime causal hosts are invalid")
        prior_hosts = set(hosts)
        sync_world_arc_routes(self, runtime)
        sync_outbreak_routes(self, runtime)
        self._defer_new_world_arc_routes(runtime, prior_hosts)
        sync_faction_routes(self, runtime)
        sync_polity_routes(self, runtime)
        sync_campaign_work_routes(self, runtime)
        sync_war_ceremony_routes(self, runtime)
        sync_institutional_process_routes(self, runtime)
        sync_qin_command_assumption_flow(self, runtime)
        sync_qin_command_briefings(self, runtime)
        sync_explicit_house_field_preparation(self, runtime)
        sync_qin_command_support(self, runtime)
        sync_campaign_command_cycle(self, runtime)
        # Command adoption is a domain write; route registration remains scheduler
        # bookkeeping. Running both here repairs historical participant operations
        # that had custody and staff assignments but no executable march order.
        sync_campaign_subordinate_orders(self, at=at)
        sync_campaign_march_routes(self, runtime, at=at)
        self._sync_household_request_routes(runtime)
        self._sync_contact_request_routes(runtime)
        self._sync_family_counsel_routes(runtime)
        sync_player_story_flow(self, runtime)
        self._normalize_house_tang_training_host(runtime)
        self._sync_house_development_requests(runtime)
        ensure_reconciliation_host(runtime)
        coverage = runtime_route_integrity(runtime)
        if not coverage.get("complete"):
            raise ValueError(f"scheduler reconciliation left invalid routes: {coverage}")
        record_reconciliation(runtime, at, coverage=coverage)
        self.put("state/runtime.json", runtime)
        return coverage

    def _prepare_scheduler_for_advance(self, target_text: str) -> None:
        del target_text  # target is not needed for route registration itself.
        runtime = copy.deepcopy(self.read("state/runtime.json"))
        ensure_reconciliation_host(runtime)
        # These compact cross-cutting hosts used to be registered by outer MRO
        # wrappers. Production chronology now registers them explicitly so the
        # causal entry point is obvious and duplicate wrapper work is suppressed.
        sync_qin_command_support(self, runtime)
        sync_campaign_command_cycle(self, runtime)
        at = str(runtime["world_time"])
        sync_campaign_subordinate_orders(self, at=at)
        sync_campaign_march_routes(self, runtime, at=at)
        scheduler = ensure_scheduler_state(runtime)
        if not isinstance(scheduler.get("causal_settled_through"), str):
            scheduler["causal_settled_through"] = str(runtime["world_time"])

        # Dynamic disease reviews are causal hosts, not post-advance catch-up.
        sync_outbreak_routes(self, runtime)
        # One-shot campaign work is a bounded hot queue that may be written by a
        # causal subsystem without a route-affecting player command.
        sync_campaign_work_routes(self, runtime)
        sync_war_ceremony_routes(self, runtime)
        scheduler = ensure_scheduler_state(runtime)
        self.put("state/runtime.json", runtime)
        assert_frontier_consistent(runtime)
        if scheduler.get("dirty") is True:
            self._reconcile_all_scheduler_domains(str(runtime["world_time"]))

    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        dispatch_due_host(self, host, due_text)

    def _command_layer_time_integration(self, command: Any, payload: Mapping[str, Any], next_dispatch: Any) -> dict[str, Any]:
        result = next_dispatch()
        if command.command_type in ROUTE_AFFECTING_COMMANDS:
            runtime = copy.deepcopy(self.read("state/runtime.json"))
            mark_scheduler_dirty(runtime, f"command:{command.command_type}")
            self.put("state/runtime.json", runtime)
        return result

    def _post_advance_domain_hooks(self, metrics: Mapping[str, Any]) -> dict[str, Any]:
        """Settle non-scheduler domain work at the chronology actually reached.

        These hooks used to live in cooperative ``_advance_runtime`` wrappers.
        Keeping them explicit here prevents inheritance order from becoming a
        hidden chronology contract while leaving consequence authority in the
        owning domain modules.
        """
        result = dict(metrics)
        runtime = self.read("state/runtime.json")
        reached = runtime.get("world_time") if isinstance(runtime, Mapping) else None
        if not isinstance(reached, str) or not reached:
            raise ValueError("chronology post-settlement lost runtime world time")

        fort_review = getattr(self, "_fort_campaign_logistics_review", None)
        if callable(fort_review):
            review = fort_review(reached)
            if isinstance(review, Mapping) and any(bool(value) for value in review.values()):
                result["fortification_logistics"] = copy.deepcopy(dict(review))
        return result

    def _advance_causal_window(self, target_text: str) -> dict[str, Any]:
        """Prepare routes, run the causal heap once, then settle named post hooks."""
        self._prepare_scheduler_for_advance(target_text)
        metrics = self._advance_causal_runtime(target_text)
        return self._post_advance_domain_hooks(metrics)

    @staticmethod
    def _merge_extra_time_metrics(total: dict[str, Any], metrics: Mapping[str, Any]) -> None:
        known = {
            "hosts_woken", "events_processed", "battlefield_reports",
            "battlefield_reviews", "campaign_event_notices",
            "battlefield_player_interrupt", "requested_time",
            "causal_settled_through", "interrupted", "wake_required", "wake",
            "pending_wake_preserved", "interrupt_reason",
            "player_facing_event_boundary", "player_facing_event_refs",
            "fortification_logistics",
        }
        for key, value in metrics.items():
            if key in known:
                continue
            if isinstance(value, int) and not isinstance(value, bool):
                total[key] = int(total.get(key, 0)) + value
        review = metrics.get("fortification_logistics")
        if isinstance(review, Mapping):
            aggregate = total.setdefault("fortification_logistics", {})
            if isinstance(aggregate, dict):
                for key, value in review.items():
                    if isinstance(value, list):
                        rows = aggregate.setdefault(key, [])
                        if isinstance(rows, list):
                            rows.extend(copy.deepcopy(value))
                    elif isinstance(value, int) and not isinstance(value, bool):
                        aggregate[key] = int(aggregate.get(key, 0)) + value
                    else:
                        aggregate[key] = copy.deepcopy(value)

    def _advance_event_bounded_downtime(self, target_text: str) -> dict[str, Any]:
        """Advance until the first newly delivered player-facing event."""
        target = CampaignTime.parse(target_text)
        self._prepare_scheduler_for_advance(target_text)
        total: dict[str, Any] = {
            "hosts_woken": 0,
            "events_processed": 0,
            "battlefield_reports": [],
            "battlefield_reviews": 0,
            "campaign_event_notices": [],
            "battlefield_player_interrupt": False,
        }
        seen_frontiers: set[tuple[str, str]] = set()
        while True:
            runtime_before = self.read("state/runtime.json")
            current = CampaignTime.parse(str(runtime_before["world_time"]))
            scheduler_signature = json.dumps(
                {
                    "hosts": runtime_before.get("hosts", {}),
                    "events": runtime_before.get("events", []),
                    "scheduler": runtime_before.get("scheduler", {}),
                },
                sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str,
            )
            frontier_key = (str(current), scheduler_signature)
            if frontier_key in seen_frontiers:
                raise ValueError("event-bounded downtime causal frontier cycle")
            seen_frontiers.add(frontier_key)
            if current >= target:
                total["requested_time"] = target_text
                total["causal_settled_through"] = str(
                    self.read("state/runtime.json").get("scheduler", {}).get("causal_settled_through", current)
                )
                return total
            step = self._next_scheduler_boundary(current, target)
            before = self._player_facing_event_refs()
            metrics = self._post_advance_domain_hooks(self._advance_causal_runtime(str(step)))
            self._merge_time_metrics(total, metrics)
            self._merge_extra_time_metrics(total, metrics)
            total["battlefield_player_interrupt"] = bool(
                total.get("battlefield_player_interrupt", False)
                or metrics.get("battlefield_player_interrupt", False)
            )
            actual = CampaignTime.parse(str(self.read("state/runtime.json")["world_time"]))
            if metrics.get("interrupted"):
                total.update({
                    key: value for key, value in metrics.items()
                    if key not in {
                        "hosts_woken", "events_processed", "battlefield_reports",
                        "battlefield_reviews", "campaign_event_notices",
                        "battlefield_player_interrupt", "fortification_logistics",
                    }
                })
                total["requested_time"] = target_text
                return total
            new_refs = sorted(self._player_facing_event_refs() - before)
            if new_refs:
                total.update({
                    "interrupted": True,
                    "wake_required": False,
                    "interrupt_reason": "player_facing_event",
                    "player_facing_event_boundary": True,
                    "player_facing_event_refs": new_refs,
                    "requested_time": target_text,
                })
                return total
            if actual >= target:
                total["requested_time"] = target_text
                total["causal_settled_through"] = str(
                    self.read("state/runtime.json").get("scheduler", {}).get("causal_settled_through", actual)
                )
                return total
            if actual < step:
                raise ValueError("downtime scheduler failed to reach its selected boundary")

    def _advance_bounded_causal_horizon(self, target_text: str) -> dict[str, Any]:
        """Advance one atomic command through bounded in-memory causal heaps.

        A broad player command is still one planner transaction: no intermediate
        state is persisted, validated, committed, or exposed. The only boundary is
        scheduler working memory. Rebuilding the heap from the already-staged
        authoritative runtime at the seven-day scheduler safety cadence prevents long skips from
        carrying an arbitrarily large heap generation while preserving the exact
        causal frontier and all staged domain writes.

        Cross-cutting post-advance hooks settle once, at the actual final/reached
        chronology, so internal heap windows do not multiply domain consequences.
        """
        target = CampaignTime.parse(target_text)
        current = CampaignTime.parse(str(self.read("state/runtime.json")["world_time"]))
        if target <= current:
            return self._advance_causal_window(target_text)

        self._prepare_scheduler_for_advance(target_text)
        runtime0 = self.read("state/runtime.json")
        metrics0 = runtime0.get("metrics", {}) if isinstance(runtime0, Mapping) else {}
        baseline_hosts_woken = int(metrics0.get("hosts_woken", 0)) if isinstance(metrics0, Mapping) else 0
        unique_woken_event_ids: set[str] = set()
        total: dict[str, Any] = {
            "hosts_woken": 0,
            "events_processed": 0,
            "battlefield_reports": [],
            "battlefield_reviews": 0,
            "campaign_event_notices": [],
            "battlefield_player_interrupt": False,
        }
        while current < target:
            window_end = current.add_seconds(self._CAUSAL_HEAP_WINDOW_SECONDS)
            step = target if target <= window_end else window_end
            metrics = self._advance_causal_runtime(str(step))
            # Mass-training instructor pools are derived only for repeated drills
            # at one causal instant. Their cache key includes world time, so retaining
            # old windows cannot improve correctness or hit rate; it only makes one
            # long atomic advance accumulate thousands of obsolete candidate pools.
            # Clear this ephemeral cache at the same seven-day scheduler boundary
            # while preserving all staged authoritative writes and the full read set.
            instructor_pool_cache = getattr(self, "_training_instructor_pool_cache", None)
            if isinstance(instructor_pool_cache, dict):
                instructor_pool_cache.clear()
            unique_woken_event_ids.update(
                str(event_id) for event_id in getattr(self, "_last_causal_woken_event_ids", ())
            )
            self._merge_time_metrics(total, metrics)
            self._merge_extra_time_metrics(total, metrics)
            total["battlefield_player_interrupt"] = bool(
                total.get("battlefield_player_interrupt", False)
                or metrics.get("battlefield_player_interrupt", False)
            )

            runtime = self.read("state/runtime.json")
            actual = CampaignTime.parse(str(runtime["world_time"]))
            if metrics.get("interrupted") or actual < step:
                total.update({
                    key: copy.deepcopy(value)
                    for key, value in metrics.items()
                    if key not in {
                        "hosts_woken", "events_processed", "battlefield_reports",
                        "battlefield_reviews", "campaign_event_notices",
                        "battlefield_player_interrupt", "fortification_logistics",
                    }
                })
                total["requested_time"] = target_text
                total["causal_settled_through"] = str(
                    runtime.get("scheduler", {}).get("causal_settled_through", actual)
                )
                runtime_metrics = runtime.setdefault("metrics", {})
                runtime_metrics["hosts_woken"] = baseline_hosts_woken + len(unique_woken_event_ids)
                total["hosts_woken"] = len(unique_woken_event_ids)
                self.put("state/runtime.json", runtime)
                return self._post_advance_domain_hooks(total)
            if actual <= current:
                raise ValueError("bounded causal scheduler failed to advance its frontier")
            current = actual

        runtime = self.read("state/runtime.json")
        total["requested_time"] = target_text
        total["causal_settled_through"] = str(
            runtime.get("scheduler", {}).get("causal_settled_through", current)
        )
        runtime_metrics = runtime.setdefault("metrics", {})
        runtime_metrics["hosts_woken"] = baseline_hosts_woken + len(unique_woken_event_ids)
        total["hosts_woken"] = len(unique_woken_event_ids)
        self.put("state/runtime.json", runtime)
        return self._post_advance_domain_hooks(total)

    def _advance_runtime(self, target_text: str) -> dict[str, Any]:
        """Advance the single production chronology authority atomically.

        Long horizons use bounded in-memory heap windows only. They remain one
        semantic command and one transaction; there are no hidden persistence
        boundaries. Downtime that intentionally stops at the first player-facing
        event remains boundary-driven because that is a gameplay semantic.
        """
        if self._interruptible_personal_travel and self._active_command_type == "travel":
            previous = self._active_command_type
            self._active_command_type = "advance_time"
            try:
                return self._advance_bounded_causal_horizon(target_text)
            finally:
                self._active_command_type = previous

        if self._downtime_stop_on_player_event:
            return self._advance_event_bounded_downtime(target_text)

        return self._advance_bounded_causal_horizon(target_text)


__all__ = ["ProductionTimeIntegrationMixin"]
