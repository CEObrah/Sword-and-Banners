from types import SimpleNamespace

from conftest import execute_production
from sword_runtime.production_planner import ProductionCampaignPlanner


def planner_for(campaign):
    p = ProductionCampaignPlanner(campaign)
    p._reset()
    return p


def test_generic_organization_conserves_people_money_and_force_ownership(campaign):
    p = planner_for(campaign)
    pop_before = int(p.read('state/population/qin.json')['population_total'])
    wallet_before = int(p.read('state/economy/player-wallet.json')['silver'])
    result = execute_production(campaign, 'organization_action', {
        'action': 'create',
        'organization_ref': 'organization_test_swordsmen',
        'name': 'Test Swordsmen Society',
        'organization_class': 'martial_society',
        'location_ref': 'loc_kanyou',
        'amount_silver': 100,
        'capacity': 20,
    }, request_id='org-create')
    p = planner_for(campaign)
    org = p.read(p.owner_path('organization_test_swordsmen'))
    treasury = p.read(p.owner_path(org['treasury_ref']))
    assert org['population_owned'] == 0
    assert org['linked_force_refs'] == []
    assert int(treasury['silver']) == 100
    assert int(p.read('state/economy/player-wallet.json')['silver']) == wallet_before - 100
    assert int(p.read('state/population/qin.json')['population_total']) == pop_before
    assert result.receipt.result['organization_ref'] == 'organization_test_swordsmen'


def test_generic_organization_project_spends_organization_treasury_and_real_local_inputs(campaign):
    p = planner_for(campaign)
    wallet_before = int(p.read('state/economy/player-wallet.json')['silver'])
    assert wallet_before >= 200
    execute_production(campaign, 'organization_action', {
        'action': 'create',
        'organization_ref': 'organization_test_builders',
        'name': 'Test Builders Guild',
        'organization_class': 'guild',
        'location_ref': 'loc_kanyou',
        'amount_silver': 200,
        'capacity': 20,
    }, request_id='org-project-create')
    p = planner_for(campaign)
    org_path = p.owner_path('organization_test_builders')
    org = p.read(org_path)
    treasury_path = p.owner_path(org['treasury_ref'])
    treasury_before = int(p.read(treasury_path)['silver'])
    pop_before = int(p.read('state/population/qin.json')['population_total'])

    ep, eco = p._private_economy('qin')
    _site_ref, region = p._local_economy_region('qin', eco, 'loc_kanyou')
    region.setdefault('commodity_stock', {})['construction_material_units'] = max(
        5000, int(region.get('commodity_stock', {}).get('construction_material_units', 0))
    )
    materials_before = int(region['commodity_stock']['construction_material_units'])
    cash_before = int(region.get('cash_silver', 0))
    p._sync_local_economy_aggregate(eco)
    p._write_private_economy(ep, eco)
    # Persist only this disposable fixture's local economy preparation.
    import json
    for path, doc in p._writes.items():
        out = campaign / path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
    p._reset()

    meta = p.read('state/meta.json')
    command = SimpleNamespace(
        command_type='institution_project', digest='organizationproject1234',
        actor_id='internal:sword-autonomy', expected_revision=int(meta['revision']), submitted_at=str(meta['time'])
    )
    result = p._start_funded_institution_project(command, {
        'institution_ref': 'organization_test_builders',
        'project_ref': 'project_org_public_well',
        'duration_hours': 24,
        'kind': 'construction',
        'magnitude': 1,
    })
    assert result['reserved_inputs']['funding_source_ref'] == org['treasury_ref']
    assert result['reserved_inputs']['silver'] > 0
    assert result['reserved_inputs']['construction_material_units'] > 0
    assert int(p.read(treasury_path)['silver']) == treasury_before - int(result['reserved_inputs']['silver'])
    ep2, eco2 = p._private_economy('qin')
    _site2, region2 = p._local_economy_region('qin', eco2, 'loc_kanyou')
    assert int(region2['commodity_stock']['construction_material_units']) == materials_before - int(result['reserved_inputs']['construction_material_units'])
    assert int(region2['cash_silver']) == cash_before + int(result['reserved_inputs']['silver'])
    assert int(p.read('state/population/qin.json')['population_total']) == pop_before


def test_stale_organization_route_cannot_substitute_another_exact_owner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    target_ref = "org.test.routing.target"
    decoy_ref = "org.test.routing.decoy"
    target_path = planner._organization_path(target_ref)
    decoy_path = planner._organization_path(decoy_ref)
    base = {
        "schema": "sword-independent-organization",
        "name": "Routing Fixture",
        "organization_class": "association",
        "state": "state_qin",
        "location_ref": "loc_kanyou",
        "status": "active",
        "capacity": 10,
        "population_owned": 0,
        "member_refs": [],
        "leader_refs": [],
        "linked_force_refs": [],
        "policies": {},
        "projects": [],
    }
    planner.put(target_path, {**base, "owner_id": target_ref})
    planner.put(decoy_path, {**base, "owner_id": decoy_ref, "name": "Wrong Organization"})
    index = planner._organization_index()
    index.setdefault("organizations", {})[target_ref] = decoy_path
    planner.put("state/organizations/index.json", index)

    resolved_path, resolved = planner._organization_exact(target_ref)
    assert resolved_path == target_path
    assert resolved["owner_id"] == target_ref
    assert resolved["name"] == "Routing Fixture"
