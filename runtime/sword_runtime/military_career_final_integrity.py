"""Final agency/integrity overlay for military career and allegiance resolution.

This layer preserves the distinction between political state allegiance, House or
patron loyalty, immediate command loyalty, formation identity, and administrative
ownership.  Private and House formations therefore participate in the same
career/loyalty simulation without being misclassified as state-owned troops.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from sword_runtime.history_store import write_history_index
from sword_runtime.military_career_command_surface import MilitaryCareerCommandSurfaceMixin, _NONLEGAL_ALIGNMENT_STATUSES
from sword_runtime.military_career_loyalty import _PLAYER_REF, _clamp, _digest
from sword_runtime.military_career_loyalty_politics import _formation_state_ref
from sword_runtime.player_story_flow import _event_owner_write, _player_delivery
from sword_runtime.sim.calendar import CampaignTime


class MilitaryCareerFinalIntegrityMixin(MilitaryCareerCommandSurfaceMixin):
    """Keep career, patronage, loyalty, and crisis state consistent across owners."""

    # ------------------------------------------------------------------
    # Political state versus House/patron identity
    # ------------------------------------------------------------------

    @staticmethod
    def _house_ref_from_family_name(value: str) -> str:
        text = str(value).strip().lower().replace("&", " and ")
        slug = "_".join(part for part in "".join(ch if ch.isalnum() else " " for ch in text).split() if part)
        if slug.startswith("house_"):
            return slug
        if slug.startswith("house"):
            slug = slug.removeprefix("house").lstrip("_")
        return f"house_{slug}" if slug else ""

    def _formation_patron_ref(self, formation: Mapping[str, Any]) -> str | None:
        admin = formation.get("administrative_owner")
        if isinstance(admin, str) and admin.startswith("house_"):
            return admin
        if isinstance(admin, str) and admin.startswith("char_"):
            try:
                _path, person = self._exact_person(admin, active=False)
            except ValueError:
                return admin
            family = person.get("family")
            if isinstance(family, str) and family:
                candidate = self._house_ref_from_family_name(family)
                if candidate:
                    owners = self.read("state/index/owner-index.json").get("owners", {})
                    if isinstance(owners, Mapping) and candidate in owners:
                        return candidate
            return admin
        force_ref = formation.get("owner_force_ref")
        if isinstance(force_ref, str):
            try:
                force = self.read(self.owner_path(force_ref))
            except (KeyError, ValueError, FileNotFoundError):
                force = None
            if isinstance(force, Mapping):
                force_admin = force.get("administrative_owner")
                if isinstance(force_admin, str) and (force_admin.startswith("house_") or force_admin.startswith("char_")):
                    return force_admin
        return None

    def _formation_political_state_ref(self, formation: Mapping[str, Any]) -> str | None:
        direct = _formation_state_ref(formation)
        if direct:
            return direct
        patron = self._formation_patron_ref(formation)
        if isinstance(patron, str) and patron.startswith("house_"):
            try:
                house = self.read(self.owner_path(patron))
            except (KeyError, ValueError, FileNotFoundError):
                house = None
            if isinstance(house, Mapping):
                state = house.get("state")
                if isinstance(state, str) and state:
                    return state if state.startswith("state_") else f"state_{state}"
        force_ref = formation.get("owner_force_ref")
        if isinstance(force_ref, str):
            try:
                force = self.read(self.owner_path(force_ref))
            except (KeyError, ValueError, FileNotFoundError):
                force = None
            ledger = force.get("cohort_ledger") if isinstance(force, Mapping) else None
            cohorts = ledger.get("cohorts") if isinstance(ledger, Mapping) else None
            found: set[str] = set()
            if isinstance(cohorts, Mapping):
                for cohort in cohorts.values():
                    if not isinstance(cohort, Mapping):
                        continue
                    origin = cohort.get("origin") if isinstance(cohort.get("origin"), Mapping) else {}
                    population_ref = origin.get("population_ref")
                    if isinstance(population_ref, str) and population_ref.startswith("population_"):
                        found.add("state_" + population_ref.removeprefix("population_"))
            if len(found) == 1:
                return next(iter(found))
        return None

    def _patron_leader_ref(self, patron_ref: str | None) -> str | None:
        if not patron_ref:
            return None
        if patron_ref.startswith("char_"):
            return patron_ref
        if patron_ref.startswith("house_"):
            try:
                house = self.read(self.owner_path(patron_ref))
            except (KeyError, ValueError, FileNotFoundError):
                return None
            leader = house.get("leader_ref") if isinstance(house, Mapping) else None
            return str(leader) if isinstance(leader, str) and leader else None
        return None

    def _formation_attention_owner_ref(self, formation: Mapping[str, Any]) -> str | None:
        admin = formation.get("administrative_owner")
        if isinstance(admin, str) and admin.startswith("state_"):
            return admin
        patron = self._formation_patron_ref(formation)
        if isinstance(patron, str) and patron.startswith("house_"):
            return patron
        return self._formation_political_state_ref(formation)

    def _update_formation_loyalty(self, formation_ref: str, at: str) -> None:
        try:
            _path, before = self._load_formation(formation_ref)
        except (KeyError, ValueError, FileNotFoundError):
            return
        prior_loyalty = before.get("military_loyalty_state") if isinstance(before, Mapping) and isinstance(before.get("military_loyalty_state"), Mapping) else {}
        last_text = prior_loyalty.get("last_review_at") if isinstance(prior_loyalty, Mapping) else None
        months = 1
        if isinstance(last_text, str):
            try:
                elapsed = CampaignTime.parse(last_text).seconds_until(CampaignTime.parse(at))
                months = max(1, int(elapsed // (30 * 86400)))
            except (TypeError, ValueError):
                months = 1
        super()._update_formation_loyalty(formation_ref, at)
        path, current0 = self._load_formation(formation_ref)
        current = copy.deepcopy(dict(current0))
        loyalty = current.get("military_loyalty_state")
        if not isinstance(loyalty, dict):
            return
        rules = self._military_rules()["formation_loyalty"]
        patron_ref = self._formation_patron_ref(current)
        political_state_ref = self._formation_political_state_ref(current)
        if political_state_ref:
            loyalty["political_state_ref"] = political_state_ref
        if patron_ref:
            bonds = loyalty.setdefault("house_patron_bonds", {})
            bond = int(bonds.get(patron_ref, int(rules.get("default_patron_bond_milli", 350))))
            bond += months * int(rules.get("patron_service_month_gain_milli", 6))
            morale = int(current.get("morale", 50) or 50)
            if morale >= 70:
                bond += int(rules.get("well_supported_patron_gain_milli", 4))
            axes = loyalty.get("axes") if isinstance(loyalty.get("axes"), Mapping) else {}
            if int(axes.get("disaffection", 180)) >= 700:
                bond -= int(rules.get("severe_disaffection_patron_loss_milli", 8))
            bonds[patron_ref] = _clamp(bond)
            loyalty["patron_ref"] = patron_ref
        current["military_loyalty_state"] = loyalty
        self.put(path, current)

        axes = loyalty.get("axes") if isinstance(loyalty.get("axes"), Mapping) else {}
        crisis_rules = self._military_rules().get("autonomous_crisis", {})
        unstable = (
            int(axes.get("disaffection", 0)) >= int(crisis_rules.get("disaffection_attention_milli", 760))
            and int(axes.get("state_allegiance", 1000)) <= int(crisis_rules.get("state_allegiance_attention_max_milli", 430))
            and int(axes.get("institutional_professional", 1000)) <= int(crisis_rules.get("institutional_loyalty_attention_max_milli", 460))
        )
        attention_owner = self._formation_attention_owner_ref(current)
        if not attention_owner:
            return
        network = self._career_network()
        attention = network.setdefault("formation_attention", {}).setdefault(attention_owner, [])
        if unstable and formation_ref not in attention:
            attention.append(formation_ref)
            attention.sort()
        elif not unstable and formation_ref in attention:
            attention[:] = [ref for ref in attention if ref != formation_ref]
        self.put("state/military/career-network/index.json", network)

    def _settle_person_career(self, person_ref: str, at: str) -> None:
        super()._settle_person_career(person_ref, at)
        if person_ref == _PLAYER_REF:
            return
        try:
            path, person0 = self._exact_person(person_ref, active=False)
        except ValueError:
            return
        person = copy.deepcopy(dict(person0))
        formation_ref, formation = self._person_current_formation(person)
        if not formation_ref or not isinstance(formation, Mapping):
            return
        patron_ref = self._formation_patron_ref(formation)
        political_state_ref = self._formation_political_state_ref(formation)
        if not patron_ref or not political_state_ref:
            return
        loyalty = self._personal_loyalty(person, political_state_ref)
        patron_bonds = loyalty.setdefault("house_patron_bonds", {})
        formation_loyalty = formation.get("military_loyalty_state") if isinstance(formation.get("military_loyalty_state"), Mapping) else {}
        aggregate_bond = int(formation_loyalty.get("house_patron_bonds", {}).get(patron_ref, 350)) if isinstance(formation_loyalty.get("house_patron_bonds"), Mapping) else 350
        current_bond = int(patron_bonds.get(patron_ref, max(300, aggregate_bond - 80)))
        patron_bonds[patron_ref] = _clamp(current_bond + 4)
        loyalty["state_ref"] = political_state_ref
        person["military_loyalty_state"] = loyalty
        self.put(path, person)

    def _materialize_emergent_officer(
        self,
        formation_ref: str,
        *,
        at: str,
        evidence_ref: str,
        alignment_ref: str,
        state_ref: str | None,
    ) -> str | None:
        _path, formation = self._load_formation(formation_ref)
        political_state = state_ref or self._formation_political_state_ref(formation)
        person_ref = super()._materialize_emergent_officer(
            formation_ref,
            at=at,
            evidence_ref=evidence_ref,
            alignment_ref=alignment_ref,
            state_ref=political_state,
        )
        if not person_ref or not political_state:
            return person_ref
        patron_ref = self._formation_patron_ref(formation)
        if not patron_ref:
            return person_ref
        person_path, person0 = self._exact_person(person_ref, active=False)
        person = copy.deepcopy(dict(person0))
        loyalty = self._personal_loyalty(person, political_state)
        formation_loyalty = formation.get("military_loyalty_state") if isinstance(formation.get("military_loyalty_state"), Mapping) else {}
        aggregate_bond = int(formation_loyalty.get("house_patron_bonds", {}).get(patron_ref, 500)) if isinstance(formation_loyalty.get("house_patron_bonds"), Mapping) else 500
        loyalty.setdefault("house_patron_bonds", {})[patron_ref] = _clamp(max(400, aggregate_bond))
        person["military_loyalty_state"] = loyalty
        self.put(person_path, person)
        return person_ref

    def evaluate_formation_allegiance(
        self,
        formation_ref: str,
        *,
        proposed_commander_ref: str | None,
        order_legitimacy_milli: int,
        immediate_officer_support_milli: int,
    ) -> dict[str, int]:
        """Resolve state, patron, commander, officer, and formation pulls separately."""
        _path, formation = self._load_formation(formation_ref)
        loyalty = formation.get("military_loyalty_state") if isinstance(formation.get("military_loyalty_state"), Mapping) else {}
        axes = loyalty.get("axes") if isinstance(loyalty.get("axes"), Mapping) else self._military_rules()["formation_loyalty"]["default_axes"]
        bonds = loyalty.get("commander_bonds") if isinstance(loyalty.get("commander_bonds"), Mapping) else {}
        commander = int(bonds.get(proposed_commander_ref, 250)) if proposed_commander_ref else 0
        patron_ref = self._formation_patron_ref(formation)
        patron_bonds = loyalty.get("house_patron_bonds") if isinstance(loyalty.get("house_patron_bonds"), Mapping) else {}
        patron = int(patron_bonds.get(patron_ref, 0)) if patron_ref else 0
        patron_leader = self._patron_leader_ref(patron_ref)
        patron_supports_proposed = bool(proposed_commander_ref and proposed_commander_ref in {patron_ref, patron_leader})
        rules = self._military_rules()["allegiance_resolution"]
        state_pull = int(axes.get("state_allegiance", 720)) * int(rules["state_weight"])
        institution_pull = int(axes.get("institutional_professional", 690)) * int(rules["institution_weight"])
        formation_pull = int(axes.get("formation_identity", 500)) * int(rules["formation_weight"])
        commander_pull = commander * int(rules["immediate_commander_weight"])
        officer_pull = _clamp(immediate_officer_support_milli) * int(rules["immediate_commander_weight"])
        legitimacy_pull = _clamp(order_legitimacy_milli) * int(rules["legitimacy_weight"])
        patron_pull = patron * int(rules.get("patron_weight", 180))
        disaffection = int(axes.get("disaffection", 180)) * abs(int(rules["disaffection_weight"]))
        obey_legal_raw = state_pull + institution_pull + legitimacy_pull + formation_pull // 2
        follow_commander_raw = commander_pull + officer_pull + formation_pull + disaffection
        if patron_supports_proposed:
            follow_commander_raw += patron_pull
        else:
            obey_legal_raw += patron_pull
        total = max(1, obey_legal_raw + follow_commander_raw)
        follow = _clamp(int(round(follow_commander_raw * 1000 / total)))
        legal = _clamp(1000 - follow)
        cohesion = _clamp(int(formation.get("cohesion", 50) or 50) * 10)
        fragmentation = _clamp(1000 - abs(legal - follow) - cohesion // 4)
        return {
            "state_obedience_milli": legal,
            "follow_proposed_commander_milli": follow,
            "fragmentation_risk_milli": fragmentation,
            "administrative_ownership_changed": 0,
        }

    # ------------------------------------------------------------------
    # Private/House instability routing
    # ------------------------------------------------------------------

    def _resolve_autonomous_desertion(self, formation_ref: str, state_ref: str, at: str) -> dict[str, Any] | None:
        try:
            path, formation0 = self._load_formation(formation_ref)
        except ValueError:
            return None
        formation = copy.deepcopy(dict(formation0))
        political_state = self._formation_political_state_ref(formation)
        if int(formation.get("personnel", 0)) <= 0 or (political_state and political_state != state_ref):
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
            result = self._apply_whole_follow(formation_ref, proposed_ref=leader_ref, crisis_ref=crisis_ref, action="desert", decisions=decisions, at=at)
        elif outcome == "remain_with_legal_authority":
            result = self._apply_whole_state(formation_ref, proposed_ref=leader_ref, crisis_ref=crisis_ref, action="desert", decisions=decisions, at=at)
        else:
            result = self._fragment_formation(formation_ref, proposed_ref=leader_ref, crisis_ref=crisis_ref, action="desert", estimate=estimate, decisions=decisions, at=at)
        history = copy.deepcopy(self.read("state/history/events/index.json"))
        history.setdefault("events", []).append({
            "event_id": crisis_ref,
            "kind": "autonomous_military_desertion_crisis",
            "at": at,
            "state_ref": state_ref,
            "administrative_owner_ref": formation.get("administrative_owner"),
            "patron_ref": self._formation_patron_ref(formation),
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
                f"The formation resolved as {result.get('outcome')}; state, patron, immediate-officer, and formation loyalties were resolved separately."
            )
            _event_owner_write(self, event_ref, {
                "event_ref": event_ref,
                "kind": "military_allegiance_crisis",
                "status": "triggered",
                "due_at": at,
                "triggered_at": at,
                "actor_ref": leader_ref,
                "target_ref": _PLAYER_REF,
                "process_kind": "autonomous_military_loyalty",
                "process_stage": str(result.get("outcome", "resolved")),
                "summary": summary,
                "delivery": _player_delivery(self, "urgent officer and formation report"),
            }, at, source_owner_ref=leader_ref)
            if getattr(self, "_pending_wake_created", None) is None:
                self._pending_wake_created = {
                    "wake_ref": f"wake.military_loyalty.{_digest([event_ref, at])}",
                    "kind": "campaign_event",
                    "at": at,
                    "campaign_event_ref": event_ref,
                    "reason": summary,
                    "target_host": getattr(self, "_active_host_id", None),
                    "event_id": getattr(self, "_active_event_id", None),
                }
        return result

    def _review_formation_attention(self, owner_ref: str, at: str) -> None:
        network = self._career_network()
        attention = [ref for ref in network.get("formation_attention", {}).get(owner_ref, []) if isinstance(ref, str)]
        if not attention:
            return
        rules = self._military_rules().get("autonomous_crisis", {})
        width = max(1, int(rules.get("review_slice_per_state_wake", 32)))
        cursors = network.setdefault("formation_attention_cursor", {})
        cursor = max(0, int(cursors.get(owner_ref, 0))) % len(attention)
        selected = [attention[(cursor + offset) % len(attention)] for offset in range(min(width, len(attention)))]
        cursors[owner_ref] = (cursor + len(selected)) % len(attention)
        self.put("state/military/career-network/index.json", network)
        for formation_ref in selected:
            try:
                _path, formation = self._load_formation(formation_ref)
            except ValueError:
                continue
            state_ref = self._formation_political_state_ref(formation)
            if state_ref:
                self._resolve_autonomous_desertion(formation_ref, state_ref, at)

    def _autonomy_house(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        super()._autonomy_house(host, occurrences, at)
        if occurrences > 0:
            self._review_formation_attention(str(host.get("owner_ref", "")), at)

    # ------------------------------------------------------------------
    # Player agency during NPC mutiny/desertion
    # ------------------------------------------------------------------

    def _prepare_following_people(
        self,
        formation_ref: str,
        *,
        proposed_ref: str,
        crisis_ref: str,
        decisions: Mapping[str, Mapping[str, Any]],
        at: str,
    ) -> None:
        _path, formation = self._load_formation(formation_ref)
        legal_ref = str(formation.get("administrative_owner", ""))
        for person_ref, row in decisions.items():
            if row.get("decision") != "follow":
                continue
            if person_ref == _PLAYER_REF and person_ref != proposed_ref:
                continue
            self._mark_person_alignment(
                person_ref,
                crisis_ref=crisis_ref,
                effective_ref=proposed_ref,
                legal_ref=legal_ref,
                decision="followed_proposed_alignment",
                at=at,
            )
        if proposed_ref not in decisions or decisions.get(proposed_ref, {}).get("decision") == "follow":
            self._mark_person_alignment(
                proposed_ref,
                crisis_ref=crisis_ref,
                effective_ref=proposed_ref,
                legal_ref=legal_ref,
                decision="proposed_alignment_leader",
                at=at,
            )

    def _apply_whole_follow(
        self,
        formation_ref: str,
        *,
        proposed_ref: str,
        crisis_ref: str,
        action: str,
        decisions: Mapping[str, Mapping[str, Any]],
        at: str,
    ) -> dict[str, Any]:
        self._prepare_following_people(formation_ref, proposed_ref=proposed_ref, crisis_ref=crisis_ref, decisions=decisions, at=at)
        path, formation0 = self._load_formation(formation_ref)
        formation = copy.deepcopy(dict(formation0))
        current = formation.get("commander_ref")
        if current == _PLAYER_REF and proposed_ref != _PLAYER_REF and decisions.get(_PLAYER_REF, {}).get("decision") == "player_decision_required":
            formation["commander_ref"] = None
            if int(formation.get("personnel", 0)) > 0:
                formation["status"] = "command_disputed"
            self.put(path, formation)
            self._release_commander_index(_PLAYER_REF, formation_ref)
        return super()._apply_whole_follow(
            formation_ref,
            proposed_ref=proposed_ref,
            crisis_ref=crisis_ref,
            action=action,
            decisions=decisions,
            at=at,
        )

    def _fragment_formation(
        self,
        formation_ref: str,
        *,
        proposed_ref: str,
        crisis_ref: str,
        action: str,
        estimate: Mapping[str, int],
        decisions: Mapping[str, Mapping[str, Any]],
        at: str,
    ) -> dict[str, Any]:
        self._prepare_following_people(formation_ref, proposed_ref=proposed_ref, crisis_ref=crisis_ref, decisions=decisions, at=at)
        return super()._fragment_formation(
            formation_ref,
            proposed_ref=proposed_ref,
            crisis_ref=crisis_ref,
            action=action,
            estimate=estimate,
            decisions=decisions,
            at=at,
        )


__all__ = ["MilitaryCareerFinalIntegrityMixin"]
