import json
import subprocess

from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime
from conftest import execute_production


def planner_for(campaign):
    p = ProductionCampaignPlanner(campaign)
    p._reset()
    return p


def write_fixture(campaign, path, doc):
    out = campaign / path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + '\n')






def flush_planner_writes(campaign, planner):
    for rel, doc in planner._writes.items():
        out = campaign / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
    for rel in planner._deletes:
        out = campaign / rel
        if out.exists():
            out.unlink()

def commit_fixture(campaign, message):
    subprocess.run(['git','-C',str(campaign),'add','-A'],check=True)
    subprocess.run(['git','-C',str(campaign),'commit','--quiet','-m',message],check=True)

def create_qin_to_zhao_sword_convoy(campaign):
    p = planner_for(campaign)
    kantan = p.read('state/markets/kantan.json')
    kantan['stock']['common_sword'] = 0
    write_fixture(campaign, 'state/markets/kantan.json', kantan)
    p = planner_for(campaign)
    at = str(p._world_time())
    p._settle_strategic_merchant_convoys('qin', at)
    flush_planner_writes(campaign, p)
    idx = p.read('state/economy/merchant-convoys.json')
    refs = [
        r for r in idx['active_refs']
        if p.read(idx['convoys'][r]).get('merchant_house_ref') == 'merchant_house_01'
        and 'common_sword' in p.read(idx['convoys'][r]).get('cargo', {})
    ]
    assert refs
    return p, idx, refs[0]


def test_strategic_merchant_convoy_owns_cargo_guards_and_silver_in_transit(campaign):
    p0 = planner_for(campaign)
    houses_before = p0.read('state/economy/merchant-houses.json')
    h_before = int(houses_before['houses']['merchant_house_01']['capital_silver'])
    _mpath, merc_before = p0._merchant_guard_pool()
    armed_before = int(merc_before['armed_total'])
    short_before = int(merc_before['short_notice_available_total'])
    ep, eco = p0._private_economy('qin')
    _site, src_region = p0._local_economy_region('qin', eco, 'loc_kanyou')
    cash_before = int(src_region['cash_silver'])
    source_before = int(p0.read('state/markets/kanyou.json')['stock']['common_sword'])

    p, idx, ref = create_qin_to_zhao_sword_convoy(campaign)
    convoy = p.read(idx['convoys'][ref])
    qty = int(convoy['cargo']['common_sword'])
    guard = convoy['guard_detail']
    guard_n = int(guard['personnel'])
    guard_wage = int(guard['wage_silver'])
    assert qty > 0 and convoy['status'] == 'in_transit' and convoy['wagon_equivalents'] >= 1
    assert guard_n > 0

    source_after = int(p.read('state/markets/kanyou.json')['stock']['common_sword'])
    houses_mid = p.read('state/economy/merchant-houses.json')
    h_mid = int(houses_mid['houses']['merchant_house_01']['capital_silver'])
    _ep2, eco2 = p._private_economy('qin')
    _site2, src_region2 = p._local_economy_region('qin', eco2, 'loc_kanyou')
    cash_mid = int(src_region2['cash_silver'])
    _mpath2, merc_mid = p._merchant_guard_pool()
    cost = int(convoy['purchase_cost_silver'])
    assert source_after == source_before - qty
    assert h_mid == h_before - cost - guard_wage
    assert cash_mid == cash_before + cost + guard_wage
    assert int(merc_mid['armed_total']) == armed_before
    assert int(merc_mid['short_notice_available_total']) == short_before - guard_n
    assert int(p.read('state/markets/kantan.json')['stock']['common_sword']) == 0

    arrival = str(CampaignTime.parse(convoy['arrives_at']).add_seconds(3600))
    _epz, ecoz = p._private_economy('zhao')
    _zsite, zregion = p._local_economy_region('zhao', ecoz, 'loc_kantan')
    zcash_before = int(zregion['cash_silver'])
    p._settle_arriving_merchant_convoys('zhao', arrival)
    convoy_after = p.read(idx['convoys'][ref])
    sold = int(convoy_after.get('arrival_sale', {}).get('sold', {}).get('common_sword', 0))
    revenue = int(convoy_after.get('arrival_sale', {}).get('revenue_silver', 0))
    assert sold > 0
    assert int(p.read('state/markets/kantan.json')['stock']['common_sword']) == sold
    h_after = int(p.read('state/economy/merchant-houses.json')['houses']['merchant_house_01']['capital_silver'])
    _epz2, ecoz2 = p._private_economy('zhao')
    _zsite2, zregion2 = p._local_economy_region('zhao', ecoz2, 'loc_kantan')
    _mpath3, merc_after = p._merchant_guard_pool()
    assert h_after == h_mid + revenue
    assert int(zregion2['cash_silver']) == zcash_before - revenue
    assert int(merc_after['armed_total']) == armed_before
    assert int(merc_after['short_notice_available_total']) == short_before
    assert int(convoy_after['guard_detail']['personnel']) == 0


def test_convoy_interception_requires_route_timing_and_conserves_cargo_and_guard_losses(campaign):
    p, idx, ref = create_qin_to_zhao_sword_convoy(campaign)
    convoy = p.read(idx['convoys'][ref])
    source_node = convoy['route_path'][0]
    formation_ref = 'formation_qin_wei_unit_01'
    formation_path = p.owner_path(formation_ref)
    formation = p.read(formation_path)
    formation['location_ref'] = source_node
    write_fixture(campaign, formation_path, formation)
    commit_fixture(campaign, 'merchant convoy interception fixture')

    _mpath, merc_before = p._merchant_guard_pool()
    armed_before = int(merc_before['armed_total'])
    cargo_before = dict(convoy['cargo'])
    before_personnel = int(formation['personnel'])
    result = execute_production(
        campaign,
        'merchant_convoy_action',
        {
            'action': 'interdict',
            'convoy_ref': ref,
            'formation_ref': formation_ref,
            'disposition': 'seize',
        },
        request_id='merchant-convoy-interdict',
    )
    outcome = result.receipt.result
    assert outcome['attacker_wins'] is True
    p = planner_for(campaign)
    convoy_after = p.read(idx['convoys'][ref])
    formation_after = p.read(formation_path)
    _mpath2, merc_after = p._merchant_guard_pool()
    assert convoy_after['status'] == 'seized'
    assert convoy_after['cargo'] == {}
    assert all(int(formation_after.get('captured_cargo', {}).get(k, 0)) >= int(v) for k, v in cargo_before.items())
    assert int(formation_after['personnel']) == before_personnel - int(outcome['attacker_losses'])
    assert int(merc_after['armed_total']) == armed_before - int(outcome['guard_losses'])
    assert ref not in p.read('state/economy/merchant-convoys.json')['active_refs']


def test_convoy_cannot_be_intercepted_from_wrong_route_node(campaign):
    p, idx, ref = create_qin_to_zhao_sword_convoy(campaign)
    formation_ref = 'formation_qin_wei_unit_01'
    # The baseline formation is elsewhere and must not be able to raid remotely.
    commit_fixture(campaign, 'merchant convoy remote interception fixture')
    import pytest
    with pytest.raises(ValueError, match='not on the convoy route|interception window'):
        execute_production(
            campaign,
            'merchant_convoy_action',
            {
                'action': 'interdict',
                'convoy_ref': ref,
                'formation_ref': formation_ref,
                'disposition': 'seize',
            },
            request_id='merchant-convoy-remote-interdict',
        )
