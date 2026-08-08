#!/usr/bin/env python3
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]
SELF=Path(__file__).resolve()
AUDIT=ROOT/'tools/audit_unreferenced_technical_files.py'
TARGETS=[ROOT/'schemas/process-contract-record-v1.schema.json', ROOT/'schemas/scene.v38.schema.json']

registry=json.loads((ROOT/'schemas/registry.json').read_text(encoding='utf-8'))
registered={str(v) for v in registry.values()}
for p in TARGETS:
    if not p.exists():
        raise SystemExit(f'expected dead schema missing: {p.relative_to(ROOT)}')
    if p.name in registered:
        raise SystemExit(f'refusing to delete registered schema: {p.name}')

# Re-prove zero live reference immediately before deletion. Ignore only the temporary audit/cleanup tools.
ignore={SELF.resolve(),AUDIT.resolve()}
for target in TARGETS:
    rel=str(target.relative_to(ROOT)); needles=(rel,target.name)
    refs=[]
    for p in ROOT.rglob('*'):
        if '.git' in p.parts or not p.is_file() or p.resolve() in ignore or p==target:
            continue
        if p.suffix.lower() not in ('.json','.md','.py','.yml','.yaml','.txt'):
            continue
        try:text=p.read_text(encoding='utf-8')
        except Exception:continue
        if any(n in text for n in needles): refs.append(str(p.relative_to(ROOT)))
    if refs:
        raise SystemExit(f'refusing deletion; {rel} still referenced by {refs}')

for p in TARGETS:
    p.unlink()

# Temporary audit machinery is not a repository feature.
if AUDIT.exists(): AUDIT.unlink()
SELF.unlink()

(ROOT/'.github/workflows/audit.yml').write_text(
    "name: audit\non: [push, pull_request]\njobs:\n  audit:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.12'\n      - run: pip install jsonschema\n      - name: Run full validator stack\n        run: python tools/run_validators.py\n",
    encoding='utf-8')
print('deleted exactly two zero-reference schema files and removed temporary audit machinery')
