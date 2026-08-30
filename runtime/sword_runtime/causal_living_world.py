"""Chronological causal overlay for Sword's production living world.

The base domain engine remains authoritative for reducers. This overlay makes
production catch-up globally chronological, preserves hosts created by callbacks,
adds bounded semantic provenance, prevents double assignment of formations, and
turns player-commanded interstate contact into a committed resumable wake rather
than either silently resolving the battle or aborting the whole time skip.
"""
from __future__ import annotations

import copy
import hashlib
import heapq
from typing import Any, Dict, Mapping, Optional

from sword_runtime.commands import CommandEnvelope
from sword_runtime.command_integration import ExplicitCommandRouterMixin
from sword_runtime.engine import RepositoryCommandPlanner, _deepcopy
from sword_runtime.living_world import HighSalienceWakeRequired, LivingWorldSwordPlanner
from sword_runtime.operation_routing import iter_exact_operation_records
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.scheduler_frontier import assert_frontier_consistent, ensure_scheduler_state, set_causal_frontier


_RUNTIME_PATH = "state/runtime.json"
_INTERSTATE_PATH = "state/politics/interstate-history.json"
_ACTIVE_OPERATION_STATES = frozenset({"planned", "mobilizing", "active", "engaged", "occupied"})
_WAKE_RESPONSE_COMMANDS = frozenset(
    {
        "advance_time",
        "formation_move",
        "formation_mobilize",
        "formation_demobilize",
        "formation_doctrine_set",
        "formation_training_set",
        "formation_assign",
        "force_assignment",
        "command_assign",
        "command_transfer",
        "resupply",
        "battlefield_control",
        "operation_create",
        "operation_transition",
        "interaction_action",
    }
)


class CausalLivingWorldSwordPlanner(ExplicitCommandRouterMixin, LivingWorldSwordPlanner):
    """Production planner with chronological catch-up and player wake boundaries."""

    _active_command_type: Optional[str] = None
    _active_event_id: Optional[str] = None
    _active_host_id: Optional[str] = None
    _pending_wake_created: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Bounded autonomous assignment
    # ------------------------------------------------------------------

    def _select_formations(
        self,
        state: str,
        objective_text: str,
        memory: Dict[str, Any],
        *,
        reserved: set[str],
        count: int = 2,
    ) -> list[str]:
        """Exclude formations already committed outside this state's auto plan."""

        occupied = set(reserved)
        own_prefix = f"operation_auto_{state}_"
        own_response = f"operation_auto_{state}_border_response"
        for operation_ref, _path, operation in iter_exact_operation_records(self):
            if str(operation.get("status", "")) not in _ACTIVE_OPERATION_STATES:
                continue
            # The state's own autonomous operations are intentionally eligible
            # for reassessment during this exact review. Manual operations and
            # other states' autonomous operations reserve their exact assets.
            if operation_ref == own_response or operation_ref.startswith(own_prefix):
                continue
            refs = operation.get("formation_refs")
            if not isinstance(refs, list):
                raise ValueError("active operation has invalid formation_refs")
            occupied.update(str(ref) for ref in refs if isinstance(ref, str) and ref)

        return super()._select_formations(
            state,
            objective_text,
            memory,
            reserved=occupied,
            count=count,
        )

    # ------------------------------------------------------------------
    # Resumable high-salience wake state
    # ------------------------------------------------------------------

    @staticmethod
    def _event_by_id(runtime: Mapping[str, Any], event_id: str) -> Optional[Dict[str, Any]]:
        events = runtime.get("events")
        if not isinstance(events, list):
            return None
        for event in events:
            if isinstance(event, dict) and event.get("event_id") == event_id:
                return event
        return None

    @staticmethod
    def _pending_wake(runtime: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        wake = runtime.get("pending_wake")
        return copy.deepcopy(wake) if isinstance(wake, Mapping) else None

    def _resume_pending_wake(self, runtime: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Resume a suspended interstate host only after explicit time continuation."""

        wake = self._pending_wake(runtime)
        if wake is None:
            return None
        if self._active_command_type != "advance_time":
            return wake

        if wake.get("kind") == "campaign_event":
            raise ValueError("campaign-event notices may not be persisted as pending wakes")

        # Operational battlefield reports are not scheduler hosts. The exact
        # operation already stores the delivered report and settlement cursor,
        # so acknowledging the player's standing continuation only clears the
        # decision boundary. Later battlefield settlement resumes from that
        # persisted operation time without fabricating a synthetic causal host.
        if wake.get("kind") in {"battlefield_report", "war_closure_ceremony"}:
            current = CampaignTime.parse(str(runtime["world_time"]))
            acknowledged = dict(wake)
            acknowledged["acknowledged_at"] = str(current)
            runtime["acknowledged_wake"] = acknowledged
            if wake.get("kind") == "war_closure_ceremony":
                host_id = wake.get("target_host")
                event_id = wake.get("event_id")
                hosts = runtime.get("hosts")
                if isinstance(hosts, dict) and isinstance(host_id, str):
                    hosts.pop(host_id, None)
                if isinstance(event_id, str):
                    runtime["events"] = [row for row in runtime.get("events", []) if not (isinstance(row, Mapping) and row.get("event_id") == event_id)]
            runtime.pop("pending_wake", None)
            return None

        host_id = wake.get("target_host")
        event_id = wake.get("event_id")
        hosts = runtime.get("hosts")
        if not isinstance(host_id, str) or not isinstance(event_id, str) or not isinstance(hosts, dict):
            raise ValueError("pending wake routing is invalid")
        host = hosts.get(host_id)
        event = self._event_by_id(runtime, event_id)
        if not isinstance(host, dict) or event is None:
            raise ValueError("pending wake lost its causal host")

        current = CampaignTime.parse(str(runtime["world_time"]))
        resume_at = current.add_seconds(3600)
        host["next_due"] = str(resume_at)
        host["safe_through"] = str(current)
        event["due_at"] = str(resume_at)
        event.pop("suspended", None)
        acknowledged = dict(wake)
        acknowledged["acknowledged_at"] = str(current)
        acknowledged["resumed_for"] = str(resume_at)
        runtime["acknowledged_wake"] = acknowledged
        runtime.pop("pending_wake", None)
        return None

    def _resolve_pending_wake_after_response(self, wake: Mapping[str, Any]) -> None:
        """Release a suspended contact if a response removed player command/contact."""

        if wake.get("kind") in {"battlefield_report", "war_closure_ceremony"}:
            runtime = self.read(_RUNTIME_PATH)
            current_wake = self._pending_wake(runtime)
            if current_wake is None or current_wake.get("wake_ref") != wake.get("wake_ref"):
                return
            if wake.get("kind") == "war_closure_ceremony":
                host_id = current_wake.get("target_host")
                event_id = current_wake.get("event_id")
                hosts = runtime.get("hosts")
                if isinstance(hosts, dict) and isinstance(host_id, str):
                    hosts.pop(host_id, None)
                if isinstance(event_id, str):
                    runtime["events"] = [row for row in runtime.get("events", []) if not (isinstance(row, Mapping) and row.get("event_id") == event_id)]
            runtime.pop("pending_wake", None)
            runtime.pop("acknowledged_wake", None)
            self.put(_RUNTIME_PATH, runtime)
            return

        formation_ref = wake.get("formation_ref")
        location_ref = wake.get("location_ref")
        if not isinstance(formation_ref, str) or not isinstance(location_ref, str):
            raise ValueError("pending wake is invalid")
        try:
            _path, formation = self._load_formation(formation_ref)
        except ValueError:
            formation = {}
        still_player_commanded = str(formation.get("commander_ref", "")) == self.PLAYER_ACTOR
        still_at_contact = str(formation.get("location_ref", "")) == location_ref
        if still_player_commanded and still_at_contact:
            return

        runtime = _deepcopy(self.read(_RUNTIME_PATH))
        current_wake = self._pending_wake(runtime)
        if current_wake is None or current_wake.get("wake_ref") != wake.get("wake_ref"):
            return
        host_id = current_wake.get("target_host")
        event_id = current_wake.get("event_id")
        hosts = runtime.get("hosts")
        host = hosts.get(host_id) if isinstance(hosts, dict) and isinstance(host_id, str) else None
        event = self._event_by_id(runtime, str(event_id)) if isinstance(event_id, str) else None
        if not isinstance(host, dict) or event is None:
            raise ValueError("pending wake lost its causal host")
        now = CampaignTime.parse(str(runtime["world_time"]))
        resume_at = now.add_seconds(3600)
        host["next_due"] = str(resume_at)
        host["safe_through"] = str(now)
        event["due_at"] = str(resume_at)
        event.pop("suspended", None)
        runtime.pop("pending_wake", None)
        runtime.pop("acknowledged_wake", None)
        self.put(_RUNTIME_PATH, runtime)

    # ------------------------------------------------------------------
    # Global chronological scheduler
    # ------------------------------------------------------------------

    @staticmethod
    def _queue_runtime_events(runtime: Mapping[str, Any]) -> list[tuple[CampaignTime, int, str]]:
        hosts = runtime.get("hosts")
        events = runtime.get("events")
        if not isinstance(hosts, Mapping) or not isinstance(events, list):
            raise ValueError("runtime causal queue is invalid")
        queue: list[tuple[CampaignTime, int, str]] = []
        for event in events:
            if not isinstance(event, Mapping):
                raise ValueError("runtime event is invalid")
            event_id = event.get("event_id")
            host_id = event.get("target_host")
            host = hosts.get(host_id) if isinstance(host_id, str) else None
            if not isinstance(event_id, str) or not isinstance(host, Mapping):
                raise ValueError("runtime event routing is invalid")
            if event.get("suspended") is True or host.get("next_due") is None:
                continue
            due_text = event.get("due_at")
            if not isinstance(due_text, str) or due_text != host.get("next_due"):
                raise ValueError("runtime event and host due time diverged")
            heapq.heappush(
                queue,
                (CampaignTime.parse(due_text), int(event.get("priority", 100)), event_id),
            )
        return queue

    def _settle_core_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        kind = host.get("kind")
        if kind == "state":
            self._autonomy_state(host, 1, due_text)
        elif kind == "population":
            self._autonomy_population(host, 1, due_text)
        elif kind == "population_mobility" and hasattr(self, "_autonomy_population_mobility"):
            self._autonomy_population_mobility(host, 1, due_text)
        elif kind == "population_mobility_arrival" and hasattr(self, "_settle_population_mobility_arrival"):
            self._settle_population_mobility_arrival(host, due_text)
        elif kind == "house":
            self._autonomy_house(host, 1, due_text)
        elif kind == "institution":
            self._autonomy_institution(host, 1, due_text)
        elif kind == "institution_bundle" and hasattr(self, "_autonomy_institution_bundle"):
            self._autonomy_institution_bundle(host, 1, due_text)
        elif kind == "faction":
            self._autonomy_faction(host, 1, due_text)
        elif kind == "polity":
            self._autonomy_polity(host, 1, due_text)
        elif kind == "mercenary":
            self._autonomy_mercenary(host, 1, due_text)
        elif kind == "interstate":
            self._autonomy_interstate(host, 1, due_text)
        elif kind == "person":
            self._autonomy_person(host, 1, due_text)
        elif kind == "house_tang_training":
            self._autonomy_house_tang_training(host, 1, due_text)

    @staticmethod
    def _battlefield_report_wake(report: Mapping[str, Any], at: str) -> Dict[str, Any]:
        report_id = str(report.get("report_id", "battlefield_report"))
        operation_ref = str(report.get("operation_ref", ""))
        digest = hashlib.sha256(f"{operation_ref}:{report_id}:{at}".encode("utf-8")).hexdigest()[:16]
        return {
            "wake_ref": f"wake_battlefield_{digest}",
            "kind": "battlefield_report",
            "at": at,
            "operation_ref": operation_ref,
            "battlefield_ref": report.get("battlefield_ref"),
            "sector_ref": report.get("sector_ref"),
            "report_id": report.get("report_id"),
            "level": report.get("level"),
            "reason": "delivered_battlefield_report",
        }

    def _advance_causal_runtime(self, target_text: str) -> Dict[str, Any]:
        runtime = _deepcopy(self.read(_RUNTIME_PATH))
        current = CampaignTime.parse(str(runtime["world_time"]))
        target = CampaignTime.parse(target_text)
        if target < current:
            raise ValueError("time may not move backward")

        ensure_scheduler_state(runtime)
        assert_frontier_consistent(runtime)
        pending = self._resume_pending_wake(runtime)
        self.put(_RUNTIME_PATH, runtime)
        queue = self._queue_runtime_events(runtime)
        # Track scheduler route *generations*, not bare event IDs.  One-shot
        # routes may be retired and later recreated for the same durable action
        # during one long advance, and synchronizers may lawfully retime an
        # existing event.  Treat (event_id, due_at) as the queue identity so a
        # newly due incarnation cannot be lost merely because an earlier
        # incarnation used the same stable event ID.
        initial_events = runtime.get("events", [])
        event_index = {
            str(event.get("event_id")): event
            for event in initial_events
            if isinstance(event, dict) and isinstance(event.get("event_id"), str)
        } if isinstance(initial_events, list) else {}
        event_positions = {
            str(event.get("event_id")): idx
            for idx, event in enumerate(initial_events)
            if isinstance(event, dict) and isinstance(event.get("event_id"), str)
        } if isinstance(initial_events, list) else {}
        known_event_routes = {
            (str(event.get("event_id")), str(event.get("due_at")))
            for event in initial_events
            if isinstance(event, Mapping)
            and isinstance(event.get("event_id"), str)
            and isinstance(event.get("due_at"), str)
        }

        def refresh_event_index(runtime_doc: Mapping[str, Any], *, force: bool = False) -> None:
            nonlocal event_index, event_positions
            if not force:
                return
            events_doc = runtime_doc.get("events", [])
            if not isinstance(events_doc, list):
                raise ValueError("runtime events registry is invalid")
            event_index = {
                str(row.get("event_id")): row
                for row in events_doc
                if isinstance(row, dict) and isinstance(row.get("event_id"), str)
            }
            event_positions = {
                str(row.get("event_id")): idx
                for idx, row in enumerate(events_doc)
                if isinstance(row, dict) and isinstance(row.get("event_id"), str)
            }

        def remove_event_route(runtime_doc: dict[str, Any], remove_id: str) -> None:
            """Remove one scheduler event in O(1) while preserving index validity."""
            events_doc = runtime_doc.get("events")
            if not isinstance(events_doc, list):
                raise ValueError("runtime events registry is invalid")
            pos = event_positions.get(remove_id)
            if pos is None or pos >= len(events_doc) or not isinstance(events_doc[pos], Mapping) or str(events_doc[pos].get("event_id", "")) != remove_id:
                # Exceptional structural mismatch: repair the bounded index once.
                refresh_event_index(runtime_doc, force=True)
                pos = event_positions.get(remove_id)
            if pos is None or pos >= len(events_doc):
                raise ValueError("scheduler event removal lost event position")
            last_index = len(events_doc) - 1
            if pos != last_index:
                moved = events_doc[last_index]
                events_doc[pos] = moved
                if isinstance(moved, Mapping) and isinstance(moved.get("event_id"), str):
                    moved_id = str(moved.get("event_id"))
                    event_positions[moved_id] = pos
                    if isinstance(moved, dict):
                        event_index[moved_id] = moved
            events_doc.pop()
            event_positions.pop(remove_id, None)
            event_index.pop(remove_id, None)

        def enqueue_unseen_routes(runtime_doc: Mapping[str, Any], rows: Any) -> None:
            if not isinstance(rows, list):
                return
            hosts_doc = runtime_doc.get("hosts", {})
            for added in rows:
                if not isinstance(added, Mapping):
                    continue
                added_id = added.get("event_id")
                added_due_text = added.get("due_at")
                if not isinstance(added_id, str) or not isinstance(added_due_text, str):
                    continue
                route_generation = (added_id, added_due_text)
                if route_generation in known_event_routes:
                    continue
                known_event_routes.add(route_generation)
                added_host_id = added.get("target_host")
                added_host = hosts_doc.get(added_host_id) if isinstance(hosts_doc, Mapping) else None
                if not isinstance(added_host, Mapping) or added.get("suspended") is True or added_host.get("next_due") is None:
                    continue
                heapq.heappush(queue, (CampaignTime.parse(added_due_text), int(added.get("priority", 100)), added_id))

        def rebuild_live_queue(runtime_doc: Mapping[str, Any]) -> None:
            """Replace stale route generations after a registry reconciliation.

            Reconciliation may retime existing event IDs. Appending the new
            generations to the current heap leaves every superseded future due
            entry resident until its old timestamp is popped. Across a long
            single advance those stale generations can dominate chronology work.
            The runtime event registry is the bounded routing authority, so after
            an exceptional full-registry rewrite rebuild the heap from its current
            live routes instead of accumulating obsolete generations.
            """
            nonlocal queue, known_event_routes
            queue = self._queue_runtime_events(runtime_doc)
            events_doc = runtime_doc.get("events", [])
            known_event_routes = {
                (str(row.get("event_id")), str(row.get("due_at")))
                for row in events_doc
                if isinstance(row, Mapping)
                and isinstance(row.get("event_id"), str)
                and isinstance(row.get("due_at"), str)
            } if isinstance(events_doc, list) else set()

        woken_events: set[str] = set()
        processed = 0
        wake_result: Optional[Dict[str, Any]] = None
        battlefield_reports: list[Dict[str, Any]] = []
        battlefield_reviews: list[Dict[str, Any]] = []
        campaign_event_notices: list[Dict[str, Any]] = []

        def settle_battlefields_until(limit: CampaignTime) -> bool:
            nonlocal wake_result
            # _advance_runtime stages the scheduler owner before entering this
            # helper. Re-read that staged object directly instead of cloning the
            # full host/event registry for every causal boundary. Any failed
            # preview discards the staged planner writes transactionally.
            current_runtime = self.read(_RUNTIME_PATH)
            start = CampaignTime.parse(str(current_runtime["world_time"]))
            if limit <= start:
                return False
            battlefield = self._settle_operational_battlefields(start, limit)
            battlefield_reports.extend(
                dict(row) for row in battlefield.get("delivered_reports", []) if isinstance(row, Mapping)
            )
            battlefield_reviews.extend(
                dict(row) for row in battlefield.get("reviews", []) if isinstance(row, Mapping)
            )
            if not battlefield.get("player_interrupt"):
                return False
            reached = str(battlefield.get("reached_time", limit))
            if self._active_command_type != "advance_time":
                raise HighSalienceWakeRequired("player_command_crosses_battlefield_report_boundary")
            if not battlefield_reports:
                raise ValueError("battlefield interrupt has no delivered player report")
            wake = self._battlefield_report_wake(battlefield_reports[-1], reached)
            runtime_at_boundary = self.read(_RUNTIME_PATH)
            set_causal_frontier(runtime_at_boundary, reached)
            runtime_at_boundary["pending_wake"] = wake
            runtime_at_boundary.pop("acknowledged_wake", None)
            self.put(_RUNTIME_PATH, runtime_at_boundary)
            wake_result = wake
            return True

        while queue:
            due, _priority, event_id = heapq.heappop(queue)
            if due > target:
                break
            runtime = self.read(_RUNTIME_PATH)
            refresh_event_index(runtime)
            event = event_index.get(event_id)
            if event is None or event.get("suspended") is True:
                continue
            hosts = runtime.get("hosts")
            host_id = event.get("target_host")
            host = hosts.get(host_id) if isinstance(hosts, dict) and isinstance(host_id, str) else None
            if not isinstance(host, dict) or host.get("next_due") is None:
                continue
            current_due = CampaignTime.parse(str(event.get("due_at")))
            if current_due != due or str(host.get("next_due")) != str(event.get("due_at")):
                continue

            # Operational battlefield movement, pressure and messenger clocks
            # share the same campaign chronology. Settle them up to this exact
            # causal instant before allowing the next autonomous host to fire.
            if settle_battlefields_until(due):
                break

            processed += 1
            woken_events.add(event_id)
            due_text = str(due)

            # Make the exact due instant visible to callbacks. If a callback
            # creates a child/person host, its scheduler mutation is based on
            # this causal instant and is preserved when we re-read after it.
            set_causal_frontier(runtime, due_text, refresh_next_due=False)
            self.put(_RUNTIME_PATH, runtime)
            self._active_event_id = event_id
            self._active_host_id = str(host_id)
            self._pending_wake_created = None
            events_before_callback = runtime.get("events", [])
            events_before_len = len(events_before_callback) if isinstance(events_before_callback, list) else 0
            host_runner = getattr(self, "_run_due_host", None)
            if callable(host_runner):
                host_runner(copy.deepcopy(host), due_text)
            else:
                from sword_runtime.time_integration import dispatch_due_host
                dispatch_due_host(self, copy.deepcopy(host), due_text)

            runtime_after = self.read(_RUNTIME_PATH)
            events_after_callback = runtime_after.get("events", [])
            if not isinstance(events_after_callback, list):
                raise ValueError("runtime events registry is invalid after causal callback")
            appended_rows = list(events_after_callback[events_before_len:]) if len(events_after_callback) > events_before_len else []
            # Register appended event positions immediately, before this callback's
            # settled one-shot route can be swap-deleted. That deletion may move the
            # newly appended tail row into the retired slot; remove_event_route()
            # will then update the moved row's exact position in O(1).
            for idx, row in enumerate(appended_rows, start=events_before_len):
                if isinstance(row, dict) and isinstance(row.get("event_id"), str):
                    rid = str(row.get("event_id"))
                    event_index[rid] = row
                    event_positions[rid] = idx
            # Planner reads return fresh Python containers, so object identity is
            # not a scheduler-registry generation signal. Keep the O(1) event
            # position map across ordinary callbacks and rebuild only when a
            # callback can actually rewrite existing routes, a route was removed,
            # or the expected position no longer contains this event.
            callback_kind = str(host.get("kind", ""))
            rebuild_registry = callback_kind == "scheduler_reconcile" or len(events_after_callback) < events_before_len
            pos = event_positions.get(event_id)
            if not rebuild_registry and (pos is None or pos >= len(events_after_callback) or not isinstance(events_after_callback[pos], Mapping) or str(events_after_callback[pos].get("event_id", "")) != event_id):
                rebuild_registry = True
            if rebuild_registry:
                refresh_event_index(runtime_after, force=True)
                event_after = event_index.get(event_id)
            else:
                event_after = events_after_callback[pos]
                event_index[event_id] = event_after
            hosts_after = runtime_after.get("hosts")
            host_after = hosts_after.get(host_id) if isinstance(hosts_after, dict) else None
            if event_after is None or not isinstance(host_after, dict):
                raise ValueError("causal callback removed its own scheduler route")

            recurrence = int(host_after.get("recurrence_seconds", 0))
            retire_after_settlement = host_after.get("retire_after_settlement") is True
            wake_created = copy.deepcopy(self._pending_wake_created)
            if wake_created is not None and wake_created.get("kind") == "campaign_event":
                campaign_event_notices.append(wake_created)
                # Informational campaign events are delivered in the command result
                # but do not become a blocking pending wake. The scheduler proceeds
                # on its normal recurrence so notices cannot trap play in hourly
                # acknowledge/resume loops.
                wake_created = None

            if wake_created is not None:
                if self._active_command_type != "advance_time":
                    raise HighSalienceWakeRequired("player_command_crosses_autonomous_contact_boundary")
                host_after["resolved_through"] = due_text
                host_after["next_due"] = None
                host_after["safe_through"] = due_text
                event_after["due_at"] = due_text
                event_after["suspended"] = True
                runtime_after["pending_wake"] = wake_created
                runtime_after.pop("acknowledged_wake", None)
                set_causal_frontier(runtime_after, due_text)
                self.put(_RUNTIME_PATH, runtime_after)
                wake_result = wake_created
                break

            host_after["resolved_through"] = due_text
            if retire_after_settlement:
                host_after["safe_through"] = due_text
                hosts_after.pop(host_id, None)
                remove_event_route(runtime_after, event_id)
                set_causal_frontier(runtime_after, due_text, refresh_next_due=False)
                self.put(_RUNTIME_PATH, runtime_after)
                if rebuild_registry:
                    refresh_event_index(runtime_after, force=True)
                    rebuild_live_queue(runtime_after)
                elif appended_rows:
                    enqueue_unseen_routes(runtime_after, appended_rows)
                continue
            if recurrence <= 0:
                host_after["next_due"] = None
                host_after["safe_through"] = due_text
                event_after["due_at"] = due_text
                event_after["suspended"] = True
                # A completed one-shot scheduler route is not historical authority.
                # Durable results live in their exact domain owner or semantic event
                # store, so retire the terminal host/event immediately.
                hosts_after.pop(host_id, None)
                remove_event_route(runtime_after, event_id)
            else:
                successor = due.add_seconds(recurrence)
                host_after["next_due"] = str(successor)
                host_after["safe_through"] = str(successor.add_seconds(-1))
                event_after["due_at"] = str(successor)
                event_after.pop("suspended", None)
                successor_route = (event_id, str(successor))
                known_event_routes.add(successor_route)
                heapq.heappush(queue, (successor, int(event_after.get("priority", 100)), event_id))
            set_causal_frontier(runtime_after, due_text, refresh_next_due=False)
            self.put(_RUNTIME_PATH, runtime_after)

            # Most callbacks append new routes to the existing scheduler list.
            # Inspect only that appended suffix. A reconciliation callback may
            # legitimately retime existing routes, and a callback may replace the
            # registry object; those bounded exceptional cases rebuild once.
            if rebuild_registry:
                # Reconciliation is the one routine callback allowed to retime
                # existing routes. A structural mismatch is treated just as
                # conservatively. Rebuild from the bounded authoritative registry
                # so superseded future generations do not accumulate in one long
                # causal heap.
                refresh_event_index(runtime_after, force=True)
                rebuild_live_queue(runtime_after)
            elif appended_rows:
                # Positions were registered before any swap-delete and therefore
                # remain exact without an O(N) list.index() search here.
                enqueue_unseen_routes(runtime_after, appended_rows)

        if wake_result is None:
            final_cursor = CampaignTime.parse(str(self.read(_RUNTIME_PATH)["world_time"]))
            if final_cursor < target:
                settle_battlefields_until(target)

        final_runtime = self.read(_RUNTIME_PATH)
        if wake_result is None:
            set_causal_frontier(final_runtime, target_text)
        else:
            assert_frontier_consistent(final_runtime)
        metrics = final_runtime.setdefault("metrics", {})
        # Expose the exact route identities to the outer chronology orchestrator
        # without widening the player-facing command result. Long atomic advances
        # may use multiple in-memory heap windows and must deduplicate recurring
        # routes exactly as one monolithic heap would.
        self._last_causal_woken_event_ids = frozenset(woken_events)
        metrics["hosts_woken"] = int(metrics.get("hosts_woken", 0)) + len(woken_events)
        metrics["events_processed"] = int(metrics.get("events_processed", 0)) + processed
        for key in ("global_person_scans", "global_faction_scans", "global_force_scans", "global_house_scans"):
            metrics.setdefault(key, 0)
        self.put(_RUNTIME_PATH, final_runtime)
        result: Dict[str, Any] = {
            "requested_time": target_text,
            "causal_settled_through": str(final_runtime.get("scheduler", {}).get("causal_settled_through", final_runtime.get("world_time"))),
            "hosts_woken": len(woken_events),
            "events_processed": processed,
            "battlefield_reports": battlefield_reports,
            "battlefield_reviews": len(battlefield_reviews),
            "battlefield_player_interrupt": bool(wake_result is not None and wake_result.get("kind") == "battlefield_report"),
            "campaign_event_notices": campaign_event_notices,
        }
        if wake_result is not None:
            result["interrupted"] = True
            result["wake_required"] = True
            result["wake"] = wake_result
        elif pending is not None and self._active_command_type != "advance_time":
            result["pending_wake_preserved"] = True
        return result

    # ------------------------------------------------------------------
    # Command routing around an active player wake
    # ------------------------------------------------------------------

    def _command_layer_causal_living_world(self, command: CommandEnvelope, payload: Mapping[str, Any], next_dispatch: Any) -> Dict[str, Any]:
        previous = self._active_command_type
        self._active_command_type = command.command_type
        try:
            runtime_before = self.read(_RUNTIME_PATH)
            pending = self._pending_wake(runtime_before)
            if pending is not None and command.command_type not in _WAKE_RESPONSE_COMMANDS:
                raise HighSalienceWakeRequired("pending_autonomous_contact_requires_player_resolution")

            if command.command_type == "advance_time":
                target_text = payload.get("target_time")
                if not target_text:
                    current = CampaignTime.parse(str(self.read(_RUNTIME_PATH)["world_time"]))
                    target_text = str(current.add_seconds(int(payload.get("hours", 0)) * 3600))
                metrics = self._advance_runtime(str(target_text))
                actual_time = str(self.read(_RUNTIME_PATH)["world_time"])
                self._write_meta(command, actual_time)
                result = self._result(world_time=actual_time, **metrics)
                return result

            result = next_dispatch()
            if pending is not None:
                self._resolve_pending_wake_after_response(pending)
            return result
        finally:
            self._active_command_type = previous
            self._active_event_id = None
            self._active_host_id = None
            self._pending_wake_created = None

    # ------------------------------------------------------------------
    # Interstate contact, battle memory, provenance, and social evidence
    # ------------------------------------------------------------------

    def _autonomy_interstate(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        if occurrences != 1:
            raise ValueError("production interstate settlement must be chronological")
        before = copy.deepcopy(self.read(_INTERSTATE_PATH))
        before_phases = {
            str(ref): str(record.get("phase", "peace"))
            for ref, record in before.get("theaters", {}).items()
            if isinstance(record, Mapping)
        }
        super()._autonomy_interstate(host, 1, at)
        after = self.read(_INTERSTATE_PATH)
        config = self.read("game/data/world/autonomous-theaters.json")
        wakes: list[Dict[str, Any]] = []
        runtime = _deepcopy(self.read(_RUNTIME_PATH))
        acknowledged = runtime.get("acknowledged_wake") if isinstance(runtime.get("acknowledged_wake"), Mapping) else None

        for cfg in config.get("theaters", []):
            if not isinstance(cfg, Mapping):
                continue
            theater_ref = str(cfg.get("theater_ref", ""))
            record = after.get("theaters", {}).get(theater_ref)
            if not theater_ref or not isinstance(record, Mapping):
                continue
            phase = str(record.get("phase", "peace"))

            # A previously acknowledged contact is consumed once the theater
            # leaves engaged state, whether through battle or lawful withdrawal.
            if (
                isinstance(acknowledged, Mapping)
                and acknowledged.get("theater_ref") == theater_ref
                and phase != "engaged"
            ):
                runtime.pop("acknowledged_wake", None)
                acknowledged = None

            if before_phases.get(theater_ref) == "engaged" or phase != "engaged":
                continue
            attacker = str(record.get("attacker_state", ""))
            defender = str(record.get("defender_state", ""))

            # Multi-front campaigns no longer have one canonical formation per
            # side. Contact authority therefore comes from the saved strategic
            # fronts/formation groups first, with the cold theater singleton only
            # as compatibility fallback. This keeps player agency intact when Wei
            # commands any lawful field army on any active axis.
            plan = record.get("strategic_plan") if isinstance(record.get("strategic_plan"), Mapping) else {}
            fronts = plan.get("fronts") if isinstance(plan.get("fronts"), list) else []
            saved_groups = record.get("formation_groups") if isinstance(record.get("formation_groups"), Mapping) else {}
            legacy_refs = cfg.get("formation_refs") if isinstance(cfg.get("formation_refs"), Mapping) else {}

            candidates: list[tuple[str, str, str]] = []
            for state, opponent, front_key in ((attacker, defender, "attacker_formation_refs"), (defender, attacker, "defender_formation_refs")):
                seen: set[str] = set()
                for front in fronts:
                    if not isinstance(front, Mapping) or str(front.get("status", "")) != "engaged":
                        continue
                    location_ref = str(front.get("objective_ref") or record.get("contact_location_ref") or cfg.get("target_location_ref", ""))
                    for formation_ref in front.get(front_key, []) if isinstance(front.get(front_key), list) else []:
                        if isinstance(formation_ref, str) and formation_ref not in seen:
                            seen.add(formation_ref); candidates.append((formation_ref, opponent, location_ref))
                if not seen:
                    group = saved_groups.get(state) if isinstance(saved_groups.get(state), list) else []
                    for formation_ref in group:
                        if isinstance(formation_ref, str) and formation_ref not in seen:
                            seen.add(formation_ref); candidates.append((formation_ref, opponent, str(record.get("contact_location_ref") or cfg.get("target_location_ref", ""))))
                if not seen:
                    formation_ref = legacy_refs.get(state)
                    if isinstance(formation_ref, str):
                        candidates.append((formation_ref, opponent, str(record.get("contact_location_ref") or cfg.get("target_location_ref", ""))))

            for formation_ref, opponent, contact_location in candidates:
                try:
                    _path, formation = self._load_formation(formation_ref)
                except ValueError:
                    continue
                if str(formation.get("commander_ref", "")) != self.PLAYER_ACTOR:
                    continue
                location_ref = contact_location or str(formation.get("location_ref", ""))
                if location_ref and str(formation.get("location_ref", "")) != location_ref:
                    continue
                if isinstance(acknowledged, Mapping) and acknowledged.get("theater_ref") == theater_ref:
                    continue
                wake_ref = "wake.interstate_contact." + hashlib.sha256(
                    f"{theater_ref}|{formation_ref}|{at}".encode("utf-8")
                ).hexdigest()[:20]
                wakes.append(
                    {
                        "wake_ref": wake_ref,
                        "kind": "interstate_contact",
                        "at": at,
                        "theater_ref": theater_ref,
                        "formation_ref": formation_ref,
                        "location_ref": location_ref,
                        "opponent_state": opponent,
                        "reason": "player-commanded formation made enemy contact before autonomous battle resolution",
                        "target_host": self._active_host_id,
                        "event_id": self._active_event_id,
                    }
                )

        self.put(_RUNTIME_PATH, runtime)
        if len(wakes) > 1:
            raise ValueError("multiple player-commanded contact wakes occurred at one causal instant")
        self._pending_wake_created = wakes[0] if wakes else None

    def _record_interstate_battle_memory(self, event: Mapping[str, Any], at: str) -> None:
        # The inherited interstate reducer owns the actual battle result. This
        # overlay adds bounded provenance to that same mutable event before the
        # planned history after-image is serialized.
        if isinstance(event, dict):
            battlefield = event.get("location_ref", event.get("battlefield_ref"))
            theater = event.get("theater_ref")
            attacker_state = event.get("attacker_state")
            defender_state = event.get("defender_state")
            attacker_ref = event.get("attacker_formation_ref")
            defender_ref = event.get("defender_formation_ref")
            losses = event.get("losses") if isinstance(event.get("losses"), Mapping) else {}

            place_refs = [str(battlefield)] if isinstance(battlefield, str) and battlefield else []
            causal_refs = [str(theater)] if isinstance(theater, str) and theater else []
            affected: list[str] = []
            for value in (attacker_ref, defender_ref):
                if isinstance(value, str) and value and value not in affected:
                    affected.append(value)
            for state in (attacker_state, defender_state):
                if isinstance(state, str) and state:
                    ref = f"state_{state}"
                    if ref not in affected:
                        affected.append(ref)

            actor_refs: list[str] = []
            material: list[str] = []
            for formation_ref, row in sorted(losses.items()):
                if not isinstance(formation_ref, str) or not isinstance(row, Mapping):
                    continue
                commander = row.get("commander_ref")
                if isinstance(commander, str) and commander and commander not in actor_refs:
                    actor_refs.append(commander)
                loss = row.get("loss")
                if isinstance(loss, int) and not isinstance(loss, bool) and loss > 0:
                    material.append(f"casualties:{formation_ref}:{loss}")
                commander_outcome = row.get("commander_outcome")
                if isinstance(commander_outcome, str) and commander_outcome not in {"", "unharmed"}:
                    material.append(f"commander:{commander}:{commander_outcome}")

            event["actor_refs"] = actor_refs[:16]
            event["place_refs"] = place_refs
            event["causal_refs"] = causal_refs
            event["affected_owner_refs"] = affected[:16]
            event["material_consequence_refs"] = material[:32]
            event["provenance"] = {
                "kind": "autonomous_runtime_resolution",
                "authority": "existing interstate battle reducer",
                "recorded_at": at,
            }

        super()._record_interstate_battle_memory(event, at)

    def _autonomy_apply_battle_losses(
        self,
        formation_ref: str,
        loss: int,
        at: str,
        *,
        losing_side: bool,
        opponent_state: str,
        seed_material: str,
    ) -> Dict[str, Any]:
        try:
            _path, formation = self._load_formation(formation_ref)
        except ValueError:
            formation = {}
        if str(formation.get("commander_ref", "")) == self.PLAYER_ACTOR:
            runtime = self.read(_RUNTIME_PATH)
            acknowledged = runtime.get("acknowledged_wake") if isinstance(runtime, Mapping) else None
            if not isinstance(acknowledged, Mapping) or acknowledged.get("formation_ref") != formation_ref:
                raise HighSalienceWakeRequired("player_commander_autonomous_battle_requires_handoff")
            # Bypass the parent wake guard only for this exact acknowledged
            # formation. The original reducer remains the mechanical authority.
            return RepositoryCommandPlanner._autonomy_apply_battle_losses(
                self,
                formation_ref,
                loss,
                at,
                losing_side=losing_side,
                opponent_state=opponent_state,
                seed_material=seed_material,
            )
        return super()._autonomy_apply_battle_losses(
            formation_ref,
            loss,
            at,
            losing_side=losing_side,
            opponent_state=opponent_state,
            seed_material=seed_material,
        )


__all__ = ["CausalLivingWorldSwordPlanner"]
