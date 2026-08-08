#!/usr/bin/env python3
import json,pathlib,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
def load(rel):return json.loads((ROOT/rel).read_text(encoding='utf-8'))
def fail(x):print('LIVING WORLD TEST FAILED');print('-',x);sys.exit(1)
# Command personnel are people, never one-person units.
idx=load('state/cmd/command-personnel.json')
if idx.get('schema')!='command-personnel-index.v2':fail('command_personnel_index_schema')
records=idx.get('record_index',{})
if len(records)<40 or idx.get('count')!=len(records):fail('command_personnel_count')
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
ma=load('data/content/mission-archetypes.json').get('archetypes',[]); wa=load('data/content/world-event-archetypes.json').get('archetypes',[])
if len(ma)<20:fail('mission_archetype_count')
if len(wa)<15:fail('event_archetype_count')
if 'mission_templates' in load('state/contract/contracts-companions-projects.json'):fail('mission_templates_in_state')
if load('state/event/living-world-events.json').get('events'):fail('event_templates_in_state')
# Factions/staff are distinct enough to play.
for f in load('state/reg/living-factions.json').get('factions',[]):
    if not f.get('goals') or not f.get('resources') or not f.get('constraints'):fail('thin_faction:'+f.get('id',''))
for p in (ROOT/'state/person/staff').glob('*.json'):
    d=json.loads(p.read_text(encoding='utf-8'))
    if not d.get('history',{}).get('service') or len(d.get('relationships',[]))<2:fail('thin_staff:'+p.name)

# Narration and choice interface contract.
if 'action_packages' in load('state/scene.json'):fail('cached_choices')
voice=(ROOT/'VOICE.md').read_text(encoding='utf-8')
for phrase in ('Repository memory is not player memory','second-person present tense','Speaker anchoring must stay clear','Choice completion is mandatory','estimated in-world','medium','long'):
    if phrase not in voice:fail('voice:'+phrase)
household=(ROOT/'data/runtime/narration/household-family.md').read_text(encoding='utf-8')
if 'keep short dialogue exchanges unmistakably attributed' not in household:fail('household_speaker_attribution')
choice=load('data/runtime/choice-presentation.json')
if not choice.get('completion_rule'):fail('choice_completion_rule_missing')
if choice.get('suggested_choice_count',{}).get('minimum')!=3:fail('choice_minimum')
if choice.get('suggested_choice_count',{}).get('maximum')!=5:fail('choice_maximum')
if choice.get('numbering_required') is not True:fail('choice_numbering_required')
if choice.get('free_form_option_required') is not True:fail('choice_free_form_required')
if choice.get('duration_required_for_every_suggested_choice') is not True:fail('choice_duration_required')

# Dormant event archetypes are causal wakeups.
print('LIVING WORLD TESTS OK')
