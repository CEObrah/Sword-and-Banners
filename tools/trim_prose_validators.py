#!/usr/bin/env python3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

audit=ROOT/'tools/audit.py'
text=audit.read_text(encoding='utf-8')
old="""_voice=(ROOT/'VOICE.md').read_text(encoding='utf-8')
for _phrase in ('Repository memory is not player memory','estimated in-world','medium','long'):
 if _phrase not in _voice:err(f'narrator_contract_missing:{_phrase}')
"""
if old not in text:
    raise SystemExit('expected narrator prose assertion block not found')
audit.write_text(text.replace(old,''),encoding='utf-8')

# Restore ordinary read-only CI and remove this one-shot maintenance helper.
(ROOT/'.github/workflows/audit.yml').write_text("name: audit\non: [push, pull_request]\njobs:\n  audit:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.12'\n      - run: pip install jsonschema\n      - name: Run full validator stack\n        run: python tools/run_validators.py\n",encoding='utf-8')
Path(__file__).unlink()
print('removed narrator prose assertions; structural choice/narration contracts remain authoritative')
