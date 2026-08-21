"""Service-authority and personnel-transfer rules for the military career subsystem.

This overlay closes three cross-system gaps without creating new authorities:

* private/House officers require their actual service authority to release them
  before a state career petition may continue;
* carried field-ration shortages affect loyalty only while a formation is in a
  field/mobilized posture, while explicit starvation/history evidence still
  applies everywhere; and
* formations that have ceased obeying their administrative owner are removed
  from that owner's autonomous interstate force selection without changing
  administrative title, territorial title, or sovereignty.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.military_career_formation_dynamics import MilitaryCareerFormationDynamicsMixin
from sword_runtime.military_career_command_surface import _NONLEGAL_ALIGNMENT_STATUSES
from sword_runtime.military_career_loyalty import _clamp, _digest
from sword_runtime.sim.calendar import CampaignTime


class MilitaryCareerServiceAuthorityMixin(MilitaryCareerFormationDynamicsMixin):
    """Service-authority, personnel-transfer, and interstate eligibility rules."""

    # ------------------------------------------------------------------
    # Field supply is not the same thing as garrison subsistence.
    # ------------------------------------------------------------------

    def _update_formation_loyalty(self, formation_ref: str, at: str) -> None:
        super()._update_formation_loyalty(formation_ref, at)
        try:
            path, formation0 = self._load_formation(formation_ref)
        except (KeyError, ValueError, FileNotFoundError):
            return
        if not isinstance(formation0, Mapping):
            return
        formation = copy.deepcopy(dict(formation0))
        loyalty = formation.get("military_loyalty_state")
        if not isinstance(loyalty, dict):
            return
        axes = loyalty.get("axes")
        if not isinstance(axes, dict):
            return
        rules = self._military_rules()["formation_loyalty"]
        statuses = {str(value).lower() for value in rules.get("field_supply_penalty_statuses", [])}
        status = str(formation.get("status", "")).lower()
        operational = bool(formation.get("mobilized", False)) or status in statuses
        logistics = formation.get("logistics") if isinstance(formation.get("logistics"), Mapping) else {}
        personnel = max(1, int(formation.get("personnel", 1) or 1))
        food_kg = max(0, int(logistics.get("food_kg", 0) or 0))
        if not operational and food_kg < personnel * 2:
            # Base settlement deliberately interprets low carried stores as a
            # field-supply signal. Undo only that fixed increment in a non-field
            # posture. Explicit missed-pay/starvation/history events remain in
            # bounded memory and are not reversed here.
            penalty = int(rules.get("supply_shortage_disaffection_gain_milli", 0))
            axes["disaffection"] = _clamp(int(axes.get("disaffection", 0)) - penalty)
            loyalty["nonfield_supply_interpretation"] = "carried field ration level ignored outside field posture; explicit subsistence evidence remains authoritative"
        formation["military_loyalty_state"] = loyalty
        self.put(path, formation)

    # ------------------------------------------------------------------
    # Private/House service authority before state personnel authority.
    # ------------------------------------------------------------------

    def _target_service_authority(self, desired_commander_ref: str | None, state_ref: str) -> tuple[str | None, str | None]:
        if not desired_commander_ref:
            return None, None
        target_ref = self._commander_target_formation(desired_commander_ref, state_ref)
        if not target_ref:
            return None, None
        try:
            _path, formation = self._load_formation(target_ref)
        except ValueError:
            return None, None
        admin = formation.get("administrative_owner")
        return target_ref, (str(admin) if isinstance(admin, str) and admin else None)

    def _service_authority_release_score(self, petition: Mapping[str, Any]) -> int:
        officer_ref = str(petition.get("officer_ref", ""))
        service_ref = str(petition.get("service_authority_ref", ""))
        try:
            _path, person = self._exact_person(officer_ref, active=False)
        except ValueError:
            return 0
        preferences = self._career_preferences(person)
        loyalty = person.get("military_loyalty_state") if isinstance(person.get("military_loyalty_state"), Mapping) else {}
        patron = 0
        if service_ref.startswith("house_"):
            bonds = loyalty.get("house_patron_bonds") if isinstance(loyalty.get("house_patron_bonds"), Mapping) else {}
            patron = int(bonds.get(service_ref, 500))
        elif service_ref.startswith("char_"):
            bonds = loyalty.get("commander_bonds") if isinstance(loyalty.get("commander_bonds"), Mapping) else {}
            patron = int(bonds.get(service_ref, 500))
        formation_ref, formation = self._person_current_formation(person)
        del formation_ref
        disaffection = 180
        if isinstance(formation, Mapping):
            aggregate = formation.get("military_loyalty_state") if isinstance(formation.get("military_loyalty_state"), Mapping) else {}
            axes = aggregate.get("axes") if isinstance(aggregate.get("axes"), Mapping) else {}
            disaffection = int(axes.get("disaffection", disaffection))
        attraction = int(petition.get("attraction_milli", 0))
        raw = (
            attraction * 35 // 100
            + int(preferences.get("ambition", 500)) * 20 // 100
            + int(preferences.get("independence", 400)) * 15 // 100
            + int(preferences.get("advancement", 500)) * 15 // 100
            + disaffection * 20 // 100
            - patron * 20 // 100
            + 120
        )
        return _clamp(raw)

    def _review_service_authority(self, state_ref: str, at: str) -> None:
        index = self._petition_index()
        pending = list(index.get("pending_by_state", {}).get(state_ref, []))
        now = CampaignTime.parse(at)
        for petition_ref in pending:
            if not isinstance(petition_ref, str):
                continue
            path = self._petition_path(petition_ref)
            raw = self.read_optional(path)
            if not isinstance(raw, Mapping) or raw.get("status") != "submitted":
                continue
            due = CampaignTime.parse(str(raw.get("review_due_at", at)))
            if due > now:
                continue
            petition = copy.deepcopy(dict(raw))
            service_ref = petition.get("service_authority_ref")
            if not isinstance(service_ref, str) or not service_ref or service_ref == state_ref:
                continue
            decision = petition.get("service_authority_decision")
            if decision in {"approved_release", "approved_internal_reassignment"}:
                continue
            desired = petition.get("desired_commander_ref")
            target_ref, target_admin = self._target_service_authority(
                str(desired) if isinstance(desired, str) else None,
                state_ref,
            )
            if target_ref and target_admin == service_ref and str(petition.get("request_kind")) != "independent_command":
                petition["service_authority_decision"] = "approved_internal_reassignment"
                petition["service_authority_reviewed_at"] = at
                petition["status"] = "authorized_handoff"
                petition["institutional_decision"] = "approved_by_current_service_authority"
                petition["personnel_action_handoff"] = {
                    "required_authority_ref": service_ref,
                    "requested_action": petition["request_kind"],
                    "officer_ref": petition["officer_ref"],
                    "desired_commander_ref": desired,
                    "rule": "private/House service authority approved an internal reassignment; actual movement still uses conserved transfer authority",
                }
                self.put(path, petition)
                continue
            prior_reviews = max(0, int(petition.get("service_authority_review_count", 0)))
            response_rules = self._military_rules().get("institutional_response", {})
            repeat_gain = max(0, int(response_rules.get("service_authority_repeat_review_gain_milli", 30)))
            repeat_cap = max(0, int(response_rules.get("service_authority_repeat_review_cap_milli", 120)))
            score = _clamp(self._service_authority_release_score(petition) + min(repeat_cap, prior_reviews * repeat_gain))
            petition["service_authority_review_count"] = prior_reviews + 1
            petition["service_authority_score_milli"] = score
            petition["service_authority_reviewed_at"] = at
            if score >= 620:
                petition["service_authority_decision"] = "approved_release"
                # The political state may still approve, reject, redirect, or
                # offer an independent command. Release is not state approval.
                self.put(path, petition)
            elif score >= 500:
                petition["service_authority_decision"] = "delayed_release_review"
                petition["review_due_at"] = str(now.add_seconds(60 * 86400))
                self.put(path, petition)
            else:
                petition["service_authority_decision"] = "release_refused"
                petition["status"] = "rejected"
                petition["institutional_decision"] = "retained_by_current_service_authority"
                self.put(path, petition)

    def _settle_petitions(self, state_ref: str, at: str) -> None:
        self._review_service_authority(state_ref, at)
        super()._settle_petitions(state_ref, at)

    # ------------------------------------------------------------------
    # House-aware target choice while preferring state service for state petitions.
    # ------------------------------------------------------------------

    def _commander_target_formation(self, commander_ref: str, state_ref: str) -> str | None:
        candidates: list[tuple[int, int, str]] = []
        assignments = self._commander_index().get("assignments", {}).get(commander_ref, [])
        for formation_ref in assignments if isinstance(assignments, list) else []:
            if not isinstance(formation_ref, str):
                continue
            try:
                _path, formation = self._load_formation(formation_ref)
            except ValueError:
                continue
            if self._formation_political_state_ref(formation) != state_ref or int(formation.get("personnel", 0)) <= 0:
                continue
            admin = str(formation.get("administrative_owner", ""))
            candidates.append((0 if admin == state_ref else 1, -int(formation.get("personnel", 0)), formation_ref))
        if not candidates:
            network = self._career_network()
            dossier_path = network.get("commanders", {}).get(commander_ref)
            dossier = self.read_optional(dossier_path) if isinstance(dossier_path, str) else None
            formation_ref = dossier.get("formation_ref") if isinstance(dossier, Mapping) else None
            if isinstance(formation_ref, str):
                try:
                    _path, formation = self._load_formation(formation_ref)
                except ValueError:
                    formation = None
                if isinstance(formation, Mapping) and self._formation_political_state_ref(formation) == state_ref and int(formation.get("personnel", 0)) > 0:
                    admin = str(formation.get("administrative_owner", ""))
                    candidates.append((0 if admin == state_ref else 1, -int(formation.get("personnel", 0)), formation_ref))
        if not candidates:
            return None
        candidates.sort()
        return candidates[0][2]

    def _independent_command_vacancy(self, state_ref: str, officer_ref: str) -> str | None:
        # Independent *state* command still requires a state-owned formation.
        # This prevents a Qin career petition from assigning somebody to a
        # private House formation as though Qin owned it.
        return super()._independent_command_vacancy(state_ref, officer_ref)

    def _create_transfer_order(
        self,
        petition: Mapping[str, Any],
        *,
        target_formation_ref: str,
        at: str,
        request_kind: str | None = None,
        already_detached: bool = False,
        source_formation_ref: str | None = None,
        inherited_transfer: Mapping[str, Any] | None = None,
    ) -> str:
        officer_ref = str(petition["officer_ref"])
        person_path, person0 = self._exact_person(officer_ref, active=False)
        person = copy.deepcopy(dict(person0))
        _target_path, target = self._load_formation(target_formation_ref)
        state_ref = str(petition["state_ref"])
        if self._formation_political_state_ref(target) != state_ref:
            raise ValueError("career petition target lies outside its approved political-state context")
        source_ref = source_formation_ref
        if source_ref is None and not already_detached:
            source_ref, _source = self._person_current_formation(person)
        source_location = self._person_location(person)
        if not source_location and source_ref:
            try:
                _source_path, source = self._load_formation(source_ref)
            except ValueError:
                source = None
            if isinstance(source, Mapping):
                source_location = str(source.get("location_ref", "")) or None
        destination = str(target.get("location_ref", ""))
        if not source_location or not destination:
            raise ValueError("personnel transfer requires exact source and destination locations")
        hours = max(1, int(self._route_travel_hours(str(source_location), destination, modes=("horse", "foot"))))
        arrives_at = str(CampaignTime.parse(at).add_seconds(hours * 3600))
        transfer_info = dict(inherited_transfer or {})
        if not already_detached:
            transfer_info = self._detach_person_from_formation(officer_ref, source_ref, at, reason="approved military career transfer")
        source_force_ref = transfer_info.get("source_force_ref")
        included = bool(transfer_info.get("included_in_force_headcount", False))
        role = str(transfer_info.get("role", "command_personnel"))
        target_force_ref = target.get("owner_force_ref")
        if included and source_force_ref != target_force_ref:
            raise ValueError("approved career movement crosses force ownership and needs a separate ownership/population transfer authority")
        order_ref = f"military_personnel_transfer_{_digest([petition.get('petition_ref'), officer_ref, target_formation_ref, at, request_kind])}"
        order = {
            "schema": "sword-military-personnel-transfer",
            "owner_id": order_ref,
            "order_ref": order_ref,
            "petition_ref": str(petition.get("petition_ref", "")),
            "officer_ref": officer_ref,
            "state_ref": state_ref,
            "request_kind": str(request_kind or petition.get("request_kind", "permanent_transfer")),
            "desired_commander_ref": petition.get("desired_commander_ref"),
            "source_formation_ref": source_ref,
            "target_formation_ref": target_formation_ref,
            "source_force_ref": source_force_ref,
            "target_force_ref": target_force_ref,
            "included_in_force_headcount": included,
            "role": role,
            "source_location_ref": source_location,
            "destination_location_ref": destination,
            "departed_at": at,
            "arrives_at": arrives_at,
            "travel_hours": hours,
            "status": "in_transit",
        }
        path = self._transfer_order_path(order_ref)
        self.put(path, order)
        self._register_owner(order_ref, path)
        index = self._transfer_index()
        index.setdefault("orders", {})[order_ref] = path
        active = index.setdefault("active_by_state", {}).setdefault(state_ref, [])
        if order_ref not in active:
            active.append(order_ref)
            active.sort()
        self.put("state/military/personnel-transfers/index.json", index)
        person = copy.deepcopy(self.read(person_path))
        self._set_person_location(person, str(source_location))
        person["military_transfer_state"] = {
            "status": "in_transit",
            "order_ref": order_ref,
            "departed_at": at,
            "arrives_at": arrives_at,
            "destination_location_ref": destination,
        }
        self.put(person_path, person)
        self._schedule_transfer_host(order)
        return order_ref

    # ------------------------------------------------------------------
    # A mutinied/deserted formation cannot be reused by its legal owner as if
    # the crisis never happened. This changes operational obedience, not title.
    # ------------------------------------------------------------------

    @staticmethod
    def _formation_obeys_administrative_owner(formation: Mapping[str, Any]) -> bool:
        alignment = formation.get("military_allegiance_state")
        if not isinstance(alignment, Mapping):
            return True
        status = str(alignment.get("status", ""))
        if status not in _NONLEGAL_ALIGNMENT_STATUSES:
            return True
        legal = str(alignment.get("legal_administrative_owner_ref", formation.get("administrative_owner", "")))
        effective = str(alignment.get("effective_authority_ref", ""))
        return bool(effective and effective == legal)

    def _filter_obedient_formations(self, refs: Any) -> list[str]:
        result: list[str] = []
        for ref in refs if isinstance(refs, list) else []:
            if not isinstance(ref, str):
                continue
            try:
                _path, formation = self._load_formation(ref)
            except ValueError:
                continue
            if self._formation_obeys_administrative_owner(formation) and int(formation.get("personnel", 0)) > 0:
                result.append(ref)
        return result

    def _interstate_theater_config(self, base: Mapping[str, Any], *, at: str | None = None, include_expeditionary: bool = True) -> dict[str, Any]:
        config = copy.deepcopy(super()._interstate_theater_config(base, at=at, include_expeditionary=include_expeditionary))
        rows: list[dict[str, Any]] = []
        for raw in config.get("theaters", []) if isinstance(config, Mapping) else []:
            if not isinstance(raw, Mapping):
                continue
            row = copy.deepcopy(dict(raw))
            sides = [str(side) for side in row.get("sides", []) if isinstance(side, str)]
            lists = row.get("formation_ref_lists") if isinstance(row.get("formation_ref_lists"), Mapping) else {}
            primaries = row.get("formation_refs") if isinstance(row.get("formation_refs"), Mapping) else {}
            filtered: dict[str, list[str]] = {}
            valid = True
            for side in sides:
                refs = list(lists.get(side, [])) if isinstance(lists.get(side), list) else []
                if not refs:
                    primary = primaries.get(side)
                    refs = [str(primary)] if isinstance(primary, str) and primary else []
                refs = self._filter_obedient_formations(refs)
                if not refs:
                    valid = False
                    break
                filtered[side] = refs
            if not valid:
                continue
            row["formation_ref_lists"] = filtered
            row["formation_refs"] = {side: refs[0] for side, refs in filtered.items()}
            row["army_groups"] = {
                side: {"primary_ref": refs[0], "formation_refs": refs, "reserve_refs": refs[1:]}
                for side, refs in filtered.items()
            }
            rows.append(row)
        return {"theaters": rows}

    def _autonomy_interstate(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        # Existing active theaters can carry saved formation_groups that predate
        # the loyalty crisis. Remove only formations that no longer obey that
        # administrative owner. The exact formation remains in the world at its
        # saved location under unchanged legal ownership.
        try:
            path = self.owner_path(str(host["owner_ref"]))
            world0 = self.read(path)
        except (KeyError, ValueError, FileNotFoundError):
            world0 = None
        if isinstance(world0, Mapping):
            world = copy.deepcopy(dict(world0))
            changed = False
            theaters = world.get("theaters")
            if isinstance(theaters, MutableMapping):
                for record in theaters.values():
                    if not isinstance(record, MutableMapping):
                        continue
                    groups = record.get("formation_groups")
                    if not isinstance(groups, MutableMapping):
                        continue
                    for side, refs in list(groups.items()):
                        filtered = self._filter_obedient_formations(refs)
                        if filtered != refs:
                            groups[side] = filtered
                            changed = True
                    armies = record.get("army_groups")
                    if isinstance(armies, MutableMapping):
                        for side, refs in groups.items():
                            if not isinstance(refs, list) or not refs:
                                armies.pop(side, None)
                                continue
                            armies[side] = {"primary_ref": refs[0], "formation_refs": refs, "reserve_refs": refs[1:]}
                if changed:
                    self.put(path, world)
        super()._autonomy_interstate(host, occurrences, at)


__all__ = ["MilitaryCareerServiceAuthorityMixin"]
