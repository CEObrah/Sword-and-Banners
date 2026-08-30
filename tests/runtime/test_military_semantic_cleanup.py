import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(rel):
    return json.loads((ROOT / rel).read_text())


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def test_no_permanent_scout_or_support_job_troop_species():
    types = read('game/data/organization/troop-types.json')['types']
    forbidden = {'scout','mounted_scout','engineer','logistics','signal','sapper','support_staff'}
    assert forbidden.isdisjoint(types)

    for p in list((ROOT / 'state/forces').glob('*.json')) + list((ROOT / 'state/formations').glob('*.json')):
        data = json.loads(p.read_text())
        for node in walk(data):
            # Specialty text may still say reconnaissance/sapper; conserved troop
            # roles and troop_type fields may not resurrect those as body species.
            if 'role' in node:
                assert node.get('role') not in forbidden, p
            assert node.get('troop_type') not in forbidden, p

    for p in (ROOT / 'state/merc').rglob('*.json'):
        data = json.loads(p.read_text())
        for node in walk(data):
            assert node.get('troop_type') not in forbidden


def test_military_mount_authority_has_no_riding_horse_species():
    items = read('game/data/items.json')['record_index']
    assert 'horse_riding' not in items
    for p in (ROOT / 'state/mounts').glob('*.json'):
        data = json.loads(p.read_text())
        assert 'horse_riding' not in data.get('types', {})
        assert all('horse_riding' not in row for row in data.get('regional_reserve', {}).values())
        assert all('horse_riding' not in row for row in data.get('allocated_to_formations', {}).values())
    for p in (ROOT / 'state/formations').glob('*.json'):
        data = json.loads(p.read_text())
        assert 'horse_riding' not in data.get('mounts', {})


def test_scouting_capability_remains_available_as_skill_and_training():
    programs = read('game/data/mil/deterministic-training-programs.json')
    assert 'program.reconnaissance' in programs.get('programs', programs)
    # The cleanup removes the manpower species, not reconnaissance knowledge.
    jo = read('state/forces/jo.json')
    cohort = jo['cohort_ledger']['cohorts']['cohort_jo_scout']
    assert cohort['role'] == 'light_infantry'
    assert cohort['skill_means']['Scouting'] > 0
    assert 'reconnaissance_specialized' in cohort['tags']
