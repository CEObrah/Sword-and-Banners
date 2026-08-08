#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

sem = ROOT / 'tools/test_semantics.py'
text = sem.read_text(encoding='utf-8')
replacements = {
"    if size>40000:print(f'CONTEXT ADVISORY: router domain {name} is {size} bytes; split only if retrieval can be narrowed without losing required mechanics')\n": "",
"if (R/'data/runtime/repository-map.json').stat().st_size>14000:print(f\"CONTEXT ADVISORY: repository-map.json is {(R/'data/runtime/repository-map.json').stat().st_size} bytes\")\n": "",
"if (R/'RUNTIME.md').stat().st_size>8000:print(f\"CONTEXT ADVISORY: RUNTIME.md is {(R/'RUNTIME.md').stat().st_size} bytes\")\n": "",
}
for old, new in replacements.items():
    if old not in text:
        raise SystemExit(f'expected context advisory text missing from test_semantics.py: {old!r}')
    text = text.replace(old, new)
sem.write_text(text, encoding='utf-8')

unit = ROOT / 'tools/test_unit_model.py'
text = unit.read_text(encoding='utf-8')
old = """# Context-size advisory only. Correctness and sufficient instructions take priority over a fixed byte ceiling.\nfor rel,advisory in [('RUNTIME.md',8000),('data/runtime/repository-map.json',12000),('VOICE.md',8000)]:\n    size=(R/rel).stat().st_size\n    if size>advisory:print(f'CONTEXT ADVISORY: {rel} is {size} bytes (soft target {advisory}); review only if duplication can be removed safely')\n"""
if old not in text:
    raise SystemExit('expected context-size advisory block missing from test_unit_model.py')
unit.write_text(text.replace(old, ''), encoding='utf-8')

# Artificial byte ceilings/advisories for instruction/routing documents must not return.
for path in (ROOT / 'tools').glob('*.py'):
    blob = path.read_text(encoding='utf-8', errors='ignore')
    if 'CONTEXT ADVISORY' in blob or 'soft target' in blob:
        raise SystemExit(f'context size advisory remains: {path.relative_to(ROOT)}')

# Restore ordinary read-only CI and remove this one-shot helper.
(ROOT / '.github/workflows/audit.yml').write_text(
    "name: audit\non: [push, pull_request]\njobs:\n  audit:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.12'\n      - run: pip install jsonschema\n      - name: Run full validator stack\n        run: python tools/run_validators.py\n",
    encoding='utf-8',
)
Path(__file__).unlink()
print('removed artificial context-size advisories; capability and correctness remain the constraints')
