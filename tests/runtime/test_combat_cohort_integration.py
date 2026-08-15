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
    _, formation, force=planner._combat_prepare_formation("formation_house_ouki_household_guard")
    snap=planner._formation_combat_snapshot(formation,force,terrain_kind="open")
    ouki=next(x for x in snap["named_participants"] if x["person_ref"]=="char_ouki")
    assert ouki["representation"] == "sab_character"
    assert ouki["role"] == "commander"
    assert ouki["command_score"] > 150
    assert ouki["direct_combat_score"] > 150
    assert ouki["equivalent_frontline_bodies"] > 1
    assert ouki["loadout_id"] == "loadout_named_glaive"
    assert ouki["melee_skill"] == "Glaive"
    assert ouki["melee_weapon_id"] == "weapon_glaive_heavy"
    assert ouki["melee_reach_m"] == 2.0
    assert ouki["ammunition_resource"] == "war_arrows"
    assert snap["cohort_personnel"] == formation["personnel"]  # Ouki is not averaged into the 520 retainers.


def test_battle_trims_cohorts_and_awards_survivor_experience_through_production_planner(campaign):
    # Keep the battle local: no strategic movement is needed to verify cohort settlement.
    for side in ("a","b"):
        execute_internal(campaign,"person_materialize",{"state":"qin","person_ref":f"char_combat_cohort_{side}","name":f"Cohort {side} Commander","birth_date":"270-BCE-01-01","role":"command_personnel"})
        execute_internal(campaign,"formation_create",{"state":"qin","formation_ref":f"formation_combat_cohort_{side}","role":"line_infantry","personnel":500,"commander_ref":f"char_combat_cohort_{side}"})
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
    person = json.load(open(campaign/person_path))
    assert person['equipment_custody']['mode'] == 'formation_issue_slot'
    assert person['equipment_custody']['formation_ref'] == 'formation_test_person_lite_retinue'


def test_field_battle_consumes_finite_crossbow_bolts_with_named_commander_ammo_separate(campaign):
    from conftest import execute_internal, activate_operation
    from sword_runtime.engine import RepositoryCommandPlanner

    qref="formation_test_bolt_crossbow"; zref="formation_test_bolt_target"
    execute_internal(campaign,"formation_create",{"state":"qin","formation_ref":qref,"role":"missile_crossbow","personnel":200,"commander_ref":"char_heki"})
    execute_internal(campaign,"formation_create",{"state":"zhao","formation_ref":zref,"role":"line_infantry","personnel":200,"commander_ref":"char_bananji"})
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
    assert int(after['logistics']['war_bolts']) == before_bolts-int(consumed['war_bolts'])
    assert int(after['logistics']['war_arrows']) == before_arrows-int(consumed.get('war_arrows',0))

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
    person_path=campaign/idx['char_test_person_lite_duel']
    person=json.load(open(person_path)); player=json.load(open(campaign/'state/player.json'))
    person['loc']=player['location']; person['current_location']=player['location']
    person_path.write_text(json.dumps(person,indent=2)+'\n')
    import subprocess
    subprocess.run(['git','-C',str(campaign),'add',str(person_path.relative_to(campaign))],check=True)
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
            "schema": "force-cohort-ledger.v1",
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
