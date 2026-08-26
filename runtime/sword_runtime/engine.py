from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from sword_runtime.commands import CommandEnvelope
from sword_runtime.command_authority import command_routing_from_groups, person_order_authority, primary_person_routing_from_groups, staff_routing_from_groups
from sword_runtime.anatomy import anatomy_activity_factor, apply_structural_injury_state, resolve_structural_injury
from sword_runtime.combat_capability import CombatCapabilityMixin
from sword_runtime.personal_combat import (
    PersonalCombatMixin,
    active_injury_rows,
    advance_injury_physiology,
    injury_physiology_snapshot,
    recover_injury_physiology,
    settle_injury_recovery_hours,
    sync_injury_record,
)
from sword_runtime.battle_trace import build_battle_causal_trace
from sword_runtime.battle_sustainment import (
    RULES_PATH as BATTLE_SUSTAINMENT_RULES_PATH,
    apply_role_absence,
    consume_frontline_ammunition,
    fatigue_gain_after_rotations,
    initialize_battle_sustainment,
    plan_hundred_sustainment_rotation,
)
from sword_runtime.siege_physics import (
    active_enclosure_ref, advance_enclosure_layer, apply_ram_damage, assault_access,
    build_hours, commit_active_layer_projection, engineering_blueprints,
    ensure_physical_state, initial_physical_state, ram_access, register_attacker_foothold,
    sync_integrity_projection, work_materials, work_record,
)
from sword_runtime.battlefield import OperationalBattlefieldMixin
from sword_runtime.cohort_tx_support import CohortTxSupportMixin
from sword_runtime.standing_force_capability import StandingForceCapabilityMixin
from sword_runtime.command_contracts import COMMAND_PAYLOAD_KEYS
from sword_runtime.development import age_years, annual_mortality_basis_points, deterministic_annual_mortality_roll, settle_combat_experience
from sword_runtime.house_lineage import ensure_house_lineage_representation, recompute_house_lineage, register_exact_house_lineage_member
from sword_runtime.house_emergence_index import record_house_emergence_candidate, remove_house_emergence_candidate
from sword_runtime.training_programs import formation_training_ref_for_role, REGISTRY_PATH as TRAINING_PROGRAM_REGISTRY_PATH, resolve_program_ref as resolve_training_program_ref, combat_skill_weights, combat_skill_weights_for_participant, registered_focus_drill_ref, settle_exact_registered_focus, settle_exact_program
from sword_runtime.training_instructors import exact_person_drill_access, instructor_contexts_for_program
from sword_runtime.training_time import compact_person_training_time_ledger
from sword_runtime.training_facilities import training_environment
from sword_runtime.military_supply import evaluate_military_supply, military_supply_sufficiency
from sword_runtime.mount_custody import (
    allocate_regional_horses_to_formation,
    force_role_horses,
    issue_force_role_horses_to_formation,
    record_formation_horse_losses,
    regional_horses,
    replace_formation_horse_allocations,
    return_formation_horses_to_regional_reserve,
    return_formation_horses_to_role_reserve,
)
from sword_runtime.morale import resolve_formation_morale
from sword_runtime.military_merit import battle_service_appraisal
from sword_runtime.military_doctrine import default_formation_doctrine_ref, doctrine_behavior
from sword_runtime.mercenary_contracts import (
    compact_mercenary_contracts,
    mercenary_has_live_contract,
    sync_mercenary_route,
)
from sword_runtime.fatigue import (
    RULES_PATH as FATIGUE_RULES_PATH,
    battle_person_fatigue_gain,
    settle_formation_idle_fatigue,
    settle_person_idle_fatigue,
    stamp_formation_activity_fatigue,
    stamp_person_activity_fatigue,
)
from sword_runtime.cohort_personnel import (
    add_recruits,
    append_formation_slices,
    ensure_cohort_ledger,
    ensure_formation_composition,
    merge_formation_slices,
    partition_formation_slices,
    record_formation_combat_experience,
    record_recruitment_cohort,
    release_external_formation_allocations,
    return_formation_slices,
    take_reserve_slices,
    trim_formation_to_personnel,
    validate_cohort_ledger,
    cohort_merged_skill_means,
)
from sword_runtime.unit_establishment import (
    establishment_composition,
    freeze_establishment_composition,
    normalize_formation_establishment,
    represented_establishment_composition,
    validate_establishment,
)
from sword_runtime.unit_duties import assign_phase_duties
from sword_runtime.semantic_validation import require_int, require_number, require_text, require_list
from sword_runtime.recruitment_campaigns import start_campaign, stage_campaign, train_campaign, finalize_campaign, cancel_campaign
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.person_location_index import sync_person_location, remove_person_location
from sword_runtime.faction_candidate_index import sync_alignment_candidate, remove_alignment_candidate
from sword_runtime.scheduler_frontier import mark_scheduler_dirty, set_causal_frontier
from sword_runtime.stat_access import merged_skill_map
from sword_runtime.support_tasks import (
    FORBIDDEN_PERMANENT_SUPPORT_ROLES,
    blueprint_difficulty,
    task_efficiency,
    task_leader_score,
    temporary_duty_personnel,
)
from sword_runtime.house_nobility import RULES_PATH as NOBILITY_RULES_PATH, apply_nobility_grant, ensure_nobility_state, grade_order
from sword_runtime.state_levy import call_state_levy, demobilize_state_levy, active_levy_formations
from sword_runtime.history_store import iter_history_events, write_history_index
from sword_runtime.officer_cadre import (
    develop_officer_cadre, ensure_officer_cadre, merge_officer_cadres,
    partition_officer_cadre, record_officer_cadre_combat_experience, reorganize_officer_cadre,
    settle_aggregate_officer_losses, unregister_materialized_rank,
)
from sword_runtime.officer_personnel import sync_materialized_officer_billets
from sword_runtime.operational_logistics import formation_movement_profile
from sword_runtime.person_lite_store import compact_person_lite_record, put_person_lite
from sword_runtime.geography import enclosing_fortification_site, shortest_path as geography_shortest_path
from sword_runtime.terrain import terrain_context_for_location, terrain_effects_for_tags, terrain_has, primary_terrain_tag, terrain_tokens
from sword_runtime.strategic_war_operations import (
    advance_autonomous_siege, commit_one_reserve_command, ensure_autonomous_siege,
    first_hostile_route_blocker, fortified_site_profile, redirect_blocked_front, war_fronts_resolved,
)
from sword_runtime.strategic_war_planning import build_interstate_strategic_plan, contingency_withdrawal_decision, integrate_reinforcement_reserves
from sword_runtime.store.overlay import StagedOverlay
from sword_runtime.store.json_fragments import assign_json_fragment, delete_json_fragment, select_json_fragment, split_json_fragment
from sword_runtime.store.repository import RepositoryStore
from sword_runtime.store.schema_validation import RegisteredSchemaValidator
from sword_runtime.tx.canonical import thaw_json
from sword_runtime.tx.coordinator import TransactionCoordinator, TransactionExecution
from sword_runtime.tx.git import GitStager
from sword_runtime.tx.receipts import ReceiptStore
from sword_runtime.tx.wal import WriteAheadLog


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _deepcopy(value: Any) -> Any:
    return copy.deepcopy(value)


def _fixed(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _pct(value: Any) -> float:
    x = _fixed(value, 0.0)
    return x / 100.0 if x > 1.0 else x


def _clamp(v: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, int(v)))


def _append_bounded(owner: dict[str, Any], key: str, row: Mapping[str, Any], *, limit: int) -> None:
    values = owner.setdefault(key, [])
    if not isinstance(values, list):
        values = []
        owner[key] = values
    values.append(_deepcopy(dict(row)))
    del values[:-max(1, int(limit))]


def _append_recent_unique_string(owner: dict[str, Any], key: str, value: str, *, limit: int) -> None:
    text = str(value).strip()
    if not text:
        return
    rows = [str(row) for row in owner.get(key, []) if isinstance(row, str) and row.strip()]
    rows = [row for row in rows if row != text]
    rows.append(text)
    owner[key] = rows[-max(1, int(limit)):]


def _compact_project_rows(rows: Any, *, terminal_limit: int = 16) -> list[Any]:
    """Keep every unresolved project and only a bounded recent terminal tail.

    Active/scheduled projects are current causal obligations. Completed/cancelled
    projects are historical evidence once their material effect has been written to
    the authoritative owner, so retaining an unlimited copy in every House or
    institution would make otherwise quiet campaigns grow forever.
    """
    if not isinstance(rows, list):
        return []
    terminal_statuses = {"completed", "cancelled", "failed", "abandoned"}
    terminal_indices = [
        idx for idx, row in enumerate(rows)
        if isinstance(row, Mapping) and str(row.get("status", "")) in terminal_statuses
    ]
    keep_terminal = set(terminal_indices[-max(0, int(terminal_limit)):]) if terminal_limit > 0 else set()
    return [
        row for idx, row in enumerate(rows)
        if not (isinstance(row, Mapping) and str(row.get("status", "")) in terminal_statuses)
        or idx in keep_terminal
    ]


@dataclass
class CommandPlan:
    transaction_id: str
    created_at: str
    writes: Dict[str, Optional[bytes]]
    result: Dict[str, Any]
    planning_reads: int
    validator: Any


COMMAND_TYPES = frozenset({
    "advance_time","scene_consequence","travel","individual_training","cohort_training",
    "health_injury","health_recovery","medical_treatment","relationship_change","recruitment","population_transfer",
    "command_group_action","command_group_train","commission_action","commitment_action","investigation_action",
    "recruitment_campaign_start","recruitment_campaign_stage","recruitment_campaign_train","recruitment_campaign_finalize","recruitment_campaign_cancel",
    "person_materialize","formation_create","formation_reconstitute","formation_split","formation_merge",
    "formation_dissolve","formation_assign","force_assignment","formation_move","formation_train","formation_equipment_repair",
    "formation_mobilize","formation_demobilize","formation_doctrine_set","formation_training_set",
    "command_assign","command_transfer","resupply","battle_resolve","battlefield_control","personal_combat","recover_projectiles","operation_create",
    "operation_transition","information_create","information_deliver","institution_project","house_action",
    "state_action","state_levy_call","state_levy_demobilize","polity_action","market_purchase","economy_transfer","enlisted_service_pay","fortification_materialize",
    "siege_start","siege_action","territorial_consequence","family_event",
    "equipment_equip","equipment_unequip","equipment_transfer","equipment_issue","equipment_return","equipment_drop","equipment_loot","equipment_consume","market_sell",
    "reputation_event","career_event","mercenary_contract","organization_action","project_resolve","project_cancel","strategic_crossing_action","settlement_civic_action","fortification_logistics","custody_action"
})

_STATE_INSTITUTION_PROFILE_PATH = "game/data/politics/state-institution-profiles.json"

_INSTITUTION_PROFILED_STATIC_KEYS = frozenset({
    "name",
    "kind",
    "state",
    "location_ref",
    "geography",
    "operating_contract",
    "policy",
    "service_region_refs",
    "staffing",
    "linked_force_ref",
    "linked_depot_ref",
    "linked_mount_pool_ref",
    "linked_population_ref",
    "fortification_profile_authority",
})

_HOT_STATE_EXPLANATION_KEYS = frozenset({
    "rule",
    "note",
    "notes",
    "representation_rule",
    "scope_rule",
    "shard_policy",
    "individualization_policy",
    "generated_from_current_source",
    "universe_notes",
    "appearance_source",
    "birth_date_source",
    "source_class",
    "baseline_ref",
    "migration_note",
    "migration_notes",
    # Static/derivable model commentary. The schema, game data, and runtime
    # functions already define these semantics; repeating prose or policy in
    # every mutable owner only bloats the save and creates drift risk.
    "personnel_representation",
    "representation_policy",
    "personnel_conservation_rule",
    "establishment_rule",
    "subordinate_registry_rule",
    "subordinate_registry_kind",
    "manpower_semantics",
    "capacity_rule",
    "classification_rule",
    "authority_rule",
    "tracking_baseline",
    "last_decision",
    "reserve_doctrine",
    "staffing_policy",
    "command_accounting",
    "routine_support_functions",
    "narration_priority",
    "current_goal",
    "derived_activity_contract",
    "capability_evidence",
    "source_owner_kind",
    # Write-only replay/audit tails. Current owners already contain the settled
    # material result; durable campaign chronology lives in the semantic event
    # store and transaction layer rather than being copied into every owner.
    "delegated_training_last_officer_results",
    "equipment_issue_history",
    "field_supply_issue_history",
    "recruitment_history",
    "economic_history",
    "stage_history",
    "local_return_history",
    "promotion_history",
    "transfer_history",
    "reconstitution_history",
    "command_attachment_casualty_history",
    "casualty_history",
    "movement_history",
    "damage_history",
    "consumption_history",
    "delay_history",
    "captured_cargo_history",
    "battlefield_history",
    "work_history",
    "development_branches",
    "resolution_basis",
    "cancellation_basis",
})


def _compact_hot_state_value(value: Any, *, training_through: str | CampaignTime | None = None) -> Any:
    """Remove non-mechanical explanation/provenance commentary from hot state.

    Git and static game data own implementation history and policy prose. Mutable
    campaign owners persist current facts, conserved links, active process state,
    and compact accumulators only.
    """
    if isinstance(value, dict):
        source = compact_person_lite_record(value) if str(value.get("schema", "")) == "person-lite" else value
        if str(source.get("schema", "")) in {"sword-institution", "sword-house"} and isinstance(source.get("projects"), list):
            source = dict(source)
            source["projects"] = _compact_project_rows(source.get("projects"), terminal_limit=16)
        dev = source.get("development_state") if isinstance(source, Mapping) else None
        if training_through is not None and isinstance(dev, Mapping) and isinstance(dev.get("training_time_ledger"), Mapping):
            source = compact_person_training_time_ledger(source, through=training_through)
        profiled_institution = (
            str(source.get("schema", "")) == "sword-institution"
            and isinstance(source.get("profile_ref"), str)
            and bool(source.get("profile_ref"))
        )
        return {
            key: _compact_hot_state_value(item, training_through=training_through)
            for key, item in source.items()
            if key not in _HOT_STATE_EXPLANATION_KEYS
            and not (profiled_institution and key in _INSTITUTION_PROFILED_STATIC_KEYS)
        }
    if isinstance(value, list):
        return [_compact_hot_state_value(item, training_through=training_through) for item in value]
    return value


class RepositoryCommandPlanner(OperationalBattlefieldMixin, CohortTxSupportMixin, PersonalCombatMixin, CombatCapabilityMixin, StandingForceCapabilityMixin):
    INTERNAL_ACTOR = "internal:sword-autonomy"
    PLAYER_ACTOR = "char_tang_wei"

    def __init__(self, root: object) -> None:
        self.store = RepositoryStore(root)
        self.root = self.store.root
        self.schema_validator = RegisteredSchemaValidator.optional(self.store)
        self._reads: set[str] = set()
        self._cache: Dict[str, Any] = {}
        self._writes: Dict[str, Any] = {}
        self._deletes: set[str] = set()
        self._geography_route_epoch = 0
        self._geography_route_graph_cache: Dict[tuple[Any, ...], Any] = {}
        self._training_instructor_pool_cache: Dict[tuple[Any, ...], Any] = {}
        self._geography_path_cache: Dict[tuple[Any, ...], Any] = {}

    def _reset(self) -> None:
        self._reads = set()
        self._cache = {}
        self._writes = {}
        self._deletes = set()
        self._geography_route_epoch = 0
        self._geography_route_graph_cache = {}
        self._training_instructor_pool_cache = {}
        self._geography_path_cache = {}

    def _expand_profiled_state(self, value: Any) -> Any:
        if not isinstance(value, dict) or str(value.get("schema", "")) != "sword-institution":
            return value
        profile_ref = value.get("profile_ref")
        if not isinstance(profile_ref, str) or not profile_ref:
            return value
        registry = self.read(_STATE_INSTITUTION_PROFILE_PATH)
        profiles = registry.get("profiles", {}) if isinstance(registry, Mapping) else {}
        profile = profiles.get(profile_ref) if isinstance(profiles, Mapping) else None
        if not isinstance(profile, Mapping):
            raise ValueError(f"unknown institution profile: {profile_ref}")
        expanded = copy.deepcopy(dict(profile))
        expanded.update(copy.deepcopy(value))
        return expanded

    def read(self, path: str) -> Any:
        base_path, tokens = split_json_fragment(path)
        if base_path in self._writes:
            if not tokens:
                return self._writes[base_path]
            try:
                return self._expand_profiled_state(select_json_fragment(self._writes[base_path], tokens))
            except KeyError as exc:
                raise FileNotFoundError(path) from exc
        if path in self._cache:
            return self._cache[path]
        self._reads.add(base_path)
        value = self._expand_profiled_state(self.store.read_json(path))
        self._cache[path] = value
        return value

    def read_optional(self, path: str) -> Any:
        base_path, tokens = split_json_fragment(path)
        if base_path in self._writes:
            if not tokens:
                return self._writes[base_path]
            try:
                return self._expand_profiled_state(select_json_fragment(self._writes[base_path], tokens))
            except KeyError:
                return None
        if path in self._cache:
            return self._cache[path]
        self._reads.add(base_path)
        if tokens:
            try:
                value = self.store.read_json(path)
            except FileNotFoundError:
                self._cache[path] = None
                return None
            value = self._expand_profiled_state(value)
            self._cache[path] = value
            return value
        raw = self.store.read_optional_bytes(base_path)
        if raw is None:
            self._cache[path] = None
            return None
        value = self._expand_profiled_state(json.loads(raw.decode("utf-8")))
        self._cache[path] = value
        return value

    def put(self, path: str, value: Any) -> None:
        base_path, tokens = split_json_fragment(path)
        if base_path in {
            "state/territory/control.json",
            "state/geography/strategic-crossings.json",
            "state/geography/dynamic.json",
        }:
            self._geography_route_epoch = int(getattr(self, "_geography_route_epoch", 0)) + 1
            cache = getattr(self, "_geography_route_graph_cache", None)
            if isinstance(cache, dict):
                cache.clear()
            path_cache = getattr(self, "_geography_path_cache", None)
            if isinstance(path_cache, dict):
                path_cache.clear()
        # Hot-state compaction is a serialization concern, not a domain reducer.
        # Rewalking a large force/formation/house owner on every intermediate put
        # makes long-horizon training/autonomy cost scale with write amplification.
        # All state owners are compacted once at the final preview serialization
        # boundary before schema/invariant validation and commit.
        compact_now = False
        if not tokens:
            stored_value = value
            self._writes[base_path] = stored_value
            self._deletes.discard(base_path)
            self._cache.pop(base_path, None)
            if (base_path == "state/player.json" or base_path.startswith("state/char/")) and isinstance(stored_value, Mapping):
                person_ref = str(stored_value.get("owner_id", ""))
                if person_ref.startswith("char_"):
                    sync_person_location(self, person_ref=person_ref, person=stored_value)
                    sync_alignment_candidate(self, member_ref=person_ref, member_kind="person", doc=stored_value)
            elif base_path.startswith("state/houses/") and isinstance(stored_value, Mapping):
                house_ref = str(stored_value.get("owner_id", stored_value.get("house_ref", "")))
                if house_ref.startswith("house_"):
                    sync_alignment_candidate(self, member_ref=house_ref, member_kind="house", doc=stored_value)
            return
        base_value = copy.deepcopy(self._writes[base_path]) if base_path in self._writes else copy.deepcopy(self.read(base_path))
        assign_json_fragment(base_value, tokens, value)
        if compact_now:
            base_value = _compact_hot_state_value(base_value)
        self._writes[base_path] = base_value
        self._deletes.discard(base_path)
        self._cache.pop(base_path, None)
        try:
            self._cache[path] = select_json_fragment(base_value, tokens)
        except KeyError:
            self._cache.pop(path, None)

    def delete(self, path: str) -> None:
        base_path, tokens = split_json_fragment(path)
        if base_path in {
            "state/territory/control.json",
            "state/geography/strategic-crossings.json",
            "state/geography/dynamic.json",
        }:
            self._geography_route_epoch = int(getattr(self, "_geography_route_epoch", 0)) + 1
            cache = getattr(self, "_geography_route_graph_cache", None)
            if isinstance(cache, dict):
                cache.clear()
            path_cache = getattr(self, "_geography_path_cache", None)
            if isinstance(path_cache, dict):
                path_cache.clear()
        if not tokens:
            if base_path == "state/player.json" or base_path.startswith("state/char/"):
                prior = self.read_optional(base_path)
                if isinstance(prior, Mapping):
                    person_ref = str(prior.get("owner_id", ""))
                    if person_ref.startswith("char_"):
                        remove_person_location(self, person_ref)
                        remove_alignment_candidate(self, person_ref)
            elif base_path.startswith("state/houses/"):
                prior = self.read_optional(base_path)
                if isinstance(prior, Mapping):
                    house_ref = str(prior.get("owner_id", prior.get("house_ref", "")))
                    if house_ref.startswith("house_"):
                        remove_alignment_candidate(self, house_ref)
            self._writes.pop(base_path, None)
            self._deletes.add(base_path)
            self._cache.pop(base_path, None)
            return
        base_value = copy.deepcopy(self._writes[base_path]) if base_path in self._writes else copy.deepcopy(self.read(base_path))
        delete_json_fragment(base_value, tokens)
        self._writes[base_path] = base_value
        self._deletes.discard(base_path)
        self._cache.pop(base_path, None)
        self._cache.pop(path, None)

    def owner_path(self, owner_ref: str) -> str:
        idx = self.read("state/index/owner-index.json")
        path = idx.get("owners", {}).get(owner_ref)
        if not isinstance(path, str):
            raise ValueError("unknown authoritative owner: %s" % owner_ref)
        return path

    def owner(self, owner_ref: str) -> tuple[str, Any]:
        path = self.owner_path(owner_ref)
        return path, self.read(path)

    @staticmethod
    def _state_key(value: str) -> str:
        v = str(value).lower().replace("state_", "").replace("population_", "")
        if v not in {"qin", "zhao", "chu", "wei", "han", "yan", "qi"}:
            raise ValueError("unknown Warring States polity: %s" % value)
        return v

    def _authorize(self, command: CommandEnvelope) -> None:
        if command.mode == "ooc":
            raise ValueError("OOC is read-only and may not execute a transaction")
        if command.actor_id == self.INTERNAL_ACTOR:
            if command.mode != "autonomous":
                raise ValueError("internal actor must use autonomous mode")
            return
        if command.actor_id != self.PLAYER_ACTOR:
            raise PermissionError("gameplay actor identity is fixed by campaign authority")
        if command.mode != "gameplay":
            raise PermissionError("player-facing actors may only use gameplay mode")

    def _write_meta(self, command: CommandEnvelope, world_time: Optional[str] = None) -> None:
        meta = _deepcopy(self.read("state/meta.json"))
        meta["revision"] = command.expected_revision + 1
        if world_time is not None:
            meta["time"] = world_time
        self.put("state/meta.json", meta)

    def _result(self, **kwargs: Any) -> Dict[str, Any]:
        out = {"planning_reads": len(self._reads)}
        out.update(kwargs)
        return out

    def _validator(self, overlay: StagedOverlay, manifest: Any) -> None:
        if self.schema_validator is not None:
            self.schema_validator.validate_overlay(overlay, manifest.paths)
        self._validate_invariants(overlay, manifest.paths)

    def _validate_invariants(self, overlay: StagedOverlay, paths: Iterable[str]) -> None:
        meta = overlay.read_json("state/meta.json")
        if meta.get("game") != "sword_and_banners":
            raise ValueError("wrong game authority")
        rt = overlay.read_json("state/runtime.json") if overlay.read_optional_bytes("state/runtime.json") else None
        if isinstance(rt, dict):
            metrics = rt.get("metrics", {})
            for key in ("global_person_scans", "global_faction_scans", "global_force_scans", "global_house_scans"):
                if int(metrics.get(key, 0)) != 0:
                    raise ValueError("global polling is forbidden: %s" % key)
        # Validate only directly affected state/military owners, never scan directories.
        touched_states: set[str] = set()
        for path in paths:
            for prefix in ("state/population/", "state/forces/", "state/states/", "state/mounts/"):
                if path.startswith(prefix):
                    name = Path(path).stem.replace("state-", "")
                    if name in {"qin","zhao","chu","wei","han","yan","qi"}:
                        touched_states.add(name)
        for state in touched_states:
            pp = f"state/population/{state}.json"
            if overlay.read_optional_bytes(pp):
                pop = overlay.read_json(pp)
                if sum(int(v) for v in pop.get("strata", {}).values()) != int(pop.get("population_total", -1)):
                    raise ValueError("population conservation failed for %s" % state)
            fp = f"state/forces/state-{state}.json"
            if overlay.read_optional_bytes(fp):
                force = overlay.read_json(fp)
                available_by_role = {str(k): int(v) for k, v in force.get("available_by_role", {}).items()}
                available = sum(available_by_role.values())
                by_location: Dict[str, int] = {}
                for pool in force.get("available_by_location", {}).values():
                    if isinstance(pool, dict):
                        for role, count in pool.items():
                            by_location[str(role)] = int(by_location.get(str(role), 0)) + int(count)
                if by_location and by_location != available_by_role:
                    raise ValueError("force location-aware reserve conservation failed for %s" % state)
                allocated = sum(int(v.get("personnel", 0)) if isinstance(v, dict) else int(v) for v in force.get("allocated_to_formations", {}).values())
                external_allocated = sum(
                    max(0, int(count))
                    for roles in force.get("external_personnel_allocations", {}).values()
                    if isinstance(roles, Mapping)
                    for count in roles.values()
                ) if isinstance(force.get("external_personnel_allocations"), Mapping) else 0
                assignments = force.get("materialized_assignments", {})
                assigned_refs = {
                    str(person_ref)
                    for person_ref, assignment in assignments.items()
                    if isinstance(assignment, Mapping) and str(assignment.get("formation_ref", ""))
                } if isinstance(assignments, Mapping) else set()
                people = force.get("materialized_people", {})
                materialized = sum(
                    int(value.get("personnel", 1)) if isinstance(value, Mapping) else int(value)
                    for person_ref, value in people.items()
                    if str(person_ref) not in assigned_refs
                ) if isinstance(people, Mapping) else 0
                if available + allocated + external_allocated + materialized != int(force.get("headcount", -1)):
                    raise ValueError("force conservation failed for %s" % state)
            mp = f"state/mounts/{state}.json"
            if overlay.read_optional_bytes(mp):
                mounts = overlay.read_json(mp)
                if sum(int(v) for v in mounts.get("types", {}).values()) != int(mounts.get("total", -1)):
                    raise ValueError("mount type conservation failed for %s" % state)
                if sum(int(v) for v in mounts.get("health", {}).values()) != int(mounts.get("total", -1)):
                    raise ValueError("mount health conservation failed for %s" % state)

    def _formation_path(self, ref: str) -> str:
        idx = self.read("state/index/owner-index.json")
        p = idx.get("owners", {}).get(ref)
        if isinstance(p, str):
            return p
        p = f"state/formations/{ref.replace('formation_','').replace('_','-')}.json"
        if self.read_optional(p) is not None:
            return p
        raise ValueError("unknown formation: %s" % ref)

    def _load_formation(self, ref: str) -> tuple[str, Any]:
        p = self._formation_path(ref)
        return p, self.read(p)

    def _register_owner(self, owner_id: str, path: str) -> None:
        idx = _deepcopy(self.read("state/index/owner-index.json"))
        owners = idx.setdefault("owners", {})
        if owner_id in owners and owners[owner_id] != path:
            raise ValueError("duplicate mutable authority: %s" % owner_id)
        owners[owner_id] = path
        self.put("state/index/owner-index.json", idx)

    def _unregister_owner(self, owner_id: str) -> None:
        idx = _deepcopy(self.read("state/index/owner-index.json"))
        idx.get("owners", {}).pop(owner_id, None)
        self.put("state/index/owner-index.json", idx)

    def _formation_location_index(self) -> Dict[str, Any]:
        path="state/index/location-formation-index.json"
        return _deepcopy(self.read_optional(path) or {"schema":"sword-location-formation-index","authority":False,"locations":{},"rule":"Derived routing only. Exact formation documents remain authority."})

    def _index_formation_location(self, formation_ref: str, old_location: Optional[str], new_location: Optional[str]) -> None:
        idx=self._formation_location_index(); locations=idx.setdefault("locations",{})
        if old_location:
            refs=locations.setdefault(str(old_location),[])
            locations[str(old_location)]=[x for x in refs if str(x)!=str(formation_ref)]
            if not locations[str(old_location)]: locations.pop(str(old_location),None)
        if new_location:
            refs=locations.setdefault(str(new_location),[])
            if str(formation_ref) not in refs: refs.append(str(formation_ref)); refs.sort()
        self.put("state/index/location-formation-index.json",idx)

    def _formations_at(self, location_ref: str) -> list[str]:
        return [str(x) for x in self._formation_location_index().get("locations",{}).get(str(location_ref),[])]

    def _ensure_person_life_host(self, person_ref: str, born_at: Optional[CampaignTime] = None) -> None:
        """Register one bounded annual causal host for an exact person.

        Births/materializations must enter the same causal scheduler as baseline named
        people.  This is a direct keyed runtime mutation, never a scan of state/char.
        """
        rt = _deepcopy(self.read("state/runtime.json"))
        host_id = "host_person_" + str(person_ref).replace("char_", "").replace(".", "_").replace("-", "_")
        if host_id in rt.setdefault("hosts", {}):
            return
        current = born_at or CampaignTime.parse(str(rt["world_time"]))
        due = current.add_seconds(31536000)
        rt["hosts"][host_id] = {
            "kind": "person",
            "owner_ref": str(person_ref),
            "recurrence_seconds": 31536000,
            "next_due": str(due),
            "resolved_through": str(current),
            "safe_through": str(due.add_seconds(-1)),
            "quiet_run_count": 0,
        }
        rt.setdefault("events", []).append({
            "event_id": f"event_{host_id}_review",
            "kind": "person_life_review",
            "priority": 95,
            "target_host": host_id,
            "due_at": str(due),
        })
        self.put("state/runtime.json", rt)

    def _actor_authority(self, actor_ref: str) -> Mapping[str, Any]:
        ref = f"authority_{actor_ref}"
        path = self.owner_path(ref)
        doc = self.read(path)
        if doc.get("actor_ref") != actor_ref:
            raise PermissionError("actor authority record does not match gameplay actor")
        return doc

    def _has_role_capability(self, actor_ref: str, authority_ref: str, capability: str) -> bool:
        doc = self._actor_authority(actor_ref)
        for role in doc.get("roles", []):
            if role.get("authority_ref") != authority_ref:
                continue
            caps = role.get("capabilities", [])
            if capability in caps or "*" in caps:
                return True
        return False

    def _state_capabilities(self, actor_ref: str, state: str) -> set[str]:
        state = self._state_key(state)
        caps: set[str] = set()
        if self._has_role_capability(actor_ref, f"state_{state}", "state_command"):
            caps.add("*")
        doc = self.read(f"state/states/{state}.json")
        for appointment in doc.get("appointments", {}).values():
            if isinstance(appointment, str):
                # Bare identity entries do not grant a blanket capability.
                continue
            if not isinstance(appointment, dict) or appointment.get("person_ref") != actor_ref:
                continue
            caps.update(str(x) for x in appointment.get("capabilities", []))
        return caps

    def _require_state_authority(self, actor_ref: str, state: str, capability: str) -> None:
        caps = self._state_capabilities(actor_ref, state)
        if "*" not in caps and capability not in caps:
            raise PermissionError(
                f"{actor_ref} lacks saved {capability} authority for state_{self._state_key(state)}"
            )

    def _require_house_authority(self, actor_ref: str, house_ref: str, capability: str) -> None:
        if not self._has_role_capability(actor_ref, house_ref, capability):
            raise PermissionError(f"{actor_ref} lacks saved {capability} authority for {house_ref}")

    def _require_institution_authority(self, actor_ref: str, institution_ref: str, capability: str) -> None:
        if self._has_role_capability(actor_ref, institution_ref, capability):
            return
        _, inst = self.owner(institution_ref)
        state = inst.get("state")
        if state:
            self._require_state_authority(actor_ref, str(state), capability)
            return
        raise PermissionError(f"{actor_ref} lacks saved {capability} authority for {institution_ref}")

    def _has_formation_authority(self, actor_ref: str, formation_ref: str, capability: str = "formation_command") -> bool:
        _, formation = self._load_formation(formation_ref)
        if formation.get("command_authority") == actor_ref or formation.get("administrative_owner") == actor_ref:
            return True
        force_ref = str(formation.get("owner_force_ref", ""))
        if force_ref and self._has_role_capability(actor_ref, force_ref, capability):
            return True
        admin = str(formation.get("administrative_owner", ""))
        if admin.startswith("house_") and self._has_role_capability(actor_ref, admin, capability):
            return True
        return False

    def _require_formation_authority(self, actor_ref: str, formation_ref: str, capability: str = "formation_command") -> None:
        if not self._has_formation_authority(actor_ref, formation_ref, capability):
            raise PermissionError(f"{actor_ref} lacks saved {capability} authority for {formation_ref}")

    def _has_formation_operational_authority(self, actor_ref: str, formation_ref: str) -> bool:
        """Return whether an actor may issue operational orders to a formation.

        Direct formation/administrative authority remains sufficient. Otherwise
        resolve the formation's exact command-group route and use the registered
        recursive command/staff authority policy. This lets a superior
        commander's Strategist address every descendant while confining a nested
        army Strategist to that nested subtree.
        """
        try:
            if self._has_formation_authority(actor_ref, formation_ref):
                return True
        except (FileNotFoundError, KeyError, ValueError):
            # Exact staff may have no separate authority_* owner. Their staff
            # appointment is sufficient evidence for scoped order authority.
            pass
        try:
            index = self.read("state/cmd/command-groups/index.json")
        except (FileNotFoundError, KeyError, ValueError):
            return False
        primary = index.get("primary_formation_group") if isinstance(index, Mapping) else None
        group_ref = primary.get(formation_ref) if isinstance(primary, Mapping) else None
        if not isinstance(group_ref, str) or not group_ref:
            return False
        try:
            authority = person_order_authority(self.read, person_ref=actor_ref, target_group_ref=group_ref)
        except (FileNotFoundError, KeyError, ValueError):
            return False
        return bool(authority.get("allowed"))

    def _require_formation_operational_authority(self, actor_ref: str, formation_ref: str) -> None:
        if not self._has_formation_operational_authority(actor_ref, formation_ref):
            raise PermissionError(f"{actor_ref} lacks operational command authority for {formation_ref}")

    def _require_commandable_person(self, actor_ref: str, person_ref: str, formation_ref: str) -> None:
        """Prove that a proposed exact commander is actually subject to the actor's command.

        Authority over a formation is not authority over arbitrary named people. Gameplay
        may appoint the player, retain an already-lawful commander, or appoint an exact
        person whose saved service record binds them to Tang Wei's personal force.
        Autonomous/state actors use their separate runtime authority path.
        """
        if actor_ref == self.INTERNAL_ACTOR:
            return
        if person_ref == actor_ref:
            return
        _, formation = self._load_formation(formation_ref)
        if str(formation.get("commander_ref") or "") == person_ref:
            return
        _, person = self._exact_person(person_ref)
        affiliation = str(person.get("affiliation", "")).strip().lower()
        force = str(person.get("current_formation_id", "")).strip().lower()
        authority = str(person.get("authority", "")).strip().lower()
        loyalty = str(person.get("loyalty", "")).strip().lower()
        saved_retainer = (
            affiliation == "tang wei personal retinue"
            or force == "personal_force_tang_wei"
            or ("tang wei" in authority and ("retainer" in authority or "field commander" in authority or "guardian" in authority))
            or ("lifetime vow" in loyalty and "tang" in affiliation)
        )
        if not saved_retainer:
            raise PermissionError(f"{actor_ref} has no saved personnel authority over {person_ref}")

    def _commander_index(self) -> Dict[str, Any]:
        path = "state/index/commander-formation-index.json"
        return _deepcopy(self.read_optional(path) or {"schema":"sword-commander-formation-index","authority":False,"assignments":{}})

    def _assign_commander_index(self, commander_ref: str, formation_ref: str, *, replace: bool = False) -> None:
        idx = self._commander_index(); assignments = idx.setdefault("assignments", {})
        current = [str(x) for x in assignments.get(commander_ref, [])]
        other = [ref for ref in current if ref != formation_ref]
        if other and not replace:
            raise ValueError(f"exact commander {commander_ref} is already assigned to {other[0]}")
        if replace:
            current = [formation_ref]
        elif formation_ref not in current:
            current.append(formation_ref)
        assignments[commander_ref] = sorted(set(current))
        self.put("state/index/commander-formation-index.json", idx)

    def _release_commander_index(self, commander_ref: Optional[str], formation_ref: str) -> None:
        if not commander_ref:
            return
        idx = self._commander_index(); assignments = idx.setdefault("assignments", {})
        current = [str(x) for x in assignments.get(str(commander_ref), []) if str(x) != formation_ref]
        if current:
            assignments[str(commander_ref)] = current
        else:
            assignments.pop(str(commander_ref), None)
        self.put("state/index/commander-formation-index.json", idx)

    def _bind_formation_commander_sheet(
        self, commander_ref: str, formation_ref: str, formation: Mapping[str, Any],
        *, person_path: str | None = None, person: Dict[str, Any] | None = None,
    ) -> None:
        """Keep an individually represented commander sheet consistent with its live formation billet."""
        if person_path is None or person is None:
            person_path, person = self._command_person(str(commander_ref), active=False)
        else:
            person = _deepcopy(person)
        span = max(0, int(formation.get("personnel", 0) or 0))
        assignment = person.setdefault("command_assignment", {})
        if not isinstance(assignment, dict):
            assignment = {}; person["command_assignment"] = assignment
        assignment.update({
            "billet": "formation_commander",
            "formation_ref": str(formation_ref),
            "current_command_span": span,
            "external_to_fighting_establishment": True,
        })
        higher = formation.get("higher_command_ref")
        if isinstance(higher, str) and higher.startswith("cmdgrp."):
            assignment["command_group_ref"] = higher
        person["current_formation_id"] = str(formation_ref)
        location = formation.get("location_ref")
        if isinstance(location, str) and location:
            self._set_person_location(person, location)
        career = person.setdefault("career_state", {})
        if isinstance(career, dict):
            career["current_billet"] = "formation_commander"
            career["current_command_span"] = span
        military = person.setdefault("military_command", {})
        if isinstance(military, dict):
            military["formation_scope"] = str(formation_ref)
            military["external_to_fighting_strength"] = True
            if span >= 500:
                military["level"] = f"{span}_commander"
        self.put(person_path, person)

    def _unbind_formation_commander_sheet(self, commander_ref: str, formation_ref: str) -> None:
        """Clear one relieved formation billet without erasing unrelated command-group authority."""
        try:
            person_path, person = self._command_person(str(commander_ref), active=False)
        except (KeyError, ValueError, FileNotFoundError):
            return
        assignment = person.get("command_assignment") if isinstance(person.get("command_assignment"), dict) else None
        current = str(person.get("current_formation_id") or "")
        if not isinstance(assignment, dict) or str(assignment.get("formation_ref") or "") != str(formation_ref):
            if current == str(formation_ref):
                person.pop("current_formation_id", None); self.put(person_path, person)
            return
        assignment.pop("formation_ref", None)
        assignment["current_command_span"] = 0
        group_ref = assignment.get("command_group_ref")
        if isinstance(group_ref, str) and group_ref.startswith("cmdgrp."):
            assignment["billet"] = "command_group_commander"
        else:
            assignment.pop("command_group_ref", None)
            assignment["billet"] = "officer_reserve"
        if current == str(formation_ref): person.pop("current_formation_id", None)
        career = person.get("career_state")
        if isinstance(career, dict):
            career["current_billet"] = assignment["billet"]
            career["current_command_span"] = 0
        military = person.get("military_command")
        if isinstance(military, dict) and str(military.get("formation_scope") or "") == str(formation_ref):
            if isinstance(group_ref, str) and group_ref.startswith("cmdgrp."):
                military["formation_scope"] = group_ref
            else:
                military.pop("formation_scope", None)
        self.put(person_path, person)

    def _authorize_command(self, command: CommandEnvelope, payload: Mapping[str, Any]) -> None:
        if command.actor_id == self.INTERNAL_ACTOR:
            return
        actor = command.actor_id
        t = command.command_type

        if t == "relationship_change" and str(payload.get("source_ref", actor)) != actor:
            raise PermissionError("gameplay may mutate only relationships sourced by the player actor")

        if t in {"reputation_event", "career_event"}:
            raise PermissionError(f"{t} is a derived world consequence and cannot be directly authored by the player")
        if t == "mercenary_contract":
            self._require_house_authority(actor, "house_tang", "house_administration")
            if str(payload.get("action")) == "accept":
                raise PermissionError("mercenary acceptance is an autonomous company decision, not a player-authored outcome")
        if t in {"project_resolve", "project_cancel"}:
            self._require_institution_authority(actor, str(payload["institution_ref"]), "institution_administration")

        if t == "information_create":
            knowers = {str(x) for x in payload.get("knowers", [])}
            if knowers != {actor}:
                raise PermissionError("gameplay information creation may establish only the acting player's own knowledge; other exact people require lawful delivery")
        elif t == "information_deliver":
            ref = str(payload["information_ref"])
            path = self.read("state/information/index.json").get("claims", {}).get(ref)
            if not path:
                raise ValueError("unknown information claim")
            claim = self.read(path)
            if actor not in claim.get("knowers", []):
                raise PermissionError("actor may deliver only information they already know")

        if t in {"house_action", "family_event"}:
            self._require_house_authority(actor, str(payload.get("house_ref", "house_tang")), "house_administration")
            if t == "family_event" and str(payload.get("kind")) in {"pregnancy","birth","death","widowhood","succession_review"}:
                raise PermissionError("involuntary family life-course outcomes are runtime/internal consequences, not player-authored commands")
        elif t == "cohort_training":
            self._require_house_authority(actor, "house_tang", "house_training")

        if t == "polity_action":
            _pp, polity = self.owner(str(payload["polity_ref"]))
            house_ref = str(polity.get("sovereign_house_ref", ""))
            if not house_ref:
                raise PermissionError("sovereign polity is missing its exact House authority")
            self._require_house_authority(actor, house_ref, "house_administration")

        if t.startswith("recruitment_campaign_"):
            if actor != self.PLAYER_ACTOR:
                raise PermissionError("player recruitment campaigns are Tang Wei-owned administrative actions")
            if str(payload.get("destination_force_ref", "force_tang_wei_personal")) != "force_tang_wei_personal":
                raise PermissionError("player recruitment campaign may populate only Tang Wei's conserved personal force")

        state_capabilities = {
            "state_action": "state_command",
            "recruitment": "recruitment",
            "population_transfer": "population_administration",
            "person_materialize": "personnel_administration",
            "formation_create": "force_administration",
            "fortification_materialize": "fortification_administration",
            "enlisted_service_pay": "treasury_disbursement",
        }
        if t in state_capabilities:
            if t == "person_materialize" and payload.get("personal_force_ref"):
                raise PermissionError("personal-retinue materialization is an internal finalization of an already conserved cohort member, not a player-authored NPC outcome")
            if t == "formation_create" and payload.get("force_ref"):
                if str(payload.get("force_ref")) != "force_tang_wei_personal" or actor != self.PLAYER_ACTOR:
                    raise PermissionError("player may create a formation from only their own conserved personal force")
            else:
                self._require_state_authority(actor, str(payload.get("state", "qin")), state_capabilities[t])
        elif t == "economy_transfer" and payload.get("direction") != "player_to_state":
            self._require_state_authority(actor, str(payload.get("state", "qin")), "treasury_disbursement")

        formation_commands = {
            "formation_reconstitute", "formation_train", "formation_equipment_repair", "formation_mobilize", "formation_demobilize",
            "formation_doctrine_set", "formation_training_set", "formation_assign", "force_assignment",
            "command_assign", "command_transfer", "formation_move", "resupply", "formation_split",
            "formation_dissolve",
        }
        if t in formation_commands:
            formation_ref = str(payload["formation_ref"])
            if t == "formation_move":
                self._require_formation_operational_authority(actor, formation_ref)
            else:
                self._require_formation_authority(actor, formation_ref)
            if t in {"command_assign", "command_transfer", "formation_assign", "force_assignment"} and payload.get("commander_ref"):
                self._require_commandable_person(actor, str(payload["commander_ref"]), formation_ref)
        elif t == "formation_merge":
            refs = [str(x) for x in payload.get("formation_refs", [])]
            if not refs:
                raise ValueError("merge requires formations")
            for ref in refs:
                self._require_formation_authority(actor, ref)
        elif t == "battle_resolve":
            side = str(payload.get("controlled_side", "attacker"))
            key = "defender_formation_refs" if side == "defender" else "attacker_formation_refs"
            refs = [str(x) for x in payload.get(key, [])]
            if not refs:
                raise PermissionError("gameplay battle requires an explicitly controlled formation side")
            for ref in refs:
                self._require_formation_authority(actor, ref)
        elif t == "battlefield_control":
            action = str(payload.get("action", ""))
            if action == "record_terminal_evidence":
                if actor != self.INTERNAL_ACTOR:
                    raise PermissionError("field-battle terminal evidence is runtime/superior-command authority only")
            elif action in {"assign", "redeploy", "set_order"}:
                self._require_formation_operational_authority(actor, str(payload.get("formation_ref", "")))
            else:
                op_ref = str(payload.get("operation_ref", ""))
                op_path = self.read("state/operations/index.json").get("operations", {}).get(op_ref)
                if not op_path:
                    raise ValueError("unknown battlefield operation")
                op = self.read(op_path)
                refs = [str(ref) for ref in op.get("formation_refs", [])]
                if not refs or not any(self._has_formation_authority(actor, ref) for ref in refs):
                    raise PermissionError("battlefield control requires authority over at least one participating formation")
        elif t == "operation_create":
            for ref in payload.get("formation_refs", []):
                self._require_formation_authority(actor, str(ref))
        elif t == "operation_transition":
            op_ref = str(payload["operation_ref"])
            op_path = self.read("state/operations/index.json").get("operations", {}).get(op_ref)
            if not op_path:
                raise ValueError("unknown operation")
            op = self.read(op_path)
            for ref in op.get("formation_refs", []):
                self._require_formation_authority(actor, str(ref))
        elif t == "institution_project":
            self._require_institution_authority(actor, str(payload["institution_ref"]), "institution_administration")
        elif t == "siege_start":
            for ref in payload.get("attacker_formation_refs", []):
                self._require_formation_authority(actor, str(ref))
        elif t == "siege_action":
            ref = str(payload["siege_ref"])
            path = self.read("state/sieges/index.json").get("sieges", {}).get(ref)
            if not path:
                raise ValueError("unknown siege")
            siege = self.read(path)
            refs = list(siege.get("attacker_formation_refs", [])) + list(siege.get("defender_formation_refs", []))
            if refs and not any(self._has_formation_authority(actor, str(x)) for x in refs):
                raise PermissionError("actor lacks command authority over either side of the siege")
        elif t == "territorial_consequence":
            controller = str(payload.get("controller", ""))
            if controller.startswith("state_"):
                self._require_state_authority(actor, controller.replace("state_", ""), "territorial_administration")
            elif controller.startswith("polity_"):
                _polity_path, polity = self.owner(controller)
                house_ref = str(polity.get("sovereign_house_ref", ""))
                if not house_ref:
                    raise PermissionError("sovereign polity is missing its exact House authority")
                self._require_house_authority(actor, house_ref, "house_administration")

    @staticmethod
    def _scale_counts(values: Mapping[str, Any], target_total: int) -> Dict[str, int]:
        """Scale a role-count mapping to an exact target while preserving its mix.

        This is a representation helper only. It never creates personnel; reducers
        still debit each returned role from the exact conserved force owner.
        """
        target = max(0, int(target_total))
        source = {str(k): max(0, int(v)) for k, v in values.items() if max(0, int(v)) > 0}
        if target == 0:
            return {}
        source_total = sum(source.values())
        if source_total <= 0:
            raise ValueError("cannot scale an empty composition")
        rows = []
        assigned = 0
        for role in sorted(source):
            exact = source[role] * target / source_total
            base = int(math.floor(exact))
            rows.append((role, base, exact - base))
            assigned += base
        remainder = target - assigned
        rows.sort(key=lambda row: (-row[2], row[0]))
        out = {role: base for role, base, _ in rows}
        for role, _, _ in rows[:remainder]:
            out[role] += 1
        return {role: count for role, count in sorted(out.items()) if count > 0}

    @staticmethod
    def _partition_counts(values: Mapping[str, Any], take_total: int, population_total: int) -> tuple[Dict[str, int], Dict[str, int]]:
        if take_total < 0 or population_total <= 0 or take_total > population_total:
            raise ValueError("invalid proportional partition")
        keys = sorted(str(k) for k in values)
        source = {k: int(values.get(k, 0)) for k in keys}
        taken: Dict[str, int] = {}
        remaining_target = take_total
        remaining_population = population_total
        for i, key in enumerate(keys):
            count = source[key]
            if i == len(keys) - 1:
                share = min(count, remaining_target)
            else:
                share = min(count, int(math.floor(count * remaining_target / max(1, remaining_population))))
            taken[key] = share
            remaining_target -= share
            remaining_population -= count
        if remaining_target:
            for key in reversed(keys):
                spare = source[key] - taken[key]
                add = min(spare, remaining_target)
                taken[key] += add
                remaining_target -= add
                if not remaining_target:
                    break
        if remaining_target:
            raise ValueError("partition could not conserve requested count")
        remainder = {k: source[k] - taken[k] for k in keys}
        return remainder, taken

    @staticmethod
    def _formation_allocation_record(formation: Mapping[str, Any]) -> Dict[str, Any]:
        composition = {str(k): max(0, int(v)) for k, v in formation.get("composition", {}).items() if int(v) > 0}
        return {"personnel": max(0, int(formation.get("personnel", 0))), "composition": composition}

    @staticmethod
    def _partition_material(values: Mapping[str, Any], take_personnel: int, total_personnel: int) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """Partition conserved numeric quantities while inheriting routing metadata.

        Formation ``logistics`` is not a pure quantity map: it can also carry
        non-conserved provenance/routing fields such as ``source_depot_ref``.
        Splitting must divide only physical quantities. Metadata describes both
        resulting bodies until another owner explicitly changes it.
        """
        parent: Dict[str, Any] = {}
        child: Dict[str, Any] = {}
        for key in sorted(str(k) for k in values):
            value = values.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                amount = max(0, int(value))
                share = int(math.floor(amount * take_personnel / max(1, total_personnel)))
                child[key] = share
                parent[key] = amount - share
            else:
                parent[key] = _deepcopy(value)
                child[key] = _deepcopy(value)
        return parent, child

    @staticmethod
    def _merge_material(*maps: Mapping[str, Any]) -> Dict[str, Any]:
        """Merge quantity maps without treating provenance metadata as stock.

        Numeric fields are conserved by summation. For non-numeric routing or
        provenance metadata, the primary formation's value is retained. This is
        consistent with formation merge semantics, where the first formation is
        the surviving owner and keeps its non-quantity routing state.
        """
        out: Dict[str, Any] = {}
        numeric_keys: set[str] = set()
        metadata_keys: set[str] = set()
        for values in maps:
            for raw_key, value in values.items():
                key = str(raw_key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    if key in metadata_keys:
                        raise ValueError(f"material field changes type across merge: {key}")
                    numeric_keys.add(key)
                    out[key] = int(out.get(key, 0)) + int(value)
                else:
                    if key in numeric_keys:
                        raise ValueError(f"material field changes type across merge: {key}")
                    metadata_keys.add(key)
                    if key not in out:
                        out[key] = _deepcopy(value)
        return out

    @staticmethod
    def _equipment_units(formation: Mapping[str, Any]) -> Dict[str, int]:
        explicit = formation.get("equipment_units_by_role")
        if isinstance(explicit, dict):
            return {str(k): max(0, int(v)) for k, v in explicit.items()}
        completeness = max(0.0, min(1.0, _pct(formation.get("equipment_completeness", 0.0))))
        return {
            str(role): min(int(count), max(0, int(round(int(count) * completeness))))
            for role, count in formation.get("composition", {}).items()
        }

    @staticmethod
    def _set_equipment_units(formation: Dict[str, Any], units: Mapping[str, Any]) -> None:
        normalized = {str(k): max(0, int(v)) for k, v in units.items()}
        formation["equipment_units_by_role"] = normalized
        personnel = max(1, int(formation.get("personnel", 0)))
        total_units = sum(normalized.values())
        formation["equipment_completeness"] = f"{min(1.0, total_units / personnel):.4f}"

    def _shield_units(self, formation: Mapping[str, Any]) -> Dict[str, int]:
        explicit = formation.get("shield_units_by_role")
        if isinstance(explicit, Mapping):
            return {str(k): max(0, int(v)) for k, v in explicit.items()}
        composition = formation.get("composition", {}) if isinstance(formation.get("composition"), Mapping) else {}
        equipment = self._equipment_units(formation)
        out: Dict[str, int] = {}
        for role, equipped in equipment.items():
            try:
                has_shield = bool(self._combat_role_uses_shield(str(role)))
            except Exception:
                has_shield = False
            if has_shield:
                out[str(role)] = min(max(0, int(composition.get(role, equipped))), max(0, int(equipped)))
        return out

    @staticmethod
    def _set_shield_units(formation: Dict[str, Any], units: Mapping[str, Any]) -> None:
        formation["shield_units_by_role"] = {str(k): max(0, int(v)) for k, v in units.items()}

    def _armor_units(self, formation: Mapping[str, Any]) -> Dict[str, int]:
        explicit = formation.get("armor_units_by_role")
        if isinstance(explicit, Mapping):
            return {str(k): max(0, int(v)) for k, v in explicit.items()}
        composition = formation.get("composition", {}) if isinstance(formation.get("composition"), Mapping) else {}
        equipment = self._equipment_units(formation)
        out: Dict[str, int] = {}
        for role, equipped in equipment.items():
            try:
                has_armor = bool(self._combat_role_uses_armor(str(role)))
            except Exception:
                has_armor = False
            if has_armor:
                out[str(role)] = min(max(0, int(composition.get(role, equipped))), max(0, int(equipped)))
        return out

    @staticmethod
    def _set_armor_units(formation: Dict[str, Any], units: Mapping[str, Any]) -> None:
        formation["armor_units_by_role"] = {str(k): max(0, int(v)) for k, v in units.items()}

    def _force_equipment_pool(self, force: Dict[str, Any]) -> Dict[str, int]:
        pool = force.setdefault("available_equipment_units_by_role", {})
        return pool

    @staticmethod
    def _force_equipment_location_pool(force: Dict[str, Any], location_ref: str) -> Dict[str, int]:
        return force.setdefault("available_equipment_by_location", {}).setdefault(location_ref, {})

    def _take_force_equipment(self, force: Dict[str, Any], role: str, count: int, location_ref: str) -> int:
        if count <= 0:
            return 0
        aggregate = self._force_equipment_pool(force); local = self._force_equipment_location_pool(force, location_ref)
        take = min(count, int(aggregate.get(role, 0)), int(local.get(role, 0)))
        aggregate[role] = int(aggregate.get(role, 0)) - take; local[role] = int(local.get(role, 0)) - take
        return take

    def _return_force_equipment(self, force: Dict[str, Any], role: str, count: int, location_ref: str) -> None:
        if count <= 0:
            return
        aggregate = self._force_equipment_pool(force); local = self._force_equipment_location_pool(force, location_ref)
        aggregate[role] = int(aggregate.get(role, 0)) + count; local[role] = int(local.get(role, 0)) + count

    @staticmethod
    def _force_location_pool(force: Dict[str, Any], location_ref: str) -> Dict[str, int]:
        pools = force.setdefault("available_by_location", {})
        return pools.setdefault(location_ref, {})

    def _take_force_personnel(self, force: Dict[str, Any], role: str, count: int, location_ref: str) -> None:
        if str(role) in FORBIDDEN_PERMANENT_SUPPORT_ROLES:
            raise ValueError("support work uses temporary duty from existing combat manpower; permanent support troop roles are not valid")
        if count < 0:
            raise ValueError("cannot take negative force personnel")
        loc_pool = self._force_location_pool(force, location_ref)
        if int(loc_pool.get(role, 0)) < count:
            raise ValueError("insufficient conserved personnel at the exact source location")
        if int(force.get("available_by_role", {}).get(role, 0)) < count:
            raise ValueError("insufficient conserved force role pool")
        loc_pool[role] = int(loc_pool.get(role, 0)) - count
        force["available_by_role"][role] = int(force["available_by_role"].get(role, 0)) - count

    def _return_force_personnel(self, force: Dict[str, Any], role: str, count: int, location_ref: str) -> None:
        if count < 0:
            raise ValueError("cannot return negative force personnel")
        loc_pool = self._force_location_pool(force, location_ref)
        loc_pool[role] = int(loc_pool.get(role, 0)) + count
        force.setdefault("available_by_role", {})[role] = int(force.get("available_by_role", {}).get(role, 0)) + count

    def _mount_pool_path_for_force(self, force_ref: str, state_hint: str = "") -> str | None:
        owner_id = f"mount_pool_{force_ref}"
        owners = self.read("state/index/owner-index.json").get("owners", {})
        path = owners.get(owner_id) if isinstance(owners, Mapping) else None
        if isinstance(path, str) and self.read_optional(path) is not None:
            return path
        state = str(state_hint or "").replace("state_", "")
        if force_ref.startswith("force_state_"):
            state = force_ref.replace("force_state_", "")
        if state:
            candidate = f"state/mounts/{state}.json"
            if self.read_optional(candidate) is not None:
                return candidate
        return None

    def _mount_pool_path_for_formation(self, formation: Mapping[str, Any]) -> str | None:
        force_ref = str(formation.get("owner_force_ref", ""))
        state_hint = str(formation.get("administrative_owner", "")).replace("state_", "")
        try:
            force = self.read(self.owner_path(force_ref)) if force_ref else {}
        except Exception:
            force = {}
        if isinstance(force, Mapping):
            state_hint = str(force.get("state", state_hint)).replace("state_", "")
        return self._mount_pool_path_for_force(force_ref, state_hint)

    def _role_horse_requirement(self, role: str, count: int) -> int:
        count = max(0, int(count))
        if count <= 0:
            return 0
        try:
            profile = self._combat_role_profile(str(role))
            loadout = self._combat_loadout(str(profile.get("loadout_id", ""))) if isinstance(profile, Mapping) else {}
        except Exception:
            loadout = {}
        return count if isinstance(loadout, Mapping) and bool(loadout.get("mount")) else 0

    def _mounted_role_counts(self, composition: Mapping[str, Any]) -> dict[str, int]:
        return {
            str(role): max(0, int(count))
            for role, count in composition.items()
            if self._role_horse_requirement(str(role), int(count)) > 0
        }

    def _material_depot(self, formation: Mapping[str, Any]) -> tuple[str, Dict[str, Any]]:
        force_ref = str(formation.get("owner_force_ref", "")); location = str(formation.get("location_ref", ""))
        if force_ref.startswith("force_state_"):
            state = force_ref.replace("force_state_", "")
            try:
                force_doc=self.read(self.owner_path(force_ref))
            except Exception:
                force_doc={}
            if isinstance(force_doc,Mapping) and str(force_doc.get("service_class",""))=="state_levy":
                state=str(force_doc.get("state",formation.get("administrative_owner", ""))).replace("state_","")
            home_path = f"state/depots/{state}.json"; home = _deepcopy(self.read(home_path))
            if home.get("location_ref") == location:
                return home_path, home
            slug = str(formation.get("formation_ref", "field")).replace("formation_", "").replace("_", "-")
            path = f"state/depots/field-{slug}.json"; existing = self.read_optional(path)
            if existing is not None:
                return path, _deepcopy(existing)
            depot={"schema":"sword-depot","owner_id":f"depot_field_{slug}","state":state,"location_ref":location,"stocks":{"grain_kg":0,"war_arrows":0,"war_bolts":0},"mounts":{},"kind":"field_cache"}; self.put(path,depot); self._register_owner(depot["owner_id"],path); return path,depot
        admin = str(formation.get("administrative_owner", "private")); slug = force_ref.replace("force_", "").replace("_", "-") or "private"; home_path=f"state/depots/{slug}.json"; existing=self.read_optional(home_path)
        if existing is not None and existing.get("location_ref") == location:
            return home_path, _deepcopy(existing)
        if existing is None:
            depot={"schema":"sword-depot","owner_id":f"depot_{force_ref or slug}","state":admin,"location_ref":location,"stocks":{"grain_kg":0,"war_arrows":0,"war_bolts":0},"mounts":{}}; self.put(home_path,depot); self._register_owner(depot["owner_id"],home_path); return home_path,depot
        field_slug=str(formation.get("formation_ref","field")).replace("formation_","").replace("_","-"); path=f"state/depots/field-{field_slug}.json"; field=self.read_optional(path)
        if field is None:
            field={"schema":"sword-depot","owner_id":f"depot_field_{field_slug}","state":admin,"location_ref":location,"stocks":{"grain_kg":0,"war_arrows":0,"war_bolts":0},"mounts":{},"kind":"field_cache"}; self.put(path,field); self._register_owner(field["owner_id"],path)
        return path,_deepcopy(field)

    def _return_formation_materials(self, formation: Mapping[str, Any], *, include_mounts: bool = True) -> None:
        path, depot = self._material_depot(formation)
        stocks = depot.setdefault("stocks", {})
        keymap = {"war_arrows": "war_arrows", "war_bolts": "war_bolts"}
        for key, amount in formation.get("logistics", {}).items():
            if not isinstance(amount, (int, float)) or isinstance(amount, bool):
                continue
            if str(key) == "remount_horses":
                if include_mounts:
                    mounts = depot.setdefault("mounts", {})
                    mounts["horse"] = int(mounts.get("horse", 0)) + int(amount)
                continue
            stock_key = keymap.get(str(key), str(key))
            stocks[stock_key] = int(stocks.get(stock_key, 0)) + int(amount)
        if include_mounts:
            mounts = depot.setdefault("mounts", {})
            for kind, count in formation.get("mounts", {}).items():
                mounts[str(kind)] = int(mounts.get(str(kind), 0)) + int(count)
        self.put(path, depot)

    def _location_record(self, location_ref: str) -> Mapping[str, Any]:
        for location in self.read("game/data/world/locations.json").get("locations", []):
            if location.get("ref") == location_ref:
                return location
        if location_ref.startswith("loc_tang_manor_"):
            return {"ref": location_ref, "kind": "estate", "functions": ["house"]}
        raise ValueError(f"unknown battlefield location: {location_ref}")

    @staticmethod
    def _person_location(person: Mapping[str, Any]) -> Optional[str]:
        for key in ("location", "current_location"):
            value = person.get(key)
            if isinstance(value, str) and value.startswith("loc_"):
                return value
        return None

    @staticmethod
    def _person_health(person: Mapping[str, Any]) -> str:
        health = person.get("health")
        if isinstance(health, Mapping):
            return str(health.get("status", person.get("health_status", "healthy")))
        return str(person.get("health_status", health if health is not None else "healthy"))

    @staticmethod
    def _set_person_health(person: Dict[str, Any], value: str) -> None:
        if isinstance(person.get("health"), dict):
            person["health"]["status"] = value
        elif "health_status" in person or "health" not in person:
            person["health_status"] = value
        else:
            person["health"] = value

    @staticmethod
    def _set_person_location(person: Dict[str, Any], value: str) -> None:
        if "location" in person:
            person["location"] = value
        else:
            person["current_location"] = value
        person.pop("location_scope", None)

    @staticmethod
    def _set_person_life_status(person: Dict[str, Any], value: str) -> None:
        if "life_status" in person:
            person["life_status"] = value
        elif "status" in person:
            person["status"] = value
        else:
            person["life_status"] = value

    def _world_time(self) -> CampaignTime:
        runtime_time = CampaignTime.parse(str(self.read("state/runtime.json")["world_time"]))
        meta_time = CampaignTime.parse(str(self.read("state/meta.json")["time"]))
        if runtime_time != meta_time:
            raise ValueError("campaign chronology authorities disagree")
        return runtime_time

    def _causal_seed(self, command: CommandEnvelope, payload: Mapping[str, Any], salt: str = "") -> int:
        meta = self.read("state/meta.json")
        material = {
            "world_seed": meta.get("world_seed"),
            "revision": command.expected_revision,
            "world_time": str(self._world_time()),
            "actor": command.actor_id,
            "command_type": command.command_type,
            "payload": payload,
            "salt": salt,
        }
        raw = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return int(hashlib.sha256(raw).hexdigest()[:16], 16)

    def _exact_person(self, person_ref: str, *, active: bool = True) -> tuple[str, Dict[str, Any]]:
        path, person0 = self.owner(str(person_ref))
        person = _deepcopy(person0)
        if person.get("schema") not in {"sab_character", "sword-materialized-person"}:
            raise ValueError(f"{person_ref} is not an exact saved person")
        life = str(person.get("life_status", person.get("status", "active"))).lower()
        if active and life in {"dead", "deceased", "destroyed"}:
            raise ValueError(f"{person_ref} is not an active living person")
        return path, person

    def _command_person(self, person_ref: str, *, active: bool = True) -> tuple[str, Dict[str, Any]]:
        """Return one individually represented formal command person.

        Formation command establishment may lawfully use either a full exact
        character or a conserved person-lite officer.  The latter is still one
        individually addressable body and therefore must move, train, suffer
        consequences, and retain command identity like any other formal command
        person.  Keep ``_exact_person`` strict for mechanics that genuinely need
        a full exact character sheet; command custody uses this broader helper.
        """
        path, person0 = self.owner(str(person_ref))
        person = _deepcopy(person0)
        if person.get("schema") not in {"sab_character", "sword-materialized-person", "person-lite"}:
            raise ValueError(f"{person_ref} is not an individually represented command person")
        life = str(person.get("life_status", person.get("status", "active"))).lower()
        if active and life in {"dead", "deceased", "destroyed"}:
            raise ValueError(f"{person_ref} is not an active living command person")
        return path, person

    def _formation_task_leader(self, formation: Mapping[str, Any]) -> Dict[str, Any] | None:
        """Resolve the best exact current leader for temporary military support work.

        Formation commander authority wins. If a Unit stores only aggregate
        top command, the enclosing command group's exact commander supplies the
        planning skill. Explicit staff authority is handled at command-group scope.
        No support-role manpower is consulted.
        """
        refs: list[str] = []
        for key in ("commander_ref", "command_authority"):
            ref = formation.get(key)
            if isinstance(ref, str) and ref and ref not in refs:
                refs.append(ref)
        group_ref = formation.get("higher_command_ref")
        if not isinstance(group_ref, str) or not group_ref:
            try:
                idx = self.read("state/cmd/command-groups/index.json")
                primary = idx.get("primary_formation_group", {}) if isinstance(idx, Mapping) else {}
                group_ref = primary.get(str(formation.get("formation_ref", ""))) if isinstance(primary, Mapping) else None
            except Exception:
                group_ref = None
        if isinstance(group_ref, str) and group_ref:
            group = self.read_optional(f"state/cmd/command-groups/{group_ref}.json")
            if isinstance(group, Mapping):
                for key in ("commander_ref",):
                    ref = group.get(key)
                    if isinstance(ref, str) and ref and ref not in refs:
                        refs.append(ref)
        for ref in refs:
            try:
                _path, person = self._exact_person(ref)
            except (KeyError, ValueError, FileNotFoundError):
                continue
            return person
        return None

    def _formation_task_score(self, formation: Mapping[str, Any], task: str) -> float:
        return task_leader_score(self._formation_task_leader(formation), task)

    def _item_record(self, item_id: str) -> Dict[str, Any]:
        index = self.read("game/data/items.json")
        shard_path = index.get("record_index", {}).get(str(item_id))
        if not isinstance(shard_path, str):
            raise ValueError(f"unknown exact item: {item_id}")
        shard = self.read(shard_path)
        record = shard.get("items", {}).get(str(item_id))
        if not isinstance(record, dict):
            raise ValueError(f"item index is inconsistent for {item_id}")
        return _deepcopy(record)

    @staticmethod
    def _market_item_id(item_key: str) -> str:
        aliases = {
            "common_sword": "weapon_sword",
            "military_sword": "weapon_sword",
            "military_spear": "weapon_spear",
            "military_bow": "weapon_bow",
            "helmet": "helmet_standard",
            "lamellar_cuirass": "armor_heavy",
            "padded_coat": "armor_light",
            "shield": "shield_standard",
            "arrows_20": "ammo_arrow",
            "bolts_20": "ammo_bolt_war",
        }
        item_id = aliases.get(str(item_key))
        if item_id is None:
            raise ValueError(f"market item has no exact equipment identity: {item_key}")
        return item_id

    def _player_inventory(self) -> tuple[str, Dict[str, Any]]:
        path = "state/economy/player-inventory.json"
        inv = _deepcopy(self.read_optional(path) or {"schema":"sword-player-inventory","owner_id":"inventory_char_tang_wei","items":{}})
        inv.setdefault("items", {})
        return path, inv

    def _player_manifest(self) -> tuple[str, Dict[str, Any]]:
        path = "state/player-detail/equipment-manifest.json"
        manifest = _deepcopy(self.read(path))
        manifest.setdefault("equipment_manifest", [])
        return path, manifest

    @staticmethod
    def _manifest_quantity(manifest: Mapping[str, Any], item_id: str, *, equipped_only: bool = False) -> int:
        total = 0
        for entry in manifest.get("equipment_manifest", []):
            if str(entry.get("item_id")) != item_id:
                continue
            state = str(entry.get("current_state", "")).lower()
            if equipped_only and not any(word in state for word in ("equipped", "worn", "readied", "quivered", "mounted")):
                continue
            total += max(0, int(entry.get("quantity", 0)))
        return total

    @staticmethod
    def _take_manifest_items(manifest: Dict[str, Any], item_id: str, quantity: int, *, require_equipped: bool = False) -> None:
        remaining = int(quantity)
        entries = manifest.setdefault("equipment_manifest", [])
        for entry in list(entries):
            if str(entry.get("item_id")) != item_id:
                continue
            state = str(entry.get("current_state", "")).lower()
            if require_equipped and not any(word in state for word in ("equipped", "worn", "readied", "quivered", "mounted")):
                continue
            take = min(remaining, max(0, int(entry.get("quantity", 0))))
            entry["quantity"] = int(entry.get("quantity", 0)) - take
            remaining -= take
            if int(entry.get("quantity", 0)) <= 0:
                entries.remove(entry)
            if remaining <= 0:
                break
        if remaining:
            raise ValueError("insufficient exact equipment custody")

    def _advance_seconds(self, seconds: int) -> tuple[str, Dict[str, int]]:
        if seconds < 0:
            raise ValueError("elapsed simulation time cannot be negative")
        current = self._world_time()
        target = str(current.add_seconds(max(1, int(seconds))))
        return target, self._advance_runtime(target)

    def _route_travel_hours(self, origin: str, destination: str, *, modes: tuple[str, ...] = ("horse", "foot")) -> int:
        plan = geography_shortest_path(self.read, str(origin), str(destination), modes=modes)
        return int(plan.get("duration_hours", 0))

    def _formation_route_next(self, origin: str, destination: str, *, formation: Mapping[str, Any] | None = None, at: str | None = None) -> tuple[str, int]:
        """Return the next lawful formation-capable hop from the unified route authority."""
        def edge_ok(edge_origin: str, nxt: str, route: Mapping[str, Any]) -> bool:
            if formation is None or not hasattr(self, "_validate_formation_transit"):
                return True
            stamp = str(at or self._world_time())
            try:
                self._validate_formation_transit(formation, nxt, stamp)
                if hasattr(self, "_validate_formation_route_edge"):
                    self._validate_formation_route_edge(formation, edge_origin, nxt, route, stamp)
                return True
            except PermissionError:
                return False
        plan = geography_shortest_path(self.read, str(origin), str(destination), modes=("formation",), edge_allowed=edge_ok)
        path = list(plan.get("path", [])); edge_hours = list(plan.get("edge_hours", []))
        if len(path) < 2:
            return str(destination), 0
        return str(path[1]), int(edge_hours[0])

    def _apply_unit_duties(
        self,
        formation_refs: Iterable[str],
        phase: str,
        *,
        context_ref: str,
        at: str | None = None,
        policy: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Persist zero-body phase duties for existing direct Units.

        Duty assignment never creates detachments or manpower.  The caller
        supplies the exact participant set for the current operation/army side.
        """
        refs = sorted({str(x) for x in formation_refs if isinstance(x, str) and x})
        formations: dict[str, Mapping[str, Any]] = {}
        people: dict[str, Mapping[str, Any]] = {}
        paths: dict[str, str] = {}
        for ref in refs:
            try:
                path, formation = self._load_formation(ref)
            except ValueError:
                continue
            if str(formation.get("formation_class", "unit")) != "unit":
                continue
            paths[ref] = path
            formations[ref] = formation
            for person_ref in (formation.get("commander_ref"),):
                if not isinstance(person_ref, str) or not person_ref or person_ref in people:
                    continue
                try:
                    _pp, person = self._command_person(person_ref)
                except (KeyError, ValueError, FileNotFoundError):
                    continue
                people[person_ref] = person
        if not formations:
            return []
        group = {"units": [{"kind": "formation", "ref": ref} for ref in sorted(formations)]}
        effective_policy = dict(policy or {})
        if policy is None and any(str(row.get("command_authority", "")) == self.PLAYER_ACTOR for row in formations.values()):
            # Tang Wei's standing Qin field-army duties apply only to the Qin
            # Units assigned under his state command. His House Guard and Tang
            # Champions remain separate personal/House forces and are not silently
            # repurposed as Qin reconnaissance, baggage, reserve, siege, or other
            # standing army-duty Units merely because they share an operation.
            effective_policy = {
                "eligible_force_refs": ["force_state_qin"],
                "eligible_administrative_owners": ["state_qin"],
            }
        doctrine = {"unit_duty_policy": effective_policy}
        rows = assign_phase_duties(
            phase=str(phase), group=group, formations_by_ref=formations, people_by_ref=people,
            doctrine=doctrine, registry=self.read("game/data/mechanics/unit-duties.json"),
        )
        stamp = str(at or self._world_time())
        for row in rows:
            ref = str(row["formation_ref"]); formation = _deepcopy(formations[ref])
            formation["current_unit_duty"] = {
                "phase": str(phase), "duty_id": str(row["duty_id"]),
                "suitability": float(row["suitability"]), "context_ref": str(context_ref), "assigned_at": stamp,
            }
            self.put(paths[ref], formation)
        return rows

    @staticmethod
    def _unit_duty_battle_factor(formation: Mapping[str, Any]) -> float:
        duty = formation.get("current_unit_duty") if isinstance(formation.get("current_unit_duty"), Mapping) else {}
        if str(duty.get("phase", "")) != "battle":
            return 1.0
        suitability = max(0.0, float(duty.get("suitability", 0.0) or 0.0))
        # Duty fit has a bounded organizational effect; it never substitutes for
        # troop capability, equipment, command, terrain, or supply.
        return max(0.94, min(1.06, 0.94 + suitability / 500.0))

    def _autonomy_move_formation_step(self, formation_ref: str, destination: str, at: str) -> Dict[str, Any]:
        path,formation0=self._load_formation(formation_ref); formation=_deepcopy(formation0); origin=str(formation.get("location_ref")); n=int(formation.get("personnel",0))
        departure=CampaignTime.parse(at); fatigue_rules=self.read(FATIGUE_RULES_PATH); settle_formation_idle_fatigue(formation,current=departure,rules=fatigue_rules)
        if n<=0: return {"status":"destroyed","location_ref":origin}
        if origin==destination: return {"status":"arrived","location_ref":origin,"hours":0}
        # Formal command identity is conserved.  A detached individually
        # represented commander blocks autonomous movement instead of being
        # silently deleted from the formation.  Cold/aggregate command paths are
        # left intact and may still provide lawful higher/aggregate command.
        commander_ref=formation.get("commander_ref")
        command_person: tuple[str, Dict[str, Any]] | None = None
        if isinstance(commander_ref,str) and commander_ref:
            try:
                cp,commander=self._command_person(commander_ref); ploc=self._person_location(commander)
                if ploc not in {origin, destination}:
                    formation["status"]="commander_detached"
                    formation["last_march_leg"]={"at":at,"from":origin,"toward":destination,"status":"blocked_by_detached_commander","commander_ref":commander_ref,"commander_location_ref":ploc}
                    self.put(path,formation)
                    return {"status":"commander_detached","location_ref":origin,"commander_ref":commander_ref,"commander_location_ref":ploc}
                command_person=(cp,commander)
            except (KeyError, ValueError, FileNotFoundError):
                command_person=None
        nxt,hours=self._formation_route_next(origin,destination,formation=formation,at=at)
        supply_state=evaluate_military_supply(self,formation,at=at)
        supply_factor=max(0.40,min(1.0,float(supply_state.get("movement_factor",1.0) or 1.0)))
        hours=max(1,int(math.ceil(hours/supply_factor)))
        formation["mobilized"]=True; formation["status"]="marching" if nxt!=destination else "deployed"; formation["location_ref"]=nxt; stamp_formation_activity_fatigue(formation,completed_at=departure.add_seconds(hours*3600),fatigue_gain=max(1,int(math.ceil(hours/8.0))),activity_kind="march"); formation["readiness"]=_clamp(int(formation.get("readiness",50))-max(0,int(hours//36))); formation["last_march_leg"]={"at":at,"from":origin,"to":nxt,"toward":destination,"hours":hours,"supply_condition":str(supply_state.get("condition","adequate")),"supply_score_milli":int(supply_state.get("score_milli",1000))}
        if command_person is not None:
            cp,commander=command_person; ploc=self._person_location(commander)
            if ploc==origin:
                self._set_person_location(commander,nxt); commander["current_formation_id"]=formation_ref; self.put(cp,commander)
        self.put(path,formation); self._index_formation_location(formation_ref,origin,nxt)
        if hasattr(self, "_sync_mercenary_tactical_company"):
            owner_ref = str(formation.get("owner_force_ref", ""))
            if owner_ref:
                try:
                    self._sync_mercenary_tactical_company(owner_ref)
                except (KeyError, ValueError, FileNotFoundError):
                    pass
        return {"status":"arrived" if nxt==destination else "marching","location_ref":nxt,"hours":hours,"supply_condition":str(supply_state.get("condition","adequate")),"supply_score_milli":int(supply_state.get("score_milli",1000))}

    def _autonomy_sustain_march(self, formation_ref: str, destination: str, at: str, theater_record: Dict[str, Any], key: str) -> Dict[str, Any]:
        """Report current derived strategic support for an autonomous march.

        Armies no longer carry or receive ration/feed inventories.  This hook is
        retained as a compatibility boundary for autonomous campaign code, but it
        never creates a convoy or transfers provisions.  Discrete ammunition or
        equipment transfers remain separate exact operations when needed.
        """
        del destination, theater_record, key
        try:
            _path, formation = self._load_formation(formation_ref)
        except ValueError:
            return {"status": "formation_missing"}
        state = evaluate_military_supply(self, formation, at=at)
        return {
            "status": "derived_supply",
            "location_ref": formation.get("location_ref"),
            "condition": state.get("condition"),
            "score_milli": state.get("score_milli"),
            "movement_factor": state.get("movement_factor"),
            "nearest_support_ref": state.get("nearest_support_ref"),
            "nearest_support_route_hours": state.get("nearest_support_route_hours"),
        }

    def _autonomy_apply_battle_losses(self, formation_ref: str, loss: int, at: str, *, losing_side: bool, opponent_state: str, seed_material: str) -> Dict[str, Any]:
        # Autonomous wars settle through the same personnel/ammunition/development
        # authorities as player-facing battles. Compression changes; conservation does not.
        if hasattr(self, "_combat_prepare_formation"):
            # Combat preparation already returns staged mutable owner images.
            # Mutate those exact transaction-local copies rather than cloning the
            # full force/cohort ledger a second time.
            path, formation, force = self._combat_prepare_formation(formation_ref)
        else:
            path, formation0 = self._load_formation(formation_ref); formation = _deepcopy(formation0)
            fp0 = self.owner_path(str(formation.get("owner_force_ref", ""))); force = _deepcopy(self.read(fp0))
        before=max(0,int(formation.get("personnel",0))); loss=max(0,min(before,int(loss)))
        opponent_authority_ref = str(opponent_state) if str(opponent_state).startswith("polity_") else f"state_{opponent_state}"
        frac=loss/max(1,before); battle_hours=3.0
        named = self._combat_named_participants(formation, force) if hasattr(self,"_combat_named_participants") else []
        rows = self._combat_cohort_snapshot(formation, force) if hasattr(self,"_combat_cohort_snapshot") else []
        # Formation logistics owns only anonymous/cohort missile stock. Exact named
        # people carry and persist their own ammunition separately, exactly as in
        # player-facing battle resolution.
        ammo_rows=list(rows)
        ammo_plan = self._combat_ammunition_plan(ammo_rows, formation.get("logistics",{}), battle_hours) if hasattr(self,"_combat_ammunition_plan") else {"consumed_by_resource":{}}
        consumed={}
        log=formation.setdefault("logistics",{})
        for resource, amount in ammo_plan.get("consumed_by_resource",{}).items():
            use=min(max(0,int(amount)),max(0,int(log.get(resource,0)))); log[resource]=max(0,int(log.get(resource,0))-use); consumed[resource]=use

        before_comp={str(role):max(0,int(count)) for role,count in formation.get("composition",{}).items()}
        shield_units_before=self._shield_units(formation)
        survivor_comp,dead_comp=self._partition_counts(before_comp,loss,before if before else 1)
        survivor_eq,lost_eq=self._partition_material(self._equipment_units(formation),loss,before if before else 1)
        survivor_mounts,lost_mounts=self._partition_material(formation.get("mounts",{}),loss,before if before else 1)
        survivor_shields: Dict[str,int]={}
        shield_losses: Dict[str,dict[str,Any]]={}
        shield_conditions=formation.setdefault("shield_condition_by_role",{})
        for role,prior_units_raw in shield_units_before.items():
            role_before=max(0,int(before_comp.get(role,0))); role_dead=max(0,int(dead_comp.get(role,0)))
            prior_units=max(0,min(role_before,int(prior_units_raw))) if role_before else 0
            casualty_lost=min(prior_units,max(0,int(round(prior_units*role_dead/max(1,role_before))))) if role_before else 0
            serviceable=max(0,min(int(survivor_comp.get(role,0)),prior_units-casualty_lost))
            prior_condition=max(0.0,min(100.0,float(shield_conditions.get(role,100.0) or 100.0)))
            # Autonomous settlement is intentionally compressed, but it may not
            # reset physical shield ownership. Contact wear is bounded from the
            # same settled casualty/contact severity rather than inventing a new
            # pool of shields.
            contact_wear=(0.30+7.0*frac)*(1.15 if losing_side else 1.0) if serviceable>0 else 0.0
            if serviceable>0 and hasattr(self,"_combat_shield_breakage_resolution"):
                br=self._combat_shield_breakage_resolution(serviceable,prior_condition,contact_wear)
                destroyed=max(0,int(br.get("units_destroyed",0) or 0)); after_units=max(0,int(br.get("units_after",serviceable) or 0)); after_condition=max(0.0,min(100.0,float(br.get("condition_after_pct",prior_condition-contact_wear) or 0)))
            else:
                destroyed=0; after_units=serviceable; after_condition=max(0.0,prior_condition-contact_wear)
            survivor_shields[role]=min(max(0,int(survivor_comp.get(role,0))),after_units)
            shield_conditions[role]=round(after_condition,3)
            shield_losses[role]={"before":prior_units,"lost_with_casualties":casualty_lost,"destroyed_in_contact":destroyed,"after":survivor_shields[role],"condition_before_pct":round(prior_condition,3),"condition_after_pct":round(after_condition,3)}

        armor_units_before=self._armor_units(formation)
        survivor_armor: Dict[str,int]={}
        armor_losses: Dict[str,dict[str,Any]]={}
        armor_conditions=formation.setdefault("armor_condition_by_role",{})
        for role,prior_units_raw in armor_units_before.items():
            role_before=max(0,int(before_comp.get(role,0))); role_dead=max(0,int(dead_comp.get(role,0)))
            prior_units=max(0,min(role_before,int(prior_units_raw))) if role_before else 0
            casualty_lost=min(prior_units,max(0,int(round(prior_units*role_dead/max(1,role_before))))) if role_before else 0
            serviceable=max(0,min(int(survivor_comp.get(role,0)),prior_units-casualty_lost))
            prior_condition=max(0.0,min(100.0,float(armor_conditions.get(role,100.0) or 100.0)))
            contact_wear=(0.20+4.5*frac)*(1.12 if losing_side else 1.0) if serviceable>0 else 0.0
            if serviceable>0 and hasattr(self,"_combat_armor_breakage_resolution"):
                br=self._combat_armor_breakage_resolution(serviceable,prior_condition,contact_wear)
                destroyed=max(0,int(br.get("units_destroyed",0) or 0)); after_units=max(0,int(br.get("units_after",serviceable) or 0)); after_condition=max(0.0,min(100.0,float(br.get("condition_after_pct",prior_condition-contact_wear) or 0)))
            else:
                destroyed=0; after_units=serviceable; after_condition=max(0.0,prior_condition-contact_wear)
            survivor_armor[role]=min(max(0,int(survivor_comp.get(role,0))),after_units)
            armor_conditions[role]=round(after_condition,3)
            armor_losses[role]={"before":prior_units,"lost_with_casualties":casualty_lost,"destroyed_in_contact":destroyed,"after":survivor_armor[role],"condition_before_pct":round(prior_condition,3),"condition_after_pct":round(after_condition,3)}
        formation["personnel"]=before-loss; formation["composition"]=survivor_comp; formation["mounts"]=survivor_mounts; self._set_equipment_units(formation,survivor_eq); self._set_shield_units(formation,survivor_shields); self._set_armor_units(formation,survivor_armor)
        supply_state = evaluate_military_supply(self, formation, at=at)
        morale_resolution = resolve_formation_morale(
            self,
            base_morale=int(formation.get("morale", 50)),
            recent_casualty_fraction=frac,
            cumulative_casualty_fraction=frac,
            registered_fear_pressure=2.0 if losing_side else 0.0,
            cohesion=int(formation.get("cohesion", 50)),
            supply_condition=str(supply_state.get("condition", "adequate")),
        )
        stamp_formation_activity_fatigue(formation,completed_at=CampaignTime.parse(at).add_seconds(int(battle_hours*3600)),fatigue_gain=18,activity_kind="battle")
        formation["morale"] = int(morale_resolution["effective_morale"])
        formation["cohesion"]=_clamp(int(formation.get("cohesion",50))-(8 if losing_side else 3))
        formation["status"]="destroyed" if formation["personnel"]<=0 else ("routed" if losing_side else "combat_effective")
        if formation["personnel"] > 0:
            officer_contact = min(1.0, .35 + frac * 3.0 + (.10 if losing_side else 0.0))
            record_officer_cadre_combat_experience(
                formation, battle_hours=battle_hours, contact_fraction=officer_contact, at=at
            )

        def remove_role(person_ref:str, role:str) -> None:
            if role=="commander" and formation.get("commander_ref")==person_ref:
                formation["commander_ref"]=None; self._release_commander_index(person_ref,formation_ref)
            for field in ("embedded_person_refs","notable_person_refs","staff_refs","specialist_refs"):
                raw=formation.get(field)
                if isinstance(raw,list) and person_ref in raw: formation[field]=[x for x in raw if x!=person_ref]

        named_outcomes={}; killed_inside=[]; inside_deaths=0
        training=self.read("game/data/mechanics/training.json")
        try:
            terrain_kind=str(terrain_context_for_location(self,str(formation.get("location_ref","")))["encoded"])
        except Exception:
            terrain_kind="open"

        def settle_autonomous_named_ammunition(person_ref:str, person:Dict[str,Any], part:Mapping[str,Any], outcome:str) -> dict[str,Any]:
            ammo_item=str(part.get("ammunition_item") or "")
            carried=max(0,int(part.get("carried_ammunition",0) or 0))
            ranged=max(0.0,float(part.get("ranged_direct_score",0) or 0))
            melee=max(0.0,float(part.get("melee_direct_score",part.get("direct_combat_score",0)) or 0))
            if not ammo_item or carried<=0 or ranged<=melee*1.03:
                return {}
            role=str(part.get("role","embedded")); exposure=max(.05,min(1.0,float(part.get("exposure_factor",.75) or .75)))
            duty={"commander":.045,"staff":.012,"specialist":.12,"notable":.20,"embedded":.24,"higher_commander":0.0}
            active_seconds=min(120.0,max(0.0,battle_hours*3600.0*duty.get(role,.10)*exposure))
            cycle=max(.8,float(part.get("ranged_cycle_seconds",6.0) or 6.0))
            released=min(carried,max(0,int(active_seconds//cycle)))
            if released<=0:
                return {}
            state=person.setdefault("combat_state",{}); projectile_state=state.setdefault("projectile_ammunition",{})
            before=max(0,int(projectile_state.get(ammo_item,carried) or 0)); fired=min(before,released)
            projectile=self._combat_weapon(ammo_item) if hasattr(self,"_combat_weapon") else {}
            recovery_base=max(0.0,min(.95,float(projectile.get("recovery_base",0) or 0))) if isinstance(projectile,Mapping) else 0.0
            terrain_recovery=.78 if terrain_has(terrain_kind,"plain") else (.58 if terrain_has(terrain_kind,"woodland","mountain","marsh") else .68)
            control_recovery=.82 if not losing_side else .28
            can_recover=outcome not in {"killed","captured"}
            recovered=min(fired,max(0,int(round(fired*recovery_base*terrain_recovery*control_recovery)))) if can_recover else 0
            after=max(0,before-fired+recovered); projectile_state[ammo_item]=after
            manifest_path="state/player-detail/equipment-manifest.json" if person_ref==self.PLAYER_ACTOR else person.get("equipment_manifest_ref")
            if isinstance(manifest_path,str) and manifest_path:
                manifest0=self.read_optional(manifest_path)
                if isinstance(manifest0,Mapping):
                    manifest=_deepcopy(manifest0); changed=False
                    for entry in manifest.get("equipment_manifest",[]):
                        if isinstance(entry,dict) and str(entry.get("item_id",""))==ammo_item:
                            entry["quantity"]=after; changed=True
                    if changed:self.put(manifest_path,manifest)
            return {"projectile_item_id":ammo_item,"before":before,"fired":fired,"recovered":recovered,"after":after,"projectile_recovery_base":round(recovery_base,5)}

        for part in named:
            pref=str(part.get("person_ref","")); role=str(part.get("role","embedded")); included=bool(part.get("included_in_personnel")); exposure=max(.05,min(1.0,float(part.get("exposure_factor",.75))))
            try: pp, p0=self.owner(pref); person=_deepcopy(p0)
            except (ValueError,KeyError,FileNotFoundError): continue
            if self._person_health(person)=="dead": continue
            roll=int(hashlib.sha256((seed_material+"|named|"+pref).encode()).hexdigest()[:8],16)%10000/10000.0
            defense=max(0.0,float(part.get("direct_combat_score",0))); survivability=max(.55,min(1.15,1.08-(defense-70)/900.0))
            death_p=min(.30,frac*(.30 if losing_side else .16)*exposure*survivability); capture_p=(min(.35,frac*.45*exposure) if losing_side and not included else 0.0); wound_p=min(.78,.015+frac*1.35*exposure*survivability); outcome="unharmed"
            if ((not included) or inside_deaths<loss) and roll<death_p:
                outcome="killed"; self._settle_person_death(pref,pp,person,at,"autonomous interstate battle casualty",settle_force_body=not included); remove_role(pref,role)
                if included: killed_inside.append(pref); inside_deaths+=1
            elif roll<death_p+capture_p:
                outcome="captured"; person["custody_state"]={"status":"captured","captured_at":at,"captured_by":opponent_authority_ref,"cause":"autonomous interstate battle"}; remove_role(pref,role); self.put(pp,person)
            elif roll<death_p+capture_p+wound_p:
                outcome="wounded"; self._set_person_health(person,"injured"); person["injury_state"]={"label":"interstate battle wound","severity":"severe" if frac>=.20 else "moderate","inflicted_at":at,"minimum_recovery_hours":72 if frac>=.20 else 24,"recovered_hours":0,"active":True}; self.put(pp,person)
            else:
                schema=str(person.get("schema")); skills=person.get("stats",{}).get("skills",{}) if schema=="person-lite" else person.get("skills",{})
                registry=self.read(TRAINING_PROGRAM_REGISTRY_PATH)
                branch_role=str(person.get("role", "") or next(iter(formation.get("composition",{})), role))
                program_ref=resolve_training_program_ref(registry,role=branch_role,training_ref=formation_training_ref_for_role(formation, branch_role),person=person)
                weights={name:weight for name,weight in combat_skill_weights_for_participant(registry,program_ref,role).items() if name in skills}
                temp=person if schema!="person-lite" else {"skills":dict(skills),"attributes":dict(person.get("stats",{}).get("attributes",{})),"aptitude":dict(person.get("aptitude",{})),"birth_date":person.get("birth_date","270-BCE-01-01"),"health_status":self._person_health(person),"development_state":_deepcopy(person.get("development_state",{}))}
                dev=settle_combat_experience(temp,weights,battle_hours*exposure,CampaignTime.parse(at),training) if weights else []
                if schema=="person-lite": person.setdefault("stats",{})["skills"]=temp.get("skills",{}); person["development_state"]=temp.get("development_state",{})
                self.put(pp,person)
            named_ammunition=settle_autonomous_named_ammunition(pref,person,part,outcome)
            if named_ammunition:
                self.put(pp,person)
            named_outcomes[pref]={"role":role,"representation":str(part.get("representation")),"outcome":outcome,"included_in_personnel":included,"named_ammunition":named_ammunition}

        force_ref=str(formation.get("owner_force_ref","")); fp=self.owner_path(force_ref) if force_ref else None
        cohort_losses={}
        if formation.get("cohort_composition"):
            cohort_losses=trim_formation_to_personnel(force,formation,old_personnel=before,new_personnel=formation["personnel"],casualty_ref=seed_material,materialized_casualty_refs=killed_inside)
            exact_role_losses={role:max(0,int(count)-int(formation.get("composition",{}).get(role,0))) for role,count in before_comp.items()}
            dead_comp={role:count for role,count in exact_role_losses.items() if count>0}
        # Top-level formation allocation and force headcount are part of the same
        # conserved casualty transaction. Update them before survivor experience,
        # whose validator intentionally checks the whole force ledger.
        alloc=force.get("allocated_to_formations",{}).get(formation_ref) if isinstance(force,dict) else None
        if isinstance(alloc,dict): alloc["personnel"]=formation["personnel"]
        elif alloc is not None: force.setdefault("allocated_to_formations",{})[formation_ref]=formation["personnel"]
        if force_ref: force["headcount"]=max(0,int(force.get("headcount",0))-loss)
        if formation.get("cohort_composition"):
            profiles=self.read("game/data/mil/recruitment-cohort-profiles.json"); contact=min(1,.35+frac*3+(.10 if losing_side else 0)); registry=self.read(TRAINING_PROGRAM_REGISTRY_PATH); combat_weights={}
            for _role in {str(c.get("role") or next(iter(formation.get("composition",{})),"line_infantry")) for c in force.get("cohort_ledger",{}).get("cohorts",{}).values() if isinstance(c,Mapping)}:
                _program=resolve_training_program_ref(registry,role=_role,training_ref=formation_training_ref_for_role(formation, _role)); combat_weights[_role]=combat_skill_weights(registry,_program)
            record_formation_combat_experience(force,formation,battle_hours=battle_hours,contact_fraction=contact,role_profiles=profiles.get("role_training_profiles",{}),training_rules=training,evidence_ref=seed_material,skill_weights_by_role=combat_weights); validate_cohort_ledger(force)
        self.put(path,formation)
        if fp: self.put(fp,force)
        if force_ref and hasattr(self,"_sync_mercenary_tactical_company"):
            # Tactical mercenary state is a conserved projection of the company
            # owner.  If synchronization fails after casualties, the battle must
            # fail closed so the transaction cannot commit divergent formation
            # and company headcounts.  Non-mercenary forces are a no-op inside
            # the synchronization helper.
            self._sync_mercenary_tactical_company(force_ref)
        if force_ref.startswith("force_state_"):
            state=force_ref.replace("force_state_",""); pp=f"state/population/{state}.json"; pop=_deepcopy(self.read(pp)); pop["strata"]["active_military"]=max(0,int(pop["strata"].get("active_military",0))-loss); pop["population_total"]=max(0,int(pop.get("population_total",0))-loss); self.put(pp,pop)
        return {"loss":loss,"equipment_units":lost_eq,"shield_losses":shield_losses,"armor_losses":armor_losses,"mounts":lost_mounts,"composition":dead_comp,"ammunition_consumed":consumed,"cohort_losses":cohort_losses,"named_person_outcomes":named_outcomes,"morale_resolution":_deepcopy(morale_resolution)}

    def _validate_person_location_for_formation(self, person_ref: str, formation: Mapping[str, Any]) -> tuple[str, Dict[str, Any]]:
        path, person = self._command_person(person_ref)
        floc = str(formation.get("location_ref", ""))
        ploc = self._person_location(person)
        if ploc == floc:
            return path, person
        scope = str(person.get("location_scope", ""))
        admin = str(formation.get("administrative_owner", ""))
        owner_force = str(formation.get("owner_force_ref", ""))
        expected_state = ""
        if admin.startswith("state_"):
            expected_state = admin
        elif owner_force.startswith("force_state_"):
            expected_state = owner_force.replace("force_", "")
        if ploc is None and scope == expected_state + "_unresolved":
            self._set_person_location(person, floc)
            return path, person
        raise ValueError("formation commander must be physically co-located with the formation")

    def _materialized_force_for_person(self, person_ref: str, person: Mapping[str, Any]) -> tuple[str, str, Dict[str, Any]] | None:
        """Resolve the one conserved force that owns an individually represented body.

        Person-lite records carry their force owner directly. Full exact formation
        staff can derive it from the live formation assignment. Command-group staff
        can derive it from one direct formation. Every candidate is verified against
        ``materialized_people`` before it is accepted.
        """
        candidates: list[str] = []
        owner = person.get("owner")
        if isinstance(owner, str) and owner.startswith("force_"):
            candidates.append(owner)
        assignment = person.get("command_assignment") if isinstance(person.get("command_assignment"), Mapping) else {}
        formation_ref = assignment.get("formation_ref") if isinstance(assignment, Mapping) else None
        if isinstance(formation_ref, str) and formation_ref:
            try:
                _formation_path, formation = self._load_formation(formation_ref)
                force_ref = formation.get("owner_force_ref")
                if isinstance(force_ref, str) and force_ref not in candidates:
                    candidates.append(force_ref)
            except (KeyError, ValueError, FileNotFoundError):
                pass
        group_ref = assignment.get("command_group_ref") if isinstance(assignment, Mapping) else None
        if isinstance(group_ref, str) and group_ref:
            try:
                group = self.read(f"state/cmd/command-groups/{group_ref}.json")
            except (KeyError, ValueError, FileNotFoundError):
                group = {}
            for unit in group.get("units", []) if isinstance(group, Mapping) else []:
                if not isinstance(unit, Mapping) or str(unit.get("kind", "")) != "formation":
                    continue
                ref = str(unit.get("ref", ""))
                if not ref:
                    continue
                try:
                    _formation_path, formation = self._load_formation(ref)
                except (KeyError, ValueError, FileNotFoundError):
                    continue
                force_ref = formation.get("owner_force_ref")
                if isinstance(force_ref, str) and force_ref not in candidates:
                    candidates.append(force_ref)
        for force_ref in candidates:
            try:
                force_path = self.owner_path(force_ref); force = _deepcopy(self.read(force_path))
            except (KeyError, ValueError, FileNotFoundError):
                continue
            people = force.get("materialized_people", {})
            if isinstance(people, Mapping) and person_ref in people:
                return force_ref, force_path, force
        return None

    def _settle_materialized_force_body_death(self, person_ref: str, person: Mapping[str, Any], at: str, reason: str) -> bool:
        """Remove one dead represented soldier from force/formation/population truth.

        This is used only when the death is *not already included* in a formation
        casualty reducer. It conserves the exact body across force headcount, any
        assigned formation slot, and the aggregate population service owner.
        """
        resolved = self._materialized_force_for_person(person_ref, person)
        if resolved is None:
            return False
        force_ref, force_path, force = resolved
        source_cohort_ref = str(person.get("source_cohort_ref", "") or "")
        source_cohort = force.get("cohort_ledger", {}).get("cohorts", {}).get(source_cohort_ref, {}) if source_cohort_ref else {}
        origin = source_cohort.get("origin", {}) if isinstance(source_cohort, Mapping) else {}
        assignments = force.get("materialized_assignments", {})
        assignment = _deepcopy(assignments.get(person_ref)) if isinstance(assignments, Mapping) and isinstance(assignments.get(person_ref), Mapping) else None
        people = force.get("materialized_people", {})
        if not isinstance(people, dict) or person_ref not in people:
            return False
        people.pop(person_ref, None)
        if isinstance(assignments, dict):
            assignments.pop(person_ref, None)
        force["headcount"] = max(0, int(force.get("headcount", 0)) - 1)

        if isinstance(assignment, Mapping):
            formation_ref = str(assignment.get("formation_ref", "") or "")
            if formation_ref:
                formation_path, formation0 = self._load_formation(formation_ref); formation = _deepcopy(formation0)
                if int(formation.get("personnel", 0)) <= 0:
                    raise ValueError("materialized death cannot reduce an empty formation")
                formation["personnel"] = int(formation.get("personnel", 0)) - 1
                role = str(assignment.get("role", "") or "")
                composition = formation.get("composition")
                if role and isinstance(composition, dict) and int(composition.get(role, 0)) > 0:
                    composition[role] = int(composition.get(role, 0)) - 1
                    if composition[role] <= 0:
                        composition.pop(role, None)
                for field in ("embedded_person_refs", "notable_person_refs", "staff_refs", "specialist_refs"):
                    refs = formation.get(field)
                    if isinstance(refs, list) and person_ref in refs:
                        formation[field] = [ref for ref in refs if ref != person_ref]
                if formation.get("commander_ref") == person_ref:
                    formation["commander_ref"] = None
                cadre = ensure_officer_cadre(formation)
                rank = person.get("military_rank") if isinstance(person.get("military_rank"), Mapping) else {}
                grade = str(rank.get("grade", "")) if isinstance(rank, Mapping) else ""
                refs_by_rank = cadre.get("materialized_refs_by_rank", {}) if isinstance(cadre, Mapping) else {}
                materialized_rank = next((key for key, refs in refs_by_rank.items() if isinstance(refs, list) and person_ref in refs), None)
                rank_key = materialized_rank or (grade if grade in cadre.get("rank_inventory", {}) else None)
                if rank_key and int(cadre.get("rank_inventory", {}).get(rank_key, 0)) > 0:
                    cadre["rank_inventory"][rank_key] = int(cadre["rank_inventory"].get(rank_key, 0)) - 1
                unregister_materialized_rank(formation, person_ref)
                reorganize_officer_cadre(formation, at=at, reason="materialized_officer_death")
                sync_materialized_officer_billets(self, formation)
                alloc = force.get("allocated_to_formations", {}).get(formation_ref) if isinstance(force.get("allocated_to_formations"), Mapping) else None
                if isinstance(alloc, dict):
                    alloc["personnel"] = int(formation.get("personnel", 0))
                    if role and isinstance(alloc.get("composition"), dict) and int(alloc["composition"].get(role, 0)) > 0:
                        alloc["composition"][role] = int(alloc["composition"].get(role, 0)) - 1
                        if alloc["composition"][role] <= 0:
                            alloc["composition"].pop(role, None)
                    elif role and "role" in alloc and str(alloc.get("role")) == role:
                        pass
                elif alloc is not None:
                    force.setdefault("allocated_to_formations", {})[formation_ref] = int(formation.get("personnel", 0))
                self.put(formation_path, formation)

        validate_cohort_ledger(force)
        self.put(force_path, force)

        admin = str(force.get("administrative_owner", "") or "")
        owner_state = ""
        if force_ref.startswith("force_state_"):
            owner_state = force_ref.removeprefix("force_state_")
            if str(force.get("service_class", "")) == "state_levy":
                owner_state = str(force.get("state", owner_state)).removeprefix("state_")
        elif isinstance(force.get("state"), str) and force.get("state"):
            owner_state = str(force.get("state")).removeprefix("state_")
        elif admin.startswith("house_"):
            try:
                owner_state = self._state_key(self.read(self.owner_path(admin)).get("state"))
            except Exception:
                owner_state = ""
        elif admin == self.PLAYER_ACTOR or force_ref == "force_tang_wei_personal":
            owner_state = "qin"
        population_ref = str(origin.get("population_ref", "") or "") if isinstance(origin, Mapping) else ""
        native_state = population_ref.removeprefix("population_") if population_ref.startswith("population_") else owner_state
        if not native_state:
            raise ValueError("materialized military death has no population authority")
        population_path = f"state/population/{native_state}.json"; population = _deepcopy(self.read(population_path))
        service_class = str(force.get("service_class", "") or "")
        if force_ref.startswith("force_state_") or service_class == "native_military":
            service_key = "serving_native_military" if native_state == owner_state else "serving_foreign_military"
            stratum = "active_military" if native_state == owner_state else "foreign_military_service"
        elif service_class == "foreign_military":
            service_key = "serving_foreign_military"
            stratum = "foreign_military_service"
        else:
            service_key = "private_household_military"; stratum = "private_household_military"
        strata = population.get("strata")
        if not isinstance(strata, dict) or int(strata.get(stratum, 0)) <= 0:
            raise ValueError("materialized military death exceeds population service stratum")
        strata[stratum] = int(strata.get(stratum, 0)) - 1
        population["population_total"] = max(0, int(population.get("population_total", 0)) - 1)

        if hasattr(self, "_record_local_service_deaths"):
            locations: list[str] = []
            current_location = self._person_location(person)
            source_location = str(origin.get("source_location_ref", "") or "") if isinstance(origin, Mapping) else ""
            for location in (current_location, source_location):
                if isinstance(location, str) and location and location not in locations:
                    locations.append(location)
            sites = population.get("local_population", {}).get("sites", {}) if isinstance(population.get("local_population"), Mapping) else {}
            for location, row in sorted(sites.items()) if isinstance(sites, Mapping) else []:
                allocation = row.get("service_allocations", {}).get(force_ref) if isinstance(row, Mapping) and isinstance(row.get("service_allocations"), Mapping) else None
                if isinstance(allocation, Mapping) and int(allocation.get("personnel", 0)) > 0 and str(location) not in locations:
                    locations.append(str(location))
            applied = 0
            for location in locations:
                trial = _deepcopy(population)
                try:
                    count = self._record_local_service_deaths(
                        trial, native_state, location, 1, service_key=service_key,
                        service_owner_ref=force_ref,
                        source_stratum=str(origin.get("source_stratum")) if isinstance(origin, Mapping) and origin.get("source_stratum") else None,
                    )
                except ValueError:
                    continue
                if count == 1:
                    population = trial; applied = 1; break
            if applied != 1:
                raise ValueError("materialized military death has no conserved local service allocation")
        self.put(population_path, population)
        if native_state == "qin" and force_ref in {"force_house_tang", "force_tang_wei_personal"}:
            try:
                from sword_runtime.tang_population import sync_tang_private_population
                sync_tang_private_population(self, at=at, reason="materialized_military_death", evidence_ref=f"{reason}:{person_ref}")
            except (KeyError, ValueError, FileNotFoundError):
                raise
        return True

    def _settle_person_death(self, person_ref: str, person_path: str, person: Dict[str, Any], at: str, reason: str, *, settle_force_body: bool = False) -> None:
        # Low-level physiology/anatomy may discover death on the mutable person
        # before this lifecycle owner runs. A pre-marked corpse still requires
        # terminal scheduler, command, family, faction and conserved-body cleanup.
        # Only a person already terminalized by this owner may return early.
        if person.get("death_terminalized_at"):
            return
        force_body_snapshot=_deepcopy(person) if settle_force_body else person
        self._set_person_life_status(person, "dead"); self._set_person_health(person, "dead")
        person["died_at"] = str(person.get("died_at") or at)
        person["death_reason"] = str(person.get("death_reason") or reason)
        person["death_terminalized_at"] = at
        activity_contract=person.get("activity_contract") if isinstance(person.get("activity_contract"),dict) else None
        if activity_contract is not None:
            activity_contract["autonomous_enabled"]=False
        activity_state=person.get("autonomous_activity_state") if isinstance(person.get("autonomous_activity_state"),dict) else None
        if activity_state is not None:
            activity_state["enabled"]=False
            activity_state.pop("next_due",None)
        # A dead individual can retain durable rank/history, but cannot remain the
        # current holder of a live billet or command span.  Current command refs
        # are cleared here; succession below establishes any replacement.
        career=person.get("career_state") if isinstance(person.get("career_state"),dict) else None
        if career is not None:
            career["current_billet"]="deceased"; career["current_command_span"]=0
        assignment=person.get("command_assignment") if isinstance(person.get("command_assignment"),dict) else None
        if assignment is not None:
            assignment["billet"]="deceased"; assignment["current_command_span"]=0
            assignment.pop("command_group_ref",None); assignment.pop("formation_ref",None)
        self.put(person_path, person)

        # Death is terminal for exact-person scheduler and career routing. A dead
        # person may remain readable history, but must not keep receiving annual
        # person wakes, standing training, military-career reviews, or faction
        # alignment consideration. Remove those projections immediately so the
        # current transaction cannot leave a mechanically active corpse behind.
        runtime=_deepcopy(self.read("state/runtime.json")); hosts=runtime.get("hosts",{}); events=runtime.get("events",[])
        retired_host_ids=[]
        if isinstance(hosts,dict):
            for host_id,host in list(hosts.items()):
                if not isinstance(host,dict):
                    continue
                refs=host.get("routed_person_refs")
                if isinstance(refs,list) and person_ref in refs:
                    host["routed_person_refs"]=[ref for ref in refs if ref!=person_ref]
                if str(host.get("kind",""))=="person" and str(host.get("owner_ref",""))==person_ref:
                    hosts.pop(host_id,None); retired_host_ids.append(str(host_id))
        if retired_host_ids and isinstance(events,list):
            dead_hosts=set(retired_host_ids)
            runtime["events"]=[row for row in events if not (isinstance(row,Mapping) and row.get("target_host") in dead_hosts)]
        mark_scheduler_dirty(runtime,f"named_person_death:{person_ref}")
        self.put("state/runtime.json",runtime)

        career_index_path="state/military/career-network/index.json"
        career_index=_deepcopy(self.read_optional(career_index_path) or {})
        if isinstance(career_index,dict):
            people=career_index.get("people") if isinstance(career_index.get("people"),dict) else {}
            people.pop(person_ref,None); career_index["people"]=people
            career_index["public_commander_refs"]=[ref for ref in career_index.get("public_commander_refs",[]) if ref!=person_ref]
            career_index["routed_person_count"]=len(people)
            career_index["last_route_sync_at"]=at
            self.put(career_index_path,career_index)
        remove_alignment_candidate(self,person_ref)
        # Remove the exact person from every routed formation command assignment
        # without a directory scan.
        cidx=self._commander_index(); assignments=list(cidx.get("assignments",{}).get(person_ref,[]))
        for formation_ref in assignments:
            try:
                fp,formation0=self._load_formation(str(formation_ref)); formation=_deepcopy(formation0)
            except ValueError:
                continue
            if formation.get("commander_ref")==person_ref:
                formation["commander_ref"]=None; formation["status"]="commander_vacant" if int(formation.get("personnel",0))>0 else formation.get("status"); self.put(fp,formation)
            self._release_commander_index(person_ref,str(formation_ref))
        # Zero-body command groups are a separate live command authority from
        # formations. A person may command more than one group and may also hold
        # additive staff duty elsewhere, so death cleanup must use complete routing
        # projections rather than one historical primary slot.
        group_index_path="state/cmd/command-groups/index.json"
        group_index=_deepcopy(self.read(group_index_path))
        group_refs=[str(ref) for ref in group_index.get("refs",[]) if isinstance(ref,str)]
        command_routes=group_index.get("command_person_groups") if isinstance(group_index.get("command_person_groups"),dict) else command_routing_from_groups(self.read,group_refs)
        staff_routes=group_index.get("staff_person_groups") if isinstance(group_index.get("staff_person_groups"),dict) else staff_routing_from_groups(self.read,group_refs)
        affected_groups=set(str(ref) for ref in command_routes.get(person_ref,[]) if isinstance(ref,str))
        affected_groups.update(str(ref) for ref in staff_routes.get(person_ref,[]) if isinstance(ref,str))
        legacy_primary=group_index.get("primary_person_group",{}).get(person_ref) if isinstance(group_index.get("primary_person_group"),dict) else None
        if isinstance(legacy_primary,str) and legacy_primary:
            affected_groups.add(legacy_primary)
        promoted_candidates:set[str]=set()

        def promote_vacated_descendant(group_ref: str, *, excluded: set[str]) -> str | None:
            """Fill one vacated descendant army from its explicit successor list.

            Parent-command succession can promote a subordinate general upward. That
            must not destroy the subordinate army or leave it needlessly leaderless
            when the child command already names a lawful successor. A successor who
            commands one of the child's direct/descendant formations may step up; the
            lower formation billet becomes vacant for ordinary staffing/replacement.
            Nested-army commanders are skipped here to avoid recursive double-hat
            promotion chains inside one death settlement.
            """
            path=f"state/cmd/command-groups/{group_ref}.json"
            try:
                doc=_deepcopy(self.read(path))
            except (FileNotFoundError,KeyError,ValueError):
                return None
            if doc.get("commander_ref") not in {None, ""}:
                return str(doc.get("commander_ref"))
            descendant_group_refs:set[str]=set()
            descendant_formation_refs:set[str]=set()
            stack=[group_ref]; seen:set[str]=set()
            while stack:
                cursor=stack.pop()
                if cursor in seen:
                    continue
                seen.add(cursor)
                cursor_doc=doc if cursor==group_ref else self.read(f"state/cmd/command-groups/{cursor}.json")
                for unit in cursor_doc.get("units",[]):
                    if not isinstance(unit,Mapping) or not isinstance(unit.get("ref"),str):
                        continue
                    if unit.get("kind")=="nested_army":
                        descendant_group_refs.add(unit["ref"]); stack.append(unit["ref"])
                    elif unit.get("kind")=="formation":
                        descendant_formation_refs.add(unit["ref"])
            for successor in list(doc.get("successor_refs",[])):
                if not isinstance(successor,str) or not successor or successor in excluded:
                    continue
                try:
                    successor_path,successor_person=self._command_person(successor)
                except (KeyError,ValueError,FileNotFoundError):
                    continue
                if str(successor_person.get("life_status",successor_person.get("status","active"))).lower() in {"dead","deceased"}:
                    continue
                # Do not recursively steal another nested army's commander in the
                # same transaction. Formation commanders can lawfully step up.
                if any(ref in descendant_group_refs for ref in command_routes.get(successor,[])):
                    continue
                commander_index=self._commander_index()
                for formation_ref in list(commander_index.get("assignments",{}).get(successor,[])):
                    if formation_ref not in descendant_formation_refs:
                        continue
                    try:
                        fp,f0=self._load_formation(formation_ref)
                    except ValueError:
                        continue
                    f=_deepcopy(f0)
                    if f.get("commander_ref")==successor:
                        f["commander_ref"]=None
                        if int(f.get("personnel",0))>0:
                            f["status"]="commander_vacant"
                        self.put(fp,f)
                        self._release_commander_index(successor,formation_ref)
                doc["commander_ref"]=successor
                doc["successor_refs"]=[ref for ref in doc.get("successor_refs",[]) if ref!=successor]
                org=doc.setdefault("organizational_state",{})
                if isinstance(org,dict):
                    org["status"]="active"
                doc["updated_at"]=at
                self.put(path,doc)
                span=int(org.get("current_recursive_strength",0) or 0) if isinstance(org,Mapping) else 0
                assignment=successor_person.setdefault("command_assignment",{})
                if isinstance(assignment,dict):
                    assignment.update({"billet":"army_commander","command_group_ref":group_ref,"formation_ref":group_ref,"current_command_span":span,"external_to_fighting_establishment":True})
                    assignment.pop("secondary_command_group_refs",None)
                successor_person.pop("current_formation_id",None)
                military=successor_person.setdefault("military_command",{})
                if isinstance(military,dict):
                    military.update({"formation_scope":group_ref,"level":f"{span}_commander","external_to_fighting_strength":True})
                    parent_ref=doc.get("parent_command_group_ref")
                    if isinstance(parent_ref,str) and parent_ref:
                        try:
                            higher=self.read(f"state/cmd/command-groups/{parent_ref}.json").get("commander_ref")
                        except (FileNotFoundError,KeyError,ValueError):
                            higher=None
                        if isinstance(higher,str) and higher:
                            military["higher_commander_ref"]=higher
                        else:
                            military.pop("higher_commander_ref",None)
                    else:
                        military.pop("higher_commander_ref",None)
                career=successor_person.setdefault("career_state",{})
                if isinstance(career,dict):
                    career["current_billet"]="army_commander"
                    career["current_command_span"]=span
                self.put(successor_path,successor_person)
                promoted_candidates.add(successor)
                return successor
            return None

        for group_ref in sorted(affected_groups):
            group_path=f"state/cmd/command-groups/{group_ref}.json"
            try:
                group=_deepcopy(self.read(group_path))
            except (FileNotFoundError,KeyError,ValueError):
                continue
            was_commander=str(group.get("commander_ref") or "")==person_ref
            group["direct_person_refs"]=[str(ref) for ref in group.get("direct_person_refs",[]) if str(ref)!=person_ref]
            if isinstance(group.get("role_assignments"),dict):
                group["role_assignments"].pop(person_ref,None)
            group["successor_refs"]=[str(ref) for ref in group.get("successor_refs",[]) if str(ref)!=person_ref]
            replacement=None
            if was_commander:
                # Command continuity comes only from explicit successor order.
                # A successor may already command a descendant or secondary group;
                # that existing command is preserved rather than blocking lawful
                # promotion or forcing a duplicate person record.
                for candidate in list(group.get("successor_refs",[])):
                    if not isinstance(candidate,str) or not candidate or candidate==person_ref:
                        continue
                    try:
                        candidate_path,candidate_person=self._command_person(candidate)
                    except (KeyError,ValueError,FileNotFoundError):
                        continue
                    if str(candidate_person.get("life_status",candidate_person.get("status","active"))).lower() in {"dead","deceased"}:
                        continue
                    # A lawful successor may already command a descendant Unit.
                    # Promotion to this parent command must vacate that descendant
                    # billet first; otherwise death succession would recreate the
                    # parent/child double-hat that the standing hierarchy forbids.
                    descendant_group_refs=set()
                    descendant_formation_refs=set()
                    stack=[group_ref]
                    seen=set()
                    while stack:
                        cursor=stack.pop()
                        if cursor in seen:
                            continue
                        seen.add(cursor)
                        cursor_doc=group if cursor==group_ref else self.read(f"state/cmd/command-groups/{cursor}.json")
                        for unit in cursor_doc.get("units",[]):
                            if not isinstance(unit,Mapping) or not isinstance(unit.get("ref"),str):
                                continue
                            if unit.get("kind")=="nested_army":
                                descendant_group_refs.add(unit["ref"]); stack.append(unit["ref"])
                            elif unit.get("kind")=="formation":
                                descendant_formation_refs.add(unit["ref"])

                    for prior_group_ref in list(command_routes.get(candidate,[])):
                        if prior_group_ref not in descendant_group_refs:
                            continue
                        prior_path=f"state/cmd/command-groups/{prior_group_ref}.json"
                        prior_group=_deepcopy(self.read(prior_path))
                        if prior_group.get("commander_ref")==candidate:
                            prior_group["commander_ref"]=None
                            prior_org=prior_group.setdefault("organizational_state",{})
                            if isinstance(prior_org,dict):
                                prior_org["status"]="commander_vacant"
                            prior_group["updated_at"]=at
                            self.put(prior_path,prior_group)
                            promote_vacated_descendant(prior_group_ref, excluded={candidate, person_ref})

                    current_commander_index=self._commander_index()
                    for prior_formation_ref in list(current_commander_index.get("assignments",{}).get(candidate,[])):
                        if prior_formation_ref not in descendant_formation_refs:
                            continue
                        try:
                            prior_fp,prior_formation0=self._load_formation(prior_formation_ref)
                        except ValueError:
                            continue
                        prior_formation=_deepcopy(prior_formation0)
                        if prior_formation.get("commander_ref")==candidate:
                            prior_formation["commander_ref"]=None
                            if int(prior_formation.get("personnel",0))>0:
                                prior_formation["status"]="commander_vacant"
                            self.put(prior_fp,prior_formation)
                            self._release_commander_index(candidate,prior_formation_ref)

                    replacement=candidate
                    group["commander_ref"]=candidate
                    group["successor_refs"]=[ref for ref in group.get("successor_refs",[]) if ref!=candidate]
                    # A staff role on this same group ends when the person becomes
                    # its commander. Staff appointments on unrelated groups remain.
                    group["direct_person_refs"]=[ref for ref in group.get("direct_person_refs",[]) if ref!=candidate]
                    if isinstance(group.get("role_assignments"),dict):
                        group["role_assignments"].pop(candidate,None)
                    promoted_candidates.add(candidate)
                    command_span=int(group.get("organizational_state",{}).get("current_recursive_strength",0) or 0)
                    candidate_assignment=candidate_person.setdefault("command_assignment",{})
                    if isinstance(candidate_assignment,dict):
                        existing=[str(ref) for ref in command_routes.get(candidate,[]) if isinstance(ref,str) and ref!=group_ref and ref not in descendant_group_refs]
                        candidate_assignment.update({"billet":"army_commander","command_group_ref":group_ref,"formation_ref":group_ref,"current_command_span":command_span,"external_to_fighting_establishment":True})
                        if existing:
                            candidate_assignment["secondary_command_group_refs"]=sorted(set(existing))
                        else:
                            candidate_assignment.pop("secondary_command_group_refs",None)
                    candidate_person.pop("current_formation_id",None)
                    candidate_command=candidate_person.setdefault("military_command",{})
                    if isinstance(candidate_command,dict):
                        candidate_command.update({"formation_scope":group_ref,"level":f"{command_span}_commander","external_to_fighting_strength":True})
                        parent_ref=group.get("parent_command_group_ref")
                        if isinstance(parent_ref,str) and parent_ref:
                            try:
                                parent_commander=self.read(f"state/cmd/command-groups/{parent_ref}.json").get("commander_ref")
                            except (FileNotFoundError,KeyError,ValueError):
                                parent_commander=None
                            if isinstance(parent_commander,str) and parent_commander:
                                candidate_command["higher_commander_ref"]=parent_commander
                            else:
                                candidate_command.pop("higher_commander_ref",None)
                        else:
                            candidate_command.pop("higher_commander_ref",None)
                    candidate_career=candidate_person.setdefault("career_state",{})
                    if isinstance(candidate_career,dict):
                        candidate_career["current_billet"]="army_commander"
                        candidate_career["current_command_span"]=command_span
                    self.put(candidate_path,candidate_person)
                    break
                if replacement is None:
                    group["commander_ref"]=None
                    org=group.setdefault("organizational_state",{})
                    if isinstance(org,dict):
                        org["status"]="commander_vacant"
                else:
                    org=group.setdefault("organizational_state",{})
                    if isinstance(org,dict) and org.get("status")=="commander_vacant":
                        org["status"]="active"
            group["updated_at"]=at
            self.put(group_path,group)

        # Rebuild all non-authoritative command/staff routing from the exact groups.
        group_index["command_person_groups"]=command_routing_from_groups(self.read,group_refs)
        group_index["primary_person_group"]=primary_person_routing_from_groups(self.read,group_refs)
        group_index["staff_person_groups"]=staff_routing_from_groups(self.read,group_refs)
        self.put(group_index_path,group_index)

        # Synchronize a promoted successor's single-sheet convenience projection
        # without discarding any secondary commands. Exact command groups remain
        # authority for every command actually held.
        for candidate in sorted(promoted_candidates):
            try:
                candidate_path,candidate_person=self._command_person(candidate)
            except (KeyError,ValueError,FileNotFoundError):
                continue
            routes=list(group_index.get("command_person_groups",{}).get(candidate,[]))
            primary_ref=group_index.get("primary_person_group",{}).get(candidate)
            if isinstance(primary_ref,str) and primary_ref:
                assignment=candidate_person.setdefault("command_assignment",{})
                if isinstance(assignment,dict):
                    assignment["command_group_ref"]=primary_ref
                    secondary=[ref for ref in routes if ref!=primary_ref]
                    if secondary:
                        assignment["secondary_command_group_refs"]=secondary
                    else:
                        assignment.pop("secondary_command_group_refs",None)
                    try:
                        primary_group=self.read(f"state/cmd/command-groups/{primary_ref}.json")
                        span=int(primary_group.get("organizational_state",{}).get("current_recursive_strength",0) or 0)
                    except (FileNotFoundError,KeyError,ValueError):
                        span=0
                    assignment["current_command_span"]=span
                    candidate_person.setdefault("career_state",{})["current_command_span"]=span
                self.put(candidate_path,candidate_person)
        # Family records are exact authority: death causes widowhood and succession review.
        family_index_path="state/family/index.json"; fidx=_deepcopy(self.read(family_index_path)); source_refs=[]
        # Family retrieval is routed through the exact person's derived index.
        # Death never scans every union or succession in the world.
        person_family=fidx.get("person_index",{}).get(person_ref,{})
        for uid in list(person_family.get("unions",[])):
            up=fidx.get("unions",{}).get(str(uid))
            if not up: continue
            union=_deepcopy(self.read(up))
            if person_ref in union.get("participants",[]) and union.get("status")=="married":
                union["status"]="widowed"; union["widowed_at"]=at; self.put(up,union); source_refs.append(up)
        for sid in list(person_family.get("successions",[])):
            sp=fidx.get("successions",{}).get(str(sid))
            if not sp: continue
            succession=_deepcopy(self.read(sp))
            if str(succession.get("current_holder_id",""))!=person_ref:
                continue
            replacement=None
            for candidate in succession.get("candidate_order",[]):
                ref=str(candidate.get("person_id",""))
                if not ref or ref==person_ref: continue
                try: self._exact_person(ref); replacement=ref; break
                except ValueError: continue
            if replacement:
                succession["current_holder_id"]=replacement; succession["last_changed_at"]=at; succession["cause"]="death of prior holder"; self.put(sp,succession); source_refs.append(sp)
        if person_ref in fidx.get("person_index",{}):
            eid="family.death."+hashlib.sha256((person_ref+":"+at).encode()).hexdigest()[:12]; ep=f"state/family/events/{eid}.json"; event={"schema":"family-event","event_id":eid,"event_type":"death_family_settlement","occurred_at":at,"authority":True,"subject_refs":[person_ref],"source_refs":source_refs}; self.put(ep,event); fidx.setdefault("events",{})[eid]=ep; fidx.setdefault("counts",{})["events"]=len(fidx["events"]); pi=fidx.setdefault("person_index",{}).setdefault(person_ref,{}); pi.setdefault("events",[]).append(eid); self.put(family_index_path,fidx)
        if settle_force_body:
            self._settle_materialized_force_body_death(person_ref, force_body_snapshot, at, reason)
        hist=_deepcopy(self.read("state/history/events/index.json")); event_id="death_"+hashlib.sha256((person_ref+":"+at+":"+reason).encode()).hexdigest()[:16]; hist.setdefault("events",[]).append({"event_id":event_id,"kind":"named_person_death","at":at,"person_ref":person_ref,"reason":reason}); write_history_index(self, hist)

    def _record_reputation_signal(self, subject_ref: str, audience_ref: str, delta: int, dimension: str, source_event_ref: str, at: str, basis: str) -> str:
        if delta==0: raise ValueError("reputation signal cannot be zero")
        idxp="state/reputation/index.json"; idx=_deepcopy(self.read(idxp)); slug=lambda x: x.replace(".","-").replace("_","-").replace(":","-"); subject_path=idx.get("subjects",{}).get(subject_ref)
        if not subject_path:
            subject_path=f"state/reputation/subjects/{slug(subject_ref)}.json"; subject={"schema":"reputation-subject","subject_id":subject_ref,"subject_type":"person" if subject_ref.startswith("char_") else "organization","as_of":at,"authority":True,"audience_profiles":{},"institutional_status_sources":[],"notes":[]}; self.put(subject_path,subject); idx.setdefault("subjects",{})[subject_ref]=subject_path
        else: subject=_deepcopy(self.read(subject_path))
        existing_profile=subject.get("audience_profiles",{}).get(audience_ref); profile_path=existing_profile or f"state/reputation/audiences/{slug(subject_ref)}--{slug(audience_ref)}.json"; profile=_deepcopy(self.read_optional(profile_path) or {"schema":"reputation-audience-profile","subject_id":subject_ref,"audience_id":audience_ref,"as_of":at,"authority":True,"standing":{"overall":0},"dimensions":{},"evidence_count":0,"last_event_refs":[],"memory_class":"normal"}); eid="reputation."+hashlib.sha256((subject_ref+"|"+audience_ref+"|"+source_event_ref+"|"+dimension).encode()).hexdigest()[:16]; ep=f"state/reputation/events/{eid}.json"; new_event=self.read_optional(ep) is None
        if new_event:
            profile.setdefault("standing",{})["overall"]=_clamp(int(profile.get("standing",{}).get("overall",0))+delta,-100,100); profile.setdefault("dimensions",{})[dimension]=_clamp(int(profile.get("dimensions",{}).get(dimension,0))+delta,-100,100); self.put(ep,{"schema":"reputation-event","event_id":eid,"subject_id":subject_ref,"event_type":"material_conduct","occurred_at":at,"source_event_ref":source_event_ref,"authority":True,"signals":{dimension:delta},"standing_signals":{"overall":delta},"visibility":{"audience_ref":audience_ref,"basis":basis},"witnesses":[audience_ref],"report_routes":[],"deliveries":{},"status":"settled"}); profile["evidence_count"]=int(profile.get("evidence_count",0))+1; profile.setdefault("last_event_refs",[]).append(eid); profile["last_event_refs"]=profile["last_event_refs"][-16:]; idx["event_count"]=int(idx.get("event_count",0))+1
        profile["as_of"]=at; self.put(profile_path,profile); subject.setdefault("audience_profiles",{})[audience_ref]=profile_path; subject["as_of"]=at; self.put(subject_path,subject); idx["subject_count"]=len(idx.get("subjects",{})); idx["audience_profile_count"]=int(idx.get("audience_profile_count",0))+(1 if existing_profile is None else 0); self.put(idxp,idx); return eid

    def _award_career_merit(self, person_ref: str, merit: int, evidence_ref: str, at: str, appraisal: Optional[Mapping[str,Any]] = None) -> Optional[str]:
        if merit<=0: return None
        pp,person0=self._exact_person(person_ref,active=False); person=_deepcopy(person0)
        if str(person.get("life_status",person.get("status","active"))).lower() in {"dead","deceased"}: return None
        career=person.setdefault("career_state",{"merit_total":0,"qualifications":[],"grade":None,"appointments":[]}); career["merit_total"]=int(career.get("merit_total",0))+int(merit); rid="career."+hashlib.sha256((person_ref+"|"+evidence_ref+"|merit").encode()).hexdigest()[:14]
        hist=_deepcopy(self.read("state/history/events/index.json")); events=hist.setdefault("events",[])
        if not any(str(r.get("event_id"))==rid for r in events):
            event={"event_id":rid,"kind":"career_merit","at":at,"person_ref":person_ref,"merit":int(merit),"evidence_ref":evidence_ref}
            if isinstance(appraisal,Mapping): event["service_appraisal"]=_deepcopy(dict(appraisal))
            events.append(event)
        write_history_index(self,hist); self.put(pp,person)
        record_house_emergence_candidate(self, person_ref=person_ref, evidence_ref=rid, at=at)
        return rid

    def _settle_due_pregnancy(self, mother_ref: str, mother_path: str, mother: Dict[str, Any], at: str) -> Optional[str]:
        preg=mother.get("pregnancy_state")
        if not isinstance(preg,dict) or not preg.get("active") or not preg.get("due_at"): return None
        due=CampaignTime.parse(str(preg["due_at"])); review=CampaignTime.parse(at)
        if review<due: return None
        father_ref=str(preg.get("father_ref","")); self._exact_person(father_ref)
        idxp="state/family/index.json"; idx=_deepcopy(self.read(idxp)); union_ref=str(preg.get("union_ref","")); union_path=idx.get("unions",{}).get(union_ref)
        if not union_path: raise ValueError("saved pregnancy lost its exact union authority")
        union=_deepcopy(self.read(union_path))
        if union.get("status")!="married" or mother_ref not in union.get("participants",[]) or father_ref not in union.get("participants",[]): raise ValueError("saved pregnancy no longer has an active parental union")
        seed=hashlib.sha256((mother_ref+"|"+father_ref+"|"+str(due)).encode()).hexdigest(); child_ref=str(preg.get("child_ref") or ("char_child_"+seed[:16])); owners=self.read("state/index/owner-index.json").get("owners",{})
        if child_ref in owners:
            preg["active"]=False; preg["resolved_at"]=at; preg["child_ref"]=child_ref; mother["pregnancy_state"]=preg; self.put(mother_path,mother); return child_ref
        loc=self._person_location(mother); child_path=f"state/char/{child_ref.replace('char_','').replace('_','-')}.json"; birth_date=f"{due.bce_year}-BCE-{due.month:02d}-{due.day:02d}"
        child={"schema":"sab_character","owner_id":child_ref,"owner_type":"character","name":"Child "+seed[:6].upper(),"birth_date":birth_date,"body":{"adult_height_cm":160+int(seed[16:20],16)%18,"growth_end_age":18,"current_weight_kg":3.0+(int(seed[20:24],16)%9)/10.0,"frame":"infant","growth_profile_id":"human_height_to_18"},"appearance":40+int(seed[24:28],16)%61,"attributes":{},"skills":{},"aptitude":{"physical_learning":100,"technical_learning":100,"tactical_learning":100,"academic_learning":100,"social_learning":100},"development_state":{},"health_status":"healthy","life_status":"active","current_location":loc,"family":mother.get("family")}; self.put(child_path,child); self._register_owner(child_ref,child_path); self._ensure_person_life_host(child_ref,due)
        parentage_id=f"parentage.{child_ref.replace('char_','')}.birth_parents"; parpath=f"state/family/parentage/{parentage_id}.json"; parentage={"schema":"family-parentage","parentage_id":parentage_id,"child_id":child_ref,"authority":True,"parent_links":[{"parent_id":mother_ref,"kind":"biological"},{"parent_id":father_ref,"kind":"biological"}],"guardian_links":[]}; self.put(parpath,parentage); idx.setdefault("parentage",{})[parentage_id]=parpath
        def add_pi(ref: str,bucket: str,value: str) -> None:
            values=idx.setdefault("person_index",{}).setdefault(ref,{}).setdefault(bucket,[])
            if value not in values: values.append(value)
        add_pi(child_ref,"parentage",parentage_id); add_pi(mother_ref,"parentage",parentage_id); add_pi(father_ref,"parentage",parentage_id)
        hpath=union.get("household_ref")
        if isinstance(hpath,str):
            household=_deepcopy(self.read(hpath)); deps=household.setdefault("dependent_refs",[])
            if child_ref not in deps: deps.append(child_ref)
            self.put(hpath,household); add_pi(child_ref,"households",str(household.get("household_id")))
        eid="family.autobirth."+seed[:16]; ep=f"state/family/events/{eid}.json"; event={"schema":"family-event","event_id":eid,"event_type":"birth","occurred_at":str(due),"authority":True,"subject_refs":[mother_ref,father_ref,child_ref],"source_refs":[union_path,parpath]+([hpath] if isinstance(hpath,str) else []),"settled_at":at}; self.put(ep,event); idx.setdefault("events",{})[eid]=ep; idx.setdefault("counts",{})["events"]=len(idx["events"]); idx["counts"]["parentage"]=len(idx.get("parentage",{})); add_pi(mother_ref,"events",eid); add_pi(father_ref,"events",eid); add_pi(child_ref,"events",eid); self.put(idxp,idx)
        preg["active"]=False; preg["resolved_at"]=at; preg["child_ref"]=child_ref; mother["pregnancy_state"]=preg; self.put(mother_path,mother)
        house_ref=mother.get("family");
        if isinstance(house_ref,str):
            try:
                hp=self.owner_path(house_ref); house=_deepcopy(self.read(hp)); register_exact_house_lineage_member(self, house, person_ref=child_ref, at=str(due)); self.put(hp,house)
            except (KeyError,ValueError): pass
        hist=_deepcopy(self.read("state/history/events/index.json")); hist.setdefault("events",[]).append({"event_id":"birth_"+seed[:16],"kind":"named_person_birth","at":str(due),"settled_at":at,"person_ref":child_ref,"mother_ref":mother_ref,"father_ref":father_ref}); write_history_index(self, hist); return child_ref

    def _settle_person_family_life_stage(self, person_ref: str, person: Dict[str, Any], review: CampaignTime) -> None:
        """Settle exact household dependency/majority from routed family authority only.

        Stable annual reviews are read-mostly.  Keep exact parentage and household
        checks live, but clone the family index/household owner only when a durable
        change is actually required.  This preserves causal behavior without making
        long horizons repeatedly copy large unchanged registries.
        """
        idxp = "state/family/index.json"
        idx_ro = self.read(idxp)
        if not isinstance(idx_ro, Mapping):
            return
        person_index_ro = idx_ro.get("person_index", {}) if isinstance(idx_ro.get("person_index"), Mapping) else {}
        pi_ro = person_index_ro.get(person_ref, {}) if isinstance(person_index_ro.get(person_ref), Mapping) else {}
        idx_mut: Dict[str, Any] | None = None
        pi_mut: Dict[str, Any] | None = None
        age = age_years(person, review)
        previous = str(person.get("family_life_stage", ""))
        location = self._person_location(person)
        touched_households: list[str] = []

        def current_idx() -> Mapping[str, Any]:
            return idx_mut if idx_mut is not None else idx_ro

        def current_pi() -> Mapping[str, Any]:
            return pi_mut if pi_mut is not None else pi_ro

        def mutable_index() -> tuple[Dict[str, Any], Dict[str, Any]]:
            nonlocal idx_mut, pi_mut
            if idx_mut is None:
                idx_mut = _deepcopy(idx_ro)
                pi_mut = idx_mut.setdefault("person_index", {}).setdefault(person_ref, {})
            assert pi_mut is not None
            return idx_mut, pi_mut

        def add_pi(bucket: str, value: str) -> None:
            _idx, pi = mutable_index()
            values = pi.setdefault(bucket, [])
            if value not in values:
                values.append(value)

        def emit(event_type: str, sources: list[str], *, history_kind: str | None = None) -> None:
            eid = "family.life." + hashlib.sha256((person_ref + "|" + event_type + "|" + str(review)).encode()).hexdigest()[:16]
            events = current_idx().get("events", {}) if isinstance(current_idx().get("events"), Mapping) else {}
            if eid in events:
                return
            idx, _pi = mutable_index()
            ep = f"state/family/events/{eid}.json"
            self.put(ep, {
                "schema": "family-event",
                "event_id": eid,
                "event_type": event_type,
                "occurred_at": str(review),
                "authority": True,
                "subject_refs": [person_ref],
                "source_refs": sources,
            })
            idx.setdefault("events", {})[eid] = ep
            idx.setdefault("counts", {})["events"] = len(idx["events"])
            add_pi("events", eid)
            if history_kind:
                history_path = "state/history/events/index.json"
                staged = getattr(self, "_writes", {})
                staged_history = staged.get(history_path) if isinstance(staged, dict) else None
                hist = staged_history if isinstance(staged_history, dict) else _deepcopy(self.read(history_path))
                hist.setdefault("events", []).append({
                    "event_id": "history_" + eid.replace("family.life.", ""),
                    "kind": history_kind,
                    "at": str(review),
                    "person_ref": person_ref,
                    "age": age,
                    "family_event_ref": ep,
                })
                write_history_index(self, hist)

        # A minor with exact biological parentage may be attached only to a
        # household already shared by the saved parents and only when residence
        # is physically compatible. This completes sparse family routing from
        # saved parentage without inventing parentage or a new household.
        if age < 18:
            household_ids = [str(x) for x in current_pi().get("households", [])]
            if not household_ids:
                parent_refs: list[str] = []
                idx_view = current_idx()
                parentage_index = idx_view.get("parentage", {}) if isinstance(idx_view.get("parentage"), Mapping) else {}
                for par_id in current_pi().get("parentage", []):
                    par_path = parentage_index.get(str(par_id))
                    if not par_path:
                        continue
                    par = self.read(par_path)
                    if str(par.get("child_id", "")) != person_ref:
                        continue
                    parent_refs.extend(str(x.get("parent_id")) for x in par.get("parent_links", []) if x.get("parent_id"))
                parent_households: list[set[str]] = []
                person_index = idx_view.get("person_index", {}) if isinstance(idx_view.get("person_index"), Mapping) else {}
                for pref in sorted(set(parent_refs)):
                    pref_index = person_index.get(pref, {}) if isinstance(person_index.get(pref), Mapping) else {}
                    vals = {str(x) for x in pref_index.get("households", [])}
                    if vals:
                        parent_households.append(vals)
                shared = set.intersection(*parent_households) if parent_households else set()
                household_index = idx_view.get("households", {}) if isinstance(idx_view.get("households"), Mapping) else {}
                for hid in sorted(shared):
                    hpath = household_index.get(hid)
                    if not hpath:
                        continue
                    household_ro = self.read(hpath)
                    residence = household_ro.get("residence_ref")
                    if location and residence and str(location) != str(residence):
                        continue
                    deps = household_ro.get("dependent_refs", []) if isinstance(household_ro.get("dependent_refs"), list) else []
                    if person_ref not in deps:
                        household = _deepcopy(household_ro)
                        household.setdefault("dependent_refs", []).append(person_ref)
                        self.put(hpath, household)
                        touched_households.append(hpath)
                    add_pi("households", hid)
                    household_ids.append(hid)
                    break
            else:
                household_index = current_idx().get("households", {}) if isinstance(current_idx().get("households"), Mapping) else {}
                for hid in household_ids:
                    hpath = household_index.get(hid)
                    if not hpath:
                        continue
                    household_ro = self.read(hpath)
                    deps = household_ro.get("dependent_refs", []) if isinstance(household_ro.get("dependent_refs"), list) else []
                    if person_ref in deps:
                        continue
                    residence = household_ro.get("residence_ref")
                    if not location or not residence or str(location) == str(residence):
                        household = _deepcopy(household_ro)
                        household.setdefault("dependent_refs", []).append(person_ref)
                        self.put(hpath, household)
                        touched_households.append(hpath)
            person["family_life_stage"] = "child"
            if touched_households and previous != "child":
                emit("dependent_household_registered", touched_households)
        else:
            transitioned = previous == "child" or not previous
            household_index = current_idx().get("households", {}) if isinstance(current_idx().get("households"), Mapping) else {}
            for hid in list(current_pi().get("households", [])):
                hpath = household_index.get(str(hid))
                if not hpath:
                    continue
                household_ro = self.read(hpath)
                deps = household_ro.get("dependent_refs", []) if isinstance(household_ro.get("dependent_refs"), list) else []
                members = household_ro.get("member_refs", []) if isinstance(household_ro.get("member_refs"), list) else []
                residence = household_ro.get("residence_ref")
                remove_dependent = person_ref in deps
                add_member = person_ref not in members and (not location or not residence or str(location) == str(residence))
                if not remove_dependent and not add_member:
                    continue
                household = _deepcopy(household_ro)
                if remove_dependent:
                    household.setdefault("dependent_refs", [])[:] = [x for x in household.get("dependent_refs", []) if str(x) != person_ref]
                if add_member and person_ref not in household.setdefault("member_refs", []):
                    household["member_refs"].append(person_ref)
                self.put(hpath, household)
                touched_households.append(hpath)
            person["family_life_stage"] = "elder" if age >= 60 else "adult"
            if transitioned:
                emit("dependent_came_of_age", touched_households, history_kind="named_person_majority")

        if idx_mut is not None:
            idx_mut.setdefault("counts", {})["events"] = len(idx_mut.get("events", {}))
            self.put(idxp, idx_mut)

    def _validate_command_semantics(self, command: CommandEnvelope, payload: Mapping[str, Any]) -> None:
        # Chronology is server-owned. Requests bind to the exact world instant
        # represented by expected_revision; callers cannot forge future/past events.
        now = self._world_time()
        if CampaignTime.parse(command.submitted_at) != now:
            raise ValueError("submitted_at must equal authoritative campaign world time")
        t = command.command_type
        if t not in COMMAND_TYPES:
            raise ValueError("unsupported Sword semantic command: %s" % t)
        allowed_keys = COMMAND_PAYLOAD_KEYS.get(t)
        if allowed_keys is None:
            raise ValueError(f"semantic command has no payload contract: {t}")
        unknown_keys = sorted(set(payload) - set(allowed_keys))
        if unknown_keys:
            raise ValueError(f"unsupported payload fields for {t}: {unknown_keys}")

        if t == "strategic_crossing_action":
            require_text(payload, "route_ref")
            require_text(payload, "action", allowed={"set_water_stage","damage_bridge","repair_bridge","damage_ferries","restore_ferries","open_ford","close_ford"})
            if str(payload.get("action")) == "set_water_stage":
                require_text(payload, "water_stage", allowed={"low","normal","high","flood"})
            if str(payload.get("action")) in {"damage_bridge","repair_bridge"}:
                require_int(payload, "amount", minimum=1, maximum=100)
            if str(payload.get("action")) in {"damage_ferries","restore_ferries"}:
                require_int(payload, "quantity", minimum=1, maximum=1000)
        if t == "scene_consequence":
            require_text(payload, "summary", max_length=4000)
        if t == "travel":
            self._location_record(require_text(payload, "destination_ref"))
            require_text(payload, "mode", allowed={"foot","horse"}, default="foot")
        if t == "health_injury":
            require_text(payload, "severity", allowed={"minor","moderate","severe","critical"}, default="minor")
        if t in {"recruitment", "population_transfer", "formation_create"}:
            require_int(payload, "personnel", minimum=1, maximum=1_000_000)
            state = self._state_key(require_text(payload, "state"))
            pop = self.read(f"state/population/{state}.json")
            if t in {"recruitment","population_transfer"}:
                source = require_text(payload, "source_stratum", default="agricultural")
                if source not in pop.get("strata", {}): raise ValueError("unknown population source stratum")
            if t == "population_transfer":
                dest = require_text(payload, "destination_stratum", default="active_military")
                if dest not in pop.get("strata", {}): raise ValueError("unknown population destination stratum")
            if t in {"recruitment","formation_create"}:
                force = self.read(f"state/forces/state-{state}.json") if not (t=="formation_create" and payload.get("force_ref")) else self.read(self.owner_path(str(payload.get("force_ref"))))
                if t == "formation_create" and isinstance(payload.get("composition"), Mapping):
                    composition = {str(k): int(v) for k, v in payload["composition"].items() if int(v) > 0}
                    if not composition or sum(composition.values()) != int(payload["personnel"]):
                        raise ValueError("formation composition must contain positive role counts summing exactly to personnel")
                    for role in composition:
                        if role not in force.get("available_by_role", {}): raise ValueError("unknown force role in formation composition")
                else:
                    role = require_text(payload, "role", default="line_infantry")
                    if role not in force.get("available_by_role", {}): raise ValueError("unknown force role")
                if t == "formation_create":
                    current = int(payload["personnel"])
                    requested_class = str(payload.get("formation_class", "")).strip().lower() or ("unit" if current >= 500 else "detachment")
                    if requested_class not in {"unit", "detachment"}:
                        raise ValueError("formation_class must be unit or detachment")
                    if payload.get("authorized_strength") is None:
                        authorized = current
                    else:
                        authorized = require_int(payload, "authorized_strength", minimum=1, maximum=1_000_000)
                    validate_establishment(personnel=current, authorized_strength=authorized, formation_class=requested_class)
        if t == "person_materialize":
            state = self._state_key(require_text(payload, "state", default="qin")); require_text(payload, "person_ref")
            if self.read("state/index/owner-index.json").get("owners",{}).get(str(payload["person_ref"])):
                raise ValueError("person_ref already exists")
            if "personal_force_ref" in payload:
                if require_text(payload, "personal_force_ref") not in {"pforce.tang_wei", "force_tang_wei_personal"}:
                    raise ValueError("unsupported personal force")
                if "source_location_ref" in payload:
                    self._location_record(require_text(payload, "source_location_ref"))
                # Personal-force people materialize only from already conserved cohorts.
                if "source_stratum" in payload or "selection_profile" in payload:
                    raise ValueError("personal materialization cannot author recruitment origin or selection; materialize an existing cohort body")
        if t == "recruitment_campaign_start":
            state=self._state_key(require_text(payload,"state",default="qin"))
            if state != "qin": raise ValueError("Tang Wei recruitment campaign currently requires Qin population authority")
            require_text(payload,"campaign_ref"); require_int(payload,"applicant_count",minimum=2,maximum=100_000)
            require_text(payload,"destination_force_ref",default="force_tang_wei_personal"); require_text(payload,"role",default="household_retainer")
            self._location_record(require_text(payload,"location_ref",default="loc_tang_manor_garrison_yard"))
        if t == "recruitment_campaign_stage":
            require_text(payload,"campaign_ref"); require_text(payload,"selection_profile")
            if ("retain_count" in payload) == ("retain_fraction" in payload): raise ValueError("selection stage requires exactly one of retain_count or retain_fraction")
            if "retain_count" in payload: require_int(payload,"retain_count",minimum=1,maximum=100_000)
            if "retain_fraction" in payload:
                fraction=require_number(payload,"retain_fraction",minimum=0.0001,maximum=0.9999)
        if t == "recruitment_campaign_train":
            require_text(payload,"campaign_ref"); require_int(payload,"hours",minimum=1,maximum=56)
        if t in {"recruitment_campaign_finalize","recruitment_campaign_cancel"}:
            require_text(payload,"campaign_ref")
        if t == "formation_split":
            require_int(payload, "personnel", minimum=1, maximum=1_000_000)
            new_ref=require_text(payload, "new_formation_ref")
            source_ref=require_text(payload, "formation_ref")
            if not new_ref.startswith("formation_"):
                raise ValueError("new_formation_ref must use the formation_ namespace")
            if new_ref == source_ref:
                raise ValueError("split formation_ref must be distinct from its source")
            owners=self.read("state/index/owner-index.json").get("owners",{})
            if new_ref in owners:
                raise ValueError("new_formation_ref already exists")
        if t == "formation_reconstitute":
            require_int(payload, "target_personnel", minimum=1, maximum=1_000_000)
            if "equipment_units" in payload: require_int(payload, "equipment_units", minimum=0, maximum=1_000_000)
            if "replacement_composition" in payload and not isinstance(payload.get("replacement_composition"), Mapping):
                raise ValueError("replacement_composition must be an object of role counts")
            if "equipment_units_by_role" in payload and not isinstance(payload.get("equipment_units_by_role"), Mapping):
                raise ValueError("equipment_units_by_role must be an object of role counts")
        if t == "formation_equipment_repair":
            require_text(payload, "formation_ref")
            require_int(payload, "hours", minimum=1, maximum=720)
            if "categories" in payload:
                categories=require_list(payload,"categories",minimum=1,maximum=2)
                if any(str(x) not in {"shield","armor"} for x in categories):
                    raise ValueError("formation equipment repair categories must be shield and/or armor")
        if t in {"individual_training", "formation_train", "cohort_training"}:
            require_int(payload, "hours", minimum=1, maximum=12)
        if t == "health_recovery":
            require_int(payload, "hours", minimum=1, maximum=168)
        if t == "advance_time":
            if ("hours" in payload) == ("target_time" in payload):
                raise ValueError("advance_time requires exactly one of hours or target_time")
            if "hours" in payload: require_int(payload, "hours", minimum=1, maximum=876_000)
            if "target_time" in payload:
                target = CampaignTime.parse(require_text(payload, "target_time", max_length=64)); seconds = now.seconds_until(target)
                if seconds < 0 or seconds > 100 * 366 * 86400: raise ValueError("advance_time target must be within the next 100 years")
        if t == "relationship_change":
            require_text(payload, "target_ref"); delta = require_int(payload, "delta", minimum=-5, maximum=5)
            if delta == 0: raise ValueError("relationship delta must be non-zero")
            self._exact_person(str(payload.get("source_ref", command.actor_id))); self._exact_person(str(payload["target_ref"]))
            require_text(payload, "kind", allowed={"trust","affection","respect","fear","resentment","loyalty"}, default="trust")
        if t in {"market_purchase","market_sell"}:
            require_int(payload, "quantity", minimum=1, maximum=10_000); require_text(payload, "item_key")
        if t in {"economy_transfer", "enlisted_service_pay"}:
            require_int(payload, "amount_silver", minimum=1, maximum=1_000_000_000, default=7 if t == "enlisted_service_pay" else None)
            if t == "economy_transfer": require_text(payload, "direction", allowed={"player_to_state", "state_to_player"})
        if t == "resupply":
            values=[]
            for key in ("war_arrows","war_bolts","remount_horses","construction_material_units"):
                if key in payload: values.append(require_int(payload,key,minimum=0,maximum=1_000_000_000))
            if not values or not any(values): raise ValueError("resupply must request at least one positive material quantity")
        if t == "formation_move":
            self._location_record(require_text(payload,"destination_ref"))
        if t == "formation_create" and payload.get("doctrine_ref") is not None:
            doctrine_ref=require_text(payload,"doctrine_ref")
            doctrine_index=self.read("game/data/mil/doctrines.json").get("record_index",{})
            if doctrine_ref not in doctrine_index: raise ValueError("unknown formation doctrine_ref")
        if t == "formation_create" and payload.get("training_ref") is not None:
            training_ref=require_text(payload,"training_ref")
            training_index=self.read("game/data/mil/training.json").get("record_index",{})
            if training_ref not in training_index: raise ValueError("unknown formation training_ref")
        if t in {"command_assign","command_transfer","formation_assign","force_assignment"}:
            if payload.get("commander_ref") is not None: self._exact_person(str(payload["commander_ref"]))
        if t == "formation_doctrine_set":
            doctrine_ref=require_text(payload,"doctrine_ref")
            doctrine_index=self.read("game/data/mil/doctrines.json").get("record_index",{})
            if doctrine_ref not in doctrine_index: raise ValueError("unknown formation doctrine_ref")
            behavior=payload.get("doctrine_behavior",{})
            if not isinstance(behavior,dict): raise ValueError("doctrine_behavior must be an object")
            if "reserve_commitment" in behavior: require_int(behavior,"reserve_commitment",minimum=0,maximum=100)
            if "withdrawal_threshold" in behavior: require_int(behavior,"withdrawal_threshold",minimum=0,maximum=100)
            if "casualty_tolerance" in behavior: require_text(behavior,"casualty_tolerance",allowed={"low","moderate","high","extreme"})
        if t == "formation_training_set":
            training_ref=require_text(payload,"training_ref")
            training_index=self.read("game/data/mil/training.json").get("record_index",{})
            if training_ref not in training_index: raise ValueError("unknown formation training_ref")
        if t == "battle_resolve":
            attackers=require_list(payload,"attacker_formation_refs",minimum=1,maximum=128); defenders=require_list(payload,"defender_formation_refs",minimum=1,maximum=128)
            if set(map(str,attackers)) & set(map(str,defenders)): raise ValueError("a formation cannot fight on both sides")
            if ("battlefield_ref" in payload) != ("sector_ref" in payload):
                raise ValueError("operational battle contact requires both battlefield_ref and sector_ref")
            if "battlefield_ref" in payload:
                require_text(payload,"battlefield_ref",max_length=160); require_text(payload,"sector_ref",max_length=220); require_text(payload,"operation_ref",max_length=160)
                self._battlefield_validate_contact(operation_ref=str(payload["operation_ref"]), battlefield_ref=str(payload["battlefield_ref"]), sector_ref=str(payload["sector_ref"]), attacker_refs=[str(x) for x in attackers], defender_refs=[str(x) for x in defenders])
        if t == "battlefield_control":
            action=require_text(payload,"action",allowed={"open","assign","redeploy","set_order","record_terminal_evidence","close"})
            require_text(payload,"operation_ref",max_length=160); require_text(payload,"battlefield_ref",max_length=160)
            if action=="open":
                require_text(payload,"name",max_length=200); require_text(payload,"layout_ref",allowed={"battlefield.layout.line_three","battlefield.layout.deep_five"})
                if "side_refs" in payload:
                    sides=require_list(payload,"side_refs",minimum=2,maximum=2)
                    if len({str(x) for x in sides})!=2 or any(not str(x) for x in sides): raise ValueError("battlefield side_refs must be two distinct stable refs")
            elif action=="assign":
                require_text(payload,"formation_ref",max_length=160); require_text(payload,"side_ref",max_length=160); require_text(payload,"sector_ref",max_length=220)
                if "order" in payload: require_text(payload,"order",allowed={"hold","attack","breakthrough","delay","reserve","withdraw"})
            elif action=="redeploy":
                require_text(payload,"formation_ref",max_length=160); require_text(payload,"target_sector_ref",max_length=220)
                if "pace" in payload: require_text(payload,"pace",allowed={"forced","standard","cautious"})
                if "order" in payload: require_text(payload,"order",allowed={"hold","attack","breakthrough","delay","reserve","withdraw"})
            elif action=="set_order":
                require_text(payload,"formation_ref",max_length=160); require_text(payload,"order",allowed={"hold","attack","breakthrough","delay","reserve","withdraw"})
            elif action=="record_terminal_evidence":
                kind=require_text(payload,"termination_kind",allowed={"surrender","objective_complete","mutual_disengagement","non_renewal"})
                require_text(payload,"evidence_ref",max_length=240)
                if kind in {"surrender","objective_complete"}: require_text(payload,"winner_side_ref",max_length=160)
                if kind in {"mutual_disengagement","non_renewal"}: require_list(payload,"accepted_side_refs",minimum=2,maximum=2)
        if t == "personal_combat":
            opponent_refs=[]
            if "opponent_refs" in payload:
                opponent_refs=[str(x) for x in require_list(payload,"opponent_refs",minimum=1,maximum=31)]
            if "opponent_ref" in payload:
                legacy=require_text(payload,"opponent_ref")
                if legacy not in opponent_refs: opponent_refs.insert(0,legacy)
            if not opponent_refs: raise ValueError("personal combat requires opponent_ref or opponent_refs")
            if len(set(opponent_refs))!=len(opponent_refs): raise ValueError("personal combat opponent refs must be unique")
            ally_refs=[str(x) for x in require_list(payload,"ally_refs",minimum=1,maximum=31)] if "ally_refs" in payload else []
            if len(set(ally_refs))!=len(ally_refs): raise ValueError("personal combat ally refs must be unique")
            if set(opponent_refs) & set(ally_refs): raise ValueError("a personal combat participant cannot be on both sides")
            if len(opponent_refs)+len(ally_refs)+1>32: raise ValueError("personal combat exact scene is bounded to 32 participants")
            for participant_ref in opponent_refs+ally_refs:
                if participant_ref==self.PLAYER_ACTOR: raise ValueError("player cannot be listed as another personal combat participant")
                _, participant=self.owner(participant_ref)
                if not isinstance(participant,Mapping) or str(participant.get("schema")) not in {"sab_character","sword-materialized-person","person-lite"}: raise ValueError("personal combat participants must be individually represented saved people")
                life=str(participant.get("life_status",participant.get("status",participant.get("health",{}).get("status","active") if isinstance(participant.get("health"),Mapping) else "active"))).lower()
                if life in {"dead","deceased","destroyed","killed"}: raise ValueError("personal combat participant is not active")
            require_int(payload,"duration_minutes",minimum=1,maximum=240,default=60)
            if "distance_m" in payload:
                try: distance_m=float(payload.get("distance_m"))
                except (TypeError,ValueError): raise ValueError("personal combat distance_m must be numeric")
                if distance_m < 0.35 or distance_m > 400.0: raise ValueError("personal combat distance_m must be between 0.35 and 400")
            if "intent_sequence" in payload:
                sequence=require_list(payload,"intent_sequence",minimum=1,maximum=24)
                for i,step in enumerate(sequence):
                    if not isinstance(step,str) or not step.strip() or len(step)>240:
                        raise ValueError(f"personal combat intent_sequence[{i}] must be concise non-empty text")
            if "stop_on_decision" in payload and not isinstance(payload.get("stop_on_decision"),bool):
                raise ValueError("personal combat stop_on_decision must be boolean")
            if "target_ref" in payload:
                target_ref=require_text(payload,"target_ref")
                if target_ref not in opponent_refs: raise ValueError("personal combat target_ref must be one of opponent_refs")
            if "participant_positions" in payload:
                positions=payload.get("participant_positions")
                if not isinstance(positions,Mapping): raise ValueError("personal combat participant_positions must be an object keyed by exact participant ref")
                legal_position_refs={self.PLAYER_ACTOR,*opponent_refs,*ally_refs}
                for pref,row in positions.items():
                    if str(pref) not in legal_position_refs: raise ValueError("participant_positions contains a person outside this exact combat scene")
                    if not isinstance(row,Mapping): raise ValueError("each participant_positions entry must be an object")
                    for axis in ("x_m","y_m","facing_deg"):
                        if axis in row:
                            try: float(row.get(axis))
                            except (TypeError,ValueError): raise ValueError(f"participant_positions {axis} must be numeric")
            if "local_obstacles" in payload:
                obstacles=require_list(payload,"local_obstacles",minimum=0,maximum=24)
                for i,row in enumerate(obstacles):
                    if not isinstance(row,Mapping): raise ValueError(f"local_obstacles[{i}] must be an object")
                    kind=require_text(row,"kind",allowed={"circle","segment"},max_length=24)
                    numeric=("x_m","y_m","radius_m") if kind=="circle" else ("x1_m","y1_m","x2_m","y2_m")
                    for axis in numeric:
                        if axis not in row: raise ValueError(f"local_obstacles[{i}] missing {axis}")
                        try: value=float(row.get(axis))
                        except (TypeError,ValueError): raise ValueError(f"local_obstacles[{i}].{axis} must be numeric")
                        if not math.isfinite(value): raise ValueError(f"local_obstacles[{i}].{axis} must be finite")
                    if kind=="circle":
                        radius=float(row.get("radius_m"));
                        if radius<=0 or radius>20: raise ValueError(f"local_obstacles[{i}].radius_m must be >0 and <=20")
                    elif "clearance_m" in row:
                        try: clearance=float(row.get("clearance_m"))
                        except (TypeError,ValueError): raise ValueError(f"local_obstacles[{i}].clearance_m must be numeric")
                        if clearance<0 or clearance>5: raise ValueError(f"local_obstacles[{i}].clearance_m must be between 0 and 5")
                    if "label" in row and (not isinstance(row.get("label"),str) or len(str(row.get("label")))>120): raise ValueError(f"local_obstacles[{i}].label must be concise text")
        if t == "recover_projectiles":
            require_int(payload,"minutes",minimum=1,maximum=240)
            if "projectile_item_id" in payload: require_text(payload,"projectile_item_id",max_length=160)
        if t == "operation_create":
            require_text(payload,"operation_ref"); require_list(payload,"formation_refs",minimum=1,maximum=512); self._location_record(require_text(payload,"location_ref"))
        if t == "operation_transition":
            require_text(payload,"operation_ref"); require_text(payload,"status",allowed={"planned","mobilizing","active","engaged","occupied","completed","cancelled"})
        if t == "information_create":
            require_text(payload,"information_ref"); require_text(payload,"claim",default=str(payload.get("fact","")),max_length=4000); require_list(payload,"knowers",minimum=1,maximum=128)
            for ref in payload.get("knowers",[]): self._exact_person(str(ref))
        if t == "information_deliver":
            self._exact_person(require_text(payload,"target_ref",default=self.PLAYER_ACTOR)); require_text(payload,"information_ref")
            if command.actor_id==self.INTERNAL_ACTOR: self._exact_person(require_text(payload,"source_ref"))
        if t == "settlement_civic_action":
            action=require_text(payload,"action",allowed={"register_local_case","resolve_local_case","start_outbreak","set_quarantine","review_outbreak"})
            if action in {"register_local_case","start_outbreak"}:
                self._location_record(require_text(payload,"location_ref"))
            if action=="register_local_case":
                require_text(payload,"case_kind",allowed={"theft","violence","corruption","tax_dispute","banditry","desertion","property","contract","other"},default="other")
                require_int(payload,"severity",minimum=1,maximum=100,default=25)
                if payload.get("evidence_refs") is not None: require_list(payload,"evidence_refs",minimum=1,maximum=128)
            elif action=="resolve_local_case":
                require_text(payload,"case_ref"); require_text(payload,"disposition",allowed={"dismissed","remedy","sanction","escalated"})
            elif action=="start_outbreak":
                require_text(payload,"syndrome",max_length=240,default="undifferentiated febrile syndrome")
                require_text(payload,"transmission_route",allowed={"close_contact","water_food","vector","respiratory","wound_contact","unknown"},default="close_contact")
                require_int(payload,"known_cases",minimum=1,maximum=100000000,default=1)
                require_int(payload,"exposed_population",minimum=0,maximum=1000000000,default=max(1,int(payload.get("known_cases",1))*10))
                require_int(payload,"exposure_pressure",minimum=0,maximum=100,default=12)
                require_int(payload,"population_resistance",minimum=0,maximum=100,default=12)
                require_text(payload,"severity_band",allowed={"mild","moderate","severe","critical"},default="moderate")
                require_int(payload,"incubation_hours",minimum=1,maximum=24*60,default=48)
                require_int(payload,"infectious_hours",minimum=1,maximum=24*180,default=120)
            elif action=="set_quarantine":
                require_text(payload,"outbreak_ref"); require_int(payload,"quarantine_strength",minimum=0,maximum=100,default=50); require_int(payload,"supply_days",minimum=0,maximum=3650,default=0)
                if "active" in payload and not isinstance(payload.get("active"),bool): raise ValueError("settlement outbreak quarantine active must be boolean")
            elif action=="review_outbreak":
                require_text(payload,"outbreak_ref")
        if t in {"state_levy_call","state_levy_demobilize"}:
            state=self._state_key(require_text(payload,"state",default="qin"))
            require_text(payload,"levy_ref",max_length=160)
            if command.actor_id!=self.INTERNAL_ACTOR:
                _ap,actor=self._exact_person(command.actor_id)
                actor_state=str(actor.get("state","")).replace("state_","").lower()
                career=actor.get("career_state",{}) if isinstance(actor.get("career_state"),Mapping) else {}
                authorities={str(x) for x in career.get("authorities",[]) if isinstance(x,str)} if isinstance(career.get("authorities"),list) else set()
                office=str(career.get("office_or_command",career.get("office","")))
                if actor_state!=state or ("raise_state_levy" not in authorities and "Sovereign / royal office" not in office):
                    raise PermissionError("only sovereign state authority may call or demobilize a levy")
            if t=="state_levy_call":
                require_int(payload,"personnel",minimum=500,maximum=5_000_000); self._location_record(require_text(payload,"location_ref")); require_text(payload,"role",allowed={"line_infantry","missile_crossbow","cavalry","chariot"},default="line_infantry")
        if t == "state_action":
            action=require_text(payload,"action",allowed={"strategic_goal","appointment","enemy_action","record_threat","recognize_polity"},default="strategic_goal")
            self._state_key(require_text(payload,"state",default="qin"))
            if action=="appointment": self._exact_person(require_text(payload,"person_ref")); require_text(payload,"office")
            if action in {"enemy_action","record_threat"}:
                require_int(payload,"severity",minimum=0,maximum=100,default=50); self._state_key(require_text(payload,"source_state",default="zhao"))
                information_ref=payload.get("information_ref")
                if information_ref:
                    information_ref=require_text(payload,"information_ref")
                    info_path=self.read("state/information/index.json").get("claims",{}).get(information_ref)
                    if not info_path: raise ValueError("state threat information_ref is not an exact saved claim")
                    info=self.read(info_path)
                    if command.actor_id!=self.INTERNAL_ACTOR and command.actor_id not in info.get("knowers",[]):
                        raise PermissionError("state threat may cite only information already known by the acting exact person")
            if action=="recognize_polity":
                polity_ref=require_text(payload,"polity_ref")
                _polity_path,polity=self.owner(polity_ref)
                if str(polity.get("schema",""))!="sword-polity" or str(polity.get("status",""))=="dissolved": raise ValueError("recognition target is not an active sovereign polity")
        if t == "polity_action":
            polity_ref=require_text(payload,"polity_ref")
            _polity_path,polity=self.owner(polity_ref)
            if str(polity.get("schema","")) != "sword-polity" or str(polity.get("status","")) == "dissolved": raise ValueError("polity_action requires an active exact sovereign polity")
            action=require_text(payload,"action",allowed={"set_strategic_goal","set_occupation_policy","set_mobilization_policy","appoint_governor","authorize_war","propose_treaty","accept_treaty","reject_treaty","recognize_polity","break_treaty","defect_client_state","found_market","open_court_case","submit_court_evidence","decide_court_case","enforce_court_case","appeal_court_case","issue_decree","appoint_office","open_coalition_conference"})
            if action=="set_strategic_goal": require_text(payload,"goal",max_length=500)
            elif action=="set_occupation_policy":
                location_ref=require_text(payload,"location_ref"); self._location_record(location_ref); require_text(payload,"policy_key",allowed={"security_posture","elite_policy","recruitment_policy","relief_policy"}); require_text(payload,"policy_value",max_length=160)
            elif action=="set_mobilization_policy": require_text(payload,"policy_value",allowed={"demobilized","defensive","balanced","expeditionary","total_war"})
            elif action=="appoint_governor": self._location_record(require_text(payload,"location_ref")); self._exact_person(require_text(payload,"person_ref"))
            elif action=="authorize_war":
                target=require_text(payload,"target_ref"); location_ref=require_text(payload,"location_ref"); self._location_record(location_ref); require_text(payload,"war_goal",max_length=500)
                if target.startswith("state_"): self._state_key(target)
                elif target.startswith("polity_"):
                    _tp,td=self.owner(target)
                    if str(td.get("schema",""))!="sword-polity" or str(td.get("status",""))=="dissolved": raise ValueError("war target is not an active sovereign polity")
                else: raise ValueError("war target must be an exact state or sovereign polity")
                if target==polity_ref: raise ValueError("polity cannot authorize war against itself")
            elif action=="recognize_polity":
                if str(polity.get("status", "")) != "recognized_state" or str(polity.get("recognition_status", "")) != "recognized": raise PermissionError("only a recognized sovereign polity may extend sovereign recognition")
                target=require_text(payload,"target_ref")
                if not target.startswith("polity_"): raise ValueError("recognition target must be an exact sovereign polity")
                _tp,td=self.owner(target)
                if str(td.get("schema",""))!="sword-polity" or str(td.get("status",""))=="dissolved": raise ValueError("recognition target is not an active sovereign polity")
                if target==polity_ref: raise ValueError("polity cannot recognize itself")
            elif action=="propose_treaty":
                target=require_text(payload,"target_ref"); kind=require_text(payload,"treaty_kind",allowed={"alliance","nonaggression","tribute","military_access","guarantee","client_state","hostage_exchange","marriage_alliance","reparations","territorial_exchange","coalition"})
                if target.startswith("state_"): self._state_key(target)
                elif target.startswith("polity_"):
                    _tp,td=self.owner(target)
                    if str(td.get("schema",""))!="sword-polity" or str(td.get("status",""))=="dissolved": raise ValueError("treaty target is not an active sovereign polity")
                else: raise ValueError("treaty target must be an exact state or sovereign polity")
                if target==polity_ref: raise ValueError("polity cannot negotiate a treaty with itself")
                if kind in {"alliance","nonaggression","marriage_alliance","territorial_exchange","coalition"}:
                    direction=require_text(payload,"direction",allowed={"mutual"},default="mutual")
                else:
                    direction=require_text(payload,"direction",allowed={"proposer_to_target","target_to_proposer"})
                if kind in {"tribute","reparations"}: require_int(payload,"amount_silver",minimum=1,maximum=1_000_000_000)
                if kind=="hostage_exchange":
                    if payload.get("hostage_person_ref"): self._exact_person(require_text(payload,"hostage_person_ref"))
                    if payload.get("counter_hostage_person_ref"): self._exact_person(require_text(payload,"counter_hostage_person_ref"))
                    if not payload.get("hostage_person_ref") and not payload.get("counter_hostage_person_ref"): raise ValueError("hostage_exchange requires at least one exact hostage person")
                if kind=="marriage_alliance":
                    self._exact_person(require_text(payload,"marriage_person_ref")); self._exact_person(require_text(payload,"marriage_partner_ref"))
                if kind=="territorial_exchange":
                    offered=require_list(payload,"offer_location_refs",minimum=1,maximum=32); requested=require_list(payload,"request_location_refs",minimum=1,maximum=32)
                    for loc in offered+requested: self._location_record(str(loc))
                if kind=="coalition":
                    coalition_target=require_text(payload,"coalition_target_ref")
                    if coalition_target.startswith("state_"): self._state_key(coalition_target)
                    elif coalition_target.startswith("polity_"): self.owner(coalition_target)
                    else: raise ValueError("coalition target must be an exact sovereign")
                    if coalition_target in {polity_ref,target}: raise ValueError("coalition target cannot be a negotiating member")
                if "duration_days" in payload: require_int(payload,"duration_days",minimum=1,maximum=36500)
            elif action=="found_market":
                self._location_record(require_text(payload,"location_ref")); require_int(payload,"investment_silver",minimum=1,maximum=1_000_000_000); require_text(payload,"market_name",max_length=160,default="Sovereign Market")
            elif action=="open_court_case":
                require_text(payload,"case_kind",allowed={"petition","investigation","legal_dispute","corruption","office_competition","succession_recognition"}); require_text(payload,"subject_ref",max_length=200)
                if payload.get("location_ref"): self._location_record(require_text(payload,"location_ref"))
                if payload.get("victim_refs") is not None: require_list(payload,"victim_refs",minimum=1,maximum=128)
            elif action=="submit_court_evidence":
                require_text(payload,"case_ref"); require_list(payload,"evidence_refs",minimum=1,maximum=128)
            elif action=="decide_court_case": require_text(payload,"case_ref"); require_text(payload,"policy_value",allowed={"uphold","dismiss","compromise","sanction","remand"})
            elif action=="enforce_court_case":
                require_text(payload,"case_ref"); require_text(payload,"remedy_kind",allowed={"none","office_removal","fine","restitution","detention","release","execution"})
                if payload.get("amount_silver") is not None: require_int(payload,"amount_silver",minimum=1,maximum=1_000_000_000)
                if payload.get("custodian_formation_ref"): self._load_formation(require_text(payload,"custodian_formation_ref"))
                if payload.get("prisoner_group_ref"): self.owner(require_text(payload,"prisoner_group_ref"))
                if payload.get("recipient_ref"): self.owner(require_text(payload,"recipient_ref"))
                if payload.get("person_ref"): self._exact_person(require_text(payload,"person_ref"),active=False)
            elif action=="appeal_court_case": require_text(payload,"case_ref")
            elif action=="open_coalition_conference":
                coalition_target=require_text(payload,"coalition_target_ref")
                if coalition_target.startswith("state_"): self._state_key(coalition_target)
                elif coalition_target.startswith("polity_"): self.owner(coalition_target)
                else: raise ValueError("coalition target must be an exact sovereign")
                invitees=require_list(payload,"invitee_refs",minimum=1,maximum=128)
                for invitee in invitees:
                    invitee=str(invitee)
                    if invitee in {polity_ref,coalition_target}: raise ValueError("coalition conference invitee cannot be host or coalition target")
                    if invitee.startswith("state_"): self._state_key(invitee)
                    elif invitee.startswith("polity_"): self.owner(invitee)
                    else: raise ValueError("coalition conference invitees must be exact sovereigns")
                if "duration_days" in payload: require_int(payload,"duration_days",minimum=1,maximum=36500)
            elif action=="issue_decree": require_text(payload,"decree_text",max_length=2000)
            elif action=="appoint_office": self._exact_person(require_text(payload,"person_ref")); require_text(payload,"office_key",max_length=160)
            elif action in {"accept_treaty","reject_treaty"}:
                proposal_ref=require_text(payload,"proposal_ref")
                _proposal_path,proposal=self.owner(proposal_ref)
                if str(proposal.get("schema",""))!="sword-diplomatic-proposal": raise ValueError("proposal_ref is not an exact diplomatic proposal")
                if str(proposal.get("target_ref",""))!=polity_ref: raise PermissionError("polity may decide only diplomatic proposals addressed to itself")
                if str(proposal.get("status",""))!="pending_response": raise ValueError("diplomatic proposal is not awaiting this polity's response")
                if CampaignTime.parse(str(proposal.get("arrives_at")))>now: raise ValueError("diplomatic proposal has not arrived yet")
                if CampaignTime.parse(str(proposal.get("expires_at",proposal.get("arrives_at"))))<=now: raise ValueError("diplomatic proposal has expired")
            elif action=="break_treaty": require_text(payload,"treaty_ref")
            elif action=="defect_client_state":
                treaty_ref=require_text(payload,"treaty_ref"); registry=self.read("state/politics/treaties.json"); treaty=registry.get("records",{}).get(treaty_ref)
                if not isinstance(treaty,Mapping) or str(treaty.get("status",""))!="active" or str(treaty.get("kind",""))!="client_state": raise ValueError("client defection requires one exact active client-state treaty")
                if str((treaty.get("terms") or {}).get("client_ref",""))!=polity_ref: raise PermissionError("only the exact client polity may defect from its client-state treaty")
        if t == "fortification_materialize":
            require_int(payload,"integrity",minimum=1,maximum=100,default=100)
            self._location_record(require_text(payload,"location_ref")); require_list(payload,"garrison_formation_refs",minimum=1,maximum=512)
            if payload.get("commander_ref"): self._exact_person(str(payload["commander_ref"]))
        if t == "siege_start":
            require_text(payload,"siege_ref"); require_text(payload,"fortification_ref"); require_list(payload,"attacker_formation_refs",minimum=1,maximum=512)
        if t == "siege_action":
            require_text(payload,"siege_ref"); action=require_text(payload,"action",allowed={"blockade","build_work","ram_gate","repair","assault","withdraw","settle","relief","offer_surrender","accept_surrender_terms"})
            if action=="blockade":
                require_int(payload,"days",minimum=1,maximum=30,default=7)
                if payload.get("route_refs") is not None: require_list(payload,"route_refs",minimum=1,maximum=64)
            if action=="build_work":
                require_text(payload,"blueprint_ref"); require_text(payload,"source_formation_ref"); require_text(payload,"target",allowed={"gate","wall","investment"},default="wall"); require_int(payload,"quantity",minimum=1,maximum=1000,default=1)
            if action=="ram_gate":
                require_int(payload,"cycles",minimum=1,maximum=200,default=10)
                if payload.get("work_ref") is not None: require_text(payload,"work_ref")
            if action=="repair":
                require_text(payload,"source_formation_ref"); require_text(payload,"target",allowed={"gate","wall"},default="gate"); require_int(payload,"hours",minimum=1,maximum=168,default=12)
            sector_attackers = payload.get("attacker_formation_refs")
            sector_defenders = payload.get("defender_formation_refs")
            if action == "assault":
                require_text(payload,"target",allowed={"gate","wall"},default="gate"); require_text(payload,"method",allowed={"auto","breach","ladder","siege_tower","swim_grapnel"},default="auto")
                if (sector_attackers is None) != (sector_defenders is None):
                    raise ValueError("siege assault sector requires both attacker_formation_refs and defender_formation_refs")
                if sector_attackers is not None:
                    require_list(payload,"attacker_formation_refs",minimum=1,maximum=128)
                    require_list(payload,"defender_formation_refs",minimum=1,maximum=128)
            elif sector_attackers is not None or sector_defenders is not None:
                raise ValueError("siege sector formation refs apply only to assault")
            if "damage" in payload or "points" in payload: raise ValueError("siege structural outcomes are runtime-derived and may not be caller supplied")
        if t == "territorial_consequence":
            self._location_record(require_text(payload,"location_ref")); controller=require_text(payload,"controller")
            if controller.startswith("state_"):
                self._state_key(controller)
            elif controller.startswith("polity_"):
                _pp, polity = self.owner(controller)
                if str(polity.get("schema", "")) != "sword-polity": raise ValueError("territorial polity controller is not an exact sovereign authority")
                if str(polity.get("status", "")) not in {"territorial_authority", "proto_state", "recognized_state"}: raise ValueError("territorial polity controller is not active")
            else:
                raise ValueError("territorial controller must be an exact state or sovereign polity authority")
        if t == "family_event":
            kind=require_text(payload,"kind",allowed={"proposal","engagement","marriage","pregnancy","birth","death","widowhood","succession_review"})
            if kind in {"proposal","marriage"}: self._exact_person(require_text(payload,"person_ref")); self._exact_person(require_text(payload,"partner_ref"))
            elif kind=="engagement": require_text(payload,"proposal_ref")
            elif kind in {"pregnancy","birth"}:
                self._exact_person(require_text(payload,"mother_ref")); self._exact_person(require_text(payload,"father_ref"))
                if kind=="birth": require_text(payload,"child_ref")
            elif kind in {"death","widowhood"}: self._exact_person(require_text(payload,"person_ref"),active=(kind=="death"))
        if t in {"equipment_equip","equipment_unequip","equipment_transfer","equipment_issue","equipment_return","equipment_drop","equipment_loot","equipment_consume"}:
            item_id=require_text(payload,"item_key"); item=self._item_record(item_id); require_int(payload,"quantity",minimum=1,maximum=10_000,default=1)
            if t in {"equipment_transfer","equipment_issue","equipment_return"}: self._exact_person(require_text(payload,"target_ref"))
            if t=="equipment_consume" and str(item.get("economic_lifecycle","")) not in {"consumable_or_none","consumable"}: raise ValueError("equipment_consume requires an actual consumable item")
        if t == "reputation_event":
            self._exact_person(require_text(payload,"subject_ref")); delta=require_int(payload,"delta",minimum=-20,maximum=20)
            if delta==0: raise ValueError("reputation delta must be non-zero")
            audience=require_text(payload,"audience_ref")
            if audience.startswith("state_"): self._state_key(audience)
            elif audience.startswith("char_"): self._exact_person(audience)
            else: self.owner(audience)
        if t == "career_event":
            self._exact_person(require_text(payload,"person_ref")); kind=require_text(payload,"kind",allowed={"qualification","promotion","demotion","office_appointment","office_removal","relief","reserve","retirement","return_to_service","affiliation_add","affiliation_remove","merit"})
            if kind=="merit": require_int(payload,"merit",minimum=1,maximum=1000)
            if kind=="qualification": require_text(payload,"qualification_ref")
            if kind in {"promotion","demotion"}:
                career_rules=self.read("game/data/mechanics/military-career.json"); formal=set((career_rules.get("formal_rank_order") or {}).keys()); require_text(payload,"grade",allowed=formal)
            if kind in {"office_appointment","office_removal"}: require_text(payload,"office")
            if kind in {"affiliation_add","affiliation_remove"}: require_text(payload,"affiliation_ref")
        if t == "mercenary_contract":
            merc_ref=require_text(payload,"mercenary_ref"); _,merc=self.owner(merc_ref)
            if "mercenary" not in str(merc.get("schema","")): raise ValueError("mercenary_ref is not a mercenary company")
            action=require_text(payload,"action",allowed={"offer","accept","pay","deploy","breach","renew","complete"})
            if action in {"offer","pay","renew"}: require_int(payload,"amount_silver",minimum=1,maximum=100_000_000)
            if action=="offer": require_int(payload,"term_days",minimum=1,maximum=3650,default=90)
            else: require_text(payload,"contract_ref")
            if action=="deploy": self._location_record(require_text(payload,"location_ref"))
        if t == "institution_project":
            require_text(payload,"institution_ref"); require_int(payload,"duration_hours",minimum=1,maximum=8760,default=168); require_text(payload,"project_ref",default="project_"+command.semantic_digest[:8]); require_int(payload,"magnitude",minimum=1,maximum=1_000_000,default=1)
            kind=str(payload.get("kind","capacity"))
            if kind=="infrastructure":
                effect=payload.get("effect")
                if not isinstance(effect,dict): raise ValueError("infrastructure project requires a structured effect")
                if not isinstance(effect.get("infrastructure_blueprint_ref"),str) or not effect.get("infrastructure_blueprint_ref"): raise ValueError("infrastructure project requires effect.infrastructure_blueprint_ref")
                if not isinstance(effect.get("target_site_ref"),str) or not effect.get("target_site_ref"): raise ValueError("infrastructure project requires effect.target_site_ref")
            if kind=="settlement_foundation":
                effect=payload.get("effect")
                if not isinstance(effect,dict): raise ValueError("settlement foundation requires a structured effect")
                if not isinstance(effect.get("source_site_ref"),str) or not effect.get("source_site_ref"): raise ValueError("settlement foundation requires effect.source_site_ref")
                if not isinstance(effect.get("new_settlement_name"),str) or not effect.get("new_settlement_name").strip(): raise ValueError("settlement foundation requires effect.new_settlement_name")
                require_int(effect,"initial_settlers",minimum=1,maximum=1000)
        if t == "project_resolve":
            require_text(payload,"institution_ref"); require_text(payload,"project_ref")
        if t == "project_cancel":
            require_text(payload,"institution_ref"); require_text(payload,"project_ref")
        if t == "house_action":
            house_ref=require_text(payload,"house_ref",default="house_tang")
            action=require_text(payload,"action",allowed={"assign_duty","set_policy","grant_nobility","proclaim_territorial_authority"},default="assign_duty")
            if action=="assign_duty":
                self._exact_person(require_text(payload,"subject_ref")); require_text(payload,"duty",max_length=160)
            elif action=="set_policy":
                require_text(payload,"policy_key",max_length=120); require_text(payload,"policy_value",max_length=400)
            elif action=="grant_nobility":
                _hp, house=self.owner(house_ref)
                if str(house.get("schema",""))!="sword-house": raise ValueError("nobility target must be an exact House")
                rules=self.read(NOBILITY_RULES_PATH); target=require_text(payload,"target_grade",allowed=set(grade_order(rules)))
                grantor=require_text(payload,"grantor_ref"); self._exact_person(grantor)
                evidence=require_text(payload,"evidence_ref",max_length=240)
                evidence_saved=False
                try:
                    self.owner_path(evidence); evidence_saved=True
                except (KeyError,ValueError,FileNotFoundError):
                    evidence_saved=any(str(row.get("event_id",""))==evidence for row in iter_history_events(self))
                if not evidence_saved: raise ValueError("nobility advancement requires an exact saved evidence reference")
                if target==str((house.get("nobility") or {}).get("grade","recognized_house")): raise ValueError("nobility grant must advance House grade")
            else:
                self._location_record(require_text(payload,"location_ref")); require_text(payload,"operation_ref"); require_text(payload,"polity_name",default="Territorial Authority",max_length=120)


    def _find_route(self, origin: str, destination: str, *, mode: Optional[str] = None) -> Mapping[str, Any]:
        requested = (str(mode),) if mode is not None else ("horse", "foot")
        return geography_shortest_path(self.read, str(origin), str(destination), modes=requested)

    def _advance_runtime(self, target_text: str) -> Dict[str, Any]:
        runtime_path = "state/runtime.json"
        rt = _deepcopy(self.read(runtime_path))
        current = CampaignTime.parse(rt["world_time"])
        target = CampaignTime.parse(target_text)
        if target < current:
            raise ValueError("time may not move backward")
        battlefield_metrics = self._settle_operational_battlefields(current, target)
        if battlefield_metrics.get("player_interrupt"):
            target = CampaignTime.parse(str(battlefield_metrics.get("reached_time", target)))
            target_text = str(target)
        events = list(rt.get("events", []))
        hosts = rt.get("hosts", {})
        woken = 0
        processed = 0
        completed_event_ids: set[str] = set()
        # Only due queue is inspected. Owners are loaded only for due hosts.
        for event in sorted(events, key=lambda e: (CampaignTime.parse(e["due_at"]), e.get("priority", 100), e["event_id"])):
            due = CampaignTime.parse(event["due_at"])
            if due > target:
                continue
            host = hosts[event["target_host"]]
            recurrence = int(host.get("recurrence_seconds", 0))
            if recurrence <= 0:
                occurrences = 1
                successor = None
            else:
                delta = due.seconds_until(target)
                occurrences = int(delta // recurrence) + 1
                successor = due.add_seconds(occurrences * recurrence)
            woken += 1
            processed += occurrences
            kind = host.get("kind")
            if kind == "state":
                self._autonomy_state(host, occurrences, target_text)
            elif kind == "population":
                self._autonomy_population(host, occurrences, target_text)
            elif kind == "house":
                self._autonomy_house(host, occurrences, target_text)
            elif kind == "institution":
                self._autonomy_institution(host, occurrences, target_text)
            elif kind == "institution_bundle" and hasattr(self, "_autonomy_institution_bundle"):
                self._autonomy_institution_bundle(host, occurrences, target_text)
            elif kind == "faction":
                self._autonomy_faction(host, occurrences, target_text)
            elif kind == "polity" and hasattr(self, "_autonomy_polity"):
                self._autonomy_polity(host, occurrences, target_text)
            elif kind == "mercenary":
                self._autonomy_mercenary(host, occurrences, target_text)
            elif kind == "interstate":
                self._autonomy_interstate(host, occurrences, target_text)
            elif kind == "person":
                self._autonomy_person(host, occurrences, target_text)
            elif kind == "house_tang_training":
                self._autonomy_house_tang_training(host, occurrences, target_text)
            elif kind == "commission" and hasattr(self, "_autonomy_commission"):
                self._autonomy_commission(host, occurrences, target_text)
            host["resolved_through"] = target_text
            if successor is None:
                host["safe_through"] = target_text
                host["next_due"] = None
                completed_event_ids.add(str(event["event_id"]))
            else:
                host["next_due"] = successor.__str__()
                # Proven safe-horizon rule: safe through the instant before the known successor.
                host["safe_through"] = successor.add_seconds(-1).__str__()
                event["due_at"] = successor.__str__()
        if completed_event_ids:
            rt["events"] = [
                event for event in events
                if str(event.get("event_id")) not in completed_event_ids
            ]
        if isinstance(rt.get("scheduler"), dict):
            # The base engine is still used by low-level tooling/tests.  Keep its
            # clock compatible with scheduler-enabled campaign state, but mark
            # route coverage dirty because only the production planner performs
            # the complete cross-domain reconciliation contract.  The next
            # production time-bearing command reconciles immediately.
            set_causal_frontier(rt, target_text)
            mark_scheduler_dirty(rt, "base_engine_advance_requires_production_reconcile")
        else:
            rt["world_time"] = target_text
        metrics = rt.setdefault("metrics", {})
        metrics["hosts_woken"] = int(metrics.get("hosts_woken", 0)) + woken
        metrics["events_processed"] = int(metrics.get("events_processed", 0)) + processed
        for key in ("global_person_scans","global_faction_scans","global_force_scans","global_house_scans"):
            metrics.setdefault(key, 0)
        self.put(runtime_path, rt)
        return {
            "hosts_woken": woken,
            "events_processed": processed,
            "battlefield_reports": list(battlefield_metrics.get("delivered_reports", [])),
            "battlefield_player_interrupt": bool(battlefield_metrics.get("player_interrupt", False)),
            "battlefield_reviews": len(battlefield_metrics.get("reviews", [])) if isinstance(battlefield_metrics.get("reviews", []), list) else int(battlefield_metrics.get("reviews", 0)),
        }

    def _autonomy_person(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        person_ref=str(host["owner_ref"])
        try:
            person_path,person0=self._exact_person(person_ref,active=False)
            is_person_lite=False
        except ValueError:
            person_path,person0=self._command_person(person_ref,active=False)
            is_person_lite=str(person0.get("schema",""))=="person-lite"
            if not is_person_lite:
                raise
        person=_deepcopy(person0); life=str(person.get("life_status",person.get("status","active"))).lower()
        if life in {"dead","deceased"}:
            person.setdefault("runtime",{})["last_life_course_review_at"]=at; self.put(person_path,person); return
        first_due=CampaignTime.parse(str(host.get("next_due",at))); recurrence=max(1,int(host.get("recurrence_seconds",31536000))); training=self.read("game/data/mechanics/training.json"); world_seed=str(self.read("state/meta.json").get("world_seed","sword")); reviews=0
        for i in range(max(0,int(occurrences))):
            review=first_due.add_seconds(i*recurrence)
            if review>CampaignTime.parse(at): break
            age=age_years(person,review); person.setdefault("runtime",{})["last_life_course_review_at"]=str(review); person["runtime"]["completed_life_course_reviews"]=int(person["runtime"].get("completed_life_course_reviews",0))+1; reviews+=1
            if not is_person_lite:
                self._settle_due_pregnancy(person_ref,person_path,person,str(review))
                self._settle_person_family_life_stage(person_ref, person, review)
            # The routed person-activity clock owns routine development. A compact
            # boolean disables the annual fallback when another current owner is active;
            # no gameplay rule is encoded by parsing explanatory prose.
            contract=person.get("activity_contract") if isinstance(person.get("activity_contract"),dict) else None
            activity_state=person.get("autonomous_activity_state") if isinstance(person.get("autonomous_activity_state"),Mapping) else None
            routed_activity_training=bool(
                isinstance(activity_state,Mapping)
                and activity_state.get("enabled") is not False
                and float(activity_state.get("verified_hours_per_cycle",0.0) or 0.0)>0.0
            )
            # Routine deliberate training has one owner: the routed person-activity
            # clock. Annual life-course review owns aging/family/mortality only once a
            # person has that route. Keeping the legacy annual training fallback as
            # well would double-award development and make long-horizon cost grow with
            # every elapsed year.
            if person_ref!=self.PLAYER_ACTOR and not is_person_lite and contract and not routed_activity_training and contract.get("annual_training_fallback_enabled", True) is not False and self._person_health(person) in {"healthy","fit","stable"}:
                registry=self.read(TRAINING_PROGRAM_REGISTRY_PATH); explicit=str(contract.get("training_program_ref","") or ""); program_ref=resolve_training_program_ref(registry,person=person,explicit_program_ref=explicit or None)
                profiles=self.read("game/data/mil/recruitment-cohort-profiles.json"); regimens=profiles.get("training_regimens",{}) if isinstance(profiles,Mapping) else {}; regimen=regimens.get(str(contract.get("training_regimen_ref","regular_army")),{}) if isinstance(regimens,Mapping) else {}
                if not isinstance(regimen,Mapping): regimen={}
                session_rules=self.read("game/data/mechanics/training-session.json"); evidence=f"annual_person_training:{person_ref}:{review}"; window_start=review.add_seconds(-recurrence)
                person_location=str(self._person_location(person) or ""); environment=training_environment(self,location_ref=person_location,simultaneous_trainees=1) if person_location else {"facility_grade":"none","capacity_factor":0.0}
                contexts=instructor_contexts_for_program(self,registry=registry,training_rules=training,program_ref=program_ref,trainee_skills=merged_skill_map(person),student_count=1,location_ref=person_location,trainee_ref=person_ref,scheduled_hours=48.0,window_start=str(window_start),window_end=str(review),evidence_ref=evidence,reserve_duty=True,hierarchical_delivery=bool(person.get("command_assignment")))
                access=exact_person_drill_access(self,registry=registry,program_ref=program_ref,person=person)
                development=settle_exact_program(person,registry=registry,program_ref=program_ref,hours=48,at=review,training_rules=training,session_rules=session_rules,facility_grade=str(environment.get("facility_grade","none")),equipment_grade=str(regimen.get("equipment_grade","adequate")),recovery_grade=str(regimen.get("recovery_grade","adequate")),feedback_grade=str(regimen.get("feedback_grade","ordinary")),cursor_key="annual_deterministic_training_cursor",instructor_context_by_drill=contexts,drill_access=access,time_window_start=str(window_start),time_window_end=str(review),time_evidence_ref=evidence)
            # Deterministic annual mortality. Named/canon/player status grants no
            # immunity; age and active injury change the annual hazard.
            bp=annual_mortality_basis_points(age,self._person_health(person))
            roll=deterministic_annual_mortality_roll(world_seed,person_ref,review)
            if roll<bp:
                settle_force_body=True
                if is_person_lite:
                    force_owned = bool(hasattr(self, "_person_lite_force_owned") and self._person_lite_force_owned(person_ref, person))
                    settle_force_body=force_owned
                self._settle_person_death(person_ref,person_path,person,str(review),"deterministic life-course mortality",settle_force_body=settle_force_body); return
        if reviews:
            self.put(person_path,person)

    def _autonomy_state(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        owner_ref = str(host["owner_ref"])
        state = self._state_key(owner_ref)
        sp = f"state/states/{state}.json"
        state_doc = _deepcopy(self.read(sp))
        net = int(state_doc.get("normal_monthly_revenue_silver",0)) - int(state_doc.get("normal_monthly_expense_silver",0))
        state_doc["treasury_silver"] = max(0, int(state_doc.get("treasury_silver",0)) + net * occurrences)
        state_doc["last_review"] = at
        threats=state_doc.get("known_threats",{})
        def threat_severity(value):
            if isinstance(value,dict): return int(value.get("severity",0))
            return int(_fixed(value,0))
        max_threat=max((threat_severity(v) for v in threats.values()),default=0)
        posture="fortify_and_reinforce" if max_threat>=70 else ("heightened_border_defense" if max_threat>=35 else "routine_readiness")
        state_doc["autonomous_posture"]=posture
        self.put(sp, state_doc)
        blueprints = self.read("game/data/mil/autonomy-blueprints.json").get("states",{}).get(state,[])
        force_path = f"state/forces/state-{state}.json"
        force = self._ct_force(force_path) if hasattr(self, "_ct_force") else _deepcopy(self.read(force_path))
        # Replacement recruiting is bounded by the exact recruitment office, treasury and civilian population.
        authorized=int(force.get("authorized_strength",force.get("headcount",0))); shortage=max(0,authorized-int(force.get("headcount",0)))
        if shortage:
            inst=self.read(self.owner_path(f"inst_{state}_recruitment_office")); capacity=int(inst.get("capacity",0))*occurrences
            pp=f"state/population/{state}.json"; pop=_deepcopy(self.read(pp)); available=max(0,int(pop["strata"].get("agricultural",0)))
            if hasattr(self, "_autonomy_state_recruitment_available"):
                available=min(available,max(0,int(self._autonomy_state_recruitment_available(state,pop))))
            econ=self.read("game/data/mechanics/economy.json"); unit_cost=int(econ.get("military_finance",{}).get("recruitment_and_basic_issue_cost_silver_per_person",12))
            affordable=int(state_doc.get("treasury_silver",0))//max(1,unit_cost)
            recruits=min(shortage,capacity,available,affordable)
            if recruits:
                pop["strata"]["agricultural"]-=recruits; pop["strata"]["active_military"]+=recruits
                source_loc=str(force.get("source_location_ref") or self.read(f"state/depots/{state}.json").get("location_ref"))
                if hasattr(self, "_autonomy_state_recruitment_source_location"):
                    source_loc=str(self._autonomy_state_recruitment_source_location(state,pop,source_loc))
                local_recruitment=[]
                if hasattr(self, "_autonomy_state_record_local_recruitment"):
                    local_recruitment=self._autonomy_state_record_local_recruitment(state,pop,recruits,at,source_loc)
                add_recruits(force,"line_infantry",recruits,location_ref=source_loc)
                record_recruitment_cohort(
                    force, role="line_infantry", count=recruits, location_ref=source_loc,
                    source_population_ref=f"population_{state}", source_stratum="agricultural",
                    recruited_at=at, profile_registry=self.read("game/data/mil/recruitment-cohort-profiles.json"),
                    selection_profile="state_basic_military_screen", provenance_ref=f"autonomy_state:{at}",
                )
                state_doc["treasury_silver"]-=recruits*unit_cost
                self.put(pp,pop); self.put(sp,state_doc)
        owner_index=self.read("state/index/owner-index.json").get("owners",{})
        for bp in blueprints:
            ref = f"formation_{state}_{bp['key']}"
            existing = owner_index.get(ref)
            role = bp["role"]; target_n = int(bp["personnel"])
            if existing:
                formation=_deepcopy(self.read(existing))
                if hasattr(self,"_ct_force"): ensure_formation_composition(force,formation,at=at)
                # Reconstitution uses the same conserved force pool as explicit player/state commands.
                need=max(0,target_n-int(formation.get("personnel",0))); formation_loc=str(formation.get("location_ref")); local=self._force_location_pool(force,formation_loc)
                take=min(need,int(force.get("available_by_role",{}).get(role,0)),int(local.get(role,0)))
                if take:
                    self._take_force_personnel(force,role,take,formation_loc)
                    old_n=int(formation.get("personnel",0)); formation["personnel"]+=take
                    formation.setdefault("composition",{})[role]=int(formation["personnel"]); new_n=int(formation["personnel"]); incoming={"readiness":35,"morale":60,"cohesion":25,"training_progress":10,"fatigue":0}
                    for field,base in incoming.items(): formation[field]=_clamp(int(round((int(formation.get(field,base))*old_n+base*take)/max(1,new_n))))
                    force["allocated_to_formations"][ref]={"personnel":int(formation["personnel"]),"role":role}
                    if hasattr(self,"_ct_force"):
                        append_formation_slices(formation,take_reserve_slices(force,role=role,count=take,location_ref=formation_loc,formation_ref=ref))
                formation["training_progress"]=_clamp(int(formation.get("training_progress",0))+min(20,occurrences*2))
                formation["cohesion"]=_clamp(int(formation.get("cohesion",50))+min(10,occurrences))
                formation["readiness"]=_clamp(int(formation.get("readiness",50))+min(10,occurrences))
                settle_formation_idle_fatigue(formation,current=CampaignTime.parse(at),rules=self.read(FATIGUE_RULES_PATH))
                if max_threat>=35:
                    formation["mobilized"]=True; formation["status"]="mobilized"
                self.put(existing,formation)
                continue
            n=target_n; source_loc=str(force.get("source_location_ref") or self.read(f"state/depots/{state}.json").get("location_ref")); local=self._force_location_pool(force,source_loc)
            if int(force.get("available_by_role",{}).get(role,0)) < n or int(local.get(role,0)) < n:
                continue
            self._take_force_personnel(force,role,n,source_loc)
            force.setdefault("allocated_to_formations",{})[ref] = {"personnel": n, "role": role}
            cohort_slices = take_reserve_slices(force,role=role,count=n,location_ref=source_loc,formation_ref=ref) if hasattr(self,"_ct_force") else []
            fpath = f"state/formations/{state}-{bp['key'].replace('_','-')}.json"
            formation = {
                "schema":"sword-formation","formation_ref":ref,
                "name":f"{state.upper()} {bp['key'].replace('_',' ').title()}",
                "owner_force_ref":f"force_state_{state}","administrative_owner":f"state_{state}",
                "command_authority":f"state_{state}","commander_ref":bp.get("commander_ref"),
                "personnel":n,"composition":{role:n},"location_ref":source_loc,
                "doctrine_ref":bp.get("doctrine_ref"),"training_ref":bp.get("training_ref"),
                "doctrine_behavior":{},
                "training_progress":15,"readiness":65,"morale":70,"cohesion":65,"fatigue":0,
                "equipment_completeness":"0.9","experience":"formed","mobilized":max_threat>=35,"status":"mobilized" if max_threat>=35 else "forming",
                "logistics":{"war_arrows":0,"war_bolts":0},
                "mounts":{},"cohort_composition":cohort_slices
            }
            formation["doctrine_ref"] = str(formation.get("doctrine_ref") or default_formation_doctrine_ref(formation))
            formation["doctrine_behavior"] = doctrine_behavior(self.read, formation)
            # Formation creation never mints ammunition. Draw the registered
            # carried load from the exact state depot, leaving any shortage real.
            ammo_needed={"war_arrows":0,"war_bolts":0}
            if hasattr(self,"_combat_role_profile") and hasattr(self,"_combat_loadout"):
                profile=self._combat_role_profile(role); loadout=self._combat_loadout(str(profile.get("loadout_id",""))) if isinstance(profile,Mapping) else {}
                if isinstance(loadout,Mapping):
                    item=str(loadout.get("ammunition_item","")); resource=getattr(self,"AMMO_RESOURCE_BY_ITEM",{}).get(item); carried=max(0,int(loadout.get("carried_ammunition",0) or 0))
                    if resource in ammo_needed: ammo_needed[resource]=n*carried
            if role == "cavalry":
                mp=f"state/mounts/{state}.json"; mounts=_deepcopy(self.read(mp)); count=min(n,int(mounts.get("types",{}).get("horse",0)))
                if count:
                    mounts.setdefault("allocated_to_formations",{})[ref]={"horse":count}
                    formation["mounts"]={"horse":count}
                    self.put(mp,mounts)
            depot_p=f"state/depots/{state}.json"; depot=_deepcopy(self.read(depot_p))
            for key,needed in (("war_arrows",ammo_needed["war_arrows"]),("war_bolts",ammo_needed["war_bolts"])):
                take=min(int(depot.get("stocks",{}).get(key,0)),needed)
                depot["stocks"][key]-=take
                formation["logistics"][key]=take
            self.put(depot_p,depot)
            if formation.get("commander_ref"):
                try:
                    cp,commander=self._validate_person_location_for_formation(str(formation["commander_ref"]),formation)
                    self._bind_formation_commander_sheet(str(formation["commander_ref"]), ref, formation, person_path=cp, person=commander)
                    self._assign_commander_index(str(formation["commander_ref"]),ref)
                except (ValueError,KeyError):
                    formation["commander_ref"]=None; formation["status"]="commander_vacant"
            self.put(fpath,formation); self._register_owner(ref,fpath); self._index_formation_location(ref,None,source_loc)
        if hasattr(self,"_ct_force"): validate_cohort_ledger(force)
        self.put(force_path,force)
        # A material known threat creates one bounded strategic response operation, not a global war tick.
        if max_threat>=35:
            op_ref=f"operation_auto_{state}_border_response"
            op_idx=_deepcopy(self.read("state/operations/index.json"))
            if op_ref not in op_idx.get("operations",{}):
                op_path=f"state/operations/{op_ref}.json"
                refs=[f"formation_{state}_{bp['key']}" for bp in blueprints[:2] if self.read("state/index/owner-index.json").get("owners",{}).get(f"formation_{state}_{bp['key']}")]
                op={"schema":"sword-operation","owner_id":op_ref,"operation_ref":op_ref,"objective":"respond to known border threat","status":"active","formation_refs":refs,"location_ref":self.read(f"state/depots/{state}.json").get("location_ref"),"created_at":at,"autonomous":True}
                self.put(op_path,op); op_idx.setdefault("operations",{})[op_ref]=op_path; self.put("state/operations/index.json",op_idx); self._register_owner(op_ref,op_path)
        self.put(sp,state_doc)

    def _autonomy_interstate(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        """Advance bounded exact interstate theaters through objective -> war -> occupation -> peace.

        The theater registry lists exact states, formations, and one contested strategic
        site.  No person/faction/force/House directory is scanned.  A long jump may
        batch many quarterly reviews, but each theater still advances one causal phase
        per saved review instant and writes exact material-history events.
        """
        path=self.owner_path(str(host["owner_ref"])); world=_deepcopy(self.read(path)); base_config=self.read("game/data/world/autonomous-theaters.json"); config=self._interstate_theater_config(base_config, at=at) if hasattr(self,"_interstate_theater_config") else base_config; territory=_deepcopy(self.read("state/territory/control.json")); treaties=_deepcopy(self.read("state/politics/treaties.json")); hist=_deepcopy(self.read("state/history/events/index.json")); first_due=CampaignTime.parse(str(host.get("next_due",at))); recurrence=max(1,int(host.get("recurrence_seconds",config.get("review_seconds",2592000)))); world_seed=str(self.read("state/meta.json").get("world_seed","sword"))
        core_states={"qin","zhao","chu","wei","han","yan","qi"}
        def side_owner_ref(side: str) -> str:
            return side if side.startswith("polity_") else f"state_{side}"
        def side_from_controller(controller_ref: str) -> str:
            return controller_ref.removeprefix("state_") if controller_ref.startswith("state_") else controller_ref
        def side_doc(side: str) -> tuple[str,Dict[str,Any]]:
            if side.startswith("polity_"):
                sp=self.owner_path(side); return sp,_deepcopy(self.read(sp))
            if side not in core_states:
                raise ValueError(f"unknown interstate sovereign side: {side}")
            sp=f"state/states/{side}.json"; return sp,_deepcopy(self.read(sp))
        def side_authorities(side: str) -> set[str]:
            if not side.startswith("polity_"):
                return {f"state_{side}"}
            _sp,doc=side_doc(side); refs={side}; refs.update(str(x) for x in doc.get("military_authority_refs",[]) if isinstance(x,str)); house=str(doc.get("sovereign_house_ref",""))
            if house: refs.add(house)
            return refs
        def side_force_refs(side: str) -> set[str]:
            if not side.startswith("polity_"):
                return {f"force_state_{side}"}
            _sp,doc=side_doc(side); return {str(x) for x in doc.get("military_force_refs",[]) if isinstance(x,str)}
        def side_home(side: str) -> str:
            if not side.startswith("polity_"):
                return str(self.read(f"state/depots/{side}.json").get("location_ref"))
            _sp,doc=side_doc(side); seat=str(doc.get("seat_claim_ref",""))
            if seat: return seat
            controlled=[str(x) for x in doc.get("occupied_site_refs",[]) if isinstance(x,str)]
            if controlled: return sorted(controlled)[0]
            for force_ref in sorted(side_force_refs(side)):
                try: force=self.read(self.owner_path(force_ref))
                except (KeyError,ValueError,FileNotFoundError): continue
                allocated=force.get("allocated_to_formations",{}) if isinstance(force,Mapping) else {}
                for formation_ref in sorted(str(x) for x in allocated):
                    try: _fp,f=self._load_formation(formation_ref)
                    except ValueError: continue
                    loc=str(f.get("location_ref",""))
                    if loc: return loc
            raise ValueError(f"sovereign side {side} lacks a lawful retreat/home location")
        def formation_power(ref: str, defender: bool, opposing_ref: str | None = None) -> float:
            if hasattr(self, "_autonomy_formation_power"):
                return float(self._autonomy_formation_power(ref, defender=defender, opposing_ref=opposing_ref))
            try: _,f=self._load_formation(ref)
            except ValueError: return 0.0
            n=max(0,int(f.get("personnel",0)))
            if n<=0: return 0.0
            readiness=int(f.get("readiness",50)); morale=int(f.get("morale",50)); cohesion=int(f.get("cohesion",50)); training=int(f.get("training_progress",20)); fatigue=int(f.get("fatigue",0)); equipment=max(.15,_pct(f.get("equipment_completeness","0"))); supply_state=military_supply_sufficiency(self,f); supply=.72+.28*float(supply_state["overall_ratio"]); doctrine=f.get("doctrine_behavior",{}); reserve=_clamp(int(doctrine.get("reserve_commitment",50))); doctrine_factor=.88+.24*reserve/100.0; base=max(.1,(readiness+morale+cohesion+training+max(0,100-fatigue))/500.0); command=1.0; commander_ref=f.get("commander_ref")
            if commander_ref:
                try:
                    _,c=self._command_person(str(commander_ref)); caps=merged_skill_map(c); score=sum(_fixed(caps.get(k,0)) for k in ("Formation Command","Tactics","Leadership","Strategy","Formation Fighting")) if isinstance(caps,dict) else 0; command+=min(500.0,score)/3000.0
                except (KeyError, ValueError, FileNotFoundError): command*=.88
            terrain=(terrain_context_for_location(self,str(f.get("location_ref")))["mechanical_effects"].get("defense_milli",1000)/1000.0) if defender else 1.0
            return n*base*equipment*supply*doctrine_factor*command*terrain

        # A body may be conserved perfectly and still be mechanically duplicated if
        # the same exact formation is admitted to two simultaneous military owners.
        # Build the non-interstate commitment set once per review call; theater
        # commitments below are read from the live ``world`` object so earlier
        # theaters settled in this same chronological pass are immediately visible.
        active_operation_formation_refs: set[str] = set()
        operation_index = self.read_optional("state/operations/index.json")
        operation_routes = operation_index.get("operations", {}) if isinstance(operation_index, Mapping) else {}
        terminal_operation_statuses = {
            "completed", "cancelled", "canceled", "failed", "resolved", "closed",
            "withdrawn", "abandoned", "peace", "terminated",
        }
        if isinstance(operation_routes, Mapping):
            for _operation_path in operation_routes.values():
                if not isinstance(_operation_path, str):
                    continue
                _operation = self.read_optional(_operation_path)
                if not isinstance(_operation, Mapping) or str(_operation.get("status", "")) in terminal_operation_statuses:
                    continue
                active_operation_formation_refs.update(
                    str(ref) for ref in _operation.get("formation_refs", []) if isinstance(ref, str)
                )

        active_siege_theaters_by_formation: dict[str, set[str]] = {}
        siege_index = self.read_optional("state/sieges/index.json")
        siege_routes = siege_index.get("sieges", {}) if isinstance(siege_index, Mapping) else {}
        terminal_siege_statuses = {"captured", "lifted", "abandoned", "resolved", "completed", "closed"}
        if isinstance(siege_routes, Mapping):
            for _siege_path in siege_routes.values():
                if not isinstance(_siege_path, str):
                    continue
                _siege = self.read_optional(_siege_path)
                if not isinstance(_siege, Mapping) or str(_siege.get("status", "")) in terminal_siege_statuses:
                    continue
                _siege_theater = str(_siege.get("strategic_theater_ref", ""))
                _siege_refs = list(_siege.get("attacker_formation_refs", []) or []) + list(_siege.get("defender_formation_refs", []) or [])
                for _formation_ref in _siege_refs:
                    if isinstance(_formation_ref, str):
                        active_siege_theaters_by_formation.setdefault(_formation_ref, set()).add(_siege_theater)

        def formation_committed_elsewhere(formation_ref: str, theater_ref: str) -> bool:
            if formation_ref in active_operation_formation_refs:
                return True
            if any(
                not siege_theater or siege_theater != theater_ref
                for siege_theater in active_siege_theaters_by_formation.get(formation_ref, set())
            ):
                return True
            theaters = world.get("theaters", {}) if isinstance(world, Mapping) else {}
            if isinstance(theaters, Mapping):
                for other_theater_ref, other_record in theaters.items():
                    if str(other_theater_ref) == theater_ref or not isinstance(other_record, Mapping):
                        continue
                    if str(other_record.get("phase", "peace")) == "peace":
                        continue
                    other_groups = other_record.get("formation_groups", {})
                    if not isinstance(other_groups, Mapping):
                        continue
                    if any(
                        formation_ref in refs
                        for refs in other_groups.values()
                        if isinstance(refs, list)
                    ):
                        return True
            return False

        def side_formation_refs(cfg: Mapping[str,Any], side: str, record: Mapping[str,Any] | None = None, review_at: str | None = None, theater_ref: str = "") -> list[str]:
            saved=[]
            if isinstance(record,Mapping):
                raw_saved=record.get("formation_groups",{}).get(side) if isinstance(record.get("formation_groups"),Mapping) else None
                if isinstance(raw_saved,list):
                    saved=[str(x) for x in raw_saved if isinstance(x,str)]
            # Once a war has a saved commitment snapshot, ordinary standing
            # formations remain excluded unless they were already committed.
            # Explicitly mobilized levies and field contractors, however, can
            # arise later and must still be discoverable as reinforcements.
            if saved:
                refs=list(saved)
            else:
                raw=cfg.get("formation_ref_lists",{}).get(side) if isinstance(cfg.get("formation_ref_lists"),Mapping) else None
                refs=[str(x) for x in raw if isinstance(x,str)] if isinstance(raw,list) else []
                if not refs:
                    one=str(cfg.get("formation_refs",{}).get(side,"")) if isinstance(cfg.get("formation_refs"),Mapping) else ""
                    if one: refs=[one]
            dynamic_refs=[]
            if side in {"qin","zhao","chu","wei","han","yan","qi"}:
                dynamic_refs.extend(active_levy_formations(self,side))
                if review_at and hasattr(self,"_tactical_mercenary_formations_for_employer"):
                    dynamic_refs.extend(self._tactical_mercenary_formations_for_employer(f"state_{side}",at=review_at))
            # Saved groups are this theater's already-authoritative commitments and
            # must remain visible even if another subsystem is inconsistent. Only
            # *new* admission is filtered here. Initial mobilization has no saved
            # groups, so every candidate must be physically free.
            if saved:
                refs.extend(
                    ref for ref in dynamic_refs
                    if ref not in saved and not formation_committed_elsewhere(ref, theater_ref)
                )
            else:
                refs.extend(dynamic_refs)
                refs=[ref for ref in refs if not formation_committed_elsewhere(ref, theater_ref)]
            return list(dict.fromkeys(refs))
        def alive_refs(refs: list[str], *, at_location: str | None = None) -> list[str]:
            out=[]
            for ref in refs:
                try: _,f=self._load_formation(ref)
                except ValueError: continue
                if int(f.get("personnel",0))<=0: continue
                if str(f.get("status", "")) == "contract_complete_withdrawing": continue
                if at_location is not None and str(f.get("location_ref",""))!=at_location: continue
                out.append(ref)
            return out
        def group_power(refs: list[str], defender: bool, opposing_refs: list[str]) -> float:
            opposing=opposing_refs[0] if opposing_refs else None
            return sum(formation_power(ref,defender,opposing) for ref in refs)
        def distribute_group_losses(refs: list[str], rate: float, at_text: str, *, losing_side: bool, opponent: str, seed_prefix: str) -> dict[str,Any]:
            alive=[]; total=0
            for ref in refs:
                try: _,f=self._load_formation(ref)
                except ValueError: continue
                n=max(0,int(f.get("personnel",0)))
                if n: alive.append((ref,n)); total+=n
            target=min(total,max(0,int(round(total*rate))))
            remaining=target; out={}
            for idx,(ref,n) in enumerate(alive):
                loss=remaining if idx==len(alive)-1 else min(remaining,max(0,int(round(target*n/max(1,total)))))
                remaining-=loss
                out[ref]=self._autonomy_apply_battle_losses(ref,loss,at_text,losing_side=losing_side,opponent_state=opponent,seed_material=f"{seed_prefix}|{ref}") if loss else {"loss":0}
            return out
        for i in range(max(0,int(occurrences))):
            review=first_due.add_seconds(i*recurrence)
            if review>CampaignTime.parse(at): break
            review_text=str(review)
            for cfg in config.get("theaters",[]):
                tref=str(cfg["theater_ref"]); record=world.setdefault("theaters",{}).setdefault(tref,{"phase":"peace","cycle":0,"pressure":int(cfg.get("base_pressure",20)),"cooldown_reviews":0,"history":[]}); sides=[str(x) for x in cfg["sides"]]; target=str(cfg["target_location_ref"]); site=territory.get("sites",{}).get(target)
                if not site: continue
                if hasattr(self,"_prune_contract_complete_withdrawals_from_interstate_record"):
                    self._prune_contract_complete_withdrawals_from_interstate_record(record)
                phase=str(record.get("phase","peace")); cooldown=max(0,int(record.get("cooldown_reviews",0)))
                if phase=="peace":
                    if cooldown>0:
                        record["cooldown_reviews"]=cooldown-1; continue
                    controller=side_from_controller(str(site.get("controller","")))
                    if controller not in sides: continue
                    attacker=sides[1] if controller==sides[0] else sides[0]
                    if hasattr(self, "_interstate_war_decision"):
                        decision=self._interstate_war_decision(attacker,controller,target,record,cfg,review_text)
                        if not isinstance(decision,Mapping): raise ValueError("interstate war decision hook returned invalid data")
                        record["pressure"]=max(0,min(100,int(decision.get("tension_score",record.get("pressure",cfg.get("base_pressure",20))))))
                        record["last_peace_review"]={"at":review_text,"attacker_candidate":attacker,"defender":controller,"authorized":bool(decision.get("authorized")),"basis":_deepcopy(decision.get("basis",{}))}
                        if not bool(decision.get("authorized")): continue
                        war_goal=_deepcopy(decision.get("war_goal",{})) if isinstance(decision.get("war_goal"),Mapping) else {"kind":"territorial_control","location_ref":target,"objective":"occupy and compel settlement"}
                        defender_goal={"kind":"territorial_defense","location_ref":target,"objective":"retain control and force withdrawal"}
                        casus=_deepcopy(decision.get("casus_belli",{})) if isinstance(decision.get("casus_belli"),Mapping) else {"kind":"authorized_strategic_war","target_location_ref":target}
                        basis=str(decision.get("decision_ref",decision.get("reason","lawful strategic authorization")))
                    else:
                        seed=int(hashlib.sha256((world_seed+"|pressure|"+tref+"|"+review_text).encode()).hexdigest()[:8],16); record["pressure"]=min(120,int(record.get("pressure",cfg.get("base_pressure",20)))+5+seed%7)
                        if int(record["pressure"])<100: continue
                        war_goal={"kind":"territorial_control","location_ref":target,"objective":"occupy and compel settlement"}; defender_goal={"kind":"territorial_defense","location_ref":target,"objective":"retain control and force withdrawal"}; casus={"kind":"escalated_rivalry_pressure","pressure":int(record["pressure"]),"target_location_ref":target}; basis="deterministic rivalry pressure"
                    record["cycle"]=int(record.get("cycle",0))+1; record["attacker_state"]=attacker; record["defender_state"]=controller; record["phase"]="mobilizing"; record["started_at"]=review_text; record["battle_count"]=0; record["war_goals"]={attacker:war_goal,controller:defender_goal}; record["casus_belli"]=casus; _append_bounded(record,"history",{"at":review_text,"event":"political_objective","attacker":attacker,"defender":controller,"target":target,"basis":basis,"war_goals":_deepcopy(record["war_goals"])},limit=32);
                    for a,b in ((attacker,controller),(controller,attacker)):
                        sp,sd=side_doc(a); goal=_deepcopy(record["war_goals"].get(a,{})); sd.setdefault("diplomacy",{})[side_owner_ref(b)]={"tension":100,"status":"war","theater_ref":tref,"since":review_text,"casus_belli":_deepcopy(record["casus_belli"]),"war_goal":goal,"negotiation_status":"hostilities_active"}; sd.setdefault("strategic_goals",[]).append(f"contest {target} against {b}"); sd["strategic_goals"]=sd["strategic_goals"][-12:]; self.put(sp,sd)
                    if hasattr(self,"_propagate_defensive_treaty_obligations"):
                        obligations=self._propagate_defensive_treaty_obligations(
                            attacker_ref=side_owner_ref(attacker),
                            defender_ref=side_owner_ref(controller),
                            location_ref=target,
                            theater_ref=tref,
                            at=review_text,
                        )
                        if obligations:
                            record["defensive_treaty_obligations"]=_deepcopy(obligations)
                    continue
                attacker=str(record.get("attacker_state","")); defender=str(record.get("defender_state",""))
                afs=side_formation_refs(cfg,attacker,record,review_text,tref); dfs=side_formation_refs(cfg,defender,record,review_text,tref)
                if not attacker or not defender:
                    record["phase"]="peace"; record["pressure"]=int(cfg.get("base_pressure",20)); continue
                if phase != "peace_settlement" and (not afs or not dfs):
                    # A declared war whose lawful field forces are already committed
                    # elsewhere must still close through the normal settlement path.
                    # Jumping directly to peace would strand exact diplomacy records
                    # in ``status: war`` and make the theater disagree with its states.
                    record["war_result"]="mobilization_unavailable" if phase=="mobilizing" else (record.get("war_result") or "no_capable_force")
                    record["phase"]="peace_settlement"
                    _append_bounded(record,"history",{
                        "at":review_text,"event":"campaign_closed_no_lawful_force",
                        "phase":phase,"attacker_formation_refs":afs,"defender_formation_refs":dfs,
                    },limit=32)
                    continue
                if phase=="mobilizing":
                    plan=build_interstate_strategic_plan(
                        self, theater_ref=tref, attacker=attacker, defender=defender,
                        primary_target=target, attacker_formation_refs=afs,
                        defender_formation_refs=dfs, at=review_text,
                    )
                    selected={
                        attacker: sorted(set(plan.get("formation_objectives",{}).get(attacker,{})) | set(plan.get("strategic_reserve_formation_refs",{}).get(attacker,[]))),
                        defender: sorted(set(plan.get("formation_objectives",{}).get(defender,{})) | set(plan.get("strategic_reserve_formation_refs",{}).get(defender,[]))),
                    }
                    live_groups={attacker:[],defender:[]}
                    for side,refs in ((attacker,selected[attacker]),(defender,selected[defender])):
                        for ref in refs:
                            try: fp,f0=self._load_formation(ref)
                            except ValueError: continue
                            f=_deepcopy(f0)
                            if int(f.get("personnel",0))<=0: continue
                            f["mobilized"]=True; f["status"]="mobilized"; f["mobilized_at"]=review_text; self.put(fp,f); live_groups[side].append(ref)
                    if not live_groups[attacker] or not live_groups[defender]:
                        record["phase"]="peace_settlement"; record["war_result"]="no_capable_force"; continue
                    record["strategic_plan"]=_deepcopy(plan)
                    record["formation_groups"]={attacker:live_groups[attacker],defender:live_groups[defender]}
                    record["army_groups"]={
                        attacker:{"primary_ref":live_groups[attacker][0],"formation_refs":live_groups[attacker],"reserve_refs":list(plan.get("strategic_reserve_formation_refs",{}).get(attacker,[]))},
                        defender:{"primary_ref":live_groups[defender][0],"formation_refs":live_groups[defender],"reserve_refs":list(plan.get("strategic_reserve_formation_refs",{}).get(defender,[]))},
                    }
                    record["unit_duties"]={attacker:self._apply_unit_duties(live_groups[attacker],"camp",context_ref=f"{tref}:{record.get('cycle')}:mobilize:{attacker}",at=review_text),defender:self._apply_unit_duties(live_groups[defender],"camp",context_ref=f"{tref}:{record.get('cycle')}:mobilize:{defender}",at=review_text)}
                    record["phase"]="advancing"
                    _append_bounded(record,"history",{"at":review_text,"event":"mobilization","concentration_mode":plan.get("concentration_mode"),"fronts":[{"front_ref":x.get("front_ref"),"objective_ref":x.get("objective_ref"),"attacker_command_refs":x.get("attacker_command_refs",[]),"defender_command_refs":x.get("defender_command_refs",[])} for x in plan.get("fronts",[])],"strategic_reserves":_deepcopy(plan.get("strategic_reserve_commands",{}))},limit=32)
                    continue
                if phase=="advancing":
                    plan=record.get("strategic_plan",{}) if isinstance(record.get("strategic_plan"),Mapping) else {}
                    fronts=plan.get("fronts",[]) if isinstance(plan.get("fronts"),list) else []
                    if not fronts:
                        # Compatibility for already-active/manual theaters created
                        # before the multi-front strategic plan existed. Saved
                        # formation_groups are real commitments, so project them
                        # into one primary front instead of treating every body as
                        # an unassigned reserve and stalling contact forever.
                        compat_a=alive_refs(afs); compat_d=alive_refs(dfs)
                        plan={
                            "planned_at": review_text, "theater_ref": tref,
                            "primary_objective_ref": target,
                            "concentration_mode": "existing_commitment",
                            "attacker_side": attacker, "defender_side": defender,
                            "fronts":[{
                                "front_ref":f"{tref}:front:{target}",
                                "objective_ref":target, "priority":100,
                                "status":"advancing",
                                "attacker_command_refs":[], "defender_command_refs":[],
                                "attacker_formation_refs":compat_a,
                                "defender_formation_refs":compat_d,
                            }],
                            "formation_objectives":{
                                attacker:{ref:target for ref in compat_a},
                                defender:{ref:target for ref in compat_d},
                            },
                            "strategic_reserve_formation_refs":{attacker:[],defender:[]},
                            "unassigned_formation_refs":{attacker:[],defender:[]},
                            "rule":"Existing committed theater formations remain committed when upgrading a legacy theater to multi-front planning.",
                        }
                        record["strategic_plan"]=plan
                        fronts=plan["fronts"]
                    # Admit only newly explicit mobilization commitments.  The
                    # strategic plan itself decides whether they are lawful
                    # standalone reserves; existing fronts are not rebuilt and
                    # named field-army hierarchy is never rewritten.
                    for _side,_refs in ((attacker,alive_refs(afs)),(defender,alive_refs(dfs))):
                        reinforcement=integrate_reinforcement_reserves(
                            self, plan, side=_side, formation_refs=_refs, at=review_text,
                        )
                        added=[str(x) for x in reinforcement.get("added_formation_refs",[]) if isinstance(x,str)]
                        if not added:
                            continue
                        groups=record.setdefault("formation_groups",{}).setdefault(_side,[])
                        record["formation_groups"][_side]=list(dict.fromkeys([str(x) for x in groups if isinstance(x,str)]+added))
                        for _ref in added:
                            try:
                                _fp,_f0=self._load_formation(_ref)
                            except ValueError:
                                continue
                            _f=_deepcopy(_f0); _f["mobilized"]=True
                            if str(_f.get("status","")) not in {"contract_complete_withdrawing","contract_complete_holdover"}:
                                _f["status"]="mobilized"
                            _f.setdefault("mobilized_at",review_text); self.put(_fp,_f)
                        _all=record["formation_groups"][_side]
                        armies=record.setdefault("army_groups",{})
                        existing=armies.get(_side,{}) if isinstance(armies.get(_side),Mapping) else {}
                        primary=str(existing.get("primary_ref",_all[0] if _all else ""))
                        armies[_side]={
                            "primary_ref":primary,
                            "formation_refs":_all,
                            "reserve_refs":list(plan.get("strategic_reserve_formation_refs",{}).get(_side,[])),
                        }
                        _append_bounded(record,"history",{
                            "at":review_text,"event":"reinforcement_entered_strategic_reserve",
                            "side":_side,"formation_refs":added,
                            "command_refs":[str(row.get("command_group_ref") or row.get("independent_formation_ref")) for row in reinforcement.get("added_commands",[]) if isinstance(row,Mapping)],
                        },limit=32)
                    record["strategic_plan"]=plan
                    fronts=plan.get("fronts",[]) if isinstance(plan.get("fronts"),list) else fronts
                    # Bounded strategic review: reserves are real intact commands,
                    # not decorative metadata. Commit at most one command per side
                    # and review boundary when an unresolved front materially needs it.
                    def _front_people(refs):
                        total=0
                        for _ref in alive_refs([str(x) for x in refs if isinstance(x,str)]):
                            try: total += max(0,int(self._load_formation(str(_ref))[1].get("personnel",0)))
                            except ValueError: continue
                        return total
                    active_for_review=[f for f in fronts if isinstance(f,dict) and str(f.get("status","")) not in {"occupied","defender_holds","abandoned","withdrawn"}]
                    active_for_review.sort(key=lambda f:(-int(f.get("priority",0)),str(f.get("front_ref",""))))
                    for front in active_for_review:
                        ap=_front_people(front.get("attacker_formation_refs",[])); dp=_front_people(front.get("defender_formation_refs",[]))
                        status=str(front.get("status",""))
                        contingencies=plan.get("operational_contingencies",{}) if isinstance(plan.get("operational_contingencies"),Mapping) else {}
                        attacker_cont=contingencies.get(attacker,{}) if isinstance(contingencies.get(attacker),Mapping) else {}
                        defender_cont=contingencies.get(defender,{}) if isinstance(contingencies.get(defender),Mapping) else {}
                        attacker_ratio=max(0.92,min(1.30,float(attacker_cont.get("reserve_commit_if_local_ratio_below_milli",1100) or 1100)/1000.0))
                        defender_ratio=max(1.02,min(1.42,float(defender_cont.get("reserve_commit_if_enemy_ratio_above_milli",1150) or 1150)/1000.0))
                        if plan.get("strategic_reserve_commands",{}).get(attacker) and (status in {"besieging","approaching_siege","route_blocked"} or (dp>0 and ap < int(dp*attacker_ratio))):
                            committed=commit_one_reserve_command(plan,side=attacker,front=front,at=review_text,reason="contingency threshold: reinforce unresolved offensive front")
                            if committed: _append_bounded(record,"history",{"at":review_text,"event":"strategic_reserve_committed","side":attacker,**committed},limit=32); ap=_front_people(front.get("attacker_formation_refs",[]))
                        if plan.get("strategic_reserve_commands",{}).get(defender) and ap>0 and (dp<=0 or ap > int(max(1,dp)*defender_ratio)):
                            committed=commit_one_reserve_command(plan,side=defender,front=front,at=review_text,reason="contingency threshold: reinforce threatened defensive front")
                            if committed: _append_bounded(record,"history",{"at":review_text,"event":"strategic_reserve_committed","side":defender,**committed},limit=32)
                        if not plan.get("strategic_reserve_commands",{}).get(attacker) and not plan.get("strategic_reserve_commands",{}).get(defender):
                            break
                    objective_maps=plan.get("formation_objectives",{}) if isinstance(plan.get("formation_objectives"),Mapping) else {}
                    marches={attacker:[],defender:[]}; supplies={attacker:[],defender:[]}
                    front_by_formation={}
                    for _front in fronts:
                        if not isinstance(_front,dict): continue
                        for _ref in _front.get("attacker_formation_refs",[]): front_by_formation[(attacker,str(_ref))]=_front
                        for _ref in _front.get("defender_formation_refs",[]): front_by_formation[(defender,str(_ref))]=_front
                    march_refs={attacker:[ref for ref in alive_refs(afs) if str((objective_maps.get(attacker,{}) or {}).get(ref,""))],defender:[ref for ref in alive_refs(dfs) if str((objective_maps.get(defender,{}) or {}).get(ref,""))]}
                    record["unit_duties"]={attacker:self._apply_unit_duties(march_refs[attacker],"march",context_ref=f"{tref}:{record.get('cycle')}:advance:{attacker}",at=review_text),defender:self._apply_unit_duties(march_refs[defender],"march",context_ref=f"{tref}:{record.get('cycle')}:advance:{defender}",at=review_text)}
                    for side,refs,label in ((attacker,alive_refs(afs),"attacker"),(defender,alive_refs(dfs),"defender")):
                        side_map=objective_maps.get(side,{}) if isinstance(objective_maps.get(side),Mapping) else {}
                        for ref in refs:
                            front=front_by_formation.get((side,ref))
                            strategic_objective=str(side_map.get(ref,""))
                            objective=str(front.get("blocking_site_ref")) if isinstance(front,Mapping) and side==attacker and front.get("blocking_site_ref") else strategic_objective
                            if not objective:
                                marches[side].append({"formation_ref":ref,"status":"strategic_reserve","location_ref":self._load_formation(ref)[1].get("location_ref")}); continue
                            supply=self._autonomy_sustain_march(ref,objective,review_text,record,label); supplies[side].append({"formation_ref":ref,"objective_ref":objective,**supply})
                            ready=supply.get("status")!="formation_missing"
                            try:
                                move=self._autonomy_move_formation_step(ref,objective,review_text) if ready else {"status":supply.get("status"),"location_ref":supply.get("location_ref")}
                            except ValueError as exc:
                                _fp,_formation=self._load_formation(ref); blocker=first_hostile_route_blocker(self,_formation,objective,review_text)
                                if side==attacker and isinstance(front,dict) and blocker and blocker.get("fortified"):
                                    front["blocking_site_ref"]=str(blocker["blocking_site_ref"]); front["blocked_route_ref"]=blocker.get("route_ref"); front["blocking_reason"]=blocker.get("reason"); front["status"]="approaching_siege"
                                    try:
                                        move=self._autonomy_move_formation_step(ref,str(blocker["blocking_site_ref"]),review_text) if ready else {"status":supply.get("status"),"location_ref":supply.get("location_ref")}
                                        move["strategic_obstacle_ref"]=str(blocker["blocking_site_ref"]); move["strategic_objective_ref"]=strategic_objective
                                    except ValueError:
                                        move={"status":"route_blocked","location_ref":_formation.get("location_ref"),"strategic_obstacle_ref":str(blocker["blocking_site_ref"]),"reason":str(exc)}
                                else:
                                    move={"status":"route_blocked","location_ref":_formation.get("location_ref"),"reason":str(exc)}
                                    if isinstance(front,dict): front["status"]="route_blocked"
                            marches[side].append({"formation_ref":ref,"objective_ref":objective,**move})
                    record["last_group_supply"]=supplies; record["last_group_march"]=marches
                    engaged=False; occupation=False; siege_active=False
                    for front in fronts:
                        if not isinstance(front,dict): continue
                        obj=str(front.get("objective_ref","")); a_refs=[str(x) for x in front.get("attacker_formation_refs",[])]; d_refs=[str(x) for x in front.get("defender_formation_refs",[])]
                        blocker=str(front.get("blocking_site_ref",""))
                        if blocker:
                            a_block=alive_refs(a_refs,at_location=blocker)
                            if a_block:
                                blocker_def=[]
                                for _fr in self._formations_at(blocker):
                                    try: _,_f=self._load_formation(_fr)
                                    except ValueError: continue
                                    if int(_f.get("personnel",0))>0 and (str(_f.get("administrative_owner")) in side_authorities(defender) or str(_f.get("owner_force_ref")) in side_force_refs(defender)): blocker_def.append(_fr)
                                siege_info=ensure_autonomous_siege(self,theater_ref=tref,front=front,site_ref=blocker,attacker_refs=a_refs,defender_refs=blocker_def,attacker_side=attacker,defender_side=defender,at=review_text)
                                if siege_info:
                                    siege_result=advance_autonomous_siege(self,siege_ref=str(siege_info["siege_ref"]),at=review_text,review_days=max(1,recurrence//86400),attacker_side=attacker)
                                    front["last_siege_review"]=_deepcopy(siege_result); siege_active=True
                                    if str(siege_result.get("status"))=="captured":
                                        block_site=territory.get("sites",{}).get(blocker)
                                        if isinstance(block_site,dict):
                                            old_control=str(block_site.get("controller","")); block_site["controller"]=side_owner_ref(attacker); block_site["previous_controller"]=old_control; block_site["changed_at"]=review_text; block_site["change_basis"]="autonomous_interstate_siege_capture"; block_site["change_evidence_ref"]=str(siege_info["siege_ref"])
                                            _eid="territory_siege_"+hashlib.sha256((tref+"|"+blocker+"|"+review_text+"|"+attacker).encode()).hexdigest()[:16]
                                            hist.setdefault("events",[]).append({"event_id":_eid,"kind":"territorial_control_change","at":review_text,"theater_ref":tref,"front_ref":front.get("front_ref"),"location_ref":blocker,"from":old_control,"to":side_owner_ref(attacker),"evidence_ref":siege_info["siege_ref"],"basis":"autonomous_interstate_siege_capture","occupying_formations":a_block})
                                        front.setdefault("reduced_obstacle_refs",[]).append(blocker); front["reduced_obstacle_refs"]=sorted(set(front["reduced_obstacle_refs"])); front.pop("blocking_site_ref",None); front.pop("blocked_route_ref",None); front.pop("blocking_reason",None); front["status"]="advancing"; siege_active=False
                                    elif bool(siege_result.get("assault_ready")) and int(siege_result.get("defender_personnel",0))>0:
                                        front["status"]="siege_assault"; engaged=True
                                    else:
                                        front["status"]="besieging"
                                else:
                                    front["status"]="approaching_siege"; siege_active=True
                            else:
                                front["status"]="approaching_siege"; siege_active=True
                            continue
                        a_here=alive_refs(a_refs,at_location=obj); d_here=alive_refs(d_refs,at_location=obj)
                        if a_here and d_here:
                            if front.get("status")!="engaged":
                                front["contact_at"]=review_text
                                _append_bounded(record,"history",{"at":review_text,"event":"contact","front_ref":front.get("front_ref"),"location_ref":obj,"attacker_formations":a_here,"defender_formations":d_here},limit=32)
                            front["status"]="engaged"; engaged=True
                        elif a_here:
                            d_alive=alive_refs(d_refs)
                            if not d_alive:
                                if fortified_site_profile(self,obj):
                                    siege_info=ensure_autonomous_siege(self,theater_ref=tref,front=front,site_ref=obj,attacker_refs=a_refs,defender_refs=d_refs,attacker_side=attacker,defender_side=defender,at=review_text)
                                    if siege_info:
                                        siege_result=advance_autonomous_siege(self,siege_ref=str(siege_info["siege_ref"]),at=review_text,review_days=max(1,recurrence//86400),attacker_side=attacker); front["last_siege_review"]=_deepcopy(siege_result)
                                        if str(siege_result.get("status"))=="captured": front["status"]="occupation"; occupation=True
                                        elif bool(siege_result.get("assault_ready")) and int(siege_result.get("defender_personnel",0))>0: front["status"]="siege_assault"; engaged=True
                                        else: front["status"]="besieging"; siege_active=True
                                    else: front["status"]="besieging"; siege_active=True
                                else:
                                    front["status"]="occupation"; occupation=True
                            else:
                                front["status"]="advancing"
                        elif str(front.get("status","")) not in {"route_blocked"}:
                            front["status"]="advancing"
                    # A non-fortified/otherwise unresolved blocked axis must not
                    # freeze forever. Reuse another existing lawful campaign axis
                    # when possible; otherwise abandon this axis for later withdrawal.
                    for _front in fronts:
                        if isinstance(_front,dict) and str(_front.get("status",""))=="route_blocked":
                            _redirect=redirect_blocked_front(self,plan,side=attacker,front=_front,at=review_text)
                            if _redirect: _append_bounded(record,"history",{"at":review_text,"event":"strategic_front_replanned",**_redirect},limit=32)
                    record["contact_at"]=review_text if engaged else record.get("contact_at")
                    if engaged: record["phase"]="engaged"
                    elif occupation: record["phase"]="occupation"
                    else: record["phase"]="advancing"
                    continue
                if phase=="engaged":
                    plan=record.get("strategic_plan",{}) if isinstance(record.get("strategic_plan"),Mapping) else {}
                    fronts=plan.get("fronts",[]) if isinstance(plan.get("fronts"),list) else []
                    any_occupation=False; any_active=False; all_resolved=True; aggregate_retreats=[]
                    for front in fronts:
                        if not isinstance(front,dict): continue
                        front_status=str(front.get("status",""))
                        if front_status not in {"engaged","siege_assault"}:
                            if front_status in {"advancing","mobilizing","besieging","approaching_siege","route_blocked"}: any_active=True; all_resolved=False
                            if front_status=="occupation": any_occupation=True; all_resolved=False
                            continue
                        strategic_obj=str(front.get("objective_ref","")); battle_obj=str(front.get("blocking_site_ref") or strategic_obj); a_refs=[str(x) for x in front.get("attacker_formation_refs",[])]; d_refs=[str(x) for x in front.get("defender_formation_refs",[])]
                        siege=None; siege_path=None; fort=None; fort_path=None; siege_artillery=None
                        if front_status=="siege_assault":
                            _sidx=self.read("state/sieges/index.json"); siege_path=(_sidx.get("sieges",{}) or {}).get(str(front.get("siege_ref",""))) if isinstance(_sidx,Mapping) else None
                            if isinstance(siege_path,str):
                                siege=_deepcopy(self.read(siege_path)); d_refs=sorted(set(d_refs+[str(x) for x in siege.get("defender_formation_refs",[])]));
                                try: fort_path=self.owner_path(str(siege.get("fortification_ref",""))); fort=_deepcopy(self.read(fort_path))
                                except (KeyError,ValueError,FileNotFoundError): fort=None
                        a_contact=alive_refs(a_refs,at_location=battle_obj); d_contact=alive_refs(d_refs,at_location=battle_obj)
                        if not a_contact:
                            front["status"]="defender_holds" if front_status=="engaged" else "besieging"; all_resolved=front_status=="engaged"; any_active=front_status=="siege_assault"; continue
                        if not d_contact and front_status=="siege_assault":
                            transition=None
                            if isinstance(siege,dict) and isinstance(fort,dict):
                                physical=ensure_physical_state(fort); active_before=active_enclosure_ref(fort)
                                register_attacker_foothold(physical,method="breach",target_ref="gate",at=review_text,battle_ref=f"auto_unopposed:{str(siege.get('siege_ref',''))}:{active_before}:{review_text}")
                                commit_active_layer_projection(physical)
                                transition=advance_enclosure_layer(physical,at=review_text,battle_ref=f"auto_unopposed:{str(siege.get('siege_ref',''))}:{active_before}:{review_text}")
                                fort["physical_state"]=physical; sync_integrity_projection(fort); self.put(fort_path,fort)
                                siege["active_enclosure_ref"]=active_enclosure_ref(fort)
                                if transition.get("final_layer_secured"):
                                    siege["status"]="captured"; siege["outcome"]="unopposed_control_after_all_enclosures_secured"; siege["captured_at"]=review_text; siege["capture_basis"]="physical_enclosure_control"
                                self.put(siege_path,siege)
                            if isinstance(siege,dict) and str(siege.get("status",""))=="captured":
                                front["status"]="occupation" if battle_obj==strategic_obj else "advancing"; any_occupation=front["status"]=="occupation"; any_active=front["status"]=="advancing"
                            else:
                                front["status"]="besieging"; front["last_enclosure_transition"]=_deepcopy(transition); any_active=True
                            all_resolved=False; continue
                        if not d_contact:
                            front["status"]="advancing"; any_active=True; all_resolved=False; continue
                        duties_a=self._apply_unit_duties(a_contact,"battle",context_ref=f"{tref}:{front.get('front_ref')}:battle:{attacker}",at=review_text)
                        duties_d=self._apply_unit_duties(d_contact,"battle",context_ref=f"{tref}:{front.get('front_ref')}:battle:{defender}",at=review_text)
                        record.setdefault("front_unit_duties",{})[str(front.get("front_ref"))]={attacker:duties_a,defender:duties_d}
                        apow=group_power(a_contact,False,d_contact); dpow=group_power(d_contact,True,a_contact)
                        if front_status=="siege_assault" and isinstance(fort,Mapping) and hasattr(self,"_siege_prepare_fortress_artillery"):
                            siege_artillery=self._siege_prepare_fortress_artillery(fort,defender_refs=d_contact,battle_hours=6,at=review_text,attacker_refs=a_contact)
                            dpow*=max(1.0,float(siege_artillery.get("defender_power_factor_milli",1000))/1000.0)
                        withdrawal = contingency_withdrawal_decision(
                            plan, attacker=attacker, defender=defender, attacker_power=apow, defender_power=dpow,
                            attacker_reserve_available=bool(plan.get("strategic_reserve_commands", {}).get(attacker)),
                            defender_reserve_available=bool(plan.get("strategic_reserve_commands", {}).get(defender)),
                            fortified_contact=front_status == "siege_assault" or bool(fortified_site_profile(self, battle_obj)),
                        )
                        if withdrawal:
                            withdrawing_side=str(withdrawal["side"]); withdrawing_refs=a_contact if withdrawing_side==attacker else d_contact
                            home=side_home(withdrawing_side); retreats=[]
                            for ref in withdrawing_refs:
                                try: retreats.append({"formation_ref":ref,**self._autonomy_move_formation_step(ref,home,review_text)})
                                except ValueError: continue
                            aggregate_retreats.extend(retreats)
                            front["last_contingency_withdrawal"]={"at":review_text,**_deepcopy(withdrawal),"formation_refs":list(withdrawing_refs)}
                            _append_bounded(record,"history",{"at":review_text,"event":"operational_contingency_withdrawal","front_ref":front.get("front_ref"),**_deepcopy(withdrawal)},limit=32)
                            if withdrawing_side==attacker:
                                front["status"]="defender_holds"
                            else:
                                front["status"]="advancing"; any_active=True; all_resolved=False
                            continue
                        if_zero=apow<=0 or dpow<=0
                        if if_zero: winner=defender if apow<=0 else attacker
                        else:
                            variance_seed=int(hashlib.sha256((world_seed+"|battle|"+tref+"|"+str(front.get("front_ref"))+"|"+review_text+"|"+str(record.get("battle_count",0))).encode()).hexdigest()[:8],16); variance=.95+(variance_seed%1001)/10000.0; winner=attacker if apow*variance>=dpow else defender
                        loser=defender if winner==attacker else attacker; winner_refs=a_contact if winner==attacker else d_contact; loser_refs=d_contact if winner==attacker else a_contact; winner_power=apow if winner==attacker else dpow; loser_power=dpow if winner==attacker else apow; ratio=max(.25,min(4.0,winner_power/max(1.0,loser_power))); loser_rate=min(.45,.14+.05*max(0.0,ratio-1.0)); winner_rate=min(.22,.05+.025*max(0.0,1.0/ratio)); seed_material=world_seed+"|"+tref+"|"+str(front.get("front_ref"))+"|"+review_text
                        if front_status=="siege_assault":
                            # Assaults through a physical breach are more costly to both
                            # sides than open-field contact; fixed defenses already modify
                            # defender power through exact crewed/ammunition-limited fire.
                            loser_rate=min(.55,loser_rate+0.04); winner_rate=min(.30,winner_rate+0.03)
                        wloss=distribute_group_losses(winner_refs,winner_rate,review_text,losing_side=False,opponent=loser,seed_prefix=seed_material+"|winner")
                        lloss=distribute_group_losses(loser_refs,loser_rate,review_text,losing_side=True,opponent=winner,seed_prefix=seed_material+"|loser")
                        record["battle_count"]=int(record.get("battle_count",0))+1; eid="interstate_battle_"+hashlib.sha256((tref+"|"+str(front.get("front_ref"))+"|"+review_text).encode()).hexdigest()[:16]
                        hist.setdefault("events",[]).append({"event_id":eid,"kind":"interstate_siege_assault" if front_status=="siege_assault" else "interstate_battle","at":review_text,"theater_ref":tref,"front_ref":front.get("front_ref"),"battlefield_ref":battle_obj,"attacker_state":attacker,"defender_state":defender,"attacker_formation_refs":a_contact,"defender_formation_refs":d_contact,"winner_state":winner,"losses":{**wloss,**lloss},"fortress_artillery":_deepcopy(siege_artillery)})
                        record["last_battle_event"]=eid; record["last_winner_state"]=winner; front["last_battle_event"]=eid; front["last_winner_state"]=winner
                        retreats=[]
                        if front_status!="siege_assault":
                            home=side_home(loser)
                            for ref in loser_refs:
                                try: retreats.append({"formation_ref":ref,**self._autonomy_move_formation_step(ref,home,review_text)})
                                except ValueError: continue
                        aggregate_retreats.extend(retreats)
                        if winner==attacker:
                            if front_status=="siege_assault":
                                transition=None; final_contested=False
                                if isinstance(siege,dict) and isinstance(fort,dict):
                                    physical=ensure_physical_state(fort); active_before=active_enclosure_ref(fort)
                                    register_attacker_foothold(physical,method="breach",target_ref="gate",at=review_text,battle_ref=eid); commit_active_layer_projection(physical)
                                    layers=physical.get("enclosure_layers",[]) if isinstance(physical.get("enclosure_layers"),list) else []
                                    layer_index=max(0,min(len(layers)-1,int(physical.get("active_layer_index",0) or 0))) if layers else 0
                                    final_current=bool(layers and layer_index+1>=len(layers))
                                    remaining=0; morale_rows=[]
                                    for _ref in d_contact:
                                        try: _dfp,_df=self._load_formation(_ref)
                                        except ValueError: continue
                                        _n=max(0,int(_df.get("personnel",0))); remaining+=_n
                                        if _n>0: morale_rows.append(max(0,min(100,int(_df.get("morale",50)))))
                                    average_morale=sum(morale_rows)/max(1,len(morale_rows)) if morale_rows else 0.0
                                    pre_defenders=sum(max(0,int(self._load_formation(_ref)[1].get("personnel",0)))+max(0,int((lloss.get(_ref,{}) or {}).get("loss",0))) for _ref in d_contact if _ref)
                                    collapse=remaining<=0 or average_morale<=15.0 or remaining<=max(50,int(pre_defenders*0.25))
                                    if final_current and not collapse:
                                        final_contested=True
                                        transition={"advanced":False,"final_layer_secured":False,"active_layer_ref":active_before,"contested":True,"remaining_defenders":remaining,"average_defender_morale":round(average_morale,3)}
                                        commit_active_layer_projection(physical)
                                    else:
                                        transition=advance_enclosure_layer(physical,at=review_text,battle_ref=eid)
                                    fort["physical_state"]=physical; sync_integrity_projection(fort); self.put(fort_path,fort)
                                    siege["active_enclosure_ref"]=active_enclosure_ref(fort)
                                    if transition.get("final_layer_secured"):
                                        siege["status"]="captured"; siege["outcome"]="attacker_control_after_all_enclosures_secured"; siege["captured_at"]=review_text; siege["capture_battle_event"]=eid; siege["capture_basis"]="physical_enclosure_control_collapse"
                                    self.put(siege_path,siege)
                                if isinstance(siege,dict) and str(siege.get("status",""))=="captured":
                                    if battle_obj==strategic_obj:
                                        front["status"]="occupation"; front["defender_defeated"]=True; any_occupation=True; all_resolved=False
                                    else:
                                        front["status"]="advancing"; front["obstacle_siege_captured"]=True; any_active=True; all_resolved=False
                                else:
                                    front["status"]="siege_assault" if final_contested else "besieging"; front["last_enclosure_transition"]=_deepcopy(transition); any_active=True; all_resolved=False
                            else:
                                reinforcement=commit_one_reserve_command(plan,side=defender,front=front,at=review_text,reason="replace defeated front before occupation") if plan.get("strategic_reserve_commands",{}).get(defender) else None
                                if reinforcement:
                                    front["status"]="advancing"; front["defender_defeated"]=False; any_active=True; all_resolved=False; _append_bounded(record,"history",{"at":review_text,"event":"strategic_reserve_committed","side":defender,**reinforcement},limit=32)
                                else:
                                    front["status"]="occupation"; front["defender_defeated"]=True; any_occupation=True; all_resolved=False
                        else:
                            if front_status=="siege_assault":
                                front["status"]="besieging"; any_active=True; all_resolved=False
                            else:
                                reinforcement=commit_one_reserve_command(plan,side=attacker,front=front,at=review_text,reason="renew offensive after local defeat") if plan.get("strategic_reserve_commands",{}).get(attacker) else None
                                if reinforcement:
                                    front["status"]="advancing"; any_active=True; all_resolved=False; _append_bounded(record,"history",{"at":review_text,"event":"strategic_reserve_committed","side":attacker,**reinforcement},limit=32)
                                else:
                                    front["status"]="defender_holds"
                    record["last_retreats"]=aggregate_retreats
                    if any_occupation: record["phase"]="occupation"
                    elif any_active: record["phase"]="advancing"
                    elif all_resolved: record["phase"]="withdrawal"
                    continue
                if phase=="occupation":
                    plan=record.get("strategic_plan",{}) if isinstance(record.get("strategic_plan"),Mapping) else {}
                    fronts=plan.get("fronts",[]) if isinstance(plan.get("fronts"),list) else []
                    primary_occupied=False; active_front=False; attacker_gain=False
                    for front in fronts:
                        if not isinstance(front,dict) or str(front.get("status",""))!="occupation":
                            if isinstance(front,Mapping) and str(front.get("status","")) in {"advancing","engaged","mobilizing","besieging","approaching_siege","siege_assault","route_blocked"}: active_front=True
                            if isinstance(front,Mapping) and str(front.get("status",""))=="occupied": attacker_gain=True
                            continue
                        obj=str(front.get("objective_ref","")); a_refs=[str(x) for x in front.get("attacker_formation_refs",[])]; d_refs=[str(x) for x in front.get("defender_formation_refs",[])]
                        attackers_at=alive_refs(a_refs,at_location=obj); enemies=[]
                        for fr in self._formations_at(obj):
                            try: _,f=self._load_formation(fr)
                            except ValueError: continue
                            if int(f.get("personnel",0))>0 and (str(f.get("administrative_owner")) in side_authorities(defender) or str(f.get("owner_force_ref")) in side_force_refs(defender)): enemies.append(fr)
                        if not attackers_at:
                            front["status"]="defender_holds"; continue
                        if enemies and not bool(front.get("defender_defeated")):
                            front["status"]="engaged"; active_front=True; continue
                        # A field victory grants the approach, never ownership of
                        # intact walls. Fortified objectives must have an exact
                        # siege outcome before territorial control can change.
                        if fortified_site_profile(self,obj):
                            siege_info=ensure_autonomous_siege(self,theater_ref=tref,front=front,site_ref=obj,attacker_refs=a_refs,defender_refs=enemies or d_refs,attacker_side=attacker,defender_side=defender,at=review_text)
                            if not siege_info:
                                front["status"]="besieging"; active_front=True; continue
                            siege_result=advance_autonomous_siege(self,siege_ref=str(siege_info["siege_ref"]),at=review_text,review_days=max(1,recurrence//86400),attacker_side=attacker); front["last_siege_review"]=_deepcopy(siege_result)
                            if str(siege_result.get("status"))!="captured":
                                if bool(siege_result.get("assault_ready")) and int(siege_result.get("defender_personnel",0))>0:
                                    front["status"]="siege_assault"; record["phase"]="engaged"
                                else:
                                    front["status"]="besieging"
                                active_front=True; continue
                        obj_site=territory.get("sites",{}).get(obj)
                        if not isinstance(obj_site,dict):
                            front["status"]="route_blocked"; active_front=True; continue
                        old=str(obj_site.get("controller")); obj_site["controller"]=side_owner_ref(attacker); obj_site["previous_controller"]=old; obj_site["changed_at"]=review_text; obj_site["change_basis"]="autonomous_interstate_siege_capture" if fortified_site_profile(self,obj) else "autonomous_interstate_occupation"; obj_site["change_evidence_ref"]=str(front.get("siege_ref") or front.get("last_battle_event") or record.get("last_battle_event"))
                        eid="territory_auto_"+hashlib.sha256((tref+"|"+obj+"|"+review_text+"|"+attacker).encode()).hexdigest()[:16]
                        hist.setdefault("events",[]).append({"event_id":eid,"kind":"territorial_control_change","at":review_text,"theater_ref":tref,"front_ref":front.get("front_ref"),"location_ref":obj,"from":old,"to":side_owner_ref(attacker),"evidence_ref":front.get("siege_ref") or front.get("last_battle_event") or record.get("last_battle_event"),"basis":obj_site["change_basis"],"occupying_formations":attackers_at})
                        front["territory_event"]=eid; front["status"]="occupied"; attacker_gain=True
                        if attacker.startswith("polity_"):
                            pp,pd=side_doc(attacker); occupied=[str(x) for x in pd.setdefault("occupied_site_refs",[]) if isinstance(x,str)]
                            if obj not in occupied: occupied.append(obj)
                            pd["occupied_site_refs"]=sorted(set(occupied)); pd.setdefault("territorial_history",[]).append({"at":review_text,"location_ref":obj,"from":old,"evidence_ref":front.get("siege_ref") or front.get("last_battle_event"),"basis":obj_site["change_basis"]}); pd["territorial_history"]=pd["territorial_history"][-32:]; self.put(pp,pd)
                        if obj==target: primary_occupied=True; record["territory_event"]=eid
                    primary_occupied = primary_occupied or any(isinstance(x,Mapping) and str(x.get("objective_ref",""))==target and str(x.get("status",""))=="occupied" for x in fronts)
                    attacker_gain = attacker_gain or any(isinstance(x,Mapping) and str(x.get("status",""))=="occupied" for x in fronts)
                    if active_front:
                        record["phase"]="engaged" if any(str(x.get("status","")) in {"engaged","siege_assault"} for x in fronts if isinstance(x,Mapping)) else "advancing"
                    elif war_fronts_resolved([x for x in fronts if isinstance(x,Mapping)]):
                        if primary_occupied:
                            record["war_result"]="attacker_occupation"
                        elif attacker_gain:
                            record["war_result"]="partial_attacker_gains"
                        else:
                            record["war_result"]="defender_holds"
                        record["phase"]="peace_settlement"
                    else:
                        record["phase"]="advancing"
                    continue
                if phase=="withdrawal":
                    retreats=[]
                    record["unit_duties"]={attacker:self._apply_unit_duties(alive_refs(afs),"retreat",context_ref=f"{tref}:{record.get('cycle')}:withdraw:{attacker}",at=review_text)}
                    for ref in alive_refs(afs):
                        try:
                            _fp,live=self._load_formation(ref)
                            if str(live.get("location_ref",""))==side_home(attacker): continue
                            retreats.append({"formation_ref":ref,**self._autonomy_move_formation_step(ref,side_home(attacker),review_text)})
                        except ValueError: continue
                    record["last_withdrawals"]=retreats; record["war_result"]=record.get("war_result") or "defender_holds"; record["phase"]="peace_settlement"; continue
                if phase=="peace_settlement":
                    cooldown=max(1,min(8,1+2*int(record.get("battle_count",0)))); truce_until=str(review.add_seconds(cooldown*recurrence)); treaty_ref="treaty_"+hashlib.sha256((tref+"|"+str(record.get("cycle"))+"|"+review_text).encode()).hexdigest()[:18]; current_controller=str(site.get("controller","")); treaty={"treaty_ref":treaty_ref,"kind":"ceasefire_and_war_settlement","parties":sorted({side_owner_ref(attacker),side_owner_ref(defender)}),"status":"active","signed_at":review_text,"theater_ref":tref,"war_result":record.get("war_result"),"truce_until":truce_until,"terms":{"ceasefire":True,"nonaggression_until":truce_until,"territorial_status":{"location_ref":target,"military_controller":current_controller,"legal_claim_resolution":"not_implied_by_military_control"},"withdrawal_rule":"forces cease offensive advance during the truce unless treaty is broken","reparations_silver":0,"claims_preserved":True},"provenance":{"kind":"autonomous_interstate_settlement","battle_count":int(record.get("battle_count",0)),"last_battle_event":record.get("last_battle_event")}}; treaties.setdefault("records",{})[treaty_ref]=treaty
                    for a,b in ((attacker,defender),(defender,attacker)):
                        sp,sd=side_doc(a); sd.setdefault("diplomacy",{})[side_owner_ref(b)]={"tension":25,"status":"armed_peace","theater_ref":tref,"settled_at":review_text,"treaty_ref":treaty_ref,"truce_until":truce_until,"negotiation_status":"settlement_in_force"}; sd.setdefault("war_history",[]).append({"theater_ref":tref,"cycle":record.get("cycle"),"started_at":record.get("started_at"),"settled_at":review_text,"result":record.get("war_result"),"treaty_ref":treaty_ref}); sd["war_history"]=sd["war_history"][-16:]; self.put(sp,sd)
                    from sword_runtime.campaign_closure import schedule_war_closure_ceremonies
                    closure=schedule_war_closure_ceremonies(self,war_scope_ref=tref,party_refs=[side_owner_ref(attacker),side_owner_ref(defender)],at=review_text,result=str(record.get("war_result") or "settled"),treaty_ref=treaty_ref)
                    treaty["war_closure_event_ref"]=closure.get("event_id")
                    treaty["postwar_ceremony_refs"]=[str(row.get("ceremony_ref")) for row in closure.get("ceremonies",[]) if isinstance(row,Mapping) and row.get("ceremony_ref")]
                    record["postwar_closure_event_ref"]=closure.get("event_id")
                    record["postwar_ceremony_refs"]=list(treaty["postwar_ceremony_refs"])
                    record["last_treaty_ref"]=treaty_ref; _append_bounded(record,"history",{"at":review_text,"event":"peace_settlement","result":record.get("war_result"),"treaty_ref":treaty_ref,"truce_until":truce_until,"war_closure_event_ref":closure.get("event_id")},limit=32); record["phase"]="peace"; record["pressure"]=int(cfg.get("base_pressure",20)); record["cooldown_reviews"]=cooldown; record.pop("attacker_state",None); record.pop("defender_state",None); continue
        world["last_review"]=at; self.put(path,world); self.put("state/territory/control.json",territory); self.put("state/politics/treaties.json",treaties); write_history_index(self, hist)
        # Peace needs only a monthly strategic review. Once any theater has entered
        # a real war phase, the same single host switches to a weekly operational
        # cadence so mobilization, supply, marches, contact, battle and settlement
        # do not each consume a whole month. The cadence is shared data, not a
        # state-specific bonus, and returns to monthly when all theaters are at peace.
        theater_rules = config if isinstance(config, Mapping) else {}
        peace_seconds = max(86400, int(theater_rules.get("review_seconds", 30 * 86400)))
        active_seconds = max(86400, min(peace_seconds, int(theater_rules.get("active_review_seconds", 7 * 86400))))
        any_active = any(isinstance(row, Mapping) and str(row.get("phase", "peace")) != "peace" for row in world.get("theaters", {}).values())
        desired_seconds = active_seconds if any_active else peace_seconds
        runtime = _deepcopy(self.read("state/runtime.json"))
        for live_host in runtime.get("hosts", {}).values():
            if isinstance(live_host, dict) and str(live_host.get("kind")) == "interstate" and str(live_host.get("owner_ref")) == str(host.get("owner_ref")):
                live_host["recurrence_seconds"] = desired_seconds
        self.put("state/runtime.json", runtime)

    def _autonomy_population(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        """Settle annual aggregate births and ordinary civilian deaths explicitly.

        Military/service bodies are not silently removed here because their force
        authorities must reconcile losses. Ordinary demography therefore applies
        mortality to civilian strata only, while battle/disease/service mechanics
        continue to own their own conserved deaths.
        """
        owner_ref = str(host["owner_ref"])
        path = self.owner_path(owner_ref)
        pop = _deepcopy(self.read(path))
        strata = pop.get("strata")
        if not isinstance(strata, dict):
            raise ValueError("population strata are invalid")
        dem = pop.get("demography")
        if not isinstance(dem, dict):
            raise ValueError("scheduled population owner lacks demographic rules")
        birth_rate = _fixed(dem.get("birth_rate_per_thousand")) / 1000.0
        death_rate = _fixed(dem.get("death_rate_per_thousand")) / 1000.0
        years = max(0, int(occurrences))
        births_total = 0
        deaths_total = 0
        deaths_by_stratum: dict[str, int] = {}
        service_keys = set(dem.get("service_strata", [
            "active_military", "private_household_military", "foreign_military_service",
            "rebel_military", "recruitment_candidates_reserved",
        ]))
        dependent_key = str(dem.get("dependent_stratum", "dependents_children_elderly"))
        if dependent_key not in strata:
            raise ValueError("demographic dependent stratum is absent from population owner")

        for _ in range(years):
            total = max(1, sum(max(0, int(value)) for value in strata.values()))
            births = max(0, int(round(total * birth_rate)))
            requested_deaths = max(0, int(round(total * death_rate)))
            civilian = {
                key: max(0, int(value))
                for key, value in strata.items()
                if key not in service_keys and max(0, int(value)) > 0
            }
            death_cap = sum(civilian.values())
            deaths = min(requested_deaths, death_cap)
            removal: dict[str, int] = {key: 0 for key in civilian}
            if deaths and civilian:
                weighted = {
                    key: count * (240 if key == dependent_key else 100)
                    for key, count in civilian.items()
                }
                denom = max(1, sum(weighted.values()))
                raw = {key: deaths * weight / denom for key, weight in weighted.items()}
                for key, value in raw.items():
                    removal[key] = min(civilian[key], int(math.floor(value)))
                remaining = deaths - sum(removal.values())
                order = sorted(
                    civilian,
                    key=lambda key: (-(raw[key] - math.floor(raw[key])), key),
                )
                while remaining > 0:
                    progressed = False
                    for key in order:
                        if remaining <= 0:
                            break
                        if removal[key] >= civilian[key]:
                            continue
                        removal[key] += 1
                        remaining -= 1
                        progressed = True
                    if not progressed:
                        break
            for key, count in removal.items():
                if count:
                    strata[key] = max(0, int(strata.get(key, 0)) - count)
                    deaths_by_stratum[key] = deaths_by_stratum.get(key, 0) + count
            strata[dependent_key] = int(strata.get(dependent_key, 0)) + births
            births_total += births
            deaths_total += deaths

        pop["population_total"] = sum(max(0, int(value)) for value in strata.values())
        dem["closes"] = int(dem.get("closes", 0)) + years
        dem["last_close"] = at
        dem["last_births"] = births_total
        dem["last_deaths"] = deaths_total
        dem["last_deaths_by_stratum"] = dict(sorted(deaths_by_stratum.items()))
        dem["births_cumulative"] = int(dem.get("births_cumulative", 0)) + births_total
        dem["deaths_cumulative"] = int(dem.get("deaths_cumulative", 0)) + deaths_total
        self.put(path, pop)

    def _autonomy_house(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        house_ref = str(host["owner_ref"])
        path = self.owner_path(house_ref)
        house = _deepcopy(self.read(path))
        cohort = house.setdefault("lineage_cohort", {})
        ensure_house_lineage_representation(self, house, at=at)
        recompute_house_lineage(self, house, at=at)
        house["last_review"] = at

        # House military recruitment is voluntary/private service from conserved population.
        # It never invokes sovereign levy authority and never mints a special House role.
        force_ref = house.get("military_force_ref")
        if isinstance(force_ref, str):
            force_path = self.owner_path(force_ref)
            force = _deepcopy(self.read(force_path))
            authorized = int(force.get("authorized_strength", force.get("headcount", 0)))
            shortage = max(0, authorized - int(force.get("headcount", 0)))
            if shortage:
                state = self._state_key(house.get("state"))
                population_path = f"state/population/{state}.json"
                population = _deepcopy(self.read(population_path))
                source = "household_and_service"
                available = int(population.get("strata", {}).get(source, 0))
                recruits = min(shortage, available, max(1, 25 * occurrences))
                if recruits:
                    population["strata"][source] -= recruits
                    population["strata"]["private_household_military"] = int(population["strata"].get("private_household_military", 0)) + recruits
                    force["headcount"] = int(force.get("headcount", 0)) + recruits
                    role_totals: dict[str, int] = {}
                    for allocation in (force.get("allocated_to_formations", {}) or {}).values():
                        if isinstance(allocation, Mapping):
                            role = str(allocation.get("role", ""))
                            if role and role != "command_personnel":
                                role_totals[role] = role_totals.get(role, 0) + max(0, int(allocation.get("personnel", 0)))
                    available_roles = [str(k) for k in (force.get("available_by_role", {}) or {}) if str(k) != "command_personnel"]
                    role = "household_retainer" if "household_retainer" in available_roles else (max(role_totals, key=lambda k: (role_totals[k], k)) if role_totals else (sorted(available_roles)[0] if available_roles else "line_infantry"))
                    force.setdefault("available_by_role", {})[role] = int(force.setdefault("available_by_role", {}).get(role, 0)) + recruits
                    source_loc = str(force.get("source_location_ref") or house.get("location_ref") or f"loc_{state}")
                    local = self._force_location_pool(force, source_loc)
                    local[role] = int(local.get(role, 0)) + recruits
                    self.put(population_path, population)
            self.put(force_path, force)

        projects = house.setdefault("projects", [])
        now = CampaignTime.parse(at)
        settled = 0
        for project in projects:
            if str(project.get("status")) not in {"scheduled", "active"} or not project.get("completes_at"):
                continue
            if CampaignTime.parse(str(project["completes_at"])) > now:
                continue
            kind = str(project.get("kind", "review")); subject = project.get("subject_ref")
            if kind in {"assign_duty", "appointment"} and subject:
                house.setdefault("duties", []).append({"subject_ref": subject, "kind": kind, "effective_at": str(project["completes_at"])})
                house["duties"] = house["duties"][-32:]
            else:
                house.setdefault("resolved_effects", {})[kind] = int(house.get("resolved_effects", {}).get(kind, 0)) + 1
            project["status"] = "completed"; project["resolved_at"] = str(project["completes_at"]); project["resolution_basis"] = "house causal review"; settled += 1
        threat = _fixed(house.get("threat_level", "0"))
        action = "guard_readiness" if threat >= 0.5 else "estate_and_retainer_review"
        self.put(path, house)

    def _autonomy_institution(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        p=self.owner_path(str(host["owner_ref"])); inst=_deepcopy(self.read(p)); inst["last_review"]=at
        kind=inst.get("kind"); state=self._state_key(inst.get("state"))
        if kind=="horse_administration":
            mp=f"state/mounts/{state}.json"; mounts=_deepcopy(self.read(mp)); recovering=int(mounts["health"].get("recovering",0)); recover=min(recovering,int(inst.get("capacity",500))*occurrences)
            mounts["health"]["recovering"]-=recover; mounts["health"]["fit"]+=recover; self.put(mp,mounts)
        elif kind=="granary_depot_office":
            dp=f"state/depots/{state}.json"; depot=_deepcopy(self.read(dp)); cap=max(1,int(inst.get("capacity",1000))); depot["stocks"]["grain_kg"]+=cap*occurrences; self.put(dp,depot)
        inst["backlog"]=max(0,int(inst.get("backlog",0))-int(inst.get("capacity",0))*occurrences)
        # Projects settle from their saved completion time during the institution's
        # normal causal review. A long time skip cannot leave completed work inert.
        settled=[]
        for project in inst.get("projects",[]):
            if str(project.get("status"))!="active" or not project.get("completes_at"): continue
            if CampaignTime.parse(str(project["completes_at"]))>CampaignTime.parse(at): continue
            kind=str(project.get("kind","capacity")); magnitude=max(1,int(project.get("magnitude",1))); effect=project.get("effect",{}) if isinstance(project.get("effect"),dict) else {}
            if kind in {"capacity","construction","expansion"}: inst["capacity"]=max(0,int(inst.get("capacity",0))+magnitude)
            elif kind in {"backlog","process"}: inst["backlog"]=max(0,int(inst.get("backlog",0))-magnitude)
            elif kind in {"stock","resource","logistics"}:
                key=str(effect.get("resource","generic_stock")); inst.setdefault("resources",{})[key]=int(inst.get("resources",{}).get(key,0))+magnitude
            else: inst.setdefault("resolved_effects",{})[kind]=int(inst.get("resolved_effects",{}).get(kind,0))+magnitude
            project["status"]="completed"; project["resolved_at"]=str(project["completes_at"]); project["resolution_basis"]="institution causal review"; settled.append(str(project.get("project_ref")))
        if settled: inst.setdefault("runtime",{})["projects_settled"]=int(inst.get("runtime",{}).get("projects_settled",0))+len(settled)
        self.put(p,inst)

    def _autonomy_faction(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        p=self.owner_path(str(host["owner_ref"])); doc=_deepcopy(self.read(p)); doc["last_review"]=at
        pressure=_clamp(int(doc.get("pressure",0))+min(20,occurrences*2)); doc["pressure"]=pressure
        if pressure>=40 and doc.get("goals"):
            doc["last_action"]={"at":at,"action":"advance_goal","goal":doc["goals"][0]}
            doc["action_count"]=int(doc.get("action_count",0) or 0)+1
            doc.pop("commitments",None)
            doc["pressure"]=max(0,pressure-20)
        self.put(p,doc)

    def _autonomy_house_tang_training(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        # Low-level reducer parity: the production planner owns full deterministic
        # cohort settlement. The base planner still recognizes the current unified
        # host and records chronology without resurrecting retired institutions.
        p="state/forces/house-tang.json"; doc=_deepcopy(self.read(p)); doc["cohort_training_closes"]=int(doc.get("cohort_training_closes",0))+max(0,int(occurrences)); doc["last_review"]=at; self.put(p,doc)

    def _autonomy_mercenary(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        owner_ref=str(host["owner_ref"]); path=self.owner_path(owner_ref); doc=_deepcopy(self.read(path))
        if doc.get("status") in {"destroyed","dissolved"}: self.put(path,doc); return
        contracts=doc.setdefault("contracts",[]); now=CampaignTime.parse(at); headcount=max(1,int(doc.get("headcount",doc.get("count",doc.get("personnel",doc.get("strength",1)))))); econ=self.read("game/data/mechanics/economy.json"); monthly=_fixed(econ.get("wages",{}).get("professional_soldier_monthly_silver",7)); factor=_fixed(self.read("game/data/mechanics/career.json").get("service_models",{}).get("army_model_mercenary",{}).get("cash_pay_factor_vs_common_role_baseline",1.35),1.35)
        active=None
        for contract in contracts:
            status=str(contract.get("status","")); term=max(1,int(contract.get("term_days",90))); amount=max(0,int(contract.get("amount_silver",0))); minimum=int(math.ceil(headcount*monthly*factor*term/30.0))
            contract["minimum_fair_value_silver"]=minimum
            if status in {"offered","renewal_offered"}:
                if amount>=minimum:
                    contract["status"]="accepted_unpaid" if status=="offered" else "renewal_accepted"; contract["accepted_at"]=at; contract["decision_basis"]="offer meets deterministic pay floor"
                else:
                    contract["status"]="rejected"; contract["rejected_at"]=at; contract["decision_basis"]="offer below deterministic pay floor"
            status=str(contract.get("status",""))
            if status=="active":
                active=contract; active_at=CampaignTime.parse(str(contract.get("active_at",at))); expires=active_at.add_days(term); contract["expires_at"]=str(expires)
                if now>=expires:
                    contract["status"]="completed"; contract["completed_at"]=str(expires); contract["completion_basis"]="contract term elapsed"; active=None
            elif status in {"accepted_unpaid","renewal_accepted"}:
                accepted_at=CampaignTime.parse(str(contract.get("accepted_at",contract.get("renewal_offered_at",at))))
                if accepted_at.seconds_until(now)>30*86400:
                    contract["status"]="breached"; contract["breached_at"]=at; contract["breach_reason"]="employer failed to fund accepted contract within 30 days"
        if active is not None: doc["status"]="deployed" if active.get("deployment_location_ref") else "contracted"
        elif any(str(c.get("status")) in {"accepted_unpaid","renewal_accepted"} for c in contracts): doc["status"]="contracted_unpaid"
        elif any(str(c.get("status")) in {"offered","renewal_offered"} for c in contracts): doc["status"]="considering_offer"
        else: doc["status"]="available"
        doc["contracts"] = compact_mercenary_contracts(contracts)
        self.put(path,doc)

    def _battle(
        self,
        command: CommandEnvelope,
        payload: Mapping[str, Any],
        *,
        context: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        attackers=[str(x) for x in payload.get("attacker_formation_refs",[])]; defenders=[str(x) for x in payload.get("defender_formation_refs",[])]
        if not attackers or not defenders: raise ValueError("battle requires saved attacker and defender formations")
        all_refs=attackers+defenders
        if len(set(all_refs))!=len(all_refs): raise ValueError("a formation may not appear on both battle sides")
        formations={ref:(lambda pf:(pf[0],_deepcopy(pf[1])))(self._load_formation(ref)) for ref in all_refs}
        locations={str(formations[ref][1].get("location_ref")) for ref in all_refs}
        if len(locations)!=1: raise ValueError("battle rejected: formations are not co-located on one battlefield")
        battlefield=next(iter(locations)); location=self._location_record(battlefield)
        operation_ref=""
        internal_operational_contact = bool(isinstance(context, Mapping) and context.get("kind") == "operational_autonomous_contact")
        if context is None or internal_operational_contact:
            operation_ref=str((context or {}).get("operation_ref") or payload.get("operation_ref", ""))
            if not operation_ref: raise ValueError("field battle requires an active saved operation proving contact")
            op_path=self.read("state/operations/index.json").get("operations",{}).get(operation_ref)
            if not op_path: raise ValueError("unknown battle operation")
            operation=self.read(op_path)
            if operation.get("status") not in {"active","engaged"}: raise ValueError("battle operation is not active")
            if operation.get("location_ref")!=battlefield: raise ValueError("battle operation location does not match formation contact")
            if not set(all_refs).issubset(set(str(x) for x in operation.get("formation_refs",[]))): raise ValueError("battle formations are not all participants in the saved operation")
            contact_proof=str((context or {}).get("contact_ref") or operation_ref)
        else:
            if context.get("location_ref")!=battlefield: raise ValueError("battle context location does not match exact formation contact")
            contact_proof=str(context.get("contact_ref",context.get("kind","context")))

        def _battle_seed(salt: str) -> int:
            if internal_operational_contact:
                material = f"{command.semantic_digest}|{contact_proof}|{(context or {}).get('started_at')}|{(context or {}).get('completed_at')}|{salt}"
                return int(hashlib.sha256(material.encode("utf-8")).hexdigest()[:16], 16)
            return self._causal_seed(command, payload, salt)

        battle_resolution_clock = (
            CampaignTime.parse(str(context.get("started_at")))
            if internal_operational_contact and isinstance(context, Mapping) and context.get("started_at")
            else self._world_time()
        )
        self._apply_unit_duties(attackers, "battle", context_ref=f"{contact_proof}:attacker", at=str(battle_resolution_clock))
        self._apply_unit_duties(defenders, "battle", context_ref=f"{contact_proof}:defender", at=str(battle_resolution_clock))
        formations={ref:(lambda pf:(pf[0],_deepcopy(pf[1])))(self._load_formation(ref)) for ref in all_refs}
        terrain_kind=str((context or {}).get("terrain_kind") or terrain_context_for_location(self,battlefield)["encoded"]); combat_forces={}; combat_rows={}
        if hasattr(self,"_combat_prepare_formation"):
            for ref in all_refs:
                cpath,cformation,cforce=self._combat_prepare_formation(ref); formations[ref]=(cpath,_deepcopy(cformation)); combat_forces[ref]=_deepcopy(cforce); combat_rows[ref]=[dict(x) for x in self._combat_cohort_snapshot(cformation,cforce)]
        represented=sum(int(formations[r][1].get("personnel",0)) for r in all_refs)
        base_battle_hours=max(1,min(12,2+int(math.log10(max(10,represented)))))
        operational_battlefield_ref=(context or {}).get("battlefield_ref") if internal_operational_contact else payload.get("battlefield_ref")
        operational_sector_ref=(context or {}).get("sector_ref") if internal_operational_contact else payload.get("sector_ref")
        if bool(operational_battlefield_ref) != bool(operational_sector_ref):
            raise ValueError("operational battle contact requires both battlefield_ref and sector_ref")
        contact_plan: Dict[str, Any]={}
        operational_contact=bool(operation_ref and operational_battlefield_ref and operational_sector_ref and (context is None or internal_operational_contact))
        if operational_contact:
            _op_path,_op_doc,operational_battlefield=self._battlefield_validate_contact(
                operation_ref=str(operation_ref),
                battlefield_ref=str(operational_battlefield_ref),
                sector_ref=str(operational_sector_ref),
                attacker_refs=attackers,
                defender_refs=defenders,
            )
            if internal_operational_contact:
                raw_plan=(context or {}).get("contact_plan")
                if not isinstance(raw_plan, Mapping):
                    raise ValueError("autonomous operational contact requires a precomputed contact plan")
                contact_plan=_deepcopy(dict(raw_plan))
            else:
                contact_plan=self._battle_lifecycle_contact_plan(
                    operational_battlefield,
                    attacker_refs=attackers,
                    start=self._world_time(),
                    base_battle_hours=float(base_battle_hours),
                    operation_ref=str(operation_ref),
                    battlefield_ref=str(operational_battlefield_ref),
                )
            battle_hours=float(contact_plan["duration_hours"])
            contact_duration_factor=float(contact_plan.get("casualty_duration_factor",1.0) or 1.0)
        else:
            battle_hours=float(base_battle_hours)
            contact_duration_factor=1.0
        battle_duration_seconds=max(1,int(round(float(battle_hours)*3600)))
        admission={}; commander_scores={}; ammo_plans={}; combat_named={}
        for ref in all_refs:
            formation_path,formation=formations[ref]
            movement = formation.get("operational_movement") if isinstance(formation.get("operational_movement"), Mapping) else None
            ready_text = str(movement.get("deployment_ready_at", "")) if movement else ""
            if ready_text:
                ready_at = CampaignTime.parse(ready_text)
                now = battle_resolution_clock
                if now < ready_at:
                    raise ValueError(f"battle rejected: {ref} is still deploying until {ready_text}")
                if str(formation.get("status", "")) == "arrived_forming":
                    formation["status"] = "ready"
                    formation["last_deployment_ready_at"] = ready_text
                    formations[ref] = (formation_path, formation)
                    self.put(formation_path, formation)
            if not bool(formation.get("mobilized",False)): raise ValueError(f"battle rejected: {ref} is not mobilized")
            if int(formation.get("personnel",0))<=0: raise ValueError(f"battle rejected: {ref} has no personnel")
            authority=str(formation.get("command_authority",""))
            if not authority: raise ValueError(f"battle rejected: {ref} has no command authority")
            if authority!=self.PLAYER_ACTOR: self.owner(authority)
            command_admission=self._combat_command_admission(formation) if hasattr(self,"_combat_command_admission") else {"mode":"exact_commander","commander_ref":formation.get("commander_ref")}
            commander_ref=command_admission.get("commander_ref"); commander_path=None; commander=None; command_mode=str(command_admission.get("mode","exact_commander"))
            if commander_ref:
                commander_path,commander=self._validate_person_location_for_formation(str(commander_ref),formation); self.put(commander_path,commander)
            n=int(formation["personnel"]); logistics=formation.setdefault("logistics",{})
            # Strategic military supply is a derived campaign condition, not a
            # ration/feed inventory.  Battle capability reads that condition below;
            # contact never consumes abstract rations or creates a second supply owner.
            supply_state=evaluate_military_supply(self,formation,at=str(battle_resolution_clock))
            if int(formation.get("fatigue",0))>=95: raise ValueError(f"battle rejected: {ref} is too fatigued for deliberate engagement")
            caps=commander.get("capabilities",commander.get("skills",{})) if isinstance(commander,Mapping) else {}; command_score=sum(_fixed(caps.get(k,0)) for k in ("Formation Command","Tactics","Leadership","Strategy","Formation Fighting")) if isinstance(caps,dict) else 0.0; commander_scores[ref]=command_score
            rows=combat_rows.get(ref,[])
            if hasattr(self,"_combat_named_participants") and ref in combat_forces: combat_named[ref]=self._combat_named_participants(formation,combat_forces[ref])
            else: combat_named[ref]=[]
            # Formation logistics owns anonymous/cohort missile stock. Exact named
            # people carry and persist their own ammunition separately.
            ammo_rows=list(rows)
            if hasattr(self,"_combat_ammunition_plan"): ammo_plans[ref]=self._combat_ammunition_plan(ammo_rows,logistics,float(battle_hours))
            else: ammo_plans[ref]={"overall_sufficiency":1.0,"consumed_by_resource":{},"desired_by_resource":{},"ranged_personnel":0}
            admission[ref]={"supply_condition":str(supply_state.get("condition","adequate")),"supply_score_milli":int(supply_state.get("score_milli",1000) or 1000),"commander_ref":str(commander_ref) if commander_ref else None,"commander_path":commander_path,"command_mode":command_mode}

        def terrain_role_factor(formation: Mapping[str,Any]) -> float:
            comp=formation.get("composition",{}); total=max(1,sum(int(v) for v in comp.values())); weighted=0.0
            for role,count in comp.items():
                r=str(role).lower(); factor=1.0
                if terrain_has(terrain_kind,"pass","fortified"):
                    if "cavalry" in r or "chariot" in r: factor*=.78
                    if any(x in r for x in ("infantry","guard","crossbow","archer")): factor*=1.10
                    if "siege" in r or "engineer" in r: factor*=1.08
                elif terrain_has(terrain_kind,"urban"):
                    if "cavalry" in r or "chariot" in r: factor*=.82
                    if any(x in r for x in ("infantry","guard","crossbow")): factor*=1.06
                elif terrain_has(terrain_kind,"plain","steppe") and ("cavalry" in r or "chariot" in r): factor*=1.10
                weighted+=int(count)*factor
            return weighted/total

        def doctrine_factor(formation: Mapping[str,Any]) -> tuple[float,float]:
            doctrine=formation.get("doctrine_behavior",{}); reserve=_clamp(int(doctrine.get("reserve_commitment",50))); power=.85+.30*(reserve/100); casualty=1.0; tolerance=str(doctrine.get("casualty_tolerance","moderate")).lower()
            if "low" in tolerance: power*=.96; casualty*=.78
            elif "high" in tolerance: power*=1.05; casualty*=1.18
            extraction=_clamp(int(doctrine.get("extraction_priority",0)))
            if extraction>=80: power*=.92; casualty*=.80
            return power,casualty

        # Resolve a bounded sequence of aggregate contact phases before scoring
        # the battle. This is deliberately not a per-soldier turn engine. Each
        # phase re-snapshots the same conserved formation after ammunition use,
        # shield/armor attrition and cohesion wear so later phases cannot reuse
        # pristine opening conditions.
        phase_rules=self._combat_interaction_rules() if hasattr(self,"_combat_interaction_rules") else {}
        raw_phases=phase_rules.get("contact_phases",[]) if isinstance(phase_rules,Mapping) else []
        phase_specs=[dict(x) for x in raw_phases if isinstance(x,Mapping) and float(x.get("duration_fraction",0) or 0)>0]
        if not phase_specs:
            phase_specs=[{"id":"opening","duration_fraction":.25,"contact_wear_factor":.75,"cohesion_wear_factor":.65},{"id":"sustained","duration_fraction":.50,"contact_wear_factor":1.15,"cohesion_wear_factor":1.10},{"id":"resolution","duration_fraction":.25,"contact_wear_factor":.90,"cohesion_wear_factor":.85}]
        phase_fraction_total=sum(max(0.0,float(x.get("duration_fraction",0) or 0)) for x in phase_specs) or 1.0
        virtual_formations={ref:_deepcopy(formations[ref][1]) for ref in all_refs}
        sustainment_rules=self.read(BATTLE_SUSTAINMENT_RULES_PATH)
        battle_sustainment={
            ref: initialize_battle_sustainment(
                formations[ref][1],
                combat_rows.get(ref,[]),
                initial_shields=self._shield_units(formations[ref][1]),
                initial_armor=self._armor_units(formations[ref][1]),
            )
            for ref in all_refs
        }
        phased_physical={ref:[] for ref in all_refs}; battle_phase_trace=[]
        phase_ammo_totals={ref:{"desired_by_resource":{},"consumed_by_resource":{},"ranged_personnel":0} for ref in all_refs}
        phase_damage_profile={ref:{"shield":{},"armor":{}} for ref in all_refs}
        phase_mount_losses={ref:0 for ref in all_refs}
        local_breach_threshold=max(5.0,min(90.0,float(phase_rules.get("local_breach_threshold_pct",35.0) or 35.0))) if isinstance(phase_rules,Mapping) else 35.0
        local_breach_penalty=max(0.0,min(.20,float(phase_rules.get("local_breach_exploitation_penalty_per_sector",.055) or .055))) if isinstance(phase_rules,Mapping) else .055
        local_breach_penalty_cap=max(0.0,min(.40,float(phase_rules.get("local_breach_exploitation_penalty_cap",.15) or .15))) if isinstance(phase_rules,Mapping) else .15
        phase_sector_state={}
        for ref in all_refs:
            vf=virtual_formations[ref]; cohesion=max(0.0,min(100.0,float(vf.get("cohesion",50) or 50)))
            base=max(20.0,min(100.0,35.0+.65*cohesion))
            sectors={}
            for sector in ("left","center","right"):
                # Deterministic, bounded asymmetry prevents every local front from
                # collapsing at exactly the same instant without inventing soldiers.
                digest=hashlib.sha256(f"{command.semantic_digest}|{ref}|sector|{sector}".encode()).digest()
                offset=((int.from_bytes(digest[:2],"big")%1001)/1000.0-.5)*8.0
                sectors[sector]=max(0.0,min(100.0,base+offset))
            phase_sector_state[ref]=sectors
        for phase_index,spec in enumerate(phase_specs):
            phase_id=str(spec.get("id",f"phase_{phase_index+1}")); phase_fraction=max(0.0,float(spec.get("duration_fraction",0) or 0))/phase_fraction_total; phase_hours=max(.001,float(battle_hours)*phase_fraction)
            contact_wear_factor=max(0.0,float(spec.get("contact_wear_factor",1.0) or 1.0)); cohesion_wear_factor=max(0.0,float(spec.get("cohesion_wear_factor",1.0) or 1.0))
            phase_rows={}; phase_support_absence={}
            for ref in all_refs:
                full_rows=[dict(x) for x in self._combat_cohort_snapshot(virtual_formations[ref],combat_forces[ref])]
                absence=dict(battle_sustainment[ref].pop("pending_absence_by_role",{}) or {})
                phase_support_absence[ref]=absence
                phase_rows[ref]=apply_role_absence(full_rows,absence)
            phase_ammo={}
            for ref in all_refs:
                frontline=battle_sustainment[ref].get("frontline_ammunition",{}) if isinstance(battle_sustainment[ref].get("frontline_ammunition"),Mapping) else {}
                phase_ammo[ref]=self._combat_ammunition_plan(phase_rows[ref],frontline,phase_hours) if hasattr(self,"_combat_ammunition_plan") else {"overall_sufficiency":1.0,"consumed_by_resource":{},"desired_by_resource":{},"ranged_personnel":0}
                totals=phase_ammo_totals[ref]
                totals["ranged_personnel"]=max(int(totals.get("ranged_personnel",0)),int(phase_ammo[ref].get("ranged_personnel",0) or 0))
                for field in ("desired_by_resource","consumed_by_resource"):
                    for resource,amount in phase_ammo[ref].get(field,{}).items(): totals[field][resource]=int(totals[field].get(resource,0))+max(0,int(amount))
            phase_snaps={}
            for ref in all_refs:
                opposing_side=defenders if ref in attackers else attackers; opposing=[row for other in opposing_side for row in phase_rows.get(other,[])]
                phase_snaps[ref]=self._formation_combat_snapshot(virtual_formations[ref],combat_forces[ref],terrain_kind=terrain_kind,ammo_plan=phase_ammo[ref],battle_hours=phase_hours,opposing_rows=opposing) if hasattr(self,"_formation_combat_snapshot") else {}
                prior_sectors=phase_sector_state.get(ref,{})
                breached=sum(1 for value in prior_sectors.values() if float(value)<=local_breach_threshold)
                breach_factor=max(1.0-local_breach_penalty_cap,1.0-min(local_breach_penalty_cap,breached*local_breach_penalty))
                phase_snaps[ref]["local_breach_factor"]=breach_factor
                phase_snaps[ref]["local_breach_count"]=breached
                phase_snaps[ref]["local_sector_integrity_before"]={k:round(float(v),3) for k,v in prior_sectors.items()}
                phased_physical[ref].append({"phase":phase_id,"weight":phase_fraction,"snap":phase_snaps[ref]})
            phase_entry={"phase":phase_id,"duration_hours":round(phase_hours,6),"formation_states":{}}
            for ref in all_refs:
                vf=virtual_formations[ref]
                logistics=vf.setdefault("logistics",{})
                phase_ammo_resources=sorted(set(str(k) for k in phase_ammo[ref].get("desired_by_resource",{})) | set(str(k) for k in phase_ammo[ref].get("consumed_by_resource",{})))
                before_state={"shield_units_by_role":dict(self._shield_units(vf)),"armor_units_by_role":dict(self._armor_units(vf)),"shield_condition_by_role":dict(vf.get("shield_condition_by_role",{})),"armor_condition_by_role":dict(vf.get("armor_condition_by_role",{})),"mounts":dict(vf.get("mounts",{})) if isinstance(vf.get("mounts"),Mapping) else {},"cohesion":int(vf.get("cohesion",50)),"ammunition":{resource:max(0,int(logistics.get(resource,0) or 0)) for resource in phase_ammo_resources},"frontline_ammunition":{resource:max(0,int(battle_sustainment[ref].get("frontline_ammunition",{}).get(resource,0) or 0)) for resource in phase_ammo_resources},"hq_ammunition":{resource:max(0,int(battle_sustainment[ref].get("hq_ammunition",{}).get(resource,0) or 0)) for resource in phase_ammo_resources},"support_absence_by_role":dict(phase_support_absence.get(ref,{}))}
                consume_frontline_ammunition(battle_sustainment[ref],phase_ammo[ref])
                for resource,amount in phase_ammo[ref].get("consumed_by_resource",{}).items(): logistics[resource]=max(0,int(logistics.get(resource,0))-max(0,int(amount)))
                enemy_refs=defenders if ref in attackers else attackers; divisor=max(1,len(enemy_refs)); incoming=[phase_snaps.get(enemy,{}).get("ranged_contact",{}) for enemy in enemy_refs]
                incoming_shield_wear=sum(float(x.get("shield_wear_pct",0) or 0) for x in incoming if isinstance(x,Mapping))/divisor
                incoming_armor_wear=sum(float(x.get("armor_wear_pct",0) or 0) for x in incoming if isinstance(x,Mapping))/divisor
                methods=set(str(x) for x in phase_snaps.get(ref,{}).get("formation_method",{}).get("methods",[]) if isinstance(x,str))
                shield_units=self._shield_units(vf); armor_units=self._armor_units(vf); shield_conditions=vf.setdefault("shield_condition_by_role",{}); armor_conditions=vf.setdefault("armor_condition_by_role",{}); general_conditions=vf.setdefault("equipment_condition_by_role",{})
                rows_by_role={str(row.get("role","")):row for row in phase_rows.get(ref,[]) if isinstance(row,Mapping)}
                phase_contact_base=max(0.0,.10*phase_hours*contact_wear_factor)
                for role,count in (vf.get("composition",{}) if isinstance(vf.get("composition"),Mapping) else {}).items():
                    if int(count)<=0: continue
                    row=rows_by_role.get(str(role),{}); general_prior=max(0.0,min(100.0,float(general_conditions.get(role,100.0) or 0))); general_conditions[role]=round(max(0.0,general_prior-phase_contact_base),3)
                    if int(shield_units.get(role,0) or 0)>0:
                        prior=max(0.0,min(100.0,float(shield_conditions.get(role,general_prior) or 0))); wear=incoming_shield_wear+(phase_contact_base*.20 if "shield_wall" in methods else 0.0); out=self._combat_shield_breakage_resolution(int(shield_units.get(role,0)),prior,wear); shield_units[role]=int(out.get("units_after",0)); shield_conditions[role]=float(out.get("condition_after_pct",0)); phase_damage_profile[ref]["shield"].setdefault(str(role),{"units_before":int(before_state["shield_units_by_role"].get(role,0))})
                    if int(armor_units.get(role,0) or 0)>0:
                        prior=max(0.0,min(100.0,float(armor_conditions.get(role,general_prior) or 0))); wear=incoming_armor_wear+phase_contact_base*.18; out=self._combat_armor_breakage_resolution(int(armor_units.get(role,0)),prior,wear); armor_units[role]=int(out.get("units_after",0)); armor_conditions[role]=float(out.get("condition_after_pct",0)); phase_damage_profile[ref]["armor"].setdefault(str(role),{"units_before":int(before_state["armor_units_by_role"].get(role,0))})
                self._set_shield_units(vf,shield_units); self._set_armor_units(vf,armor_units)
                # Mount losses also settle between phases. A cavalry body that
                # loses horses on a braced spear line therefore enters the next
                # phase with fewer actually mounted riders and less charge mass.
                current_mounts=sum(max(0,int(v)) for v in (vf.get("mounts",{}) if isinstance(vf.get("mounts"),Mapping) else {}).values())
                own_method_profile=phase_snaps.get(ref,{}).get("formation_method",{}) if isinstance(phase_snaps.get(ref,{}),Mapping) else {}
                mount_phase=self._combat_phase_mount_attrition(
                    current_mounts,
                    float(own_method_profile.get("mounted_share",0) or 0),
                    float(own_method_profile.get("mount_casualty_risk",1.0) or 1.0),
                    phase_hours,
                    contact_wear_factor,
                ) if hasattr(self,"_combat_phase_mount_attrition") else {"units_before":current_mounts,"units_lost":0,"units_after":current_mounts,"loss_fraction":0.0}
                mount_phase_loss=max(0,min(current_mounts,int(mount_phase.get("units_lost",0) or 0)))
                if mount_phase_loss>0:
                    survivor_mounts,_lost_phase_mounts=self._partition_material(vf.get("mounts",{}),mount_phase_loss,max(1,current_mounts))
                    vf["mounts"]=survivor_mounts
                    phase_mount_losses[ref]+=mount_phase_loss
                # Cohesion erodes between phases from sustained contact, not only
                # at final settlement. This changes later shieldwall/phalanx order.
                pressure=max(0.0,sum(float(phase_snaps.get(enemy,{}).get("formation_method",{}).get("combat_factor",1.0) or 1.0) for enemy in enemy_refs)/divisor-1.0)
                cohesion_loss=max(0,int(round((.55+1.8*pressure)*cohesion_wear_factor*phase_fraction*3.0*contact_duration_factor)))
                vf["cohesion"]=_clamp(int(vf.get("cohesion",50))-cohesion_loss)
                # A three-sector transient front is enough to let a local breach
                # matter inside this battle without materializing anonymous soldiers.
                own_method=max(.35,float(phase_snaps.get(ref,{}).get("formation_method",{}).get("combat_factor",1.0) or 1.0))
                enemy_method=max(.35,sum(float(phase_snaps.get(enemy,{}).get("formation_method",{}).get("combat_factor",1.0) or 1.0) for enemy in enemy_refs)/divisor)
                hero_frontage=sum(max(0.0,float(phase_snaps.get(enemy,{}).get("hero_interventions",{}).get("frontage_displacement_m",0) or 0)) for enemy in enemy_refs)/divisor
                contact_ratio=max(.35,min(3.5,enemy_method/own_method))
                prior_sector_state=dict(phase_sector_state.get(ref,{})); next_sector_state={}
                for sector,integrity in prior_sector_state.items():
                    sector_bias=1.15 if sector=="center" else 1.0
                    loss_pct=(3.0+6.0*contact_ratio+min(8.0,hero_frontage*.04))*phase_fraction*contact_wear_factor*sector_bias*contact_duration_factor
                    # Cohesion preserves a line but cannot make it invulnerable.
                    cohesion_resistance=.72+.28*(max(0.0,min(100.0,float(vf.get("cohesion",50) or 50)))/100.0)
                    next_sector_state[sector]=max(0.0,min(100.0,float(integrity)-loss_pct/cohesion_resistance))
                phase_sector_state[ref]=next_sector_state
                newly_breached=[sector for sector,value in next_sector_state.items() if value<=local_breach_threshold and prior_sector_state.get(sector,100)>local_breach_threshold]
                breached_after=sum(1 for v in next_sector_state.values() if v<=local_breach_threshold)
                support_rotation={"duty":"sustainment_rotation","rotation_personnel":0,"reason":"final_contact_phase"}
                if phase_index+1<len(phase_specs):
                    next_fraction=max(0.0,float(phase_specs[phase_index+1].get("duration_fraction",0) or 0))/phase_fraction_total
                    next_phase_hours=max(.001,float(battle_hours)*next_fraction)
                    support_rotation=plan_hundred_sustainment_rotation(
                        battle_sustainment[ref],
                        vf,
                        [dict(x) for x in self._combat_cohort_snapshot(vf,combat_forces[ref])],
                        command_effects=phase_snaps.get(ref,{}).get("command_effects",{}),
                        current_shields=self._shield_units(vf),
                        current_armor=self._armor_units(vf),
                        current_mounts=sum(max(0,int(v)) for v in (vf.get("mounts",{}) if isinstance(vf.get("mounts"),Mapping) else {}).values()),
                        breached_sectors=breached_after,
                        next_phase_hours=next_phase_hours,
                        rules=sustainment_rules,
                    )
                    shield_repl=support_rotation.get("shield_replacements_by_role",{}) if isinstance(support_rotation.get("shield_replacements_by_role"),Mapping) else {}
                    armor_repl=support_rotation.get("armor_replacements_by_role",{}) if isinstance(support_rotation.get("armor_replacements_by_role"),Mapping) else {}
                    if shield_repl:
                        units=self._shield_units(vf); conditions=vf.setdefault("shield_condition_by_role",{})
                        for role,amount in shield_repl.items():
                            add=max(0,int(amount or 0)); old=max(0,int(units.get(role,0) or 0)); cap=max(old,int(battle_sustainment[ref].get("initial_shields_by_role",{}).get(role,old) or old)); add=min(add,max(0,cap-old))
                            if add>0:
                                prior=float(conditions.get(role,100.0) or 0); units[role]=old+add; conditions[role]=round((old*prior+add*100.0)/max(1,old+add),3)
                        self._set_shield_units(vf,units)
                    if armor_repl:
                        units=self._armor_units(vf); conditions=vf.setdefault("armor_condition_by_role",{})
                        for role,amount in armor_repl.items():
                            add=max(0,int(amount or 0)); old=max(0,int(units.get(role,0) or 0)); cap=max(old,int(battle_sustainment[ref].get("initial_armor_by_role",{}).get(role,old) or old)); add=min(add,max(0,cap-old))
                            if add>0:
                                prior=float(conditions.get(role,100.0) or 0); units[role]=old+add; conditions[role]=round((old*prior+add*100.0)/max(1,old+add),3)
                        self._set_armor_units(vf,units)
                    remounts=max(0,int(support_rotation.get("remount_horses_issued",0) or 0))
                    if remounts>0:
                        mounts=vf.setdefault("mounts",{}); mounts["horse"]=max(0,int(mounts.get("horse",0) or 0))+remounts
                after_state={"shield_units_by_role":dict(self._shield_units(vf)),"armor_units_by_role":dict(self._armor_units(vf)),"shield_condition_by_role":dict(vf.get("shield_condition_by_role",{})),"armor_condition_by_role":dict(vf.get("armor_condition_by_role",{})),"mounts":dict(vf.get("mounts",{})) if isinstance(vf.get("mounts"),Mapping) else {},"cohesion":int(vf.get("cohesion",50)),"ammunition":{resource:max(0,int(logistics.get(resource,0) or 0)) for resource in phase_ammo_resources},"frontline_ammunition":{resource:max(0,int(battle_sustainment[ref].get("frontline_ammunition",{}).get(resource,0) or 0)) for resource in phase_ammo_resources},"hq_ammunition":{resource:max(0,int(battle_sustainment[ref].get("hq_ammunition",{}).get(resource,0) or 0)) for resource in phase_ammo_resources}}
                phase_entry["formation_states"][ref]={"before":before_state,"after":after_state,"ammunition_consumed":dict(phase_ammo[ref].get("consumed_by_resource",{})),"sustainment_rotation":support_rotation,"incoming_shield_wear_pct":round(incoming_shield_wear,4),"incoming_armor_wear_pct":round(incoming_armor_wear,4),"mounts_lost_in_phase":mount_phase_loss,"mount_loss_fraction":round(float(mount_phase.get("loss_fraction",0) or 0),8),"mount_casualty_risk":round(float(mount_phase.get("mount_casualty_risk",own_method_profile.get("mount_casualty_risk",1.0)) or 1.0),6),"formation_methods":sorted(methods),"local_sector_integrity_before":{k:round(float(v),3) for k,v in prior_sector_state.items()},"local_sector_integrity_after":{k:round(float(v),3) for k,v in next_sector_state.items()},"local_breach_threshold_pct":round(local_breach_threshold,3),"newly_breached_sectors":newly_breached,"breached_sector_count_after":breached_after}
            battle_phase_trace.append(phase_entry)
        # Replace the old one-shot ammunition budget with sequential phase use.
        # This guarantees later phases see the stock that physically remains.
        for ref in all_refs:
            desired=sum(int(v) for v in phase_ammo_totals[ref]["desired_by_resource"].values()); consumed=sum(int(v) for v in phase_ammo_totals[ref]["consumed_by_resource"].values()); phase_ammo_totals[ref]["overall_sufficiency"]=(consumed/desired if desired>0 else 1.0); ammo_plans[ref]=phase_ammo_totals[ref]
            initial_shields=self._shield_units(formations[ref][1]); final_shields=self._shield_units(virtual_formations[ref]); initial_armor=self._armor_units(formations[ref][1]); final_armor=self._armor_units(virtual_formations[ref])
            for role,units in initial_shields.items():
                phase_damage_profile[ref]["shield"].setdefault(role,{})["units_before"]=int(units); phase_damage_profile[ref]["shield"][role]["units_after"]=int(final_shields.get(role,0)); phase_damage_profile[ref]["shield"][role]["survival_fraction"]=round(int(final_shields.get(role,0))/max(1,int(units)),8); phase_damage_profile[ref]["shield"][role]["condition_after_pct"]=float(virtual_formations[ref].get("shield_condition_by_role",{}).get(role,0 if int(final_shields.get(role,0))<=0 else 100))
            for role,units in initial_armor.items():
                phase_damage_profile[ref]["armor"].setdefault(role,{})["units_before"]=int(units); phase_damage_profile[ref]["armor"][role]["units_after"]=int(final_armor.get(role,0)); phase_damage_profile[ref]["armor"][role]["survival_fraction"]=round(int(final_armor.get(role,0))/max(1,int(units)),8); phase_damage_profile[ref]["armor"][role]["condition_after_pct"]=float(virtual_formations[ref].get("armor_condition_by_role",{}).get(role,0 if int(final_armor.get(role,0))<=0 else 100))

        score_details={}; casualty_modifiers={}
        def side_score(refs:list[str],opposing_refs:list[str]) -> float:
            score=0.0; opposing_rows=[row for other in opposing_refs for row in combat_rows.get(other,[])]
            for ref in refs:
                formation=formations[ref][1]; n=int(formation["personnel"]); readiness=int(formation.get("readiness",50)); morale=int(formation.get("morale",50)); cohesion=int(formation.get("cohesion",50)); fatigue=int(formation.get("fatigue",0)); training=int(formation.get("training_progress",20)); equipment=_pct(formation.get("equipment_completeness","0")); logistics=formation.get("logistics",{})
                supply_state=military_supply_sufficiency(self,formation)
                ammo_ratio=float(ammo_plans.get(ref,{}).get("overall_sufficiency",1.0)); supply=max(.20,min(1.0,float(supply_state.get("combat_factor", .72+.28*float(supply_state["overall_ratio"])) ))); role_factor=terrain_role_factor(formation); doctrine_power,casualty_modifier=doctrine_factor(formation); casualty_modifiers[ref]=casualty_modifier
                organization=max(.18,min(1.15,(readiness+morale+cohesion+max(0,100-fatigue))/400)); integration=max(.72,min(1.12,.72+training/250))
                if hasattr(self,"_formation_combat_snapshot") and ref in combat_forces:
                    snap=self._formation_combat_snapshot(formation,combat_forces[ref],terrain_kind=terrain_kind,ammo_plan=ammo_plans[ref],battle_hours=float(battle_hours),opposing_rows=opposing_rows)
                    phase_items=phased_physical.get(ref,[])
                    def phase_average(key:str,default:float)->float:
                        if not phase_items:return float(snap.get(key,default))
                        return sum(float(item.get("weight",0) or 0)*float(item.get("snap",{}).get(key,default) or default) for item in phase_items)/max(1e-9,sum(float(item.get("weight",0) or 0) for item in phase_items))
                    capability=phase_average("capability_factor",1.0); weapon_factor=phase_average("melee_weapon_factor",1.0); reach=phase_average("reach_factor",1.0); ranged=phase_average("ranged_factor",1.0); protection=phase_average("protection_factor",1.0); mount_factor=phase_average("mount_factor",1.0); effective=phase_average("frontage_equivalent",float(formation.get("personnel",0) or 0)); method_factor=phase_average("formation_method_factor",1.0); local_breach_factor=phase_average("local_breach_factor",1.0)
                    command_factor=float(snap["command_factor"]); named_equiv=0.0; hero_factor=float(snap.get("hero_disruption_factor",1.0)); hero_profile=dict(snap.get("hero_interventions",{})); combat_named[ref]=list(snap.get("named_participants",[]))
                    if phase_items:
                        last_phase=phase_items[-1].get("snap",{}); method_profile=dict(last_phase.get("formation_method",{}))
                        ranged_rows=[item.get("snap",{}).get("ranged_contact",{}) for item in phase_items if isinstance(item.get("snap",{}).get("ranged_contact",{}),Mapping)]
                        total_phase_shots=sum(max(0,int(row.get("projectiles_fired",0) or 0)) for row in ranged_rows)
                        if total_phase_shots>0:
                            def shot_weighted(field:str,default:float=0.0)->float:
                                return sum(max(0,int(row.get("projectiles_fired",0) or 0))*float(row.get(field,default) or default) for row in ranged_rows)/max(1,total_phase_shots)
                            ranged_contact_profile={
                                "projectiles_fired":total_phase_shots,
                                "weighted_impact_index":round(shot_weighted("weighted_impact_index"),3),
                                "weighted_penetration_index":round(shot_weighted("weighted_penetration_index"),3),
                                "average_flight_time_seconds":round(shot_weighted("average_flight_time_seconds"),4),
                                "shield_intercept_fraction":round(shot_weighted("shield_intercept_fraction"),5),
                                "average_shield_interception_angle_deg":round(shot_weighted("average_shield_interception_angle_deg"),3),
                                "shield_effective_path_factor":round(shot_weighted("shield_effective_path_factor",1.0),5),
                                "shield_wear_pct":round(sum(float(row.get("shield_wear_pct",0) or 0) for row in ranged_rows),3),
                                "armor_penetration_ratio":round(shot_weighted("armor_penetration_ratio"),5),
                                "armor_wear_pct":round(sum(float(row.get("armor_wear_pct",0) or 0) for row in ranged_rows),3),
                                "combat_factor":round(sum(float(item.get("weight",0) or 0)*float(item.get("snap",{}).get("ranged_contact",{}).get("combat_factor",1.0) or 1.0) for item in phase_items),6),
                                "projectile_recovery_base":round(shot_weighted("projectile_recovery_base"),5),
                                "contact_distribution":next((dict(row.get("contact_distribution",{})) for row in ranged_rows if isinstance(row.get("contact_distribution"),Mapping) and row.get("contact_distribution")),{}),
                                "phase_profiles":[dict(row) for row in ranged_rows],
                            }
                        else:
                            ranged_contact_profile=dict(last_phase.get("ranged_contact",{}))
                        method_profile["phase_weighted_combat_factor"]=round(method_factor,6); method_profile["contact_phases"]=[{"phase":str(item.get("phase","")),"weight":round(float(item.get("weight",0) or 0),6),"combat_factor":round(float(item.get("snap",{}).get("formation_method_factor",1) or 1),6),"shield_share":item.get("snap",{}).get("formation_method",{}).get("shield_share"),"shieldwall_integrity":item.get("snap",{}).get("formation_method",{}).get("shieldwall_integrity"),"phalanx_integrity":item.get("snap",{}).get("formation_method",{}).get("phalanx_integrity")} for item in phase_items]
                    else:
                        method_profile=dict(snap.get("formation_method",{})); ranged_contact_profile=dict(snap.get("ranged_contact",{}))
                else:
                    base=max(.10,(readiness+morale+cohesion+training+max(0,100-fatigue))/500); capability=base; weapon_factor=reach=ranged=protection=mount_factor=1.0; command_factor=1+min(commander_scores[ref],500)/2500; effective=float(n); named_equiv=0; method_factor=hero_factor=local_breach_factor=1.0; method_profile={}; hero_profile={"interventions":[],"casualty_pressure":0,"disruption_factor":1.0}
                duty_factor=self._unit_duty_battle_factor(formation)
                quality=capability*weapon_factor*reach*ranged*protection*mount_factor*method_factor*local_breach_factor*hero_factor*organization*integration*max(.20,equipment)*supply*command_factor*role_factor*doctrine_power*duty_factor
                score_details[ref]={"scale":10000,"unit_duty_factor":int(round(duty_factor*10000)),"unit_duty":_deepcopy(formation.get("current_unit_duty")),"effective_bodies_milli":int(round(effective*1000)),"capability":int(round(capability*10000)),"weapon":int(round(weapon_factor*10000)),"reach":int(round(reach*10000)),"ranged":int(round(ranged*10000)),"protection":int(round(protection*10000)),"mount":int(round(mount_factor*10000)),"formation_method_factor":int(round(method_factor*10000)),"local_breach_factor":int(round(local_breach_factor*10000)),"hero_disruption_factor":int(round(hero_factor*10000)),"formation_method":method_profile,"ranged_contact":ranged_contact_profile,"hero_interventions":hero_profile.get("interventions",[]),"hero_casualty_pressure":int(hero_profile.get("casualty_pressure",0) or 0),"hero_officer_pressure_milli":int(round(float(hero_profile.get("officer_pressure",0) or 0)*1000)),"hero_cohesion_shock_milli":int(round(float(hero_profile.get("cohesion_shock_pressure",0) or 0)*1000)),"hero_artillery_pressure_milli":int(round(float(hero_profile.get("artillery_pressure",0) or 0)*1000)),"hero_command_attention_seconds_milli":int(round(float(hero_profile.get("command_attention_seconds",0) or 0)*1000)),"mount_casualty_risk_milli":int(round(float(method_profile.get("mount_casualty_risk",1.0))*1000)),"organization":int(round(organization*10000)),"integration":int(round(integration*10000)),"equipment":int(round(equipment*10000)),"supply":int(round(supply*10000)),"ammo_sufficiency":int(round(ammo_ratio*10000)),"command":int(round(command_factor*10000)),"terrain_role":int(round(role_factor*10000)),"doctrine":int(round(doctrine_power*10000)),"quality":int(round(quality*10000)),"contact_phase_count":len(phased_physical.get(ref,[]))}
                score+=effective*quality
            return max(1.0,score)

        a_score=side_score(attackers,defenders); d_score=side_score(defenders,attackers)
        attacker_hero_pressure=sum(max(0,int(score_details.get(ref,{}).get("hero_casualty_pressure",0))) for ref in attackers)
        defender_hero_pressure=sum(max(0,int(score_details.get(ref,{}).get("hero_casualty_pressure",0))) for ref in defenders)
        attacker_hero_officer_pressure=sum(max(0,int(score_details.get(ref,{}).get("hero_officer_pressure_milli",0)))/1000.0 for ref in attackers)
        defender_hero_officer_pressure=sum(max(0,int(score_details.get(ref,{}).get("hero_officer_pressure_milli",0)))/1000.0 for ref in defenders)
        attacker_hero_cohesion_shock=sum(max(0,int(score_details.get(ref,{}).get("hero_cohesion_shock_milli",0)))/1000.0 for ref in attackers)
        defender_hero_cohesion_shock=sum(max(0,int(score_details.get(ref,{}).get("hero_cohesion_shock_milli",0)))/1000.0 for ref in defenders)
        attacker_hero_artillery_pressure=sum(max(0,int(score_details.get(ref,{}).get("hero_artillery_pressure_milli",0)))/1000.0 for ref in attackers)
        defender_hero_artillery_pressure=sum(max(0,int(score_details.get(ref,{}).get("hero_artillery_pressure_milli",0)))/1000.0 for ref in defenders)
        hero_intervention_by_person={}
        for formation_ref in attackers+defenders:
            detail=score_details.get(formation_ref,{}) if isinstance(score_details.get(formation_ref),Mapping) else {}
            for row in detail.get("hero_interventions",[]) if isinstance(detail.get("hero_interventions"),list) else []:
                if not isinstance(row,Mapping): continue
                person_ref=str(row.get("person_ref",""))
                if not person_ref: continue
                prior=hero_intervention_by_person.get(person_ref)
                if not isinstance(prior,Mapping) or float(row.get("incoming_injury_risk",0) or 0)>float(prior.get("incoming_injury_risk",0) or 0):
                    hero_intervention_by_person[person_ref]=dict(row)
        attacker_personnel_before=max(1,sum(int(formations[ref][1].get("personnel",0)) for ref in attackers))
        defender_personnel_before=max(1,sum(int(formations[ref][1].get("personnel",0)) for ref in defenders))
        fortress_support_factor=1.0
        if isinstance(context,Mapping) and str(context.get("kind",""))=="siege_assault":
            fortress_support_factor=max(1.0,min(1.35,int(context.get("fortress_defender_power_factor_milli",1000))/1000.0)); d_score*=fortress_support_factor
        seed=_battle_seed("mass-battle"); variance=((seed%2001)-1000)/100000; attack_pressure=d_score/max(1,a_score); defense_pressure=a_score/max(1,d_score); a_rate=max(.01,min(.45,.035*attack_pressure+variance)); d_rate=max(.01,min(.45,.045*defense_pressure-variance))
        if attack_pressure>=5:a_rate=min(1,.60+min(.40,(attack_pressure-5)*.10))
        if defense_pressure>=5:d_rate=min(1,.60+min(.40,(defense_pressure-5)*.10))
        if terrain_has(terrain_kind,"pass","fortified"): d_rate*=.86
        # Casualty rates were historically calibrated to a whole-battle contact
        # window.  Operational battles now resolve one bounded contact period at
        # a time, so short periods cannot repeatedly apply a full-day casualty
        # envelope before reinforcements, dusk, or other chronology boundaries.
        a_rate*=contact_duration_factor; d_rate*=contact_duration_factor
        if internal_operational_contact:
            started_text=str((context or {}).get("started_at") or contact_plan.get("started_at") or "")
            completed_text=str((context or {}).get("completed_at") or contact_plan.get("planned_end_at") or "")
            if not started_text or not completed_text:
                raise ValueError("autonomous operational contact requires exact start/end chronology")
            battle_started=CampaignTime.parse(started_text); battle_completed=CampaignTime.parse(completed_text)
            runtime_frontier = CampaignTime.parse(str(self.read("state/runtime.json")["world_time"]))
            if battle_completed <= battle_started or battle_completed < runtime_frontier:
                raise ValueError("autonomous operational contact cannot settle before the current causal frontier")
            battle_duration_seconds=max(1, battle_started.seconds_until(battle_completed))
            battle_hours=battle_duration_seconds/3600.0
        else:
            battle_started=self._world_time(); battle_completed=battle_started.add_seconds(battle_duration_seconds)
        attacker_won=a_score>=d_score; event_id="battle_"+command.semantic_digest[:16]; killed={}; material_losses={}; named_person_outcomes={}; all_named_refs=[]
        named_fatigue_settled:set[str]=set(); named_fatigue_rules=self.read(FATIGUE_RULES_PATH)

        def remove_active_role(formation:Dict[str,Any],person_ref:str,role:str) -> None:
            if role=="commander" and formation.get("commander_ref")==person_ref: formation["commander_ref"]=None; self._release_commander_index(person_ref,str(formation.get("formation_ref")))
            for field in ("embedded_person_refs","notable_person_refs","staff_refs","specialist_refs"):
                raw=formation.get(field)
                if isinstance(raw,list) and person_ref in raw: formation[field]=[x for x in raw if x!=person_ref]

        def award_person_experience(person:Dict[str,Any],role:str,exposure:float) -> None:
            schema=str(person.get("schema")); attrs,skills=(person.get("attributes",{}),person.get("skills",{})) if schema!="person-lite" else (person.get("stats",{}).get("attributes",{}),person.get("stats",{}).get("skills",{}))
            if not isinstance(skills,dict) or not skills:return
            registry=self.read(TRAINING_PROGRAM_REGISTRY_PATH)
            branch_role=str(person.get("role", "") or next(iter(formation.get("composition",{})), role))
            program_ref=resolve_training_program_ref(registry,role=branch_role,training_ref=formation_training_ref_for_role(formation, branch_role),person=person)
            weights={name:weight for name,weight in combat_skill_weights_for_participant(registry,program_ref,role).items() if name in skills}
            if not weights:return
            training=self.read("game/data/mechanics/training.json"); temp=person
            if schema=="person-lite": temp={"skills":dict(skills),"attributes":dict(attrs) if isinstance(attrs,dict) else {},"aptitude":dict(person.get("aptitude",{})),"birth_date":person.get("birth_date","270-BCE-01-01"),"health_status":self._person_health(person),"development_state":_deepcopy(person.get("development_state",{}))}
            try: developments=settle_combat_experience(temp,weights,battle_hours*max(.15,exposure),battle_completed,training)
            except (ValueError,TypeError): developments=[]
            if schema=="person-lite": person.setdefault("stats",{})["skills"]=temp.get("skills",{}); person["development_state"]=temp.get("development_state",{})


        def settle_named_projectile_ammunition(person_ref:str,person:Dict[str,Any],participant:Mapping[str,Any],hero_row:Mapping[str,Any],*,won_field:bool,outcome:str)->dict[str,Any]:
            released=max(0,int(hero_row.get("projectiles_released",0) or 0))
            ammo_item=str(hero_row.get("projectile_item_id") or participant.get("ammunition_item") or "")
            if released<=0 or not ammo_item:
                return {}
            state=person.setdefault("combat_state",{})
            projectile_state=state.setdefault("projectile_ammunition",{})
            fallback=max(0,int(participant.get("carried_ammunition",participant.get("default_carried_ammunition",0)) or 0))
            before=max(0,int(projectile_state.get(ammo_item,fallback) or 0))
            fired=min(before,released)
            recovery_base=max(0.0,min(.95,float(hero_row.get("projectile_recovery_base",0) or 0)))
            terrain_recovery=0.78 if terrain_has(terrain_kind,"plain") else (0.58 if terrain_has(terrain_kind,"woodland","mountain","marsh") else 0.68)
            control_recovery=0.82 if won_field else 0.28
            can_recover=outcome not in {"killed","captured"}
            recovered=min(fired,max(0,int(round(fired*recovery_base*terrain_recovery*control_recovery)))) if can_recover else 0
            after=max(0,before-fired+recovered)
            projectile_state[ammo_item]=after
            manifest_path="state/player-detail/equipment-manifest.json" if person_ref==self.PLAYER_ACTOR else person.get("equipment_manifest_ref")
            if isinstance(manifest_path,str) and manifest_path:
                manifest0=self.read_optional(manifest_path)
                if isinstance(manifest0,Mapping):
                    manifest=_deepcopy(manifest0); changed=False
                    for entry in manifest.get("equipment_manifest",[]):
                        if isinstance(entry,dict) and str(entry.get("item_id",""))==ammo_item:
                            entry["quantity"]=after; changed=True
                    if changed:self.put(manifest_path,manifest)
            return {"projectile_item_id":ammo_item,"before":before,"fired":fired,"recovered":recovered,"after":after,"projectile_recovery_base":round(recovery_base,5)}

        for refs,rate in ((attackers,a_rate),(defenders,d_rate)):
            for ref in refs:
                path,formation=formations[ref]; before=int(formation["personnel"]); before_comp={str(role):max(0,int(count)) for role,count in formation.get("composition",{}).items()}; adjusted_rate=rate*casualty_modifiers.get(ref,1); loss=min(before,max(0,int(round(before*adjusted_rate)))); survivor_comp,dead_comp=self._partition_counts(before_comp,loss,before)
                if loss > 0:
                    freeze_establishment_composition(formation)
                source_total=defender_personnel_before if ref in attackers else attacker_personnel_before
                source_officer_pressure=defender_hero_officer_pressure if ref in attackers else attacker_hero_officer_pressure
                source_cohesion_shock=defender_hero_cohesion_shock if ref in attackers else attacker_hero_cohesion_shock
                source_artillery_pressure=defender_hero_artillery_pressure if ref in attackers else attacker_hero_artillery_pressure
                hero_officer_pressure_alloc=source_officer_pressure*before/max(1,source_total)
                hero_cohesion_shock_alloc=source_cohesion_shock*before/max(1,source_total)
                hero_artillery_pressure_alloc=source_artillery_pressure*before/max(1,source_total)
                # Reclassify some already-settled casualties onto artillery/engineer
                # crews when a named intervention physically reaches that local
                # frontage. Total deaths and formation personnel remain conserved.
                artillery_roles=[role for role,count in before_comp.items() if count>0 and any(tok in role.lower() for tok in ("siege","engineer","artillery","engine"))]
                artillery_shift=min(max(0,int(round(hero_artillery_pressure_alloc*.35))),sum(max(0,before_comp.get(role,0)-dead_comp.get(role,0)) for role in artillery_roles))
                artillery_shift_applied=0
                if artillery_shift>0 and artillery_roles:
                    donors=[role for role,count in dead_comp.items() if count>0 and role not in artillery_roles]
                    for _ in range(artillery_shift):
                        target=next((role for role in artillery_roles if survivor_comp.get(role,0)>0),None); donor=next((role for role in donors if dead_comp.get(role,0)>0),None)
                        if target is None or donor is None: break
                        dead_comp[donor]-=1; survivor_comp[donor]=survivor_comp.get(donor,0)+1; dead_comp[target]=dead_comp.get(target,0)+1; survivor_comp[target]=max(0,survivor_comp.get(target,0)-1); artillery_shift_applied+=1
                survivor_eq,lost_eq=self._partition_material(self._equipment_units(formation),loss,before)
                sustainment_state=battle_sustainment.get(ref,{}) if isinstance(battle_sustainment.get(ref),Mapping) else {}
                remounts_issued=max(0,int(sustainment_state.get("remount_horses_issued",0) or 0))
                combined_mounts={str(k):max(0,int(v)) for k,v in (formation.get("mounts",{}) if isinstance(formation.get("mounts"),Mapping) else {}).items()}
                if remounts_issued>0: combined_mounts["horse"]=max(0,int(combined_mounts.get("horse",0)))+remounts_issued
                total_mounts=sum(max(0,int(v)) for v in combined_mounts.values()); mount_risk=max(.25,int(score_details.get(ref,{}).get("mount_casualty_risk_milli",1000))/1000.0); casualty_mount_loss=min(total_mounts,max(0,int(round(total_mounts*(loss/max(1,before))*mount_risk)))); phase_mount_loss=min(total_mounts,max(0,int(phase_mount_losses.get(ref,0) or 0))); mount_loss=max(casualty_mount_loss,phase_mount_loss); survivor_mounts,lost_mounts=self._partition_material(combined_mounts,mount_loss,max(1,total_mounts)) if total_mounts else ({}, {})
                formation["personnel"]=before-loss; formation["composition"]=survivor_comp; formation["mounts"]=survivor_mounts; self._set_equipment_units(formation,survivor_eq)
                condition_state=formation.setdefault("equipment_condition_by_role",{}); condition_losses={}
                shield_condition_state=formation.setdefault("shield_condition_by_role",{}); armor_condition_state=formation.setdefault("armor_condition_by_role",{})
                shield_units_state=self._shield_units(formation); self._set_shield_units(formation,shield_units_state)
                armor_units_state=self._armor_units(formation); self._set_armor_units(formation,armor_units_state)
                row_by_role={str(row.get("role")):row for row in combat_rows.get(ref,[]) if isinstance(row,Mapping)}
                rows_by_role={}
                for combat_row in combat_rows.get(ref,[]):
                    if not isinstance(combat_row,Mapping): continue
                    rows_by_role.setdefault(str(combat_row.get("role","")),[]).append(combat_row)
                # Shield quantity and shield condition are distinct authorities.
                # Existing formations lazily materialize their initial serviceable
                # shield count from the pre-battle combat snapshot. Casualties then
                # remove a proportional share of those physical shields before
                # contact breakage is applied below.
                shield_units_before={}
                shield_units_after_casualties={}
                shield_units_lost_with_casualties={}
                for role,role_rows in rows_by_role.items():
                    if not any(_fixed(r.get("shield_structure",0))>0 or _fixed(r.get("shield_units",0))>0 for r in role_rows):
                        continue
                    default_units=max(0,int(round(sum(max(0.0,float(r.get("shield_units",r.get("count",0)) or 0)) for r in role_rows))))
                    role_before=max(0,int(before_comp.get(role,0)))
                    role_dead=max(0,int(dead_comp.get(role,0)))
                    prior_units=max(0,min(role_before,int(shield_units_state.get(role,default_units) or 0)))
                    casualty_loss=min(prior_units,max(0,int(round(prior_units*role_dead/max(1,role_before))))) if role_before else 0
                    surviving_units=max(0,min(int(survivor_comp.get(role,0)),prior_units-casualty_loss))
                    shield_units_before[role]=prior_units
                    shield_units_after_casualties[role]=surviving_units
                    shield_units_lost_with_casualties[role]=prior_units-surviving_units
                    shield_units_state[role]=surviving_units
                # Armor quantity is likewise separate from mean armor condition.
                # ``armor_units_by_role`` counts serviceable protective sets (the
                # role's required body armor / helmet combination), so a 1,000-man
                # role with 500 surviving sets receives armor protection for only
                # those 500 bodies rather than a fictitious formation-wide average.
                armor_units_before={}
                armor_units_after_casualties={}
                armor_units_lost_with_casualties={}
                for role,role_rows in rows_by_role.items():
                    if not any(_fixed(r.get("armor_units",0))>0 or _fixed(r.get("armor_protection_index",0))>0 for r in role_rows):
                        continue
                    default_units=max(0,int(round(sum(max(0.0,float(r.get("armor_units",r.get("count",0)) or 0)) for r in role_rows))))
                    role_before=max(0,int(before_comp.get(role,0)))
                    role_dead=max(0,int(dead_comp.get(role,0)))
                    prior_units=max(0,min(role_before,int(armor_units_state.get(role,default_units) or 0)))
                    casualty_loss=min(prior_units,max(0,int(round(prior_units*role_dead/max(1,role_before))))) if role_before else 0
                    surviving_units=max(0,min(int(survivor_comp.get(role,0)),prior_units-casualty_loss))
                    armor_units_before[role]=prior_units
                    armor_units_after_casualties[role]=surviving_units
                    armor_units_lost_with_casualties[role]=prior_units-surviving_units
                    armor_units_state[role]=surviving_units
                casualty_fraction_for_wear=loss/max(1,before)
                enemy_refs=attackers if ref in defenders else defenders
                target_side_count=max(1,len(defenders if ref in defenders else attackers))
                incoming_ranged=[score_details.get(enemy,{ }).get("ranged_contact",{}) for enemy in enemy_refs]
                if battle_phase_trace:
                    incoming_shield_wear=sum(float(phase.get("formation_states",{}).get(ref,{}).get("incoming_shield_wear_pct",0) or 0) for phase in battle_phase_trace)
                    incoming_armor_wear=sum(float(phase.get("formation_states",{}).get(ref,{}).get("incoming_armor_wear_pct",0) or 0) for phase in battle_phase_trace)
                else:
                    incoming_shield_wear=sum(float(x.get("shield_wear_pct",0) or 0) for x in incoming_ranged if isinstance(x,Mapping))/target_side_count
                    incoming_armor_wear=sum(float(x.get("armor_wear_pct",0) or 0) for x in incoming_ranged if isinstance(x,Mapping))/target_side_count
                method_info=score_details.get(ref,{}).get("formation_method",{}) if isinstance(score_details.get(ref,{}).get("formation_method"),Mapping) else {}
                methods=set(str(x) for x in method_info.get("methods",[]) if isinstance(x,str))
                for role,count in survivor_comp.items():
                    if int(count)<=0: continue
                    row=row_by_role.get(str(role),{}); prior=max(0.0,min(100.0,float(condition_state.get(role,100.0)))); contact_wear=.10*float(battle_hours)+6.0*casualty_fraction_for_wear
                    if _fixed(row.get("shield_structure",0))>0 and "shield_wall" in methods: contact_wear*=1.35
                    if row.get("mounted") and "mounted_charge" in methods: contact_wear*=1.45
                    after=max(0.0,prior-contact_wear); condition_state[role]=round(after,3)
                    shield_prior=max(0.0,min(100.0,float(shield_condition_state.get(role,prior))))
                    armor_prior=max(0.0,min(100.0,float(armor_condition_state.get(role,prior))))
                    has_shield=bool(row.get("shield_id")) and int(shield_units_state.get(role,0) or 0)>0
                    shield_wear_delta=(incoming_shield_wear if has_shield else 0.0)+(contact_wear*.20 if has_shield and "shield_wall" in methods else 0.0)
                    shield_after=max(0.0,shield_prior-shield_wear_delta)
                    armor_wear_delta=(incoming_armor_wear if int(armor_units_state.get(role,0) or 0)>0 else 0.0)+(contact_wear*.18 if int(armor_units_state.get(role,0) or 0)>0 else 0.0)
                    armor_after=max(0.0,armor_prior-armor_wear_delta)
                    destroyed_shields=0
                    if has_shield:
                        serviceable=max(0,int(shield_units_state.get(role,0) or 0)); phased_shield=phase_damage_profile.get(ref,{}).get("shield",{}).get(str(role),{}) if isinstance(phase_damage_profile.get(ref,{}),Mapping) else {}
                        if isinstance(phased_shield,Mapping) and "survival_fraction" in phased_shield:
                            survival=max(0.0,min(1.0,float(phased_shield.get("survival_fraction",1.0) or 0))); remaining=max(0,min(serviceable,int(round(serviceable*survival)))); destroyed_shields=serviceable-remaining; shield_units_state[role]=remaining; shield_after=max(0.0,min(100.0,float(phased_shield.get("condition_after_pct",shield_after) or 0))) if remaining>0 else 0.0
                        elif hasattr(self,"_combat_shield_breakage_resolution"):
                            shield_breakage=self._combat_shield_breakage_resolution(serviceable,shield_prior,shield_wear_delta)
                            destroyed_shields=max(0,int(shield_breakage.get("units_destroyed",0) or 0)); shield_units_state[role]=max(0,int(shield_breakage.get("units_after",0) or 0)); shield_after=max(0.0,min(100.0,float(shield_breakage.get("condition_after_pct",shield_after) or 0)))
                        else:
                            shield_units_state[role]=serviceable
                    destroyed_armor=0
                    if int(armor_units_state.get(role,0) or 0)>0:
                        serviceable_armor=max(0,int(armor_units_state.get(role,0) or 0)); phased_armor=phase_damage_profile.get(ref,{}).get("armor",{}).get(str(role),{}) if isinstance(phase_damage_profile.get(ref,{}),Mapping) else {}
                        if isinstance(phased_armor,Mapping) and "survival_fraction" in phased_armor:
                            survival=max(0.0,min(1.0,float(phased_armor.get("survival_fraction",1.0) or 0))); remaining=max(0,min(serviceable_armor,int(round(serviceable_armor*survival)))); destroyed_armor=serviceable_armor-remaining; armor_units_state[role]=remaining; armor_after=max(0.0,min(100.0,float(phased_armor.get("condition_after_pct",armor_after) or 0))) if remaining>0 else 0.0
                        elif hasattr(self,"_combat_armor_breakage_resolution"):
                            armor_breakage=self._combat_armor_breakage_resolution(serviceable_armor,armor_prior,armor_wear_delta)
                            destroyed_armor=max(0,int(armor_breakage.get("units_destroyed",0) or 0)); armor_units_state[role]=max(0,int(armor_breakage.get("units_after",0) or 0)); armor_after=max(0.0,min(100.0,float(armor_breakage.get("condition_after_pct",armor_after) or 0)))
                        else:
                            armor_units_state[role]=serviceable_armor
                    shield_condition_state[role]=round(shield_after,3); armor_condition_state[role]=round(armor_after,3)
                    condition_losses[role]={"before_condition_pct":round(prior,3),"after_condition_pct":round(after,3),"condition_loss_pct":round(prior-after,3),"shield_before_condition_pct":round(shield_prior,3),"shield_after_condition_pct":round(shield_after,3),"shield_condition_loss_pct":round(shield_prior-shield_after,3),"shield_units_before":int(shield_units_before.get(role,0)),"shield_units_lost_with_casualties":int(shield_units_lost_with_casualties.get(role,0)),"shield_units_destroyed":int(destroyed_shields),"shield_units_after":int(shield_units_state.get(role,0)),"armor_before_condition_pct":round(armor_prior,3),"armor_after_condition_pct":round(armor_after,3),"armor_condition_loss_pct":round(armor_prior-armor_after,3),"armor_units_before":int(armor_units_before.get(role,0)),"armor_units_lost_with_casualties":int(armor_units_lost_with_casualties.get(role,0)),"armor_units_destroyed":int(destroyed_armor),"armor_units_after":int(armor_units_state.get(role,0))}
                self._set_shield_units(formation,shield_units_state); self._set_armor_units(formation,armor_units_state)
                consumed={}
                recovered_ammunition={}
                own_ranged_profile=score_details.get(ref,{}).get("ranged_contact",{}) if isinstance(score_details.get(ref,{}).get("ranged_contact"),Mapping) else {}
                won_side=(ref in attackers and attacker_won) or (ref in defenders and not attacker_won)
                terrain_recovery=0.78 if terrain_has(terrain_kind,"plain") else (0.58 if terrain_has(terrain_kind,"woodland","mountain","marsh") else 0.68)
                control_recovery=0.82 if won_side else 0.28
                base_recovery=max(0.0,min(.95,float(own_ranged_profile.get("projectile_recovery_base",0) or 0)))
                for resource,amount in ammo_plans.get(ref,{}).get("consumed_by_resource",{}).items():
                    use=min(max(0,int(amount)),max(0,int(formation["logistics"].get(resource,0)))); formation["logistics"][resource]=max(0,int(formation["logistics"].get(resource,0))-use); consumed[resource]=use
                    recovered=min(use,max(0,int(round(use*base_recovery*terrain_recovery*control_recovery))))
                    if recovered:
                        formation["logistics"][resource]=max(0,int(formation["logistics"].get(resource,0)))+recovered; recovered_ammunition[resource]=recovered
                spare_consumed=sustainment_state.get("spare_outfitting_consumed",{}) if isinstance(sustainment_state.get("spare_outfitting_consumed"),Mapping) else {}
                formation_spares=formation.setdefault("spare_outfitting_sets",{})
                for spare_key,amount in spare_consumed.items():
                    used=max(0,int(amount or 0)); available=max(0,int(formation_spares.get(spare_key,0) or 0))
                    if used>available: raise ValueError(f"battle sustainment spare outfitting overdraw: {spare_key} used {used}, held {available}")
                    formation_spares[spare_key]=available-used
                if remounts_issued>0:
                    logistics=formation.setdefault("logistics",{}); available_remounts=max(0,int(logistics.get("remount_horses",0) or 0))
                    if remounts_issued>available_remounts: raise ValueError(f"battle sustainment remount overdraw: used {remounts_issued}, held {available_remounts}")
                    logistics["remount_horses"]=available_remounts-remounts_issued
                formation_fatigue_rules=self.read(FATIGUE_RULES_PATH).get("formation",{}); battle_costs=formation_fatigue_rules.get("activity_cost_per_hour",{}) if isinstance(formation_fatigue_rules,Mapping) else {}; battle_cost_per_hour=max(0.0,float(battle_costs.get("battle",5.0) or 0.0)); base_battle_fatigue=max(1,int(math.ceil(battle_cost_per_hour*float(battle_hours))))
                battle_fatigue_gain=fatigue_gain_after_rotations(base_battle_fatigue,personnel=before,battle_hours=float(battle_hours),rest_person_hours=float(sustainment_state.get("rest_person_hours",0.0) or 0.0),rules=sustainment_rules)
                hero_cohesion_loss=min(12,max(0,int(round((1.0-math.exp(-max(0.0,hero_cohesion_shock_alloc)/8.0))*12.0*contact_duration_factor))))
                hero_morale_loss=min(8,max(0,int(round((1.0-math.exp(-max(0.0,hero_cohesion_shock_alloc)/12.0))*8.0*contact_duration_factor))))
                contact_cohesion_loss=max(1,int(round(5*contact_duration_factor)))
                morale_resolution=resolve_formation_morale(
                    self, base_morale=int(formation.get("morale",50)),
                    recent_casualty_fraction=loss/max(1,before), cumulative_casualty_fraction=loss/max(1,before),
                    registered_fear_pressure=hero_morale_loss, cohesion=int(formation.get("cohesion",50)),
                    supply_condition=str(admission[ref].get("supply_condition","adequate")),
                )
                stamp_formation_activity_fatigue(formation,completed_at=battle_completed,fatigue_gain=battle_fatigue_gain,activity_kind="battle"); formation["morale"]=int(morale_resolution["effective_morale"]); formation["cohesion"]=_clamp(int(formation.get("cohesion",50))-contact_cohesion_loss-hero_cohesion_loss); formation["status"]="combat_effective" if formation["personnel"]>0 else "destroyed"; killed[ref]=loss
                source_pressure=attacker_hero_pressure if ref in defenders else defender_hero_pressure; hero_attributed=min(loss,max(0,int(round(source_pressure*before/max(1,source_total)))))
                material_losses[ref]={"equipment_units":lost_eq,"mounts":lost_mounts,"mount_casualties":mount_loss,"phase_mount_attrition":phase_mount_loss,"casualty_correlated_mount_loss":casualty_mount_loss,"mount_casualty_risk_milli":int(round(mount_risk*1000)),"equipment_condition_losses":condition_losses,"hero_attributed_casualties":hero_attributed,"hero_officer_pressure":round(hero_officer_pressure_alloc,4),"hero_cohesion_shock_pressure":round(hero_cohesion_shock_alloc,4),"hero_cohesion_loss":hero_cohesion_loss,"hero_morale_loss":hero_morale_loss,"morale_resolution":_deepcopy(morale_resolution),"hero_artillery_pressure":round(hero_artillery_pressure_alloc,4),"hero_artillery_casualty_reclassification":artillery_shift_applied,"strategic_supply_condition":str(admission[ref].get("supply_condition","adequate")),"strategic_supply_score_milli":int(admission[ref].get("supply_score_milli",1000) or 1000),"ammunition_consumed":consumed,"ammunition_recovered":recovered_ammunition,"battlefield_sustainment":{"command_scale_personnel":int(sustainment_state.get("command_scale_personnel",100) or 100),"rotation_count":len(sustainment_state.get("rotations",[])) if isinstance(sustainment_state.get("rotations"),list) else 0,"rest_person_hours":round(float(sustainment_state.get("rest_person_hours",0.0) or 0.0),3),"battle_fatigue_gain":battle_fatigue_gain,"outfitting_sets_consumed":{str(k):max(0,int(v)) for k,v in spare_consumed.items()},"remount_horses_issued":remounts_issued},"incoming_ranged_shield_wear_pct":round(incoming_shield_wear,3),"incoming_ranged_armor_wear_pct":round(incoming_armor_wear,3),"composition_losses":dead_comp}
                casualty_fraction=loss/max(1,before); losing_side=(ref in attackers and not attacker_won) or (ref in defenders and attacker_won); named_killed_inside=[]; inside_deaths=0
                commander_lost_this_battle=False; key_staff_lost_this_battle=False
                participants=combat_named.get(ref,[])
                for participant in participants:
                    person_ref=str(participant.get("person_ref","")); role=str(participant.get("role","embedded")); included=bool(participant.get("included_in_personnel")); all_named_refs.append(person_ref)
                    if participant.get("command_scope")=="higher":
                        continue
                    exposure=max(.05,min(1.0,float(participant.get("exposure_factor",.75))))
                    try: person_path,person0=self.owner(person_ref); person=_deepcopy(person0)
                    except (ValueError,KeyError,FileNotFoundError): continue
                    if self._person_health(person)=="dead": continue
                    hero_row=hero_intervention_by_person.get(person_ref,{}) if isinstance(hero_intervention_by_person.get(person_ref,{}),Mapping) else {}
                    hero_injury_risk=max(0.0,min(.98,float(hero_row.get("incoming_injury_risk",0) or 0)))
                    hero_death_risk=max(0.0,min(.60,float(hero_row.get("incoming_death_risk",0) or 0)))
                    named_ammunition={}
                    roll=(_battle_seed("named:"+ref+":"+person_ref)%10000)/10000
                    base_death=min(.30,casualty_fraction*(.30 if losing_side else .16)*exposure)
                    base_wound=min(.78,.015+casualty_fraction*1.35*exposure)
                    if hero_row:
                        death_p=min(.60,1.0-(1.0-base_death)*(1.0-hero_death_risk))
                        physical_wound=max(0.0,hero_injury_risk-hero_death_risk)
                        wound_p=min(.90,1.0-(1.0-base_wound)*(1.0-physical_wound))
                    else:
                        death_p=base_death; wound_p=base_wound
                    capture_p=min(.35,casualty_fraction*.45*exposure) if losing_side and not included else 0
                    wound_p=min(wound_p,max(0.0,.995-death_p-capture_p)); outcome="unharmed"
                    may_die=(not included) or inside_deaths<loss
                    if may_die and roll<death_p:
                        outcome="killed"; self._settle_person_death(person_ref,person_path,person,str(battle_completed),"battle casualty during named local intervention" if hero_row else "battle casualty",settle_force_body=not included)
                        if role=="commander": commander_lost_this_battle=True
                        elif role=="staff": key_staff_lost_this_battle=True
                        remove_active_role(formation,person_ref,role)
                        if included: named_killed_inside.append(person_ref); inside_deaths+=1
                    elif roll<death_p+capture_p:
                        outcome="captured"; person["custody_state"]={"status":"captured","captured_at":str(battle_completed),"battle_ref":event_id,"captured_by":"defender" if ref in attackers else "attacker"}
                        if role=="commander": commander_lost_this_battle=True
                        elif role=="staff": key_staff_lost_this_battle=True
                        remove_active_role(formation,person_ref,role); self.put(person_path,person)
                    elif roll<death_p+capture_p+wound_p:
                        outcome="wounded"
                        incoming_layers=hero_row.get("representative_incoming_contact_layers",[]) if isinstance(hero_row.get("representative_incoming_contact_layers"),list) else []
                        severity_rank={"none":0,"minor":1,"moderate":2,"serious":3,"severe":3,"critical":4}
                        best_layer=max((row for row in incoming_layers if isinstance(row,Mapping)),key=lambda row:(severity_rank.get(str(row.get("armor_severity","none")),0),float(row.get("armor_maximum_ratio",0) or 0)),default=None)
                        physical_severity=str(best_layer.get("armor_severity","none")) if isinstance(best_layer,Mapping) else "none"
                        if physical_severity=="severe": physical_severity="serious"
                        if hero_row and isinstance(best_layer,Mapping) and physical_severity in {"minor","moderate","serious","critical"} and hasattr(self,"_personal_apply_wound"):
                            zone=str(best_layer.get("aim_zone") or "upper_torso"); structure=str(best_layer.get("aim_structure") or zone); mode=str(best_layer.get("enemy_attack_mode") or "blunt")
                            structural=resolve_structural_injury(zone=zone,structure=structure,side="midline",mode=mode,severity=physical_severity,impact_index=float(best_layer.get("armor_residual_impact",0) or 0),penetration_index=float(best_layer.get("armor_residual_penetration",0) or 0),contact_grade="solid",seed=_battle_seed("hero-wound:"+person_ref))
                            wound=self._personal_apply_wound(person,zone=zone,severity=physical_severity,mode=mode,source_weapon=str(best_layer.get("enemy_weapon_id") or "battlefield_weapon"),at=str(battle_completed),side="midline",structure=structure,structural_resolution=structural)
                            wound["structural_state_changes"]=apply_structural_injury_state(person,structural,at=str(battle_completed),source_weapon=str(best_layer.get("enemy_weapon_id") or "battlefield_weapon"))
                            wound["battle_ref"]=event_id; wound["causal_source"]="named_local_intervention_contact"
                        else:
                            self._set_person_health(person,"injured"); person["injury_state"]={"label":"battle wound","severity":"severe" if casualty_fraction>=.20 else "moderate","inflicted_at":str(battle_completed),"minimum_recovery_hours":72 if casualty_fraction>=.20 else 24,"recovered_hours":0,"active":True}
                        if role=="commander": commander_lost_this_battle=True
                        elif role=="staff": key_staff_lost_this_battle=True
                        remove_active_role(formation,person_ref,role); award_person_experience(person,role,exposure); self.put(person_path,person)
                    else:
                        award_person_experience(person,role,exposure); self.put(person_path,person)
                    if hero_row:
                        named_ammunition=settle_named_projectile_ammunition(person_ref,person,participant,hero_row,won_field=won_side,outcome=outcome)
                    named_fatigue={}
                    if outcome!="killed" and person_ref not in named_fatigue_settled:
                        fatigue_gain=battle_person_fatigue_gain(
                            rules=named_fatigue_rules,battle_hours=float(battle_hours),role=role,
                            endurance=float(participant.get("endurance",0) or 0),
                            available_contact_seconds=float(hero_row.get("available_personal_contact_seconds",0) or 0) if hero_row else 0.0,
                            physical_contacts=int(hero_row.get("physical_contacts",0) or 0) if hero_row else 0,
                            burden_multiplier=float(participant.get("fatigue_burden_multiplier",1.0) or 1.0),
                        )
                        named_fatigue=stamp_person_activity_fatigue(person,completed_at=battle_completed,fatigue_gain=fatigue_gain,activity_kind="battle")
                        named_fatigue_settled.add(person_ref)
                    if outcome!="killed":
                        self.put(person_path,person)
                    named_person_outcomes[person_ref]={"formation_ref":ref,"representation":str(participant.get("representation")),"role":role,"outcome":outcome,"roll_basis_points":int(round(roll*10000)),"casualty_fraction_basis_points":int(round(casualty_fraction*10000)),"direct_combat_score_milli":int(round(float(participant.get("direct_combat_score",0))*1000)),"command_score_milli":int(round(float(participant.get("command_score",0))*1000)),"named_intervention":bool(hero_row),"intervention_incoming_injury_risk_milli":int(round(hero_injury_risk*1000)),"intervention_incoming_death_risk_milli":int(round(hero_death_risk*1000)),"intervention_incoming_expected_contacts_milli":int(round(float(hero_row.get("incoming_expected_contacts",0) or 0)*1000)) if hero_row else 0,"named_ammunition":named_ammunition,"fatigue":named_fatigue}
                    if outcome!="killed" and str(participant.get("representation"))!="person-lite" and role in {"commander","staff"}:
                        won=(ref in attackers and attacker_won) or (ref in defenders and not attacker_won)
                        appraisal=battle_service_appraisal(
                            won=won, command_role=role, own_personnel_before=before, enemy_personnel_before=source_total,
                            own_casualties=loss, battle_hours=float(battle_hours), operational_contact=bool(operational_contact),
                        )
                        merit_award=max(1,int(appraisal.get("adjudicated_merit",1) or 1))
                        try: self._award_career_merit(person_ref,merit_award,event_id,str(battle_completed),appraisal=appraisal)
                        except ValueError: pass
                for killed_ref in named_killed_inside:
                    unregister_materialized_rank(formation, killed_ref)
                if commander_lost_this_battle or key_staff_lost_this_battle:
                    command_loss_morale = resolve_formation_morale(
                        self, base_morale=int(formation.get("morale", 50) or 50),
                        cohesion=int(formation.get("cohesion", 50) or 50),
                        commander_lost=commander_lost_this_battle, key_staff_lost=key_staff_lost_this_battle,
                    )
                    formation["morale"] = int(command_loss_morale["effective_morale"])
                    material_losses[ref]["command_loss_morale_resolution"] = _deepcopy(command_loss_morale)
                material_losses[ref]["aggregate_officer_losses"] = settle_aggregate_officer_losses(
                    formation, before_personnel=before, casualties=loss, seed=f"{event_id}:{ref}:officer_cadre",
                    targeting_pressure=hero_officer_pressure_alloc,
                )
                reorganize_officer_cadre(formation, at=str(battle_completed), reason="post_battle_reorganization")
                if formation["personnel"] > 0:
                    officer_contact_fraction = min(1.0, .35 + casualty_fraction * 3.0 + (.10 if losing_side else 0.0))
                    record_officer_cadre_combat_experience(
                        formation, battle_hours=float(battle_hours), contact_fraction=officer_contact_fraction, at=str(battle_completed)
                    )
                sync_materialized_officer_billets(self, formation)
                self.put(path,formation)

                force_ref=str(formation["owner_force_ref"]); fp=self.owner_path(force_ref); force=self._ct_force(fp) if hasattr(self,"_ct_force") else _deepcopy(self.read(fp)); cohort_losses={}
                if hasattr(self,"_ct_isolate_training"): self._ct_isolate_training(force,formation,event_id+":"+ref)
                if formation.get("cohort_composition"):
                    cohort_losses=trim_formation_to_personnel(force,formation,old_personnel=before,new_personnel=formation["personnel"],casualty_ref=event_id,materialized_casualty_refs=named_killed_inside); material_losses[ref]["cohort_losses"]=cohort_losses
                    exact_role_losses={role:max(0,int(count)-int(formation.get("composition",{}).get(role,0))) for role,count in before_comp.items()}
                    material_losses[ref]["composition_losses"]={role:count for role,count in exact_role_losses.items() if count>0}
                alloc=force.get("allocated_to_formations",{}).get(ref)
                if isinstance(alloc,dict): alloc["personnel"]=formation["personnel"]
                elif alloc is not None: force["allocated_to_formations"][ref]=formation["personnel"]
                force["headcount"]=int(force.get("headcount",0))-loss
                if formation.get("cohort_composition"):
                    profiles=self.read("game/data/mil/recruitment-cohort-profiles.json"); training_rules=self.read("game/data/mechanics/training.json"); contact_fraction=min(1,.35+casualty_fraction*3+(.10 if losing_side else 0)); registry=self.read(TRAINING_PROGRAM_REGISTRY_PATH); combat_weights={}
                    for _item in formation.get("cohort_composition",[]):
                        if not isinstance(_item,Mapping): continue
                        _cohort=force.get("cohort_ledger",{}).get("cohorts",{}).get(str(_item.get("cohort_id","")),{})
                        if not isinstance(_cohort,Mapping): continue
                        _role=str(_cohort.get("role") or next(iter(formation.get("composition",{})),"line_infantry")); _program=resolve_training_program_ref(registry,role=_role,training_ref=formation_training_ref_for_role(formation, _role)); combat_weights[_role]=combat_skill_weights(registry,_program)
                    record_formation_combat_experience(force,formation,battle_hours=float(battle_hours),contact_fraction=contact_fraction,role_profiles=profiles.get("role_training_profiles",{}),training_rules=training_rules,evidence_ref=event_id,skill_weights_by_role=combat_weights); validate_cohort_ledger(force); self.put(path,formation)
                self.put(fp,force)
                if force_ref.startswith("force_state_"):
                    state=force_ref.replace("force_state_","")
                    if str(force.get("service_class",""))=="state_levy": state=str(force.get("state",state)).replace("state_","")
                    pp=f"state/population/{state}.json"; pop=_deepcopy(self.read(pp)); pop["strata"]["active_military"]-=loss; pop["population_total"]-=loss; self.put(pp,pop)
                elif str(force.get("administrative_owner",""))==self.PLAYER_ACTOR:
                    pp="state/population/qin.json"; pop=_deepcopy(self.read(pp)); pop["strata"]["private_household_military"]=max(0,int(pop["strata"].get("private_household_military",0))-loss); pop["population_total"]-=loss; self.put(pp,pop)
                elif str(force.get("administrative_owner","" )).startswith("house_"):
                    house_ref=str(force["administrative_owner"]); house=self.read(self.owner_path(house_ref)); state=self._state_key(house.get("state")); pp=f"state/population/{state}.json"; pop=_deepcopy(self.read(pp)); pop["strata"]["private_household_military"]=max(0,int(pop["strata"].get("private_household_military",0))-loss); pop["population_total"]-=loss; self.put(pp,pop)

        immediate_army_staff_review = {"reviewed_command_group_refs": [], "evidence": []}
        if hasattr(self, "_trigger_post_battle_army_staff_reviews"):
            immediate_army_staff_review = self._trigger_post_battle_army_staff_reviews(
                killed, at=str(battle_completed), battle_ref=event_id
            )
        if operational_contact and not internal_operational_contact:
            self._battle_lifecycle_begin_contact(
                operation_ref=str(operation_ref),
                battlefield_ref=str(operational_battlefield_ref),
                sector_ref=str(operational_sector_ref),
                contact_ref=event_id,
                started_at=battle_started,
                ends_at=battle_completed,
                light_mode=str(contact_plan.get("light_mode", "daylight")),
                attacker_refs=attackers,
                defender_refs=defenders,
            )
        if internal_operational_contact:
            time_metrics={"hosts_woken":0,"events_processed":0,"battlefield_reports":[],"battlefield_reviews":0,"battlefield_player_interrupt":False}
        else:
            time_metrics=self._advance_runtime(str(battle_completed))
        if operational_contact and not internal_operational_contact:
            reached = CampaignTime.parse(str(self.read("state/runtime.json").get("world_time", battle_completed)))
            if reached >= battle_completed:
                self._battle_lifecycle_clear_contact(
                    operation_ref=str(operation_ref),
                    battlefield_ref=str(operational_battlefield_ref),
                    contact_ref=event_id,
                    at=reached,
                )
        operational_battlefield_ref = (context or {}).get("battlefield_ref") if internal_operational_contact else payload.get("battlefield_ref")
        operational_sector_ref = (context or {}).get("sector_ref") if internal_operational_contact else payload.get("sector_ref")
        hero_object_consequences=[]
        contact_status: Dict[str, Any]={}
        if operational_battlefield_ref and operational_sector_ref and operation_ref:
            winner_officer_pressure=attacker_hero_officer_pressure if attacker_won else defender_hero_officer_pressure
            winner_cohesion_pressure=attacker_hero_cohesion_shock if attacker_won else defender_hero_cohesion_shock
            winner_artillery_pressure=attacker_hero_artillery_pressure if attacker_won else defender_hero_artillery_pressure
            loser_refs=defenders if attacker_won else attackers
            local_breach_summary={
                "formation_refs":list(loser_refs),
                "breached_sector_count":0,
                "sector_integrity_by_formation":{},
            }
            if battle_phase_trace:
                final_states=battle_phase_trace[-1].get("formation_states",{}) if isinstance(battle_phase_trace[-1],Mapping) else {}
                for loser_ref in loser_refs:
                    state=final_states.get(loser_ref,{}) if isinstance(final_states,Mapping) else {}
                    after=state.get("local_sector_integrity_after",{}) if isinstance(state,Mapping) else {}
                    if isinstance(after,Mapping):
                        local_breach_summary["sector_integrity_by_formation"][loser_ref]={str(k):float(v) for k,v in after.items()}
                    local_breach_summary["breached_sector_count"]+=max(0,int(state.get("breached_sector_count_after",0) or 0)) if isinstance(state,Mapping) else 0
            hero_object_consequences=self._battlefield_apply_battle_result(
                operation_ref=str(operation_ref),
                battlefield_ref=str(operational_battlefield_ref),
                sector_ref=str(operational_sector_ref),
                attacker_refs=attackers,
                defender_refs=defenders,
                winner="attacker" if attacker_won else "defender",
                event_id=event_id,
                at=battle_completed,
                hero_object_pressure={
                    "officer_pressure":round(winner_officer_pressure,6),
                    "cohesion_shock_pressure":round(winner_cohesion_pressure,6),
                    "artillery_pressure":round(winner_artillery_pressure,6),
                },
                local_breach_summary=local_breach_summary,
                contact_duration_factor=contact_duration_factor if operational_contact else 1.0,
            )
            if operational_contact:
                contact_status=self._battle_lifecycle_contact_status(
                    operation_ref=str(operation_ref),
                    battlefield_ref=str(operational_battlefield_ref),
                    sector_ref=str(operational_sector_ref),
                    attacker_refs=attackers,
                    defender_refs=defenders,
                    event_id=event_id,
                )
        battlefield_sustainment_summary={
            ref:{
                "command_scale_personnel":int(battle_sustainment.get(ref,{}).get("command_scale_personnel",100) or 100),
                "initial_frontline_ammunition":dict(battle_sustainment.get(ref,{}).get("initial_frontline_ammunition",{})),
                "initial_hq_ammunition":dict(battle_sustainment.get(ref,{}).get("initial_hq_ammunition",{})),
                "remaining_frontline_ammunition":dict(battle_sustainment.get(ref,{}).get("frontline_ammunition",{})),
                "remaining_hq_ammunition":dict(battle_sustainment.get(ref,{}).get("hq_ammunition",{})),
                "rotations":_deepcopy(battle_sustainment.get(ref,{}).get("rotations",[])),
                "outfitting_sets_consumed":dict(battle_sustainment.get(ref,{}).get("spare_outfitting_consumed",{})),
                "remount_horses_issued":max(0,int(battle_sustainment.get(ref,{}).get("remount_horses_issued",0) or 0)),
                "rest_person_hours":round(float(battle_sustainment.get(ref,{}).get("rest_person_hours",0.0) or 0.0),3),
            }
            for ref in all_refs
        }
        causal_trace,narration_contract=build_battle_causal_trace(
            attackers=attackers,defenders=defenders,battlefield_ref=battlefield,terrain_kind=terrain_kind,
            formations=formations,killed=killed,material_losses=material_losses,score_details=score_details,
            named_person_outcomes=named_person_outcomes,attacker_won=attacker_won,
        )
        winner_scope="contact_period" if operational_contact else "battle"
        terrain_tags=sorted(terrain_tokens(terrain_kind)); terrain_primary=primary_terrain_tag(terrain_kind)
        hist=_deepcopy(self.read("state/history/events/index.json")); hist.setdefault("events",[]).append({"event_id":event_id,"kind":"battle","at":str(battle_started),"completed_at":str(battle_completed),"duration_hours":battle_hours,"operation_ref":operation_ref,"winner":"attacker" if attacker_won else "defender","winner_scope":winner_scope,"operational_contact":operational_contact,"contact_plan":_deepcopy(contact_plan),"contact_status":_deepcopy(contact_status),"battlefield_ref":battlefield,"operational_battlefield_ref":operational_battlefield_ref,"sector_ref":operational_sector_ref,"contact_proof":contact_proof,"fortress_support_factor_milli":int(round(fortress_support_factor*1000)),"terrain_kind":terrain_primary,"terrain_tags":terrain_tags,"terrain_profile":terrain_kind,"attackers":attackers,"defenders":defenders,"participant_refs":sorted(set(x for x in all_named_refs if x)),"killed":killed,"material_losses":material_losses,"named_person_outcomes":named_person_outcomes,"hero_object_consequences":hero_object_consequences,"causal_trace":causal_trace,"narration_contract":narration_contract}); write_history_index(self, hist)
        result={"battle_event":event_id,"battlefield_ref":battlefield,"operational_battlefield_ref":operational_battlefield_ref,"sector_ref":operational_sector_ref,"contact_proof":contact_proof,"terrain_kind":terrain_primary,"terrain_tags":terrain_tags,"terrain_profile":terrain_kind,"represented_personnel":represented,"casualties":killed,"material_losses":material_losses,"winner":"attacker" if attacker_won else "defender","winner_scope":winner_scope,"operational_contact":operational_contact,"contact_plan":_deepcopy(contact_plan),"contact_status":_deepcopy(contact_status),"score_breakdown":score_details,"named_person_outcomes":named_person_outcomes,"causal_trace":causal_trace,"narration_contract":narration_contract,"ammunition_plans":{ref:{"desired_by_resource":ammo_plans[ref].get("desired_by_resource",{}),"consumed_by_resource":ammo_plans[ref].get("consumed_by_resource",{}),"overall_sufficiency_basis_points":int(round(float(ammo_plans[ref].get("overall_sufficiency",1))*10000))} for ref in all_refs},"battlefield_sustainment":battlefield_sustainment_summary,"duration_hours":battle_hours,"contact_phases":battle_phase_trace,"hero_object_consequences":hero_object_consequences,"immediate_army_staff_review":immediate_army_staff_review,"world_time":str(battle_completed)}; result.update(time_metrics); return result

    def _dispatch(self, command: CommandEnvelope, payload: Mapping[str, Any]) -> Dict[str, Any]:
        t=command.command_type
        if t not in COMMAND_TYPES:
            raise ValueError("unsupported Sword semantic command: %s" % t)
        if t in {"command_group_action", "command_group_train", "investigation_action", "commission_action", "medical_treatment", "commitment_action", "information_create", "information_deliver"} and hasattr(self, "_dispatch_campaign_depth"):
            return self._dispatch_campaign_depth(command, payload)
        if t=="advance_time":
            requested=payload.get("target_time")
            current=CampaignTime.parse(self.read("state/runtime.json")["world_time"])
            if not requested:
                hours=int(payload.get("hours",0)); requested=current.add_seconds(hours*3600).__str__()
            requested_time=CampaignTime.parse(str(requested)); totals={"hosts_woken":0,"events_processed":0}; delivered=[]; interrupted=False
            while current < requested_time:
                boundary,_detail=self._battlefield_next_boundary_time(current,requested_time)
                step=boundary if boundary is not None and boundary < requested_time else requested_time
                if step<=current: step=current.add_seconds(1)
                metrics=self._advance_runtime(str(step))
                totals["hosts_woken"]+=int(metrics.get("hosts_woken",0)); totals["events_processed"]+=int(metrics.get("events_processed",0))
                delivered.extend(metrics.get("battlefield_reports",[]))
                current=CampaignTime.parse(str(step))
                if metrics.get("battlefield_player_interrupt"):
                    interrupted=True; break
            actual=str(current); self._write_meta(command,actual); return self._result(world_time=actual,requested_time=str(requested_time),interrupted=interrupted,battlefield_reports=delivered,**totals)
        if t=="scene_consequence":
            summary = str(payload.get("summary", "material scene consequence"))
            # Stable operations use this hidden command only as typed transport
            # for player-authored interaction attempts. Those attempts are routing
            # state, not world consequences, so keep them out of semantic history.
            from sword_runtime.api.interaction_surface import record_interaction_attempt
            attempt_ref = record_interaction_attempt(self, summary, at=command.submitted_at)
            if attempt_ref is not None:
                self._write_meta(command)
                return self._result(event_id=attempt_ref, record_kind="interaction_attempt")
            # Generic internal scene consequences remain semantic only when an
            # internal caller explicitly uses this command with a non-attempt
            # summary. The player-facing API never exposes that raw route.
            hist = _deepcopy(self.read("state/history/events/index.json"))
            eid = "scene_" + command.semantic_digest[:16]
            hist.setdefault("events", []).append({
                "event_id": eid, "kind": "scene_consequence",
                "at": command.submitted_at, "summary": summary,
            })
            write_history_index(self, hist)
            self._write_meta(command)
            return self._result(event_id=eid)
        if t=="travel":
            player=_deepcopy(self.read("state/player.json")); origin=player.get("location"); dest=str(payload["destination_ref"]); mode=str(payload.get("mode","foot"));
            if mode not in {"foot","horse"}: raise ValueError("personal travel mode must be foot or horse")
            route=self._find_route(origin,dest,mode=mode); base_duration=int(route.get("duration_hours",route.get("hours",24))); body_factor=anatomy_activity_factor(player, f"{mode}_travel")
            if mode=="foot" and body_factor<0.12: raise ValueError("current permanent bodily function cannot support ordinary foot travel")
            duration=max(1,int(math.ceil(base_duration/max(0.05,body_factor)))) if base_duration>0 else 0; current=self._world_time(); settle_person_idle_fatigue(player,current=current,rules=self.read(FATIGUE_RULES_PATH),state="ordinary"); target_time=current.add_seconds(duration*3600); target=str(target_time); m=self._advance_runtime(target); player["location"]=dest
            if duration>0: stamp_person_activity_fatigue(player,completed_at=target_time,fatigue_gain=max(1,duration//12),activity_kind="travel")
            self.put("state/player.json",player); self._write_meta(command,target); return self._result(origin=origin,destination=dest,route_ref=route.get("ref", route.get("route_ref")),route_refs=route.get("route_refs",[]),route_path=route.get("path",[]),base_duration_hours=base_duration,bodily_function_factor=round(body_factor,6),duration_hours=duration,world_time=target,**m)
        if t=="individual_training":
            player=_deepcopy(self.read("state/player.json")); hours=int(payload.get("hours",1)); focus=str(payload.get("focus","Athletics"))
            if self._person_health(player)!="healthy": raise ValueError("injured player requires recovery before deliberate training")
            current=self._world_time(); training=self.read("game/data/mechanics/training.json"); settle_person_idle_fatigue(player,current=current,rules=self.read(FATIGUE_RULES_PATH),state="ordinary")
            player_fatigue=player.get("health",{}).get("fatigue",player.get("fatigue",0)) if isinstance(player.get("health"),Mapping) else player.get("fatigue",0)
            if int(player_fatigue or 0)>70: raise ValueError("player is too fatigued for deliberate training")
            if focus not in merged_skill_map(player): raise ValueError("training focus must name an exact saved skill")
            registry=self.read(TRAINING_PROGRAM_REGISTRY_PATH); contract=player.get("activity_contract") if isinstance(player.get("activity_contract"),Mapping) else {}; explicit=str(contract.get("training_program_ref","") or "")
            program_ref=resolve_training_program_ref(registry,person=player,explicit_program_ref=explicit or None); drill_ref=registered_focus_drill_ref(registry,program_ref,focus)
            profiles=self.read("game/data/mil/recruitment-cohort-profiles.json"); regimens=profiles.get("training_regimens",{}) if isinstance(profiles,Mapping) else {}; regimen=regimens.get(str(contract.get("training_regimen_ref","regular_army")),{}) if isinstance(regimens,Mapping) else {}
            if not isinstance(regimen,Mapping): regimen={}
            target_time=current.add_seconds(hours*3600); target=str(target_time); evidence=f"individual_training:{command.semantic_digest[:24]}"
            player_location=str(self._person_location(player) or ""); environment=training_environment(self,location_ref=player_location,simultaneous_trainees=1) if player_location else {"facility_grade":"none","capacity_factor":0.0}
            contexts=instructor_contexts_for_program(self,registry=registry,training_rules=training,program_ref=program_ref,trainee_skills=merged_skill_map(player),student_count=1,location_ref=player_location,trainee_ref=self.PLAYER_ACTOR,scheduled_hours=float(hours),window_start=str(current),window_end=target,evidence_ref=evidence,reserve_duty=True,focus_drill_ref=drill_ref)
            access=exact_person_drill_access(self,registry=registry,program_ref=program_ref,person=player); metrics=self._advance_runtime(target); session_rules=self.read("game/data/mechanics/training-session.json")
            development=settle_exact_registered_focus(player,registry=registry,program_ref=program_ref,focus_skill=focus,hours=hours,at=target_time,training_rules=training,session_rules=session_rules,facility_grade=str(environment.get("facility_grade","none")),equipment_grade=str(regimen.get("equipment_grade","adequate")),recovery_grade=str(regimen.get("recovery_grade","adequate")),feedback_grade=str(regimen.get("feedback_grade","ordinary")),instructor_context_by_drill=contexts,drill_access=access,time_window_start=str(current),time_window_end=target,time_evidence_ref=evidence)
            verified=max(0,int(development.get("verified_hours",hours) or 0));
            if verified>0: stamp_person_activity_fatigue(player,completed_at=target_time,fatigue_gain=max(1,int(round(verified/2.0))),activity_kind="training")
            dev=player.setdefault("development_state",{}); last=dev.get("last_training") if isinstance(dev.get("last_training"),Mapping) else {}; dev["last_training"]={**dict(last),"started_at":str(current),"completed_at":target,"focus":focus,"verified_hours":verified,"program_ref":program_ref,"drill_ref":drill_ref}; self.put("state/player.json",player); self._write_meta(command,target); return self._result(focus=focus,hours=hours,verified_training_hours=verified,program_ref=program_ref,drill_ref=drill_ref,world_time=target,development=development,**metrics)
        if t=="formation_equipment_repair":
            from sword_runtime.formation_armory_issue import repair_house_formation_equipment
            started=self._world_time()
            categories_raw=payload.get("categories", ["shield", "armor"])
            categories=tuple(str(x) for x in categories_raw) if isinstance(categories_raw,list) else ("shield","armor")
            result=repair_house_formation_equipment(
                self,
                formation_ref=str(payload.get("formation_ref", "")),
                hours=int(payload.get("hours",1)),
                actor_ref=str(command.actor_id),
                at=str(started),
                categories=categories,
            )
            world_time,metrics=self._advance_seconds(int(payload.get("hours",1))*3600)
            self._write_meta(command,str(world_time))
            return self._result(world_time=str(world_time),**result,**metrics)
        if t=="cohort_training":
            p="state/forces/sword-manor.json"; doc=_deepcopy(self.read(p)); hours=int(payload.get("hours",1)); cohort_ref=str(payload.get("cohort_ref","trainee"))
            if cohort_ref not in doc.get("available_by_role",{}): raise ValueError("unknown Inner Walls training cohort")
            current=self._world_time(); target_time=current.add_seconds(hours*3600); target=str(target_time); metrics=self._advance_runtime(target)
            from sword_runtime.training_programs import REGISTRY_PATH as _TRAINING_PROGRAM_REGISTRY_PATH, resolve_program_ref as _resolve_training_program, settle_cohort_program as _settle_cohort_program
            from sword_runtime.training_instructors import instructor_contexts_for_program as _instructor_contexts_for_program
            from sword_runtime.training_facilities import program_facility_access as _program_facility_access
            profiles=self.read("game/data/mil/recruitment-cohort-profiles.json"); training=self.read("game/data/mechanics/training.json"); regimen=profiles.get("training_regimens",{}).get("house_tang_max_sustainable",{}); registry=self.read(_TRAINING_PROGRAM_REGISTRY_PATH); program_ref=_resolve_training_program(registry,role=cohort_ref)
            ledger=ensure_cohort_ledger(doc,at=str(current)); changed=[]
            for cid,cohort in ledger.get("cohorts",{}).items():
                if not isinstance(cohort,dict) or str(cohort.get("role"))!=cohort_ref: continue
                alive=sum(max(0,int(v)) for v in cohort.get("reserve_by_location",{}).values())+sum(max(0,int(v)) for v in cohort.get("allocated_by_formation",{}).values())
                if alive<=0: continue
                before={k:float(v) for k,v in cohort_merged_skill_means(cohort).items()}
                cohort_location = next((str(loc) for loc,count in sorted(cohort.get("reserve_by_location",{}).items()) if int(count or 0)>0), "") if isinstance(cohort.get("reserve_by_location"),Mapping) else ""
                if not cohort_location and isinstance(cohort.get("allocated_by_formation"),Mapping):
                    locations=set()
                    for formation_ref,count in cohort.get("allocated_by_formation",{}).items():
                        if int(count or 0)<=0: continue
                        try:
                            _fp,_formation=self._load_formation(str(formation_ref))
                            if isinstance(_formation,Mapping) and _formation.get("location_ref"):
                                locations.add(str(_formation.get("location_ref")))
                        except (KeyError,ValueError,FileNotFoundError):
                            pass
                    if len(locations)==1: cohort_location=next(iter(locations))
                training_evidence=f"cohort_training:{command.semantic_digest[:24]}:{cid}"
                instructor_contexts=_instructor_contexts_for_program(
                    self,registry=registry,training_rules=training,program_ref=program_ref,
                    trainee_skills=cohort_merged_skill_means(cohort),
                    student_count=alive,location_ref=cohort_location,scheduled_hours=float(hours),
                    window_start=str(current),window_end=target,evidence_ref=training_evidence,reserve_duty=True,
                )
                drill_access=_program_facility_access(self,registry=registry,program_ref=program_ref,location_ref=cohort_location) if cohort_location else None
                environment=training_environment(self,location_ref=cohort_location,simultaneous_trainees=alive) if cohort_location else {"facility_grade":"none","capacity_factor":0.0}
                effective_hours=float(hours)*max(0.0,min(1.0,float(environment.get("capacity_factor",0.0))))
                _settle_cohort_program(cohort,registry=registry,program_ref=program_ref,deliberate_hours=effective_hours,role_exposure_hours=0.0,training_rules=training,facility_grade=str(environment.get("facility_grade","none")),equipment_grade=str(regimen.get("equipment_grade","superior")),recovery_grade=str(regimen.get("recovery_grade","excellent")),evidence_ref=training_evidence,instructor_context_by_drill=instructor_contexts,drill_access=drill_access)
                gains={k:round(float(v)-before.get(k,float(v)),3) for k,v in cohort_merged_skill_means(cohort).items() if float(v)-before.get(k,float(v))>1e-9}
                changed.append({"cohort_id":cid,"personnel":alive,"program_ref":program_ref,"skill_mean_gains":gains})
            if not changed: raise ValueError("selected Inner Walls role has no trainable living cohort")
            validate_cohort_ledger(doc); doc["cohort_training_hours"]=int(doc.get("cohort_training_hours",0))+hours; doc["last_training_at"]=target; self.put(p,doc); self._write_meta(command,target); return self._result(cohort_ref=cohort_ref,hours=hours,world_time=target,cohort_development=changed,**metrics)
        if t in {"health_injury","health_recovery"}:
            player=_deepcopy(self.read("state/player.json"));
            if t=="health_injury":
                severity=str(payload.get("severity","minor")).lower(); recovery_hours={"minor":8,"moderate":24,"severe":72,"critical":168}.get(severity)
                if recovery_hours is None: raise ValueError("unknown injury severity")
                fatigue_cost={"minor":8,"moderate":18,"severe":30,"critical":45}[severity]; self._set_person_health(player,"injured"); player["fatigue"]=_clamp(int(player.get("fatigue",0))+fatigue_cost); player["injury_state"]={"label":str(payload.get("injury","injury")),"severity":severity,"inflicted_at":self.read("state/runtime.json")["world_time"],"minimum_recovery_hours":recovery_hours,"recovered_hours":0,"active":True}; self.put("state/player.json",player); self._write_meta(command); return self._result(health=self._person_health(player),severity=severity,minimum_recovery_hours=recovery_hours)
            hours=int(payload.get("hours",8))
            if hours<1 or hours>168: raise ValueError("recovery must consume between 1 and 168 elapsed hours")
            # Rest is not a substitute for hemorrhage control.  Once combat
            # wounds carry exact bleeding rates, allowing `health_recovery` to
            # close the primary mirror while an uncontrolled ledger wound keeps
            # bleeding would both violate causality and resurrect a stale wound
            # on the next combat read.
            active_before=active_injury_rows(player)
            physiology_before=injury_physiology_snapshot(player) if active_before else {"bleeding":0.0,"respiratory":0.0}
            uncontrolled=physiology_before["bleeding"]
            if uncontrolled>1e-9:
                raise ValueError("uncontrolled bleeding requires medical stabilization before ordinary recovery")
            injury_mechanics=self.read("game/data/mechanics/injury.json")
            respiratory_thresholds=injury_mechanics.get("physiology",{}).get("respiratory_failure_thresholds",{}) if isinstance(injury_mechanics.get("physiology",{}),Mapping) else {}
            if physiology_before["respiratory"]>_fixed(respiratory_thresholds.get("compensated_compromise_percent"),35.0):
                raise ValueError("uncompensated respiratory injury requires medical stabilization before ordinary recovery")
            current=CampaignTime.parse(self.read("state/runtime.json")["world_time"]); target=current.add_seconds(hours*3600).__str__(); metrics=self._advance_runtime(target); player["fatigue"]=_clamp(int(player.get("fatigue",0))-max(1,hours*2)); injury=player.get("injury_state")
            physiology=None
            if active_before:
                physiology=recover_injury_physiology(player,injury_mechanics,elapsed_hours=hours)
                if physiology.get("state")=="dead":
                    player["died_at"]=target; player["death_reason"]="physiological_collapse_during_recovery"
                    self._settle_person_death(self.PLAYER_ACTOR,"state/player.json",player,target,"physiological_collapse_during_recovery")
                    self._write_meta(command,target); return self._result(health="dead",fatigue=player.get("fatigue",0),hours=hours,world_time=target,physiology_state="dead",**metrics)
                if physiology.get("state")=="incapacitated":
                    self._set_person_health(player,"injured")
            recovery_summary=settle_injury_recovery_hours(player,elapsed_hours=hours,resolved_at=target) if active_before else {"resolved_injury_refs":[],"active_injury_refs":[],"active_count":0}
            if recovery_summary.get("active_count",0): self._set_person_health(player,"injured")
            elif isinstance(physiology,Mapping) and physiology.get("state") in {"incapacitated","dead"}: self._set_person_health(player,"injured" if physiology.get("state")=="incapacitated" else "dead")
            elif self._person_health(player)!="dead": self._set_person_health(player,"healthy")
            self.put("state/player.json",player); self._write_meta(command,target); return self._result(health=self._person_health(player),fatigue=player["fatigue"],hours=hours,world_time=target,recovery_summary=recovery_summary,**metrics)
        if t=="relationship_change":
            p="state/relationships.json"; doc=_deepcopy(self.read_optional(p) or {"schema":"sword-relationship-ledger","owner_id":"relationships","edges":[]}); src=str(payload.get("source_ref",command.actor_id)); dst=str(payload["target_ref"]); kind=str(payload.get("kind","trust")); delta=int(payload.get("delta",0)); _,src_person=self._exact_person(src); _,dst_person=self._exact_person(dst)
            if command.actor_id!=self.INTERNAL_ACTOR:
                src_loc=self._person_location(src_person); dst_loc=self._person_location(dst_person)
                if not src_loc or src_loc!=dst_loc: raise ValueError("direct relationship change requires exact co-location; remote social effects must arise from evidence/reputation")
            edge=next((e for e in doc["edges"] if e["source_ref"]==src and e["target_ref"]==dst and e["kind"]==kind),None)
            if edge is None: edge={"source_ref":src,"target_ref":dst,"kind":kind,"value":0,"evidence_refs":[]}; doc["edges"].append(edge)
            edge["value"]=_clamp(int(edge["value"])+delta,-100,100); edge["last_changed_at"]=str(self._world_time()); basis=str(payload.get("basis_ref",f"direct_interaction:{command.expected_revision}")); edge["last_basis_ref"]=basis; edge.setdefault("evidence_refs",[]).append(basis); edge["evidence_refs"]=edge["evidence_refs"][-16:]; self.put(p,doc); world_time,metrics=self._advance_seconds(3600); self._write_meta(command,world_time); return self._result(target_ref=dst,kind=kind,value=edge["value"],world_time=world_time,**metrics)
        if t in {"recruitment_campaign_start","recruitment_campaign_stage","recruitment_campaign_train","recruitment_campaign_finalize","recruitment_campaign_cancel"}:
            evidence=f"{t}:{command.semantic_digest[:24]}"
            if t=="recruitment_campaign_start": result=start_campaign(self,payload,evidence_ref=evidence); hours=1
            elif t=="recruitment_campaign_stage": result=stage_campaign(self,payload,evidence_ref=evidence); hours=1
            elif t=="recruitment_campaign_train": result=train_campaign(self,payload,evidence_ref=evidence); hours=int(payload["hours"])
            elif t=="recruitment_campaign_finalize": result=finalize_campaign(self,payload,evidence_ref=evidence); hours=1
            else: result=cancel_campaign(self,payload,evidence_ref=evidence); hours=1
            world_time,metrics=self._advance_seconds(hours*3600); self._write_meta(command,world_time); result.update({"world_time":world_time,"duration_hours":hours}); result.update(metrics); return self._result(**result)
        if t in {"recruitment","population_transfer"}:
            state=self._state_key(payload["state"]); n=int(payload["personnel"]); pp=f"state/population/{state}.json"; pop=_deepcopy(self.read(pp)); source=str(payload.get("source_stratum","agricultural")); dest=str(payload.get("destination_stratum","active_military"));
            if int(pop["strata"].get(source,0))<n: raise ValueError("insufficient population source")
            pop["strata"][source]-=n; pop["strata"][dest]=int(pop["strata"].get(dest,0))+n; self.put(pp,pop)
            if t=="recruitment":
                fp=f"state/forces/state-{state}.json"
                force=self._ct_force(fp) if hasattr(self,"_ct_force") else _deepcopy(self.read(fp))
                role=str(payload.get("role","line_infantry"))
                source_loc=str(force.get("source_location_ref") or self.read(f"state/depots/{state}.json").get("location_ref"))
                add_recruits(force,role,n,location_ref=source_loc)
                if hasattr(self,"_ct_force"):
                    record_recruitment_cohort(
                        force,
                        role=role,
                        count=n,
                        location_ref=source_loc,
                        source_population_ref=f"population_{state}",
                        source_stratum=source,
                        recruited_at=str(self._world_time()),
                        profile_registry=self.read("game/data/mil/recruitment-cohort-profiles.json"),
                        background_profile=(str(payload.get("background_profile")) if payload.get("background_profile") else None),
                        selection_profile=(str(payload.get("selection_profile")) if payload.get("selection_profile") else "state_basic_military_screen"),
                        selection_retain_fraction=(_fixed(payload.get("selection_retain_fraction")) if payload.get("selection_retain_fraction") is not None else None),
                        provenance_ref=f"recruitment:{command.semantic_digest[:24]}",
                    )
                self.put(fp,force); duration_hours=max(8,int(math.ceil(n/250.0))*8)
            else:
                duration_hours=max(4,int(math.ceil(n/1000.0))*4)
            target,metrics=self._advance_seconds(duration_hours*3600); self._write_meta(command,target); return self._result(state=state,personnel=n,duration_hours=duration_hours,world_time=target,**metrics)
        if t=="person_materialize":
            state=self._state_key(payload.get("state","qin")); person_ref=str(payload["person_ref"]); representation=str(payload.get("representation","person_lite" if payload.get("personal_force_ref") else "exact"))
            if representation not in {"person_lite","exact"}: raise ValueError("materialization representation must be person_lite or exact")
            raw_personal=str(payload.get("personal_force_ref") or "")
            force_ref="force_tang_wei_personal" if raw_personal in {"pforce.tang_wei","force_tang_wei_personal"} else f"force_state_{state}"
            fp=self.owner_path(force_ref); force=self._ct_force(fp) if hasattr(self,"_ct_force") else _deepcopy(self.read(fp))
            role=str(payload.get("role","household_retainer" if force_ref=="force_tang_wei_personal" else "command_personnel")); source_loc=str(payload.get("source_location_ref") or force.get("source_location_ref") or self.read(f"state/depots/{state}.json").get("location_ref")); formation_ref=str(payload.get("formation_ref") or "")
            if representation=="person_lite":
                if_path=None
                person={"schema":"person-lite","id":person_ref,"name":str(payload.get("name",person_ref)),"birth_date":str(payload.get("birth_date","270-BCE-01-01")),"owner":force_ref,"military_rank":{"grade":"materialized_retainer","durable":True},"career_state":{"current_billet":role},"role":role,"stats":{"attributes":{},"skills":{}},"health":{"status":"healthy","fatigue":0},"current_location":source_loc,"body":{"adult_height_cm":170.0,"growth_end_age":18,"current_weight_kg":65.0,"frame":"average"},"appearance":50}
                seed_target=person
            else:
                if_path=f"state/char/{person_ref.replace('char_','').replace('_','-')}.json"
                person={"schema":"sword-materialized-person","owner_id":person_ref,"owner_type":"character","id":person_ref,"name":str(payload.get("name",person_ref)),"state":state,"birth_date":str(payload.get("birth_date","270-BCE-01-01")),"status":"alive","life_status":"active","health_status":"healthy","current_location":source_loc,"attributes":{},"skills":{},"aptitude":{"physical_learning":100,"technical_learning":100,"tactical_learning":100,"academic_learning":100,"social_learning":100},"development_state":{}}
                seed_target=person
            if if_path is not None and self.read_optional(if_path) is not None: raise ValueError("person_ref already exists")
            # Materialized people inherit the canonical equipment standard for the
            # cohort/role they came from. This keeps their individual combat reach,
            # protection and ammunition requirements aligned with the anonymous
            # bodies they replace until an exact equipment transaction changes it.
            if hasattr(self,"_combat_role_profile"):
                role_profile=self._combat_role_profile(role)
                loadout_id=str(role_profile.get("loadout_id", "")) if isinstance(role_profile,Mapping) else ""
                if loadout_id:
                    if representation=="person_lite":
                        seed_target["equipment_standard"]=loadout_id
                    else:
                        seed_target["equipment_loadout_id"]=loadout_id
            if formation_ref:
                formation_path,formation0=self._load_formation(formation_ref); formation=_deepcopy(formation0)
                if str(formation.get("owner_force_ref"))!=force_ref: raise ValueError("materialization formation does not belong to selected force")
                if hasattr(self,"_ct_materialize_from_formation"):
                    self._ct_materialize_from_formation(force,formation,role=role,person_ref=person_ref,person=seed_target)
                else: raise ValueError("cohort materialization support unavailable")
                formation.setdefault("embedded_person_refs",[]).append(person_ref); formation["embedded_person_refs"]=list(dict.fromkeys(formation["embedded_person_refs"]))
                force.setdefault("materialized_assignments",{})[person_ref]={"formation_ref":formation_ref,"role":role,"personnel":1}
                seed_target["equipment_custody"]={"mode":"formation_issue_slot","formation_ref":formation_ref,"role":role}
                self.put(formation_path,formation)
            else:
                if hasattr(self,"_ct_materialize_from_cohort"):
                    self._ct_materialize_from_cohort(force,role,source_loc,person_ref,seed_target)
                else: raise ValueError("cohort materialization support unavailable")
                self._take_force_personnel(force,role,1,source_loc)
                seed_target["equipment_custody"]={"mode":"force_issue_standard","force_ref":force_ref,"role":role}
            # Convert deterministic sampled exact-style stats to the compact person-lite layout.
            if representation=="person_lite":
                attrs=seed_target.pop("attributes",{})
                skills=seed_target.pop("skills",{})
                seed_target["stats"]={"attributes":attrs,"skills":skills}
                apt=seed_target.get("aptitude",{})
                if apt: seed_target["aptitude"]=apt
                hv=int(hashlib.sha256((person_ref+"|body").encode()).hexdigest()[:8],16)
                seed_target["body"]={"adult_height_cm":round(160.0+(hv%211)/10.0,1),"growth_end_age":18,"current_weight_kg":round(52.0+((hv//211)%241)/10.0,1),"frame":"average"}
                seed_target["appearance"]=int((hv//509)%101)
            force.setdefault("materialized_people",{})[person_ref]={"personnel":1,"role":role,"source_cohort_ref":str(seed_target.get("source_cohort_ref","") or ""),"source_mode":"materialized_exact_person"}
            validate_cohort_ledger(force); self.put(fp,force)
            if force_ref=="force_tang_wei_personal":
                pfpath="state/pforce/wei.json"; pforce=_deepcopy(self.read(pfpath)); pforce.setdefault("members",[]).append(person_ref); pforce["members"]=list(dict.fromkeys(pforce["members"])); self.put(pfpath,pforce)
            if representation=="person_lite":
                put_person_lite(self, person=person, scope_ref=(formation_ref or force_ref))
            else:
                self.put(if_path,person); self._register_owner(person_ref,if_path)
                self._ensure_person_life_host(person_ref,self._world_time())
            world_time,metrics=self._advance_seconds(3600); self._write_meta(command,world_time); return self._result(person_ref=person_ref,representation=representation,personal_force_ref=(force_ref if force_ref=="force_tang_wei_personal" else None),formation_ref=(formation_ref or None),world_time=world_time,**metrics)
        if t=="formation_create":
            state=self._state_key(payload.get("state","qin")); ref=str(payload["formation_ref"]); n=int(payload["personnel"]); requested_force_ref=str(payload.get("force_ref") or f"force_state_{state}"); fp=self.owner_path(requested_force_ref); force=self._ct_force(fp) if hasattr(self,"_ct_force") else _deepcopy(self.read(fp));
            if self.read_optional(f"state/formations/{ref.replace('formation_','').replace('_','-')}.json") is not None: raise ValueError("formation_ref already exists")
            source_loc=str(force.get("source_location_ref",self.read(f"state/depots/{state}.json")["location_ref"])); location=str(payload.get("location_ref",source_loc))
            raw_comp=payload.get("composition"); role=str(payload.get("role","line_infantry")); composition={str(k):int(v) for k,v in raw_comp.items() if int(v)>0} if isinstance(raw_comp,Mapping) else {role:n}
            requested_class=str(payload.get("formation_class","")).strip().lower() or ("unit" if n>=500 else "detachment")
            authorized=int(payload.get("authorized_strength",n))
            validate_establishment(personnel=n,authorized_strength=authorized,formation_class=requested_class)
            if sum(composition.values()) != n: raise ValueError("formation composition must sum exactly to personnel")
            leaked_support=sorted(set(composition) & set(FORBIDDEN_PERMANENT_SUPPORT_ROLES))
            if leaked_support: raise ValueError(f"formation composition cannot create permanent support troop roles: {leaked_support}")
            mount_pool_path=self._mount_pool_path_for_force(requested_force_ref,state)
            mount_pool=_deepcopy(self.read(mount_pool_path)) if mount_pool_path else None
            mount_need_by_role={r:self._role_horse_requirement(r,c) for r,c in composition.items()}
            if isinstance(mount_pool,dict):
                for mounted_role,need_horses in mount_need_by_role.items():
                    if need_horses<=0: continue
                    available_horses=force_role_horses(mount_pool,location,mounted_role)+regional_horses(mount_pool,location)
                    if available_horses<need_horses:
                        raise ValueError(f"new mounted formation lacks conserved horses at {location}: role {mounted_role} needs {need_horses}, available {available_horses}")
            local_pool=self._force_location_pool(force,location)
            for comp_role,count in composition.items():
                if comp_role not in force.get("available_by_role",{}): raise ValueError(f"unknown force role in formation composition: {comp_role}")
                if int(local_pool.get(comp_role,0)) < count or int(force.get("available_by_role",{}).get(comp_role,0)) < count:
                    raise ValueError("new formation must muster every requested role from sufficient exact personnel at the requested geographic disposition")
            for comp_role,count in composition.items(): self._take_force_personnel(force,comp_role,count,location)
            raw_eq=payload.get("equipment_units_by_role")
            requested_eq_by_role={str(k):max(0,int(v)) for k,v in raw_eq.items()} if isinstance(raw_eq,Mapping) else {}
            if not requested_eq_by_role:
                if "equipment_units" in payload:
                    requested_eq_by_role=self._scale_counts(composition,max(0,min(n,int(payload.get("equipment_units",0)))))
                else:
                    requested_eq_by_role={r:int(round(c*.8)) for r,c in composition.items()}
            equipped_by_role={}
            for comp_role,count in composition.items():
                desired=min(count,max(0,int(requested_eq_by_role.get(comp_role,0)))); equipped_by_role[comp_role]=self._take_force_equipment(force,comp_role,desired,location)
            force.setdefault("allocated_to_formations",{})[ref]={"personnel":n,"composition":_deepcopy(composition)}
            cohort_slices=[]
            if hasattr(self,"_ct_force"):
                for comp_role,count in composition.items(): cohort_slices.extend(take_reserve_slices(force,role=comp_role,count=count,location_ref=location,formation_ref=ref,validate=False))
                validate_cohort_ledger(force)
            formation_mounts={}
            if isinstance(mount_pool,dict):
                issued_horses=0
                for mounted_role,need_horses in mount_need_by_role.items():
                    if need_horses<=0: continue
                    from_role=issue_force_role_horses_to_formation(mount_pool,location_ref=location,role=mounted_role,formation_ref=ref,count=need_horses)
                    from_region=allocate_regional_horses_to_formation(mount_pool,location_ref=location,formation_ref=ref,count=need_horses-from_role)
                    if from_role+from_region!=need_horses:
                        raise ValueError("mounted formation muster lost exact horse custody")
                    issued_horses+=need_horses
                if issued_horses: formation_mounts["horse"]=issued_horses
                self.put(mount_pool_path,mount_pool)
            self.put(fp,force)
            path=f"state/formations/{ref.replace('formation_','').replace('_','-')}.json"; commander_ref=payload.get("commander_ref"); admin_owner=str(force.get("administrative_owner",f"state_{state}")); default_authority=self.PLAYER_ACTOR if requested_force_ref=="force_tang_wei_personal" else admin_owner; f={"schema":"sword-formation","formation_ref":ref,"name":str(payload.get("name",ref)),"owner_force_ref":requested_force_ref,"administrative_owner":admin_owner,"command_authority":str(payload.get("command_authority",default_authority)),"commander_ref":commander_ref,"personnel":n,"authorized_strength":authorized,"formation_class":requested_class,"composition":_deepcopy(composition),"cohort_composition":cohort_slices,"location_ref":location,"doctrine_ref":payload.get("doctrine_ref"),"training_ref":payload.get("training_ref"),"doctrine_behavior":{},"training_progress":0,"readiness":40,"morale":60,"cohesion":35,"fatigue":0,"experience":"new","mobilized":False,"status":"forming","logistics":{"war_arrows":0,"war_bolts":0,"construction_material_units":0},"mounts":formation_mounts,"created_at":str(self._world_time())}
            f["doctrine_ref"] = str(f.get("doctrine_ref") or default_formation_doctrine_ref(f))
            f["doctrine_behavior"] = doctrine_behavior(self.read, f)
            normalize_formation_establishment(f)
            ensure_officer_cadre(f); reorganize_officer_cadre(f, at=str(self._world_time()), reason="formation_creation")
            self._set_equipment_units(f,equipped_by_role)
            initial_shields={role:count for role,count in equipped_by_role.items() if count>0 and self._combat_role_uses_shield(role)}
            if initial_shields:
                self._set_shield_units(f,initial_shields)
            initial_armor={role:count for role,count in equipped_by_role.items() if count>0 and self._combat_role_uses_armor(role)}
            if initial_armor:
                self._set_armor_units(f,initial_armor)
            if commander_ref:
                cp, commander=self._validate_person_location_for_formation(str(commander_ref),f)
                self._bind_formation_commander_sheet(str(commander_ref), ref, f, person_path=cp, person=commander)
                self._assign_commander_index(str(commander_ref),ref)
            self.put(path,f); self._register_owner(ref,path); self._index_formation_location(ref,None,location)
            muster_hours=max(1,min(48,int(math.ceil(n/500.0)))); current=self._world_time(); target=str(current.add_seconds(muster_hours*3600)); metrics=self._advance_runtime(target); self._write_meta(command,target); return self._result(formation_ref=ref,personnel=n,authorized_strength=authorized,formation_class=requested_class,composition=composition,world_time=target,muster_hours=muster_hours,**metrics)
        if t in {"formation_reconstitute","formation_train","formation_mobilize","formation_demobilize","formation_doctrine_set","formation_training_set","formation_assign","force_assignment","command_assign","command_transfer","formation_move","resupply"}:
            ref=str(payload["formation_ref"]); p,f0=self._load_formation(ref); f=_deepcopy(f0); world_time: Optional[str]=None; time_metrics: Dict[str,int]={}
            if t=="formation_reconstitute":
                max_fighting=max(0,int(f.get("authorized_strength",f.get("personnel",0))))
                target=int(payload.get("target_personnel",f["personnel"]));
                if target>max_fighting: raise ValueError("reconstitution target exceeds authorized fighting establishment")
                need=max(0,target-int(f["personnel"]));
                if need<=0: raise ValueError("reconstitution target must exceed current personnel")
                fp=self.owner_path(f["owner_force_ref"]); force=self._ct_force(fp) if hasattr(self,"_ct_force") else _deepcopy(self.read(fp)); location=str(f.get("location_ref")); local=self._force_location_pool(force,location)
                current_comp={str(k):max(0,int(v)) for k,v in f.get("composition",{}).items() if max(0,int(v))>0}
                raw_establishment=f.get("establishment_composition") if isinstance(f.get("establishment_composition"),Mapping) else represented_establishment_composition(f)
                establishment={str(k):max(0,int(v)) for k,v in raw_establishment.items() if max(0,int(v))>0}
                if not establishment: establishment={"line_infantry":max(1,int(f.get("personnel",0)))}
                explicit=payload.get("replacement_composition")
                if isinstance(explicit,Mapping):
                    desired_add={str(k):max(0,int(v)) for k,v in explicit.items() if max(0,int(v))>0}
                    if sum(desired_add.values()) != need: raise ValueError("replacement_composition must sum exactly to the requested personnel increase")
                    leaked_support=sorted(set(desired_add) & set(FORBIDDEN_PERMANENT_SUPPORT_ROLES))
                    if leaked_support: raise ValueError(f"reconstitution cannot create permanent support troop roles: {leaked_support}")
                else:
                    target_comp=self._scale_counts(establishment,target)
                    deficits={role:max(0,int(target_comp.get(role,0))-int(current_comp.get(role,0))) for role in target_comp}
                    deficit_total=sum(deficits.values())
                    desired_add=self._scale_counts(deficits,need) if deficit_total>need else {r:c for r,c in deficits.items() if c>0}
                    if sum(desired_add.values()) < need:
                        supplement=self._scale_counts(establishment,need-sum(desired_add.values()))
                        for role,count in supplement.items(): desired_add[role]=desired_add.get(role,0)+count
                actual_add={}
                for role,wanted in desired_add.items():
                    if role not in force.get("available_by_role",{}):
                        if isinstance(explicit,Mapping): raise ValueError(f"unknown replacement role: {role}")
                        continue
                    actual=min(wanted,max(0,int(local.get(role,0))),max(0,int(force.get("available_by_role",{}).get(role,0))))
                    if actual>0: actual_add[role]=actual
                take=sum(actual_add.values())
                if take<=0: raise ValueError("no requested replacement personnel are physically available at formation location")
                for role,count in actual_add.items(): self._take_force_personnel(force,role,count,location)
                old_n=int(f["personnel"]); new_n=old_n+take; f["personnel"]=new_n
                for role,count in actual_add.items(): f.setdefault("composition",{})[role]=int(f.get("composition",{}).get(role,0))+count
                raw_eq=payload.get("equipment_units_by_role")
                requested_eq_by_role={str(k):max(0,int(v)) for k,v in raw_eq.items()} if isinstance(raw_eq,Mapping) else {}
                if not requested_eq_by_role:
                    requested_eq_by_role=self._scale_counts(actual_add,max(0,min(take,int(payload.get("equipment_units",take))))) if "equipment_units" in payload else dict(actual_add)
                equipment=self._equipment_units(f); shield_units=self._shield_units(f); armor_units=self._armor_units(f)
                for role,count in actual_add.items():
                    prior_equipped=max(0,int(equipment.get(role,0)))
                    prior_shields=max(0,int(shield_units.get(role,min(prior_equipped,int(current_comp.get(role,0)))))) if self._combat_role_uses_shield(role) else 0
                    prior_armor=max(0,int(armor_units.get(role,min(prior_equipped,int(current_comp.get(role,0)))))) if self._combat_role_uses_armor(role) else 0
                    gear_take=self._take_force_equipment(force,role,min(count,max(0,int(requested_eq_by_role.get(role,0)))),location); equipment[role]=prior_equipped+gear_take
                    if self._combat_role_uses_shield(role):
                        shield_units[role]=min(int(f.get("composition",{}).get(role,0)),prior_shields+gear_take)
                    if self._combat_role_uses_armor(role):
                        armor_units[role]=min(int(f.get("composition",{}).get(role,0)),prior_armor+gear_take)
                self._set_equipment_units(f,equipment); self._set_shield_units(f,shield_units); self._set_armor_units(f,armor_units)
                # Replacements enter at baseline recruit quality. Veteran state is diluted, never cloned.
                incoming={"readiness":35,"morale":60,"cohesion":25,"training_progress":10,"fatigue":0}
                for field,base in incoming.items(): f[field]=_clamp(int(round((int(f.get(field,base))*old_n + base*take)/max(1,new_n))))
                if take*2>=new_n and str(f.get("experience","new")) in {"veteran","hardened"}: f["experience"]="field_tested"
                force["allocated_to_formations"][ref]=self._formation_allocation_record(f)
                if hasattr(self,"_ct_force"):
                    incoming_slices=[]
                    for role,count in actual_add.items(): incoming_slices.extend(take_reserve_slices(force,role=role,count=count,location_ref=location,formation_ref=ref,validate=False))
                    append_formation_slices(f,incoming_slices)
                    validate_cohort_ledger(force)
                self.put(fp,force); hours=max(1,min(72,int(math.ceil(take/250.0)))); current=self._world_time(); world_time=str(current.add_seconds(hours*3600)); time_metrics=self._advance_runtime(world_time); f["last_reconstituted_at"]=world_time; f["last_reconstitution_by_role"]=_deepcopy(actual_add); reorganize_officer_cadre(f, at=world_time, reason="formation_reconstitution"); sync_materialized_officer_billets(self, f)
            elif t=="formation_train":
                hours=int(payload.get("hours",1)); environment=training_environment(self,location_ref=str(f.get("location_ref", "")),simultaneous_trainees=max(1,int(f.get("personnel",0)))); capacity_factor=max(0.0,min(1.0,float(environment.get("capacity_factor",0.0)))); effective_hours=float(hours)*capacity_factor
                if effective_hours <= 0: raise ValueError("formation has no usable physical training space at its current location")
                current=self._world_time(); settle_formation_idle_fatigue(f,current=current,rules=self.read(FATIGUE_RULES_PATH)); world_time=str(current.add_seconds(hours*3600)); time_metrics=self._advance_runtime(world_time); org_hours=max(0,int(math.floor(effective_hours+1e-9))); f["training_progress"]=_clamp(int(f.get("training_progress",0))+max(1,org_hours//4)); f["cohesion"]=_clamp(int(f.get("cohesion",50))+max(1,org_hours//4)); f["readiness"]=_clamp(int(f.get("readiness",50))+max(0,org_hours//6)); stamp_formation_activity_fatigue(f,completed_at=CampaignTime.parse(world_time),fatigue_gain=max(1,org_hours//5),activity_kind="training"); f["verified_training_hours"]=round(float(f.get("verified_training_hours",0))+effective_hours,3); f["last_training_at"]=world_time
                # Formation training improves both organization and the actual participating cohort capability. Curriculum never grants a facility bonus.
                self.put(p,f)
                if hasattr(self,"_ct_train_formation"):
                    self._ct_train_formation(ref,float(hours),f"formation_training:{command.semantic_digest[:24]}")
                    f=_deepcopy(self.read(p))
                develop_officer_cadre(f, training_hours=effective_hours, at=world_time); reorganize_officer_cadre(f, at=world_time, reason="post_training_officer_review"); sync_materialized_officer_billets(self, f)
            elif t=="formation_mobilize":
                if bool(f.get("mobilized",False)): raise ValueError("formation is already mobilized")
                world_time,time_metrics=self._advance_seconds(4*3600); f["mobilized"]=True; f["status"]="mobilized"; f["mobilized_at"]=world_time
            elif t=="formation_demobilize":
                if not bool(f.get("mobilized",False)): raise ValueError("formation is already demobilized")
                world_time,time_metrics=self._advance_seconds(2*3600); f["mobilized"]=False; f["status"]="ready"; f["demobilized_at"]=world_time
            elif t=="formation_doctrine_set":
                world_time=str(self._world_time()); f["doctrine_ref"]=str(payload.get("doctrine_ref")); f["doctrine_behavior"]=doctrine_behavior(self.read, f, explicit=payload.get("doctrine_behavior") if isinstance(payload.get("doctrine_behavior"), Mapping) else None); f["doctrine_last_reformed_at"]=world_time
            elif t=="formation_training_set":
                world_time=str(self._world_time()); f["training_ref"]=payload.get("training_ref"); f["training_program_last_changed_at"]=world_time
            elif t in {"formation_assign","force_assignment","command_assign","command_transfer"}:
                commander_ref=payload.get("commander_ref",f.get("commander_ref")); command_authority=str(payload.get("command_authority",f.get("command_authority")))
                if command.actor_id!=self.INTERNAL_ACTOR and command_authority not in {command.actor_id,str(f.get("administrative_owner"))}: raise PermissionError("player may not forge a new command authority")
                old_commander=f.get("commander_ref")
                if commander_ref:
                    cp,commander=self._validate_person_location_for_formation(str(commander_ref),f)
                    self._bind_formation_commander_sheet(str(commander_ref), ref, f, person_path=cp, person=commander)
                    self._assign_commander_index(str(commander_ref),ref)
                if old_commander and old_commander!=commander_ref:
                    self._release_commander_index(str(old_commander),ref)
                    self._unbind_formation_commander_sheet(str(old_commander),ref)
                f["command_authority"]=command_authority; f["commander_ref"]=commander_ref; world_time,time_metrics=self._advance_seconds(3600); f["command_last_changed_at"]=world_time
            elif t=="formation_move":
                if not bool(f.get("mobilized",False)): raise ValueError("formation movement requires mobilization")
                move_duties=self._apply_unit_duties([ref], "march", context_ref=f"formation_move:{command.semantic_digest[:24]}", at=str(self._world_time()))
                if move_duties:
                    f=_deepcopy(self.read(p))
                dest=str(payload["destination_ref"]); origin=str(f["location_ref"])
                if hasattr(self,"_validate_formation_transit"):
                    self._validate_formation_transit(f,dest,str(self._world_time()))
                route=self._find_route(origin,dest,mode="formation"); movement=formation_movement_profile(self.read,f,route); hours=int(movement.get("tail_arrival_hours",route.get("duration_hours",route.get("hours",24)))); f["last_route_refs"]=list(route.get("route_refs",[])); f["last_route_path"]=list(route.get("path",[]));
                commander_ref=f.get("commander_ref"); commander_path=None; commander=None
                current=self._world_time(); fatigue_rules=self.read(FATIGUE_RULES_PATH); settle_formation_idle_fatigue(f,current=current,rules=fatigue_rules)
                if commander_ref:
                    commander_path,commander=self._validate_person_location_for_formation(str(commander_ref),f); settle_person_idle_fatigue(commander,current=current,rules=fatigue_rules,state="ordinary")
                world_time=str(current.add_seconds(hours*3600)); time_metrics=self._advance_runtime(world_time); f["location_ref"]=dest; self._index_formation_location(ref,origin,dest); stamp_formation_activity_fatigue(f,completed_at=CampaignTime.parse(world_time),fatigue_gain=max(1,hours//12),activity_kind="march"); f["last_moved_at"]=world_time; ready_at=str(current.add_seconds(int(movement.get("battle_ready_hours",hours)*3600))); f["operational_movement"]={**movement,"origin_ref":origin,"destination_ref":dest,"departed_at":str(current),"tail_arrived_at":world_time,"deployment_ready_at":ready_at}; f["status"]="ready" if CampaignTime.parse(ready_at)<=CampaignTime.parse(world_time) else "arrived_forming"
                if commander is not None and commander_path is not None: self._set_person_location(commander,dest); stamp_person_activity_fatigue(commander,completed_at=CampaignTime.parse(world_time),fatigue_gain=max(1,hours//12),activity_kind="march"); self.put(commander_path,commander)
            elif t=="resupply":
                dp,depot=self._material_depot(f)
                if depot.get("location_ref") and depot.get("location_ref")!=f.get("location_ref"): raise ValueError("resupply requires physical depot access")
                requests={"war_arrows":int(payload.get("war_arrows",0)),"war_bolts":int(payload.get("war_bolts",0)),"construction_material_units":int(payload.get("construction_material_units",0))}; mapkey={"war_arrows":"war_arrows","war_bolts":"war_bolts","construction_material_units":"construction_material_units"}
                remount_horses=max(0,int(payload.get("remount_horses",0) or 0))
                for k,n in requests.items():
                    available=int(depot.get("stocks",{}).get(mapkey[k],0))
                    if n > available:
                        raise ValueError(f"depot lacks exact requested {k}: requested {n}, available {available}")
                available_remounts=max(0,int((depot.get("mounts",{}) if isinstance(depot.get("mounts"),Mapping) else {}).get("horse",0) or 0))
                if remount_horses > available_remounts:
                    raise ValueError(f"depot lacks exact requested remount_horses: requested {remount_horses}, available {available_remounts}")
                transferred=sum(requests.values())+remount_horses
                if transferred<=0: raise ValueError("resupply requires at least one positive material quantity")
                for k,n in requests.items():
                    if n<=0: continue
                    depot.setdefault("stocks",{})[mapkey[k]]=int(depot.get("stocks",{}).get(mapkey[k],0))-n; f.setdefault("logistics",{})[k]=int(f.get("logistics",{}).get(k,0))+n
                if remount_horses>0:
                    depot.setdefault("mounts",{})["horse"]=available_remounts-remount_horses
                    f.setdefault("logistics",{})["remount_horses"]=max(0,int(f.get("logistics",{}).get("remount_horses",0) or 0))+remount_horses
                world_time,time_metrics=self._advance_seconds(max(3600,min(12*3600,int(math.ceil(transferred/5000.0))*3600))); f["last_resupplied_at"]=world_time; self.put(dp,depot)
            self.put(p,f); self._write_meta(command,world_time); result=self._result(formation_ref=ref,status=f.get("status"),world_time=world_time or str(self._world_time())); result.update(time_metrics); return result
        if t in {"formation_split","formation_merge","formation_dissolve"}:
            if t=="formation_split":
                ref=str(payload["formation_ref"]); p,f0=self._load_formation(ref); f=_deepcopy(f0); normalize_formation_establishment(f); original=_deepcopy(f); new_ref=str(payload["new_formation_ref"]); n=int(payload["personnel"]); 
                if n<=0 or n>=int(f["personnel"]): raise ValueError("invalid split personnel")
                total=int(original["personnel"]); parent_current=total-n; original_authorized=int(original.get("authorized_strength",total)); child_authorized=n if n<500 else int(math.ceil(n/100.0))*100; parent_authorized=original_authorized-child_authorized; child_class="unit" if child_authorized>=500 else "detachment"; parent_class="unit" if parent_authorized>=500 else "detachment"; validate_establishment(personnel=n,authorized_strength=child_authorized,formation_class=child_class); validate_establishment(personnel=parent_current,authorized_strength=parent_authorized,formation_class=parent_class); f["personnel"]=parent_current; f["authorized_strength"]=parent_authorized; f["formation_class"]=parent_class; new=_deepcopy(original); new["formation_ref"]=new_ref; new["name"]=str(payload.get("name",new_ref)); new["personnel"]=n; new["authorized_strength"]=child_authorized; new["formation_class"]=child_class; new["commander_ref"]=None; new["status"]="detached_pending_commander"
                for field in ("embedded_person_refs","internal_person_refs"):
                    if field in new: new[field]=[]
                for field in ("attached_unit_command_by_role","attached_support_by_role"):
                    if field in new: new[field]={}
                new.pop("command_attachment_source_force_ref",None); new.pop("command_structure",None)
                saved_est=original.get("establishment_composition") if isinstance(original.get("establishment_composition"),Mapping) else None; establishment={str(k):max(0,int(v)) for k,v in (saved_est or represented_establishment_composition(original)).items() if max(0,int(v))>0}; est_total=sum(establishment.values());
                if est_total!=original_authorized: establishment=establishment_composition(establishment,original_authorized); est_total=sum(establishment.values())
                if est_total!=original_authorized: raise ValueError("formation split could not resolve exact fighting establishment composition")
                parent_est,child_est=self._partition_counts(establishment,child_authorized,original_authorized); f["establishment_composition"]=parent_est; new["establishment_composition"]=child_est
                f["logistics"],new["logistics"]=self._partition_material(original.get("logistics",{}),n,total); f["mounts"],new["mounts"]=self._partition_material(original.get("mounts",{}),n,total)
                np=f"state/formations/{new_ref.replace('formation_','').replace('_','-')}.json"; fp=self.owner_path(f["owner_force_ref"]); force=self._ct_force(fp) if hasattr(self,"_ct_force") else _deepcopy(self.read(fp)); ensure_formation_composition(force,f,at=str(self._world_time())) if hasattr(self,"_ct_force") else None
                if hasattr(self,"_ct_force"):
                    new["cohort_composition"]=[]; parent_comp,child_comp=partition_formation_slices(force,f,new,n)
                else:
                    parent_comp,child_comp=self._partition_counts(original.get("composition",{}),n,total); f["composition"]=parent_comp; new["composition"]=child_comp
                parent_eq={}; child_eq={}
                for eq_role,raw_amount in self._equipment_units(original).items():
                    amount=max(0,int(raw_amount)); role_total=max(0,int(original.get("composition",{}).get(eq_role,0))); moved=max(0,int(child_comp.get(eq_role,0)))
                    share=min(amount,moved if role_total<=0 else int(math.floor(amount*moved/max(1,role_total))))
                    child_eq[str(eq_role)]=share; parent_eq[str(eq_role)]=amount-share
                self._set_equipment_units(f,parent_eq); self._set_equipment_units(new,child_eq)
                original_shields=self._shield_units(original); parent_shields={}; child_shields={}
                for shield_role,raw_amount in original_shields.items():
                    amount=max(0,int(raw_amount)); role_total=max(0,int(original.get("composition",{}).get(shield_role,0))); moved=max(0,int(child_comp.get(shield_role,0)))
                    share=min(amount,moved if role_total<=0 else int(math.floor(amount*moved/max(1,role_total))))
                    child_shields[str(shield_role)]=share; parent_shields[str(shield_role)]=amount-share
                self._set_shield_units(f,parent_shields); self._set_shield_units(new,child_shields)
                original_armor=self._armor_units(original); parent_armor={}; child_armor={}
                for armor_role,raw_amount in original_armor.items():
                    amount=max(0,int(raw_amount)); role_total=max(0,int(original.get("composition",{}).get(armor_role,0))); moved=max(0,int(child_comp.get(armor_role,0)))
                    share=min(amount,moved if role_total<=0 else int(math.floor(amount*moved/max(1,role_total))))
                    child_armor[str(armor_role)]=share; parent_armor[str(armor_role)]=amount-share
                self._set_armor_units(f,parent_armor); self._set_armor_units(new,child_armor)
                partition_officer_cadre(f, new, child_personnel=n, total_personnel=total); normalize_formation_establishment(f); normalize_formation_establishment(new)
                sync_materialized_officer_billets(self, f); sync_materialized_officer_billets(self, new)
                force["allocated_to_formations"][ref]=self._formation_allocation_record(f); force["allocated_to_formations"][new_ref]=self._formation_allocation_record(new)
                if hasattr(self,"_ct_force"): validate_cohort_ledger(force)
                self.put(fp,force); self.put(p,f); self.put(np,new); self._register_owner(new_ref,np); self._index_formation_location(new_ref,None,str(new.get("location_ref"))); world_time,metrics=self._advance_seconds(max(3600,int(math.ceil(n/1000.0))*3600)); self._write_meta(command,world_time); return self._result(formation_ref=ref,new_formation_ref=new_ref,world_time=world_time,**metrics)
            refs=list(payload.get("formation_refs",[]));
            if t=="formation_merge":
                if len(refs)<2: raise ValueError("merge requires at least two formations")
                primary=refs[0]; pp,pf0=self._load_formation(primary); pf=_deepcopy(pf0); normalize_formation_establishment(pf); fp=self.owner_path(pf["owner_force_ref"]); force=self._ct_force(fp) if hasattr(self,"_ct_force") else _deepcopy(self.read(fp));
                if hasattr(self,"_ct_force"): ensure_formation_composition(force,pf,at=str(self._world_time()))
                members=[pf]; adopted_commander=pf.get("commander_ref")
                for ref in refs[1:]:
                    p,f=self._load_formation(ref)
                    if f.get("owner_force_ref")!=pf.get("owner_force_ref"): raise ValueError("merge requires one conserved owner force")
                    if f.get("location_ref")!=pf.get("location_ref"): raise ValueError("merge requires co-located formations")
                    secondary_commander=f.get("commander_ref")
                    if adopted_commander is None and secondary_commander:
                        adopted_commander=secondary_commander; pf["commander_ref"]=secondary_commander; self._release_commander_index(str(secondary_commander),ref); self._assign_commander_index(str(secondary_commander),primary)
                    elif secondary_commander:
                        self._release_commander_index(str(secondary_commander),ref)
                    member=_deepcopy(f); normalize_formation_establishment(member)
                    if hasattr(self,"_ct_force"): ensure_formation_composition(force,member,at=str(self._world_time()))
                    release_external_formation_allocations(force,formation_ref=str(ref),location_ref=str(member.get("location_ref"))); members.append(member); self.delete(p); self._unregister_owner(ref); self._index_formation_location(str(ref),str(f.get("location_ref")),None); force["allocated_to_formations"].pop(ref,None)
                total=sum(int(x["personnel"]) for x in members); merged_authorized=sum(int(x.get("authorized_strength",x.get("personnel",0))) for x in members); merged_class="unit" if merged_authorized>=500 else "detachment"; validate_establishment(personnel=total,authorized_strength=merged_authorized,formation_class=merged_class); establishment_rows=[]
                for member in members:
                    member_authorized=int(member.get("authorized_strength",member.get("personnel",0))); raw=member.get("establishment_composition") if isinstance(member.get("establishment_composition"),Mapping) else represented_establishment_composition(member); normalized={str(k):max(0,int(v)) for k,v in raw.items() if max(0,int(v))>0}; establishment_rows.append(normalized if sum(normalized.values())==member_authorized else establishment_composition(normalized,member_authorized))
                pf["personnel"]=total; pf["authorized_strength"]=merged_authorized; pf["formation_class"]=merged_class; pf["composition"]=self._merge_material(*(x.get("composition",{}) for x in members)); pf["establishment_composition"]=self._merge_material(*establishment_rows); pf["logistics"]=self._merge_material(*(x.get("logistics",{}) for x in members)); pf["mounts"]=self._merge_material(*(x.get("mounts",{}) for x in members)); self._set_equipment_units(pf,self._merge_material(*(self._equipment_units(x) for x in members))); self._set_shield_units(pf,self._merge_material(*(self._shield_units(x) for x in members))); self._set_armor_units(pf,self._merge_material(*(self._armor_units(x) for x in members)))
                for field in ("readiness","morale","cohesion","fatigue","training_progress"):
                    pf[field]=_clamp(int(round(sum(int(x.get(field,0))*int(x["personnel"]) for x in members)/max(1,total))))
                merge_officer_cadres(pf, members[1:]); sync_materialized_officer_billets(self, pf); normalize_formation_establishment(pf)
                force["allocated_to_formations"][primary]={"personnel":total,"composition":_deepcopy(pf["composition"])}
                if hasattr(self,"_ct_force"):
                    merge_formation_slices(force,pf,members[1:]); validate_cohort_ledger(force)
                self.put(pp,pf); self.put(fp,force); world_time,metrics=self._advance_seconds(max(3600,int(math.ceil(total/2000.0))*3600)); self._write_meta(command,world_time); return self._result(formation_ref=primary,personnel=total,world_time=world_time,**metrics)
            ref=str(payload.get("formation_ref",refs[0] if refs else "")); p,f0=self._load_formation(ref); f=_deepcopy(f0); fp=self.owner_path(f["owner_force_ref"]); force=self._ct_force(fp) if hasattr(self,"_ct_force") else _deepcopy(self.read(fp)); location=str(f.get("location_ref"))
            if hasattr(self,"_ct_force"): ensure_formation_composition(force,f,at=str(self._world_time()))
            for role,count in f.get("composition",{}).items(): self._return_force_personnel(force,str(role),int(count),location)
            for role,count in self._equipment_units(f).items(): self._return_force_equipment(force,str(role),int(count),location)
            force["allocated_to_formations"].pop(ref,None)
            if hasattr(self,"_ct_force"):
                return_formation_slices(force,f)
            release_external_formation_allocations(force,formation_ref=ref,location_ref=location)
            if hasattr(self,"_ct_force"): validate_cohort_ledger(force)
            self.put(fp,force); self._return_formation_materials(f); self._release_commander_index(f.get("commander_ref"),ref); self.delete(p); self._unregister_owner(ref); self._index_formation_location(ref,location,None); world_time,metrics=self._advance_seconds(max(3600,int(math.ceil(int(f.get("personnel",0))/1000.0))*3600)); self._write_meta(command,world_time); return self._result(dissolved=ref,location_ref=location,world_time=world_time,**metrics)
        if t=="battle_resolve":
            result=self._battle(command,payload); self._write_meta(command,str(result["world_time"])); return self._result(**result)
        if t=="battlefield_control":
            result=self._battlefield_control(command,payload); self._write_meta(command,str(result["world_time"])); return self._result(**result)
        if t=="recover_projectiles":
            player=_deepcopy(self.read("state/player.json")); loc=self._person_location(player)
            if not loc: raise ValueError("projectile recovery requires an exact current player location")
            state=player.setdefault("combat_state",{}); field=state.get("field_projectiles",[])
            if not isinstance(field,list): field=[]
            item_filter=str(payload.get("projectile_item_id", ""))
            eligible=[]
            for i,row in enumerate(field):
                if not isinstance(row,Mapping) or str(row.get("location_ref"))!=str(loc) or max(0,int(row.get("quantity",0)))<=0: continue
                if item_filter and str(row.get("projectile_item_id"))!=item_filter: continue
                eligible.append((i,row))
            if not eligible: raise ValueError("no recoverable personal projectiles are present at the player's exact current location")
            minutes=int(payload.get("minutes",1)); rules=self.read("game/data/mechanics/combat.json").get("projectile_recovery_model",{})
            seconds_per=max(3.0,float(rules.get("search_seconds_per_projectile",12.0) or 12.0)) if isinstance(rules,Mapping) else 12.0
            capacity=max(1,int((minutes*60)//seconds_per)); remaining=capacity; recovered: dict[str,int]={}
            mutable=[dict(x) if isinstance(x,Mapping) else x for x in field]
            for i,row in eligible:
                if remaining<=0: break
                take=min(remaining,max(0,int(row.get("quantity",0)))); item_id=str(row.get("projectile_item_id"));
                if take<=0 or not item_id: continue
                mutable[i]["quantity"]=max(0,int(mutable[i].get("quantity",0))-take); remaining-=take; recovered[item_id]=recovered.get(item_id,0)+take
            mutable=[row for row in mutable if not isinstance(row,Mapping) or max(0,int(row.get("quantity",0)))>0]
            state["field_projectiles"]=mutable
            ammo=state.setdefault("projectile_ammunition",{})
            mp,manifest=self._player_manifest()
            for item_id,count in recovered.items():
                ammo[item_id]=max(0,int(ammo.get(item_id,0)))+count
                entry=next((e for e in manifest.get("equipment_manifest",[]) if isinstance(e,dict) and str(e.get("item_id"))==item_id),None)
                if isinstance(entry,dict): entry["quantity"]=max(0,int(entry.get("quantity",0)))+count
                else: manifest.setdefault("equipment_manifest",[]).append({"item_id":item_id,"quantity":count,"custody":"Tang Wei player equipment","current_state":"quivered/readied after recovery from prior personal combat site"})
            self.put(mp,manifest); self.put("state/player.json",player)
            world_time,metrics=self._advance_seconds(minutes*60); self._write_meta(command,world_time)
            return self._result(recovered_by_item=recovered,recovered_total=sum(recovered.values()),search_minutes=minutes,location_ref=loc,remaining_recovery_candidates=sum(max(0,int(row.get("quantity",0))) for row in mutable if isinstance(row,Mapping) and str(row.get("location_ref"))==str(loc)),world_time=world_time,**metrics)
        if t=="personal_combat":
            player=_deepcopy(self.read("state/player.json"))
            opponent_refs=[str(x) for x in payload.get("opponent_refs",[]) if str(x)]
            if payload.get("opponent_ref"):
                legacy=str(payload["opponent_ref"])
                if legacy not in opponent_refs: opponent_refs.insert(0,legacy)
            if not opponent_refs: raise ValueError("personal combat requires at least one exact opponent")
            ally_refs=[str(x) for x in payload.get("ally_refs",[]) if str(x)]
            if len(set(opponent_refs+ally_refs+[self.PLAYER_ACTOR]))!=len(opponent_refs)+len(ally_refs)+1:
                raise ValueError("personal combat participant refs must be unique and exclude the player")
            if len(opponent_refs)+len(ally_refs)+1>32: raise ValueError("personal combat exact scene is bounded to 32 participants")
            participant_people: dict[str,dict[str,Any]]={}
            participant_paths: dict[str,str]={}
            for participant_ref in opponent_refs+ally_refs:
                path,person0=self.owner(participant_ref); person=_deepcopy(person0)
                if person.get("schema") not in {"sab_character","sword-materialized-person","person-lite"}: raise ValueError("personal combat participant is not an individually represented saved person")
                if str(person.get("life_status",person.get("status","active"))).lower() in {"dead","deceased"}: raise ValueError("personal combat participant is not active")
                participant_people[participant_ref]=person; participant_paths[participant_ref]=path
            opponent_ref=opponent_refs[0]; opponent=participant_people[opponent_ref]
            player_loc=self._person_location(player)
            participant_locations={ref:self._person_location(person) for ref,person in participant_people.items()}
            if not player_loc or any(not loc or loc!=player_loc for loc in participant_locations.values()):
                raise ValueError("personal combat requires exact co-location of all saved participants")
            # A wound is a combat state, not a magical prohibition on further
            # fighting.  Exact injured people may continue if they are conscious
            # and physically active; the personal resolver applies their saved
            # wound/anatomy penalties.  Only terminal/incapacitated state blocks
            # another combat slice.
            for who, person in [("player",player)]+[(ref,participant_people[ref]) for ref in opponent_refs+ally_refs]:
                health = self._person_health(person).lower()
                life = str(person.get("life_status", person.get("status", "active"))).lower()
                combat_state = person.get("combat_state") if isinstance(person.get("combat_state"), Mapping) else {}
                if life in {"dead", "deceased"} or health in {"dead", "deceased", "incapacitated"} or bool(combat_state.get("incapacitated")):
                    raise ValueError(f"{who} is not physically active enough for personal combat")
            minutes=int(payload.get("duration_minutes",60))
            if minutes<1 or minutes>240: raise ValueError("personal combat duration must be between 1 and 240 minutes")
            objective=str(payload.get("objective","combat"))
            environment=self._environment_snapshot(player_loc) if hasattr(self,"_environment_snapshot") else None
            resolution=self._personal_combat_slice(
                command,payload,player,opponent_ref,opponent,environment,
                opponent_people={ref:participant_people[ref] for ref in opponent_refs},
                ally_people={ref:participant_people[ref] for ref in ally_refs},
            )
            outcome=str(resolution["outcome"]); spar=bool(resolution["spar"])

            def apply_exact_mount_loss_to_manifest(person: dict[str,Any], manifest_doc: dict[str,Any], *, location_ref: str) -> bool:
                """Persist a dead/disabled exact mount without inventing a new pool.

                Named personal-combat mounts are already in individual custody (or
                represented by the person's exact loadout).  Their casualty is
                therefore a state transition of that exact allocated horse, not a
                second debit against a formation/state remount pool.  Replacement
                later requires a real remount issue from an existing conserved
                stock authority.
                """
                mount_state=person.get("mount_combat_state") if isinstance(person.get("mount_combat_state"),Mapping) else None
                if not isinstance(mount_state,dict): return False
                status=str(mount_state.get("status","active")).lower()
                if status not in {"dead","disabled","lost"}: return False
                changed=False
                terminal_text=(f"dead horse remains at {location_ref} after personal combat" if status=="dead" else f"combat-disabled horse at {location_ref} after personal combat")
                rows=manifest_doc.get("equipment_manifest",[]) if isinstance(manifest_doc.get("equipment_manifest"),list) else []
                for entry in rows:
                    if not isinstance(entry,dict): continue
                    iid=str(entry.get("item_id",""))
                    if iid=="horse" and any(token in str(entry.get("current_state","")).lower() for token in ("mounted","equipped","readied")):
                        entry["current_state"]=terminal_text; changed=True
                    elif iid in {"horse_armor_heavy","tack_standard"} and "mounted horse" in str(entry.get("current_state","")).lower():
                        entry["current_state"]=(f"left with dead horse at {location_ref}" if status=="dead" else f"removed from combat-disabled horse at {location_ref}"); changed=True
                compact=person.get("current_equipment_state") if isinstance(person.get("current_equipment_state"),Mapping) else None
                if isinstance(compact,dict):
                    compact["mounted"]=False
                    compact["mount_location"]=location_ref
                mount_state["service_loss_pending"]=False
                mount_state["service_loss_recorded"]=True
                return changed

            # Equipment wear is contact-causal. Only the item that actually
            # blocked, parried, struck armor, or otherwise carried the impact
            # loses condition; there is no blanket per-fight durability tax.
            mp,manifest=self._player_manifest()
            disarmed_ref=(resolution.get("end_state") or {}).get("disarmed_ref") if isinstance(resolution.get("end_state"),Mapping) else None
            player_disarmed=(resolution.get("player_equipment") or {}).get("best_weapon") if disarmed_ref==self.PLAYER_ACTOR else None
            condition_changes=resolution.get("equipment_condition_changes",{}) if isinstance(resolution.get("equipment_condition_changes"),Mapping) else {}
            player_changes=condition_changes.get(self.PLAYER_ACTOR,{}) if isinstance(condition_changes.get(self.PLAYER_ACTOR),Mapping) else {}
            for entry in manifest.get("equipment_manifest",[]):
                iid=str(entry.get("item_id", ""))
                change=player_changes.get(iid) if iid else None
                if isinstance(change,Mapping):
                    entry["condition_pct"]=max(0,min(100,int(round(float(change.get("after_condition_pct",entry.get("condition_pct",100)))))))
                    if entry["condition_pct"]==0:
                        entry["current_state"]="broken/unserviceable in player custody"
                if player_disarmed and iid==str(player_disarmed):
                    entry["current_state"]=f"dropped at {player_loc} during personal combat"
            apply_exact_mount_loss_to_manifest(player,manifest,location_ref=str(player_loc))
            # Personal projectile ammunition is exact carried custody. Keep the
            # player's equipped/quivered manifest quantity synchronized with the
            # resolver's saved carried-ammunition state so arrows/bolts cannot
            # reappear in the next fight after being fired.
            player_ammo=player.get("combat_state",{}).get("projectile_ammunition",{}) if isinstance(player.get("combat_state"),Mapping) else {}
            if isinstance(player_ammo,Mapping):
                for ammo_id,raw_count in player_ammo.items():
                    count=max(0,int(raw_count or 0)); matches=[e for e in manifest.get("equipment_manifest",[]) if isinstance(e,dict) and str(e.get("item_id"))==str(ammo_id) and any(token in str(e.get("current_state","")).lower() for token in ("equipped","readied","quivered"))]
                    if matches:
                        matches[0]["quantity"]=count
                        for extra in matches[1:]: extra["quantity"]=0
                    elif count>0:
                        manifest.setdefault("equipment_manifest",[]).append({"item_id":str(ammo_id),"quantity":count,"custody":"Tang Wei player equipment","current_state":"quivered/readied on person"})
                manifest["equipment_manifest"]=[e for e in manifest.get("equipment_manifest",[]) if not isinstance(e,Mapping) or int(e.get("quantity",0) or 0)>0]
            self.put(mp,manifest)

            current=CampaignTime.parse(self.read("state/runtime.json")["world_time"])
            elapsed=max(1,int(math.ceil(float(resolution.get("elapsed_seconds",minutes*60)))))
            target=current.add_seconds(elapsed).__str__()
            metrics=self._advance_runtime(target)
            player_dead=str(player.get("life_status",player.get("status","active"))).lower() in {"dead","deceased"}
            if player_dead:
                self._settle_person_death(self.PLAYER_ACTOR,"state/player.json",player,target,str(player.get("death_reason") or "personal combat fatality"))
            else:
                self.put("state/player.json",player)
            for participant_ref,person in participant_people.items():
                # Exact non-player combatants may own their own equipment manifest.
                # Synchronize only carried projectile entries; stored inventory is
                # a separate custody state and is not consumed by the combat slice.
                ammo_state=person.get("combat_state",{}).get("projectile_ammunition",{}) if isinstance(person.get("combat_state"),Mapping) else {}
                manifest_path=person.get("equipment_manifest_ref")
                if isinstance(manifest_path,str) and manifest_path:
                    manifest0=self.read_optional(manifest_path)
                    if isinstance(manifest0,Mapping):
                        pm=_deepcopy(manifest0); changed=False
                        if isinstance(ammo_state,Mapping):
                            for ammo_id,raw_count in ammo_state.items():
                                matches=[e for e in pm.get("equipment_manifest",[]) if isinstance(e,dict) and str(e.get("item_id"))==str(ammo_id) and any(token in str(e.get("current_state","")).lower() for token in ("equipped","readied","quivered"))]
                                if matches:
                                    matches[0]["quantity"]=max(0,int(raw_count or 0)); changed=True
                                    for extra in matches[1:]: extra["quantity"]=0
                        if apply_exact_mount_loss_to_manifest(person,pm,location_ref=str(player_loc)):
                            changed=True
                        if changed:
                            pm["equipment_manifest"]=[e for e in pm.get("equipment_manifest",[]) if not isinstance(e,Mapping) or int(e.get("quantity",0) or 0)>0]; self.put(manifest_path,pm)
                else:
                    # Embedded/static individual loadouts have no separate
                    # manifest file. The exact person's mount_combat_state is the
                    # persistent casualty authority and suppresses that role
                    # loadout until a future remount operation explicitly clears
                    # it.
                    mount_state=person.get("mount_combat_state") if isinstance(person.get("mount_combat_state"),Mapping) else None
                    if isinstance(mount_state,dict) and str(mount_state.get("status","active")).lower() in {"dead","disabled","lost"}:
                        mount_state["service_loss_pending"]=False; mount_state["service_loss_recorded"]=True
                participant_dead=str(person.get("life_status",person.get("status","active"))).lower() in {"dead","deceased"}
                if participant_dead:
                    self._settle_person_death(participant_ref,participant_paths[participant_ref],person,target,str(person.get("death_reason") or "personal combat fatality"),settle_force_body=True)
                else:
                    self.put(participant_paths[participant_ref],person)

            hist=_deepcopy(self.read("state/history/events/index.json"))
            eid="personal_combat_"+hashlib.sha256((str(current)+":"+self.PLAYER_ACTOR+":"+",".join(sorted(opponent_refs))+":"+",".join(sorted(ally_refs))+":"+objective).encode()).hexdigest()[:16]
            recovery_rows=resolution.get("projectile_recovery_candidates",[]) if isinstance(resolution.get("projectile_recovery_candidates"),list) else []
            field_counts: dict[str,int]={}
            for row in recovery_rows:
                if not isinstance(row,Mapping) or str(row.get("actor_ref"))!=self.PLAYER_ACTOR: continue
                item_id=str(row.get("projectile_item_id", "")); fraction=max(0.0,min(.95,float(row.get("recoverable_fraction",0) or 0)))
                if not item_id or fraction<=0: continue
                token=(eid+"|"+str(row.get("release_event_id", ""))+"|"+item_id).encode()
                roll=(int(hashlib.sha256(token).hexdigest()[:8],16)%1000000)/1000000.0
                if roll < fraction: field_counts[item_id]=field_counts.get(item_id,0)+1
            if field_counts:
                field=player.setdefault("combat_state",{}).setdefault("field_projectiles",[])
                for item_id,count in sorted(field_counts.items()):
                    existing=next((x for x in field if isinstance(x,dict) and str(x.get("projectile_item_id"))==item_id and str(x.get("location_ref"))==str(player_loc)),None)
                    if isinstance(existing,dict):
                        existing["quantity"]=max(0,int(existing.get("quantity",0)))+count; existing["last_source_combat_ref"]=eid; existing["last_deposited_at"]=target
                    else:
                        field.append({"projectile_item_id":item_id,"quantity":count,"location_ref":player_loc,"source_combat_ref":eid,"deposited_at":target,"status":"recoverable_in_field"})
                self.put("state/player.json",player)
            hist_event={
                "event_id":eid,"kind":"personal_combat","at":str(current),"completed_at":target,
                "actor_ref":self.PLAYER_ACTOR,"opponent_ref":opponent_ref,"opponent_refs":opponent_refs,"ally_refs":ally_refs,"location_ref":player_loc,
                "objective":objective,"spar":spar,"outcome":outcome,
                "start_state":resolution.get("start_state"),
                "causal_trace":resolution.get("causal_trace",[]),
                "end_state":resolution.get("end_state"),
                "decision_boundary":resolution.get("decision_boundary"),
                "narration_contract":resolution.get("narration_contract"),
                "player_equipment":resolution.get("player_equipment"),
                "opponent_equipment":resolution.get("opponent_equipment"),
                "equipment_condition_changes":resolution.get("equipment_condition_changes",{}),
                "mount_wounds":resolution.get("mount_wounds",[]),
                "elapsed_seconds":elapsed,
                "environment":({key:environment.get(key) for key in ("weather_block_ref","condition","light","visibility","ground")} if isinstance(environment,Mapping) else None),
            }
            hist.setdefault("events",[]).append(hist_event); write_history_index(self,hist)
            if outcome in {"win","loss"}:
                for hostile_ref in opponent_refs:
                    self._record_reputation_signal(self.PLAYER_ACTOR,hostile_ref,1 if outcome=="win" else -1,"personal_combat",eid,target,"direct witness to the exact encounter")
            if not spar and outcome=="win": self._award_career_merit(self.PLAYER_ACTOR,1,eid,target)
            self._write_meta(command,target)
            public_resolution={k:v for k,v in resolution.items() if k!="spar"}
            return self._result(
                **public_resolution,scale="exact_personal",opponent_ref=opponent_ref,opponent_refs=opponent_refs,ally_refs=ally_refs,location_ref=player_loc,
                duration_minutes=(elapsed/60.0),world_time=target,score_scale=100,
                environment=({key:environment.get(key) for key in ("weather_block_ref","condition","light","visibility","ground","mechanical_effects")} if isinstance(environment,Mapping) else None),
                **metrics,
            )
        if t in {"operation_create","operation_transition"}:
            idxp="state/operations/index.json"; idx=_deepcopy(self.read(idxp))
            if t=="operation_create":
                ref=str(payload["operation_ref"]); formation_refs=[str(x) for x in payload.get("formation_refs",[])]; forms=[self._load_formation(x)[1] for x in formation_refs]
                if idx.get("operations",{}).get(ref): raise ValueError("operation_ref already exists")
                authorities={str(f.get("administrative_owner")) for f in forms if f.get("administrative_owner")}
                # A battle/contact operation may legitimately contain opposing formations.
                # Gameplay authorization is enforced before this reducer; internal autonomy
                # may create a contested operation spanning multiple administrative owners.
                path=f"state/operations/{ref}.json"; now=str(self._world_time()); doc={"schema":"sword-operation","owner_id":ref,"operation_ref":ref,"objective":str(payload.get("objective","operation")),"status":"planned","location_ref":payload.get("location_ref"),"formation_refs":formation_refs,"administrative_authorities":sorted(authorities),"administrative_authority":next(iter(authorities)) if len(authorities)==1 else None,"contested":len(authorities)>1,"created_at":now}; self.put(path,doc); idx.setdefault("operations",{})[ref]=path; self.put(idxp,idx); self._register_owner(ref,path); world_time,metrics=self._advance_seconds(2*3600); self._write_meta(command,world_time); return self._result(operation_ref=ref,status="planned",world_time=world_time,**metrics)
            ref=str(payload["operation_ref"]); path=idx.get("operations",{}).get(ref)
            if not path: raise ValueError("unknown operation")
            doc=_deepcopy(self.read(path)); status=str(payload["status"]); old=str(doc.get("status","planned")); legal={"planned":{"mobilizing","cancelled"},"mobilizing":{"active","cancelled"},"active":{"engaged","occupied","completed","cancelled"},"engaged":{"active","occupied","completed","cancelled"},"occupied":{"completed","cancelled"},"completed":set(),"cancelled":set()}
            if status==old: raise ValueError("operation transition must change state")
            if status not in legal.get(old,set()): raise ValueError(f"illegal operation transition: {old} -> {status}")
            refs=[str(x) for x in doc.get("formation_refs",[])]
            if status in {"active","engaged","occupied"}:
                if not refs: raise ValueError("active operation requires exact participating formations")
                forms=[self._load_formation(x)[1] for x in refs]; locations={str(x.get("location_ref")) for x in forms}
                if len(locations)!=1 or next(iter(locations))!=doc.get("location_ref"): raise ValueError("active operation requires all formations at the exact operation location")
                if any(not bool(x.get("mobilized",False)) for x in forms): raise ValueError("active operation requires mobilized formations")
                if status=="occupied":
                    surviving=[x for x in forms if int(x.get("personnel",0))>0]
                    if not surviving: raise ValueError("occupation requires a surviving formation at the site")
                    authorities={str(x.get("administrative_owner")) for x in surviving}
                    if len(authorities)!=1: raise ValueError("occupation requires one exact controlling authority")
                    doc["occupation_authority"]=next(iter(authorities)); doc["occupied_at"]=str(self._world_time())
            duration_hours={"mobilizing":2,"active":1,"engaged":1,"occupied":6,"completed":1,"cancelled":1}[status]; now=str(self._world_time()); doc["status"]=status; doc["updated_at"]=now; self.put(path,doc)
            duty_phase={"mobilizing":"camp","active":"camp","engaged":"battle","occupied":"camp"}.get(status)
            if duty_phase:
                doc["unit_duties"] = self._apply_unit_duties(refs, duty_phase, context_ref=ref, at=now)
                self.put(path,doc)
            after_action_review=None
            if status in {"completed","cancelled"}:
                idx.setdefault("operations",{}).pop(ref,None)
                routed = idx.get("active_battlefield_operation_refs", [])
                if not isinstance(routed, list):
                    raise ValueError("active battlefield operation routing is invalid")
                idx["active_battlefield_operation_refs"] = sorted({str(x) for x in routed if isinstance(x, str) and x and x != ref})
                idx["terminal_operation_count"]=int(idx.get("terminal_operation_count",0))+1
                recent=idx.setdefault("recent_terminal_refs",[]); recent.append({"operation_ref":ref,"status":status,"at":now}); del recent[:-64]
                self.put(idxp,idx)
                from sword_runtime.campaign_closure import record_operation_after_action
                after_action_review=record_operation_after_action(self,ref,at=now)
            world_time,metrics=self._advance_seconds(duration_hours*3600); self._write_meta(command,world_time); return self._result(operation_ref=ref,status=doc["status"],after_action_review=after_action_review,world_time=world_time,**metrics)
        if t in {"information_create","information_deliver"}:
            idxp="state/information/index.json"; idx=_deepcopy(self.read(idxp))
            if t=="information_create":
                ref=str(payload["information_ref"]); path=f"state/information/{ref}.json"
                if self.read_optional(path) is not None: raise ValueError("information_ref already exists")
                claim=str(payload.get("claim",payload.get("fact",""))); knowers=[str(x) for x in payload.get("knowers",[])]; confidence=max(0,min(1000,int(payload.get("confidence_milli",round(float(payload.get("confidence",1.0))*1000))))); now=str(self._world_time()); holder_states={knower:{"epistemic_kind":str(payload.get("epistemic_kind","observation")),"confidence_milli":confidence,"source_ref":str(payload.get("provenance","runtime")),"learned_at":now} for knower in knowers}; doc={"schema":"sword-information","owner_id":ref,"information_ref":ref,"subject_ref":str(payload.get("subject_ref") or ref),"fact":claim,"claim":claim,"epistemic_kind":str(payload.get("epistemic_kind","observation")),"confidence_milli":confidence,"confidence":f"{confidence/1000:.3f}","provenance":str(payload.get("provenance","runtime")),"evidence_refs":[str(x) for x in payload.get("evidence_refs",[])],"classification":str(payload.get("classification","ordinary")),"location_ref":payload.get("location_ref"),"discoverability_milli":max(0,min(1000,int(payload.get("discoverability_milli",500)))),"investigation_discoverable":True,"origin_authority":"runtime_established" if command.actor_id==self.INTERNAL_ACTOR else "player_assertion","world_truth_authority":False,"claim_status":"runtime_established" if command.actor_id==self.INTERNAL_ACTOR else "unverified_claim","knowers":knowers,"holder_states":holder_states,"deliveries":[],"created_at":now}; self.put(path,doc); idx.setdefault("claims",{})[ref]=path; by_holder=idx.setdefault("by_holder",{}); [by_holder.setdefault(knower,[]).append(ref) for knower in knowers if ref not in by_holder.setdefault(knower,[])]; self.put(idxp,idx); self._register_owner(ref,path); world_time,metrics=self._advance_seconds(300); self._write_meta(command,world_time); return self._result(information_ref=ref,confidence_milli=confidence,world_time=world_time,**metrics)
            ref=str(payload["information_ref"]); path=idx.get("claims",{}).get(ref)
            if not path: raise ValueError("unknown information claim")
            doc=_deepcopy(self.read(path)); target=str(payload.get("target_ref",self.PLAYER_ACTOR)); _,target_person=self._exact_person(target); sender_ref=command.actor_id if command.actor_id!=self.INTERNAL_ACTOR else str(payload.get("source_ref",doc.get("knowers",[self.PLAYER_ACTOR])[0] if doc.get("knowers") else self.PLAYER_ACTOR)); _,sender=self._exact_person(sender_ref); sender_loc=self._person_location(sender); target_loc=self._person_location(target_person)
            if sender_ref not in doc.get("knowers",[]): raise PermissionError("information may travel only from an exact saved knower")
            if not sender_loc or not target_loc: raise ValueError("information delivery requires exact sender and recipient locations")
            hours=self._route_travel_hours(sender_loc,target_loc); seconds=300 if hours==0 else hours*3600; departed=str(self._world_time()); world_time,metrics=self._advance_seconds(seconds); knowers=doc.setdefault("knowers",[])
            if target not in knowers: knowers.append(target)
            source_state=(doc.get("holder_states") or {}).get(sender_ref,{}) if isinstance(doc.get("holder_states"),dict) else {}; source_conf=int(source_state.get("confidence_milli",doc.get("confidence_milli",1000))); delivered_conf=max(0,min(1000,source_conf)); doc.setdefault("holder_states",{})[target]={"epistemic_kind":"report","confidence_milli":delivered_conf,"source_ref":sender_ref,"channel":"courier","learned_at":world_time}; delivery={"source_ref":sender_ref,"target_ref":target,"departed_at":departed,"arrived_at":world_time,"source_location_ref":sender_loc,"target_location_ref":target_loc,"channel":"courier","travel_hours":hours,"confidence_milli":delivered_conf}; doc.setdefault("deliveries",[]).append(delivery); doc["deliveries"]=doc["deliveries"][-64:]; holder_refs=idx.setdefault("by_holder",{}).setdefault(target,[]); holder_refs.append(ref) if ref not in holder_refs else None; self.put(idxp,idx); self.put(path,doc); self._write_meta(command,world_time); return self._result(information_ref=ref,delivered_to=target,confidence_milli=delivered_conf,world_time=world_time,travel_hours=hours,**metrics)
        if t in {"institution_project","project_resolve"}:
            ref=str(payload["institution_ref"]); p=self.owner_path(ref); doc=_deepcopy(self.read(p)); projects=doc.setdefault("projects",[])
            if t=="institution_project":
                project_ref=str(payload.get("project_ref","project_"+command.semantic_digest[:8]));
                if any(str(x.get("project_ref"))==project_ref and str(x.get("status")) not in {"completed","cancelled"} for x in projects): raise ValueError("active project_ref already exists")
                duration=int(payload.get("duration_hours",168)); kind=str(payload.get("kind","capacity")); magnitude=int(payload.get("magnitude",1)); current=self._world_time(); completes=str(current.add_seconds(duration*3600)); project={"project_ref":project_ref,"kind":kind,"magnitude":magnitude,"status":"active","started_at":str(current),"completes_at":completes,"effect":dict(payload.get("effect",{}))}; projects.append(project); self.put(p,doc); world_time,metrics=self._advance_seconds(3600); self._write_meta(command,world_time); return self._result(institution_ref=ref,project_ref=project_ref,completes_at=completes,world_time=world_time,**metrics)
            project_ref=str(payload["project_ref"]); project=next((x for x in projects if str(x.get("project_ref"))==project_ref),None)
            if not project: raise ValueError("unknown institution project")
            if project.get("status")!="active": raise ValueError("institution project is not active")
            if self._world_time()<CampaignTime.parse(str(project["completes_at"])): raise ValueError("institution project is not complete yet")
            kind=str(project.get("kind","capacity")); magnitude=max(1,int(project.get("magnitude",1))); effect=project.get("effect",{}) if isinstance(project.get("effect"),dict) else {}
            if kind in {"capacity","construction","expansion"}: doc["capacity"]=max(0,int(doc.get("capacity",0))+magnitude)
            elif kind in {"backlog","process"}: doc["backlog"]=max(0,int(doc.get("backlog",0))-magnitude)
            elif kind in {"stock","resource","logistics"}:
                key=str(effect.get("resource","generic_stock")); doc.setdefault("resources",{})[key]=int(doc.get("resources",{}).get(key,0))+magnitude
            else: doc.setdefault("resolved_effects",{})[kind]=int(doc.get("resolved_effects",{}).get(kind,0))+magnitude
            project["status"]="completed"; project["resolved_at"]=str(self._world_time()); self.put(p,doc); world_time,metrics=self._advance_seconds(3600); self._write_meta(command,world_time); return self._result(institution_ref=ref,project_ref=project_ref,status="completed",world_time=world_time,**metrics)
        if t=="house_action":
            ref=str(payload.get("house_ref","house_tang")); p=self.owner_path(ref); doc=_deepcopy(self.read(p)); action=str(payload.get("action","assign_duty")); now=str(self._world_time()); result={"house_ref":ref,"action":action}
            if action=="assign_duty":
                subject_ref=str(payload["subject_ref"]); duty=str(payload["duty"]); pp,person0=self._exact_person(subject_ref); person=_deepcopy(person0); assignment={"duty":duty,"house_ref":ref,"assigned_at":now,"grantor_ref":command.actor_id}; person.setdefault("career_state",{}).setdefault("appointments",[]).append(assignment); person["career_state"]["appointments"]=person["career_state"]["appointments"][-32:]; self.put(pp,person); doc.setdefault("duty_assignments",{})[subject_ref]=assignment; result.update({"subject_ref":subject_ref,"duty":duty})
            elif action=="grant_nobility":
                grantor_ref=str(payload["grantor_ref"]); evidence_ref=str(payload["evidence_ref"]); target_grade=str(payload["target_grade"]); gp,grantor=self._exact_person(grantor_ref)
                if command.actor_id!=self.INTERNAL_ACTOR and grantor_ref!=command.actor_id: raise PermissionError("House nobility grantor must be the acting authority")
                house_state=str(doc.get("state","")).lower().replace("state_",""); grantor_state=str(grantor.get("state","")).lower().replace("state_","")
                career=grantor.get("career_state",{}) if isinstance(grantor.get("career_state"),Mapping) else {}; office=str(career.get("office_or_command","")); authorities={str(x) for x in career.get("authorities",[]) if isinstance(x,str)} if isinstance(career.get("authorities"),list) else set()
                if grantor_state!=house_state or ("Sovereign / royal office" not in office and "grant_house_nobility" not in authorities): raise PermissionError("actor lacks sovereign or explicitly delegated House nobility authority")
                rules=self.read(NOBILITY_RULES_PATH); grant_ref="nobility."+hashlib.sha256((ref+":"+target_grade+":"+grantor_ref+":"+evidence_ref+":"+now).encode()).hexdigest()[:16]; prior=str(ensure_nobility_state(doc,rules).get("grade")); state=apply_nobility_grant(doc,rules,target_grade=target_grade,grantor_ref=grantor_ref,evidence_ref=evidence_ref,at=now,grant_ref=grant_ref)
                hist=_deepcopy(self.read("state/history/events/index.json")); hist.setdefault("events",[]).append({"event_id":grant_ref,"kind":"house_nobility_grant","at":now,"house_ref":ref,"prior_grade":prior,"grade":target_grade,"grantor_ref":grantor_ref,"evidence_ref":evidence_ref}); write_history_index(self,hist); result.update({"prior_grade":prior,"grade":target_grade,"grant_ref":grant_ref,"nobility":state})
            else:
                key=str(payload["policy_key"]); value=str(payload["policy_value"]); doc.setdefault("policies",{})[key]={"value":value,"set_at":now,"set_by":command.actor_id}; result.update({"policy_key":key,"policy_value":value})
            self.put(p,doc); world_time,metrics=self._advance_seconds(2*3600); self._write_meta(command,world_time); return self._result(world_time=world_time,**result,**metrics)
        if t in {"state_levy_call","state_levy_demobilize"}:
            state=self._state_key(payload.get("state","qin")); levy_ref=str(payload["levy_ref"]); now=str(self._world_time())
            if t=="state_levy_call":
                result=call_state_levy(self,state=state,personnel=int(payload["personnel"]),location_ref=str(payload["location_ref"]),role=str(payload.get("role","line_infantry")),levy_ref=levy_ref,at=now); duration=max(4,int(math.ceil(int(payload["personnel"])/5000.0))*4)
            else:
                result=demobilize_state_levy(self,state=state,levy_ref=levy_ref,at=now); duration=max(4,int(math.ceil(int(result.get("survivors_returned",0))/5000.0))*4)
            world_time,metrics=self._advance_seconds(duration*3600); self._write_meta(command,world_time); return self._result(state=state,action=t,world_time=world_time,duration_hours=duration,**result,**metrics)
        if t=="state_action":
            state=self._state_key(payload.get("state","qin")); p=f"state/states/{state}.json"; doc=_deepcopy(self.read(p)); action=str(payload.get("action","strategic_goal"));
            if action=="strategic_goal":
                goal = str(payload.get("goal", "maintain readiness")).strip() or "maintain readiness"
                _append_recent_unique_string(doc, "strategic_goals", goal, limit=16)
            elif action=="appointment":
                person_ref=str(payload["person_ref"]); self._exact_person(person_ref); capabilities=[str(x) for x in payload.get("capabilities",[])]; doc.setdefault("appointments",{})[str(payload["office"])]={"person_ref":person_ref,"capabilities":capabilities,"appointed_at":str(self._world_time())}
            elif action in {"enemy_action","record_threat"}:
                source=self._state_key(payload.get("source_state","zhao")); severity=_clamp(int(payload.get("severity",50)))
                information_ref=str(payload.get("information_ref","")).strip()
                threat={"severity":severity,"observed_at":str(self._world_time()),"provenance":str(payload.get("provenance","lawful report"))}
                if information_ref:
                    info_path=self.read("state/information/index.json").get("claims",{}).get(information_ref)
                    if not info_path: raise ValueError("state threat information_ref is not an exact saved claim")
                    info=self.read(info_path)
                    threat["information_ref"]=information_ref
                    threat["information_provenance"]=str(info.get("provenance","saved claim"))
                    known=doc.setdefault("known_information_refs",[])
                    if information_ref in known: known.remove(information_ref)
                    known.append(information_ref); del known[:-64]
                doc.setdefault("known_threats",{})[source]=threat
                doc.setdefault("diplomacy",{})[f"state_{source}"]={"tension":severity}
            self.put(p,doc); world_time,metrics=self._advance_seconds(2*3600); self._write_meta(command,world_time); return self._result(state=state,action=action,world_time=world_time,**metrics)
        if t in {"market_purchase","market_sell","economy_transfer","enlisted_service_pay"}:
            walletp="state/economy/player-wallet.json"; wallet=_deepcopy(self.read(walletp))
            if t in {"market_purchase","market_sell"}:
                marketp="state/markets/kanyou.json"; market=_deepcopy(self.read(marketp)); market_key=str(payload["item_key"]); qty=int(payload.get("quantity",1)); econ=self.read("game/data/mechanics/economy.json"); prices=econ.get("prices_silver",econ.get("prices",{}))
                if market_key not in market.get("stock",{}) or market_key not in prices: raise ValueError("unknown or unpriced market item")
                item_id=self._market_item_id(market_key); self._item_record(item_id); pack_size=20 if market_key=="arrows_20" else 1; exact_qty=qty*pack_size; unit_price=_fixed(prices[market_key]); total=int(round(unit_price*qty)); player_location=self.read("state/player.json").get("location")
                if player_location != market.get("location_ref"): raise ValueError("market transaction requires lawful physical market access")
                invp,inv=self._player_inventory()
                ep="state/economy/private/qin.json"; eco=_deepcopy(self.read(ep))
                if t=="market_purchase":
                    if int(market["stock"].get(market_key,0))<qty: raise ValueError("insufficient market stock")
                    if int(wallet.get("silver",0))<total: raise ValueError("insufficient player funds")
                    wallet["silver"]-=total; market["stock"][market_key]-=qty; eco["cash_silver"]=int(eco.get("cash_silver",0))+total; inv["items"][item_id]=int(inv["items"].get(item_id,0))+exact_qty; result={"item_key":market_key,"item_id":item_id,"quantity":qty,"exact_quantity":exact_qty,"spent_silver":total}
                else:
                    if int(inv["items"].get(item_id,0))<exact_qty: raise ValueError("insufficient unequipped player inventory to sell")
                    proceeds=max(1,int(math.floor(total*0.70))); if_cash=int(eco.get("cash_silver",0))
                    if if_cash<proceeds: raise ValueError("local private economy cannot fund this purchase")
                    inv["items"][item_id]-=exact_qty; wallet["silver"]+=proceeds; market["stock"][market_key]=int(market["stock"].get(market_key,0))+qty; eco["cash_silver"]-=proceeds; result={"item_key":market_key,"item_id":item_id,"quantity":qty,"exact_quantity":exact_qty,"received_silver":proceeds}
                self.put(invp,inv); self._register_owner("inventory_char_tang_wei",invp); self.put(ep,eco); self.put(marketp,market); self.put(walletp,wallet); world_time,metrics=self._advance_seconds(max(300,qty*60)); self._write_meta(command,world_time); return self._result(world_time=world_time,**result,**metrics)
            state=self._state_key(payload.get("state","qin")); sp=f"state/states/{state}.json"; sd=_deepcopy(self.read(sp)); amount=int(payload.get("amount_silver",7 if t=="enlisted_service_pay" else 0));
            if t=="economy_transfer" and payload.get("direction")=="player_to_state":
                if int(wallet["silver"]) < amount: raise ValueError("insufficient funds")
                wallet["silver"] -= amount; sd["treasury_silver"] += amount
            else:
                if int(sd["treasury_silver"]) < amount: raise ValueError("state treasury insufficient")
                sd["treasury_silver"] -= amount; wallet["silver"] += amount
            self.put(sp,sd); self.put(walletp,wallet); world_time,metrics=self._advance_seconds(1800); self._write_meta(command,world_time); return self._result(amount_silver=amount,state=state,world_time=world_time,**metrics)
        if t in {"equipment_equip","equipment_unequip","equipment_transfer","equipment_issue","equipment_return","equipment_drop","equipment_loot","equipment_consume"}:
            item_id=str(payload["item_key"]); qty=int(payload.get("quantity",1)); self._item_record(item_id); player=_deepcopy(self.read("state/player.json")); player_loc=self._person_location(player); invp,inv=self._player_inventory(); mp,manifest=self._player_manifest(); entries=manifest.setdefault("equipment_manifest",[])
            def find_entry(states: tuple[str,...]=()) -> Optional[Dict[str,Any]]:
                for entry in entries:
                    if str(entry.get("item_id"))!=item_id: continue
                    state=str(entry.get("current_state","")).lower()
                    if not states or any(token in state for token in states): return entry
                return None
            if t=="equipment_equip":
                equipped=self._manifest_quantity(manifest,item_id,equipped_only=True)
                if equipped>=qty: raise ValueError("requested item quantity is already equipped")
                need=qty-equipped; stored=find_entry(("stored","ready room","stables","sheathed"))
                while need>0 and stored is not None and int(stored.get("quantity",0))>0:
                    take=min(need,int(stored["quantity"])); stored["quantity"]-=take; entries.append({"item_id":item_id,"quantity":take,"custody":"Tang Wei player equipment","current_state":"equipped/readied on person"}); need-=take
                    if stored["quantity"]<=0: entries.remove(stored)
                    stored=find_entry(("stored","ready room","stables","sheathed"))
                if need:
                    if int(inv["items"].get(item_id,0))<need: raise ValueError("player does not own enough of the exact item to equip")
                    inv["items"][item_id]-=need; entries.append({"item_id":item_id,"quantity":need,"custody":"Tang Wei player equipment","current_state":"equipped/readied on person"})
                action="equipped"
            elif t=="equipment_unequip":
                if self._manifest_quantity(manifest,item_id,equipped_only=True)<qty: raise ValueError("insufficient equipped quantity")
                self._take_manifest_items(manifest,item_id,qty,require_equipped=True); entries.append({"item_id":item_id,"quantity":qty,"custody":"Tang Wei player equipment","current_state":"stored with player at "+str(player_loc)}); action="unequipped"
            elif t in {"equipment_transfer","equipment_issue"}:
                target_ref=str(payload["target_ref"]); tp,target=self._exact_person(target_ref); target_loc=self._person_location(target)
                if not player_loc or player_loc!=target_loc: raise ValueError("equipment transfer requires exact co-location")
                available=int(inv["items"].get(item_id,0)); take_inv=min(qty,available); inv["items"][item_id]=available-take_inv; remaining=qty-take_inv
                if remaining: self._take_manifest_items(manifest,item_id,remaining,require_equipped=False)
                target.setdefault("personal_inventory",{})[item_id]=int(target.get("personal_inventory",{}).get(item_id,0))+qty; self.put(tp,target); action="issued" if t=="equipment_issue" else "transferred"
            elif t=="equipment_return":
                target_ref=str(payload["target_ref"]); tp,target=self._exact_person(target_ref); target_loc=self._person_location(target)
                if not player_loc or player_loc!=target_loc: raise ValueError("equipment return requires exact co-location")
                tinv=target.setdefault("personal_inventory",{}); available=int(tinv.get(item_id,0))
                if available<qty: raise ValueError("returning person does not hold enough of the exact item")
                tinv[item_id]=available-qty
                if tinv[item_id]<=0: tinv.pop(item_id,None)
                inv["items"][item_id]=int(inv["items"].get(item_id,0))+qty; self.put(tp,target); action="returned"
            elif t=="equipment_drop":
                available=int(inv["items"].get(item_id,0)); take_inv=min(qty,available); inv["items"][item_id]=available-take_inv; remaining=qty-take_inv
                if remaining: self._take_manifest_items(manifest,item_id,remaining,require_equipped=False)
                world_items_path="state/economy/world-items.json"; world_items=_deepcopy(self.read(world_items_path)); cache=world_items.setdefault("locations",{}).setdefault(str(player_loc),{}); cache[item_id]=int(cache.get(item_id,0))+qty; self.put(world_items_path,world_items); hist=_deepcopy(self.read("state/history/events/index.json")); eid="equipment_drop_"+command.semantic_digest[:16]; hist.setdefault("events",[]).append({"event_id":eid,"kind":"equipment_drop","at":str(self._world_time()),"person_ref":self.PLAYER_ACTOR,"location_ref":player_loc,"item_id":item_id,"quantity":qty}); write_history_index(self, hist); action="dropped"
            elif t=="equipment_loot":
                world_items_path="state/economy/world-items.json"; world_items=_deepcopy(self.read(world_items_path)); cache=world_items.setdefault("locations",{}).setdefault(str(player_loc),{}); available=int(cache.get(item_id,0))
                if available<qty: raise ValueError("no sufficient exact dropped item exists at the player location")
                cache[item_id]=available-qty
                if cache[item_id]<=0: cache.pop(item_id,None)
                if not cache: world_items["locations"].pop(str(player_loc),None)
                inv["items"][item_id]=int(inv["items"].get(item_id,0))+qty; self.put(world_items_path,world_items); action="looted"
            else:
                available=int(inv["items"].get(item_id,0)); take_inv=min(qty,available); inv["items"][item_id]=available-take_inv; remaining=qty-take_inv
                if remaining: self._take_manifest_items(manifest,item_id,remaining,require_equipped=True)
                action="consumed"
            entries[:]=[e for e in entries if int(e.get("quantity",0))>0]; inv["items"]={k:int(v) for k,v in inv["items"].items() if int(v)>0}; self.put(invp,inv); self._register_owner("inventory_char_tang_wei",invp); self.put(mp,manifest); world_time,metrics=self._advance_seconds(300 if t in {"equipment_equip","equipment_unequip","equipment_consume","equipment_loot"} else 600); self._write_meta(command,world_time); return self._result(action=action,item_id=item_id,quantity=qty,world_time=world_time,**metrics)
        if t=="reputation_event":
            subject_ref=str(payload["subject_ref"]); audience_ref=str(payload["audience_ref"]); delta=int(payload["delta"]); event_type=str(payload.get("event_type","material_conduct")); now=str(self._world_time()); idxp="state/reputation/index.json"; idx=_deepcopy(self.read(idxp)); subject_path=idx.get("subjects",{}).get(subject_ref)
            if not subject_path: raise ValueError("reputation subject is not registered")
            subject=_deepcopy(self.read(subject_path)); slug=lambda x: x.replace(".","-").replace("_","-").replace(":","-"); profile_id=f"reputation.{slug(subject_ref)}.{slug(audience_ref)}"; profile_path=subject.get("audience_profiles",{}).get(audience_ref,f"state/reputation/audiences/{slug(subject_ref)}--{slug(audience_ref)}.json"); profile=_deepcopy(self.read_optional(profile_path) or {"schema":"reputation-audience-profile","subject_id":subject_ref,"audience_id":audience_ref,"as_of":now,"authority":True,"standing":{"overall":0},"dimensions":{},"evidence_count":0,"last_event_refs":[],"memory_class":"normal"}); profile["standing"]["overall"]=_clamp(int(profile.get("standing",{}).get("overall",0))+delta,-100,100); dimension=str(payload.get("dimension","general")); profile.setdefault("dimensions",{})[dimension]=_clamp(int(profile.get("dimensions",{}).get(dimension,0))+delta,-100,100); eid="reputation."+hashlib.sha256((now+":"+subject_ref+":"+audience_ref+":"+str(command.expected_revision)).encode()).hexdigest()[:16]; event_path=f"state/reputation/events/{eid}.json"; event={"schema":"reputation-event","event_id":eid,"subject_id":subject_ref,"event_type":event_type,"occurred_at":now,"source_event_ref":payload.get("source_event_ref"),"authority":True,"signals":{dimension:delta},"standing_signals":{"overall":delta},"visibility":{"audience_ref":audience_ref,"basis":str(payload.get("basis","verified material evidence"))},"witnesses":[str(x) for x in payload.get("witnesses",[])],"report_routes":[],"deliveries":{},"status":"settled"}; self.put(event_path,event); profile["as_of"]=now; profile["evidence_count"]=int(profile.get("evidence_count",0))+1; profile.setdefault("last_event_refs",[]).append(eid); profile["last_event_refs"]=profile["last_event_refs"][-16:]; self.put(profile_path,profile); subject.setdefault("audience_profiles",{})[audience_ref]=profile_path; subject["as_of"]=now; self.put(subject_path,subject); idx["event_count"]=int(idx.get("event_count",0))+1; idx["audience_profile_count"]=sum(len(self.read(path).get("audience_profiles",{})) if path!=subject_path else len(subject.get("audience_profiles",{})) for path in idx.get("subjects",{}).values()); self.put(idxp,idx); world_time,metrics=self._advance_seconds(300); self._write_meta(command,world_time); return self._result(event_ref=eid,subject_ref=subject_ref,audience_ref=audience_ref,standing=profile["standing"]["overall"],world_time=world_time,**metrics)
        if t=="career_event":
            person_ref=str(payload["person_ref"]); pp,person0=self._exact_person(person_ref); person=_deepcopy(person0); kind=str(payload["kind"]); career=person.setdefault("career_state",{}); career.setdefault("merit_total",0); career.setdefault("qualifications",[]); career.setdefault("appointments",[]); rank=person.setdefault("military_rank",{"grade":"unranked","durable":True}); now=str(self._world_time()); record={"record_id":"career."+hashlib.sha256((now+":"+person_ref+":"+kind+":"+str(command.expected_revision)).encode()).hexdigest()[:14],"person_ref":person_ref,"kind":kind,"at":now,"authority":True}
            if kind=="merit":
                merit=int(payload["merit"]); career["merit_total"]=int(career.get("merit_total",0))+merit; record.update({"merit":merit,"evidence_ref":payload.get("evidence_ref")})
            elif kind=="qualification":
                q=str(payload["qualification_ref"]); quals=career.setdefault("qualifications",[])
                if q not in quals: quals.append(q)
                record["qualification_ref"]=q; record["evidence_ref"]=payload.get("evidence_ref")
            elif kind in {"promotion","demotion"}:
                grade=str(payload["grade"]); rules=self.read("game/data/mechanics/military-career.json"); order={str(k):int(v) for k,v in (rules.get("formal_rank_order") or {}).items()}; current=str(rank.get("grade","unranked")); current_for_order="unranked" if current=="not_formally_recorded" else current
                if current_for_order not in order: raise ValueError("current durable military grade is outside the generic formal rank ladder and requires dedicated authority")
                if grade not in order: raise ValueError("unknown durable military grade")
                current_order=order[current_for_order]; target_order=order[grade]
                if kind=="promotion" and target_order<=current_order: raise ValueError("promotion requires a higher durable military grade")
                if kind=="demotion" and target_order>=current_order: raise ValueError("demotion requires a lower durable military grade")
                if not payload.get("grantor_ref"): raise ValueError(kind+" requires lawful grantor authority")
                if not payload.get("evidence_ref"): raise ValueError(kind+" requires saved evidence")
                rank.update({"grade":grade,"durable":True,"changed_at":now,"change_kind":kind,"grantor_ref":payload.get("grantor_ref"),"evidence_ref":payload.get("evidence_ref")}); person["rank"]=grade; record.update({"prior_grade":current,"grade":grade,"grantor_ref":payload.get("grantor_ref"),"evidence_ref":payload.get("evidence_ref")})
            elif kind=="office_appointment":
                office=str(payload["office"]); career.setdefault("appointments",[]).append({"office":office,"at":now,"grantor_ref":payload.get("grantor_ref"),"evidence_ref":payload.get("evidence_ref"),"active":True}); career["appointments"]=career["appointments"][-32:]; career["office_or_command"]=office; career["current_billet"]=office; ca=person.setdefault("command_assignment",{}); ca["billet"]=office; record["office"]=office
            elif kind in {"office_removal","relief"}:
                requested=str(payload.get("office") or career.get("office_or_command") or "active command billet"); ended=False
                for row in reversed(career.setdefault("appointments",[])):
                    if isinstance(row,dict) and row.get("active",True) and (kind=="relief" or str(row.get("office"))==requested):
                        row["active"]=False; row["ended_at"]=now; row["ended_by_ref"]=payload.get("grantor_ref"); row["end_kind"]=kind; ended=True; requested=str(row.get("office",requested)); break
                if kind=="office_removal" and not ended: raise ValueError("office removal requires a saved active appointment")
                career["office_or_command"]="No active command billet"; career["current_billet"]="officer_reserve" if kind=="relief" else "unassigned"; ca=person.setdefault("command_assignment",{}); ca["billet"]=career["current_billet"]; ca.pop("command_group_ref",None); ca.pop("formation_ref",None); ca["current_command_span"]=0; record["office"]=requested; record["durable_grade_preserved"]=str(rank.get("grade","unranked"))
            elif kind=="reserve":
                career["office_or_command"]="Officer reserve / cadre"; career["current_billet"]="officer_reserve"; ca=person.setdefault("command_assignment",{}); ca.update({"billet":"officer_reserve","current_command_span":0}); ca.pop("command_group_ref",None); ca.pop("formation_ref",None); record["durable_grade_preserved"]=str(rank.get("grade","unranked"))
            elif kind=="retirement":
                career["office_or_command"]="Retired from active military service"; career["current_billet"]="retired"; career["retired_at"]=now; ca=person.setdefault("command_assignment",{}); ca.update({"billet":"retired","current_command_span":0}); ca.pop("command_group_ref",None); ca.pop("formation_ref",None); record["durable_grade_preserved"]=str(rank.get("grade","unranked"))
            elif kind=="return_to_service":
                if str(career.get("current_billet","")) not in {"retired","officer_reserve","unassigned"}: raise ValueError("return_to_service requires retired/reserve/unassigned status")
                career["office_or_command"]="Awaiting active military billet"; career["current_billet"]="officer_reserve"; career["returned_to_service_at"]=now; person.setdefault("command_assignment",{}).update({"billet":"officer_reserve","current_command_span":0}); record["durable_grade_preserved"]=str(rank.get("grade","unranked"))
            elif kind in {"affiliation_add","affiliation_remove"}:
                affiliation_ref=str(payload["affiliation_ref"]); active=career.setdefault("affiliations",[])
                if kind=="affiliation_add":
                    if affiliation_ref in active: raise ValueError("affiliation is already active")
                    active.append(affiliation_ref)
                else:
                    if affiliation_ref not in active: raise ValueError("affiliation removal requires a saved active affiliation")
                    career["affiliations"]=[x for x in active if str(x)!=affiliation_ref]
                _append_bounded(career,"affiliation_history",{"affiliation_ref":affiliation_ref,"action":kind,"at":now,"grantor_ref":payload.get("grantor_ref"),"evidence_ref":payload.get("evidence_ref")},limit=32); record["affiliation_ref"]=affiliation_ref
            else:
                raise ValueError("unsupported career event kind")
            hist=_deepcopy(self.read("state/history/events/index.json")); hist.setdefault("events",[]).append({"event_id":record["record_id"],"kind":"career_event","at":now,**{k:v for k,v in record.items() if k not in {"record_id","authority"}}}); write_history_index(self,hist); self.put(pp,person)
            if kind=="merit": record_house_emergence_candidate(self, person_ref=person_ref, evidence_ref=record["record_id"], at=now)
            elif person.get("house_ref"): remove_house_emergence_candidate(self, person_ref)
            world_time,metrics=self._advance_seconds(3600); self._write_meta(command,world_time); return self._result(person_ref=person_ref,kind=kind,military_rank=person.get("military_rank"),career_state=career,record_id=record["record_id"],world_time=world_time,**metrics)
        if t=="mercenary_contract":
            merc_ref=str(payload["mercenary_ref"]); mp,merc0=self.owner(merc_ref); merc=_deepcopy(merc0); action=str(payload["action"]); contracts=merc.setdefault("contracts",[]); now=self._world_time(); contract_ref=str(payload.get("contract_ref","contract."+hashlib.sha256((merc_ref+":"+str(now)+":"+str(command.expected_revision)).encode()).hexdigest()[:12])); contract=next((x for x in contracts if str(x.get("contract_ref"))==contract_ref),None); treasury_path=self.owner_path("treasury_house_tang"); treasury=_deepcopy(self.read(treasury_path)); metrics: Dict[str,int]={}; world_time=str(now)
            if action=="offer":
                if mercenary_has_live_contract(merc):
                    raise ValueError("mercenary company already has a live contract obligation")
                if not bool(merc.get("accounting_only", True)) or str(merc.get("status", "available")) != "available":
                    raise ValueError("mercenary company is not available for a new contract obligation")
                amount=int(payload["amount_silver"]); term=int(payload.get("term_days",90)); contract={"contract_ref":contract_ref,"employer_ref":"house_tang","company_ref":merc_ref,"status":"offered","offered_at":str(now),"amount_silver":amount,"term_days":term,"paid_silver":0,"deployment_location_ref":None}; contracts.append(contract); merc["status"]="considering_offer"; world_time,metrics=self._advance_seconds(3600)
            else:
                if contract is None: raise ValueError("unknown exact mercenary contract")
                amount=int(payload.get("amount_silver",contract.get("amount_silver",0)))
                if action=="accept":
                    if contract.get("status") not in {"offered","renewal_offered"}: raise ValueError("contract is not awaiting company acceptance")
                    contract["status"]="accepted_unpaid"; contract["accepted_at"]=str(now); merc["status"]="contracted_unpaid"; world_time,metrics=self._advance_seconds(3600)
                elif action=="pay":
                    if contract.get("status") not in {"accepted_unpaid","active","renewal_accepted"}: raise ValueError("contract is not payable in its current state")
                    due=max(0,int(contract.get("amount_silver",0))-int(contract.get("paid_silver",0))); pay=min(amount,due)
                    if pay<=0: raise ValueError("contract has no outstanding lawful payment")
                    if int(treasury.get("silver",0))<pay: raise ValueError("House Tang treasury cannot fund mercenary payment")
                    treasury["silver"]-=pay; merc["treasury_silver"]=int(merc.get("treasury_silver",0))+pay; contract["paid_silver"]=int(contract.get("paid_silver",0))+pay
                    if int(contract["paid_silver"])>=int(contract.get("amount_silver",0)): contract["status"]="active"; contract["active_at"]=str(now); merc["status"]="contracted"
                    self.put(treasury_path,treasury); world_time,metrics=self._advance_seconds(3600)
                elif action=="deploy":
                    if contract.get("status")!="active": raise ValueError("mercenary deployment requires a paid active contract")
                    dest=str(payload["location_ref"]); origin=merc.get("current_location_ref") or merc.get("location_ref"); hours=24 if not isinstance(origin,str) else self._route_travel_hours(origin,dest,modes=("formation","horse","foot")); world_time,metrics=self._advance_seconds(max(1,hours)*3600); merc["current_location_ref"]=dest; contract["deployment_location_ref"]=dest; contract["deployed_at"]=world_time; merc["status"]="deployed"
                elif action=="breach":
                    contract["status"]="breached"; contract["breached_at"]=str(now); contract["breach_reason"]=str(payload.get("reason","material breach")); merc["status"]="breached"; world_time,metrics=self._advance_seconds(3600)
                elif action=="renew":
                    if contract.get("status") not in {"active","completed"}: raise ValueError("only active/completed contracts may be renewed")
                    contract["status"]="renewal_offered"; contract["amount_silver"]=amount; contract["paid_silver"]=0; contract["term_days"]=int(payload.get("term_days",contract.get("term_days",90))); contract["renewal_offered_at"]=str(now); world_time,metrics=self._advance_seconds(3600)
                elif action=="complete":
                    if contract.get("status") not in {"active","breached"}: raise ValueError("contract is not completable")
                    contract["status"]="completed"; contract["completed_at"]=str(now); merc["status"]="available"; world_time,metrics=self._advance_seconds(3600)
            merc["contracts"] = compact_mercenary_contracts(contracts)
            merc.setdefault("runtime",{})["last_contract_event_at"]=world_time
            self.put(mp,merc)
            runtime = _deepcopy(self.read("state/runtime.json"))
            if sync_mercenary_route(runtime, merc_ref, merc, world_time):
                self.put("state/runtime.json", runtime)
            self._write_meta(command,world_time); return self._result(mercenary_ref=merc_ref,contract_ref=contract_ref,action=action,status=contract.get("status") if contract else None,world_time=world_time,**metrics)
        if t=="fortification_materialize":
            ref=str(payload["fortification_ref"]); requested_loc=str(payload["location_ref"]); loc=enclosing_fortification_site(self.read, requested_loc) or requested_loc; profiles=self.read("game/data/world/fortification-profiles.json"); profile=next((x for x in profiles.get("profiles",[]) if x.get("site_ref",x.get("location_ref"))==loc),None)
            if not profile: raise ValueError("location has no fortification profile or enclosing fortified parent")
            if self.read("state/fortifications/index.json").get("fortifications",{}).get(ref): raise ValueError("fortification_ref already exists")
            garr=[str(x) for x in payload.get("garrison_formation_refs",[])]; loaded=[]
            for fr in garr:
                fp0,gf0=self._load_formation(fr); gf=_deepcopy(gf0)
                garrison_loc=str(gf.get("location_ref")); garrison_parent=enclosing_fortification_site(self.read,garrison_loc) or garrison_loc
                if garrison_parent!=loc: raise ValueError("fortification garrison must already be at the fortified parent site or an enclosed military child")
                loaded.append((fp0,gf))
            if not loaded: raise ValueError("fortification requires exact saved garrison")
            depot_projection=None
            if hasattr(self,"_fortified_site_runtime_records"):
                _dpath,depot_projection,_apath,_art=self._fortified_site_runtime_records(loc,at=str(self._world_time()))
            commander_ref=payload.get("commander_ref")
            if commander_ref:
                cp,commander=self._validate_person_location_for_formation(str(commander_ref),loaded[0][1]); self.put(cp,commander)
            projected_food=int(((depot_projection or {}).get("stocks") or {}).get("grain_kg",0))
            path=f"state/fortifications/{ref}.json"; initial_integrity=int(payload.get("integrity",100)); doc={"schema":"sword-fortification","owner_id":ref,"fortification_ref":ref,"site_ref":loc,"location_ref":loc,"profile":profile,"integrity":initial_integrity,"physical_state":initial_physical_state(profile,initial_integrity),"garrison_formation_refs":garr,"food_kg":projected_food,"food_projection_only":True,"fortified_site_depot_ref":str((depot_projection or {}).get("owner_id","")),"commander_ref":commander_ref,"state":self._state_key(payload.get("state","qin")),"materialized_at":str(self._world_time())}; sync_integrity_projection(doc); self.put(path,doc); idx=_deepcopy(self.read("state/fortifications/index.json")); idx.setdefault("fortifications",{})[ref]=path; self.put("state/fortifications/index.json",idx); self._register_owner(ref,path); world_time,metrics=self._advance_seconds(2*3600); self._write_meta(command,world_time); return self._result(fortification_ref=ref,food_kg=projected_food,fortified_site_depot_ref=doc.get("fortified_site_depot_ref"),world_time=world_time,**metrics)
        if t in {"siege_start","siege_action"}:
            idxp="state/sieges/index.json"; idx=_deepcopy(self.read(idxp))
            if t=="siege_start":
                ref=str(payload["siege_ref"]); fort_ref=str(payload["fortification_ref"])
                if idx.get("sieges",{}).get(ref): raise ValueError("siege_ref already exists")
                fort_path,fort0=self.owner(fort_ref); fort=_deepcopy(fort0)
                if fort.get("schema")!="sword-fortification": raise ValueError("siege requires an exact fortification")
                if not isinstance(fort.get("physical_state"),Mapping):
                    fort["physical_state"]=initial_physical_state(fort.get("profile",{}),int(fort.get("integrity",100))); sync_integrity_projection(fort); self.put(fort_path,fort)
                attackers=[str(x) for x in payload.get("attacker_formation_refs",[])]; defenders=[str(x) for x in fort.get("garrison_formation_refs",[])]
                if set(attackers)&set(defenders): raise ValueError("a siege formation cannot attack itself")
                attack_states=set(); defend_states=set()
                for fr in attackers+defenders:
                    _,sf=self._load_formation(fr)
                    sf_loc=str(sf.get("location_ref")); contact_site=enclosing_fortification_site(self.read,sf_loc) or sf_loc
                    if contact_site!=str(fort.get("location_ref")): raise ValueError("siege requires exact physical contact at the fortified parent site or one of its lawful access/enclosed locations")
                    if not bool(sf.get("mobilized",False)): raise ValueError("siege participants must be mobilized")
                    admin=str(sf.get("administrative_owner","")); (attack_states if fr in attackers else defend_states).add(admin)
                if attack_states & defend_states: raise ValueError("siege requires hostile administrative sides")
                profile=fort.get("profile",{}) if isinstance(fort.get("profile"),Mapping) else {}
                registered_routes=[str(x) for x in profile.get("route_control_refs",[]) if isinstance(x,str)]
                path=f"state/sieges/{ref}.json"; now=str(self._world_time())
                doc={
                    "schema":"sword-siege","owner_id":ref,"siege_ref":ref,"fortification_ref":fort_ref,
                    "attacker_formation_refs":attackers,"defender_formation_refs":defenders,"status":"active","days":0,"casualties":{},"started_at":now,
                    "attacker_authorities":sorted(attack_states),"defender_authorities":sorted(defend_states),"outcome":None,
                    "engineering_works":[],"registered_approach_route_refs":registered_routes,"blockade":{"covered_route_refs":[],"fully_invested":False},
                    "physical_access_model":str((fort.get("physical_state") or {}).get("model","qualitative_fortification")),
                    "active_enclosure_ref":active_enclosure_ref(fort),
                    "fortified_site_depot_ref":fort.get("fortified_site_depot_ref"),
                    "fortress_artillery_ref":None,
                }
                if hasattr(self,"_fortified_site_runtime_records"):
                    _dp,_dd,_ap,_aa=self._fortified_site_runtime_records(str(fort.get("site_ref",fort.get("location_ref",""))),at=now)
                    doc["fortified_site_depot_ref"]=str(_dd.get("owner_id","")); doc["fortress_artillery_ref"]=str(_aa.get("owner_id",""))
                self.put(path,doc); idx.setdefault("sieges",{})[ref]=path; self.put(idxp,idx); self._register_owner(ref,path)
                world_time,metrics=self._advance_seconds(6*3600); self._write_meta(command,world_time)
                return self._result(siege_ref=ref,status="active",physical_access_model=doc["physical_access_model"],registered_approach_route_refs=registered_routes,world_time=world_time,**metrics)
            ref=str(payload["siege_ref"]); path=idx.get("sieges",{}).get(ref)
            if not path: raise ValueError("unknown siege")
            siege=_deepcopy(self.read(path)); action=str(payload["action"]); fp=self.owner_path(siege["fortification_ref"]); fort=_deepcopy(self.read(fp)); world_time=str(self._world_time()); metrics: Dict[str,int]={}; action_details: Dict[str,Any]={}
            if not isinstance(fort.get("physical_state"),Mapping): fort["physical_state"]=initial_physical_state(fort.get("profile",{}),int(fort.get("integrity",100)))
            if siege.get("status") not in {"active","captured","withdrawn","relieved"} and action!="settle": raise ValueError("siege is not active")
            if action=="blockade":
                if siege.get("status")!="active": raise ValueError("blockade requires an active siege")
                days=int(payload.get("days",7)); registered={str(x) for x in siege.get("registered_approach_route_refs",[])}; requested={str(x) for x in payload.get("route_refs",[])} if payload.get("route_refs") is not None else set(registered)
                if registered and (not requested or not requested.issubset(registered)): raise ValueError("blockade route_refs must be exact registered fortification approaches")
                covered=set(str(x) for x in siege.setdefault("blockade",{}).get("covered_route_refs",[])); covered.update(requested); siege["blockade"]["covered_route_refs"]=sorted(covered); siege["blockade"]["fully_invested"]=bool(registered) and registered.issubset(covered)
                defender_refs=[str(fr) for fr in fort.get("garrison_formation_refs",[])]; defenders=sum(int(self._load_formation(fr)[1].get("personnel",0)) for fr in defender_refs); profile=fort.get("profile",{}) if isinstance(fort.get("profile"),Mapping) else {}; baseline=profile.get("physical_baseline",{}) if isinstance(profile.get("physical_baseline"),Mapping) else {}; autarkic=str(baseline.get("storage_class",""))=="strategic_autarky_siege_reserve"
                blockade_start=self._world_time(); blockade_seconds=max(0,days*86400); blockade_end=blockade_start.add_seconds(blockade_seconds); supply_conditions=[]
                for fr in siege.get("attacker_formation_refs",[]):
                    ap,af0=self._load_formation(str(fr)); af=_deepcopy(af0); settle_formation_idle_fatigue(af,current=blockade_start,rules=self.read(FATIGUE_RULES_PATH)); stamp_formation_activity_fatigue(af,completed_at=blockade_end,fatigue_gain=max(1,days//3),activity_kind="blockade"); self.put(ap,af)
                    supply_conditions.append({"formation_ref":str(fr),**evaluate_military_supply(self,af,at=str(blockade_end))})
                for fr in defender_refs:
                    _dp,df=self._load_formation(fr); supply_conditions.append({"formation_ref":fr,**evaluate_military_supply(self,df,at=str(blockade_end))})
                if hasattr(self,"_siege_defender_reserve_draw"):
                    reserve_draw=self._siege_defender_reserve_draw(fort,days=days,defenders=defenders,at=str(self._world_time()))
                else:
                    reserve_draw={"consumed":{},"shortfall":{},"ration_authority":"persistent_formation_subsistence"}
                siege["days"]=int(siege.get("days",0))+days; action_details={"covered_route_refs":sorted(covered),"fully_invested":bool(siege["blockade"].get("fully_invested")),"formation_supply_conditions":supply_conditions,"defender_reserve_draw":reserve_draw,"strategic_autarky":autarkic,"autarky_rule":"internal production may continue if undamaged; field-army supply is derived strategically while fortified-site food/water endurance remains physical siege state"}; world_time,metrics=self._advance_seconds(blockade_seconds)
            elif action=="build_work":
                if siege.get("status")!="active": raise ValueError("siege engineering requires an active siege")
                source_ref=str(payload["source_formation_ref"]); attacker_refs={str(x) for x in siege.get("attacker_formation_refs",[])}
                if source_ref not in attacker_refs: raise ValueError("attacker siege work must be built by an exact saved attacker formation")
                sp,sf0=self._load_formation(source_ref); sf=_deepcopy(sf0)
                sf_loc=str(sf.get("location_ref")); sf_contact=enclosing_fortification_site(self.read,sf_loc) or sf_loc
                if sf_contact!=str(fort.get("location_ref")): raise ValueError("siege-work labor and materials must be physically co-located at the besieged site or its lawful access node")
                blueprints=engineering_blueprints(self.read); blueprint_ref=str(payload["blueprint_ref"]); blueprint=blueprints.get(blueprint_ref)
                if not isinstance(blueprint,Mapping): raise ValueError("unknown registered siege engineering blueprint")
                target=str(payload.get("target","wall")); quantity=int(payload.get("quantity",1)); kind=str(blueprint.get("kind","work"))
                legal_targets={"battering_ram":{"gate"},"assault_ladder":{"wall"},"grapnel_rope":{"wall"},"siege_tower":{"wall"},"crossing":{"gate","wall"},"mantlet":{"gate","wall"},"covered_gallery":{"gate","wall"},"mine":{"wall"},"fascine":{"gate","wall"},"investment_work":{"investment"}}
                if kind in legal_targets and target not in legal_targets[kind]: raise ValueError(f"{kind} cannot be built for siege target {target}")
                materials=work_materials(blueprint,quantity); logistics=sf.setdefault("logistics",{})
                for key,needed in materials.items():
                    available=float(logistics.get(key,0));
                    if available+1e-9<float(needed): raise ValueError(f"source formation lacks carried {key}: needs {needed}, has {available}")
                engineering_score=self._formation_task_score(sf,"engineering"); difficulty=blueprint_difficulty(blueprint); efficiency=task_efficiency(engineering_score,difficulty)
                labor_available=temporary_duty_personnel(int(sf.get("personnel",0)),"engineering",minimum=max(1,int(blueprint.get("crew_min",1))))
                hours=build_hours(blueprint,quantity,labor_available,labor_efficiency=efficiency); crew=min(labor_available,max(1,int(blueprint.get("crew_optimal",blueprint.get("crew_min",1)))))
                for key,needed in materials.items(): logistics[key]=float(logistics.get(key,0))-float(needed)
                start_work=self._world_time(); work_end=start_work.add_seconds(hours*3600); settle_formation_idle_fatigue(sf,current=start_work,rules=self.read(FATIGUE_RULES_PATH)); stamp_formation_activity_fatigue(sf,completed_at=work_end,fatigue_gain=max(1,min(25,hours//8)),activity_kind="siege_construction"); self.put(sp,sf); work_supply=evaluate_military_supply(self,sf,at=str(work_end))
                now=str(self._world_time()); work_ref="siege_work_"+hashlib.sha256((ref+"|"+now+"|"+blueprint_ref+"|"+target+"|"+str(len(siege.get("engineering_works",[])))).encode()).hexdigest()[:18]; work=work_record(blueprint_ref,blueprint,work_ref=work_ref,target=target,quantity=quantity,at=now,source_formation_ref=source_ref,materials=materials); work["enclosure_ref"]=active_enclosure_ref(fort); work["labor_personnel_used"]=crew; work["engineering_leadership_score"]=round(engineering_score,3); work["engineering_difficulty"]=round(difficulty,3); work["labor_efficiency"]=round(efficiency,4); work["construction_hours"]=hours; work["condition_pct"]=100.0
                siege.setdefault("engineering_works",[]).append(work); world_time,metrics=self._advance_seconds(hours*3600); work["completed_at"]=world_time; action_details={"work":work,"strategic_supply":work_supply}
            elif action=="ram_gate":
                if siege.get("status")!="active": raise ValueError("ram action requires an active siege")
                access=ram_access(fort,siege)
                if not access.get("admissible"): raise ValueError(str(access.get("reason","ram cannot physically reach the gate")))
                current_enclosure=active_enclosure_ref(fort); candidates=[w for w in siege.get("engineering_works",[]) if isinstance(w,dict) and w.get("status")=="serviceable" and w.get("kind")=="battering_ram" and w.get("target")=="gate" and str(w.get("enclosure_ref",current_enclosure))==current_enclosure]
                if payload.get("work_ref") is not None: candidates=[w for w in candidates if str(w.get("work_ref"))==str(payload.get("work_ref"))]
                if not candidates: raise ValueError("no selected serviceable ram is present at the gate")
                work=candidates[0]; cycles=int(payload.get("cycles",10)); condition=max(0.1,float(work.get("condition_pct",100.0))/100.0); impact=float(work.get("base_impact_index",0.0))*condition; damage=apply_ram_damage(fort,impact,cycles); work["condition_pct"]=max(0.0,float(work.get("condition_pct",100.0))-cycles*0.15)
                if work["condition_pct"]<=10.0: work["status"]="unserviceable"
                elapsed=max(3600,int(math.ceil(cycles*float(work.get("base_cycle_seconds",20.0))))); world_time,metrics=self._advance_seconds(elapsed); action_details={"access":access,"ram_work_ref":work.get("work_ref"),"cycles":cycles,"structural_result":damage,"causal_trace":[{"phase":"engine_contact","event":"registered battering ram reaches the exact gate over a load-bearing crossing","work_ref":work.get("work_ref")},{"phase":"structural_impact","event":"ram cycles damage the gate structure","cycles":cycles,**damage}],"narration_contract":{"must_render":["physical gate contact","ram impact and resulting gate condition"],"may_compress":["repeated identical ram cycles"],"do_not_reveal":["hidden seeds or unobserved defender state"]}}
            elif action=="assault":
                if siege.get("status")!="active": raise ValueError("assault requires an active siege")
                target=str(payload.get("target","gate")); requested_method=str(payload.get("method","auto")); methods=[requested_method] if requested_method!="auto" else (["breach"] if target=="gate" else ["breach","ladder","siege_tower","swim_grapnel"]); access=None
                for method in methods:
                    probe=assault_access(fort,siege,target,method)
                    if probe.get("admissible"): access=probe; access["method"]=method; break
                    access=probe
                if not access or not access.get("admissible"): raise ValueError(str((access or {}).get("reason","no lawful physical assault path exists")))
                all_attackers=[str(x) for x in siege.get("attacker_formation_refs",[])]; all_defenders=[str(x) for x in fort.get("garrison_formation_refs",[])]; sector_attackers=[str(x) for x in payload.get("attacker_formation_refs",[])] if payload.get("attacker_formation_refs") is not None else []; sector_defenders=[str(x) for x in payload.get("defender_formation_refs",[])] if payload.get("defender_formation_refs") is not None else []
                if not sector_attackers and not sector_defenders:
                    if len(all_attackers)>128 or len(all_defenders)>128: raise ValueError("large siege assault requires an explicit battlefield sector of at most 128 formations per side")
                    sector_attackers=all_attackers; sector_defenders=all_defenders
                if not set(sector_attackers).issubset(set(all_attackers)): raise ValueError("siege assault sector contains a formation outside the saved attacker force")
                if not set(sector_defenders).issubset(set(all_defenders)): raise ValueError("siege assault sector contains a formation outside the exact fortification garrison")
                active_layer_before=active_enclosure_ref(fort)
                live_all_defenders=[fr for fr in all_defenders if int(self._load_formation(fr)[1].get("personnel",0))>0]
                full_layer_assault=set(live_all_defenders).issubset(set(sector_defenders))
                # An emptied enclosure still has physical walls and gates. Once a
                # lawful access path exists, attackers may occupy it without asking
                # the mass-battle resolver to manufacture a zero-body opponent.
                if not live_all_defenders:
                    physical=ensure_physical_state(fort)
                    register_attacker_foothold(physical,method=str(access.get("method","assault")),target_ref=str(access.get("target_ref",target)),at=str(self._world_time()),battle_ref=f"unopposed:{ref}:{active_layer_before}")
                    transition=advance_enclosure_layer(physical,at=str(self._world_time()),battle_ref=f"unopposed:{ref}:{active_layer_before}")
                    fort["physical_state"]=physical; sync_integrity_projection(fort)
                    world_time,metrics=self._advance_seconds(3600)
                    siege["active_enclosure_ref"]=active_enclosure_ref(fort)
                    if transition.get("final_layer_secured"):
                        siege["status"]="captured"; siege["outcome"]="attacker_control"; siege["captured_at"]=world_time
                    access_event={"phase":"fortification_access","event":"attacking formations enter an undefended enclosure through a physically admitted access path","target":target,"method":access.get("method"),"access_class":access.get("access_class"),"enclosure_ref":active_layer_before}
                    layer_event={"phase":"enclosure_control","event":"the physically reached enclosure passes to attacker control without a defending body remaining to contest it","transition":transition}
                    action_details={"battle_event":None,"winner":"attacker","unopposed":True,"access":access,"enclosure_transition":transition,"causal_trace":[access_event,layer_event],"narration_contract":{"must_render":[access_event,layer_event],"may_compress":[],"do_not_reveal":["hidden seeds or unobserved defender state"]},"casualties":{}}
                else:
                    fortress_fire={"defender_power_factor_milli":1000,"active_systems":{},"ammunition_consumed":{}}
                    if hasattr(self,"_siege_prepare_fortress_artillery"):
                        fortress_fire=self._siege_prepare_fortress_artillery(fort,defender_refs=sector_defenders,attacker_refs=sector_attackers,battle_hours=max(1,min(12,2+int(math.log10(max(10,sum(int(self._load_formation(x)[1].get("personnel",0)) for x in sector_attackers+sector_defenders)))))),at=str(self._world_time()))
                    result=self._battle(command,{"attacker_formation_refs":sector_attackers,"defender_formation_refs":sector_defenders},context={"kind":"siege_assault","contact_ref":ref,"location_ref":fort["location_ref"],"fortress_defender_power_factor_milli":int(fortress_fire.get("defender_power_factor_milli",1000)),"fortress_fire":fortress_fire});
                    for fr,n in result["casualties"].items(): siege.setdefault("casualties",{})[fr]=int(siege.get("casualties",{}).get(fr,0))+int(n)
                    siege["last_assault_event"]=result["battle_event"]; siege.setdefault("assault_sectors",[]).append({"battle_ref":result["battle_event"],"at":str(result["world_time"]),"attacker_formation_refs":sector_attackers,"defender_formation_refs":sector_defenders,"access":access,"enclosure_ref":active_layer_before,"structural_damage_from_troop_battle":0}); siege["assault_sectors"]=siege["assault_sectors"][-32:]; world_time=str(result["world_time"]); metrics={k:int(result.get(k,0)) for k in ("hosts_woken","events_processed") if k in result}
                    transition=None
                    if result.get("winner")=="attacker":
                        physical=ensure_physical_state(fort)
                        register_attacker_foothold(physical,method=str(access.get("method","assault")),target_ref=str(access.get("target_ref",target)),at=world_time,battle_ref=str(result["battle_event"]))
                        commit_active_layer_projection(physical)
                        # A sector victory establishes a persistent foothold. Only a
                        # victory against every surviving defender assigned to the
                        # current enclosure secures that layer and opens the next.
                        if full_layer_assault:
                            transition=advance_enclosure_layer(physical,at=world_time,battle_ref=str(result["battle_event"]))
                        fort["physical_state"]=physical; sync_integrity_projection(fort)
                        siege["active_enclosure_ref"]=active_enclosure_ref(fort)
                        if transition and transition.get("final_layer_secured"):
                            siege["status"]="captured"; siege["outcome"]="attacker_control"; siege["captured_at"]=world_time
                    access_event={"phase":"fortification_access","event":"attacking formations reach the defended contact through a physically admitted access path","target":target,"method":access.get("method"),"access_class":access.get("access_class"),"enclosure_ref":active_layer_before,"breach_width_m":access.get("breach_width_m"),"crossing_length_m":access.get("crossing_length_m")}
                    artillery_event={"phase":"fortress_artillery","event":"fixed fortress systems fire only with serviceable installations, exact crews and physical ammunition","support":fortress_fire}
                    enclosure_event={"phase":"enclosure_control","event":"assault control is resolved at one physical enclosure; surviving inner layers remain independent defenses","transition":transition,"sector_foothold_only":bool(result.get("winner")=="attacker" and not full_layer_assault)}
                    collateral=None
                    if result.get("winner")=="attacker" and hasattr(self,"_siege_damage_fortified_site"):
                        collateral=self._siege_damage_fortified_site(fort,damage_percent=2.0,target="artillery",at=world_time,cause=f"close assault {result.get('battle_event')}")
                    action_details={"battle_event":result["battle_event"],"winner":result["winner"],"access":access,"fortress_fire":fortress_fire,"fortress_collateral_damage":collateral,"enclosure_transition":transition,"causal_trace":[access_event,artillery_event,enclosure_event]+list(result.get("causal_trace",[])),"narration_contract":{"must_render":[access_event,artillery_event,enclosure_event]+list((result.get("narration_contract") or {}).get("must_render",[])),"may_compress":list((result.get("narration_contract") or {}).get("may_compress",[])),"do_not_reveal":list((result.get("narration_contract") or {}).get("do_not_reveal",[]))},"casualties":result.get("casualties",{})}

            elif action=="repair":
                if siege.get("status")!="active": raise ValueError("repair requires an active siege")
                source_ref=str(payload["source_formation_ref"]); defenders={str(x) for x in fort.get("garrison_formation_refs",[])}
                if source_ref not in defenders: raise ValueError("siege repair labor must come from an exact saved garrison formation")
                sp,sf0=self._load_formation(source_ref); sf=_deepcopy(sf0); target=str(payload.get("target","gate")); hours=int(payload.get("hours",12)); state=fort.get("physical_state",{})
                if not isinstance(state,dict) or state.get("model") not in {"exact_perimeter","nested_exact_enclosures"}: raise ValueError("physical repair requires exact registered fortification geometry")
                if target=="gate":
                    gates=state.get("gates",{}) if isinstance(state.get("gates"),Mapping) else {}; structure=gates.get("main_gate",{}) if isinstance(gates.get("main_gate"),Mapping) else {}
                else:
                    structure=state.get("perimeter",{}) if isinstance(state.get("perimeter"),Mapping) else {}
                condition=float(structure.get("structural_condition_percent",100.0)); old_breach=float(structure.get("breach_width_m",0.0)) if target=="gate" else max([float(x.get("width_m",0.0)) for x in state.get("breaches",[]) if isinstance(x,Mapping) and str(x.get("target_kind","wall"))=="wall"] or [0.0]); damaged=max(0.0,100.0-condition)
                if damaged<=0 and old_breach<=0: raise ValueError("selected fortification structure has no material damage to repair")
                engineering_score=self._formation_task_score(sf,"engineering"); efficiency=task_efficiency(engineering_score,45.0); labor_people=temporary_duty_personnel(int(sf.get("personnel",0)),"engineering")
                if labor_people<=0: raise ValueError("physical structural repair requires available garrison manpower")
                restored=min(damaged,max(0.5,hours*labor_people*efficiency/1000.0)); material_units=max(1,int(math.ceil(restored*100.0))); logistics=sf.setdefault("logistics",{})
                carried=max(0,int(logistics.get("construction_material_units",0))); from_carried=min(carried,material_units); remaining_material=max(0,material_units-from_carried); from_depot=0
                if remaining_material and hasattr(self,"_siege_repair_from_site_depot"):
                    _rdp,_rdd,from_depot=self._siege_repair_from_site_depot(fort,required_units=remaining_material,at=str(self._world_time()))
                if from_carried+from_depot<material_units: raise ValueError("garrison and fortified-site depot lack physical construction materials for the requested repair")
                start_repair=self._world_time(); settle_formation_idle_fatigue(sf,current=start_repair,rules=self.read(FATIGUE_RULES_PATH)); logistics["construction_material_units"]=carried-from_carried; stamp_formation_activity_fatigue(sf,completed_at=start_repair.add_seconds(hours*3600),fatigue_gain=max(1,hours//8),activity_kind="siege_repair"); structure["structural_condition_percent"]=min(100.0,condition+restored)
                new_breach=max(0.0,old_breach-restored*0.25)
                if target=="gate":
                    structure["breach_width_m"]=new_breach
                    if new_breach<1.5 and structure["structural_condition_percent"]>20.0: structure["status"]="closed"
                    for breach in state.get("breaches",[]) if isinstance(state.get("breaches"),list) else []:
                        if isinstance(breach,dict) and str(breach.get("target_kind"))=="gate": breach["width_m"]=new_breach; breach["status"]="repaired" if new_breach<=0 else "open"
                else:
                    remaining=new_breach
                    for breach in state.get("breaches",[]) if isinstance(state.get("breaches"),list) else []:
                        if isinstance(breach,dict) and str(breach.get("target_kind","wall"))=="wall" and remaining>=0:
                            breach["width_m"]=max(0.0,min(float(breach.get("width_m",0.0)),remaining)); breach["status"]="repaired" if float(breach.get("width_m",0.0))<=0 else "open"
                commit_active_layer_projection(state); fort["physical_state"]=state; sync_integrity_projection(fort); self.put(sp,sf); world_time,metrics=self._advance_seconds(hours*3600); action_details={"target":target,"integrity_restored_pct":round(restored,3),"breach_width_reduced_m":round(old_breach-new_breach,3),"construction_material_units_consumed":material_units,"construction_material_from_carried":from_carried,"construction_material_from_site_depot":from_depot,"labor_personnel_used":labor_people,"engineering_leadership_score":round(engineering_score,3),"labor_efficiency":round(efficiency,4)}
            elif action=="withdraw":
                if siege.get("status")!="active": raise ValueError("only an active siege may withdraw")
                siege["status"]="withdrawn"; siege["outcome"]="defender_holds"; world_time,metrics=self._advance_seconds(4*3600)
            elif action=="relief":
                if siege.get("status")!="active": raise ValueError("relief requires an active siege")
                siege["status"]="relieved"; siege["outcome"]="defender_holds"; world_time,metrics=self._advance_seconds(4*3600)
            elif action=="settle":
                if siege.get("status") not in {"captured","withdrawn","relieved"}: raise ValueError("siege cannot settle until a causal outcome exists")
                siege["settled_from"]=siege["status"]; siege["status"]="settled"; siege["settled_at"]=str(self._world_time()); world_time,metrics=self._advance_seconds(3600)
            sync_integrity_projection(fort); self.put(fp,fort); self.put(path,siege); self._write_meta(command,world_time)
            result=self._result(siege_ref=ref,status=siege["status"],action=action,outcome=siege.get("outcome"),world_time=world_time,**metrics); result.update(action_details); return result
        if t=="territorial_consequence":
            loc=str(payload["location_ref"]); controller=str(payload["controller"]); terr=_deepcopy(self.read("state/territory/control.json")); site=terr["sites"].get(loc)
            if not site: raise ValueError("unknown strategic territory")
            old_controller=str(site.get("controller"))
            if controller==old_controller: raise ValueError("territorial consequence must materially change control")
            controller_authorities={controller}; controller_force_refs=set(); polity_path=None; polity=None
            if controller.startswith("polity_"):
                polity_path,polity0=self.owner(controller); polity=_deepcopy(polity0)
                controller_authorities.update(str(x) for x in polity.get("military_authority_refs",[]) if isinstance(x,str))
                sovereign_house=str(polity.get("sovereign_house_ref",""))
                if sovereign_house: controller_authorities.add(sovereign_house)
                controller_force_refs.update(str(x) for x in polity.get("military_force_refs",[]) if isinstance(x,str))
            evidence_ref=None; basis=None
            if payload.get("siege_ref"):
                evidence_ref=str(payload["siege_ref"]); _,sg=self.owner(evidence_ref)
                if sg.get("status") not in {"captured","settled"} or sg.get("outcome")!="attacker_control": raise ValueError("territorial transfer requires an attacker-captured siege outcome")
                attacker_states={str(x) for x in sg.get("attacker_authorities",[])}
                if not (controller_authorities & attacker_states): raise ValueError("territorial controller must be backed by the authority that actually captured the site")
                basis="captured_siege"
            elif payload.get("operation_ref"):
                evidence_ref=str(payload["operation_ref"]); op_path=self.read("state/operations/index.json").get("operations",{}).get(evidence_ref)
                if not op_path: raise ValueError("unknown occupation operation")
                op=self.read(op_path)
                if op.get("status") not in {"occupied","completed"} or op.get("location_ref")!=loc: raise ValueError("territorial transfer requires a completed occupation at the exact site")
                forms=[self._load_formation(str(fr))[1] for fr in op.get("formation_refs",[])]; authorities={str(f.get("administrative_owner")) for f in forms if int(f.get("personnel",0))>0}; force_refs={str(f.get("owner_force_ref")) for f in forms if int(f.get("personnel",0))>0}
                op_authorities={str(x) for x in op.get("administrative_authorities",[]) if isinstance(x,str)} if isinstance(op.get("administrative_authorities"),list) else set(); op_authority=str(op.get("administrative_authority", ""));
                if op_authority: op_authorities.add(op_authority)
                grants={str(x) for x in op.get("territorial_grants",[]) if isinstance(x,str)} if isinstance(op.get("territorial_grants"),list) else set(); entitlement=str(op.get("sovereign_entitlement_ref", ""));
                if entitlement: grants.add(entitlement)
                if not ((controller_authorities & (authorities|op_authorities|grants)) or (controller_force_refs & force_refs)): raise ValueError("territorial controller must be backed by military/administrative ownership or an explicit saved territorial grant; command authority alone is insufficient")
                basis="occupation_operation"
            else:
                raise ValueError("territorial control changes require exact siege or occupation evidence")
            now=str(self._world_time()); site["controller"]=controller; site["previous_controller"]=old_controller; site["changed_at"]=now; site["change_evidence_ref"]=evidence_ref; site["change_basis"]=basis
            for route_ref, route_state in (terr.get("route_states", {}) or {}).items():
                if isinstance(route_state, dict) and str(route_state.get("control_site_ref") or "") == loc:
                    route_state["controller_ref"] = controller
                    route_state["controller_changed_at"] = now
                    route_state["control_evidence_ref"] = evidence_ref
            try:
                locations_doc=self.read("game/data/world/locations.json")
                enclosed_refs={str(row.get("ref")) for row in locations_doc.get("locations",[]) if isinstance(row,dict) and str(row.get("contained_by_fortification_site_ref") or "")==loc}
            except (KeyError,FileNotFoundError,ValueError):
                enclosed_refs=set()
            for child_ref in enclosed_refs:
                child=terr.get("sites",{}).get(child_ref)
                if isinstance(child,dict):
                    child["physical_access_controller"]=controller
                    child["physical_access_changed_at"]=now
                    child["physical_access_evidence_ref"]=evidence_ref
            self.put("state/territory/control.json",terr)
            if polity is not None and polity_path is not None:
                occupied=[str(x) for x in polity.setdefault("occupied_site_refs",[])];
                if loc not in occupied: occupied.append(loc)
                polity["occupied_site_refs"]=sorted(set(occupied));
                if str(polity.get("status"))=="territorial_authority": polity["status"]="proto_state"
                polity.setdefault("territorial_history",[]).append({"at":now,"location_ref":loc,"from":old_controller,"evidence_ref":evidence_ref,"basis":basis}); polity["territorial_history"]=polity["territorial_history"][-32:]; self.put(polity_path,polity)
            hist=_deepcopy(self.read("state/history/events/index.json")); eid="territory_"+hashlib.sha256((now+":"+loc+":"+controller).encode()).hexdigest()[:16]; hist.setdefault("events",[]).append({"event_id":eid,"kind":"territorial_control_change","at":now,"location_ref":loc,"from":old_controller,"to":controller,"evidence_ref":evidence_ref,"basis":basis}); write_history_index(self, hist); world_time,metrics=self._advance_seconds(12*3600); self._write_meta(command,world_time); return self._result(location_ref=loc,controller=controller,previous_controller=old_controller,evidence_ref=evidence_ref,world_time=world_time,**metrics)
        if t=="family_event":
            house_ref=str(payload.get("house_ref","house_tang")); hp=self.owner_path(house_ref); house=_deepcopy(self.read(hp)); kind=str(payload["kind"]); idxp="state/family/index.json"; idx=_deepcopy(self.read(idxp)); now=self._world_time(); world_time=str(now); subjects: list[str]=[]; source_refs: list[str]=[]; result: Dict[str,Any]={"house_ref":house_ref,"kind":kind}
            def person_age(ref: str) -> int:
                return age_years(self._exact_person(ref)[1], now)
            def active_union(a: str, b: Optional[str]=None) -> tuple[Optional[str],Optional[str],Optional[Dict[str,Any]]]:
                for uid,path in idx.get("unions",{}).items():
                    u=self.read(path); participants={str(x) for x in u.get("participants",[])}
                    if a in participants and (b is None or b in participants) and str(u.get("status")) in {"betrothed","married"}: return str(uid),str(path),_deepcopy(u)
                return None,None,None
            def add_person_index(ref: str, bucket: str, record_id: str) -> None:
                pi=idx.setdefault("person_index",{}).setdefault(ref,{}); values=pi.setdefault(bucket,[]);
                if record_id not in values: values.append(record_id)
            def close_kin(a: str, b: str) -> bool:
                if a==b: return True
                for kp in idx.get("kinships",{}).values():
                    kin=self.read(kp); participants={str(x) for x in kin.get("participants",[])}
                    if {a,b}.issubset(participants) and str(kin.get("status","active"))=="active": return True
                parents={}
                for pp in idx.get("parentage",{}).values():
                    par=self.read(pp); child=str(par.get("child_id","")); parents[child]={str(x.get("parent_id")) for x in par.get("parent_links",[]) if x.get("parent_id")}
                if a in parents.get(b,set()) or b in parents.get(a,set()): return True
                if parents.get(a,set()) & parents.get(b,set()): return True
                return False
            def write_family_event(event_type: str, refs: list[str], refs_sources: list[str]) -> str:
                eid="family."+event_type+"."+hashlib.sha256((str(now)+":"+":".join(sorted(refs))+":"+str(command.expected_revision)).encode()).hexdigest()[:12]; path=f"state/family/events/{eid}.json"; event={"schema":"family-event","event_id":eid,"event_type":event_type,"occurred_at":str(now),"authority":True,"subject_refs":refs,"source_refs":refs_sources}; self.put(path,event); idx.setdefault("events",{})[eid]=path; idx.setdefault("counts",{})["events"]=len(idx["events"]);
                for ref in refs: add_person_index(ref,"events",eid)
                return eid
            if kind=="proposal":
                a=str(payload["person_ref"]); b=str(payload["partner_ref"]);
                if a==b: raise ValueError("a family proposal requires two distinct people")
                if close_kin(a,b): raise ValueError("marriage proposal is ineligible because the saved family authority records close kinship")
                if person_age(a)<16 or person_age(b)<16: raise ValueError("marriage proposal participants must be at least 16")
                pa,aa=self._exact_person(a); pb,bb=self._exact_person(b);
                if self._person_location(aa)!=self._person_location(bb) or self._person_location(aa) is None: raise ValueError("family proposal requires exact co-location")
                if active_union(a)[2] or active_union(b)[2]: raise ValueError("participant already has an active union")
                if command.actor_id!=self.INTERNAL_ACTOR and a!=command.actor_id: raise PermissionError("player may author only their own proposal")
                pid=str(payload.get("proposal_ref",f"proposal.{a}.{b}.{command.expected_revision}")); path=f"state/family/proposals/{pid}.json";
                if self.read_optional(path) is not None: raise ValueError("proposal_ref already exists")
                proposal={"schema":"family-proposal","proposal_id":pid,"kind":"marriage_proposal","proposer_id":a,"target_id":b,"status":"pending","authority":True,"proposed_at":str(now),"player_choice_required":b==self.PLAYER_ACTOR}; self.put(path,proposal); idx.setdefault("proposals",{})[pid]=path; idx.setdefault("counts",{})["proposals"]=len(idx["proposals"]); add_person_index(a,"proposals",pid); add_person_index(b,"proposals",pid); subjects=[a,b]; source_refs=[path]; result["proposal_ref"]=pid; result["family_event"]=write_family_event("proposal_made",subjects,source_refs)
            elif kind=="engagement":
                pid=str(payload.get("proposal_ref","")); path=idx.get("proposals",{}).get(pid);
                if not path: raise ValueError("engagement requires an exact saved proposal")
                proposal=_deepcopy(self.read(path));
                if proposal.get("status")!="pending": raise ValueError("proposal is not pending")
                a=str(proposal["proposer_id"]); b=str(proposal["target_id"]);
                if command.actor_id!=self.INTERNAL_ACTOR and command.actor_id!=b: raise PermissionError("player may accept only a proposal made to the player")
                pa,aa=self._exact_person(a); pb,bb=self._exact_person(b);
                if self._person_location(aa)!=self._person_location(bb) or self._person_location(aa) is None: raise ValueError("engagement requires exact co-location")
                proposal["status"]="accepted"; proposal["accepted_at"]=str(now); self.put(path,proposal); uid="union."+"_".join(sorted([a.replace("char_",""),b.replace("char_","")])) ; up=f"state/family/unions/{uid}.json"; union={"schema":"family-union","union_id":uid,"participants":[a,b],"status":"betrothed","authority":True,"formed_at":str(now),"date_precision":"exact_runtime","recognition":{"recognized":True,"basis":"accepted saved proposal"},"relationship_refs":[],"proposal_ref":pid}; self.put(up,union); idx.setdefault("unions",{})[uid]=up; idx.setdefault("counts",{})["unions"]=len(idx["unions"]); add_person_index(a,"unions",uid); add_person_index(b,"unions",uid); subjects=[a,b]; source_refs=[path,up]; result["union_ref"]=uid; result["family_event"]=write_family_event("betrothal_formed",subjects,source_refs)
            elif kind=="marriage":
                a=str(payload["person_ref"]); b=str(payload["partner_ref"]); uid,up,union=active_union(a,b)
                if union is None or union.get("status")!="betrothed": raise ValueError("marriage requires a saved accepted betrothal")
                pa,aa=self._exact_person(a); pb,bb=self._exact_person(b); loc=self._person_location(aa)
                if not loc or loc!=self._person_location(bb): raise ValueError("marriage requires exact co-location")
                union["status"]="married"; union["married_at"]=str(now); self.put(str(up),union); hid="household."+"_".join(sorted([a.replace("char_",""),b.replace("char_","")])) ; hpath=f"state/family/households/{hid}.json"; household={"schema":"family-household","household_id":hid,"authority":True,"status":"active","member_refs":[a,b],"dependent_refs":[],"property_refs":[],"institution_refs":[],"residence_ref":loc,"union_refs":[uid]}; self.put(hpath,household); union["household_ref"]=hpath; self.put(str(up),union); idx.setdefault("households",{})[hid]=hpath; idx.setdefault("counts",{})["households"]=len(idx["households"]); add_person_index(a,"households",hid); add_person_index(b,"households",hid); subjects=[a,b]; source_refs=[str(up),hpath]; result.update({"union_ref":uid,"household_ref":hid}); result["family_event"]=write_family_event("marriage_formed",subjects,source_refs)
            elif kind=="pregnancy":
                mother_ref=str(payload["mother_ref"]); father_ref=str(payload["father_ref"]); uid,up,union=active_union(mother_ref,father_ref)
                if union is None or union.get("status")!="married": raise ValueError("pregnancy requires a recognized active married union")
                mp,mother=self._exact_person(mother_ref); self._exact_person(father_ref)
                if isinstance(mother.get("pregnancy_state"),dict) and mother["pregnancy_state"].get("active"): raise ValueError("pregnancy already active")
                due=now.add_days(270); mother["pregnancy_state"]={"active":True,"father_ref":father_ref,"union_ref":uid,"recognized_at":str(now),"due_at":str(due)}; self.put(mp,mother); subjects=[mother_ref,father_ref]; source_refs=[str(up)]; result["due_at"]=str(due)
            elif kind=="birth":
                mother_ref=str(payload["mother_ref"]); father_ref=str(payload["father_ref"]); child_ref=str(payload["child_ref"]); mp,mother=self._exact_person(mother_ref); fp,father=self._exact_person(father_ref); preg=mother.get("pregnancy_state")
                if not isinstance(preg,dict) or not preg.get("active") or preg.get("father_ref")!=father_ref: raise ValueError("birth requires a matching active saved pregnancy")
                due=CampaignTime.parse(str(preg["due_at"]));
                if now<due: raise ValueError("birth cannot occur before the saved due time")
                if self.read("state/index/owner-index.json").get("owners",{}).get(child_ref): raise ValueError("child_ref already exists")
                loc=self._person_location(mother); birth_date=f"{now.bce_year}-BCE-{now.month:02d}-{now.day:02d}"; seed=self._causal_seed(command,payload,"birth:"+child_ref); child_path=f"state/char/{child_ref.replace('char_','').replace('_','-')}.json"; child={"schema":"sab_character","owner_id":child_ref,"owner_type":"character","name":str(payload.get("name",child_ref.replace('char_','').replace('_',' ').title())),"birth_date":birth_date,"body":{"adult_height_cm":float(160+(seed%1800)/100.0),"growth_end_age":18,"current_weight_kg":3.2+((seed//100)%8)/10.0,"frame":"infant","growth_profile_id":"human_height_to_18"},"appearance":int(40+(seed%61)),"attributes":{},"skills":{},"aptitude":{"physical_learning":100,"technical_learning":100,"tactical_learning":100,"academic_learning":100,"social_learning":100},"development_state":{},"health_status":"healthy","life_status":"active","current_location":loc,"family":house_ref}; self.put(child_path,child); self._register_owner(child_ref,child_path); self._ensure_person_life_host(child_ref,now); parentage_id=f"parentage.{child_ref.replace('char_','')}.birth_parents"; parpath=f"state/family/parentage/{parentage_id}.json"; parentage={"schema":"family-parentage","parentage_id":parentage_id,"child_id":child_ref,"authority":True,"parent_links":[{"parent_id":mother_ref,"kind":"biological"},{"parent_id":father_ref,"kind":"biological"}],"guardian_links":[]}; self.put(parpath,parentage); idx.setdefault("parentage",{})[parentage_id]=parpath; idx.setdefault("counts",{})["parentage"]=len(idx["parentage"]); add_person_index(child_ref,"parentage",parentage_id); add_person_index(mother_ref,"parentage",parentage_id); add_person_index(father_ref,"parentage",parentage_id); uid=str(preg.get("union_ref")); up=idx.get("unions",{}).get(uid); union=self.read(up) if up else {}; hpath=union.get("household_ref") if isinstance(union,dict) else None
                if isinstance(hpath,str): household=_deepcopy(self.read(hpath)); deps=household.setdefault("dependent_refs",[]);
                if isinstance(hpath,str) and child_ref not in deps: deps.append(child_ref); self.put(hpath,household); add_person_index(child_ref,"households",str(household.get("household_id")))
                preg["active"]=False; preg["resolved_at"]=str(now); preg["child_ref"]=child_ref; mother["pregnancy_state"]=preg; self.put(mp,mother); register_exact_house_lineage_member(self, house, person_ref=child_ref, at=str(now)); subjects=[mother_ref,father_ref,child_ref]; source_refs=[parpath]+([str(hpath)] if hpath else []); result.update({"child_ref":child_ref,"parentage_ref":parentage_id}); result["family_event"]=write_family_event("birth",subjects,source_refs)
            elif kind=="death":
                person_ref=str(payload["person_ref"]); pp,person=self._exact_person(person_ref)
                self._settle_person_death(person_ref,pp,person,str(now),str(payload.get("reason","family-recorded death")),settle_force_body=True)
                subjects=[person_ref]
                ensure_house_lineage_representation(self, house, at=str(now)); recompute_house_lineage(self, house, at=str(now))
                result["family_event"]="family.death."+hashlib.sha256((person_ref+":"+str(now)).encode()).hexdigest()[:12]
            elif kind=="widowhood":
                person_ref=str(payload["person_ref"]); changed=[]
                for uid,up in list(idx.get("unions",{}).items()):
                    union=_deepcopy(self.read(up));
                    if person_ref in union.get("participants",[]) and union.get("status")=="married": union["status"]="widowed"; union["widowed_at"]=str(now); self.put(up,union); changed.append(up)
                if not changed: raise ValueError("no active marriage exists for widowhood settlement")
                subjects=[person_ref]; source_refs=changed; result["family_event"]=write_family_event("widowhood",subjects,source_refs)
            elif kind=="succession_review":
                sid=str(payload.get("succession_ref","succession.house_tang")); sp=idx.get("successions",{}).get(sid);
                if not sp: raise ValueError("unknown succession record")
                succession=_deepcopy(self.read(sp)); holder=str(succession.get("current_holder_id","")); holder_dead=False
                if holder:
                    try: holder_dead=str(self._exact_person(holder,active=False)[1].get("life_status","active")) in {"dead","deceased"}
                    except ValueError: holder_dead=True
                if holder_dead:
                    replacement=None
                    for c in succession.get("candidate_order",[]):
                        ref=str(c.get("person_id",""));
                        try:
                            self._exact_person(ref); replacement=ref; break
                        except ValueError: continue
                    if replacement is None: raise ValueError("succession has no living eligible candidate")
                    succession["current_holder_id"]=replacement; succession["last_changed_at"]=str(now); self.put(sp,succession); result["new_holder_ref"]=replacement; subjects=[holder,replacement]; source_refs=[sp]; result["family_event"]=write_family_event("succession_change",subjects,source_refs)
                else: result["new_holder_ref"]=holder
            idx.setdefault("counts",{})["unions"]=len(idx.get("unions",{})); idx["counts"]["households"]=len(idx.get("households",{})); idx["counts"]["parentage"]=len(idx.get("parentage",{})); self.put(idxp,idx); self.put(hp,house); family_hours={"proposal":1,"engagement":1,"marriage":8,"pregnancy":1,"birth":8,"death":0,"widowhood":1,"succession_review":2}; metrics: Dict[str,int]={}; hours=int(family_hours.get(kind,1));
            if hours>0: world_time,metrics=self._advance_seconds(hours*3600)
            self._write_meta(command,world_time); result.update({"world_time":world_time}); result.update(metrics); return self._result(**result)
        raise ValueError("unsupported Sword semantic command: %s" % t)

    def preview(self, command: CommandEnvelope) -> CommandPlan:
        self._reset(); self._authorize(command)
        if self.store.campaign_id()!=command.campaign_id: raise ValueError("campaign mismatch")
        self.store.require_revision(command.expected_revision)
        payload=thaw_json(command.payload)
        self._validate_command_semantics(command,payload)
        self._authorize_command(command,payload)
        result=self._dispatch(command,payload)
        # Make runtime metrics reflect actual unique planning fanout and write count when runtime is touched.
        if "state/runtime.json" in self._writes:
            rt=self._writes["state/runtime.json"]; rt.setdefault("metrics",{})["planning_reads"]=len(self._reads); rt["metrics"]["writes"]=len(self._writes)+len(self._deletes)
        writes={}
        runtime_frontier = self._writes.get("state/runtime.json")
        if not isinstance(runtime_frontier, Mapping):
            runtime_frontier = self.store.read_json("state/runtime.json")
        training_through = runtime_frontier.get("world_time") if isinstance(runtime_frontier, Mapping) else None
        if not isinstance(training_through, str) or not training_through:
            training_through = None
        for p,v in self._writes.items():
            if p == "state" or p.startswith("state/"):
                v = _compact_hot_state_value(v, training_through=training_through)
                self._writes[p] = v
            raw=_json_bytes(v)
            if self.store.read_optional_bytes(p) != raw:
                writes[p]=raw
        for p in self._deletes:
            if self.store.read_optional_bytes(p) is not None:
                writes[p]=None
        result["planning_reads"]=len(self._reads); result["writes"]=len(writes)
        txid="sword-"+hashlib.sha256((command.digest+":"+str(command.expected_revision)).encode()).hexdigest()[:24]
        return CommandPlan(txid,command.submitted_at,writes,result,len(self._reads),self._validator)


class SwordRuntime:
    def __init__(self, root: object, runtime_root: object | None = None) -> None:
        import os
        self.root=Path(root).resolve(); self.store=RepositoryStore(self.root); self.planner=RepositoryCommandPlanner(self.root)
        runtime_dir=(Path(runtime_root).resolve() if runtime_root is not None else self.root/".sword-runtime"); runtime_dir.mkdir(parents=True,exist_ok=True)
        self.runtime_dir=runtime_dir
        self.coordinator=TransactionCoordinator(
            self.store, GitStager(self.root), WriteAheadLog(runtime_dir/"wal"), ReceiptStore(runtime_dir/"receipts"), runtime_dir/"campaign.lock", lock_timeout=10.0, remote_durability=None)
        self.replicator=None
        remote=os.environ.get("SWORD_GIT_REMOTE"); branch=os.environ.get("SWORD_GIT_BRANCH")
        if remote and branch:
            from sword_runtime.replication import BestEffortReplicator
            self.replicator=BestEffortReplicator(self.root,runtime_dir,remote,branch)

    def preview(self, command: CommandEnvelope) -> CommandPlan:
        if command.actor_id == RepositoryCommandPlanner.INTERNAL_ACTOR or command.mode == "autonomous":
            raise PermissionError("trusted internal commands are not exposed through player-facing preview")
        payload=thaw_json(command.payload)
        if command.command_type in {"battle_resolve","personal_combat"} or (command.command_type=="siege_action" and str(payload.get("action"))=="assault"):
            raise PermissionError("stochastic or contested outcomes are execute-only and cannot be probed through player preview")
        return self.planner.preview(command)

    def execute(self, command: CommandEnvelope, crash_injector=None) -> TransactionExecution:
        # Durable duplicate lookup comes before planning because a retry is intentionally stale.
        existing=self.coordinator.lookup_receipt(command)
        if existing is not None:
            from sword_runtime.tx.coordinator import TransactionExecution
            return TransactionExecution("duplicate",existing,None,None,{})
        plan=self.planner.preview(command)
        execution=self.coordinator.execute(command,plan.transaction_id,plan.created_at,plan.writes,plan.result,plan.validator,crash_injector=crash_injector)
        if execution.status=="committed" and execution.commit_hash and self.replicator is not None:
            self.replicator.replicate(execution.commit_hash)
        return execution

    def recover(self):
        return self.coordinator.recover()

__all__=["RepositoryCommandPlanner","SwordRuntime","CommandPlan","COMMAND_TYPES"]
