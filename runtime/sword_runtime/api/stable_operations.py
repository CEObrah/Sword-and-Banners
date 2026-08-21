"""Production operations with stable low-information failure classification."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional

from sword_runtime.api.command_discovery import compact_command_family
from sword_runtime.api.interaction_surface import (
    HOT_FORMATION_LIMIT,
    HOT_INFORMATION_LIMIT,
    INTERACTION_ACTIONS,
    fresh_runtime_projection,
    recent_interaction_attempts,
    translate_interaction_command,
    triggered_interaction_handles,
    triggered_interaction_page,
    triggered_interaction_record,
    validate_interaction_payload,
)
from sword_runtime.api.operations import CampaignOperations, OperationError, _receipt_record
from sword_runtime.api.input_guidance import COMMAND_INPUT_GUIDANCE, INPUT_GUIDANCE_POLICY
from sword_runtime.causal_living_world import _WAKE_RESPONSE_COMMANDS
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

_WAKE_VISIBLE_FIELDS = (
    "wake_ref", "kind", "at", "theater_ref", "formation_ref", "location_ref",
    "opponent_state", "operation_ref", "battlefield_ref",
    "sector_ref", "report_id", "level", "reason",
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

        Command groups are zero-body authority owners. Their commander/deputy layer
        must not disappear merely because those people are not also formation
        commanders in the compact formation window.
        """
        try:
            index = self.store.read_json("state/cmd/command-groups/index.json")
        except (FileNotFoundError, ValueError):
            return []
        refs = index.get("refs", []) if isinstance(index, Mapping) else []
        primary = index.get("primary_person_group", {}) if isinstance(index, Mapping) else {}
        primary_ref = primary.get(player_id) if isinstance(primary, Mapping) else None
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
            for role_key in ("commander_ref", "deputy_ref"):
                person_ref = group.get(role_key)
                if isinstance(person_ref, str) and person_ref:
                    expected_people.append((person_ref, role_key.removesuffix("_ref")))
            for person_ref in group.get("successor_refs", []) if isinstance(group.get("successor_refs"), list) else []:
                if isinstance(person_ref, str) and person_ref and all(person_ref != existing[0] for existing in expected_people):
                    expected_people.append((person_ref, "successor"))
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
                if command_role in {"deputy", "successor"} and assigned_group != ref:
                    integrity.append({
                        "person_ref": person_ref,
                        "command_role": command_role,
                        "issue": "command_group_assignment_mismatch",
                        "expected_command_group_ref": ref,
                        "person_command_group_ref": assigned_group,
                    })
            candidates.append({
                "command_group_ref": ref,
                "display_name": group.get("display_name"),
                "context": group.get("context"),
                "location_ref": group.get("location"),
                "commander_ref": group.get("commander_ref"),
                "deputy_ref": group.get("deputy_ref"),
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
        """Return only operational facts the player's command position can know.

        The active operation index is already the bounded routing owner. Enemy
        assignments and undelivered pressure reports stay hidden; the view
        exposes battlefield geometry, the player's own formation assignments,
        and reports whose messenger delivery has actually completed.
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
                own_assignments = {
                    formation_ref: dict(assignments[formation_ref])
                    for formation_ref in sorted(own)
                    if isinstance(assignments.get(formation_ref), Mapping)
                }
                player_sides = {str(row.get("side_ref")) for row in own_assignments.values() if row.get("side_ref")}
                delivered_reports = [
                    {
                        key: report.get(key)
                        for key in ("report_id", "sector_ref", "target_side_ref", "level", "pressure_milli", "created_at", "delivered_at", "summary")
                        if key in report
                    }
                    for report in battlefield.get("reports", [])
                    if isinstance(report, Mapping)
                    and report.get("status") == "delivered"
                    and report.get("target_side_ref") in player_sides
                ]
                battlefields.append({
                    "battlefield_ref": battlefield_ref,
                    "name": battlefield.get("name"),
                    "status": battlefield.get("status"),
                    "layout_ref": battlefield.get("layout_ref"),
                    "sector_refs": sorted(str(ref) for ref in (battlefield.get("sectors") or {}) if isinstance(ref, str)),
                    "controlled_assignments": own_assignments,
                    "delivered_reports": delivered_reports,
                    "opened_at": battlefield.get("opened_at"),
                    "updated_at": battlefield.get("updated_at"),
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
                            "order_ref", "issued_at", "issuer_ref", "arc_ref", "target_ref",
                            "objective", "status", "applies_to_formation_refs",
                            "excluded_non_state_formation_refs", "agency_rule",
                        )
                        if key in row
                    }
            views.append({
                "operation_ref": operation_ref,
                "status": operation.get("status"),
                "objective": operation.get("objective"),
                "location_ref": operation.get("location_ref"),
                "controlled_formation_refs": sorted(own),
                "order_status": operation.get("order_status"),
                "current_operational_order": current_order,
                "battlefields": battlefields,
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

    def _translate_surface_command(self, command: CommandEnvelope) -> CommandEnvelope:
        if command.command_type == "scene_consequence":
            raise OperationError(422, "raw_scene_consequence_not_player_authored")
        if command.command_type != "interaction_action":
            return command
        self._validate_interaction_authority(command)
        return translate_interaction_command(command)

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
        compact_handles = [
            {
                key: row.get(key)
                for key in ("interaction_ref", "kind", "triggered_at", "summary", "source_ref", "target_ref")
                if row.get(key) is not None
            }
            for row in handles
        ]
        compact_attempts = [
            {
                key: row.get(key)
                for key in ("event_id", "at", "request_id", "action", "target_ref", "process_ref", "formation_refs")
                if row.get(key) not in (None, [], "")
            }
            for row in attempts
        ]
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

        # Keep ordinary turn handoff bounded. Paging and exact revalidation are
        # escape hatches, so projection limits never become world cardinality limits.
        known_all = list(context.get("known_information", []))
        known_recent = list(reversed(known_all[-HOT_INFORMATION_LIMIT:]))
        context["known_information"] = known_recent
        context["known_information_count"] = len(known_all)
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
        command_group_refs = {str(item.get("command_group_ref")) for item in command_group_views if item.get("command_group_ref")}
        command_group_people: set[str] = set()
        for item in command_group_views:
            for key in ("commander_ref", "deputy_ref"):
                if item.get(key): command_group_people.add(str(item[key]))
            for ref in item.get("successor_refs", []) if isinstance(item.get("successor_refs"), list) else []:
                if ref: command_group_people.add(str(ref))
        all_commanders = {str(item.get("commander_ref")) for item in formations_all if item.get("commander_ref")}
        hot_commanders = {str(item.get("commander_ref")) for item in formations_hot if item.get("commander_ref")}
        permitted_objects = set(context.get("permitted_object_refs", [])) - all_formation_refs
        permitted_objects.update(hot_formation_refs)
        permitted_objects.update(controlled_operation_refs)
        permitted_objects.update(command_group_refs)
        permitted_objects.update(handle_refs)
        context["permitted_object_refs"] = sorted(permitted_objects)
        permitted_people = set(context.get("permitted_person_ids", [])) - all_commanders
        permitted_people.update(hot_commanders)
        permitted_people.update(command_group_people)
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
                "next_cursor": str(len(known_recent)),
            }
        if context["interaction_handles_truncated"]:
            read_hints["interaction_handles_page"] = {
                "tool": "list_interaction_handles",
                "next_cursor": str(len(handles)),
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
            if command.command_type == "interaction_action":
                preview = dict(preview)
                preview["surface_command_type"] = "interaction_action"
                preview["world_response_status"] = "not_established_by_attempt"
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
        if receipt is not None and command.command_type == "interaction_action":
            receipt = dict(receipt)
            receipt["surface_command_type"] = "interaction_action"
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
            if command.command_type == "interaction_action":
                receipt["surface_command_type"] = "interaction_action"
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
