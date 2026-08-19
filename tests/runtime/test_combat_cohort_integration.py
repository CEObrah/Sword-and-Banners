from __future__ import annotations

import json
from copy import deepcopy

from conftest import execute_internal, execute_production_internal, activate_operation


def _cohort(role: str, *, skill: float, attribute: float, count: int = 1000):
    skills = {
        "Spear": skill, "Sword": skill, "Shield": skill, "Defense": skill,
        "Formation Fighting": skill, "Athletics": skill, "Mass Combat": skill,
        "Bow": skill, "Crossbow": skill, "Riding": skill, "Scouting": skill,
        "Survival": skill,
    }
    attrs = {k: attribute for k in ("Strength","Agility","Endurance","Toughness","Coordination","Awareness","Composure")}
    return {
        "cohort_id":"cohort_test", "role":role, "count":count,
        "skill_means":skills, "attribute_means":attrs,
        "reserve_by_location":{}, "allocated_by_formation":{"formation_test":count},
        "verified_combat_exposure_hours_per_person":0.0, "field_engagements":0,
    }


def _formation(role: str, *, count: int = 1000, arrows: int = 0, bolts: int = 0):
    return {
        "formation_ref":"formation_test", "personnel":count, "composition":{role:count},
        "cohort_composition":[{"cohort_id":"cohort_test","count":count}],
        "cohesion":90, "logistics":{"food_kg":count*2,"fodder_kg":0,"war_arrows":arrows,"war_bolts":bolts},
        "mounts":{},
    }


def _force(cohort):
    return {"cohort_ledger":{"cohorts":{"cohort_test":cohort}}}


def test_cohort_stats_change_mass_combat_capability(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner
    planner=RepositoryCommandPlanner(campaign)
    low_c=_cohort("line_infantry",skill=20,attribute=45); high_c=_cohort("line_infantry",skill=125,attribute=105)
    f=_formation("line_infantry")
    low=planner._formation_combat_snapshot(f,_force(low_c),terrain_kind="open")
    high=planner._formation_combat_snapshot(f,_force(high_c),terrain_kind="open")
    assert high["melee_capability_mean"] > low["melee_capability_mean"] * 3
    assert high["capability_factor"] > low["capability_factor"]


def test_reach_reverses_when_spear_line_is_compressed(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner
    planner=RepositoryCommandPlanner(campaign)
    spear=[{"count":100,"melee_reach_m":2.35,"melee_minimum_range_m":0.80}]
    sword=[{"count":100,"melee_reach_m":0.85,"melee_minimum_range_m":0.15}]
    spear_open=planner._combat_reach_factor(spear,sword,90,"open")
    sword_open=planner._combat_reach_factor(sword,spear,90,"open")
    spear_cramped=planner._combat_reach_factor(spear,sword,15,"hall")
    sword_cramped=planner._combat_reach_factor(sword,spear,15,"hall")
    assert spear_open > sword_open
    assert spear_cramped < sword_cramped


def test_arrows_and_bolts_are_finite_and_weapon_specific(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner
    planner=RepositoryCommandPlanner(campaign)
    archer=_cohort("archer",skill=90,attribute=80,count=100); af=_formation("archer",count=100)
    arows=planner._combat_cohort_snapshot(af,_force(archer))
    zero=planner._combat_ammunition_plan(arows,{"war_arrows":0,"war_bolts":10000},4)
    partial=planner._combat_ammunition_plan(arows,{"war_arrows":90,"war_bolts":10000},4)
    full=planner._combat_ammunition_plan(arows,{"war_arrows":10000,"war_bolts":0},4)
    assert zero["consumed_by_resource"]["war_arrows"] == 0
    assert planner._combat_ranged_factor(arows,zero,[]) == 1.0
    assert partial["consumed_by_resource"]["war_arrows"] == 90
    assert planner._combat_ranged_factor(arows,full,[]) > planner._combat_ranged_factor(arows,partial,[]) > 1.0

    cross=_cohort("crossbow_infantry",skill=90,attribute=80,count=100); cf=_formation("crossbow_infantry",count=100)
    crows=planner._combat_cohort_snapshot(cf,_force(cross))
    wrong=planner._combat_ammunition_plan(crows,{"war_arrows":10000,"war_bolts":0},4)
    right=planner._combat_ammunition_plan(crows,{"war_arrows":0,"war_bolts":10000},4)
    assert wrong["consumed_by_resource"]["war_bolts"] == 0
    assert right["consumed_by_resource"]["war_bolts"] > 0


def test_exact_commander_is_separate_from_ouki_cohort_mean(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner
    planner=RepositoryCommandPlanner(campaign)
    _, formation, force=planner._combat_prepare_formation("formation_house_ouki_household_01")
    assert formation["commander_ref"] is None
    assert formation["higher_command_ref"] == "cmdgrp.house_ouki_household.field_army"
    snap=planner._formation_combat_snapshot(formation,force,terrain_kind="open")
    ouki=next(x for x in snap["named_participants"] if x["person_ref"]=="char_ouki")
    assert ouki["representation"] == "sab_character"
    assert ouki["role"] == "higher_commander"
    assert ouki["command_scope"] == "higher"
    assert ouki["command_score"] > 150
    assert ouki["direct_combat_score"] > 150
    assert "equivalent_frontline_bodies" not in ouki
    assert "ranged_equivalent_bodies" not in ouki
    assert ouki["included_in_personnel"] is False
    assert ouki["loadout_id"] == "loadout_named_glaive"
    assert ouki["melee_skill"] == "Glaive"
    assert ouki["melee_weapon_id"] == "weapon_glaive_heavy"
    assert ouki["melee_reach_m"] == 2.0
    assert snap["command_effects"]["higher_command_mode"] == "higher_commander"
    assert snap["command_effects"]["higher_command_score"] > 150
    assert snap["cohort_personnel"] == formation["personnel"]


def test_battle_trims_cohorts_and_awards_survivor_experience_through_production_planner(campaign):
    # Keep the battle local: no strategic movement is needed to verify cohort settlement.
    for side in ("a","b"):
        execute_internal(campaign,"person_materialize",{"state":"qin","person_ref":f"char_combat_cohort_{side}","name":f"Cohort {side} Commander","birth_date":"270-BCE-01-01","role":"command_personnel","source_location_ref":"loc_qin_eastern_depot"})
        execute_internal(campaign,"formation_create",{"state":"qin","formation_ref":f"formation_combat_cohort_{side}","role":"line_infantry","personnel":500,"location_ref":"loc_qin_eastern_depot","commander_ref":f"char_combat_cohort_{side}"})
        execute_internal(campaign,"resupply",{"formation_ref":f"formation_combat_cohort_{side}","food_kg":500})
        execute_internal(campaign,"formation_mobilize",{"formation_ref":f"formation_combat_cohort_{side}"})
    op=activate_operation(campaign,"operation_combat_cohort_integration",["formation_combat_cohort_a","formation_combat_cohort_b"],"loc_qin_eastern_depot")
    idx=json.load(open(campaign/'state/index/owner-index.json'))['owners']
    before_force=json.load(open(campaign/idx['force_state_qin']))
    a_before=json.load(open(campaign/idx['formation_combat_cohort_a']))
    before_cids=[x['cohort_id'] for x in a_before['cohort_composition']]
    before_exp={cid:float(before_force['cohort_ledger']['cohorts'][cid].get('verified_combat_exposure_hours_per_person',0)) for cid in before_cids}
    result=execute_production_internal(campaign,"battle_resolve",{"attacker_formation_refs":["formation_combat_cohort_a"],"defender_formation_refs":["formation_combat_cohort_b"],"operation_ref":op,"objective":"cohort integration test"})
    after_force=json.load(open(campaign/idx['force_state_qin']))
    a_after=json.load(open(campaign/idx['formation_combat_cohort_a']))
    assert result.receipt.result['casualties']['formation_combat_cohort_a'] > 0
    phases=result.receipt.result.get('contact_phases',[])
    assert [x.get('phase') for x in phases] == ['opening','sustained','resolution']
    assert all('formation_combat_cohort_a' in x.get('formation_states',{}) for x in phases)
    assert sum(int(x['count']) for x in a_after['cohort_composition']) == int(a_after['personnel'])
    survivor_cids=[x['cohort_id'] for x in a_after['cohort_composition']]
    assert survivor_cids
    assert all(float(after_force['cohort_ledger']['cohorts'][cid].get('verified_combat_exposure_hours_per_person',0)) > 0 for cid in survivor_cids)
    assert all(int(after_force['cohort_ledger']['cohorts'][cid].get('field_engagements',0)) >= 1 for cid in survivor_cids)


def test_commander_and_deputy_remain_separate_named_combatants(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner
    planner = RepositoryCommandPlanner(campaign)
    _, formation, force = planner._combat_prepare_formation("formation_tang_champions_first")
    snap = planner._formation_combat_snapshot(formation, force, terrain_kind="open")
    by_ref = {row["person_ref"]: row for row in snap["named_participants"]}
    assert by_ref["char_duan_jin"]["role"] == "commander"
    assert by_ref["char_shen_rui"]["role"] == "deputy"
    assert by_ref["char_duan_jin"]["command_score"] > 100
    assert by_ref["char_shen_rui"]["command_score"] > 100
    assert by_ref["char_duan_jin"]["included_in_personnel"] is False
    assert by_ref["char_shen_rui"]["included_in_personnel"] is False
    assert snap["cohort_personnel"] == formation["personnel"]


def test_person_lite_inside_personal_formation_is_separate_without_cloning_body(campaign):
    from conftest import execute_internal
    from sword_runtime.engine import RepositoryCommandPlanner

    campaign_ref = "recruitment.test.person-lite-battle"
    execute_internal(campaign, "recruitment_campaign_start", {
        "state": "qin", "campaign_ref": campaign_ref, "applicant_count": 40,
        "destination_force_ref": "force_tang_wei_personal", "role": "household_retainer",
        "location_ref": "loc_tang_manor_garrison_yard",
    })
    execute_internal(campaign, "recruitment_campaign_stage", {
        "campaign_ref": campaign_ref, "selection_profile": "wei_basic_eligibility", "retain_count": 20,
    })
    execute_internal(campaign, "recruitment_campaign_finalize", {"campaign_ref": campaign_ref})
    execute_internal(campaign, "formation_create", {
        "state": "qin", "force_ref": "force_tang_wei_personal",
        "formation_ref": "formation_test_person_lite_retinue", "role": "household_retainer",
        "personnel": 20, "equipment_units": 0,
    })

    planner = RepositoryCommandPlanner(campaign)
    _, before_formation = planner._load_formation("formation_test_person_lite_retinue")
    before_anonymous = sum(int(row["count"]) for row in before_formation["cohort_composition"])
    assert before_anonymous == 20

    execute_internal(campaign, "person_materialize", {
        "state": "qin", "person_ref": "char_test_person_lite_battle", "name": "Battle Standout",
        "personal_force_ref": "force_tang_wei_personal", "role": "household_retainer",
        "representation": "person_lite", "formation_ref": "formation_test_person_lite_retinue",
        "source_location_ref": "loc_tang_manor_garrison_yard",
    })

    planner = RepositoryCommandPlanner(campaign)
    _, formation, force = planner._combat_prepare_formation("formation_test_person_lite_retinue")
    anonymous = sum(int(row["count"]) for row in formation["cohort_composition"])
    named = {row["person_ref"]: row for row in planner._combat_named_participants(formation, force)}
    standout = named["char_test_person_lite_battle"]
    assert formation["personnel"] == 20
    assert anonymous == 19
    assert standout["representation"] == "person-lite"
    assert standout["included_in_personnel"] is True
    assert standout["loadout_id"] == "loadout_escort_guard"
    assert standout["melee_weapon_id"] == "weapon_spear_long"
    assert standout["melee_reach_m"] == 2.35
    assert standout["ammunition_resource"] == "war_arrows"
    assert int(force["materialized_people"]["char_test_person_lite_battle"]) == 1
    person_path = json.load(open(campaign/'state/index/owner-index.json'))['owners']['char_test_person_lite_battle']
    person = RepositoryCommandPlanner(campaign).read(person_path)
    assert person['equipment_custody']['mode'] == 'formation_issue_slot'
    assert person['equipment_custody']['formation_ref'] == 'formation_test_person_lite_retinue'


def test_field_battle_consumes_finite_crossbow_bolts_with_named_commander_ammo_separate(campaign):
    from conftest import execute_internal, activate_operation
    from sword_runtime.engine import RepositoryCommandPlanner

    qref="formation_test_bolt_crossbow"; zref="formation_test_bolt_target"
    qcmd="char_test_bolt_qin_commander"; zcmd="char_test_bolt_zhao_commander"
    execute_internal(campaign,"person_materialize",{"state":"qin","person_ref":qcmd,"name":"Bolt Test Qin Commander","birth_date":"270-BCE-01-01","role":"command_personnel","source_location_ref":"loc_qin_eastern_depot"})
    execute_internal(campaign,"person_materialize",{"state":"zhao","person_ref":zcmd,"name":"Bolt Test Zhao Commander","birth_date":"270-BCE-01-01","role":"command_personnel","source_location_ref":"loc_zhao_regional_01"})
    execute_internal(campaign,"formation_create",{"state":"qin","formation_ref":qref,"role":"missile_crossbow","personnel":200,"location_ref":"loc_qin_eastern_depot","commander_ref":qcmd})
    execute_internal(campaign,"formation_create",{"state":"zhao","formation_ref":zref,"role":"line_infantry","personnel":200,"location_ref":"loc_zhao_regional_01","commander_ref":zcmd})
    # Both formations are at their state depots. Move the Zhao formation to Qin's eastern depot
    # only after supplying enough food for the route; keep the actual contact local to Qin.
    execute_internal(campaign,"resupply",{"formation_ref":qref,"food_kg":500,"war_arrows":5000,"war_bolts":2400})
    execute_internal(campaign,"formation_mobilize",{"formation_ref":qref})
    execute_internal(campaign,"resupply",{"formation_ref":zref,"food_kg":2000})
    execute_internal(campaign,"formation_mobilize",{"formation_ref":zref})

    # Use the existing route helper from conftest for exact strategic movement.
    from conftest import move_formation_internal
    move_formation_internal(campaign,zref,"loc_qin_eastern_depot")
    op=activate_operation(campaign,"operation_test_bolt_consumption",[qref,zref],"loc_qin_eastern_depot")
    idx=json.load(open(campaign/'state/index/owner-index.json'))['owners']
    before=json.load(open(campaign/idx[qref]))
    before_arrows=int(before['logistics']['war_arrows']); before_bolts=int(before['logistics']['war_bolts'])
    result=execute_production_internal(campaign,"battle_resolve",{"attacker_formation_refs":[qref],"defender_formation_refs":[zref],"operation_ref":op,"objective":"finite bolt test"}).receipt.result
    after=json.load(open(campaign/idx[qref]))
    consumed=result['ammunition_plans'][qref]['consumed_by_resource']
    assert int(consumed.get('war_bolts',0)) > 0
    # The crossbow cohort consumes bolts. The exact named commander may also
    # consume arrows from his own saved bow loadout; both resources must debit
    # independently from the formation's finite logistics stock.
    recovered=int(result['material_losses'][qref].get('ammunition_recovered',{}).get('war_bolts',0))
    assert int(after['logistics']['war_bolts']) == before_bolts-int(consumed['war_bolts'])+recovered
    assert 0 <= recovered < int(consumed['war_bolts'])
    target_after=json.load(open(campaign/idx[zref]))
    assert any(float(v) < 100.0 for v in target_after.get('shield_condition_by_role',{}).values())
    assert any(float(v) < 100.0 for v in target_after.get('armor_condition_by_role',{}).values())
    ranged_profile=result['score_breakdown'][qref]['ranged_contact']
    assert float(ranged_profile['weighted_penetration_index']) > 0
    assert float(ranged_profile['shield_wear_pct']) > 0
    assert int(after['logistics']['war_arrows']) == before_arrows-int(consumed.get('war_arrows',0))

    phases=result['contact_phases']
    assert [row['phase'] for row in phases] == ['opening','sustained','resolution']
    q_states=[row['formation_states'][qref] for row in phases]
    assert q_states[0]['before']['ammunition']['war_bolts'] == before_bolts
    assert q_states[0]['after']['ammunition']['war_bolts'] < before_bolts
    for prior,current in zip(q_states,q_states[1:]):
        assert current['before']['ammunition'].get('war_bolts',0) == prior['after']['ammunition'].get('war_bolts',0)
    assert q_states[-1]['after']['ammunition'].get('war_bolts',0) == before_bolts-int(consumed.get('war_bolts',0))
    z_states=[row['formation_states'][zref] for row in phases]
    for prior,current in zip(z_states,z_states[1:]):
        assert current['before']['shield_units_by_role'] == prior['after']['shield_units_by_role']
        assert current['before']['armor_units_by_role'] == prior['after']['armor_units_by_role']
        assert current['before']['shield_condition_by_role'] == prior['after']['shield_condition_by_role']
        assert current['before']['armor_condition_by_role'] == prior['after']['armor_condition_by_role']
    opening_method=result['score_breakdown'][zref]['formation_method']['contact_phases'][0]
    closing_method=result['score_breakdown'][zref]['formation_method']['contact_phases'][-1]
    assert float(closing_method.get('shield_share') or 0) <= float(opening_method.get('shield_share') or 0)
    assert float(closing_method.get('shieldwall_integrity') or 0) <= float(opening_method.get('shieldwall_integrity') or 0)

    planner=RepositoryCommandPlanner(campaign)
    _,f,force=planner._combat_prepare_formation(qref)
    rows=planner._combat_cohort_snapshot(f,force)
    wrong=planner._combat_ammunition_plan(rows,{"war_arrows":999999,"war_bolts":0},3.0)
    assert wrong['consumed_by_resource']['war_bolts'] == 0
    assert planner._combat_ranged_factor(rows,wrong,[]) == 1.0


def test_person_lite_can_resolve_personal_combat_with_own_stats_and_loadout(campaign):
    from conftest import execute_internal, execute
    campaign_ref = "recruitment.test.person-lite-duel"
    execute_internal(campaign, "recruitment_campaign_start", {
        "state":"qin","campaign_ref":campaign_ref,"applicant_count":10,
        "destination_force_ref":"force_tang_wei_personal","role":"household_retainer",
        "location_ref":"loc_tang_manor_garrison_yard",
    })
    execute_internal(campaign, "recruitment_campaign_stage", {
        "campaign_ref":campaign_ref,"selection_profile":"wei_basic_eligibility","retain_count":5,
    })
    execute_internal(campaign, "recruitment_campaign_finalize", {"campaign_ref":campaign_ref})
    execute_internal(campaign, "person_materialize", {
        "state":"qin","person_ref":"char_test_person_lite_duel","name":"Retainer Sparring Partner",
        "personal_force_ref":"force_tang_wei_personal","role":"household_retainer",
        "representation":"person_lite","source_location_ref":"loc_tang_manor_garrison_yard",
    })
    idx=json.load(open(campaign/'state/index/owner-index.json'))['owners']
    person_path=idx['char_test_person_lite_duel']
    from sword_runtime.engine import RepositoryCommandPlanner
    person=RepositoryCommandPlanner(campaign).read(person_path); player=json.load(open(campaign/'state/player.json'))
    person['loc']=player['location']; person['current_location']=player['location']
    base_path, person_ref = person_path.split('#/records/', 1)
    shard_path=campaign/base_path
    shard=json.load(open(shard_path)); shard['records'][person_ref]=person
    shard_path.write_text(json.dumps(shard,indent=2)+'\n')
    import subprocess
    subprocess.run(['git','-C',str(campaign),'add',str(shard_path.relative_to(campaign))],check=True)
    subprocess.run(['git','-C',str(campaign),'commit','--quiet','-m','test: co-locate person-lite sparring partner'],check=True)
    result=execute(campaign,'personal_combat',{
        'opponent_ref':'char_test_person_lite_duel','duration_minutes':10,'objective':'controlled spar'
    })
    assert result.status=='committed'
    assert result.receipt.result['opponent_ref']=='char_test_person_lite_duel'
    assert result.receipt.result['opponent_equipment']['best_weapon']=='weapon_spear_long'
    assert result.receipt.result['opponent_score'] > 0


def test_materialized_casualty_is_inside_total_formation_losses_not_extra_body():
    from sword_runtime.cohort_personnel import trim_formation_to_personnel

    force = {
        "headcount": 20,
        "cohort_ledger": {
            "schema": "force-cohort-ledger",
            "representation": "aggregate_provenance_cohorts",
            "cohorts": {
                "cohort_test": {
                    "cohort_id": "cohort_test", "role": "household_retainer",
                    "reserve_by_location": {},
                    "allocated_by_formation": {"formation_test": 19},
                }
            },
        },
        "materialized_people": {"char_standout": 1},
        "materialized_assignments": {
            "char_standout": {"formation_ref": "formation_test", "personnel": 1}
        },
    }
    formation = {
        "formation_ref": "formation_test", "personnel": 20,
        "cohort_composition": [{"cohort_id": "cohort_test", "count": 19}],
    }

    losses = trim_formation_to_personnel(
        force, formation, old_personnel=20, new_personnel=16,
        casualty_ref="battle:test:materialized-casualty",
        materialized_casualty_refs=["char_standout"],
    )

    assert losses == {"cohort_test": 3}
    assert formation["cohort_composition"] == [{"cohort_id": "cohort_test", "count": 16}]
    assert "char_standout" not in force["materialized_people"]
    assert "char_standout" not in force["materialized_assignments"]
    assert 16 == sum(row["count"] for row in formation["cohort_composition"])


def test_bastion_aggregate_unit_command_and_embedded_echelons_are_mechanically_live(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner
    planner=RepositoryCommandPlanner(campaign)
    _, formation, force=planner._combat_prepare_formation("formation_bastion_iron_rampart_01")
    assert formation["commander_ref"] is None
    assert formation["command_structure"]["unit_command"]["external_to_fighting_establishment"] is True
    admission=planner._combat_command_admission(formation)
    assert admission["mode"] == "aggregate_unit_command"
    assert admission["commander_ref"] is None
    assert admission["higher_command"] is True
    snap=planner._formation_combat_snapshot(formation,force,terrain_kind="fortress")
    effects=snap["command_effects"]
    # The saved mixed-role 1,000/500/100 hierarchy is a mapping with a summary,
    # not the legacy list shape. Local and maneuver echelons must both contribute.
    assert effects["local"] > 1.0
    assert effects["maneuver"] > 1.0
    assert effects["unit"] > 1.0
    assert effects["higher_command_mode"] == "higher_commander"
    higher={row["person_ref"]:row for row in snap["named_participants"] if row.get("command_scope")=="higher"}
    assert "char_han_ru" in higher
    assert "equivalent_frontline_bodies" not in higher["char_han_ru"]
    assert higher["char_han_ru"]["included_in_personnel"] is False
    assert snap["cohort_personnel"] == formation["personnel"]


def test_mapping_command_hierarchy_does_not_fall_back_to_fake_generic_echelons(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner
    planner=RepositoryCommandPlanner(campaign)
    formation={
        "formation_ref":"formation_command_shape_test",
        "personnel":5000,
        "training_progress":70,
        "cohesion":80,
        "command_structure":{
            "unit_command":{"commander_post":"materialize_when_individually_relevant","external_to_fighting_establishment":True},
            "internal_hierarchy":{"summary":[{"scale":100,"count":50,"counted_inside_troop_strength":True}]},
        },
    }
    effects=planner._combat_command_effects(formation,[])
    assert effects["local"] > 1.0
    # Only a 100-man echelon was explicitly saved. If the mapping were ignored,
    # the old generic fallback would fabricate 500/1000 echelons and this would exceed 1.
    assert effects["maneuver"] == 1.0
    assert effects["unit"] > 1.0


def test_mixed_role_battle_casualties_keep_report_formation_and_force_roles_identical(campaign):
    refs=[]
    composition={'line_infantry':251,'missile_crossbow':149,'cavalry':100}
    for side in ('a','b'):
        cmd=f'char_mixed_battle_{side}_commander'; ref=f'formation_mixed_battle_{side}'; refs.append(ref)
        execute_internal(campaign,'person_materialize',{'state':'qin','person_ref':cmd,'name':f'Mixed Battle {side} Commander','birth_date':'270-BCE-01-01','role':'command_personnel','source_location_ref':'loc_qin_eastern_depot'})
        execute_internal(campaign,'formation_create',{'state':'qin','formation_ref':ref,'personnel':500,'composition':composition,'location_ref':'loc_qin_eastern_depot','commander_ref':cmd})
        execute_internal(campaign,'resupply',{'formation_ref':ref,'food_kg':500})
        execute_internal(campaign,'formation_mobilize',{'formation_ref':ref})
    op=activate_operation(campaign,'operation_mixed_battle_roles',refs,'loc_qin_eastern_depot')
    owners=json.load(open(campaign/'state/index/owner-index.json'))['owners']
    before={ref:json.load(open(campaign/owners[ref])) for ref in refs}
    result=execute_production_internal(campaign,'battle_resolve',{'attacker_formation_refs':[refs[0]],'defender_formation_refs':[refs[1]],'operation_ref':op,'objective':'mixed role casualty conservation'}).receipt.result
    force=json.load(open(campaign/'state/forces/state-qin.json'))
    trace=list(result['causal_trace'])
    kinds={row['kind'] for row in trace}
    assert {'contact_geometry','formation_contact','casualty_pressure','cohesion_response','battle_result'}.issubset(kinds)
    casualty_event=next(row for row in trace if row['kind']=='casualty_pressure')
    assert int(casualty_event['attacker_losses']) == int(result['casualties'][refs[0]])
    assert int(casualty_event['defender_losses']) == int(result['casualties'][refs[1]])
    contract=result['narration_contract']
    trace_ids={row['id'] for row in trace}
    assert set(contract['must_render']).issubset(trace_ids)
    assert any('score' in text for text in contract['do_not_reveal'])
    for ref in refs:
        after=json.load(open(campaign/owners[ref]))
        losses=result['material_losses'][ref]['composition_losses']
        exact_loss={role:int(before[ref]['composition'].get(role,0))-int(after['composition'].get(role,0)) for role in before[ref]['composition']}
        exact_loss={role:n for role,n in exact_loss.items() if n}
        assert losses == exact_loss
        assert sum(after['composition'].values()) == after['personnel']
        assert force['allocated_to_formations'][ref]['composition'] == after['composition']


def test_personal_combat_emits_player_visible_causal_trace_and_narration_contract(campaign):
    from conftest import execute, execute_internal
    opponent = 'char_test_causal_trace_opponent'
    player_location = json.load(open(campaign/'state/player.json'))['location']
    execute_internal(campaign, 'person_materialize', {
        'state':'qin', 'person_ref':opponent, 'name':'Causal Trace Opponent',
        'birth_date':'270-BCE-01-01', 'role':'command_personnel',
        'source_location_ref':player_location,
    })
    result = execute(campaign, 'personal_combat', {
        'opponent_ref':opponent, 'objective':'controlled spar', 'duration_minutes':10,
    }).receipt.result
    assert result['scale'] == 'exact_personal'
    assert result['causal_trace'] and isinstance(result['causal_trace'], (list, tuple))
    kinds = {row.get('kind') for row in result['causal_trace']}
    assert 'attack' in kinds
    assert kinds & {'movement', 'weapon_interaction', 'contact'}
    assert float(result['start_state'].get('distance_m')) > 0
    assert float(result['end_state'].get('distance_m')) > 0
    contract = result['narration_contract']
    assert contract['must_render']
    trace_ids = {row['id'] for row in result['causal_trace']}
    assert set(contract['must_render']).issubset(trace_ids)
    assert contract['do_not_reveal']
    assert 'numeric stats' in ' '.join(contract['do_not_reveal'])
    # Player-facing trace must not leak the hidden control values that drive
    # the deterministic physical resolution.
    forbidden = {'attack_control', 'defense_control', 'control_margin', 'causal_seed', 'jitter'}
    assert not any(forbidden & set(row) for row in result['causal_trace'])


def test_personal_equipment_burden_is_wearer_stat_derived_not_fixed(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner
    planner = RepositoryCommandPlanner(campaign)
    loadout = {
        'body_armor':'armor_tang', 'helmet':'helmet_tang',
        'primary_melee_weapon':'weapon_spear_long', 'shield':'shield_tang',
    }
    ordinary = planner._combat_load_burden(loadout, {
        'Strength':55, 'Endurance':55, 'Agility':55, 'Coordination':55, 'Awareness':55,
    })
    exceptional = planner._combat_load_burden(loadout, {
        'Strength':180, 'Endurance':180, 'Agility':180, 'Coordination':180, 'Awareness':180,
    })
    assert ordinary['total_load_kg'] == exceptional['total_load_kg']
    assert ordinary['movement_factor'] < exceptional['movement_factor']
    assert ordinary['fatigue_multiplier'] > exceptional['fatigue_multiplier']
    assert ordinary['recovery_factor'] < exceptional['recovery_factor']


def test_personal_combat_non_spar_stops_at_material_decision_boundary(campaign):
    from conftest import execute, execute_internal
    opponent = 'char_test_decision_boundary_opponent'
    player_location = json.load(open(campaign/'state/player.json'))['location']
    execute_internal(campaign, 'person_materialize', {
        'state':'qin', 'person_ref':opponent, 'name':'Decision Boundary Opponent',
        'birth_date':'270-BCE-01-01', 'role':'command_personnel',
        'source_location_ref':player_location,
    })
    # The command grants a large horizon, but a live duel is allowed to stop
    # at a much earlier tactical decision boundary rather than simulating the
    # entire requested horizon.
    result = execute(campaign, 'personal_combat', {
        'opponent_ref':opponent, 'objective':'duel', 'duration_minutes':60,
    }).receipt.result
    assert result['requested_duration_minutes'] == 60
    assert 0 < result['elapsed_seconds'] <= 60 * 60
    assert result['decision_boundary']['kind'] in {
        'opponent_wounded', 'player_wounded', 'opponent_disarmed', 'player_disarmed',
        'lethal_follow_through_available', 'separation_or_stalemate',
    }
    assert isinstance(result['decision_boundary']['player_decision_required'], bool)
    assert result['elapsed_seconds'] < 60 * 60


def test_personal_combat_intent_sequence_is_linked_and_dependency_safe(campaign):
    from conftest import execute, execute_internal
    opponent = 'char_test_linked_combo_opponent'
    player_location = json.load(open(campaign/'state/player.json'))['location']
    execute_internal(campaign, 'person_materialize', {
        'state':'qin', 'person_ref':opponent, 'name':'Linked Combo Opponent',
        'birth_date':'270-BCE-01-01', 'role':'command_personnel',
        'source_location_ref':player_location,
    })
    plan = ['parry the opening attack', 'step inside', 'cut the weapon arm']
    result = execute(campaign, 'personal_combat', {
        'opponent_ref':opponent, 'objective':'controlled spar', 'duration_minutes':10,
        'intent_sequence':plan, 'stop_on_decision':True,
    }).receipt.result
    links = list(result['intent_sequence'])
    assert [row['intent'] for row in links] == plan
    assert all(row['status'] in {
        'completed', 'failed', 'cancelled_dependency_failed', 'not_reached_in_slice'
    } for row in links)
    # A defensive first link is resolved as a contingent response to the
    # opponent's opening pressure. A longer weapon may physically intercept
    # that approach before an ordinary attack event is needed.
    defensive_events = [row for row in result['causal_trace'] if row.get('declared_intent') == plan[0]]
    assert defensive_events and defensive_events[0]['actor_ref'] == 'char_tang_wei'
    assert defensive_events[0]['kind'] in {'weapon_interaction', 'attack'}
    failed = next((i for i,row in enumerate(links) if row['status']=='failed'), None)
    if failed is not None:
        assert all(row['status']=='cancelled_dependency_failed' for row in links[failed+1:])
    # If the weapon-arm cut is actually reached, its physical contact must use
    # the requested body zone rather than a generic random wound label.
    weapon_arm = [row for row in result['causal_trace'] if row.get('declared_intent') == 'cut the weapon arm' and row.get('kind') == 'contact']
    if weapon_arm:
        assert weapon_arm[-1]['body_zone'] == 'forearms_hands'
