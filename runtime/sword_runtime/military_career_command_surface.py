"""Narrow semantic-command registration for military allegiance crises.

The monolithic base engine remains closed by default. This production mixin
admits exactly one additional semantic command owned by the military career and
loyalty subsystem, validates it against the ordinary chronology/payload rules,
and routes resolution to the exact formation/loyalty authorities below.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from sword_runtime.command_contracts import COMMAND_PAYLOAD_KEYS
from sword_runtime.campaign_communications import player_command_location
from sword_runtime.commands import CommandEnvelope
from sword_runtime.history_store import recent_history_events, write_history_index
from sword_runtime.military_career_loyalty import _PLAYER_REF, _clamp, _digest, _event_kind, _event_mentions
from sword_runtime.military_career_loyalty_politics import MilitaryCareerLoyaltyPoliticsMixin, _formation_state_ref
from sword_runtime.player_story_flow import _dispatch_player_story_message, _event_owner_write, _player_delivery
from sword_runtime.sim.calendar import CampaignTime

_COMMAND = "military_allegiance_action"
_ACTIONS = frozenset({"rebel", "defect", "mutiny", "defy_state_order", "desert"})
_NONLEGAL_ALIGNMENT_STATUSES = frozenset({
    "rebel", "defect", "mutiny", "defy_state_order", "desert",
    "fragmented_rebel", "fragmented_defect", "fragmented_mutiny",
    "fragmented_defy_state_order", "fragmented_desert",
})


class MilitaryCareerCommandSurfaceMixin(MilitaryCareerLoyaltyPoliticsMixin):
    """Register one high-salience player/NPC military allegiance command."""

    def _update_formation_loyalty(self, formation_ref: str, at: str) -> None:
        """Remember commander changes and route only genuinely unstable formations."""
        try:
            _before_path, before = self._load_formation(formation_ref)
        except (KeyError, ValueError, FileNotFoundError):
            before = None
        old_loyalty = before.get("military_loyalty_state") if isinstance(before, Mapping) and isinstance(before.get("military_loyalty_state"), Mapping) else {}
        prior_commander = old_loyalty.get("last_commander_ref") if isinstance(old_loyalty, Mapping) else None
        super()._update_formation_loyalty(formation_ref, at)
        try:
            path, after0 = self._load_formation(formation_ref)
        except (KeyError, ValueError, FileNotFoundError):
            return
        if not isinstance(after0, Mapping):
            return
        after = copy.deepcopy(dict(after0))
        loyalty = after.get("military_loyalty_state")
        if not isinstance(loyalty, dict):
            return
        current_commander = after.get("commander_ref") if isinstance(after.get("commander_ref"), str) else None
        if prior_commander is not None and prior_commander != current_commander:
            axes = loyalty.get("axes") if isinstance(loyalty.get("axes"), dict) else {}
            bonds = loyalty.get("commander_bonds") if isinstance(loyalty.get("commander_bonds"), dict) else {}
            prior_bond = int(bonds.get(prior_commander, 250)) if isinstance(prior_commander, str) else 250
            shock = max(6, min(55, max(0, prior_bond - 350) // 9 + 6))
            axes["disaffection"] = _clamp(int(axes.get("disaffection", 180)) + shock)
            axes["formation_identity"] = _clamp(int(axes.get("formation_identity", 500)) + min(12, shock // 3))
            recent = loyalty.setdefault("recent_memory", [])
            if isinstance(recent, list):
                recent.append({
                    "at": at,
                    "event_ref": f"command_change:{prior_commander}:{current_commander or 'vacant'}:{at}",
                    "kind": "command_reassignment_memory",
                    "prior_commander_ref": prior_commander,
                    "new_commander_ref": current_commander,
                    "disaffection_delta_milli": shock,
                    "basis": "long-serving formations remember removal or loss of familiar commanders",
                })
                recent[:] = recent[-int(self._military_rules()["formation_loyalty"]["recent_memory_limit"]):]
        loyalty["last_commander_ref"] = current_commander
        after["military_loyalty_state"] = loyalty
        self.put(path, after)

        state_ref = _formation_state_ref(after)
        if not state_ref:
            return
        axes = loyalty.get("axes") if isinstance(loyalty.get("axes"), Mapping) else {}
        crisis_rules = self._military_rules().get("autonomous_crisis", {})
        unstable = (
            int(axes.get("disaffection", 0)) >= int(crisis_rules.get("disaffection_attention_milli", 760))
            and int(axes.get("state_allegiance", 1000)) <= int(crisis_rules.get("state_allegiance_attention_max_milli", 430))
            and int(axes.get("institutional_professional", 1000)) <= int(crisis_rules.get("institutional_loyalty_attention_max_milli", 460))
        )
        network = self._career_network()
        attention = network.setdefault("formation_attention", {}).setdefault(state_ref, [])
        if unstable and formation_ref not in attention:
            attention.append(formation_ref)
            attention.sort()
        elif not unstable and formation_ref in attention:
            attention[:] = [ref for ref in attention if ref != formation_ref]
        self.put("state/military/career-network/index.json", network)

    def _reroute_transfer(self, order: dict[str, Any], target_formation_ref: str, at: str, reason: str) -> str | None:
        """Ensure a rerouted one-shot order cannot remain falsely active."""
        new_ref = super()._reroute_transfer(order, target_formation_ref, at, reason)
        index = self._transfer_index()
        state_ref = str(order.get("state_ref", ""))
        rows = index.setdefault("active_by_state", {}).setdefault(state_ref, [])
        index["active_by_state"][state_ref] = [ref for ref in rows if ref != str(order.get("order_ref", ""))]
        self.put("state/military/personnel-transfers/index.json", index)
        return new_ref

    # ------------------------------------------------------------------
    # Event-driven emergent officers
    # ------------------------------------------------------------------

    def _battle_evidence_ref(self, formation_ref: str) -> str | None:
        for event in reversed(recent_history_events(self, 96)):
            event_ref = event.get("event_id")
            if not isinstance(event_ref, str) or not _event_mentions(event, {formation_ref}):
                continue
            kind = _event_kind(event).lower()
            if any(token in kind for token in ("battle", "combat", "siege")):
                return event_ref
        return None

    def _post_battle_officer_emergence(
        self,
        command: CommandEnvelope,
        payload: Mapping[str, Any],
        result: dict[str, Any],
    ) -> None:
        """Convert repeated field relevance into a conserved exact officer."""
        refs: list[str] = []
        for key in ("attacker_formation_refs", "defender_formation_refs"):
            values = payload.get(key)
            if isinstance(values, list):
                refs.extend(str(ref) for ref in values if isinstance(ref, str))
        refs = list(dict.fromkeys(refs))
        if not refs:
            return
        rules = self._military_rules().get("officer_emergence", {})
        threshold = max(1, int(rules.get("materialization_pressure_threshold_milli", 430)))
        minimum_reviews = max(1, int(rules.get("minimum_battle_reviews", 2)))
        base_gain = max(1, int(rules.get("base_battle_pressure_gain_milli", 70)))
        survival_divisor = max(1, int(rules.get("survival_gain_divisor", 20)))
        quality_divisor = max(1, int(rules.get("quality_gain_divisor", 25)))
        casualties = result.get("casualties") if isinstance(result.get("casualties"), Mapping) else {}
        at = str(result.get("world_time") or self.read("state/runtime.json").get("world_time"))
        player_visible: list[str] = []
        for formation_ref in refs:
            try:
                path, formation0 = self._load_formation(formation_ref)
            except ValueError:
                continue
            formation = copy.deepcopy(dict(formation0))
            personnel = max(0, int(formation.get("personnel", 0)))
            if personnel <= 0:
                continue
            evidence_ref = self._battle_evidence_ref(formation_ref)
            if not evidence_ref:
                continue
            emergence = formation.setdefault("officer_emergence_state", {})
            if emergence.get("last_evidence_ref") == evidence_ref:
                continue
            losses = max(0, int(casualties.get(formation_ref, 0)))
            before = max(1, personnel + losses)
            survival_milli = _clamp(1000 - losses * 1000 // before)
            quality_milli = _clamp(
                (int(formation.get("readiness", 50)) + int(formation.get("morale", 50)) + int(formation.get("cohesion", 50)) + int(formation.get("training_progress", 20))) * 10 // 4
            )
            reviews = int(emergence.get("battle_reviews", 0)) + 1
            gain = base_gain + survival_milli // survival_divisor + quality_milli // quality_divisor + min(80, reviews * 5)
            emergence["battle_reviews"] = reviews
            emergence["relevance_pressure_milli"] = min(10000, int(emergence.get("relevance_pressure_milli", 0)) + gain)
            emergence["last_evidence_ref"] = evidence_ref
            emergence["last_review_at"] = at
            formation["officer_emergence_state"] = emergence
            self.put(path, formation)
            if reviews < minimum_reviews or int(emergence["relevance_pressure_milli"]) < threshold:
                continue
            alignment_ref = str(formation.get("commander_ref") or formation.get("command_authority") or formation.get("administrative_owner") or "military_service")
            person_ref = self._materialize_emergent_officer(
                formation_ref,
                at=at,
                evidence_ref=evidence_ref,
                alignment_ref=alignment_ref,
                state_ref=_formation_state_ref(formation),
            )
            if not person_ref:
                continue
            path, formation0 = self._load_formation(formation_ref)
            formation = copy.deepcopy(dict(formation0))
            emergence = formation.setdefault("officer_emergence_state", {})
            emergence["relevance_pressure_milli"] = max(0, int(emergence.get("relevance_pressure_milli", threshold)) - threshold)
            emergence["materializations_total"] = int(emergence.get("materializations_total", 0)) + 1
            emergence["last_materialized_person_ref"] = person_ref
            recent = emergence.setdefault("recent_materialized_person_refs", [])
            if person_ref not in recent:
                recent.append(person_ref)
            emergence["recent_materialized_person_refs"] = recent[-16:]
            self.put(path, formation)
            if command.actor_id != self.INTERNAL_ACTOR and self._has_formation_authority(command.actor_id, formation_ref):
                player_visible.append(person_ref)
        if player_visible:
            result["player_visible_emergent_officer_refs"] = player_visible
            result["emergent_officer_rule"] = "each listed person is a newly exact representation of one already-conserved formation member whose repeated field relevance crossed the saved materialization threshold"

    # ------------------------------------------------------------------
    # Routed autonomous desertion/mutiny pressure
    # ------------------------------------------------------------------

    def _autonomous_crisis_candidate(self, formation_ref: str, state_ref: str, crisis_ref: str, at: str) -> str | None:
        _path, formation = self._load_formation(formation_ref)
        best: tuple[int, str] | None = None
        for person_ref in self._formation_named_officer_refs(formation):
            if person_ref == _PLAYER_REF:
                continue
            try:
                _pp, person = self._exact_person(person_ref, active=False)
            except ValueError:
                continue
            loyalty = person.get("military_loyalty_state") if isinstance(person.get("military_loyalty_state"), Mapping) else {}
            state = int(loyalty.get("state_allegiance_milli", 720))
            institution = int(loyalty.get("institutional_professional_milli", 700))
            formation_bond = int(loyalty.get("formation_bond_milli", 400))
            pressure = (1000 - state) + (1000 - institution) + formation_bond
            if best is None or pressure > best[0] or (pressure == best[0] and person_ref < best[1]):
                best = (pressure, person_ref)
        if best is not None and best[0] >= 1450:
            return best[1]

        # Extreme aggregate disaffection can make an otherwise anonymous junior
        # officer causally important. Materialize that existing body rather than
        # inventing a rebel leader out of thin air.
        person_ref = self._materialize_emergent_officer(
            formation_ref,
            at=at,
            evidence_ref=crisis_ref,
            alignment_ref=str(formation.get("administrative_owner", state_ref)),
            state_ref=state_ref,
        )
        if not person_ref:
            return None
        person_path, person0 = self._exact_person(person_ref, active=False)
        person = copy.deepcopy(dict(person0))
        formation_loyalty = formation.get("military_loyalty_state") if isinstance(formation.get("military_loyalty_state"), Mapping) else {}
        axes = formation_loyalty.get("axes") if isinstance(formation_loyalty.get("axes"), Mapping) else {}
        loyalty = self._personal_loyalty(person, state_ref)
        loyalty["state_allegiance_milli"] = _clamp(int(axes.get("state_allegiance", 430)) + 20)
        loyalty["institutional_professional_milli"] = _clamp(int(axes.get("institutional_professional", 460)) + 20)
        loyalty["formation_bond_milli"] = max(650, int(loyalty.get("formation_bond_milli", 400)))
        person["military_loyalty_state"] = loyalty
        person["military_alignment_state"] = {
            "status": "crisis_spokesperson_candidate",
            "crisis_ref": crisis_ref,
            "effective_authority_ref": str(formation.get("administrative_owner", state_ref)),
            "at": at,
            "administrative_ownership_changed": False,
        }
        self.put(person_path, person)
        return person_ref

    def _resolve_autonomous_desertion(self, formation_ref: str, state_ref: str, at: str) -> dict[str, Any] | None:
        try:
            path, formation0 = self._load_formation(formation_ref)
        except ValueError:
            return None
        formation = copy.deepcopy(dict(formation0))
        if int(formation.get("personnel", 0)) <= 0 or _formation_state_ref(formation) != state_ref:
            return None
        alignment = formation.get("military_allegiance_state")
        if isinstance(alignment, Mapping) and str(alignment.get("status", "")) in _NONLEGAL_ALIGNMENT_STATUSES:
            return None
        loyalty = formation.get("military_loyalty_state") if isinstance(formation.get("military_loyalty_state"), Mapping) else {}
        axes = loyalty.get("axes") if isinstance(loyalty.get("axes"), Mapping) else {}
        rules = self._military_rules().get("autonomous_crisis", {})
        if not (
            int(axes.get("disaffection", 0)) >= int(rules.get("disaffection_attention_milli", 760))
            and int(axes.get("state_allegiance", 1000)) <= int(rules.get("state_allegiance_attention_max_milli", 430))
            and int(axes.get("institutional_professional", 1000)) <= int(rules.get("institutional_loyalty_attention_max_milli", 460))
        ):
            return None
        last = loyalty.get("last_autonomous_crisis_at")
        if isinstance(last, str):
            elapsed = CampaignTime.parse(last).seconds_until(CampaignTime.parse(at))
            if elapsed < max(1, int(rules.get("cooldown_days", 180))) * 86400:
                return None
        crisis_ref = f"military_autonomous_desertion_{_digest([formation_ref, state_ref, at])}"
        leader_ref = self._autonomous_crisis_candidate(formation_ref, state_ref, crisis_ref, at)
        if not leader_ref:
            return None
        # Record cooldown before resolution. Any fragment inherits the formation's
        # bounded loyalty history through the split and therefore remembers it.
        path, formation0 = self._load_formation(formation_ref)
        formation = copy.deepcopy(dict(formation0))
        loyalty = formation.get("military_loyalty_state") if isinstance(formation.get("military_loyalty_state"), dict) else {}
        loyalty["last_autonomous_crisis_at"] = at
        formation["military_loyalty_state"] = loyalty
        self.put(path, formation)

        support, _detail = self._immediate_officer_support(formation_ref, leader_ref)
        order_legitimacy = _clamp(int(axes.get("legitimacy_confidence", 700)) + 90)
        estimate = self.evaluate_formation_allegiance(
            formation_ref,
            proposed_commander_ref=leader_ref,
            order_legitimacy_milli=order_legitimacy,
            immediate_officer_support_milli=support,
        )
        decisions = self._named_crisis_decisions(formation_ref, leader_ref, crisis_ref)
        outcome = self._choose_crisis_outcome(estimate, crisis_ref, formation_ref)
        player_involved = str(formation.get("commander_ref", "")) == _PLAYER_REF or str(formation.get("command_authority", "")) == _PLAYER_REF
        if outcome == "follow_proposed_commander":
            result = self._apply_whole_follow(
                formation_ref,
                proposed_ref=leader_ref,
                crisis_ref=crisis_ref,
                action="desert",
                decisions=decisions,
                at=at,
            )
        elif outcome == "remain_with_legal_authority":
            result = self._apply_whole_state(
                formation_ref,
                proposed_ref=leader_ref,
                crisis_ref=crisis_ref,
                action="desert",
                decisions=decisions,
                at=at,
            )
        else:
            result = self._fragment_formation(
                formation_ref,
                proposed_ref=leader_ref,
                crisis_ref=crisis_ref,
                action="desert",
                estimate=estimate,
                decisions=decisions,
                at=at,
            )
        history = copy.deepcopy(self.read("state/history/events/index.json"))
        history.setdefault("events", []).append({
            "event_id": crisis_ref,
            "kind": "autonomous_military_desertion_crisis",
            "at": at,
            "state_ref": state_ref,
            "formation_ref": formation_ref,
            "leader_ref": leader_ref,
            "outcome": result.get("outcome"),
            "estimate": dict(estimate),
            "named_decisions": copy.deepcopy(decisions),
            "administrative_ownership_changed": False,
        })
        write_history_index(self, history)
        if player_involved:
            event_ref = f"event_{crisis_ref}"
            summary = (
                f"Severe accumulated disaffection inside {formation_ref} has produced an active desertion/mutiny crisis. "
                f"The formation resolved as {result.get('outcome')}; subordinate officers and troops did not move as a single loyalty block."
            )
            _dispatch_player_story_message(
                self, event_ref=event_ref, at=at, actor_ref=leader_ref, source_owner_ref=leader_ref,
                event_kind="military_allegiance_crisis", process_kind="autonomous_military_loyalty",
                transit_stage="urgent_formation_report_in_transit",
                delivered_stage=str(result.get("outcome", "resolved")), delivered_summary=summary,
                route_label="urgent officer and formation report",
                source_location_ref=str(formation.get("location_ref") or ""),
            )
            # The autonomous crisis has already mechanically resolved; its report
            # is high-salience information, not a decision that can lawfully stop
            # chronology before the courier reaches Wei.
            self._pending_wake_created = None
        return result

    def _autonomy_state(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        super()._autonomy_state(host, occurrences, at)
        if occurrences <= 0:
            return
        state_ref = str(host.get("owner_ref", ""))
        network = self._career_network()
        attention = [ref for ref in network.get("formation_attention", {}).get(state_ref, []) if isinstance(ref, str)]
        if not attention:
            return
        rules = self._military_rules().get("autonomous_crisis", {})
        width = max(1, int(rules.get("review_slice_per_state_wake", 32)))
        cursors = network.setdefault("formation_attention_cursor", {})
        cursor = max(0, int(cursors.get(state_ref, 0))) % len(attention)
        selected = [attention[(cursor + offset) % len(attention)] for offset in range(min(width, len(attention)))]
        cursors[state_ref] = (cursor + len(selected)) % len(attention)
        self.put("state/military/career-network/index.json", network)
        for formation_ref in selected:
            self._resolve_autonomous_desertion(formation_ref, state_ref, at)

    # ------------------------------------------------------------------
    # Player/NPC semantic command
    # ------------------------------------------------------------------

    def _validate_command_semantics(self, command: CommandEnvelope, payload: Mapping[str, Any]) -> None:
        if command.command_type != _COMMAND:
            super()._validate_command_semantics(command, payload)
            return

        # Mirror the base engine's generic chronology and payload fail-closed
        # checks without opening its global command registry to arbitrary types.
        now = self._world_time()
        if CampaignTime.parse(command.submitted_at) != now:
            raise ValueError("submitted_at must equal authoritative campaign world time")
        allowed = COMMAND_PAYLOAD_KEYS.get(_COMMAND)
        if allowed is None:
            raise ValueError("military allegiance command has no payload contract")
        unknown = sorted(set(payload) - set(allowed))
        if unknown:
            raise ValueError(f"unsupported payload fields for {_COMMAND}: {unknown}")

        action = str(payload.get("action", ""))
        if action not in _ACTIONS:
            raise ValueError("unsupported military allegiance action")
        refs = payload.get("formation_refs")
        if (
            not isinstance(refs, list)
            or not 1 <= len(refs) <= 64
            or any(not isinstance(ref, str) or not ref for ref in refs)
            or len(refs) != len(set(refs))
        ):
            raise ValueError("military allegiance action requires 1-64 distinct formation_refs")
        proposed = str(payload.get("proposed_commander_ref") or command.actor_id)
        self._exact_person(proposed, active=False)
        for ref in refs:
            _path, formation = self._load_formation(str(ref))
            if int(formation.get("personnel", 0)) <= 0:
                raise ValueError("military allegiance action requires living formations")
        claimant = payload.get("claimant_ref")
        if claimant is not None and (not isinstance(claimant, str) or not claimant or len(claimant) > 180):
            raise ValueError("claimant_ref must be a non-empty bounded saved reference when supplied")
        basis_ref = payload.get("basis_ref")
        if basis_ref is not None:
            if not isinstance(basis_ref, str) or not basis_ref or len(basis_ref) > 180:
                raise ValueError("basis_ref is invalid")
            if hasattr(self, "_evidence_claim"):
                self._evidence_claim(command.actor_id, basis_ref, require_authoritative=False)

    def _authorize_command(self, command: CommandEnvelope, payload: Mapping[str, Any]) -> None:
        if command.command_type != _COMMAND:
            super()._authorize_command(command, payload)
            return
        # _authorize() has already enforced internal/autonomous versus
        # player/gameplay identity and mode. This layer owns only crisis scope.
        if command.actor_id == self.INTERNAL_ACTOR:
            proposed = str(payload.get("proposed_commander_ref") or "")
            if not proposed:
                raise PermissionError("autonomous military allegiance action requires an exact proposed commander")
            return
        proposed = str(payload.get("proposed_commander_ref") or command.actor_id)
        if proposed != command.actor_id:
            raise PermissionError("player may initiate a military allegiance crisis only for their own declared command position")
        for formation_ref in payload.get("formation_refs", []):
            if not self._has_formation_authority(command.actor_id, str(formation_ref)):
                raise PermissionError("military allegiance crisis may be initiated only within formations the player currently commands")

        # Immediate allegiance breaks are local contested command acts.  This
        # command surface intentionally has no delayed remote-command owner yet,
        # so authority alone is insufficient: the player must actually be with
        # every affected formation.  Keep this check here rather than only in a
        # parent mixin because this surface owns the command and short-circuits
        # parent authorization for military_allegiance_action.
        player_location = player_command_location(self)
        if not player_location:
            raise PermissionError("military allegiance crisis requires Tang Wei's exact current location")
        for formation_ref in payload.get("formation_refs", []):
            _path, formation = self._load_formation(str(formation_ref))
            if str(formation.get("location_ref") or "") != player_location:
                raise PermissionError(
                    "remote military allegiance action requires a physical command-message route; "
                    "Tang Wei must be co-located with the affected formation for the immediate crisis command"
                )

    def _command_layer_military_career_command_surface(self, command: CommandEnvelope, payload: Mapping[str, Any], next_dispatch: Any) -> dict[str, Any]:
        if command.command_type == _COMMAND:
            result = self._resolve_military_allegiance_action(command, payload)
            self._write_meta(command, str(result["world_time"]))
            return self._result(**result)
        result = next_dispatch()
        if command.command_type == "battle_resolve" and isinstance(result, dict):
            self._post_battle_officer_emergence(command, payload, result)
        return result


__all__ = ["MilitaryCareerCommandSurfaceMixin"]
