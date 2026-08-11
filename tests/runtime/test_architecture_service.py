import json, os
from pathlib import Path
from fastapi.testclient import TestClient
from conftest import execute, execute_internal, meta

def test_runtime_game_state_separation():
    root=Path(__file__).resolve().parents[2]
    assert (root/'runtime/sword_runtime').is_dir()
    assert (root/'game/data').is_dir()
    assert (root/'state/runtime.json').is_file()
    assert not (root/'state/process-state').exists()
    assert not (root/'state/unit').exists()
    assert not (root/'state/force-pool').exists()
    assert (root/'archive/legacy-execution').is_dir()

def test_no_cross_game_runtime_imports():
    root=Path(__file__).resolve().parents[2]
    texts='\n'.join(p.read_text(errors='ignore') for p in (root/'runtime/sword_runtime').rglob('*.py'))
    assert 'import shinobi' not in texts.lower()
    assert 'from shinobi' not in texts.lower()

def test_world_density_and_cold_hosts():
    root=Path(__file__).resolve().parents[2]
    houses=json.load(open(root/'game/data/world/noble-houses.json'))
    locations=json.load(open(root/'game/data/world/locations.json'))
    runtime=json.load(open(root/'state/runtime.json'))
    assert len(houses['houses']) >= 40
    assert len(locations['locations']) >= 70
    # Host count grows when exact named-person/interstate actors become causal.
    # Assert required actor coverage rather than freezing an obsolete total.
    assert sum(1 for h in runtime['hosts'].values() if h.get('kind')=='mercenary') == 60
    assert sum(1 for h in runtime['hosts'].values() if h.get('kind')=='person') >= 70
    assert sum(1 for h in runtime['hosts'].values() if h.get('kind')=='interstate') == 1
    assert all(runtime['metrics'][k]==0 for k in ('global_person_scans','global_faction_scans','global_force_scans','global_house_scans'))

def test_champions_doctrine_is_principal_survival():
    root=Path(__file__).resolve().parents[2]
    for name in ('tang-champions-first.json','tang-champions-second.json'):
        f=json.load(open(root/'state/formations'/name))
        assert f['doctrine_behavior']['principal_ref']=='char_tang_wei'
        assert f['doctrine_behavior']['primary_success_condition']=='Tang Wei returns alive'
        assert f['doctrine_behavior']['extraction_priority']==100

def test_ownership_is_distinct_from_command():
    root=Path(__file__).resolve().parents[2]
    f=json.load(open(root/'state/formations/tang-champions-first.json'))
    assert f['owner_force_ref']=='force_house_tang'
    assert f['administrative_owner']=='char_tang_wei'
    assert 'command_authority' in f

def test_economy_reference_balance():
    root=Path(__file__).resolve().parents[2]
    e=json.load(open(root/'game/data/mechanics/economy-gold.json'))
    assert e['service_issue']['standard_service_kit_is_state_issue'] is True
    assert float(e['wages']['professional_soldier_monthly_silver']) > float(e['wages']['unskilled_monthly_silver'])
    assert e['prices_silver']['common_sword'] <= e['wages']['professional_soldier_monthly_silver']*2

def test_api_auth_and_player_safe_information(campaign):
    from sword_runtime.api.app import create_app
    execute_internal(campaign,'information_create',{'information_ref':'secret_api_test','claim':'hidden Zhao disposition','confidence':'0.8','knowers':['char_riboku']})
    token='x'*48
    with TestClient(create_app(campaign,token)) as client:
        assert client.get('/health').status_code==200
        assert client.get('/v1/play/context').status_code==401
        r=client.get('/v1/play/context',headers={'Authorization':f'Bearer {token}'})
        assert r.status_code==200
        data=r.json(); assert data['policy'].startswith('hidden state omitted')
        assert all(x['information_ref']!='secret_api_test' for x in data['known_information'])

def test_player_api_forbids_internal_actor(campaign):
    from sword_runtime.api.app import create_app
    token='y'*48; m=meta(campaign)
    body={'campaign_id':m['campaign_id'],'request_id':'api-internal','actor_id':'internal:sword-autonomy','command_type':'repair','expected_revision':m['revision'],'submitted_at':m['time'],'payload':{'path':'state/player.json','changes':{}},'mode':'maintenance'}
    with TestClient(create_app(campaign,token)) as client:
        r=client.post('/v1/commands/execute',headers={'Authorization':f'Bearer {token}'},json=body)
        assert r.status_code==403

def test_railway_and_mcp_files_present():
    root=Path(__file__).resolve().parents[2]
    assert (root/'railway.json').is_file()
    assert (root/'runtime/sword_runtime/bootstrap.py').is_file()
    assert (root/'runtime/sword_runtime/api/mcp.py').is_file()
    py=(root/'pyproject.toml').read_text()
    assert 'mcp==2.0.0' in py
    mcp_source=(root/'runtime/sword_runtime/api/mcp.py').read_text()
    assert 'from mcp.server import MCPServer' in mcp_source
    assert 'mcp.server.fastmcp' not in mcp_source

def test_gameplay_router_has_no_version_ids():
    root=Path(__file__).resolve().parents[2]
    rule=(root/'game/rules/process.md').read_text().lower()
    assert 'v1' not in rule and 'v2' not in rule and 'release history' not in rule
