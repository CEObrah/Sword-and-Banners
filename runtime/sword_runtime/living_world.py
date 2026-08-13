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


OPERATIONAL_MEMORY_PATH = "state/world/operational-memory.json"
_MAX_STATE_OPERATIONS = 3
_MAX_FORMATION_CANDIDATES = 24
_MAX_MEMORY_EVENTS = 32


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
                "schema": "sword-operational-memory.v1",
                "authority": False,
                "as_of": at,
                "state_memory": {},
                "formation_memory": {},
            }
        elif not isinstance(raw, Mapping) or raw.get("schema") != "sword-operational-memory.v1":
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
        row = states.setdefault(
            state,
            {
                "last_review": None,
                "operation_capacity": 1,
                "active_operation_refs": [],
                "completed_operation_refs": [],
                "battle_wins": 0,
                "battle_losses": 0,
                "recent_event_refs": [],
            },
        )
        if not isinstance(row, dict):
            raise ValueError("state operational memory is invalid")
        return row

    @staticmethod
    def _formation_memory(memory: Dict[str, Any], formation_ref: str) -> Dict[str, Any]:
        formations = memory["formation_memory"]
        row = formations.setdefault(
            formation_ref,
            {
                "role": "unknown",
                "lifecycle": "standing_state_formation",
                "replacement_policy": "maintain_strength",
                "current_personnel": 0,
                "target_strength": 0,
                "last_readiness": 0,
                "training_reviews": 0,
                "replacements_received": 0,
                "deployments": 0,
                "battles": 0,
                "wins": 0,
                "losses": 0,
                "casualties": 0,
                "last_operation_ref": None,
                "last_result": None,
                "last_result_at": None,
                "recent_event_refs": [],
            },
        )
        if not isinstance(row, dict):
            raise ValueError("formation operational memory is invalid")
        return row

    @staticmethod
    def _formation_role(formation: Mapping[str, Any]) -> str:
        composition = formation.get("composition")
        if not isinstance(composition, Mapping) or not composition:
            return "unknown"
        ranked: list[tuple[int, str]] = []
        for raw_role, raw_count in composition.items():
            if isinstance(raw_count, bool) or not isinstance(raw_count, (int, float)):
                continue
            ranked.append((int(raw_count), str(raw_role)))
        return max(ranked, default=(0, "unknown"))[1]

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
            for name in ("Formation Command", "Tactics", "Leadership", "Strategy", "Mass Combat", "Logistics")
        ]
        return int(round(sum(values) / max(1, len(values))))

    @staticmethod
    def _objective_role_bonus(role: str, objective_text: str) -> int:
        text = objective_text.lower()
        if any(token in text for token in ("siege", "fort", "breach", "wall")):
            return {"siege_engineering": 42, "line_infantry": 22, "missile_infantry": 14, "cavalry": 4}.get(role, 8)
        if any(token in text for token in ("pursuit", "raid", "mobile", "screen", "relief", "intercept")):
            return {"cavalry": 42, "missile_cavalry": 40, "line_infantry": 16, "siege_engineering": 2}.get(role, 10)
        if any(token in text for token in ("border", "defend", "threat", "hold", "protect", "guard")):
            return {"line_infantry": 34, "missile_infantry": 28, "cavalry": 20, "siege_engineering": 12}.get(role, 10)
        return {"line_infantry": 22, "cavalry": 22, "missile_infantry": 20, "siege_engineering": 14}.get(role, 12)

    def _formation_score(
        self,
        formation_ref: str,
        formation: Mapping[str, Any],
        objective_text: str,
        memory: Dict[str, Any],
        reserved: set[str],
    ) -> int:
        personnel = max(0, int(formation.get("personnel", 0)))
        if personnel <= 0 or str(formation.get("status", "")).lower() in {"destroyed", "dissolved"}:
            return -10**9
        readiness = _clamp(int(formation.get("readiness", 50)))
        morale = _clamp(int(formation.get("morale", 50)))
        cohesion = _clamp(int(formation.get("cohesion", 50)))
        training = _clamp(int(formation.get("training_progress", 20)))
        fatigue = _clamp(int(formation.get("fatigue", 0)))
        logistics = formation.get("logistics") if isinstance(formation.get("logistics"), Mapping) else {}
        food_days_x10 = min(100, int(int(logistics.get("food_kg", 0)) * 10 / max(1, personnel * 2)))
        role = self._formation_role(formation)
        history = self._formation_memory(memory, formation_ref)
        history_signal = min(30, int(history.get("wins", 0)) * 5) - min(20, int(history.get("losses", 0)) * 4)
        command = min(100, self._commander_score(formation))
        assignment_penalty = 180 if formation_ref in reserved else 0
        return (
            readiness * 3
            + morale * 2
            + cohesion * 3
            + training * 2
            + (100 - fatigue) * 2
            + food_days_x10
            + command * 2
            + self._objective_role_bonus(role, objective_text) * 5
            + history_signal
            - assignment_penalty
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
        refs = sorted(str(ref) for ref in allocated)[:_MAX_FORMATION_CANDIDATES] if isinstance(allocated, Mapping) else []
        candidates: list[tuple[int, str, str]] = []
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
            candidates.append((score, ref, self._formation_role(formation)))
        candidates.sort(key=lambda row: (-row[0], row[1]))
        if not candidates:
            return []
        selected: list[tuple[int, str, str]] = [candidates[0]]
        while len(selected) < min(count, len(candidates)):
            used_roles = {row[2] for row in selected}
            remaining = [row for row in candidates if row[1] not in {item[1] for item in selected}]
            if not remaining:
                break
            remaining.sort(key=lambda row: (-(row[0] + (90 if row[2] not in used_roles else 0)), row[1]))
            selected.append(remaining[0])
        return [row[1] for row in selected]

    def _derive_doctrine_behavior(self, formation: Mapping[str, Any]) -> Dict[str, Any]:
        existing = formation.get("doctrine_behavior") if isinstance(formation.get("doctrine_behavior"), Mapping) else {}
        result = copy.deepcopy(dict(existing))
        role = self._formation_role(formation)
        if role in {"cavalry", "missile_cavalry"}:
            defaults = {"casualty_tolerance": "moderate", "reserve_commitment": 70, "withdrawal_threshold": 35}
        elif role == "siege_engineering":
            defaults = {"casualty_tolerance": "low", "reserve_commitment": 35, "withdrawal_threshold": 45}
        elif role == "missile_infantry":
            defaults = {"casualty_tolerance": "low", "reserve_commitment": 55, "withdrawal_threshold": 40}
        else:
            defaults = {"casualty_tolerance": "moderate", "reserve_commitment": 50, "withdrawal_threshold": 30}
        for key, value in defaults.items():
            result[key] = value
        if int(formation.get("training_progress", 0)) >= 70 and str(formation.get("experience", "")) not in {"new", "formed"}:
            result["withdrawal_threshold"] = max(20, int(result["withdrawal_threshold"]) - 5)
        return result

    def _update_formation_review_memory(
        self,
        memory: Dict[str, Any],
        formation_ref: str,
        formation: Mapping[str, Any],
        *,
        target_strength: int,
        occurrences: int,
    ) -> None:
        row = self._formation_memory(memory, formation_ref)
        prior = int(row.get("current_personnel", 0))
        current = max(0, int(formation.get("personnel", 0)))
        if prior > 0 and current > prior:
            row["replacements_received"] = int(row.get("replacements_received", 0)) + current - prior
        row["role"] = self._formation_role(formation)
        row["lifecycle"] = "standing_state_formation"
        row["replacement_policy"] = "maintain_strength"
        row["current_personnel"] = current
        row["target_strength"] = max(0, int(target_strength))
        row["last_readiness"] = _clamp(int(formation.get("readiness", 0)))
        row["training_reviews"] = int(row.get("training_reviews", 0)) + max(0, int(occurrences))

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
        capacity = max(1, min(_MAX_STATE_OPERATIONS, 1 + admin // 40))
        state_memory["last_review"] = at
        state_memory["operation_capacity"] = capacity

        blueprints = self.read("game/data/mil/autonomy-blueprints.json").get("states", {}).get(state, [])
        targets = {f"formation_{state}_{bp['key']}": int(bp.get("personnel", 0)) for bp in blueprints if isinstance(bp, Mapping) and isinstance(bp.get("key"), str)}
        force = self.read(f"state/forces/state-{state}.json")
        allocated = force.get("allocated_to_formations") if isinstance(force, Mapping) else {}
        for formation_ref in sorted(str(ref) for ref in allocated)[:_MAX_FORMATION_CANDIDATES] if isinstance(allocated, Mapping) else []:
            try:
                path, formation0 = self._load_formation(formation_ref)
            except ValueError:
                continue
            formation = _deepcopy(formation0)
            if formation.get("doctrine_ref") is None:
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
        material = [row for row in ranked_threats if row[0] >= 35][:_MAX_STATE_OPERATIONS]
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
            if isinstance(path, str):
                op = _deepcopy(self.read(path))
                if op.get("autonomous") is not True:
                    continue
                op["status"] = "active"
                op["formation_refs"] = selected
                op["objective"] = objective_text
                op["objective_refs"] = [threat_ref]
                op["assignment_authority_ref"] = f"state_{state}"
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
                }
                self.put(path, op)
                operations[op_ref] = path
                self._register_owner(op_ref, path)
            for formation_ref in selected:
                row = self._formation_memory(memory, formation_ref)
                if row.get("last_operation_ref") != op_ref:
                    row["deployments"] = int(row.get("deployments", 0)) + 1
                row["last_operation_ref"] = op_ref

        previous_active = [str(ref) for ref in state_memory.get("active_operation_refs", []) if isinstance(ref, str)]
        completed = state_memory.setdefault("completed_operation_refs", [])
        if not isinstance(completed, list):
            raise ValueError("state operational memory is invalid")
        for op_ref in previous_active:
            if op_ref in desired or not op_ref.startswith(f"operation_auto_{state}_"):
                continue
            path = operations.get(op_ref)
            if isinstance(path, str):
                op = _deepcopy(self.read(path))
                if op.get("autonomous") is True and op.get("status") in {"planned", "mobilizing", "active", "engaged", "occupied"}:
                    op["status"] = "cancelled"
                    self.put(path, op)
            self._bounded_append(completed, op_ref, 32)
        state_memory["active_operation_refs"] = desired[:capacity]
        self.put(operation_index_path, op_index)
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
        for state in (attacker_state, defender_state):
            if state not in {"qin", "zhao", "chu", "wei", "han", "yan", "qi"}:
                continue
            row = self._state_memory(memory, state)
            if state == winner_state:
                row["battle_wins"] = int(row.get("battle_wins", 0)) + 1
            else:
                row["battle_losses"] = int(row.get("battle_losses", 0)) + 1
            refs = row.setdefault("recent_event_refs", [])
            if isinstance(refs, list):
                self._bounded_append(refs, event_id)
        for formation_ref, loss_record in losses.items():
            if not isinstance(formation_ref, str) or not isinstance(loss_record, Mapping):
                continue
            row = self._formation_memory(memory, formation_ref)
            row["battles"] = int(row.get("battles", 0)) + 1
            formation_state = ""
            try:
                _path, formation = self._load_formation(formation_ref)
                formation_state = str(formation.get("administrative_owner", "")).replace("state_", "")
                row["current_personnel"] = max(0, int(formation.get("personnel", 0)))
                row["last_readiness"] = _clamp(int(formation.get("readiness", 0)))
            except ValueError:
                pass
            won = bool(formation_state and formation_state == winner_state)
            row["wins" if won else "losses"] = int(row.get("wins" if won else "losses", 0)) + 1
            row["casualties"] = int(row.get("casualties", 0)) + max(0, int(loss_record.get("loss", 0)))
            row["last_result"] = "victory" if won else "defeat"
            row["last_result_at"] = at
            refs = row.setdefault("recent_event_refs", [])
            if isinstance(refs, list):
                self._bounded_append(refs, event_id)
            commander_ref = loss_record.get("commander_ref")
            if isinstance(commander_ref, str) and commander_ref and commander_ref != self.PLAYER_ACTOR:
                opponent = defender_state if formation_state == attacker_state else attacker_state
                if opponent:
                    self._record_reputation_signal(
                        commander_ref,
                        f"state_{opponent}",
                        3 if won else 1,
                        "battle_command",
                        event_id,
                        at,
                        "reported autonomous battlefield command",
                    )
        self.put(OPERATIONAL_MEMORY_PATH, memory)

    def _autonomy_interstate(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        history_before = self.read("state/history/events/index.json")
        before_count = len(history_before.get("events", [])) if isinstance(history_before, Mapping) and isinstance(history_before.get("events"), list) else 0
        super()._autonomy_interstate(host, occurrences, at)
        history_after = self.read("state/history/events/index.json")
        events = history_after.get("events", []) if isinstance(history_after, Mapping) else []
        if not isinstance(events, list):
            return
        for event in events[before_count:]:
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
