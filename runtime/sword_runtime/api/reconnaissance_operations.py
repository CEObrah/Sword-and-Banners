"""Player-safe military reconnaissance command surface and response-route guard."""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from sword_runtime.api.input_guidance import INPUT_GUIDANCE_POLICY
from sword_runtime.api.interaction_surface import (
    _expects_response,
    person_owner_path,
    validate_interaction_payload,
)
from sword_runtime.api.sovereign_authority_operations import SovereignAuthorityAwareOperations
from sword_runtime.api.stable_operations import OperationError
from sword_runtime.commands import CommandEnvelope
from sword_runtime.geography import location_chain
from sword_runtime.interaction_routing_health import _route_available
from sword_runtime.reconnaissance import (
    RECON_INDEX_PATH,
    RECON_SCHEMA,
    RECON_SURFACE_COMMAND,
    reconnaissance_ref_from_digest,
    reconnaissance_transport,
)

_RECON_PAYLOAD_KEYS = frozenset({"formation_ref", "operation_ref", "region_ref", "observation_hours"})
_RECON_GUIDANCE = {
    "formation_ref": {"rule": "use one exact controlled, mobilized formation already inside the assigned reconnaissance region"},
    "operation_ref": {"rule": "use one exact current controlled military operation whose player-visible campaign context establishes the hostile target state"},
    "region_ref": {"rule": "use an exact player-known registered region/location containing the scout's current exact location"},
    "observation_hours": {"type": "integer", "minimum": 1, "maximum": 24, "default": 6},
    "outcome_rule": "the caller chooses only scout, parent operation, region, and observation time; contact, enemy strength, routes observed, confidence, and report content are server-owned causal results",
    "movement_rule": "this command does not move the scout; move the formation first through the formation mechanic",
    "battle_rule": "reconnaissance never starts a battle, pursuit, occupation, or attack by itself",
    "delivery_rule": "the scout commander receives the observation first; a causal military courier/report route delivers it to Tang Wei through campaign time",
}


def _read_optional(store: Any, path: str) -> Any:
    try:
        return store.read_json(path)
    except (FileNotFoundError, KeyError, TypeError, ValueError):
        return None


class ReconnaissanceAwareOperations(SovereignAuthorityAwareOperations):
    """Add a typed scouting surface and reject response promises with no route."""

    def _active_reconnaissance_views(self, player_id: str) -> list[dict[str, Any]]:
        index = _read_optional(self.store, RECON_INDEX_PATH)
        if not isinstance(index, Mapping):
            return []
        route_map = index.get("reconnaissance", {}) if isinstance(index.get("reconnaissance"), Mapping) else {}
        refs = index.get("active_by_actor", {}).get(player_id, []) if isinstance(index.get("active_by_actor"), Mapping) else []
        views: list[dict[str, Any]] = []
        for ref in refs if isinstance(refs, list) else []:
            if not isinstance(ref, str):
                continue
            path = route_map.get(ref) if isinstance(route_map, Mapping) else None
            if not isinstance(path, str):
                continue
            row = _read_optional(self.store, path)
            if not isinstance(row, Mapping) or row.get("schema") != RECON_SCHEMA or row.get("issuer_ref") != player_id:
                continue
            views.append({
                "process_ref": ref,
                "kind": "military_reconnaissance",
                "status": row.get("status"),
                "phase": row.get("phase"),
                "formation_ref": row.get("formation_ref"),
                "operation_ref": row.get("operation_ref"),
                "region_ref": row.get("region_ref"),
                "started_at": row.get("started_at"),
                "observation_due_at": row.get("observation_due_at"),
                "report_dispatched_at": row.get("report_dispatched_at"),
                "report_target_location_ref": row.get("report_target_location_ref"),
            })
        return views

    def play_context(self) -> dict[str, Any]:
        context = super().play_context()
        out = copy.deepcopy(context)
        commands = out.get("commands")
        if isinstance(commands, dict):
            command_types = commands.get("command_types")
            if isinstance(command_types, list) and RECON_SURFACE_COMMAND not in command_types:
                command_types.append(RECON_SURFACE_COMMAND)
                command_types.sort()
        player_id = str(out.get("campaign", {}).get("player_id") or "")
        if player_id:
            active = self._active_reconnaissance_views(player_id)
            if active:
                processes = out.setdefault("active_player_processes", [])
                if isinstance(processes, list):
                    known = {str(row.get("process_ref")) for row in processes if isinstance(row, Mapping)}
                    processes.extend(row for row in active if str(row.get("process_ref")) not in known)
                permitted = out.setdefault("permitted_object_refs", [])
                if isinstance(permitted, list):
                    existing = set(str(x) for x in permitted if isinstance(x, str))
                    for row in active:
                        ref = str(row.get("process_ref") or "")
                        if ref and ref not in existing:
                            permitted.append(ref)
                            existing.add(ref)
                    permitted.sort()
        return out

    def get_command_contract(self, command_type: str) -> dict[str, Any]:
        if command_type != RECON_SURFACE_COMMAND:
            return super().get_command_contract(command_type)
        return {
            "command_type": RECON_SURFACE_COMMAND,
            "accepted_payload_keys": sorted(_RECON_PAYLOAD_KEYS),
            "input_guidance": copy.deepcopy(_RECON_GUIDANCE),
            "contested_preview_policy": "deterministic_preview_hidden_observation",
            "availability": {"available": True, "scope": "normal"},
            "input_guidance_policy": INPUT_GUIDANCE_POLICY,
        }

    def _validate_interaction_authority(self, command: CommandEnvelope) -> None:
        super()._validate_interaction_authority(command)
        payload = validate_interaction_payload(command.payload)
        if not _expects_response(str(payload["action"]), payload.get("expects_response")):
            return
        target_ref = str(payload["target_ref"])
        # Exact people may answer naturally when local, or through the existing
        # person/contact/message routes validated by the parent surface.  The
        # structural defect was accepting response-bearing *object/process*
        # attempts when no causal responder existed at all.
        if person_owner_path(self.store, target_ref) is not None:
            return
        attempt = {
            "event_id": f"interaction_preview_{command.semantic_digest[:24]}",
            "actor_id": command.actor_id,
            **payload,
        }
        if not _route_available(self.store, attempt):
            raise OperationError(409, "interaction_response_route_unavailable")

    def _validate_reconnaissance(self, command: CommandEnvelope) -> dict[str, Any]:
        payload = command.payload
        if not isinstance(payload, Mapping) or set(payload) != set(payload).intersection(_RECON_PAYLOAD_KEYS):
            raise OperationError(422, "military_reconnaissance_payload_invalid")
        if set(payload) - _RECON_PAYLOAD_KEYS:
            raise OperationError(422, "military_reconnaissance_payload_invalid")
        formation_ref = payload.get("formation_ref")
        operation_ref = payload.get("operation_ref")
        region_ref = payload.get("region_ref")
        if not all(isinstance(value, str) and value for value in (formation_ref, operation_ref, region_ref)):
            raise OperationError(422, "military_reconnaissance_payload_invalid")
        hours = payload.get("observation_hours", 6)
        if isinstance(hours, bool) or not isinstance(hours, int) or not 1 <= hours <= 24:
            raise OperationError(422, "military_reconnaissance_observation_hours_invalid")

        context = super().play_context()
        player_id = str(context.get("campaign", {}).get("player_id") or "")
        if command.actor_id != player_id:
            raise OperationError(403, "military_reconnaissance_not_authorized")
        formations = self._all_controlled_formations(player_id)
        formation = next((row for row in formations if row.get("formation_ref") == formation_ref), None)
        if not isinstance(formation, Mapping):
            raise OperationError(403, "military_reconnaissance_formation_not_controlled")
        if formation.get("mobilized") is False or int(formation.get("personnel", 0) or 0) <= 0:
            raise OperationError(409, "military_reconnaissance_formation_not_ready")
        commander_ref = formation.get("commander_ref")
        if not isinstance(commander_ref, str) or not commander_ref:
            raise OperationError(409, "military_reconnaissance_formation_has_no_commander")
        formation_location = formation.get("location_ref")
        if not isinstance(formation_location, str):
            raise OperationError(409, "military_reconnaissance_formation_location_unknown")
        try:
            if region_ref not in location_chain(self.store.read_json, formation_location):
                raise OperationError(409, "military_reconnaissance_formation_outside_region")
        except ValueError as exc:
            raise OperationError(422, "military_reconnaissance_region_invalid") from exc

        permitted_objects = set(str(x) for x in context.get("permitted_object_refs", []) if isinstance(x, str))
        map_context = context.get("map_context") if isinstance(context.get("map_context"), Mapping) else {}
        known_locations = {
            str(map_context.get(key)) for key in ("location_ref", "parent_ref", "region_ref", "access_node_ref")
            if isinstance(map_context.get(key), str)
        }
        if region_ref not in permitted_objects and region_ref not in known_locations:
            raise OperationError(404, "military_reconnaissance_region_not_player_known")

        operation = next((row for row in context.get("controlled_operations", []) if isinstance(row, Mapping) and row.get("operation_ref") == operation_ref), None)
        if not isinstance(operation, Mapping):
            raise OperationError(404, "military_reconnaissance_operation_not_controlled")
        controlled_refs = {str(x) for x in operation.get("controlled_formation_refs", []) if isinstance(x, str)}
        if controlled_refs and formation_ref not in controlled_refs:
            raise OperationError(409, "military_reconnaissance_formation_not_in_operation")
        campaign_context = operation.get("campaign_context") if isinstance(operation.get("campaign_context"), Mapping) else {}
        target_state_ref = campaign_context.get("target_state_ref")
        if not isinstance(target_state_ref, str) or not target_state_ref:
            entry = operation.get("entry_authority") if isinstance(operation.get("entry_authority"), Mapping) else {}
            target_state_ref = entry.get("target_state_ref")
        if not isinstance(target_state_ref, str) or not target_state_ref:
            raise OperationError(409, "military_reconnaissance_target_state_not_established")

        return {
            "schema": "sword-military-reconnaissance.v1",
            "surface_digest": command.semantic_digest,
            "formation_ref": formation_ref,
            "operation_ref": operation_ref,
            "region_ref": region_ref,
            "target_state_ref": target_state_ref,
            "scout_commander_ref": commander_ref,
            "report_to_ref": player_id,
            "observation_hours": hours,
        }

    def _translate_surface_command(self, command: CommandEnvelope) -> CommandEnvelope:
        if command.command_type != RECON_SURFACE_COMMAND:
            return super()._translate_surface_command(command)
        record = self._validate_reconnaissance(command)
        # Reconnaissance uses the same hidden engine transport boundary as typed
        # interaction/scene actions. Raw scene_consequence remains forbidden to
        # callers, so this machine envelope cannot be forged through the public API.
        summary = reconnaissance_transport(record)
        return CommandEnvelope(
            campaign_id=command.campaign_id,
            request_id=command.request_id,
            actor_id=command.actor_id,
            command_type="scene_consequence",
            expected_revision=command.expected_revision,
            submitted_at=command.submitted_at,
            payload={"summary": summary},
            mode=command.mode,
        )


__all__ = ["ReconnaissanceAwareOperations"]
