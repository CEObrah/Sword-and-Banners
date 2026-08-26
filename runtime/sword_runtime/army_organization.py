"""Recursive command-group establishment and autonomous NPC staffing.

Command groups own zero bodies.  A parent sees each direct Formation or intact
Nested Army as one Unit slot.  Review may move a parent's already-existing
direct Unit into an understrength subordinate NPC army, but never flattens
nested descendants, manufactures manpower, changes durable rank, or silently
dissolves damaged organizations.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from sword_runtime.command_units import FORMATION, NESTED_ARMY, append_unit, remove_unit, unit_entries
from sword_runtime.sim.calendar import CampaignTime


def _group_path(ref: str) -> str:
    if not isinstance(ref, str) or not ref.startswith("cmdgrp.") or any(x in ref for x in ("/", "\\", "..")):
        raise ValueError("invalid command_group_ref")
    return f"state/cmd/command-groups/{ref}.json"


class ArmyOrganizationMixin:
    """Establishment review one layer above formation reconstitution."""

    _ARMY_STAFF_ROUTES = "state/cmd/army-staff-routes.json"
    _ARMY_STAFF_REVIEW_SECONDS = 30 * 86400

    def _army_staff_routes(self) -> dict[str, Any]:
        row = self.read_optional(self._ARMY_STAFF_ROUTES)
        if not isinstance(row, Mapping):
            raise ValueError("army staff route registry is missing")
        return copy.deepcopy(dict(row))

    def _army_group_authority(self, group_ref: str) -> str:
        """Resolve one command group through its saved hierarchy, never a world scan."""
        seen: set[str] = set()
        current = group_ref
        while current not in seen:
            seen.add(current)
            group = self.read(_group_path(current))
            authority = str(group.get("authority_ref", ""))
            if authority.startswith("state_"):
                return authority
            if authority == "house_tang":
                return "house_tang"
            if authority in {"char_tang_wei", "pforce.tang_wei"}:
                return "char_tang_wei"
            parent = group.get("parent_command_group_ref")
            if not isinstance(parent, str) or not parent:
                return authority or "unknown"
            current = parent
        raise ValueError("command hierarchy contains a cycle")

    def _register_army_staff_route(self, group_ref: str) -> None:
        routes = self._army_staff_routes()
        authority = self._army_group_authority(group_ref)
        mapping = routes.setdefault("routes", {})
        refs = mapping.setdefault(authority, [])
        if group_ref not in refs:
            refs.append(group_ref); refs.sort()
            self.put(self._ARMY_STAFF_ROUTES, routes)

    def _ensure_army_staff_hosts(self) -> None:
        runtime = copy.deepcopy(self.read("state/runtime.json"))
        hosts = runtime.get("hosts"); events = runtime.get("events")
        if not isinstance(hosts, dict) or not isinstance(events, list):
            raise ValueError("runtime causal queue is invalid")
        routes = self._army_staff_routes().get("routes", {})
        if not isinstance(routes, Mapping):
            raise ValueError("army staff routes are invalid")
        now = CampaignTime.parse(str(runtime["world_time"]))
        changed = False
        event_ids = {str(e.get("event_id")) for e in events if isinstance(e, Mapping)}
        for authority, refs0 in sorted(routes.items()):
            refs = [str(x) for x in refs0] if isinstance(refs0, list) else []
            # The player's hierarchy remains player-directed. Its subordinates are
            # reviewed only when the player explicitly delegates/reviews them.
            if authority == "char_tang_wei" or not refs:
                continue
            slug = str(authority).replace(".", "_").replace("-", "_")
            host_id = f"host_army_staff_{slug}"; event_id = f"event_army_staff_{slug}"
            host = hosts.get(host_id)
            if not isinstance(host, dict):
                due = now.add_seconds(self._ARMY_STAFF_REVIEW_SECONDS)
                host = {"kind":"army_staff","owner_ref":f"army_staff:{authority}","authority_ref":authority,"routed_command_group_refs":refs,"recurrence_seconds":self._ARMY_STAFF_REVIEW_SECONDS,"resolved_through":str(now),"next_due":str(due),"safe_through":str(due.add_seconds(-1))}
                hosts[host_id] = host; changed = True
            elif host.get("routed_command_group_refs") != refs:
                host["routed_command_group_refs"] = refs; changed = True
            if event_id not in event_ids:
                events.append({"event_id":event_id,"kind":"army_staff_review","priority":87,"target_host":host_id,"due_at":str(host["next_due"])})
                event_ids.add(event_id); changed = True
        if changed:
            self.put("state/runtime.json", runtime)

    def _settle_army_staff_host(self, host: Mapping[str, Any], at: str) -> None:
        refs = host.get("routed_command_group_refs")
        if not isinstance(refs, list):
            raise ValueError("army staff host lost routed command groups")
        for group_ref in refs:
            if not isinstance(group_ref, str):
                continue
            group = self.read_optional(_group_path(group_ref))
            if not isinstance(group, Mapping):
                continue
            commander = str(group.get("commander_ref", ""))
            if not commander or commander == str(getattr(self, "PLAYER_ACTOR", "char_tang_wei")):
                continue
            self._review_army_organization(group_ref, at=at, allow_auto_staff=True)

    # Due-host settlement is centrally dispatched by time_integration.py.

    def _trigger_post_battle_army_staff_reviews(
        self,
        casualty_counts: Mapping[str, Any],
        *,
        at: str,
        battle_ref: str,
    ) -> dict[str, Any]:
        """Immediately review NPC command groups materially disrupted by battle.

        This is a bounded exact-index operation.  It never scans the world and it
        never changes durable rank.  A formation qualifies when one battle kills
        at least the configured fraction of its pre-battle personnel or destroys
        the formation.  Player-directed command hierarchies are excluded even if
        a subordinate NPC happens to command one of their Units.
        """
        rules = self.read("game/data/mechanics/military-career.json")
        lifecycle = rules.get("army_lifecycle", {}) if isinstance(rules, Mapping) else {}
        trigger_bp = max(1, min(10000, int(lifecycle.get("immediate_staff_review_casualty_basis_points", 1500))))
        index = self._command_group_index()
        mapping = index.get("primary_formation_group", {})
        if not isinstance(mapping, Mapping):
            raise ValueError("command-group formation routing is invalid")

        triggered: list[str] = []
        evidence: list[dict[str, Any]] = []
        seen_groups: set[str] = set()
        player_actor = str(getattr(self, "PLAYER_ACTOR", "char_tang_wei"))
        for formation_ref, raw_loss in sorted(casualty_counts.items()):
            if not isinstance(formation_ref, str):
                continue
            loss = max(0, int(raw_loss or 0))
            try:
                _fp, formation = self._load_formation(formation_ref)
            except ValueError:
                continue
            after = max(0, int(formation.get("personnel", 0)))
            before = after + loss
            if before <= 0:
                continue
            loss_bp = min(10000, int(round(loss * 10000 / before)))
            destroyed = after <= 0 or str(formation.get("status", "")) == "destroyed"
            if not destroyed and loss_bp < trigger_bp:
                continue
            group_ref = mapping.get(formation_ref)
            if not isinstance(group_ref, str) or not group_ref or group_ref in seen_groups:
                continue
            authority = self._army_group_authority(group_ref)
            if authority == player_actor:
                continue
            group = self.read_optional(_group_path(group_ref))
            if not isinstance(group, Mapping):
                continue
            commander = str(group.get("commander_ref", ""))
            if not commander or commander == player_actor:
                continue
            org = self._review_army_organization(group_ref, at=at, allow_auto_staff=True)
            seen_groups.add(group_ref)
            triggered.append(group_ref)
            evidence.append({
                "formation_ref": formation_ref,
                "command_group_ref": group_ref,
                "casualties": loss,
                "personnel_before": before,
                "personnel_after": after,
                "casualty_basis_points": loss_bp,
                "destroyed": destroyed,
                "auto_attached_unit_refs": list(org.get("last_auto_attached_unit_refs", [])),
            })

        return {
            "trigger_basis_points": trigger_bp,
            "reviewed_command_group_refs": triggered,
            "evidence": evidence,
        }

    def _army_candidate_owner_forces(self, group_ref: str, *, seen: set[str] | None = None) -> set[str]:
        seen = set() if seen is None else set(seen)
        if group_ref in seen:
            raise ValueError("command hierarchy contains a cycle")
        seen.add(group_ref)
        doc = self.read(_group_path(group_ref))
        forces: set[str] = set()
        for row in unit_entries(doc):
            if row["kind"] == FORMATION:
                _fp, formation = self._load_formation(row["ref"])
                owner = formation.get("owner_force_ref")
                if isinstance(owner, str) and owner:
                    forces.add(owner)
            else:
                forces.update(self._army_candidate_owner_forces(row["ref"], seen=seen))
        return forces

    def _review_army_organization(
        self,
        group_ref: str,
        *,
        at: str,
        allow_auto_staff: bool,
    ) -> dict[str, Any]:
        path = _group_path(group_ref)
        group0 = self.read(path)
        if not isinstance(group0, Mapping):
            raise ValueError("command group is missing")
        group = copy.deepcopy(dict(group0))
        rows = unit_entries(group)
        org = group.get("organizational_state") if isinstance(group.get("organizational_state"), Mapping) else {}
        commander = str(group.get("commander_ref", ""))
        player_actor = str(getattr(self, "PLAYER_ACTOR", "char_tang_wei"))
        parent_ref = group.get("parent_command_group_ref")

        anchor_force: str | None = None
        anchor_location = str(group.get("location", ""))
        for row in rows:
            if row["kind"] != FORMATION:
                continue
            _fp, formation = self._load_formation(row["ref"])
            if not anchor_force and formation.get("owner_force_ref"):
                anchor_force = str(formation.get("owner_force_ref"))
            if not anchor_location and formation.get("location_ref"):
                anchor_location = str(formation.get("location_ref"))

        candidates: list[dict[str, Any]] = []
        parent: dict[str, Any] | None = None
        if isinstance(parent_ref, str):
            parent0 = self.read(_group_path(parent_ref))
            if isinstance(parent0, Mapping):
                parent = copy.deepcopy(dict(parent0))
                for candidate in unit_entries(parent):
                    if candidate["ref"] == group_ref:
                        continue
                    if candidate["kind"] == FORMATION:
                        _fp, formation = self._load_formation(candidate["ref"])
                        owner_force = str(formation.get("owner_force_ref", ""))
                        location = str(formation.get("location_ref", ""))
                        if anchor_force and owner_force != anchor_force:
                            continue
                        if anchor_location and location != anchor_location:
                            continue
                        strength = max(0, int(formation.get("personnel", 0)))
                        candidates.append({
                            "kind": FORMATION,
                            "ref": candidate["ref"],
                            "current_strength": strength,
                            "owner_force_ref": owner_force or None,
                            "location_ref": location or None,
                            "parent_direct_unit": True,
                        })
                    else:
                        child = self.read(_group_path(candidate["ref"]))
                        location = str(child.get("location", "")) if isinstance(child, Mapping) else ""
                        if anchor_location and location and location != anchor_location:
                            continue
                        forces = self._army_candidate_owner_forces(candidate["ref"])
                        if anchor_force and (not forces or forces != {anchor_force}):
                            continue
                        summary = self._command_group_organizational_summary(candidate["ref"])
                        candidates.append({
                            "kind": NESTED_ARMY,
                            "ref": candidate["ref"],
                            "current_strength": int(summary.get("recursive_strength", 0)),
                            "owner_force_refs": sorted(forces),
                            "location_ref": location or None,
                            "parent_direct_unit": True,
                            "intact_nested_army": True,
                        })

        # Stable selection: the parent OOB order is strategic intent, so preserve it.
        attached: list[str] = []
        authorized_slots = max(1, int(org.get("authorized_direct_unit_slots", max(1, len(rows)))))
        authorized_strength = max(0, int(org.get("authorized_strength", 0)))
        summary_now = self._command_group_organizational_summary(group_ref)
        current_strength = max(0, int(summary_now.get("recursive_strength", 0)))
        vacant_slots = max(0, authorized_slots - len(rows))
        can_auto = bool(
            allow_auto_staff
            and commander
            and commander != player_actor
            and isinstance(parent_ref, str)
            and parent is not None
            and vacant_slots > 0
            and (authorized_strength <= 0 or current_strength < authorized_strength)
        )

        if can_auto and parent is not None:
            index = self._command_group_index()
            for candidate in candidates:
                if vacant_slots <= 0:
                    break
                if authorized_strength > 0 and current_strength >= authorized_strength:
                    break
                ref = str(candidate["ref"])
                kind = str(candidate["kind"])
                strength = max(0, int(candidate.get("current_strength", 0)))

                # Move the exact direct Unit.  Never copy it and never move descendants.
                remove_unit(parent, ref)
                append_unit(group, kind=kind, ref=ref)
                if kind == FORMATION:
                    fp, f0 = self._load_formation(ref)
                    formation = copy.deepcopy(f0)
                    if formation.get("higher_command_ref") not in {None, str(parent_ref), group_ref}:
                        raise ValueError(f"{ref} reports to an incompatible higher command")
                    formation["higher_command_ref"] = group_ref
                    self.put(fp, formation)
                    index.setdefault("primary_formation_group", {})[ref] = group_ref
                else:
                    cp = _group_path(ref)
                    child = copy.deepcopy(self.read(cp))
                    if child.get("parent_command_group_ref") not in {None, str(parent_ref), group_ref}:
                        raise ValueError(f"{ref} reports to an incompatible parent command")
                    child["parent_command_group_ref"] = group_ref
                    child["updated_at"] = at
                    self.put(cp, child)
                attached.append(ref)
                vacant_slots -= 1
                current_strength += strength

            if attached:
                parent["updated_at"] = at
                group["updated_at"] = at
                self.put(_group_path(str(parent_ref)), parent)
                self._write_command_group_index(index)

        if attached:
            self.put(path, group)
        self._refresh_command_group_organizational_chain(group_ref, at)

        # Candidate and attachment lists describe this review result only. They are
        # returned to the caller but are not durable command-group history.
        final = self.read(path)
        result = copy.deepcopy(dict(final.get("organizational_state", {})))
        result["available_attachment_candidates"] = candidates[:24]
        result["last_auto_attached_unit_refs"] = attached
        return result

    def _dispatch_command_group_action(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        result = super()._dispatch_command_group_action(command, payload)
        action = str(payload.get("action", ""))
        now = str(self._world_time())
        if action == "review_organization":
            group_ref = str(payload["command_group_ref"])
            allow = bool(payload.get("allow_auto_staff", command.actor_id == self.INTERNAL_ACTOR))
            org = self._review_army_organization(group_ref, at=now, allow_auto_staff=allow)
            out = dict(result)
            out["organizational_state"] = org
            out["auto_attached_unit_refs"] = tuple(org.get("last_auto_attached_unit_refs", ()))
            out["available_attachment_candidates"] = tuple(org.get("available_attachment_candidates", ()))
            return out
        if action == "promote_formation_to_army":
            army_ref = result.get("promoted_army_ref") if isinstance(result, Mapping) else None
            if isinstance(army_ref, str):
                # Promotion establishes the new command and its candidate view, but does not
                # silently transfer a second Unit in the same career transaction.
                self._review_army_organization(army_ref, at=now, allow_auto_staff=False)
                self._register_army_staff_route(army_ref)
        return result
