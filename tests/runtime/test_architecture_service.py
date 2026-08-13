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
        data=r.json()
        assert data['limits']['ooc_is_read_only'] is True
        assert data['object_read_policy'].startswith('Use only exact IDs')
        assert all(x['information_ref']!='secret_api_test' for x in data['known_information'])
        assert data['campaign']['player_id']==meta(campaign)['player_id']


def test_play_context_scene_projection_freshness_and_readiness(campaign):
    from sword_runtime.api.app import create_app
    token='p'*48
    with TestClient(create_app(campaign,token)) as client:
        headers={'Authorization':f'Bearer {token}'}
        data=client.get('/v1/play/context',headers=headers).json()
        assert data['scene']['projection_status'] in {'fresh','fresh_runtime_projection'}
        if data['controlled_formations']:
            formation=data['controlled_formations'][0]
            for field in ('readiness','morale','cohesion','training_progress','fatigue','logistics'):
                assert field in formation

        scene_path=campaign/'state/scene.json'
        scene=json.load(open(scene_path))
        scene_refs={str(x) for x in scene.get('relevant_owner_ids',[]) if isinstance(x,str)}
        intrinsic_people={data['campaign']['player_id']} | {
            str(f.get('commander_ref')) for f in data['controlled_formations']
            if isinstance(f.get('commander_ref'),str) and str(f.get('commander_ref')).startswith('char_')
        }
        intrinsic_objects={
            str(f.get('formation_ref')) for f in data['controlled_formations']
            if isinstance(f.get('formation_ref'),str)
        }
        scene_only_people={x for x in scene_refs if x.startswith('char_')} - intrinsic_people
        scene_only_objects={x for x in scene_refs if not x.startswith('char_')} - intrinsic_objects

        # Scene projections are presentation caches, not authority. Mutate only
        # this disposable fixture to simulate an authored projection left behind
        # after a state/time change. The service must discard its transient claims
        # and immediately provide a revision-matched minimal projection from live
        # owners and already-triggered player-visible facts.
        scene['world_time']='stale-projection-test'
        scene_path.write_text(json.dumps(scene,indent=2)+'\n')
        stale=client.get('/v1/play/context',headers=headers).json()
        projected=stale['scene']
        assert projected['projection_status']=='fresh_runtime_projection'
        assert projected['projected_revision']==stale['campaign']['revision']
        assert projected['projected_at']==stale['campaign']['world_time']
        assert projected['unresolved_decision'] is None
        assert projected['known_clock_boundaries']==[]
        assert projected['location_id']==stale['player']['location']
        assert projected['projection_provenance']=='exact_current_owners_triggered_events_and_typed_player_attempts'
        if projected.get('continuity_anchor') is not None:
            assert projected['continuity_anchor']['presentation_only'] is True
        visible_handles={x['interaction_ref'] for x in stale.get('interaction_handles',[])}
        assert all(x.get('interaction_ref') in visible_handles for x in projected['observable_pressures'])
        assert scene_only_people.isdisjoint(set(stale['permitted_person_ids']))
        assert scene_only_objects.isdisjoint(set(stale['permitted_object_refs']))


def test_player_api_forbids_internal_actor(campaign):
    from sword_runtime.api.app import create_app
    token='y'*48; m=meta(campaign)
    body={'campaign_id':m['campaign_id'],'request_id':'api-internal','actor_id':'internal:sword-autonomy','command_type':'repair','expected_revision':m['revision'],'submitted_at':m['time'],'payload':{'path':'state/player.json','changes':{}},'mode':'maintenance'}
    with TestClient(create_app(campaign,token)) as client:
        r=client.post('/v1/commands/execute',headers={'Authorization':f'Bearer {token}'},json=body)
        assert r.status_code==403


def test_api_uses_one_runtime_instance_and_explicit_runtime_root(campaign,tmp_path):
    from sword_runtime.api.app import create_app
    token='z'*48
    runtime_root=tmp_path/'service-runtime'
    app=create_app(campaign,token,runtime_root)
    assert app.state.campaign_operations.runtime is app.state.sword_runtime
    assert app.state.sword_runtime.runtime_dir == runtime_root.resolve()
    assert app.state.sword_runtime.replicator is None
    assert app.state.sword_runtime.planner.PLAYER_ACTOR == meta(campaign)['player_id']


def test_mcp_attestation_is_exact_short_lived_and_tamper_evident():
    from sword_runtime.api.mcp import McpOAuthSettings, _preview_attestation, _verify_preview_attestation
    from sword_runtime.commands import CommandEnvelope
    oauth=McpOAuthSettings(
        public_url='https://example.test/mcp',issuer_url='https://issuer.test/',jwks_url='https://issuer.test/.well-known/jwks.json',audience='https://example.test/mcp',algorithms=('RS256',),read_scope='sword:read',write_scope='sword:write',allowed_subjects=('auth0|player',),allowed_client_ids=(),preview_secret='A'*43,allowed_origins=('https://chatgpt.com',)
    )
    command=CommandEnvelope(campaign_id='campaign',request_id='request-1',actor_id='char_tang_wei',command_type='scene_consequence',expected_revision=1,submitted_at='245-BCE-01-01T00:00:00+08:00',payload={'summary':'test'})
    proof=_preview_attestation(command,oauth,now=1000)
    assert _verify_preview_attestation(command,proof,oauth,now=1001)
    assert not _verify_preview_attestation(command,proof+'x',oauth,now=1001)
    changed=CommandEnvelope(campaign_id='campaign',request_id='request-1',actor_id='char_tang_wei',command_type='scene_consequence',expected_revision=1,submitted_at='245-BCE-01-01T00:00:00+08:00',payload={'summary':'different'})
    assert not _verify_preview_attestation(changed,proof,oauth,now=1001)
    assert not _verify_preview_attestation(command,proof,oauth,now=1301)


def test_railway_and_mcp_files_present():
    root=Path(__file__).resolve().parents[2]
    skill=root/'plugins/sword-and-banners/skills/sword-and-banners-game-master'
    assert (root/'railway.toml').is_file()
    assert not (root/'railway.json').exists()
    railway=(root/'railway.toml').read_text()
    assert '"**"' in railway and '"!/state/**"' in railway
    assert (root/'runtime/sword_runtime/bootstrap.py').is_file()
    assert (root/'runtime/sword_runtime/api/mcp.py').is_file()
    assert (root/'runtime/sword_runtime/api/mcp_extensions.py').is_file()
    assert (root/'runtime/sword_runtime/service_runtime.py').is_file()
    assert (root/'docs/RUNTIME_SERVICE_DEPLOYMENT.md').is_file()
    assert (skill/'SKILL.md').is_file()
    for name in ('narration.md','choices.md','player-interface.md','runtime-architecture.md','repository-map.md','ooc-dev.md','live-play-review.md'):
        assert (skill/'references'/name).is_file()
    for obsolete in ('AGENTS.md','DEPLOYMENT.md','PLAYER_INTERFACE.md','REPOSITORY_MAP.md','RUNTIME.md','VOICE.md'):
        assert not (root/obsolete).exists()
    py=(root/'pyproject.toml').read_text()
    assert 'mcp==2.0.0' in py and 'PyJWT[crypto]==2.13.0' in py
    mcp_source=(root/'runtime/sword_runtime/api/mcp.py').read_text()
    extension_source=(root/'runtime/sword_runtime/api/mcp_extensions.py').read_text()
    app_source=(root/'runtime/sword_runtime/api/app.py').read_text()
    assert 'from mcp.server.mcpserver import MCPServer' in mcp_source
    assert 'get_play_context' in mcp_source
    assert 'preview_attestation' in mcp_source
    assert 'sword:read' in mcp_source and 'sword:write' in mcp_source
    for tool_name in ('get_command_contract','list_controlled_formations','list_known_information','list_interaction_handles'):
        assert f'name="{tool_name}"' in extension_source
    assert 'install_extended_tools' in app_source


def test_gameplay_router_has_no_version_ids():
    root=Path(__file__).resolve().parents[2]
    rule=(root/'game/rules/process.md').read_text().lower()
    assert 'v1' not in rule and 'v2' not in rule and 'release history' not in rule
