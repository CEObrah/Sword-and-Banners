from __future__ import annotations

import json
from pathlib import Path

from sword_runtime.land_development import site_enclosure_layers, urban_capacity_land_budget, validate_land_registry

ROOT=Path(__file__).resolve().parents[2]
MAJOR=(
    ('qin','loc_kanyou'),('qin','loc_sai'),('zhao','loc_kantan'),('zhao','loc_gyou'),
    ('chu','loc_shintei'),('wei','loc_dairyou'),('wei','loc_keiyou'),('han','loc_han_capital'),
    ('yan','loc_ji'),('qi','loc_ei'),
)

def load(rel): return json.loads((ROOT/rel).read_text())

def test_major_city_parcels_conserve_region_land_and_fit_saved_support():
    land=load('state/development/land.json'); infra=load('state/infrastructure/settlements.json')['sites']; rules=load('game/data/mechanics/land-development.json')
    assert validate_land_registry(land)==[]
    for state,ref in MAJOR:
        site=land['sites'][ref]; pop=load(f'state/population/{state}.json')['local_population']['sites'][ref]
        cap=int(infra[ref]['effective_resident_support_capacity_people'])
        total=int(pop['civilian_population'])+int(pop['service_population'])
        assert cap>=total
        # Physical city geometry is a saved planning baseline, not a live mirror of
        # today's mutable service headcount. Military and training parcels must
        # encode the same original permanent-service planning population.
        planning = rules['urban_capacity_planning']
        military_rate = float(planning['military_barracks_land_km2_per_1000_permanent_service']) / 1000.0
        training_rate = float(planning['training_land_km2_per_1000_permanent_service']) / 1000.0
        military_service = float(site['enclosed_land_use_km2']['military']) / military_rate
        training_service = float(site['enclosed_land_use_km2']['training']) / training_rate
        assert abs(military_service - training_service) <= 1.0
        planned_service = int(round((military_service + training_service) / 2.0))
        assert 0 <= planned_service <= cap
        budget = urban_capacity_land_budget(
            resident_support_capacity=cap,
            civilian_capacity=max(0, cap - planned_service),
            permanent_service_population=planned_service,
            site_kind=site['kind'],
            rules=rules,
            preserved_external_land_km2=site.get('external_land_use_km2', {}),
        )
        fixed = budget['fixed_enclosed_land_use_km2']
        assert abs(float(site['enclosed_land_use_km2']['residential']) - float(fixed['residential'])) <= 1e-3
        assert abs(float(site['enclosed_land_use_km2']['military']) - float(fixed['military'])) <= 1e-3
        assert abs(float(site['enclosed_land_use_km2']['training']) - float(fixed['training'])) <= 1e-3
        circulation=(float(site['enclosed_land_use_km2'].get('transport',0))+float(site['external_land_use_km2'].get('transport',0)))/float(site['parcel_area_km2'])
        assert circulation+1e-6>=float(rules['site_class_circulation_minimum_fraction']['capital' if site['kind']=='capital' else 'city'])
        region=land['regions'][site['region_ref']]
        assert float(region['nested_site_parcels_km2']) >= float(site['parcel_area_km2'])


def test_capitals_and_cities_have_generic_nested_defended_layers():
    land=load('state/development/land.json')
    for _state,ref in MAJOR:
        layers=site_enclosure_layers(land,ref)
        assert len(layers)==(3 if land['sites'][ref]['kind']=='capital' else 2)
        areas=[float(x['area_km2']) for x in layers]
        assert all(a>b for a,b in zip(areas,areas[1:]))
        assert layers[0]['kind']=='outer_city'
        assert int(layers[0]['protected_population_capacity'])>0
        assert all(float(layer['fortification']['constructed_outer_perimeter_km'])>0 for layer in layers)

def test_hot_fortification_profile_reads_current_land_geometry(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    p=ProductionCampaignPlanner(campaign); p._reset()
    land=p.read('state/development/land.json')['sites']['loc_kanyou']
    profile=p._fortification_profile_for_site('loc_kanyou')
    assert profile['physical_baseline']['constructed_wall_centerline_perimeter_km']==land['fortification']['constructed_outer_perimeter_km']
    assert profile['physical_baseline']['outer_wall']['tower_count']==land['fortification']['tower_count']
    assert len(profile['current_enclosure_layers'])==3
