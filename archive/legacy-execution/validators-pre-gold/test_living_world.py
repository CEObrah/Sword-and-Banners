#!/usr/bin/env python3
import json,pathlib,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
def load(rel):return json.loads((ROOT/rel).read_text(encoding='utf-8'))
def fail(x):print('LIVING WORLD TEST FAILED');print('-',x);sys.exit(1)
# Command personnel are people, never one-person units.
idx=load('state/cmd/command-personnel.json')
if idx.get('schema')!='command-personnel-index.v2':fail('command_personnel_index_schema')
records=idx.get('record_index',{})
if not records or idx.get('count')!=len(records):fail('command_personnel_count')
seen=set()
for pid,rel in records.items():
    if pid in seen:fail('duplicate_command_person:'+pid)
    seen.add(pid)
    rp=ROOT/rel
    if not rp.exists():fail('command_person_record_missing:'+pid)
    d=json.loads(rp.read_text(encoding='utf-8'))
    if d.get('schema')!='command-person.v1' or d.get('person_id')!=pid:fail('command_person_record:'+pid)
    c=d.get('command',{})
    if not isinstance(c,dict) or c.get('command_scope')!='army_or_unit_command_personnel':fail('command_person_scope:'+pid)
    if any(k in d for k in ('personnel_count','unit_personnel_delta','embedded_in_unit')):fail('command_person_as_unit:'+pid)

# Cold archetypes only.
ma=load('game/data/content/mission-archetypes.json').get('archetypes',[]); wa=load('game/data/content/world-event-archetypes.json').get('archetypes',[])
if len(ma)<20:fail('mission_archetype_count')
if len(wa)<15:fail('event_archetype_count')
if 'mission_templates' in load('state/contract/contracts-companions-projects.json'):fail('mission_templates_in_state')
if load('state/event/living-world-events.json').get('events'):fail('event_templates_in_state')
# Factions/staff are distinct enough to play.
fidx=load('state/reg/living-factions.json')
factions=[]
for rel in fidx.get('record_index',{}).values():
    factions.append(load(rel).get('faction',{}))
if len(factions)<12:fail('living_faction_count')
for f in factions:
    if not f.get('goals') or not f.get('resources') or not f.get('constraints') or not f.get('current_plan'):fail('thin_faction:'+f.get('id',''))
for p in (ROOT/'state/person/staff').glob('*.json'):
    d=json.loads(p.read_text(encoding='utf-8'))
    if not d.get('history',{}).get('service') or len(d.get('relationships',[]))<2:fail('thin_staff:'+p.name)

# Narration and choice interface contract.
if 'action_packages' in load('state/scene.json'):fail('cached_choices')
choice=load('game/data/runtime/choice-presentation.json')
if not choice.get('completion_rule'):fail('choice_completion_rule_missing')
if choice.get('suggested_choice_count',{}).get('minimum')!=3:fail('choice_minimum')
if choice.get('suggested_choice_count',{}).get('maximum')!=5:fail('choice_maximum')
if choice.get('numbering_required') is not True:fail('choice_numbering_required')
if choice.get('free_form_option_required') is not True:fail('choice_free_form_required')
if choice.get('duration_required_for_every_suggested_choice') is not True:fail('choice_duration_required')

# Tang Wei has two peer 50-person Tang Champion companies. Duan commands First; Shen commands Second.
first=load('state/unit/tang-champions-first.json'); second=load('state/unit/tang-champions-second.json')
for label,unit,uid,cmd in (
    ('first',first,'unit_tang_wei_tang_champions_first','char_duan_jin'),
    ('second',second,'unit_tang_wei_tang_champions_second','char_shen_rui'),
):
    if unit.get('id')!=uid:fail('champion_unit_id:'+label)
    pers=unit.get('personnel',{})
    if pers.get('representation')!='aggregate' or pers.get('count')!=50 or pers.get('member_ids'):fail('champion_unit_members:'+label)
    if unit.get('commander_id')!=cmd:fail('champion_unit_commander:'+label)
    if unit.get('loadout_standard')!='loadout_house_guardian_cavalry':fail('champion_unit_loadout:'+label)
    if unit.get('doctrine')!='doc.tang_wei.household_champions' or unit.get('training')!='train.tang_wei.household_champions':fail('champion_unit_program:'+label)
pf=load('state/pforce/wei.json')
if pf.get('permanent_units')!=['unit_tang_wei_tang_champions_first','unit_tang_wei_tang_champions_second'] or pf.get('unassigned_members'):fail('champion_personal_force_assignment')
duan=load('state/cmd/command-groups/cmdgrp.duan_jin.tang_champions_first.json')
shen=load('state/cmd/command-groups/cmdgrp.shen_rui.tang_champions_second.json')
if duan.get('direct_unit_refs')!=['unit_tang_wei_tang_champions_first'] or duan.get('deputy_ref') is not None:fail('champion_duan_command_group')
if shen.get('direct_unit_refs')!=['unit_tang_wei_tang_champions_second'] or shen.get('deputy_ref') is not None:fail('champion_shen_command_group')

# Current House Tang and Sword Manor training plans use the sustainable deliberate-training ceiling.
contracts=load('state/train/training-contracts.json')
targets={'force_house_guardian_cavalry','force_house_guards','unit_tang_wei_tang_champions_first','unit_tang_wei_tang_champions_second','SM-O-01','SM-S','SM-G','SM-J','SM-C-01','support_sword_manor_medical_camp','SM-T'}
seen_targets=set()
for rec in contracts.get('records',[]):
    facts=rec.get('facts',{})
    owner=facts.get('owner')
    if owner in targets:
        seen_targets.add(owner)
        if facts.get('planned_training_hours_per_person_per_month')!=240:fail('training_ceiling:'+owner)
if seen_targets!=targets:fail('training_target_coverage')

print('LIVING WORLD TESTS OK')
