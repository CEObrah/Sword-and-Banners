#!/usr/bin/env python3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def replace_method(path: Path, old_name: str, new_block: str, next_marker: str) -> None:
    s=path.read_text(encoding='utf-8')
    start=s.index(f'    def {old_name}(')
    end=s.index(next_marker, start)
    s=s[:start]+new_block.rstrip()+"\n\n"+s[end:]
    path.write_text(s,encoding='utf-8')

p=ROOT/'runtime/sword_runtime/house_tang_development.py'
s=p.read_text(encoding='utf-8')
s=s.replace('from sword_runtime.household_request_flow import (\n    _emit_watch_report,\n    _perform_house_requested_sword_intake,\n    _response_event,\n    _sword_manor_status,\n    _treasury_safe_ceiling,\n)', 'from sword_runtime.household_request_flow import (\n    _emit_watch_report,\n    _perform_house_requested_military_intake,\n    _house_tang_force_status,\n    _response_event,\n    _treasury_safe_ceiling,\n)')
p.write_text(s,encoding='utf-8')

normalize='''    def _normalize_house_tang_training_host(self, runtime: dict[str, Any]) -> None:
        """Keep one monthly House Tang training/replacement host and retire old hosts."""
        hosts = runtime.get("hosts")
        events = runtime.get("events")
        if not isinstance(hosts, dict) or not isinstance(events, list):
            raise ValueError("runtime causal queue is invalid")
        now = CampaignTime.parse(str(runtime["world_time"]))
        old_hosts = [
            host_id for host_id, host in hosts.items()
            if isinstance(host, Mapping)
            and (host_id == "host_sword_manor" or host.get("kind") == "sword_manor" or host.get("owner_ref") == "force_sword_manor")
        ]
        inherited = None
        for host_id in old_hosts:
            row = hosts.pop(host_id, None)
            if inherited is None and isinstance(row, Mapping):
                inherited = dict(row)
        events[:] = [
            row for row in events
            if not isinstance(row, Mapping)
            or str(row.get("target_host", "")) not in set(old_hosts) | {"host_house_tang_training"}
        ]
        host_id = "host_house_tang_training"
        existing = hosts.get(host_id)
        if not isinstance(existing, dict):
            existing = {}
            hosts[host_id] = existing
        inherited_due = inherited.get("next_due") if isinstance(inherited, Mapping) else None
        due = CampaignTime.parse(str(inherited_due)) if isinstance(inherited_due, str) else None
        if due is None or due <= now:
            due = now.add_seconds(MONTH_SECONDS)
        existing.update({
            "kind": "house_tang_training",
            "owner_ref": "force_house_tang",
            "recurrence_seconds": MONTH_SECONDS,
            "next_due": str(due),
            "resolved_through": str((inherited or {}).get("resolved_through", runtime["world_time"])),
            "safe_through": str(due.add_seconds(-1)),
            "quiet_run_count": max(0, int(existing.get("quiet_run_count", (inherited or {}).get("quiet_run_count", 0)) or 0)),
        })
        events.append({
            "event_id": "event_host_house_tang_training_review",
            "kind": "institution_review",
            "priority": 100,
            "target_host": host_id,
            "due_at": str(due),
        })'''
replace_method(p,'_normalize_sword_manor_host',normalize,'    def _sync_house_development_requests')

autonomy='''    def _autonomy_house_tang_training(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        """Advance the unified two-species House Tang professional force.

        This monthly owner deliberately has no rank/species promotion ladder. The
        same conserved House Infantry and House Cavalry cohorts improve their real
        attributes/skills through the normal deterministic cohort training engine.
        Replacement recruitment remains vacancy-, equipment-, remount-, and
        population-bounded through household_request_flow; this host never mints
        bodies merely because a review occurred.
        """
        occurrences = max(0, int(occurrences))
        if not occurrences:
            return
        house = deepcopy(self.read(HOUSE_FORCE))
        manor = deepcopy(self.read(MANOR_POPULATION))
        qin = deepcopy(self.read(QIN_POPULATION))
        ensure_cohort_ledger(house, at=at)
        roles = set(str(r) for r in house.get("authorized_by_role", {}))
        if roles != {"house_infantry", "house_cavalry"}:
            raise ValueError(f"House Tang active troop taxonomy must be exactly infantry/cavalry, got {sorted(roles)}")
        for cycle in range(occurrences):
            event_ref = f"house_tang_training:{at}:{cycle}"
            self._fc_train(house, "house_tang_max_sustainable", 1, event_ref)
            # Civilian household growth remains independent of military replacement
            # intake and therefore cannot fill a military vacancy by side effect.
            manor.setdefault("recruitment_runtime", {})["last_civil_intake"] = self._civil_intake(
                qin, manor, at=at, cycle_ref=event_ref
            )
        house["cohort_training_closes"] = int(house.get("cohort_training_closes", 0)) + occurrences
        house["last_review"] = at
        manor.setdefault("recruitment_runtime", {})["last_review"] = at
        validate_cohort_ledger(house)
        self.put(HOUSE_FORCE, house)
        self.put(MANOR_POPULATION, manor)
        self.put(QIN_POPULATION, qin)
        runtime = deepcopy(self.read(RUNTIME_PATH))
        runtime["last_house_tang_training_review"] = at
        self.put(RUNTIME_PATH, runtime)
        sync_tang_private_population(
            self,
            at=at,
            reason="house_tang_monthly_training_and_civil_settlement",
            evidence_ref=f"house_tang_training:{at}",
        )'''
replace_method(p,'_autonomy_manor',autonomy,'    # Due-host settlement is centrally dispatched')

# Scheduler/runtime routing.
p=ROOT/'runtime/sword_runtime/time_integration.py'
s=p.read_text(encoding='utf-8')
s=s.replace('"sword_manor": {"owner": "core_living_world", "wake": "domain"}', '"house_tang_training": {"owner": "core_living_world", "wake": "domain"}')
s=s.replace('"mercenary", "interstate", "person", "sword_manor",', '"mercenary", "interstate", "person", "house_tang_training",')
s=s.replace('self._normalize_sword_manor_host(runtime)', 'self._normalize_house_tang_training_host(runtime)')
p.write_text(s,encoding='utf-8')

for rel in ['runtime/sword_runtime/causal_living_world.py','runtime/sword_runtime/engine.py']:
    p=ROOT/rel; s=p.read_text(encoding='utf-8')
    s=s.replace('elif kind == "sword_manor":\n            self._autonomy_manor(', 'elif kind == "house_tang_training":\n            self._autonomy_house_tang_training(')
    p.write_text(s,encoding='utf-8')

# Production hardening layer: keep world-arc enrichment but stop reviving deleted
# Sword Manor establishment/cost authorities.
p=ROOT/'runtime/sword_runtime/house_tang_development_integrity.py'
s=p.read_text(encoding='utf-8')
start=s.index('    def _normalize_sword_manor_host(')
end=s.index('    def _enrich_world_arc_report(', start)
new='''    def _normalize_house_tang_training_host(self, runtime: dict[str, Any]) -> None:
        HouseTangDevelopmentMixin._normalize_house_tang_training_host(self, runtime)

'''
s=s[:start]+new+s[end:]
s=s.replace('''    def _settle_expansion_request(self, host: Mapping[str, Any], at: str) -> None:\n        super()._settle_expansion_request(host, at)\n        self._sync_sword_manor_derived_state()\n\n    def _settle_expansion_completion(self, host: Mapping[str, Any], at: str) -> None:\n        super()._settle_expansion_completion(host, at)\n        self._sync_sword_manor_derived_state()\n\n    def _autonomy_manor(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:\n        super()._autonomy_manor(host, occurrences, at)\n        self._sync_sword_manor_derived_state()\n''','''    def _settle_expansion_request(self, host: Mapping[str, Any], at: str) -> None:\n        super()._settle_expansion_request(host, at)\n\n    def _settle_expansion_completion(self, host: Mapping[str, Any], at: str) -> None:\n        super()._settle_expansion_completion(host, at)\n\n    def _autonomy_house_tang_training(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:\n        super()._autonomy_house_tang_training(host, occurrences, at)\n''')
p.write_text(s,encoding='utf-8')
print('recovered unified House Tang training runtime')
