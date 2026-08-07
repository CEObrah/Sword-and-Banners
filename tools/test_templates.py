#!/usr/bin/env python3
import json,os,glob,sys

def jtype(v):
    if v is None:return 'null'
    if isinstance(v,bool):return 'boolean'
    if isinstance(v,int) and not isinstance(v,bool):return 'integer'
    if isinstance(v,float):return 'number'
    if isinstance(v,str):return 'string'
    if isinstance(v,list):return 'array'
    if isinstance(v,dict):return 'object'
    return type(v).__name__
def allowed_type(actual,allowed):
    if not allowed:return True
    return actual in allowed or (actual=='integer' and 'number' in allowed)
def load_schema_templates(repo):
    idx=json.load(open(os.path.join(repo,'data/runtime/template-index.json'))); out={}
    for rel in idx['shards'].values(): out.update(json.load(open(os.path.join(repo,rel)))['templates'])
    return out
def validate_doc(label,d,c,errors):
    for k in c.get('required_top_level_keys',[]):
        if k not in d: errors.append(f'{label}: missing required top-level key {k!r}')
    oc=c.get('object_contracts',{});tc=c.get('type_contracts',{});ac=c.get('array_contracts',{})
    def walk(v,p):
        at=jtype(v); al=tc.get(p,[])
        if not allowed_type(at,al): errors.append(f'{label}{p or "/"}: type {at} not in {al}')
        if isinstance(v,dict):
            con=oc.get(p)
            if con is None:
                errors.append(f'{label}{p or "/"}: object path has no template contract'); return
            if con.get('mode')=='closed':
                extra=set(v)-set(con.get('allowed_keys',[]))
                if extra: errors.append(f'{label}{p or "/"}: unregistered keys {sorted(extra)}')
                for k,x in v.items(): walk(x,(p+'/'+k) if p else '/'+k)
            elif con.get('mode')=='open_map':
                for x in v.values(): walk(x,(p+'/*') if p else '/*')
            else: errors.append(f'{label}{p or "/"}: invalid template mode')
        elif isinstance(v,list):
            spec=ac.get(p)
            if spec is None:
                if v: errors.append(f'{label}{p}: nonempty array has no item template contract')
                return
            ait=spec.get('item_types',[])
            for i,x in enumerate(v):
                if not allowed_type(jtype(x),ait): errors.append(f'{label}{p}/{i}: item type {jtype(x)} not in {ait}')
                walk(x,(p+'/*') if p else '/*')
    walk(d,'')
def schema_object_contracts(schema,path='',out=None):
    """Return schema-declared object properties by JSON-pointer-like template path.

    This is intentionally structural rather than a full JSON-Schema evaluator. It
    follows object properties, array items, map value schemas and branch overlays
    (allOf/anyOf/oneOf). The ordinary schema/audit validators still own semantic
    validation; this check prevents the cold write template from silently dropping
    a field that the formal schema already permits.
    """
    if out is None: out={}
    if not isinstance(schema,dict): return out
    props={}
    if isinstance(schema.get('properties'),dict): props.update(schema['properties'])
    for key in ('allOf','anyOf','oneOf'):
        for branch in schema.get(key,[]) or []:
            if not isinstance(branch,dict): continue
            if isinstance(branch.get('properties'),dict): props.update(branch['properties'])
            schema_object_contracts(branch,path,out)
    if props or schema.get('type')=='object':
        out.setdefault(path,set()).update(props)
        for key,sub in props.items():
            if isinstance(sub,dict):
                child=(path+'/'+key) if path else '/'+key
                schema_object_contracts(sub,child,out)
    if schema.get('type')=='array' or 'items' in schema:
        item=schema.get('items')
        if isinstance(item,dict):
            schema_object_contracts(item,(path+'/*') if path else '/*',out)
    ap=schema.get('additionalProperties')
    if isinstance(ap,dict):
        schema_object_contracts(ap,(path+'/*') if path else '/*',out)
    return out

def validate_template_schema_coverage(repo,sid,ent,contract,errors):
    sp=contract.get('source_schema') or ent.get('source_schema')
    if not sp: return
    full=os.path.join(repo,sp)
    if not os.path.exists(full):
        errors.append(f'{ent["path"]}: source schema missing {sp}')
        return
    schema=json.load(open(full))
    expected=schema_object_contracts(schema)
    oc=contract.get('object_contracts',{})
    for path,keys in expected.items():
        if not keys: continue
        con=oc.get(path)
        if con is None:
            errors.append(f'{ent["path"]}: schema {sid} object {path or "/"} has no template object contract')
            continue
        if con.get('mode')=='closed':
            missing=set(keys)-set(con.get('allowed_keys',[]))
            if missing:
                errors.append(f'{ent["path"]}: schema {sid} fields absent from template at {path or "/"}: {sorted(missing)}')

def main(repo):
    errors=[];checked=0;entries=load_schema_templates(repo)
    # Mutable state: every JSON owner must declare a schema and have a registered template.
    for p in glob.glob(os.path.join(repo,'state','**','*.json'),recursive=True):
        rel=os.path.relpath(p,repo);d=json.load(open(p))
        if not isinstance(d,dict): errors.append(f'{rel}: mutable state root must be object');continue
        sid=d.get('schema')
        if not isinstance(sid,str): errors.append(f'{rel}: mutable state missing schema');continue
        ent=entries.get(sid)
        if not ent: errors.append(f'{rel}: schema {sid!r} has no registered template');continue
        tp=os.path.join(repo,ent['path'])
        if not os.path.exists(tp):errors.append(f'{rel}: missing template {ent["path"]}');continue
        c=json.load(open(tp));validate_doc(rel,d,c,errors);checked+=1
    # Schema-bearing static gameplay/runtime data must also follow a registered structural template.
    static_checked=0
    skip_prefixes=('data/runtime/templates/','data/runtime/template-index-shards/','data/runtime/path-templates/')
    for p in glob.glob(os.path.join(repo,'data','**','*.json'),recursive=True):
        rel=os.path.relpath(p,repo).replace('\\','/')
        if any(rel.startswith(x) for x in skip_prefixes): continue
        d=json.load(open(p))
        if not isinstance(d,dict): continue
        sid=d.get('schema')
        if not isinstance(sid,str): continue
        ent=entries.get(sid)
        if not ent: errors.append(f'{rel}: declared static schema {sid!r} has no registered template'); continue
        tp=os.path.join(repo,ent['path'])
        if not os.path.exists(tp): errors.append(f'{rel}: missing static template {ent["path"]}'); continue
        validate_doc(rel,d,json.load(open(tp)),errors); static_checked+=1
    # Path contracts cover intentionally schema-less static data structures.
    pidx=os.path.join(repo,'data/runtime/path-template-index.json');path_checked=0
    if os.path.exists(pidx):
        pi=json.load(open(pidx))
        for ent in pi.get('templates',[]):
            c=json.load(open(os.path.join(repo,ent['path'])))
            matches=glob.glob(os.path.join(repo,ent['glob']))
            if not matches: errors.append(f'path template {ent["glob"]}: no files matched')
            for p in matches:
                rel=os.path.relpath(p,repo);d=json.load(open(p));validate_doc(rel,d,c,errors);path_checked+=1
    # System update contracts must resolve every referenced template and declared authority/read path.
    scidx=os.path.join(repo,'data/runtime/system-contract-index.json')
    if not os.path.exists(scidx): errors.append('system-contract-index missing')
    else:
        si=json.load(open(scidx))
        for system_id,rel in si.get('systems',{}).items():
            cp=os.path.join(repo,rel)
            if not os.path.exists(cp): errors.append(f'system contract {system_id}: missing {rel}'); continue
            c=json.load(open(cp))
            if c.get('schema')!='system-contract.v1' or c.get('system_id')!=system_id: errors.append(f'{rel}: malformed system contract')
            for sid in c.get('owner_templates',[]):
                if sid not in entries: errors.append(f'{rel}: unknown owner template {sid}')
            for ap in c.get('authority_paths',[]):
                full=os.path.join(repo,ap)
                if '*' in ap:
                    base=ap.split('*',1)[0].rstrip('/')
                    if base and not os.path.exists(os.path.join(repo,base)):
                        errors.append(f'{rel}: authority glob base missing {ap}')
                elif ap.endswith('/'):
                    if not os.path.isdir(full): errors.append(f'{rel}: authority directory missing {ap}')
                elif not os.path.exists(full):
                    errors.append(f'{rel}: authority path missing {ap}')
    # Narration router is a cold module selector: all module paths must exist and stay out of startup hot set.
    nrp=os.path.join(repo,'data/runtime/narration-router.json')
    if not os.path.exists(nrp): errors.append('narration-router missing')
    else:
        nr=json.load(open(nrp))
        mods=nr.get('modules',{})
        for mid,spec in mods.items():
            rel=spec if isinstance(spec,str) else spec.get('path') if isinstance(spec,dict) else None
            if not rel or not os.path.exists(os.path.join(repo,rel)): errors.append(f'narration module {mid}: missing {rel}')
            elif rel in ('VOICE.md','RUNTIME.md'): errors.append(f'narration module {mid}: illegally reloads hot startup file')
    # Registry/template self-consistency.
    for sid,ent in entries.items():
        tp=os.path.join(repo,ent['path'])
        if not os.path.exists(tp): errors.append(f'template index missing {ent["path"]}');continue
        c=json.load(open(tp))
        if c.get('schema')!='file-template.v1' or c.get('target_schema')!=sid or c.get('unknown_key_policy')!='reject': errors.append(f'{ent["path"]}: malformed structural template')
        validate_template_schema_coverage(repo,sid,ent,c,errors)
    if errors:
        print('TEMPLATE CONTRACT FAIL',len(errors))
        for e in errors[:250]:print('-',e)
        if len(errors)>250:print('...',len(errors)-250,'more')
        return 1
    print(f'TEMPLATE CONTRACT OK: {checked} mutable owners; {static_checked} schema-bearing static files; {path_checked} schema-less path-contracted files; {len(entries)} registered structure templates')
    return 0
if __name__=='__main__':raise SystemExit(main(sys.argv[1] if len(sys.argv)>1 else '.'))
