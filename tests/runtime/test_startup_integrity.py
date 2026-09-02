from __future__ import annotations

import json
from pathlib import Path

import pytest

from sword_runtime.startup_integrity import StartupIntegrityError, validate_startup_integrity


def _load(root: Path, rel: str):
    return json.loads((root / rel).read_text(encoding='utf-8'))


def _save(root: Path, rel: str, value) -> None:
    (root / rel).write_text(json.dumps(value, separators=(',', ':')) + '\n', encoding='utf-8')


def _promoted_non_char_commander_fixture(campaign: Path) -> tuple[str, str, str]:
    """Replace one full-character commander with an officer.* full owner."""
    owners_doc = _load(campaign, 'state/index/owner-index.json')
    owners = owners_doc['owners']
    source_ref = 'char_cmd_qin_kanki_raider_host'
    source_path = owners[source_ref]
    person = _load(campaign, source_path)
    formation_ref = person['command_assignment']['formation_ref']
    formation_path = owners[formation_ref]
    formation = _load(campaign, formation_path)

    promoted_ref = 'officer.test.startup.promoted.full'
    promoted_path = 'state/person/startup-promoted-full-test.json'
    person['owner_id'] = promoted_ref
    if 'id' in person:
        person['id'] = promoted_ref
    person['schema'] = 'sab_character'
    formation['commander_ref'] = promoted_ref
    owners[promoted_ref] = promoted_path

    _save(campaign, promoted_path, person)
    _save(campaign, formation_path, formation)
    _save(campaign, 'state/index/owner-index.json', owners_doc)
    return promoted_ref, promoted_path, formation_path


def test_current_campaign_passes_fast_startup_integrity(campaign: Path) -> None:
    result = validate_startup_integrity(campaign)
    assert result['ok'] is True
    assert result['scheduler_hosts'] == result['scheduler_events']
    assert result['formation_commanders_checked'] > 0


def test_startup_integrity_rejects_split_player_location(campaign: Path) -> None:
    player = _load(campaign, 'state/player.json')
    player['current_location'] = 'loc_qin_eastern_depot'
    _save(campaign, 'state/player.json', player)
    with pytest.raises(StartupIntegrityError, match='player location aliases diverge'):
        validate_startup_integrity(campaign)


def test_startup_integrity_rejects_commander_span_drift(campaign: Path) -> None:
    owners = _load(campaign, 'state/index/owner-index.json')['owners']
    ref = 'char_cmd_qin_kanki_raider_host'
    path = owners[ref]
    person = _load(campaign, path)
    person['career_state']['current_command_span'] -= 500
    _save(campaign, path, person)
    with pytest.raises(StartupIntegrityError, match='commander career span diverges'):
        validate_startup_integrity(campaign)


def test_startup_integrity_rejects_dangling_formation_commander(campaign: Path) -> None:
    owners = _load(campaign, 'state/index/owner-index.json')['owners']
    formation_ref = 'formation_red_lance_a'
    formation_path = owners[formation_ref]
    formation = _load(campaign, formation_path)
    formation['commander_ref'] = 'officer.missing.commander'
    _save(campaign, formation_path, formation)
    with pytest.raises(StartupIntegrityError, match='formation commander has no authoritative owner'):
        validate_startup_integrity(campaign)


def test_startup_integrity_rejects_dangling_embedded_command_person(campaign: Path) -> None:
    owners = _load(campaign, 'state/index/owner-index.json')['owners']
    formation_ref = 'formation_red_lance_a'
    formation_path = owners[formation_ref]
    formation = _load(campaign, formation_path)
    formation['embedded_person_refs'] = list(formation.get('embedded_person_refs', [])) + [
        'officer.missing.embedded'
    ]
    _save(campaign, formation_path, formation)
    with pytest.raises(StartupIntegrityError, match='formation embedded person has no authoritative owner'):
        validate_startup_integrity(campaign)


def test_startup_integrity_rejects_person_lite_unit_commander(campaign: Path) -> None:
    owners = _load(campaign, 'state/index/owner-index.json')['owners']
    formation_ref = 'formation_red_lance_a'
    formation = _load(campaign, owners[formation_ref])
    commander_ref = formation['commander_ref']
    commander_path = owners[commander_ref]
    commander = _load(campaign, commander_path)
    commander['schema'] = 'person-lite'
    _save(campaign, commander_path, commander)
    with pytest.raises(StartupIntegrityError, match='unit-scale formation commander is person-lite'):
        validate_startup_integrity(campaign)


def test_startup_integrity_checks_promoted_full_person_with_non_char_identity(campaign: Path) -> None:
    promoted_ref, promoted_path, _formation_path = _promoted_non_char_commander_fixture(campaign)
    clean = validate_startup_integrity(campaign)
    assert clean['formation_commanders_checked'] > 0

    person = _load(campaign, promoted_path)
    person['career_state']['current_command_span'] -= 500
    _save(campaign, promoted_path, person)
    with pytest.raises(StartupIntegrityError, match=f'commander career span diverges: {promoted_ref}'):
        validate_startup_integrity(campaign)


def test_transaction_invariant_checks_promoted_full_person_with_non_char_identity(campaign: Path) -> None:
    _promoted_ref, promoted_path, _formation_path = _promoted_non_char_commander_fixture(campaign)
    person = _load(campaign, promoted_path)
    person['career_state']['current_command_span'] -= 500
    _save(campaign, promoted_path, person)

    class DiskOverlay:
        def read_json(self, rel):
            return _load(campaign, str(rel))

        def read_optional_bytes(self, rel):
            path = campaign / str(rel)
            return path.read_bytes() if path.exists() else None

    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    with pytest.raises(ValueError, match='formation commander career span diverged'):
        planner._validate_invariants(DiskOverlay(), [promoted_path])


def _materialized_exact_commander_fixture(campaign: Path) -> tuple[str, str, str]:
    """Convert one full commander fixture to the exact sparse materialized schema."""
    owners = _load(campaign, 'state/index/owner-index.json')['owners']
    ref = 'char_cmd_qin_kanki_raider_host'
    path = owners[ref]
    person = _load(campaign, path)
    formation_ref = person['command_assignment']['formation_ref']
    person['schema'] = 'sword-materialized-person'
    _save(campaign, path, person)
    return ref, path, owners[formation_ref]


def test_startup_integrity_checks_materialized_exact_person_under_state_char(campaign: Path) -> None:
    ref, path, _formation_path = _materialized_exact_commander_fixture(campaign)
    person = _load(campaign, path)
    person['location'] = 'loc_qin_eastern_depot'
    person['current_location'] = 'loc_tang_manor'
    _save(campaign, path, person)
    with pytest.raises(StartupIntegrityError, match=f'exact-person location aliases diverge: {ref}'):
        validate_startup_integrity(campaign)


def test_transaction_invariant_checks_materialized_exact_person_under_state_char(campaign: Path) -> None:
    _ref, path, _formation_path = _materialized_exact_commander_fixture(campaign)
    person = _load(campaign, path)
    person['career_state']['current_command_span'] -= 500
    _save(campaign, path, person)

    class DiskOverlay:
        def read_json(self, rel):
            return _load(campaign, str(rel))

        def read_optional_bytes(self, rel):
            target = campaign / str(rel)
            return target.read_bytes() if target.exists() else None

    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    with pytest.raises(ValueError, match='formation commander career span diverged'):
        planner._validate_invariants(DiskOverlay(), [path])


def test_transaction_invariant_rejects_dangling_embedded_command_person(campaign: Path) -> None:
    owners = _load(campaign, 'state/index/owner-index.json')['owners']
    formation_ref = 'formation_red_lance_a'
    formation_path = owners[formation_ref]
    formation = _load(campaign, formation_path)
    formation['embedded_person_refs'] = list(formation.get('embedded_person_refs', [])) + [
        'officer.missing.embedded.tx'
    ]
    _save(campaign, formation_path, formation)

    class DiskOverlay:
        def read_json(self, rel):
            return _load(campaign, str(rel))

        def read_optional_bytes(self, rel):
            target = campaign / str(rel)
            return target.read_bytes() if target.exists() else None

    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    with pytest.raises(ValueError, match='formation embedded person has no authoritative owner'):
        planner._validate_invariants(DiskOverlay(), [formation_path])


def _named_custody_fixture(campaign: Path) -> tuple[str, str, str]:
    person_ref='char_kisui'; group_ref='prisoners_named_startup_fixture'; group_path=f'state/custody/groups/{group_ref}.json'; loc='loc_kankoku_pass'
    owners_doc=_load(campaign,'state/index/owner-index.json'); person_path=owners_doc['owners'][person_ref]
    person=_load(campaign,person_path); person['current_location']=loc; person['custody_state']={'status':'prisoner','prisoner_group_ref':group_ref,'location_ref':loc}; _save(campaign,person_path,person)
    group={'schema':'sword-prisoner-group','owner_id':group_ref,'source_formation_ref':'formation_zhao_retsubi_gate_command','source_force_ref':'force_state_zhao','custodian_formation_ref':'formation_qin_kankoku_central_gate','captor_authority_ref':'state_qin','location_ref':loc,'personnel':0,'by_role':{},'cohort_slices':[],'named_prisoner_refs':[person_ref],'guards_allocated':0,'guard_requirement':1,'legal_status':'prisoner_of_war','status':'held'}
    (campaign/'state/custody/groups').mkdir(parents=True,exist_ok=True); _save(campaign,group_path,group)
    owners_doc['owners'][group_ref]=group_path; _save(campaign,'state/index/owner-index.json',owners_doc)
    custody=_load(campaign,'state/custody/index.json'); custody.setdefault('groups',{})[group_ref]=group_path; custody.setdefault('active_refs',[]).append(group_ref); custody['active_refs']=sorted(set(custody['active_refs'])); _save(campaign,'state/custody/index.json',custody)
    return person_ref,person_path,group_path


def test_startup_integrity_rejects_named_prisoner_location_split(campaign: Path) -> None:
    person_ref,person_path,_group_path=_named_custody_fixture(campaign)
    clean=validate_startup_integrity(campaign)
    assert clean['active_custody_groups_checked']==1
    person=_load(campaign,person_path); person['current_location']='loc_qin_eastern_depot'; person['custody_state']['location_ref']='loc_qin_eastern_depot'; _save(campaign,person_path,person)
    with pytest.raises(StartupIntegrityError,match=f'named prisoner location diverges from custody group: prisoners_named_startup_fixture:{person_ref}'):
        validate_startup_integrity(campaign)


def test_transaction_invariant_rejects_named_prisoner_custody_split(campaign: Path) -> None:
    person_ref,person_path,group_path=_named_custody_fixture(campaign)
    person=_load(campaign,person_path); person['custody_state']['prisoner_group_ref']='prisoners_named_wrong_group'; _save(campaign,person_path,person)

    class DiskOverlay:
        def read_json(self, rel):
            return _load(campaign, str(rel))
        def read_optional_bytes(self, rel):
            target=campaign/str(rel).split('#/',1)[0]
            return target.read_bytes() if target.exists() else None

    from sword_runtime.engine import RepositoryCommandPlanner
    planner=RepositoryCommandPlanner(campaign)
    with pytest.raises(ValueError,match='named prisoner has no authoritative custody group'):
        planner._validate_invariants(DiskOverlay(),[group_path,person_path])
