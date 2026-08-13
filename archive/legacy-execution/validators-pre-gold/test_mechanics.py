#!/usr/bin/env python3
import json,math
from decimal import Decimal,ROUND_HALF_UP
from pathlib import Path
R=Path(__file__).resolve().parents[1];t=json.loads((R/'tests/mechanics-v38.json').read_text())['tests'];by={x['id']:x for x in t}
def r3(x):return float(Decimal(str(x)).quantize(Decimal('0.001'),rounding=ROUND_HALF_UP))
def chk(i,v):
 e=by[i]['expected']; assert (abs(float(v)-float(e))<.0011) if isinstance(e,(int,float)) else v==e,(i,v,e)
x=by['reach_170cm']['inputs'];chk('reach_170cm',r3(.45*x['height_m']))
x=by['weapon_adjustment_190cm']['inputs'];chk('weapon_adjustment_190cm',r3(x['item_reach']+.22*(x['height_m']-1.70)))
x=by['fall_energy_80kg_2m']['inputs'];chk('fall_energy_80kg_2m',r3(x['mass']*9.80665*x['height']))
attack=.45*120+.20*100+.15*90+.10*80+.10*80+4+8-5;chk('attack_control_example',r3(attack))
dodge=.35*100+.25*90+.15*80+.10*100+.10*95+.05*80+5-0-5;chk('dodge_control_example',r3(dodge))
m=by['contact_grade_17_5']['inputs']['margin']; grade={'grade':'denied','multiplier':0.0} if m<=-25 else {'grade':'glancing','multiplier':.45} if m<=0 else {'grade':'solid','multiplier':.8} if m<=15 else {'grade':'clean','multiplier':1.0} if m<=40 else {'grade':'exceptional','multiplier':1.15};chk('contact_grade_17_5',grade)
x=by['armor_penetration_ratio']['inputs'];chk('armor_penetration_ratio',r3(x['penetration']/(x['resistance']*x['condition']*x['fit']*x['angle'])))
x=by['armor_impact_ratio']['inputs'];chk('armor_impact_ratio',r3(x['impact']*x['transfer']/(x['blunt']*x['condition']*x['fit']*x['angle'])))
x=by['siege_crew_factor']['inputs'];chk('siege_crew_factor',r3(max(.5,min(1,x['fit']/x['optimal']))))
control=.24*80+.22*70+.14*75+.14*75+.10*70+.10*80+.06*70;chk('siege_control_factor',r3(max(.6,min(1.25,.70+control/400))))
# Morale closure: every component is computed from registered saved inputs.
x=by['morale_detailed_example']['inputs']
cas=max(0,min(60,120*x['recent_casualty_fraction']+40*x['cumulative_casualty_fraction']))
cmd=18*x['commander_lost']+8*x['deputy_lost']
pos={'none':0,'flanked':10,'rear_compromised':20,'encircled':35}[x['positional']]
iso={'connected':0,'separated':8,'cut_off':18}[x['isolation']]
sup={'secure':0,'strained':8,'critical':18,'exhausted':30}[x['supply']]
fear=max(0,min(40,x['fear_pressure']))
coh=max(-15,min(25,(x['cohesion']-70)*.25))
rally=x['command_action_used']*max(0,min(35,((.40*x['Leadership']+.30*x['Presence']+.30*x['Formation_Command'])-60)*.35))*x['commander_familiarity_factor']
pressure=cas+cmd+pos+iso+sup+fear-rally-coh
effective=max(0,min(200,x['base']-pressure))
state='rout_or_surrender' if effective<25 else 'breaking' if effective<50 else 'shaken' if effective<80 else 'steady' if effective<120 else 'confident' if effective<160 else 'unyielding'
chk('morale_detailed_example',{'pressure':r3(pressure),'effective':r3(effective),'state':state})

tr=json.loads((R/'game/data/mechanics/training.json').read_text());chk('representation_efficiency',tr['representation_efficiency'])
x=by['training_capacity_example']['inputs']; vals=[]
for a,r in ((x['instructor_hours'],x['required_instructor_hours']),(x['facility_slots'],x['required_slots']),(x['equipment_sets'],x['required_sets'])):
 vals.append(1 if r==0 else a/r)
chk('training_capacity_example',r3(max(0,min(1,*vals))))
x=by['skill_cost_100']['inputs'];chk('skill_cost_100',r3(18*(1+x['current_score']/50)**1.75))
x=by['diminishing_at_ceiling']['inputs'];score=x['score'];ceiling=x['ceiling']
if score<=ceiling-20: d=1.0
elif score<=ceiling: d=1.0-(score-(ceiling-20))*(.55/20)
elif score<=ceiling+20: d=.45-(score-ceiling)*(.35/20)
else: d=.05
chk('diminishing_at_ceiling',r3(d))
x=by['rust_450d']['inputs'];rust=0 if x['unused_days']<=180 else min(.08,.01*math.floor((x['unused_days']-180)/90));chk('rust_450d',r3(rust))
x=by['raw_edu_example']['inputs'];raw=x['verified_hours']*x['competency_share']*x['intensity']*x['practice_mode']*x['instruction']*x['instructor_capacity']*x['facility']*x['equipment']*x['health']*x['recovery']*x['feedback']*x['age']*x['aptitude']*x['potential']*x['relevance']*x['interruption']*x['representation'];chk('raw_edu_example',r3(raw))
# Politics closure.
x=by['scheme_progress_example']['inputs'];chk('scheme_progress_example',x['access']+x['agent']+x['resources']+x['vulnerability']+x['preparation']-x['difficulty']-x['opposition'])
x=by['evidence_weight_example']['inputs'];chk('evidence_weight_example',r3(x['quality']*x['reliability']*x['custody']*x['corroboration']-x['contradiction']))
x=by['war_capacity_example']['inputs'];chk('war_capacity_example',min(x.values()))
x=by['coalition_support_example']['inputs'];chk('coalition_support_example',sum(x['support'])-sum(x['oppose']))
print('MECHANICS TESTS OK')
