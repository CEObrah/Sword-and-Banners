#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_EXTS = {'.json','.md','.py','.yml','.yaml','.txt'}
replacements = {
    'sab_character_v38': 'sab_character',
    'data/runtime/templates/sab_character_v38.template.json': 'data/runtime/templates/sab_character.template.json',
    'schemas/sab-character-v38.schema.json': 'schemas/sab-character.schema.json',
    'sab-character-v38.schema.json': 'sab-character.schema.json',
}
renames = {
    'data/runtime/templates/sab_character_v38.template.json': 'data/runtime/templates/sab_character.template.json',
    'schemas/sab-character-v38.schema.json': 'schemas/sab-character.schema.json',
}

for old_rel, new_rel in renames.items():
    old = ROOT / old_rel
    new = ROOT / new_rel
    if not old.exists():
        raise SystemExit(f'missing source: {old_rel}')
    if new.exists():
        raise SystemExit(f'target already exists: {new_rel}')
    new.parent.mkdir(parents=True, exist_ok=True)
    old.rename(new)

for path in ROOT.rglob('*'):
    if not path.is_file() or '.git' in path.parts or path.suffix.lower() not in TEXT_EXTS:
        continue
    if path.name == Path(__file__).name:
        continue
    text = path.read_text(encoding='utf-8')
    new = text
    for old, repl in sorted(replacements.items(), key=lambda x: len(x[0]), reverse=True):
        new = new.replace(old, repl)
    if new != text:
        path.write_text(new, encoding='utf-8')

# Assert the current structural and formal registries now use the stable semantic ID.
s = json.loads((ROOT / 'data/runtime/template-index-shards/s.json').read_text(encoding='utf-8'))
entry = s.get('templates', {}).get('sab_character')
if not entry:
    raise SystemExit('sab_character template key missing after migration')
if entry.get('path') != 'data/runtime/templates/sab_character.template.json':
    raise SystemExit('sab_character template path mismatch')
if entry.get('source_schema') != 'schemas/sab-character.schema.json':
    raise SystemExit('sab_character formal schema path mismatch')
registry = json.loads((ROOT / 'schemas/registry.json').read_text(encoding='utf-8'))
if registry.get('sab_character') != 'sab-character.schema.json':
    raise SystemExit('sab_character schema registry mismatch')
if 'sab_character_v38' in registry:
    raise SystemExit('legacy sab_character_v38 registry key remains')

print('Migrated sab_character_v38 -> sab_character and renamed its current template/formal schema authorities.')
