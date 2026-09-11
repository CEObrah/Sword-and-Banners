import json

from conftest import execute_internal


def _owners(campaign):
    return json.load(open(campaign / 'state/index/owner-index.json'))['owners']


def _formation(campaign, ref):
    return json.load(open(campaign / _owners(campaign)[ref]))


def _force(campaign):
    return json.load(open(campaign / 'state/forces/state-qin.json'))


def test_mixed_role_create_split_merge_and_dissolve_preserve_exact_roles(campaign):
    ref = 'formation_mixed_qin'
    child = 'formation_mixed_qin_child'
    location = 'loc_qin_regional_01'
    composition = {'line_infantry': 2400, 'missile_crossbow': 800, 'cavalry': 800}
    before = _force(campaign)

    execute_internal(campaign, 'formation_create', {
        'state': 'qin',
        'formation_ref': ref,
        'personnel': 4000,
        'composition': composition,
        'location_ref': location,
    })
    created = _formation(campaign, ref)
    force = _force(campaign)
    assert created['composition'] == composition
    assert 'establishment_composition' not in created  # full-strength mix is derived, not duplicated
    assert force['allocated_to_formations'][ref] == {'personnel': 4000, 'composition': composition}
    for role, count in composition.items():
        assert force['available_by_role'][role] == before['available_by_role'][role] - count

    execute_internal(campaign, 'formation_split', {
        'formation_ref': ref,
        'new_formation_ref': child,
        'personnel': 1500,
    })
    parent = _formation(campaign, ref)
    detached = _formation(campaign, child)
    assert sum(parent['composition'].values()) == 2500
    assert sum(detached['composition'].values()) == 1500
    assert set(parent['composition']) == set(composition)
    assert set(detached['composition']) == set(composition)
    for role, count in composition.items():
        assert parent['composition'].get(role, 0) + detached['composition'].get(role, 0) == count

    split_force = _force(campaign)
    assert split_force['allocated_to_formations'][ref]['composition'] == parent['composition']
    assert split_force['allocated_to_formations'][child]['composition'] == detached['composition']

    execute_internal(campaign, 'formation_merge', {'formation_refs': [ref, child]})
    merged = _formation(campaign, ref)
    assert merged['personnel'] == 4000
    assert merged['composition'] == composition
    assert _force(campaign)['allocated_to_formations'][ref]['composition'] == composition

    execute_internal(campaign, 'formation_dissolve', {'formation_ref': ref})
    after = _force(campaign)
    for role in composition:
        assert after['available_by_role'][role] == before['available_by_role'][role]


def test_mixed_role_reconstitution_restores_establishment_mix_instead_of_first_role(campaign):
    ref = 'formation_mixed_reconstitution_qin'
    child = 'formation_mixed_reconstitution_qin_child'
    location = 'loc_qin_regional_01'
    composition = {'line_infantry': 3000, 'missile_crossbow': 1000, 'cavalry': 500}

    execute_internal(campaign, 'formation_create', {
        'state': 'qin',
        'formation_ref': ref,
        'personnel': 4500,
        'authorized_strength': 5000,
        'composition': composition,
        'location_ref': location,
    })
    execute_internal(campaign, 'formation_split', {
        'formation_ref': ref,
        'new_formation_ref': child,
        'personnel': 1500,
    })
    parent = _formation(campaign, ref)
    child_after_split = _formation(campaign, child)
    assert parent['authorized_strength'] + child_after_split['authorized_strength'] == 5000
    before = dict(parent['composition'])
    execute_internal(campaign, 'formation_reconstitute', {
        'formation_ref': ref,
        'target_personnel': 3500,
    })
    rebuilt = _formation(campaign, ref)
    added = {role: rebuilt['composition'].get(role, 0) - before.get(role, 0) for role in rebuilt['composition']}
    assert rebuilt['personnel'] == 3500
    assert sum(rebuilt['composition'].values()) == 3500
    assert sum(value for value in added.values() if value > 0) == 500
    assert len([role for role, value in added.items() if value > 0]) >= 2
    assert _force(campaign)['allocated_to_formations'][ref]['composition'] == rebuilt['composition']
