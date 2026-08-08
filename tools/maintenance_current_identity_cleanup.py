#!/usr/bin/env python3
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IDX = ROOT / 'data/runtime/template-index.json'
RELEASE_RE = re.compile(r'\.v(?:38|39)$')
PATH_RELEASE_RE = re.compile(r'([.-])v(?:38|39)(?=[.-])')
TEXT_EXTS = {'.json','.md','.py','.yml','.yaml','.txt'}


def load_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def dump_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')


def clean_path(rel):
    return PATH_RELEASE_RE.sub('', rel)


def safe_rename(old_rel, new_rel):
    if old_rel == new_rel:
        return
    old = ROOT / old_rel
    new = ROOT / new_rel
    if not old.exists():
        raise SystemExit(f'missing rename source: {old_rel}')
    new.parent.mkdir(parents=True, exist_ok=True)
    if new.exists():
        if old.read_bytes() != new.read_bytes():
            raise SystemExit(f'rename collision: {old_rel} -> {new_rel}')
        old.unlink()
    else:
        old.rename(new)


def main():
    idx = load_json(IDX)
    sid_map = {}
    path_map = {}
    for _, rel in idx['shards'].items():
        doc = load_json(ROOT / rel)
        for sid, ent in list(doc.get('templates', {}).items()):
            if ent.get('scope') == 'mutable_state' and RELEASE_RE.search(sid):
                new_sid = RELEASE_RE.sub('', sid)
                sid_map[sid] = new_sid
                for key in ('path','source_schema'):
                    old_path = ent.get(key)
                    if isinstance(old_path, str):
                        new_path = clean_path(old_path)
                        if new_path != old_path:
                            path_map[old_path] = new_path

    if not sid_map:
        print('No mutable v38/v39 schema identities remain.')
        return 0

    for old_rel, new_rel in sorted(path_map.items(), key=lambda x: len(x[0]), reverse=True):
        safe_rename(old_rel, new_rel)

    replacements = {**sid_map, **path_map}
    for path in ROOT.rglob('*'):
        if not path.is_file() or '.git' in path.parts or path.suffix.lower() not in TEXT_EXTS:
            continue
        text = path.read_text(encoding='utf-8')
        new = text
        for old, repl in sorted(replacements.items(), key=lambda x: len(x[0]), reverse=True):
            new = new.replace(old, repl)
        if new != text:
            path.write_text(new, encoding='utf-8')

    idx = load_json(IDX)
    for _, rel in idx['shards'].items():
        p = ROOT / rel
        doc = load_json(p)
        out = {}
        for sid, ent in doc.get('templates', {}).items():
            new_sid = sid_map.get(sid, sid)
            if new_sid in out and out[new_sid] != ent:
                raise SystemExit(f'template key collision: {sid} -> {new_sid}')
            out[new_sid] = ent
        doc['templates'] = dict(sorted(out.items()))
        dump_json(p, doc)

    runtime = ROOT / 'RUNTIME.md'
    rt = runtime.read_text(encoding='utf-8')
    old = '`OOC:` never persists. `PREVIEW:` computes without persistence. `ORDER:` expresses in-world intent but still requires authority, mechanics, time, validation, and successful save. Questions/brainstorming are not orders.'
    new = '`OOC:` never persists. Ordinary in-world natural-language declarations are gameplay instructions and still require authority, mechanics, time, validation, and successful save. Questions, hypotheticals, comparisons, audits, and brainstorming are nonpersistent unless the player actually forms or communicates the intent in-world.'
    if old not in rt:
        raise SystemExit('RUNTIME intent-token paragraph not found')
    runtime.write_text(rt.replace(old, new), encoding='utf-8')

    pi = ROOT / 'PLAYER_INTERFACE.md'
    pt = pi.read_text(encoding='utf-8')
    old_block = '''## Intent prefixes\n\n- `OOC:` discussion/design only. Never persist a roster, appointment, relationship, acquisition, war plan, doctrine change, or other campaign fact.\n- `PREVIEW:` calculate organization, authority, costs, time, logistics, requirements, blockers, and likely consequences without persistence.\n- `ORDER:` explicit in-world player order. Validate authority, resources, time, information, legality, and persistence before narrating success.\n\nNatural language remains valid. Questions, comparisons, and brainstorming are not orders.\n'''
    new_block = '''## Intent boundary\n\n- `OOC:` discussion/design only. Never persist a roster, appointment, relationship, acquisition, war plan, doctrine change, or other campaign fact.\n- Ordinary in-world natural-language declarations are gameplay instructions. Validate authority, resources, time, information, legality, and persistence before narrating success.\n- Questions, comparisons, audits, hypotheticals, wishlists, and brainstorming are nonpersistent unless the player actually forms or communicates the intent in-world.\n\nNo special gameplay command prefix is required.\n'''
    if old_block not in pt:
        raise SystemExit('PLAYER_INTERFACE intent block not found')
    pt = pt.replace(old_block, new_block)
    pt = pt.replace('PREVIEW REORGANIZATION', 'REORGANIZATION REVIEW')
    pt = pt.replace('PREVIEW:', 'OOC:')
    pt = pt.replace('ORDER:', '')
    pi.write_text(pt, encoding='utf-8')

    intent_path = ROOT / 'tests/interface-intent.json'
    intent = load_json(intent_path)
    intent['cases'] = [
        {'input':'OOC: Would this officer be a good future commander?','expected_persistence':False},
        {'input':'OOC: Calculate a formation from my currently assigned troops.','expected_persistence':False},
        {'input':'Adopt the reviewed formation using only troops lawfully assigned to me.','expected_persistence':'normal_transaction_required'}
    ]
    dump_json(intent_path, intent)

    audit = ROOT / 'tools/audit.py'
    at = audit.read_text(encoding='utf-8')
    old_audit = "for _phrase in ('OOC:','PREVIEW:','ORDER:','FORM UNIT','FORMATION SETUP','CHECKPOINT'):\n if _phrase not in _iface:err(f'player_interface_missing:{_phrase}')"
    new_audit = "for _phrase in ('OOC:','No special gameplay command prefix is required.','FORM UNIT','FORMATION SETUP','CHECKPOINT'):\n if _phrase not in _iface:err(f'player_interface_missing:{_phrase}')\nfor _phrase in ('PRE'+'VIEW:','OR'+'DER:'):\n if _phrase in _iface:err(f'player_interface_obsolete_token:{_phrase}')"
    if old_audit not in at:
        raise SystemExit('audit interface-token contract not found')
    audit.write_text(at.replace(old_audit, new_audit), encoding='utf-8')

    leftovers = []
    for path in ROOT.rglob('*'):
        if not path.is_file() or '.git' in path.parts or path.suffix.lower() not in TEXT_EXTS:
            continue
        if path.name == Path(__file__).name:
            continue
        text = path.read_text(encoding='utf-8')
        if 'PREVIEW:' in text or 'ORDER:' in text:
            leftovers.append(str(path.relative_to(ROOT)))
    if leftovers:
        raise SystemExit('obsolete interface tokens remain: ' + ', '.join(leftovers))

    print(f'Migrated {len(sid_map)} mutable release-suffixed schema identities.')
    for old, new_sid in sorted(sid_map.items()):
        print(f'  {old} -> {new_sid}')
    print(f'Renamed {len(path_map)} registered schema/template authority files.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
