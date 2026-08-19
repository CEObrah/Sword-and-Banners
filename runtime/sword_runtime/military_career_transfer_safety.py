"""Transfer-safety and command-authority guards for military careers.

No transfer may stage a source detachment before force-ownership legality is
known. The same layer preserves all existing interstate config metadata while
filtering formations that no longer obey their administrative owner and ensures
formation-instability routing reflects the final corrected loyalty state.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from sword_runtime.military_career_service_authority import MilitaryCareerServiceAuthorityMixin


class MilitaryCareerTransferSafetyMixin(MilitaryCareerServiceAuthorityMixin):
    """Fail closed before consequential personnel writes and preserve command eligibility."""

    def _update_formation_loyalty(self, formation_ref: str, at: str) -> None:
        super()._update_formation_loyalty(formation_ref, at)
        try:
            _path, formation = self._load_formation(formation_ref)
        except (KeyError, ValueError, FileNotFoundError):
            return
        loyalty = formation.get("military_loyalty_state") if isinstance(formation, Mapping) and isinstance(formation.get("military_loyalty_state"), Mapping) else {}
        axes = loyalty.get("axes") if isinstance(loyalty.get("axes"), Mapping) else {}
        rules = self._military_rules().get("autonomous_crisis", {})
        unstable = (
            int(axes.get("disaffection", 0)) >= int(rules.get("disaffection_attention_milli", 760))
            and int(axes.get("state_allegiance", 1000)) <= int(rules.get("state_allegiance_attention_max_milli", 430))
            and int(axes.get("institutional_professional", 1000)) <= int(rules.get("institutional_loyalty_attention_max_milli", 460))
        )
        owner_ref = self._formation_attention_owner_ref(formation)
        if not owner_ref:
            return
        network = self._career_network()
        attention = network.setdefault("formation_attention", {}).setdefault(owner_ref, [])
        if unstable and formation_ref not in attention:
            attention.append(formation_ref)
            attention.sort()
        elif not unstable and formation_ref in attention:
            attention[:] = [ref for ref in attention if ref != formation_ref]
        self.put("state/military/career-network/index.json", network)

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
        _target_path, target = self._load_formation(target_formation_ref)
        target_force_ref = target.get("owner_force_ref")
        source_force_ref = None
        included = False

        if inherited_transfer is not None:
            source_force_ref = inherited_transfer.get("source_force_ref")
            included = bool(inherited_transfer.get("included_in_force_headcount", False))
        elif not already_detached:
            _person_path, person = self._exact_person(officer_ref, active=False)
            source_ref = source_formation_ref
            if source_ref is None:
                source_ref, _source = self._person_current_formation(person)
            if source_ref:
                try:
                    _source_path, source = self._load_formation(source_ref)
                    source_force_ref = source.get("owner_force_ref")
                except ValueError:
                    source_force_ref = None
                if isinstance(source_force_ref, str) and source_force_ref:
                    try:
                        force = self.read(self.owner_path(source_force_ref))
                    except (KeyError, ValueError, FileNotFoundError):
                        force = None
                    assignments = force.get("materialized_assignments") if isinstance(force, Mapping) else None
                    row = assignments.get(officer_ref) if isinstance(assignments, Mapping) else None
                    included = isinstance(row, Mapping) and str(row.get("formation_ref", "")) == source_ref

        if included and source_force_ref != target_force_ref:
            raise ValueError(
                "approved career movement crosses force ownership and needs a separate ownership/population transfer authority"
            )

        return super()._create_transfer_order(
            petition,
            target_formation_ref=target_formation_ref,
            at=at,
            request_kind=request_kind,
            already_detached=already_detached,
            source_formation_ref=source_formation_ref,
            inherited_transfer=inherited_transfer,
        )

    def _interstate_theater_config(self, base: Mapping[str, Any], *, at: str | None = None) -> dict[str, Any]:
        # Bypass only the service-authority projection wrapper so unrelated
        # civil-world config keys survive unchanged, then apply the same lawful
        # formation filter to the theater lists.
        config = copy.deepcopy(
            super(MilitaryCareerServiceAuthorityMixin, self)._interstate_theater_config(base, at=at)
        )
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
        config["theaters"] = rows
        return config


__all__ = ["MilitaryCareerTransferSafetyMixin"]
