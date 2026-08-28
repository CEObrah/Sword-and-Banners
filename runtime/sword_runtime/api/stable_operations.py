"""Production operations with stable low-information failure classification."""
from __future__ import annotations

import copy

from collections.abc import Mapping
from typing import Any, Optional

from sword_runtime.api.command_discovery import compact_command_family
from sword_runtime.api.interaction_surface import (
    HOT_FORMATION_LIMIT,
    HOT_INFORMATION_LIMIT,
    INTERACTION_ACTIONS,
    SCENE_SESSION_ACTIONS,
    fresh_runtime_projection,
    recent_interaction_attempts,
    translate_interaction_command,
    translate_scene_action_command,
    triggered_interaction_handles,
    triggered_interaction_page,
    triggered_interaction_record,
    validate_interaction_payload,
    validate_scene_action_payload,
)
from sword_runtime.scene_sessions import (
    active_scene_session, inspect_scene_history, recent_scene_history, scene_session_projection,
)
from sword_runtime.api.operations import CampaignOperations, OperationError, _receipt_record
from sword_runtime.api.input_guidance import COMMAND_INPUT_GUIDANCE, INPUT_GUIDANCE_POLICY
from sword_runtime.causal_living_world import _WAKE_RESPONSE_COMMANDS
from sword_runtime.battle_command import player_battle_missions
from sword_runtime.campaign_briefing import campaign_arc_ref, latest_campaign_briefing_ref
from sword_runtime.campaign_command_cycle import campaign_command_projection
from sword_runtime.command_contracts import COMMAND_PAYLOAD_KEYS
from sword_runtime.commands import CommandEnvelope
from sword_runtime.engine import COMMAND_TYPES
from sword_runtime.living_world import HighSalienceWakeRequired
from sword_runtime.tx.errors import (
    CommitVerificationError,
    ConcurrentModificationError,
    DirtyRepositoryError,
    GitCommitError,
    GitStageError,
    IdempotencyConflictError,
    LockUnavailableError,
    ReadbackVerificationError,
    RecoveryError,
    RemoteDurabilityError,
    StaleRevisionError,
    TransactionError,
    WalError,
)


_TRANSACTION_CODES = {
    GitStageError: "transaction_git_stage_failed",
    GitCommitError: "transaction_git_commit_failed",
    CommitVerificationError: "transaction_commit_verification_failed",
    ReadbackVerificationError: "transaction_readback_failed",
    WalError: "transaction_wal_failed",
    ConcurrentModificationError: "transaction_concurrent_modification",
}

_COMMAND_SCENE_EVENT_KINDS = frozenset({
    "campaign_command_council", "campaign_command_superior_order", "campaign_command_after_action_review",
    "campaign_command_dawn_briefing", "campaign_command_evening_sitrep",
})


def _compact_interaction_attempts(attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep player-authored conversational continuity without importing outcomes."""
    return [
        {
            key: row.get(key)
            for key in (
                "event_id", "at", "action", "target_ref", "process_ref", "formation_refs",
                "player_statement", "posture", "topic", "scopes", "scene_session_ref", "thread_status",
                "resolved_at", "response_ref",
            )
            if row.get(key) not in (None, [], "")
        }
        for row in attempts
    ]


def _campaign_command_present_refs(
    handles: list[dict[str, Any]],
    *,
    current_time: object,
    player_location: object,
    runtime: Mapping[str, Any],
    active_session: Mapping[str, Any] | None = None,
) -> set[str]:
    """Return exact command-event people whose scene window is still live.

    Most command events are point-in-time handoffs. A formal war council is a
    multi-hour physical session: its exact attendees remain scene-present until
    the deterministic council-return host retires. This preserves the event's
    physical truth across interaction writes and conservative in-scene time
    advances without turning broad city co-location into same-room presence.
    """
    hosts = runtime.get("hosts") if isinstance(runtime, Mapping) else None
    active_council_cycles = {
        str(host.get("cycle_ref"))
        for host in hosts.values()
        if isinstance(hosts, Mapping)
        for host in [host]
        if isinstance(host, Mapping)
        and host.get("kind") == "campaign_command_council_return"
        and isinstance(host.get("cycle_ref"), str)
        and host.get("cycle_ref")
    } if isinstance(hosts, Mapping) else set()

    refs: set[str] = set()
    for row in handles:
        if not isinstance(row, Mapping):
            continue
        kind = row.get("kind")
        if kind not in _COMMAND_SCENE_EVENT_KINDS:
            continue
        cycle_ref = row.get("campaign_command_cycle_ref")
        active_council = (
            kind == "campaign_command_council"
            and isinstance(cycle_ref, str)
            and cycle_ref in active_council_cycles
            and isinstance(active_session, Mapping)
            and active_session.get("status") == "active"
            and active_session.get("kind") == "war_council"
            and active_session.get("process_ref") == cycle_ref
        )
        if row.get("triggered_at") != current_time and not active_council:
            continue
        delivery = row.get("delivery") if isinstance(row.get("delivery"), Mapping) else {}
        if delivery.get("location_ref") != player_location:
            continue
        for ref in row.get("present_person_refs", []) if isinstance(row.get("present_person_refs"), list) else []:
            if isinstance(ref, str) and ref.startswith("char_"):
                refs.add(ref)
    return refs


_WAKE_VISIBLE_FIELDS = (
    "wake_ref", "kind", "at", "theater_ref", "formation_ref", "location_ref",
    "opponent_state", "operation_ref", "battlefield_ref",
    "sector_ref", "report_id", "level", "reason",
    "ceremony_ref", "closure_event_ref", "state_ref",
)


def transaction_failure_code(exc: TransactionError) -> str:
    for exc_type, code in _TRANSACTION_CODES.items():
        if isinstance(exc, exc_type):
            return code
    return "transaction_rejected"


class StableCampaignOperations(CampaignOperations):
    """Player surface that fails closed without leaking server/Git internals."""

    @staticmethod
    def _formation_sort_key(item: Mapping[str, Any], player_location: object) -> tuple[int, str]:
        return (0 if item.get("location_ref") == player_location else 1, str(item.get("formation_ref") or ""))

    @staticmethod
    def _cursor_offset(cursor: Optional[str], code: str) -> int:
        if cursor is None:
            return 0
        if not isinstance(cursor, str) or not cursor.isdigit() or len(cursor) > 12:
            raise OperationError(422, code)
        offset = int(cursor)
        if offset < 0 or offset > 1_000_000:
            raise OperationError(422, code)
        return offset

    def _all_controlled_formations(self, player_id: str) -> list[dict[str, Any]]:
        return super()._controlled_formations(player_id)

    def _controlled_command_group_views(self, player_id: str) -> list[dict[str, Any]]:
        """Bounded exact command-group projection for groups the player commands.

        Command groups are zero-body authority owners. Their commander, explicit
        staff roles and successor order must not disappear merely because those
        people are not also formation commanders in the compact formation window.
        """
        try:
            index = self.store.read_json("state/cmd/command-groups/index.json")
        except (FileNotFoundError, ValueError):
            return []
        refs = index.get("refs", []) if isinstance(index, Mapping) else []
        primary = index.get("primary_person_group", {}) if isinstance(index, Mapping) else {}
        primary_ref = primary.get(player_id) if isinstance(primary, Mapping) else None
        staff_routes = index.get("staff_person_groups", {}) if isinstance(index, Mapping) else {}
        candidates: list[dict[str, Any]] = []
        for ref in refs if isinstance(refs, list) else []:
            if not isinstance(ref, str):
                continue
            try:
                group = self.store.read_json(f"state/cmd/command-groups/{ref}.json")
            except (FileNotFoundError, ValueError):
                continue
            if not isinstance(group, Mapping):
                continue
            if ref != primary_ref and group.get("commander_ref") != player_id and group.get("authority_ref") != player_id:
                continue
            units = group.get("units", []) if isinstance(group.get("units"), list) else []
            expected_location = str(group.get("location", "") or "")
            expected_people: list[tuple[str, str]] = []
            for role_key in ("commander_ref",):
                person_ref = group.get(role_key)
                if isinstance(person_ref, str) and person_ref:
                    expected_people.append((person_ref, role_key.removesuffix("_ref")))
            for person_ref in group.get("successor_refs", []) if isinstance(group.get("successor_refs"), list) else []:
                if isinstance(person_ref, str) and person_ref and all(person_ref != existing[0] for existing in expected_people):
                    expected_people.append((person_ref, "successor"))
            role_assignments = group.get("role_assignments", {}) if isinstance(group.get("role_assignments"), Mapping) else {}
            for person_ref, role in sorted(role_assignments.items()):
                if isinstance(person_ref, str) and person_ref.startswith("char_") and all(person_ref != existing[0] for existing in expected_people):
                    expected_people.append((person_ref, str(role or "staff")))

            def _assigned_within_group_tree(assigned_ref: object) -> bool:
                if not isinstance(assigned_ref, str) or not assigned_ref:
                    return False
                current = assigned_ref
                seen: set[str] = set()
                while current and current not in seen:
                    if current == ref:
                        return True
                    seen.add(current)
                    try:
                        row = self.store.read_json(f"state/cmd/command-groups/{current}.json")
                    except (FileNotFoundError, ValueError):
                        return False
                    parent = row.get("parent_command_group_ref") if isinstance(row, Mapping) else None
                    current = str(parent) if isinstance(parent, str) and parent else ""
                return False

            integrity: list[dict[str, Any]] = []
            for person_ref, command_role in expected_people:
                if person_ref == player_id:
                    continue
                try:
                    person_path = self.runtime.planner.owner_path(person_ref)
                    person = self.store.read_json(person_path)
                except (KeyError, FileNotFoundError, ValueError):
                    integrity.append({
                        "person_ref": person_ref,
                        "command_role": command_role,
                        "issue": "missing_exact_person_owner",
                    })
                    continue
                person_location = str(
                    person.get("current_location", person.get("location_ref", person.get("location", ""))) or ""
                ) if isinstance(person, Mapping) else ""
                if expected_location and person_location and person_location != expected_location:
                    integrity.append({
                        "person_ref": person_ref,
                        "command_role": command_role,
                        "issue": "command_group_location_mismatch",
                        "group_location_ref": expected_location,
                        "person_location_ref": person_location,
                    })
                assignment = person.get("command_assignment") if isinstance(person, Mapping) else None
                assigned_group = assignment.get("command_group_ref") if isinstance(assignment, Mapping) else None
                if command_role != "commander":
                    is_staff_role = isinstance(role_assignments, Mapping) and isinstance(role_assignments.get(person_ref), str)
                    if is_staff_role:
                        routed = staff_routes.get(person_ref, []) if isinstance(staff_routes, Mapping) else []
                        assigned_ok = isinstance(routed, list) and ref in routed
                    else:
                        routed = []
                        assigned_ok = _assigned_within_group_tree(assigned_group)
                    if not assigned_ok:
                        integrity.append({
                            "person_ref": person_ref,
                            "command_role": command_role,
                            "issue": "command_group_assignment_mismatch",
                            "expected_command_group_ref": ref,
                            "person_command_group_ref": assigned_group,
                            "indexed_staff_group_refs": list(routed) if isinstance(routed, list) else [],
                        })
            candidates.append({
                "command_group_ref": ref,
                "display_name": group.get("display_name"),
                "context": group.get("context"),
                "location_ref": group.get("location"),
                "commander_ref": group.get("commander_ref"),
                "role_assignments": dict(group.get("role_assignments", {})) if isinstance(group.get("role_assignments"), Mapping) else {},
                "successor_refs": list(group.get("successor_refs", [])) if isinstance(group.get("successor_refs"), list) else [],
                "standing_doctrine_ref": group.get("standing_doctrine_ref"),
                "active_context_ref": group.get("active_context_ref"),
                "integrity_status": "needs_attention" if integrity else "ok",
                "integrity_diagnostics": integrity,
                "direct_units": [
                    {"kind": row.get("kind"), "ref": row.get("ref")}
                    for row in units if isinstance(row, Mapping) and row.get("kind") and row.get("ref")
                ],
                "organizational_state": {
                    key: group.get("organizational_state", {}).get(key)
                    for key in ("status", "authorized_strength", "current_recursive_strength", "reorganization_need")
                    if isinstance(group.get("organizational_state"), Mapping) and group.get("organizational_state", {}).get(key) is not None
                },
            })
        candidates.sort(key=lambda row: (0 if row.get("command_group_ref") == primary_ref else 1, str(row.get("command_group_ref"))))
        return candidates[:8]

    def _all_known_information(self, player_id: str) -> list[dict[str, Any]]:
        return super()._known_information(player_id)

    def _interaction_refs(self) -> tuple[list[dict[str, Any]], set[str], int]:
        handles, total = triggered_interaction_handles(self.store)
        handles = list(reversed(handles))
        return handles, {str(item["interaction_ref"]) for item in handles}, total

    def _player_process_views(self, player_id: str) -> list[dict[str, Any]]:
        """Return only currently actionable durable processes indexed to this player."""
        views: list[dict[str, Any]] = []
        specs = (
            ("state/investigations/index.json", ("investigations",), {"active"}),
            ("state/commissions/index.json", ("requests", "commissions"), {"pending", "offered", "active", "reported"}),
            ("state/commitments/index.json", ("commitments",), {"active", "overdue", "fulfillment_claimed"}),
        )
        for index_path, buckets, active_statuses in specs:
            try:
                index = self.store.read_json(index_path)
            except (FileNotFoundError, ValueError):
                continue
            active_by_actor = index.get("active_by_actor") if isinstance(index, Mapping) else None
            by_actor = index.get("by_actor") if isinstance(index, Mapping) else None
            refs = active_by_actor.get(player_id, []) if isinstance(active_by_actor, Mapping) else (by_actor.get(player_id, []) if isinstance(by_actor, Mapping) else [])
            if not isinstance(refs, list):
                continue
            for object_ref in refs:
                if not isinstance(object_ref, str):
                    continue
                path = None
                for bucket in buckets:
                    mapping = index.get(bucket) if isinstance(index, Mapping) else None
                    candidate = mapping.get(object_ref) if isinstance(mapping, Mapping) else None
                    if isinstance(candidate, str):
                        path = candidate
                        break
                if not isinstance(path, str):
                    continue
                try:
                    record = self.store.read_json(path)
                except (FileNotFoundError, ValueError):
                    continue
                status = record.get("status")
                if status not in active_statuses:
                    continue
                schema = record.get("schema")
                if schema == "sword-investigation":
                    views.append({"object_ref": object_ref, "kind": "investigation", "status": status, "subject_ref": record.get("subject_ref"), "question": record.get("question"), "location_ref": record.get("location_ref"), "worked_hours": record.get("worked_hours")})
                elif schema == "sword-commission-request":
                    views.append({"object_ref": object_ref, "kind": "commission_request", "status": status, "issuer_ref": record.get("issuer_ref"), "category": record.get("category"), "responds_at": record.get("responds_at"), "commission_ref": record.get("commission_ref")})
                elif schema == "sword-commission":
                    views.append({"object_ref": object_ref, "kind": "commission", "status": status, "issuer_ref": record.get("issuer_ref"), "category": record.get("category"), "objective": record.get("objective"), "location_ref": record.get("location_ref"), "settlement_pending": record.get("settlement_pending", False)})
                elif schema == "sword-commitment":
                    views.append({"object_ref": object_ref, "kind": "commitment", "status": status, "obligor_ref": record.get("obligor_ref"), "beneficiary_ref": record.get("beneficiary_ref"), "commitment_kind": record.get("kind"), "description": record.get("description"), "due_at": record.get("due_at")})
        return sorted(views, key=lambda row: (str(row.get("kind")), str(row.get("object_ref"))))


    def _durable_player_decisions(self, player_id: str, player_processes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Project unresolved player-owned choices from exact durable owners.

        These are not scheduler wakes and do not disable unrelated commands. A
        causal wake is reserved for a world state that cannot safely progress
        without the player's immediate response.
        """
        decisions: list[dict[str, Any]] = []
        player = self.store.read_json("state/player.json")
        career = player.get("career_state", {}) if isinstance(player, Mapping) else {}
        refs = career.get("pending_qin_command_offer_refs", []) if isinstance(career, Mapping) else []
        offers = career.get("pending_qin_command_offers", {}) if isinstance(career, Mapping) else {}
        for offer_ref in refs if isinstance(refs, list) else []:
            if not isinstance(offer_ref, str):
                continue
            details = offers.get(offer_ref) if isinstance(offers, Mapping) else None
            if not isinstance(details, Mapping):
                continue
            decisions.append({
                "decision_ref": offer_ref,
                "kind": "qin_field_command_offer",
                "command_type": "interaction_action",
                "response_actions": ["proceed", "comply", "decline"],
                "formation_ref": details.get("formation_ref"),
                "formation_name": details.get("formation_name"),
                "personnel": details.get("personnel"),
                "location_ref": details.get("location_ref"),
                "operation_ref": details.get("operation_ref"),
            })
        for process in player_processes:
            if process.get("kind") != "commission" or process.get("status") != "offered":
                continue
            decisions.append({
                "decision_ref": process.get("object_ref"),
                "kind": "commission_offer",
                "command_type": "commission_action",
                "response_actions": ["accept", "decline"],
                "issuer_ref": process.get("issuer_ref"),
                "category": process.get("category"),
                "objective": process.get("objective"),
                "location_ref": process.get("location_ref"),
            })
        return decisions[:8]

    def _controlled_operation_views(self, controlled_refs: set[str]) -> list[dict[str, Any]]:
        """Return actionable player-safe operation views for controlled forces.

        Exact operations remain authority. Official campaign briefing claims may
        add a bounded snapshot of friendly participation and enemy intelligence;
        undelivered or hidden state never leaks through this projection.
        """
        try:
            index = self.store.read_json("state/operations/index.json")
        except FileNotFoundError:
            return []
        operations = index.get("operations") if isinstance(index, Mapping) else None
        if not isinstance(operations, Mapping):
            return []
        views: list[dict[str, Any]] = []
        for operation_ref, path in sorted(operations.items()):
            if not isinstance(operation_ref, str) or not isinstance(path, str):
                continue
            operation = self.store.read_json(path)
            participants = {str(ref) for ref in operation.get("formation_refs", [])}
            own = participants & controlled_refs
            if not own:
                continue
            battlefields: list[dict[str, Any]] = []
            for battlefield_ref, battlefield in sorted((operation.get("battlefields") or {}).items()):
                if not isinstance(battlefield_ref, str) or not isinstance(battlefield, Mapping):
                    continue
                assignments = battlefield.get("assignments") if isinstance(battlefield.get("assignments"), Mapping) else {}
                own_assignments = {formation_ref: dict(assignments[formation_ref]) for formation_ref in sorted(own) if isinstance(assignments.get(formation_ref), Mapping)}
                player_sides = {str(row.get("side_ref")) for row in own_assignments.values() if row.get("side_ref")}
                delivered_reports = []
                for report in battlefield.get("reports", []):
                    if not isinstance(report, Mapping) or report.get("status") != "delivered" or report.get("target_side_ref") not in player_sides:
                        continue
                    projected = {
                        key: report.get(key)
                        for key in ("report_id", "sector_ref", "target_side_ref", "level", "pressure_milli", "created_at", "delivered_at", "summary", "interrupt_player")
                        if key in report
                    }
                    if hasattr(self.runtime, "_battlefield_enrich_player_report"):
                        projected.update({
                            key: value
                            for key, value in self.runtime._battlefield_enrich_player_report(battlefield, report).items()
                            if key in {"player_can_intervene", "intervention_options"}
                        })
                    delivered_reports.append(projected)
                battlefields.append({
                    "battlefield_ref": battlefield_ref, "name": battlefield.get("name"), "status": battlefield.get("status"),
                    "layout_ref": battlefield.get("layout_ref"), "sector_refs": sorted(str(ref) for ref in (battlefield.get("sectors") or {}) if isinstance(ref, str)),
                    "controlled_assignments": own_assignments, "player_missions": player_battle_missions(battlefield, own), "delivered_reports": delivered_reports,
                    "outcome": copy.deepcopy(battlefield.get("outcome")) if isinstance(battlefield.get("outcome"), Mapping) else None,
                    "opened_at": battlefield.get("opened_at"), "closed_at": battlefield.get("closed_at"), "updated_at": battlefield.get("updated_at"),
                })
            current_order = None
            last_order_ref = str(operation.get("last_operational_order_ref") or "")
            orders = operation.get("operational_orders") if isinstance(operation.get("operational_orders"), list) else []
            if last_order_ref:
                row = next((item for item in reversed(orders) if isinstance(item, Mapping) and str(item.get("order_ref", "")) == last_order_ref), None)
                if isinstance(row, Mapping):
                    current_order = {
                        key: row.get(key)
                        for key in (
                            "order_ref", "issued_at", "issuer_ref", "arc_ref", "target_ref", "objective", "status",
                            "actionability_status", "mission_packet", "follow_on_requirement",
                            "applies_to_formation_refs", "excluded_non_state_formation_refs",
                            "superior_commander_ref", "decision_authority_ref", "transmitted_by_ref", "coordination_authority_ref",
                        ) if key in row
                    }

            # Operation.location_ref may lag a multi-formation command. Use the
            # exact controlled formation locations for current player context.
            own_locations: list[str] = []
            for formation_ref in sorted(own):
                try:
                    formation_path = self.store.read_json("state/index/owner-index.json").get("owners", {}).get(formation_ref)
                    formation = self.store.read_json(formation_path) if isinstance(formation_path, str) else None
                except FileNotFoundError:
                    formation = None
                if isinstance(formation, Mapping) and isinstance(formation.get("location_ref"), str):
                    own_locations.append(str(formation["location_ref"]))
            unique_locations = sorted(set(own_locations))
            location_ref = unique_locations[0] if len(unique_locations) == 1 else operation.get("location_ref")

            arc_ref = campaign_arc_ref(operation)
            briefing_ref = operation.get("briefing_information_ref")
            if not isinstance(briefing_ref, str) or not briefing_ref:
                briefing_ref = latest_campaign_briefing_ref(self.store, operation_ref, arc_ref)
            campaign_context = None
            if isinstance(briefing_ref, str):
                try:
                    info_index = self.store.read_json("state/information/index.json")
                    info_path = info_index.get("claims", {}).get(briefing_ref)
                    info = self.store.read_json(info_path) if isinstance(info_path, str) else None
                except FileNotFoundError:
                    info = None
                if isinstance(info, Mapping) and isinstance(info.get("campaign_context"), Mapping):
                    campaign_context = dict(info["campaign_context"])
            operational_area_ref = None
            strategic_target_ref = None
            entry_status = None
            if isinstance(current_order, Mapping) and isinstance(current_order.get("mission_packet"), Mapping):
                packet = current_order["mission_packet"]
                operational_area_ref = packet.get("destination_ref")
                strategic_target_ref = packet.get("strategic_target_ref")
                entry_status = packet.get("entry_status")
            if isinstance(campaign_context, Mapping):
                area = campaign_context.get("operational_area")
                if isinstance(area, Mapping):
                    if operational_area_ref is None:
                        operational_area_ref = area.get("destination_ref")
                    if strategic_target_ref is None:
                        strategic_target_ref = area.get("strategic_target_ref")
                    if entry_status is None:
                        entry_status = area.get("entry_status")

            campaign_command = campaign_command_projection(getattr(self.runtime, "planner", self.store), operation_ref)

            views.append({
                "operation_ref": operation_ref, "status": operation.get("status"), "objective": operation.get("objective"),
                "location_ref": location_ref, "controlled_formation_refs": sorted(own), "order_status": operation.get("order_status"),
                "campaign_phase": operation.get("campaign_phase"), "campaign_arc_ref": arc_ref,
                "briefing_information_ref": briefing_ref, "last_phase_information_ref": operation.get("last_phase_information_ref"),
                "operational_area_ref": operational_area_ref, "strategic_target_ref": strategic_target_ref, "entry_status": entry_status, "campaign_context": campaign_context,
                "current_operational_order": current_order, "campaign_command": campaign_command, "battlefields": battlefields,
            })
        return views

    def _validate_interaction_authority(self, command: CommandEnvelope) -> None:
        payload = validate_interaction_payload(command.payload)
        base = super().play_context()
        player_id = str(base["campaign"]["player_id"])
        all_formations = self._all_controlled_formations(player_id)
        controlled_refs = {str(item["formation_ref"]) for item in all_formations if item.get("formation_ref")}
        permitted = set(base.get("permitted_person_ids", [])) | set(base.get("permitted_object_refs", []))

        target_ref = payload["target_ref"]
        target_visible = target_ref in permitted or triggered_interaction_record(self.store, target_ref) is not None
        current_location = base.get("player", {}).get("location")
        if payload["action"] == "seek_contact" and target_ref == current_location:
            target_visible = True
        if not target_visible:
            raise OperationError(404, "interaction_target_not_player_visible")

        process_ref = payload["process_ref"]
        if (
            process_ref is not None
            and process_ref not in permitted
            and triggered_interaction_record(self.store, process_ref) is None
        ):
            raise OperationError(404, "interaction_process_not_player_visible")
        if any(ref not in controlled_refs for ref in payload["formation_refs"]):
            raise OperationError(403, "interaction_formation_not_controlled")

    def _validate_scene_session_authority(self, command: CommandEnvelope) -> None:
        payload = validate_scene_action_payload(command.payload)
        base = super().play_context()
        player = self.store.read_json("state/player.json")
        player_location = player.get("location") if isinstance(player, Mapping) else None
        owner_index = self.store.read_json("state/index/owner-index.json")
        owners = owner_index.get("owners", {}) if isinstance(owner_index, Mapping) else {}
        active = active_scene_session(self.store)
        action = payload["action"]

        permitted_people = set(str(x) for x in base.get("permitted_person_ids", []) if isinstance(x, str))
        permitted_objects = set(str(x) for x in base.get("permitted_object_refs", []) if isinstance(x, str))
        # Current delivered event casts are already player-visible.  Include
        # only their exact advertised participants, never arbitrary residents at
        # the same broad location.
        event_rows, _ = triggered_interaction_handles(self.store, limit=32)
        current_time = base.get("campaign", {}).get("world_time") if isinstance(base.get("campaign"), Mapping) else None
        visible_event_refs: set[str] = set()
        for row in event_rows:
            if not isinstance(row, Mapping):
                continue
            event_ref = row.get("interaction_ref")
            if isinstance(event_ref, str):
                visible_event_refs.add(event_ref)
            if row.get("triggered_at") == current_time:
                permitted_people.update(str(x) for x in row.get("present_person_refs", []) if isinstance(x, str))
                for key in ("operation_ref", "campaign_command_cycle_ref"):
                    ref = row.get(key)
                    if isinstance(ref, str):
                        permitted_objects.add(ref)
        permitted_objects.update(visible_event_refs)

        if action == "open":
            participants = set(str(x) for x in payload["participant_refs"] if isinstance(x, str))
            participants.add(command.actor_id)
            if any(ref not in permitted_people for ref in participants):
                raise OperationError(404, "scene_participant_not_player_visible")
            for ref in participants:
                path = owners.get(ref) if isinstance(owners, Mapping) else None
                if not isinstance(path, str):
                    raise OperationError(404, "scene_participant_not_player_visible")
                person = self.store.read_json(path)
                location = person.get("current_location") or person.get("location_ref") or person.get("location")
                if location != player_location:
                    raise OperationError(409, "scene_participant_not_colocated")
            process_ref = payload.get("process_ref")
            if isinstance(process_ref, str) and process_ref not in permitted_objects:
                raise OperationError(404, "scene_process_not_player_visible")
            return

        if active is None or str(active.get("session_ref")) != str(payload.get("session_ref")):
            raise OperationError(409, "scene_session_not_active")
        if action == "record_speech":
            participants = set(str(x) for x in active.get("participant_refs", []) if isinstance(x, str))
            speaker_ref = str(payload.get("speaker_ref"))
            if speaker_ref not in participants:
                raise OperationError(409, "scene_speaker_not_present")
            speaker_path = owners.get(speaker_ref) if isinstance(owners, Mapping) else None
            if not isinstance(speaker_path, str):
                raise OperationError(409, "scene_speaker_not_present")
            speaker = self.store.read_json(speaker_path)
            speaker_location = speaker.get("current_location") or speaker.get("location_ref") or speaker.get("location") if isinstance(speaker, Mapping) else None
            if speaker_location != player_location:
                raise OperationError(409, "scene_speaker_not_colocated")
            open_questions = set(str(x) for x in active.get("open_question_refs", []) if isinstance(x, str))
            question_ref = payload.get("resolves_question_ref")
            if question_ref is not None and str(question_ref) not in open_questions:
                raise OperationError(409, "scene_question_not_open")
            permitted_basis = permitted_people | permitted_objects | participants | open_questions
            process_ref = active.get("process_ref")
            if isinstance(process_ref, str):
                permitted_basis.add(process_ref)
            for ref in payload.get("basis_refs", []):
                if str(ref) not in permitted_basis:
                    raise OperationError(404, "scene_speech_basis_not_player_visible")

    def _translate_surface_command(self, command: CommandEnvelope) -> CommandEnvelope:
        if command.command_type == "scene_consequence":
            raise OperationError(422, "raw_scene_consequence_not_player_authored")
        if command.command_type == "interaction_action":
            self._validate_interaction_authority(command)
            return translate_interaction_command(command)
        if command.command_type == "scene_session_action":
            self._validate_scene_session_authority(command)
            return translate_scene_action_command(command)
        return command

    def play_context(self):
        context = super().play_context()
        context.setdefault("limits", {})["high_salience_wake_boundary"] = True
        context["limits"]["operational_memory_is_non_authoritative"] = True
        context["limits"]["campaign_event_notices_nonblocking"] = True
        context["limits"]["bounded_hot_context_with_exact_rehydration"] = True

        player_id = str(context["campaign"]["player_id"])
        command_group_views = self._controlled_command_group_views(player_id)
        context["controlled_command_groups"] = command_group_views
        context["controlled_command_groups_count"] = len(command_group_views)
        handles, handle_refs, handle_count = self._interaction_refs()
        attempts, _ = recent_interaction_attempts(self.store, player_id)
        attempts = list(reversed(attempts))
        active_session = scene_session_projection(self.store)
        if isinstance(active_session, Mapping):
            player_location = context.get("player", {}).get("location")
            participants = [str(x) for x in active_session.get("participant_refs", []) if isinstance(x, str) and x]
            owner_index = self.store.read_json("state/index/owner-index.json")
            owners = owner_index.get("owners", {}) if isinstance(owner_index, Mapping) else {}
            coherent = bool(player_id in participants and player_location)
            for ref in participants:
                if not coherent or ref == player_id:
                    continue
                path = owners.get(ref) if isinstance(owners, Mapping) else None
                if not isinstance(path, str):
                    coherent = False; break
                try:
                    person = self.store.read_json(path)
                except FileNotFoundError:
                    coherent = False; break
                if not isinstance(person, Mapping):
                    coherent = False; break
                location = person.get("current_location") or person.get("location_ref") or person.get("location")
                if location != player_location:
                    coherent = False; break
            if not coherent or active_session.get("location_ref") != player_location:
                active_session = None
        recent_speech = recent_scene_history(self.store, limit=8)
        context["active_scene_session"] = active_session
        if isinstance(active_session, Mapping):
            context["permitted_person_ids"] = sorted(
                set(context.get("permitted_person_ids", []))
                | {str(x) for x in active_session.get("participant_refs", []) if isinstance(x, str)}
            )
        context["recent_scene_history"] = recent_speech
        compact_handles = []
        for row in handles:
            compact = {
                key: row.get(key)
                for key in ("interaction_ref", "kind", "triggered_at", "source_ref", "target_ref", "operation_ref", "campaign_command_cycle_ref", "present_person_refs")
                if row.get(key) is not None
            }
            summary = row.get("summary")
            if isinstance(summary, str):
                if len(summary) > 360:
                    compact["summary"] = summary[:357].rstrip() + "..."
                    compact["summary_truncated"] = True
                else:
                    compact["summary"] = summary
            compact_handles.append(compact)
        compact_attempts = _compact_interaction_attempts(attempts)
        player_processes = self._player_process_views(player_id)
        context["active_player_processes"] = player_processes
        durable_decisions = self._durable_player_decisions(player_id, player_processes)
        context["unresolved_decisions"] = durable_decisions
        if durable_decisions and not context.get("unresolved_decision"):
            context["unresolved_decision"] = durable_decisions[0]
            context["decision_required"] = True
            context["decision_reason"] = "durable_player_decision"
            context["attention_required"] = True
            context["attention_reason"] = "durable_player_decision"
        process_refs = {str(row["object_ref"]) for row in player_processes if row.get("object_ref")}
        context["permitted_object_refs"] = sorted(set(context.get("permitted_object_refs", [])) | process_refs)

        # Preserve a presentation-only anchor, then replace a stale authored
        # scene with a revision-matched projection made only from exact current
        # owners, triggered event-registry facts, and typed player attempts.
        scene_context = context.get("scene")
        if isinstance(scene_context, dict):
            continuity_anchor = None
            if scene_context.get("projection_status") == "stale_after_state_change":
                raw_scene = self.runtime.store.read_json("state/scene.json")
                narrative = raw_scene.get("narrative", {}) if isinstance(raw_scene, Mapping) else {}
                if not isinstance(narrative, Mapping):
                    narrative = {}
                summary = raw_scene.get("scene_summary") if isinstance(raw_scene, Mapping) else None
                if not isinstance(summary, str) or not summary.strip():
                    summary = narrative.get("last_scene_summary")
                if isinstance(summary, str) and summary.strip():
                    continuity_anchor = {
                        "presentation_only": True,
                        "prior_scene_id": raw_scene.get("scene_id"),
                        "prior_location": raw_scene.get("location_id") or raw_scene.get("location"),
                        "summary": summary.strip(),
                        "warning": (
                            "Previous-scene orientation only; it does not prove current presence, access, "
                            "pressure, opportunity, occupancy, or unresolved status."
                        ),
                    }
                projection = fresh_runtime_projection(context, compact_handles, compact_attempts)
                projection["continuity_anchor"] = continuity_anchor
                context["scene"] = projection
                scene_context = projection
                context.setdefault("narration_guidance", {})["stale_scene_policy"] = (
                    "stale authored scene claims are stripped; the runtime supplies a revision-matched "
                    "minimal projection from exact current owners, triggered event facts, and typed "
                    "player interaction attempts, while older prose remains presentation-only continuity"
                )
            else:
                scene_context.setdefault("continuity_anchor", None)
            scene_context["active_scene_session"] = copy.deepcopy(active_session)
            active_session_ref = active_session.get("session_ref") if isinstance(active_session, Mapping) else None
            scene_context["active_questions"] = [
                {key: row.get(key) for key in ("event_id", "at", "target_ref", "player_statement", "topic", "scopes", "scene_session_ref") if row.get(key) not in (None, "", [])}
                for row in compact_attempts
                if row.get("action") == "ask"
                and row.get("thread_status", "open") == "open"
                and active_session_ref is not None
                and row.get("scene_session_ref") == active_session_ref
            ][:8]

        # A campaign-command conference is an exact physical people-centered
        # event.  When its delivered handle is current at Wei's exact location,
        # surface those exact people as present instead of forcing the GM to infer
        # attendance from a report summary.
        current_time = context.get("campaign", {}).get("world_time")
        player_location_for_cast = context.get("player", {}).get("location")
        command_present_refs = _campaign_command_present_refs(
            handles,
            current_time=current_time,
            player_location=player_location_for_cast,
            runtime=self.runtime.store.read_json("state/runtime.json"),
            active_session=active_session,
        )
        if command_present_refs and isinstance(context.get("scene"), dict):
            owner_index = self.store.read_json("state/index/owner-index.json")
            owners = owner_index.get("owners", {}) if isinstance(owner_index, Mapping) else {}
            cast_rows = []
            for ref in sorted(command_present_refs):
                path = owners.get(ref) if isinstance(owners, Mapping) else None
                if not isinstance(path, str):
                    continue
                try:
                    person = self.store.read_json(path)
                except FileNotFoundError:
                    continue
                if not isinstance(person, Mapping):
                    continue
                person_location = person.get("current_location") or person.get("location_ref") or person.get("location")
                if person_location != player_location_for_cast:
                    continue
                cast_rows.append({
                    "person_id": ref,
                    "name": person.get("name") or ref,
                    "role": person.get("role") or (person.get("career_state", {}) or {}).get("office_or_command"),
                    "location": player_location_for_cast,
                    "scene_basis": ["campaign_command_event"],
                })
            scene = context["scene"]
            cast = scene.setdefault("scene_cast", {})
            cast["present_people"] = cast_rows
            cast["visible_people"] = copy.deepcopy(cast_rows)
            cast.setdefault("nearby_people", [])
            cast.setdefault("referenced_people", [])
            cast["generic_participation_rule"] = (
                "Campaign-command attendance is exact only for people carried by a current command event or a still-open formal council and revalidated at Tang Wei's exact location."
            )
            context["permitted_person_ids"] = sorted(set(context.get("permitted_person_ids", [])) | command_present_refs)

        # Keep ordinary turn handoff bounded. Paging and exact revalidation are
        # escape hatches, so projection limits never become world cardinality limits.
        known_all = list(context.get("known_information", []))
        # Superseded claims remain exact player knowledge and are available
        # through paging, but repeatedly injecting them beside the current
        # assessment wastes every-turn context and can make old intelligence
        # look equally actionable. Keep the hot handoff focused on current
        # assessments while preserving the complete epistemic history on read.
        known_current = [
            row for row in known_all
            if not isinstance(row, Mapping) or row.get("assessment_status") != "historical_superseded"
        ]
        known_recent = list(reversed(known_current[-HOT_INFORMATION_LIMIT:]))
        context["known_information"] = known_recent
        context["known_information_count"] = len(known_all)
        context["known_information_current_count"] = len(known_current)
        context["known_information_historical_count"] = len(known_all) - len(known_current)
        context["known_information_truncated"] = len(known_all) > len(known_recent)

        formations_all = list(context.get("controlled_formations", []))
        player_location = context.get("player", {}).get("location")
        formations_all.sort(key=lambda item: self._formation_sort_key(item, player_location))
        formations_hot = formations_all[:HOT_FORMATION_LIMIT]
        context["controlled_formations"] = formations_hot
        context["controlled_formations_count"] = len(formations_all)
        context["controlled_formations_truncated"] = len(formations_all) > len(formations_hot)

        all_formation_refs = {str(item.get("formation_ref")) for item in formations_all if item.get("formation_ref")}
        hot_formation_refs = {str(item.get("formation_ref")) for item in formations_hot if item.get("formation_ref")}
        controlled_operation_views = self._controlled_operation_views(all_formation_refs)
        controlled_operation_refs = {str(item["operation_ref"]) for item in controlled_operation_views}
        campaign_cycle_refs: set[str] = set()
        campaign_command_people: set[str] = set()
        campaign_command_objects: set[str] = set()
        for item in controlled_operation_views:
            command = item.get("campaign_command") if isinstance(item.get("campaign_command"), Mapping) else None
            if not isinstance(command, Mapping):
                continue
            cycle_ref = command.get("cycle_ref")
            if isinstance(cycle_ref, str) and cycle_ref:
                campaign_cycle_refs.add(cycle_ref)
            for key in ("supreme_commander_ref", "superior_command_ref", "coordination_authority_ref"):
                ref = command.get(key)
                if not isinstance(ref, str) or not ref:
                    continue
                if ref.startswith("char_"):
                    campaign_command_people.add(ref)
                else:
                    campaign_command_objects.add(ref)
            for ref in command.get("participant_commander_refs", []) if isinstance(command.get("participant_commander_refs"), list) else []:
                if isinstance(ref, str) and ref.startswith("char_"):
                    campaign_command_people.add(ref)
        command_group_refs = {str(item.get("command_group_ref")) for item in command_group_views if item.get("command_group_ref")}
        command_group_people: set[str] = set()
        for item in command_group_views:
            if item.get("commander_ref"):
                command_group_people.add(str(item["commander_ref"]))
            for ref in item.get("successor_refs", []) if isinstance(item.get("successor_refs"), list) else []:
                if ref: command_group_people.add(str(ref))
            for ref in item.get("role_assignments", {}) if isinstance(item.get("role_assignments"), Mapping) else {}:
                if isinstance(ref, str) and ref.startswith("char_"):
                    command_group_people.add(ref)
        all_commanders = {str(item.get("commander_ref")) for item in formations_all if item.get("commander_ref")}
        hot_commanders = {str(item.get("commander_ref")) for item in formations_hot if item.get("commander_ref")}
        permitted_objects = set(context.get("permitted_object_refs", [])) - all_formation_refs
        permitted_objects.update(hot_formation_refs)
        permitted_objects.update(controlled_operation_refs)
        permitted_objects.update(campaign_cycle_refs)
        permitted_objects.update(campaign_command_objects)
        permitted_objects.update(command_group_refs)
        permitted_objects.update(handle_refs)
        context["permitted_object_refs"] = sorted(permitted_objects)
        permitted_people = set(context.get("permitted_person_ids", [])) - all_commanders
        permitted_people.update(hot_commanders)
        permitted_people.update(command_group_people)
        permitted_people.update(campaign_command_people)
        permitted_people.add(player_id)
        context["permitted_person_ids"] = sorted(permitted_people)

        context["interaction_handles"] = compact_handles
        context["interaction_handles_count"] = handle_count
        context["interaction_handles_truncated"] = handle_count > len(handles)
        context["recent_interaction_attempts"] = compact_attempts
        context["controlled_operations"] = controlled_operation_views

        read_hints = context.setdefault("read_hints", {})
        if context["controlled_formations_truncated"]:
            read_hints["controlled_formations_page"] = {
                "tool": "list_controlled_formations",
                "next_cursor": str(len(formations_hot)),
            }
        if context["known_information_truncated"]:
            read_hints["known_information_page"] = {
                "tool": "list_known_information",
                # The hot list is a semantic current-assessment projection, not
                # a positional prefix of the complete paged knowledge ledger.
                "next_cursor": "0",
                "scope": "complete knowledge including superseded historical assessments",
            }
        if context["interaction_handles_truncated"]:
            read_hints["interaction_handles_page"] = {
                "tool": "list_interaction_handles",
                "next_cursor": str(len(handles)),
            }
        if any(isinstance(row, Mapping) and row.get("summary_truncated") for row in compact_handles):
            read_hints["interaction_handle_detail"] = {
                "tool": "inspect_game_object",
                "rule": "Inspect the exact interaction_ref only when the complete message/report text is material to the current turn.",
            }
        if recent_speech:
            head = inspect_scene_history(self.store, "scene_history_head")
            latest_period = head.get("latest_period_ref") if isinstance(head, Mapping) else None
            read_hints["scene_history"] = {
                "tool": "inspect_game_object",
                "object_ref": "scene_history_head",
                "latest_period_ref": latest_period,
                "rule": "Attributed speech is durable observed history but never objective world truth or mechanical authority; follow previous_period_ref only when older conversation continuity is material.",
            }

        commands = context.setdefault("commands", {})
        command_types = dict(commands.get("command_types", {}))
        command_types.pop("scene_consequence", None)
        command_types["interaction_action"] = {
            "accepted_payload_keys": ["action", "formation_refs", "player_statement", "posture", "process_ref", "target_ref"],
            "input_guidance": {
                "target_ref": {
                    "rule": (
                        "use an exact permitted person/object or returned interaction_ref; seek_contact may "
                        "instead target the player's exact current location to record an attempt to find a lawful receiving channel"
                    )
                },
                "process_ref": {"rule": "optional exact permitted process/interaction ref"},
                "action": {"allowed_values": sorted(INTERACTION_ACTIONS)},
                "formation_refs": {"rule": "optional unique exact controlled formation refs"},
                "player_statement": {"type": "string", "maximum_length": 2000, "rule": "player-authored speech only"},
                "posture": {"type": "string", "maximum_length": 500, "rule": "player-authored posture only"},
                "outcome_rule": "NPC/world response fields are forbidden; an interaction command commits only the player's attempt unless another runtime authority establishes a response.",
                "time_rule": "interaction_action never advances chronology; elapsed waiting must use advance_time.",
            },
            "contested_preview_policy": "attempt_only_no_external_outcome",
        }
        command_types["scene_session_action"] = {
            "accepted_payload_keys": ["action", "agenda", "basis_refs", "close_reason", "kind", "participant_refs", "process_ref", "purpose", "resolves_question_ref", "session_ref", "speaker_ref", "speech_kind", "statement"],
            "input_guidance": {
                "action": {"allowed_values": sorted(SCENE_SESSION_ACTIONS)},
                "open_rule": "Open only a people-centered scene among exact co-located participants. The runtime fixes the session location to Tang Wei's exact current location.",
                "record_speech_rule": "Persist only important attributed non-mechanical speech from an active participant. Binding orders, promises, offices, money, movement, secrets and other hard consequences require their real semantic command.",
                "close_rule": "Close the active scene when it actually concludes, Wei leaves, combat/hard interruption supersedes it, or the player explicitly skips to its conclusion.",
                "truth_rule": "Persisted speech proves only that the speaker was attributed the statement in this scene; it is not objective truth.",
            },
            "contested_preview_policy": "presentation_history_only_no_mechanical_outcome",
        }
        commands["command_types"] = command_types
        commands["supported_command_types"] = sorted(command_types)
        commands["hidden_internal_command_types"] = ["scene_consequence"]

        runtime = self.runtime.store.read_json("state/runtime.json")
        wake = runtime.get("pending_wake") if isinstance(runtime, Mapping) else None
        if isinstance(wake, Mapping):
            wake_campaign_event_ref = wake.get("campaign_event_ref")
            if isinstance(wake_campaign_event_ref, str) and wake_campaign_event_ref:
                context.setdefault("permitted_object_refs", [])
                context["permitted_object_refs"] = sorted(set(context["permitted_object_refs"]) | {wake_campaign_event_ref})
            wake_operation_ref = wake.get("operation_ref")
            if isinstance(wake_operation_ref, str) and wake_operation_ref:
                context.setdefault("permitted_object_refs", [])
                context["permitted_object_refs"] = sorted(set(context["permitted_object_refs"]) | {wake_operation_ref})
            context["pending_wake"] = {key: wake[key] for key in _WAKE_VISIBLE_FIELDS if key in wake}
            if wake.get("kind") == "campaign_event":
                raise OperationError(500, "invalid_persisted_campaign_event_wake")
            if wake.get("kind") == "battlefield_report":
                response_types = sorted(set(_WAKE_RESPONSE_COMMANDS) | {'interaction_action'})
                if "scene_consequence" in response_types:
                    response_types.remove("scene_consequence")
                context["pending_wake"]["response_command_types"] = response_types
                context["pending_wake"]["continue_command"] = "advance_time"
                context["pending_wake"]["requires_player_decision"] = True
                context["decision_required"] = True
                context["decision_reason"] = "battlefield_report_boundary"
                commands["availability_scope"] = "battlefield_report_response"
                commands["temporarily_available_command_types"] = response_types
            else:
                response_types = sorted(set(_WAKE_RESPONSE_COMMANDS) | {'interaction_action'})
                if "scene_consequence" in response_types:
                    response_types.remove("scene_consequence")
                if "interaction_action" not in response_types:
                    response_types.append("interaction_action")
                    response_types.sort()
                context["pending_wake"]["response_command_types"] = response_types
                context["pending_wake"]["continue_contact_command"] = "advance_time"
                context["pending_wake"]["requires_player_decision"] = True
                context["decision_required"] = True
                context["decision_reason"] = "high_salience_autonomous_contact"
                commands["availability_scope"] = "pending_wake_response"
                commands["temporarily_available_command_types"] = response_types
        return context

    def get_command_family(self, family: str) -> dict[str, Any]:
        if not isinstance(family, str) or not family:
            raise OperationError(422, "command_family_invalid")
        context = self.play_context()
        commands = context.get("commands", {})
        if not isinstance(commands, Mapping):
            raise OperationError(500, "command_surface_unavailable")
        try:
            return compact_command_family(commands, family)
        except KeyError as exc:
            raise OperationError(404, "command_family_not_available") from exc

    def get_command_contract(self, command_type: str) -> dict[str, Any]:
        if command_type == "interaction_action":
            record: dict[str, Any] = {
                "accepted_payload_keys": ["action", "formation_refs", "player_statement", "posture", "process_ref", "target_ref"],
                "input_guidance": {
                    "target_ref": {"rule": "use an exact permitted person/object or returned interaction_ref; seek_contact may instead target the player's exact current location"},
                    "process_ref": {"rule": "optional exact permitted process/interaction ref"},
                    "action": {"allowed_values": sorted(INTERACTION_ACTIONS)},
                    "formation_refs": {"rule": "optional unique exact controlled formation refs"},
                    "player_statement": {"type": "string", "maximum_length": 2000, "rule": "player-authored speech only"},
                    "posture": {"type": "string", "maximum_length": 500, "rule": "player-authored posture only"},
                    "outcome_rule": "NPC/world response fields are forbidden; the command commits only the player's attempt.",
                    "time_rule": "interaction_action never advances chronology; elapsed waiting uses advance_time.",
                },
                "contested_preview_policy": "attempt_only_no_external_outcome",
            }
        elif command_type == "scene_session_action":
            record = {
                "accepted_payload_keys": ["action", "agenda", "basis_refs", "close_reason", "kind", "participant_refs", "process_ref", "purpose", "resolves_question_ref", "session_ref", "speaker_ref", "speech_kind", "statement"],
                "input_guidance": {
                    "action": {"allowed_values": sorted(SCENE_SESSION_ACTIONS)},
                    "authority_rule": "This command owns scene continuity and attributed speech only. It cannot establish hard world consequences.",
                    "speaker_rule": "record_speech requires an exact participant in the active session and may resolve only an open question in that session.",
                    "persistence_rule": "Important attributed speech is written to bounded recent history plus a lossless period shard; ordinary connective dialogue need not be persisted.",
                },
                "contested_preview_policy": "presentation_history_only_no_mechanical_outcome",
            }
        elif command_type == "standing_training_settle":
            record = {
                "accepted_payload_keys": ["target_ref"],
                "input_guidance": {
                    "target_ref": {"rule": "use Tang Wei's player_id or one exact controlled formation_ref"},
                    "hours_rule": "caller-supplied hours are forbidden",
                    "focus_rule": "caller-supplied focuses are forbidden; saved role/billet/training_ref resolves a finite registered deterministic program; current stats and narration do not choose gains",
                    "time_rule": "settlement advances no campaign time",
                },
                "contested_preview_policy": "deterministic_server_owned_credit_only",
            }
        elif command_type in COMMAND_TYPES and command_type != "scene_consequence":
            record = {
                "accepted_payload_keys": sorted(COMMAND_PAYLOAD_KEYS.get(command_type, ())),
                "input_guidance": dict(COMMAND_INPUT_GUIDANCE.get(command_type, {})),
                "contested_preview_policy": "outcome_hidden_until_execute" if command_type in {"battle_resolve", "personal_combat", "siege_action", "medical_treatment"} else "deterministic_preview",
            }
        else:
            raise OperationError(404, "command_contract_not_available")

        runtime = self.runtime.store.read_json("state/runtime.json")
        wake = runtime.get("pending_wake") if isinstance(runtime, Mapping) else None
        available = True
        scope = "normal"
        if isinstance(wake, Mapping):
            if wake.get("kind") == "campaign_event":
                raise OperationError(500, "invalid_persisted_campaign_event_wake")
            response_types = set(_WAKE_RESPONSE_COMMANDS) | {"interaction_action"}
            response_types.discard("scene_consequence")
            available = command_type in response_types
            scope = "pending_wake_response"
        return {
            "command_type": command_type,
            **record,
            "availability": {"available": available, "scope": scope},
            "input_guidance_policy": INPUT_GUIDANCE_POLICY,
        }

    def list_controlled_formations(self, cursor: Optional[str] = None, limit: int = 20) -> dict[str, Any]:
        offset = self._cursor_offset(cursor, "formation_page_invalid")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 64:
            raise OperationError(422, "formation_page_invalid")
        player_id = self._player_actor()
        values = self._all_controlled_formations(player_id)
        player_location = self.store.read_json("state/player.json").get("location")
        values.sort(key=lambda item: self._formation_sort_key(item, player_location))
        page = values[offset:offset + limit]
        next_offset = offset + len(page)
        return {
            "cursor": cursor,
            "count": len(values),
            "returned": len(page),
            "truncated": next_offset < len(values),
            "next_cursor": str(next_offset) if next_offset < len(values) else None,
            "formations": page,
        }

    def list_known_information(self, cursor: Optional[str] = None, limit: int = 20) -> dict[str, Any]:
        offset = self._cursor_offset(cursor, "information_page_invalid")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 64:
            raise OperationError(422, "information_page_invalid")
        values = list(reversed(self._all_known_information(self._player_actor())))
        page = values[offset:offset + limit]
        next_offset = offset + len(page)
        return {
            "cursor": cursor,
            "count": len(values),
            "returned": len(page),
            "truncated": next_offset < len(values),
            "next_cursor": str(next_offset) if next_offset < len(values) else None,
            "known_information": page,
        }

    def list_interaction_handles(self, cursor: Optional[str] = None, limit: int = 20) -> dict[str, Any]:
        try:
            return triggered_interaction_page(self.store, cursor=cursor, limit=limit)
        except ValueError as exc:
            raise OperationError(422, "interaction_page_invalid") from exc

    def inspect_game_object(self, object_ref: str) -> dict[str, Any]:
        history = inspect_scene_history(self.store, object_ref)
        if history is not None:
            return {"object_ref": object_ref, "visibility": "player_observed_attributed_scene_history", "object": history}
        interaction = triggered_interaction_record(self.store, object_ref)
        if interaction is not None:
            return {"object_ref": object_ref, "visibility": "player_visible_triggered_event", "object": interaction}
        context = self.play_context()
        operation_view = next((row for row in context.get("controlled_operations", []) if row.get("operation_ref") == object_ref), None)
        if isinstance(operation_view, Mapping):
            return {"object_ref": object_ref, "visibility": "controlled_operation", "object": dict(operation_view)}
        if object_ref in set(context.get("permitted_object_refs", [])):
            return super().inspect_game_object(object_ref)

        # Exact known claims may fall out of the hot window without becoming
        # forgotten. Revalidate the exact saved knower before returning it.
        info_index = self.store.read_json("state/information/index.json")
        claim_path = info_index.get("claims", {}).get(object_ref)
        if isinstance(claim_path, str):
            claim = self.store.read_json(claim_path)
            if context["campaign"]["player_id"] in claim.get("knowers", []):
                return {
                    "object_ref": object_ref,
                    "visibility": "player_known_information",
                    "object": {
                        "information_ref": claim.get("information_ref"),
                        "subject_ref": claim.get("subject_ref"),
                        "claim": claim.get("claim"),
                        "epistemic_kind": claim.get("epistemic_kind"),
                        "confidence_milli": claim.get("confidence_milli"),
                        "source_ref": claim.get("source_ref"),
                        "evidence_refs": claim.get("evidence_refs", []),
                        "classification": claim.get("classification"),
                        "provenance": claim.get("provenance"),
                        "world_truth_authority": False,
                    },
                }

        # Controlled formations outside the hot window remain inspectable by
        # exact ref after current authority is revalidated.
        owners = self.store.read_json("state/index/owner-index.json").get("owners", {})
        path = owners.get(object_ref)
        if isinstance(path, str) and object_ref.startswith("formation_"):
            formation = self.store.read_json(path)
            player_id = context["campaign"]["player_id"]
            if formation.get("command_authority") == player_id or formation.get("administrative_owner") in {player_id, "house_tang"}:
                formation = self._formation_with_projected_fatigue(formation)
                fields = ("owner_id", "formation_ref", "name", "role", "personnel", "location_ref", "status", "mobilized", "commander_ref", "command_authority", "administrative_owner", "doctrine_ref", "training_ref", "supply", "logistics", "morale", "cohesion", "readiness", "training_progress", "fatigue", "experience")
                return {"object_ref": object_ref, "visibility": "controlled_exact_rehydration", "object": {key: formation.get(key) for key in fields if key in formation}}
        raise OperationError(404, "object_not_player_visible")

    def preview_command(self, command):
        if command.actor_id != self._player_actor() or command.mode != "gameplay":
            raise OperationError(403, "player_surface_forbids_internal_mode")
        translated = self._translate_surface_command(command)
        try:
            preview = self.runtime.preview_for_execution(translated)
            if command.command_type in {"interaction_action", "scene_session_action"}:
                preview = dict(preview)
                preview["surface_command_type"] = command.command_type
                if command.command_type == "interaction_action":
                    preview["world_response_status"] = "not_established_by_attempt"
                else:
                    preview["mechanical_consequence_authority"] = False
            return preview
        except HighSalienceWakeRequired as exc:
            raise OperationError(409, "high_salience_wake_required") from exc
        except StaleRevisionError as exc:
            raise OperationError(409, "stale_revision") from exc
        except PermissionError as exc:
            raise OperationError(403, "command_not_authorized") from exc
        except (TypeError, ValueError, FileNotFoundError) as exc:
            raise OperationError(422, "command_rejected") from exc

    def lookup_command_receipt(self, command: CommandEnvelope) -> Optional[dict[str, Any]]:
        if command.command_type == "scene_consequence":
            return super().lookup_command_receipt(command)
        translated = self._translate_surface_command(command)
        receipt = super().lookup_command_receipt(translated)
        if receipt is not None and command.command_type in {"interaction_action", "scene_session_action"}:
            receipt = dict(receipt)
            receipt["surface_command_type"] = command.command_type
        return receipt

    def execute_command(self, command):
        if command.actor_id != self._player_actor() or command.mode != "gameplay":
            raise OperationError(403, "player_surface_forbids_internal_mode")
        if command.command_type == "scene_consequence":
            existing = super().lookup_command_receipt(command)
            if existing is not None:
                return existing
            raise OperationError(422, "raw_scene_consequence_not_player_authored")
        translated = self._translate_surface_command(command)
        try:
            receipt = _receipt_record(self.runtime.execute(translated))
            if command.command_type in {"interaction_action", "scene_session_action"}:
                receipt["surface_command_type"] = command.command_type
            return receipt
        except HighSalienceWakeRequired as exc:
            raise OperationError(409, "high_salience_wake_required") from exc
        except StaleRevisionError as exc:
            raise OperationError(409, "stale_revision") from exc
        except IdempotencyConflictError as exc:
            raise OperationError(409, "idempotency_conflict") from exc
        except LockUnavailableError as exc:
            raise OperationError(503, "campaign_writer_busy") from exc
        except RemoteDurabilityError as exc:
            raise OperationError(503, "transaction_remote_durability_failed") from exc
        except (DirtyRepositoryError, RecoveryError) as exc:
            raise OperationError(503, "campaign_unavailable") from exc
        except PermissionError as exc:
            raise OperationError(403, "command_not_authorized") from exc
        except TransactionError as exc:
            raise OperationError(409, transaction_failure_code(exc)) from exc
        except (TypeError, ValueError, FileNotFoundError) as exc:
            raise OperationError(422, "command_rejected") from exc
        except Exception as exc:
            raise OperationError(503, "campaign_runtime_unavailable") from exc


__all__ = ["StableCampaignOperations", "transaction_failure_code"]
