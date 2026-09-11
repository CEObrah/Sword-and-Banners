#!/usr/bin/env python3
from __future__ import annotations
import json, os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def load(rel): return json.loads((ROOT/rel).read_text(encoding='utf-8'))
def save(rel,d):
 p=ROOT/rel; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(d,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
def route_exists(route:str)->bool:
 if not route:
  return False
 base, sep, frag = route.partition('#')
 path = ROOT / base
 if not path.is_file():
  return False
 if not sep:
  return True
 try:
  doc = json.loads(path.read_text(encoding='utf-8'))
 except Exception:
  return False
 cur = doc
 for raw in frag.lstrip('/').split('/'):
  if raw == '':
   continue
  key = raw.replace('~1','/').replace('~0','~')
  if isinstance(cur, dict) and key in cur:
   cur = cur[key]
  elif isinstance(cur, list) and key.isdigit() and int(key) < len(cur):
   cur = cur[int(key)]
  else:
   return False
 return True

def char_path_for(ref:str):
 if ref=='char_tang_wei': return 'state/player.json'
 for p in (ROOT/'state/char').glob('*.json'):
  try:d=json.loads(p.read_text())
  except Exception:continue
  if d.get('owner_id')==ref or d.get('id')==ref:
   return p.relative_to(ROOT).as_posix()
 return None

def main():
 # Correct the two known staff-role migration residues.
 for rel,person in [
  ('state/cmd/command-groups/cmdgrp.tang_wei.field_army.json','char_lin_zhen'),
  ('state/cmd/command-groups/cmdgrp.shin.hi_shin.json','char_karyoten'),
 ]:
  d=load(rel); d.setdefault('role_assignments',{})[person]='strategist'; save(rel,d)
 # Preserve explicit Tang Wei succession continuity.
 rel='state/cmd/command-groups/cmdgrp.tang_wei.field_army.json'; d=load(rel); d['successor_refs']=['char_lin_zhen']; save(rel,d)
 # Retired duplicate Bastion command layer. The real outer-wall branch remains.
 obsolete=ROOT/'state/cmd/command-groups/cmdgrp.house_tang.bastions.json'
 if obsolete.exists(): obsolete.unlink()

 # Load exact command groups and formations.
 groups={}
 for p in sorted((ROOT/'state/cmd/command-groups').glob('cmdgrp*.json')):
  d=json.loads(p.read_text()); ref=d.get('id')
  if isinstance(ref,str) and ref.startswith('cmdgrp.'):
   groups[ref]=(p.relative_to(ROOT).as_posix(),d)
 formations={}
 for p in sorted((ROOT/'state/formations').glob('*.json')):
  d=json.loads(p.read_text()); ref=d.get('formation_ref')
  if isinstance(ref,str): formations[ref]=(p.relative_to(ROOT).as_posix(),d)

 # Derive direct formation parents and command/staff/member routing from exact groups.
 primary_form={}; command_routes={}; staff_routes={}; member_routes={}
 for ref,(_p,g) in sorted(groups.items()):
  cmd=g.get('commander_ref')
  if isinstance(cmd,str) and cmd: command_routes.setdefault(cmd,[]).append(ref)
  for person in g.get('direct_person_refs',[]) if isinstance(g.get('direct_person_refs'),list) else []:
   if isinstance(person,str) and person: member_routes.setdefault(person,[]).append(ref)
  for person,role in (g.get('role_assignments') or {}).items() if isinstance(g.get('role_assignments'),dict) else []:
   if isinstance(person,str) and person and isinstance(role,str) and role: staff_routes.setdefault(person,[]).append(ref)
  for u in g.get('units',[]) if isinstance(g.get('units'),list) else []:
   if not isinstance(u,dict) or u.get('kind')!='formation' or not isinstance(u.get('ref'),str): continue
   fr=u['ref']; prior=primary_form.get(fr)
   if prior not in (None,ref): raise RuntimeError(f'duplicate direct formation parent {fr}: {prior} / {ref}')
   primary_form[fr]=ref
 for m in (command_routes,staff_routes,member_routes):
  for k in list(m): m[k]=sorted(set(m[k]))

 def choose(refs):
  rows=[]
  for ref in sorted(set(refs)):
   g=groups[ref][1]; org=g.get('organizational_state') if isinstance(g.get('organizational_state'),dict) else {}
   strength=int(org.get('current_recursive_strength',org.get('authorized_strength',0)) or 0)
   child=1 if isinstance(g.get('parent_command_group_ref'),str) and g.get('parent_command_group_ref') else 0
   rows.append((-strength,child,ref))
  return sorted(rows)[0][2]
 primary_person={}
 for person in sorted(set(command_routes)|set(member_routes)):
  refs=command_routes.get(person) or member_routes.get(person) or []
  if refs: primary_person[person]=choose(refs)

 cgi=load('state/cmd/command-groups/index.json')
 cgi.update({'schema':'command-group-index','authority':False,'count':len(groups),'refs':sorted(groups),
             'primary_person_group':primary_person,'primary_formation_group':dict(sorted(primary_form.items())),
             'staff_person_groups':dict(sorted(staff_routes.items())),'command_person_groups':dict(sorted(command_routes.items()))})
 save('state/cmd/command-groups/index.json',cgi)

 # Synchronize each formation's direct higher-command pointer to the exact group index.
 for fr,(rel,f) in formations.items():
  if fr in primary_form: f['higher_command_ref']=primary_form[fr]
  elif isinstance(f.get('higher_command_ref'),str) and f['higher_command_ref'].startswith('cmdgrp.') and f['higher_command_ref'] not in groups:
   f.pop('higher_command_ref',None)
  save(rel,f)

 # Rebuild owner routing conservatively: retain every still-real old route, then
 # overwrite authoritative exact character/formation/force/group/person-lite routes.
 old=load('state/index/owner-index.json'); owners={k:v for k,v in (old.get('owners') or {}).items() if isinstance(v,str) and route_exists(v)}
 # Add every unique top-level exact owner_id in state. This catches exact
 # subsystem owners such as fortress artillery without inventing nested owners.
 top_level={}
 for p in sorted((ROOT/'state').rglob('*.json')):
  try: d=json.loads(p.read_text(encoding='utf-8'))
  except Exception: continue
  if not isinstance(d,dict): continue
  ref=d.get('owner_id')
  if not isinstance(ref,str) or not ref: continue
  rel=p.relative_to(ROOT).as_posix()
  prior=top_level.get(ref)
  if prior and prior!=rel: raise RuntimeError(f'duplicate top-level owner_id {ref}: {prior} / {rel}')
  top_level[ref]=rel
 owners.update(top_level)
 # Exact characters and player.
 player=load('state/player.json'); owners[player.get('owner_id','char_tang_wei')]='state/player.json'
 for p in sorted((ROOT/'state/char').glob('*.json')):
  d=json.loads(p.read_text()); ref=d.get('owner_id') or d.get('id')
  if isinstance(ref,str) and ref: owners[ref]=p.relative_to(ROOT).as_posix()
 # Exact formations/forces/groups.
 for fr,(rel,_d) in formations.items(): owners[fr]=rel
 for p in sorted((ROOT/'state/forces').glob('*.json')):
  d=json.loads(p.read_text()); ref=d.get('owner_id') or d.get('id')
  if isinstance(ref,str) and ref: owners[ref]=p.relative_to(ROOT).as_posix()
 for ref,(rel,_d) in groups.items(): owners[ref]=rel
 # Person-lite shards are exact routed records without individual files.
 for p in sorted((ROOT/'state/person/person-lite').glob('*.json')):
  d=json.loads(p.read_text()); recs=d.get('records')
  if isinstance(recs,dict):
   rel=p.relative_to(ROOT).as_posix()
   for ref in recs:
    owners[ref]=f'{rel}#/records/{ref}'
 old['owners']=dict(sorted(owners.items())); old['owner_id']='owner_index'; save('state/index/owner-index.json',old)

 # House formation active fields: two troop species only. Historical cohort ids/evidence remain untouched.
 removed_embedded=removed_cadre=cleaned_house=0
 owners=old['owners']
 for fr,(rel,f) in formations.items():
  changed=False
  emb=f.get('embedded_person_refs')
  if isinstance(emb,list):
   kept=[r for r in emb if isinstance(r,str) and r in owners and route_exists(owners[r])]
   removed_embedded += len(emb)-len(kept)
   if kept!=emb: f['embedded_person_refs']=kept; changed=True
  cadre=f.get('officer_cadre')
  if isinstance(cadre,dict) and isinstance(cadre.get('materialized_refs_by_rank'),dict):
   for rank,refs in list(cadre['materialized_refs_by_rank'].items()):
    if not isinstance(refs,list): continue
    kept=[r for r in refs if isinstance(r,str) and r in owners and route_exists(owners[r])]
    removed_cadre += len(refs)-len(kept)
    if kept!=refs: cadre['materialized_refs_by_rank'][rank]=kept; changed=True
  if f.get('owner_force_ref')=='force_house_tang':
   comp=f.get('composition') if isinstance(f.get('composition'),dict) else {}
   roles={str(k) for k,v in comp.items() if int(v)>0}
   if not roles <= {'house_infantry','house_cavalry'}: raise RuntimeError((fr,'illegal live House roles',roles))
   if roles=={'house_cavalry'}:
    loadouts={'house_cavalry':'loadout_tang_mounted'}; primary='loadout_tang_mounted'; training='train.house_tang.house_cavalry'
   elif roles=={'house_infantry'}:
    loadouts={'house_infantry':'loadout_tang_foot'}; primary='loadout_tang_foot'; training='train.house_tang.house_infantry_outer_wall' if 'outer_wall' in fr else 'train.house_tang.house_infantry'
   else:
    loadouts={}
    if 'house_infantry' in roles: loadouts['house_infantry']='loadout_tang_foot'
    if 'house_cavalry' in roles: loadouts['house_cavalry']='loadout_tang_mounted'
    primary=None; training='train.house_tang.house_infantry'
   f['registered_loadouts_by_role']=loadouts
   if primary: f['registered_loadout_ref']=primary
   else: f.pop('registered_loadout_ref',None)
   f['training_ref']=training
   f['attached_unit_command_by_role']={}
   f['command_attachment_source_force_ref']='force_house_tang'
   cleaned_house+=1; changed=True
  if changed: save(rel,f)

 # Refresh exact commander sheets from the exact billet they currently hold.
 form_cmd={}
 for fr,(rel,f) in formations.items():
  c=f.get('commander_ref')
  if isinstance(c,str) and c: form_cmd[c]=(fr,f)
 group_cmd={c:refs for c,refs in command_routes.items()}
 synced_form=synced_group=0
 for person,(fr,f) in form_cmd.items():
  rel=owners.get(person)
  if not rel or '#/' in rel or not rel.startswith(('state/char/','state/player.json')): continue
  p=load(rel); span=int(f.get('personnel',0) or 0); parent=primary_form.get(fr)
  p['current_formation_id']=fr
  if f.get('location_ref'): p['current_location']=f['location_ref']
  ca=p.setdefault('command_assignment',{}); ca.update({'billet':'formation_commander','formation_ref':fr,'current_command_span':span,'external_to_fighting_establishment':True})
  if parent: ca['command_group_ref']=parent
  mc=p.setdefault('military_command',{}); mc['formation_scope']=fr; mc['external_to_fighting_strength']=True
  if span>=500: mc['level']=f'{span}_commander'
  if parent and parent in groups:
   higher=groups[parent][1].get('commander_ref')
   if isinstance(higher,str) and higher and higher!=person: mc['higher_commander_ref']=higher
  cs=p.setdefault('career_state',{}); cs['current_command_span']=span; cs['current_billet']='formation_commander'
  if any(x in str(p.get('role','')).lower() for x in ('sword manor','bastion','trainee commander','disciple commander')):
   p['role']=f'{span}-man Commander, {f.get("name",fr)}'
   cs['office_or_command']=p['role']
  save(rel,p); synced_form+=1
 for person,refs in group_cmd.items():
  if person in form_cmd: continue
  rel=owners.get(person)
  if not rel or '#/' in rel or not rel.startswith(('state/char/','state/player.json')): continue
  primary=primary_person.get(person) or choose(refs); g=groups[primary][1]
  p=load(rel); span=int((g.get('organizational_state') or {}).get('current_recursive_strength',(g.get('organizational_state') or {}).get('authorized_strength',0)) or 0)
  p.pop('current_formation_id',None)
  if g.get('location'): p['current_location']=g['location']
  ca=p.setdefault('command_assignment',{}); ca.update({'billet':'command_group_commander','formation_ref':primary,'command_group_ref':primary,'current_command_span':span,'external_to_fighting_establishment':True})
  mc=p.setdefault('military_command',{}); mc.update({'formation_scope':primary,'external_to_fighting_strength':True})
  if span>=500: mc['level']=f'{span}_commander'
  parent=g.get('parent_command_group_ref')
  if isinstance(parent,str) and parent in groups:
   higher=groups[parent][1].get('commander_ref')
   if isinstance(higher,str) and higher and higher!=person: mc['higher_commander_ref']=higher
  cs=p.setdefault('career_state',{}); cs['current_command_span']=span; cs['current_billet']='command_group_commander'
  save(rel,p); synced_group+=1

 # Command-personnel is a projection of currently relevant individually represented
 # military people. Current formation/group commanders and group staff are derived
 # from exact command owners. In addition, preserve routed person-lite staff and
 # exact staff carrying a live command_assignment even when they are not a fighting
 # commander. This keeps named operations/logistics staff addressable without
 # resurrecting dead or missing roster shards.
 current_people=set(form_cmd)|set(command_routes)|set(staff_routes)
 cp=load('state/cmd/command-personnel.json'); prior_routes=cp.get('record_index',{}) if isinstance(cp.get('record_index'),dict) else {}
 for person,rel in sorted(prior_routes.items()):
  if not isinstance(rel,str) or not route_exists(rel):
   continue
  try:
   base,sep,frag=rel.partition('#'); doc=json.loads((ROOT/base).read_text(encoding='utf-8')); rec0=doc
   if sep and frag:
    for raw in frag.lstrip('/').split('/'):
     if raw:
      key=raw.replace('~1','/').replace('~0','~'); rec0=rec0[key] if isinstance(rec0,dict) else rec0[int(key)]
  except Exception:
   continue
  if not isinstance(rec0,dict):
   continue
  life=str(rec0.get('life_status',rec0.get('status','active'))).lower()
  if life in {'dead','deceased','destroyed'}:
   continue
  if rec0.get('schema')=='person-lite':
   current_people.add(person)
   continue
  assignment=rec0.get('command_assignment') if isinstance(rec0.get('command_assignment'),dict) else {}
  group_ref=assignment.get('command_group_ref'); formation_ref=assignment.get('formation_ref')
  if (isinstance(group_ref,str) and group_ref in groups) or (isinstance(formation_ref,str) and formation_ref in formations):
   current_people.add(person)
 rec={}
 for person in sorted(current_people):
  rel=owners.get(person)
  if rel and route_exists(rel): rec[person]=rel
 cp['schema']='command-personnel-index'; cp['id']='command_personnel'; cp['record_index']=rec; cp['count']=len(rec)
 # Scope shards are still useful only when their shard physically exists.
 if isinstance(cp.get('scope_shards'),dict):
  cp['scope_shards']={k:v for k,v in cp['scope_shards'].items() if isinstance(v,list) and all(isinstance(r,dict) and route_exists(str(r.get('path',''))) for r in v)}
 save('state/cmd/command-personnel.json',cp)
 print(json.dumps({'groups':len(groups),'formations':len(formations),'owner_routes':len(owners),'command_personnel':len(rec),'house_formations_cleaned':cleaned_house,'stale_embedded_removed':removed_embedded,'stale_cadre_refs_removed':removed_cadre,'formation_commander_sheets_synced':synced_form,'group_commander_sheets_synced':synced_group},indent=2))

if __name__=='__main__': main()
