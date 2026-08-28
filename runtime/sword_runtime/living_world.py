"""Bounded living-world intelligence layered over Sword's exact authorities.

This module does not create a second campaign authority. It remembers bounded
operational evidence, selects among exact saved formations, and protects the
player from silent irreversible autonomous battle consequences. Exact people,
formations, operations, states, Houses, force pools, and the causal scheduler
remain authoritative in their existing owners.
"""
from __future__ import annotations

import copy
import hashlib
import re
from typing import Any, Dict, Mapping, Optional, Sequence

from sword_runtime.engine import RepositoryCommandPlanner, _clamp, _deepcopy, _fixed
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.history_store import history_total_count, recent_history_events
from sword_runtime.military_supply import military_supply_sufficiency
from sword_runtime.military_doctrine import default_formation_doctrine_ref, doctrine_behavior, role_doctrine_defaults


OPERATIONAL_MEMORY_PATH = "state/world/operational-memory.json"
_MIN_OPERATION_ADMIN_COST = 40
_MAX_MEMORY_EVENTS = 32
_MAX_FORMATION_MEMORY = 64


class HighSalienceWakeRequired(ValueError):
    """An autonomous consequence must be handed back to the player first."""


class LivingWorldSwordPlanner(RepositoryCommandPlanner):
    """Production planner overlay for learned, bounded autonomous behavior."""

    @staticmethod
    def _slug(value: object) -> str:
        clean = re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
        return clean[:64] or "unknown"

    @staticmethod
    def _bounded_append(values: list[str], value: str, limit: int = _MAX_MEMORY_EVENTS) -> None:
        if value in values:
            values.remove(value)
        values.append(value)
        del values[:-limit]

    def _operational_memory(self, at: str) -> Dict[str, Any]:
        raw = self.read_optional(OPERATIONAL_MEMORY_PATH)
        if raw is None:
            memory: Dict[str, Any] = {
                "schema": "sword-operational-memory",
                "authority": False,
                "as_of": at,
                "state_memory": {},
                "formation_memory": {},
            }
        elif not isinstance(raw, Mapping) or raw.get("schema") != "sword-operational-memory":
            raise ValueError("operational memory projection is invalid")
        else:
            memory = copy.deepcopy(dict(raw))
        if not isinstance(memory.get("state_memory"), dict) or not isinstance(memory.get("formation_memory"), dict):
            raise ValueError("operational memory projection is invalid")
        memory["as_of"] = at
        self.put(OPERATIONAL_MEMORY_PATH, memory)
        return memory

    @staticmethod
    def _state_memory(memory: Dict[str, Any], state: str) -> Dict[str, Any]:
        states = memory["state_memory"]
        row = states.setdefault(state, {"formation_candidate_cursor": 0})
        if not isinstance(row, dict):
            raise ValueError("state operational memory is invalid")
        return row

    @staticmethod
    def _formation_memory(memory: Dict[str, Any], formation_ref: str) -> Dict[str, Any]:
        formations = memory["formation_memory"]
        row = formations.setdefault(
            formation_ref,
            {"wins": 0, "losses": 0, "last_result_at": None},
        )
        if not isinstance(row, dict):
            raise ValueError("formation operational memory is invalid")
        return row

    @staticmethod
    def _memory_time_key(value: object) -> tuple[int, int, int, int, int, int]:
        try:
            parsed = CampaignTime.parse(str(value))
        except (TypeError, ValueError):
            return (0, 0, 0, 0, 0, 0)
        return (parsed.sort_year, parsed.month, parsed.day, parsed.hour, parsed.minute, parsed.second)

    @classmethod
    def _prune_formation_memory(cls, memory: Dict[str, Any]) -> None:
        formations = memory.get("formation_memory")
        if not isinstance(formations, dict) or len(formations) <= _MAX_FORMATION_MEMORY:
            return
        ranked: list[tuple[tuple[int, int, int, int, int, int], int, str]] = []
        for formation_ref, row in formations.items():
            if not isinstance(formation_ref, str) or not isinstance(row, Mapping):
                continue
            touched = row.get("last_result_at") or row.get("last_review_at")
            activity = int(row.get("wins", 0)) + int(row.get("losses", 0))
            ranked.append((cls._memory_time_key(touched), activity, formation_ref))
        keep = {ref for _time, _activity, ref in sorted(ranked, reverse=True)[:_MAX_FORMATION_MEMORY]}
        for formation_ref in list(formations):
            if formation_ref not in keep:
                formations.pop(formation_ref, None)

    @staticmethod
    def _formation_roles(formation: Mapping[str, Any]) -> dict[str, int]:
        composition = formation.get("composition")
        if not isinstance(composition, Mapping):
            return {}
        return {
            str(role): max(0, int(count))
            for role, count in composition.items()
            if not isinstance(count, bool) and isinstance(count, (int, float)) and int(count) > 0
        }

    @staticmethod
    def _formation_role(formation: Mapping[str, Any]) -> str:
        composition = LivingWorldSwordPlanner._formation_roles(formation)
        if not composition:
            return "unknown"
        return max(((count, role) for role, count in composition.items()), default=(0, "unknown"))[1]

    @staticmethod
    def _role_doctrine_defaults(role: str) -> tuple[int, int, str]:
        """Return reserve, withdrawal and casualty doctrine for one fighting role.

        This helper exists only to derive a formation-level default from its
        actual mixed composition.  It is not a combat bonus and it does not
        replace an explicit saved doctrine.
        """
        row = role_doctrine_defaults(role)
        return int(row["reserve_commitment"]), int(row["withdrawal_threshold"]), str(row["casualty_tolerance"])

    def _commander_score(self, formation: Mapping[str, Any]) -> int:
        commander_ref = formation.get("commander_ref")
        if not isinstance(commander_ref, str) or not commander_ref:
            return 0
        try:
            _path, commander = self._exact_person(commander_ref)
        except ValueError:
            return 0
        skills = commander.get("skills")
        if not isinstance(skills, Mapping):
            skills = commander.get("capabilities") if isinstance(commander.get("capabilities"), Mapping) else {}
        values = [
            _fixed(skills.get(name, 0))
            for name in ("Formation Command", "Tactics", "Leadership", "Strategy", "Formation Fighting", "Logistics")
        ]
        return int(round(sum(values) / max(1, len(values))))

    @staticmethod
    def _objective_role_bonus(role: str, objective_text: str) -> int:
        text = objective_text.lower()
        if any(token in text for token in ("siege", "fort", "breach", "wall")):
            return {"line_infantry": 30, "missile_infantry": 14, "cavalry": 4, "artillery": 36}.get(role, 8)
        if any(token in text for token in ("pursuit", "raid", "mobile", "screen", "relief", "intercept")):
            return {"cavalry": 42, "missile_cavalry": 40, "line_infantry": 16}.get(role, 10)
        if any(token in text for token in ("border", "defend", "threat", "hold", "protect", "guard")):
            return {"line_infantry": 34, "missile_infantry": 28, "cavalry": 20}.get(role, 10)
        return {"line_infantry": 24, "cavalry": 22, "missile_infantry": 20}.get(role, 12)

    def _formation_score(
        self,
        formation_ref: str,
        formation: Mapping[str, Any],
        objective_text: str,
        memory: Dict[str, Any],
        reserved: set[str],
    ) -> int:
        personnel = max(0, int(formation.get("personnel", 0)))
        if formation_ref in reserved:
            return -10**9
        if personnel <= 0 or str(formation.get("status", "")).lower() in {"destroyed", "dissolved"}:
            return -10**9
        readiness = _clamp(int(formation.get("readiness", 50)))
        morale = _clamp(int(formation.get("morale", 50)))
        cohesion = _clamp(int(formation.get("cohesion", 50)))
        training = _clamp(int(formation.get("training_progress", 20)))
        fatigue = _clamp(int(formation.get("fatigue", 0)))
        supply_score = int(round(100.0 * float(military_supply_sufficiency(self, formation)["overall_ratio"])))
        roles = self._formation_roles(formation)
        role_bonus = 0
        role_total = sum(roles.values())
        if role_total > 0:
            role_bonus = int(round(sum(self._objective_role_bonus(role, objective_text) * count for role, count in roles.items()) / role_total))
        formation_memory = memory.get("formation_memory", {}) if isinstance(memory, Mapping) else {}
        history = formation_memory.get(formation_ref, {}) if isinstance(formation_memory, Mapping) else {}
        history_signal = min(30, int(history.get("wins", 0)) * 5) - min(20, int(history.get("losses", 0)) * 4)
        command = min(100, self._commander_score(formation))
        return (
            readiness * 3
            + morale * 2
            + cohesion * 3
            + training * 2
            + (100 - fatigue) * 2
            + supply_score
            + command * 2
            + role_bonus * 5
            + history_signal
        )

    def _select_formations(
        self,
        state: str,
        objective_text: str,
        memory: Dict[str, Any],
        *,
        reserved: set[str],
        count: int = 2,
    ) -> list[str]:
        force = self.read(f"state/forces/state-{state}.json")
        allocated = force.get("allocated_to_formations") if isinstance(force, Mapping) else None
        refs = sorted(str(ref) for ref in allocated) if isinstance(allocated, Mapping) else []
        candidates: list[tuple[int, str, frozenset[str]]] = []
        for ref in refs:
            try:
                _path, formation = self._load_formation(ref)
            except ValueError:
                continue
            if str(formation.get("administrative_owner")) != f"state_{state}":
                continue
            score = self._formation_score(ref, formation, objective_text, memory, reserved)
            if score <= -10**8:
                continue
            candidates.append((score, ref, frozenset(self._formation_roles(formation))))
        candidates.sort(key=lambda row: (-row[0], row[1]))
        if not candidates:
            return []
        selected: list[tuple[int, str, frozenset[str]]] = [candidates[0]]
        while len(selected) < min(count, len(candidates)):
            used_roles = set().union(*(row[2] for row in selected))
            remaining = [row for row in candidates if row[1] not in {item[1] for item in selected}]
            if not remaining:
                break
            remaining.sort(key=lambda row: (-(row[0] + (90 if row[2] - used_roles else 0)), row[1]))
            selected.append(remaining[0])
        return [row[1] for row in selected]

    def _derive_doctrine_behavior(self, formation: Mapping[str, Any]) -> Dict[str, Any]:
        return doctrine_behavior(self.read, formation)

    def _update_formation_review_memory(
        self,
        memory: Dict[str, Any],
        formation_ref: str,
        formation: Mapping[str, Any],
        *,
        target_strength: int,
        occurrences: int,
    ) -> None:
        """Review current formation authority without shadow-copying it.

        Personnel, role mix, readiness, target strength and training counters are
        read directly from exact formation/force owners. Operational memory only
        retains evidence that can affect a later choice and cannot be re-derived.
        """
        return None

    def _operation_plan_fields(
        self,
        *,
        state: str,
        threat_ref: str,
        threat_value: object,
        selected: list[str],
        admin: int,
        host: Mapping[str, Any],
        at: str,
    ) -> dict[str, Any]:
        """Build a material operation brief from current exact owners.

        These fields are planning constraints and provenance, not separate military
        authority.  Formation custody, logistics stocks, state knowledge and the
        operation owner remain authoritative in their existing records.
        """
        depot = self.read(f"state/depots/{state}.json")
        snapshots: dict[str, Any] = {}
        for formation_ref in selected:
            try:
                _, formation = self._load_formation(formation_ref)
            except ValueError:
                continue
            logistics = formation.get("logistics") if isinstance(formation.get("logistics"), Mapping) else {}
            snapshots[formation_ref] = {
                "personnel": max(0, int(formation.get("personnel", 0))),
                "location_ref": formation.get("location_ref"),
                "strategic_supply": military_supply_sufficiency(self, formation),
                "war_arrows": max(0, int(logistics.get("war_arrows", 0))),
                "war_bolts": max(0, int(logistics.get("war_bolts", 0))),
            }
        recurrence = max(1, int(host.get("recurrence_seconds", 2592000)))
        review_by = str(CampaignTime.parse(at).add_seconds(recurrence))
        intelligence_refs: list[str] = []
        if isinstance(threat_value, Mapping):
            for key in ("information_ref", "claim_ref", "report_ref", "evidence_ref"):
                value = threat_value.get(key)
                if isinstance(value, str) and value:
                    intelligence_refs.append(value)
        target_location_ref = None
        if isinstance(threat_value, Mapping):
            raw_location = threat_value.get("location_ref")
            if isinstance(raw_location, str) and raw_location:
                target_location_ref = raw_location
        return {
            "target_location_ref": target_location_ref,
            "authority_terms": {
                "assignment_authority_ref": f"state_{state}",
                "administrative_capacity_at_assignment": admin,
                "administrative_capacity_cost": _MIN_OPERATION_ADMIN_COST,
            },
            "supply_plan": {
                "source_depot_ref": f"state_depot_{state}",
                "source_location_ref": depot.get("location_ref"),
                "formation_support_at_review": snapshots,
            },
            "opposition_ref": threat_ref,
            "intelligence_basis": {
                "state_known_threat_ref": threat_ref,
                "exact_information_refs": sorted(set(intelligence_refs)),
            },
            "review_by": review_by,
            "victory_criteria": [
                "saved threat severity falls below the material-response threshold",
                "the threatened objective is secured or the hostile force is no longer capable of the saved threat",
            ],
            "termination_criteria": [
                "assignment authority cancels or supersedes the operation",
                "all assigned formations become unavailable or incapable",
                "the saved threat ceases to require a material state response",
            ],
        }

    @staticmethod
    def _threat_severity(value: object) -> int:
        if isinstance(value, Mapping):
            raw = value.get("severity", 0)
        else:
            raw = value
        if isinstance(raw, bool):
            return 0
        try:
            return max(0, min(100, int(float(raw))))
        except (TypeError, ValueError):
            return 0

    def _autonomy_state(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        state = self._state_key(str(host["owner_ref"]))
        super()._autonomy_state(host, occurrences, at)

        memory = self._operational_memory(at)
        state_memory = self._state_memory(memory, state)
        state_doc = self.read(f"state/states/{state}.json")
        admin = max(0, int(state_doc.get("administrative_capacity", 0)))
        capacity = max(1, 1 + admin // _MIN_OPERATION_ADMIN_COST)
        blueprints = self.read("game/data/mil/autonomy-blueprints.json").get("states", {}).get(state, [])
        targets = {f"formation_{state}_{bp['key']}": int(bp.get("personnel", 0)) for bp in blueprints if isinstance(bp, Mapping) and isinstance(bp.get("key"), str)}
        force = self.read(f"state/forces/state-{state}.json")
        allocated = force.get("allocated_to_formations") if isinstance(force, Mapping) else {}
        for formation_ref in sorted(str(ref) for ref in allocated) if isinstance(allocated, Mapping) else []:
            try:
                path, formation0 = self._load_formation(formation_ref)
            except ValueError:
                continue
            formation = _deepcopy(formation0)
            if not isinstance(formation.get("doctrine_ref"), str) or not formation.get("doctrine_ref"):
                formation["doctrine_ref"] = default_formation_doctrine_ref(formation)
                formation["doctrine_behavior"] = self._derive_doctrine_behavior(formation)
                self.put(path, formation)
            self._update_formation_review_memory(
                memory,
                formation_ref,
                formation,
                target_strength=targets.get(formation_ref, int(formation.get("personnel", 0))),
                occurrences=occurrences,
            )

        threats = state_doc.get("known_threats") if isinstance(state_doc.get("known_threats"), Mapping) else {}
        ranked_threats = sorted(
            ((self._threat_severity(value), str(key), value) for key, value in threats.items()),
            key=lambda row: (-row[0], row[1]),
        )
        material = [row for row in ranked_threats if row[0] >= 35]
        operation_index_path = "state/operations/index.json"
        op_index = _deepcopy(self.read(operation_index_path))
        operations = op_index.setdefault("operations", {})
        if not isinstance(operations, dict):
            raise ValueError("operation index is invalid")

        desired: list[str] = []
        reserved: set[str] = set()
        for index, (severity, threat_ref, threat_value) in enumerate(material[:capacity]):
            op_ref = f"operation_auto_{state}_border_response" if index == 0 else f"operation_auto_{state}_{self._slug(threat_ref)}"
            objective_text = f"respond to known threat {threat_ref}"
            if isinstance(threat_value, Mapping):
                kind = threat_value.get("kind")
                if isinstance(kind, str) and kind:
                    objective_text += f" ({kind})"
            selected = self._select_formations(state, objective_text, memory, reserved=reserved, count=2)
            if not selected:
                continue
            reserved.update(selected)
            desired.append(op_ref)
            path = operations.get(op_ref)
            plan_fields = self._operation_plan_fields(
                state=state,
                threat_ref=threat_ref,
                threat_value=threat_value,
                selected=selected,
                admin=admin,
                host=host,
                at=at,
            )
            if isinstance(path, str):
                op = _deepcopy(self.read(path))
                if op.get("autonomous") is not True:
                    continue
                op["status"] = "active"
                op["formation_refs"] = selected
                op["objective"] = objective_text
                op["objective_refs"] = [threat_ref]
                op["assignment_authority_ref"] = f"state_{state}"
                op.update(_deepcopy(plan_fields))
                self.put(path, op)
            else:
                path = f"state/operations/{op_ref}.json"
                op = {
                    "schema": "sword-operation",
                    "owner_id": op_ref,
                    "operation_ref": op_ref,
                    "objective": objective_text,
                    "status": "active",
                    "formation_refs": selected,
                    "location_ref": self.read(f"state/depots/{state}.json").get("location_ref"),
                    "created_at": at,
                    "autonomous": True,
                    "assignment_authority_ref": f"state_{state}",
                    "objective_refs": [threat_ref],
                    **_deepcopy(plan_fields),
                }
                self.put(path, op)
                operations[op_ref] = path
                self._register_owner(op_ref, path)

        previous_active = [
            str(ref)
            for ref, path in operations.items()
            if isinstance(ref, str)
            and ref.startswith(f"operation_auto_{state}_")
            and isinstance(path, str)
            and str(self.read(path).get("status", "")) in {"planned", "mobilizing", "active", "engaged", "occupied"}
        ]
        for op_ref in previous_active:
            if op_ref in desired or not op_ref.startswith(f"operation_auto_{state}_"):
                continue
            path = operations.get(op_ref)
            if isinstance(path, str):
                op = _deepcopy(self.read(path))
                if op.get("autonomous") is True and op.get("status") in {"planned", "mobilizing", "active", "engaged", "occupied"}:
                    op["status"] = "cancelled"
                    op["updated_at"] = at
                    self.put(path, op)
                    operations.pop(op_ref, None)
                    op_index["terminal_operation_count"] = int(op_index.get("terminal_operation_count", 0)) + 1
                    recent = op_index.setdefault("recent_terminal_refs", [])
                    recent.append({"operation_ref": op_ref, "status": "cancelled", "at": at})
                    del recent[:-64]
        # Active/terminal operation truth lives in the exact operation index.
        self.put(operation_index_path, op_index)
        self._prune_formation_memory(memory)
        self.put(OPERATIONAL_MEMORY_PATH, memory)

    def _record_interstate_battle_memory(self, event: Mapping[str, Any], at: str) -> None:
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            return
        memory = self._operational_memory(at)
        winner_state = str(event.get("winner_state", ""))
        attacker_state = str(event.get("attacker_state", ""))
        defender_state = str(event.get("defender_state", ""))
        losses = event.get("losses") if isinstance(event.get("losses"), Mapping) else {}
        for formation_ref, loss_record in losses.items():
            if not isinstance(formation_ref, str) or not isinstance(loss_record, Mapping):
                continue
            row = self._formation_memory(memory, formation_ref)
            formation_state = ""
            if formation_ref == str(event.get("attacker_formation_ref", "")):
                formation_state = attacker_state
            elif formation_ref == str(event.get("defender_formation_ref", "")):
                formation_state = defender_state
            try:
                _path, formation = self._load_formation(formation_ref)
                if not formation_state:
                    formation_state = str(formation.get("administrative_owner", "")).replace("state_", "")
            except ValueError:
                pass
            won = bool(formation_state and formation_state == winner_state)
            row["wins" if won else "losses"] = int(row.get("wins" if won else "losses", 0)) + 1
            row["last_result_at"] = at
            commander_ref = loss_record.get("commander_ref")
            if isinstance(commander_ref, str) and commander_ref and commander_ref != self.PLAYER_ACTOR:
                opponent = defender_state if formation_state == attacker_state else attacker_state
                if opponent:
                    opponent_ref = opponent if opponent.startswith("polity_") else f"state_{opponent}"
                    self._record_reputation_signal(
                        commander_ref,
                        opponent_ref,
                        3 if won else 1,
                        "battle_command",
                        event_id,
                        at,
                        "reported autonomous battlefield command",
                    )
        self._prune_formation_memory(memory)
        self.put(OPERATIONAL_MEMORY_PATH, memory)

    def _autonomy_interstate(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        before_count = history_total_count(self)
        super()._autonomy_interstate(host, occurrences, at)
        after_count = history_total_count(self)
        appended = max(0, after_count - before_count)
        if not appended:
            return
        for event in recent_history_events(self, appended):
            if isinstance(event, Mapping) and event.get("kind") == "interstate_battle":
                self._record_interstate_battle_memory(event, str(event.get("at", at)))

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
            raise HighSalienceWakeRequired("player_commander_autonomous_battle_requires_handoff")
        return super()._autonomy_apply_battle_losses(
            formation_ref,
            loss,
            at,
            losing_side=losing_side,
            opponent_state=opponent_state,
            seed_material=seed_material,
        )


__all__ = [
    "HighSalienceWakeRequired",
    "LivingWorldSwordPlanner",
    "OPERATIONAL_MEMORY_PATH",
]
