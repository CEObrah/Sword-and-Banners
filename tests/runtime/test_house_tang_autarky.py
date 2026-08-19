import json


def test_tang_manor_autarky_uses_internal_finite_production_and_storage(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    from sword_runtime.house_tang_production import settle_house_tang_estate_autarky

    planner=ProductionCampaignPlanner(campaign)
    before=json.load(open(campaign/'state/depots/house-tang.json'))
    before_qin=json.load(open(campaign/'state/economy/private/qin.json'))
    result=settle_house_tang_estate_autarky(planner,'244-BCE-08-28T06:00:00+08:00')
    after=planner.read('state/depots/house-tang.json')
    after_qin=planner.read('state/economy/private/qin.json')

    assert result['civilian_residents']==725000
    assert result['resident_military_bodies']>160000
    assert result['resident_house_mounts']>=6000
    assert result['food_output_kg']==22733333
    assert result['food_consumed_kg']>19000000
    assert result['food_shortfall_kg']==0
    assert result['fodder_shortfall_kg']==0
    assert 0 <= after['stocks']['grain_kg'] <= after['storage_capacity']['grain_kg']
    assert 0 <= after['stocks']['fodder_kg'] <= after['storage_capacity']['fodder_kg']
    assert after_qin==before_qin, 'autarkic survival production must not debit Qin private-economy imports'
    assert after['stocks']['grain_kg'] > before['stocks']['grain_kg']


def test_tang_manor_physical_damage_reduces_autarkic_output(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    from sword_runtime.house_tang_production import settle_house_tang_estate_autarky

    p=campaign/'state/infrastructure/settlements.json'
    infrastructure=json.load(open(p))
    infrastructure['sites']['loc_tang_manor']['productive_assets']['staple_agriculture_condition']=0.5
    p.write_text(json.dumps(infrastructure,indent=2)+'\n')
    planner=ProductionCampaignPlanner(campaign)
    result=settle_house_tang_estate_autarky(planner,'244-BCE-08-28T06:00:00+08:00')
    assert result['food_output_kg'] in {11366666,11366667}
    assert result['productive_condition']['food']==0.5
