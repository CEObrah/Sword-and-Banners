"""Player-safe projection of sovereign campaign-entry authority.

This layer corrects stale staging language without mutating campaign state during a
read. Exact operations and orders remain authority. When the same exact sovereign
campaign order already establishes lawful hostile entry, the player surface must not
continue advertising a second nonexistent war/entry authorization gate.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any, Optional

from sword_runtime.api.campaign_planning_operations import CampaignPlanningAwareOperations
from sword_runtime.api.interaction_surface import person_owner_path, validate_interaction_payload
from sword_runtime.api.operations import OperationError
from sword_runtime.causal_event_store import get_causal_event_from_reader
from sword_runtime.deployment_attestation import deployment_attestation
from sword_runtime.interaction_routing_health import summarize_interaction_routing
from sword_runtime.sovereign_campaign_authority import operation_entry_projection
from sword_runtime.operation_routing import exact_operation_record


_REMOTE_PERSON_CHANNEL_KINDS = frozenset({
    "message", "audience_response", "institutional_response", "petition_response",
})
_STALE_ENTRY_DIRECTIVE_KINDS = frozenset({"hold_staging_and_report"})


class SovereignAuthorityAwareOperations(CampaignPlanningAwareOperations):
    """Keep bounded operation, interaction, and deployment handoffs aligned with exact authority."""

    @staticmethod
    def _campaign_commander_name(campaign_command: Mapping[str, Any], commander_ref: str) -> str | None:
        planning = campaign_command.get("march_planning") if isinstance(campaign_command.get("march_planning"), Mapping) else {}
        scheme = planning.get("campaign_scheme") if isinstance(planning.get("campaign_scheme"), Mapping) else {}
        rows = scheme.get("command_assignments") if isinstance(scheme.get("command_assignments"), list) else []
        for row in rows:
            if not isinstance(row, Mapping) or row.get("commander_ref") != commander_ref:
                continue
            name = row.get("commander_name")
            if isinstance(name, str) and name:
                return name
        return None

    def _normalize_post_planning_projection(self, view: dict[str, Any]) -> None:
        """Normalize fields that CampaignPlanningAwareOperations adds after base views.

        Python dispatch invokes this class's `_controlled_operation_views` while the
        parent `play_context` is still assembling the operation projection. The live
        march-planning overlay is attached only after that call returns, so planning
        status and commander-name cleanup must run once more on the final view.
        """
        campaign_command = view.get("campaign_command")
        if not isinstance(campaign_command, Mapping):
            return
        campaign_command = copy.deepcopy(dict(campaign_command))

        planning = campaign_command.get("march_planning")
        if isinstance(planning, Mapping):
            planning = copy.deepcopy(dict(planning))
            scheme = planning.get("campaign_scheme")
            if isinstance(scheme, Mapping):
                scheme = copy.deepcopy(dict(scheme))
                scheme_status = scheme.get("status")
                if isinstance(scheme_status, str) and "entry_authority" in scheme_status:
                    scheme["historical_status"] = scheme_status
                    scheme["status"] = "staff_plan_pending_exact_orders"
                    scheme["status_projection_only"] = True
                planning["campaign_scheme"] = scheme
            campaign_command["march_planning"] = planning

        supreme_ref = campaign_command.get("supreme_commander_ref") or campaign_command.get("superior_command_ref")
        if isinstance(supreme_ref, str) and supreme_ref:
            context = copy.deepcopy(dict(view.get("campaign_context", {})))
            if not isinstance(context.get("campaign_commander_ref"), str) or not context.get("campaign_commander_ref"):
                context["campaign_commander_ref"] = supreme_ref
                context["campaign_commander_projection_only"] = True
            if not isinstance(context.get("campaign_commander_name"), str) or not context.get("campaign_commander_name"):
                name = self._campaign_commander_name(campaign_command, supreme_ref)
                if isinstance(name, str) and name:
                    context["campaign_commander_name"] = name
            view["campaign_context"] = context

        view["campaign_command"] = campaign_command

    def _controlled_operation_views(self, controlled_refs: set[str]) -> list[dict[str, Any]]:
        views = super()._controlled_operation_views(controlled_refs)
        for view in views:
            operation_ref = view.get("operation_ref")
            resolved = exact_operation_record(self.store.read_json, str(operation_ref or ""))
            if resolved is None:
                continue
            _path, operation = resolved
            campaign_context = view.get("campaign_context") if isinstance(view.get("campaign_context"), Mapping) else None
            authority = operation_entry_projection(self.runtime.planner, operation, campaign_context)
            if not isinstance(authority, Mapping) or authority.get("authorized") is not True:
                continue

            # Do not falsify the saved historical packet. Surface the effective
            # legal state beside it and correct only fields whose old value claimed
            # that hostile entry itself was forbidden. A separate exact march or
            # tactical order may still be required by the campaign command chain.
            view["entry_status"] = "authorized"
            view["entry_authority"] = copy.deepcopy(dict(authority))
            if str(view.get("campaign_phase", "")) == "awaiting_entry_authority":
                view["campaign_phase"] = "awaiting_march_orders"
                view["campaign_phase_projection_only"] = True
            if str(view.get("order_status", "")) == "awaiting_entry_authority":
                view["order_status"] = "awaiting_march_orders"
                view["order_status_projection_only"] = True

            context = copy.deepcopy(dict(campaign_context)) if isinstance(campaign_context, Mapping) else {}
            area = context.get("operational_area") if isinstance(context.get("operational_area"), Mapping) else {}
            area = copy.deepcopy(dict(area))
            area["hostile_entry_authorized"] = True
            area["entry_status"] = "authorized"
            area["entry_authority_basis"] = authority.get("basis")
            context["operational_area"] = area
            view["campaign_context"] = context

            current_order = view.get("current_operational_order")
            if isinstance(current_order, Mapping):
                current_order = copy.deepcopy(dict(current_order))
                packet = current_order.get("mission_packet")
                if isinstance(packet, Mapping):
                    packet = copy.deepcopy(dict(packet))
                    packet["hostile_entry_authorized"] = True
                    packet["entry_status"] = "authorized"
                    packet["entry_authority_basis"] = authority.get("basis")
                    next_trigger = packet.get("next_phase_trigger")
                    if isinstance(next_trigger, str) and "entry authority" in next_trigger.lower():
                        packet["historical_next_phase_trigger"] = next_trigger
                        packet["next_phase_trigger"] = (
                            "Hostile entry authority is already established. Exact march sequence, timing, command assignment, "
                            "and tactics remain separate authorities."
                        )
                        packet["next_phase_trigger_projection_only"] = True
                    current_order["mission_packet"] = packet
                current_order["effective_entry_authority"] = copy.deepcopy(dict(authority))
                follow_on = current_order.get("follow_on_requirement")
                if isinstance(follow_on, str) and "entry authority" in follow_on.lower():
                    current_order["historical_follow_on_requirement"] = follow_on
                    current_order["follow_on_requirement"] = (
                        "Hostile entry authority is already established. Await or execute the distinct exact march/order handoff; "
                        "movement, tactics, and temporary campaign roles remain separate decisions."
                    )
                    current_order["follow_on_requirement_projection_only"] = True
                if str(current_order.get("status", "")) == "staged_awaiting_entry_authority":
                    current_order["historical_staging_status"] = current_order.get("status")
                    current_order["status"] = "completed_staging_entry_now_authorized"
                    current_order["status_projection_only"] = True
                view["current_operational_order"] = current_order

            campaign_command = view.get("campaign_command")
            if isinstance(campaign_command, Mapping):
                campaign_command = copy.deepcopy(dict(campaign_command))
                campaign_command["entry_authority"] = copy.deepcopy(dict(authority))
                campaign_command["stale_entry_hold_rule"] = (
                    "Any older directive whose only blocker is missing war/entry authority is no longer a current legal-entry block. "
                    "Exact march sequence, command assignment, and tactical orders remain separate authorities."
                )

                directive = campaign_command.get("current_superior_directive")
                if isinstance(directive, Mapping):
                    directive = copy.deepcopy(dict(directive))
                    text = str(directive.get("directive_text") or "")
                    kind = str(directive.get("kind") or "")
                    if kind in _STALE_ENTRY_DIRECTIVE_KINDS and "entry authority" in text.lower():
                        directive["historical_status"] = directive.get("status")
                        directive["historical_directive_text"] = text
                        directive["status"] = "superseded_by_entry_authority"
                        directive["status_projection_only"] = True
                        directive["entry_hold_effective"] = False
                        directive["effective_directive_rule"] = (
                            "Maintain readiness, security, reconnaissance, and command reporting while awaiting the distinct exact march/order handoff. "
                            "The prior hostile-entry prohibition is no longer effective."
                        )
                        campaign_command["current_superior_directive"] = directive

                daily = campaign_command.get("daily_cycle")
                if isinstance(daily, Mapping):
                    daily = copy.deepcopy(dict(daily))
                    paused_phase = daily.get("paused_campaign_phase")
                    if paused_phase == "awaiting_entry_authority" and str(view.get("campaign_phase", "")) != "awaiting_entry_authority":
                        daily["historical_paused_campaign_phase"] = paused_phase
                        daily["paused_campaign_phase"] = view.get("campaign_phase")
                        daily["paused_campaign_phase_projection_only"] = True
                    campaign_command["daily_cycle"] = daily

                # Some older/current callers attach march planning directly to the
                # base operation view. Normalize it here when present. The final
                # play_context pass below covers the live overlay added later by
                # CampaignPlanningAwareOperations.
                planning = campaign_command.get("march_planning")
                if isinstance(planning, Mapping):
                    planning = copy.deepcopy(dict(planning))
                    scheme = planning.get("campaign_scheme")
                    if isinstance(scheme, Mapping):
                        scheme = copy.deepcopy(dict(scheme))
                        scheme_status = scheme.get("status")
                        if isinstance(scheme_status, str) and "entry_authority" in scheme_status:
                            scheme["historical_status"] = scheme_status
                            scheme["status"] = "staff_plan_pending_exact_orders"
                            scheme["status_projection_only"] = True
                        planning["campaign_scheme"] = scheme
                    campaign_command["march_planning"] = planning

                supreme_ref = campaign_command.get("supreme_commander_ref") or campaign_command.get("superior_command_ref")
                if isinstance(supreme_ref, str) and supreme_ref:
                    context = copy.deepcopy(dict(view.get("campaign_context", {})))
                    if not isinstance(context.get("campaign_commander_ref"), str) or not context.get("campaign_commander_ref"):
                        context["campaign_commander_ref"] = supreme_ref
                        context["campaign_commander_projection_only"] = True
                    if not isinstance(context.get("campaign_commander_name"), str) or not context.get("campaign_commander_name"):
                        name = self._campaign_commander_name(campaign_command, supreme_ref)
                        if isinstance(name, str) and name:
                            context["campaign_commander_name"] = name
                    view["campaign_context"] = context

                view["campaign_command"] = campaign_command
        return views

    def _validate_interaction_authority(self, command) -> None:
        """Require real access for direct person interaction, not mere visibility."""
        super()._validate_interaction_authority(command)
        payload = validate_interaction_payload(command.payload)
        target_ref = payload["target_ref"]
        if payload["action"] == "seek_contact" or person_owner_path(self.store, target_ref) is None:
            return

        context = self.play_context()
        scene = context.get("scene") if isinstance(context, Mapping) else None
        cast = scene.get("scene_cast") if isinstance(scene, Mapping) else None
        present = cast.get("present_people") if isinstance(cast, Mapping) else []
        present_refs = {
            str(row.get("person_id"))
            for row in present
            if isinstance(row, Mapping) and isinstance(row.get("person_id"), str)
        } if isinstance(present, list) else set()
        if target_ref in present_refs:
            return

        # A delivered message/response from this exact person is an established
        # remote channel for replying through that process. It is not physical
        # co-presence and cannot be reused with an unrelated process.
        process_ref = payload.get("process_ref")
        if isinstance(process_ref, str) and process_ref:
            process = get_causal_event_from_reader(self.store, process_ref)
            player_id = str(context.get("campaign", {}).get("player_id") or "")
            if (
                isinstance(process, Mapping)
                and process.get("status") == "triggered"
                and process.get("kind") in _REMOTE_PERSON_CHANNEL_KINDS
                and process.get("actor_ref") == target_ref
                and process.get("target_ref") == player_id
            ):
                return
        raise OperationError(409, "interaction_person_access_not_established")

    def play_context(self) -> dict[str, Any]:
        context = super().play_context()
        authorized = [
            row for row in context.get("controlled_operations", [])
            if isinstance(row, dict)
            and isinstance(row.get("entry_authority"), Mapping)
            and row["entry_authority"].get("authorized") is True
        ]
        for view in authorized:
            self._normalize_post_planning_projection(view)
        if authorized:
            guidance = context.setdefault("narration_guidance", {})
            guidance["campaign_entry_authority"] = (
                "When a controlled operation exposes entry_authority.authorized=true, do not narrate a need for another war declaration or hostile-entry authorization. "
                "Fields prefixed historical_ preserve stale pre-authority text only for provenance; projection-only status/directive fields are the effective player-facing reading until chronology commits the next exact order lifecycle. "
                "A distinct march, formation assignment, tactical order, ceasefire, treaty, or war-termination decision must still come from its own authority."
            )

        interaction = context.get("commands", {}).get("command_types", {}).get("interaction_action")
        if isinstance(interaction, dict):
            guidance = interaction.setdefault("input_guidance", {})
            guidance["direct_person_access_rule"] = (
                "A permitted person ID establishes visibility/read authority, not face-to-face access. Any interaction action other than seek_contact that targets an exact person requires that person in scene.scene_cast.present_people, or an exact triggered message/response process from that same person establishing a remote reply channel. nearby_people, broad co-location, campaign membership, and person-sheet availability do not satisfy this rule."
            )
        context.setdefault("limits", {})["direct_person_interaction_requires_access"] = True
        return context

    def ooc_audit(self, focus: Optional[str] = None, observations: Optional[list[str]] = None) -> dict[str, Any]:
        result = super().ooc_audit(focus, observations)
        result["deployment"] = deployment_attestation(self.runtime.root)
        routing = summarize_interaction_routing(self.runtime.planner)
        result["interaction_routing"] = routing
        vitality = result.get("playability_vitality")
        if isinstance(vitality, dict):
            diagnostics = list(vitality.get("diagnostics", [])) if isinstance(vitality.get("diagnostics"), list) else []
            suggestions = list(vitality.get("suggestions", [])) if isinstance(vitality.get("suggestions"), list) else []
            diagnostics.extend(str(value) for value in routing.get("diagnostics", []) if isinstance(value, str))
            suggestions.extend(str(value) for value in routing.get("suggestions", []) if isinstance(value, str))
            vitality["diagnostics"] = list(dict.fromkeys(diagnostics))
            vitality["suggestions"] = list(dict.fromkeys(suggestions))
        return result

    def execute_command(self, command):
        try:
            return super().execute_command(command)
        except OperationError as exc:
            # An old service discovers a deploy-relevant main revision during
            # remote-durability preflight before it can mutate campaign truth.
            # Translate that specific operational condition into actionable UX
            # rather than making a healthy campaign look generically broken.
            if exc.code == "transaction_remote_durability_failed":
                attestation = deployment_attestation(self.runtime.root)
                if attestation.get("deployment_required") is True:
                    raise OperationError(503, "deployment_required") from exc
            raise


__all__ = ["SovereignAuthorityAwareOperations"]
