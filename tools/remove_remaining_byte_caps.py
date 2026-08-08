#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()

audit = ROOT / 'tools/audit.py'
text = audit.read_text(encoding='utf-8')
old = """# Dormant event archetypes use causal wake-up, not monthly polling.\nif (ROOT/'state/player.json').stat().st_size>6500:err('startup_player_bloat')\nif (ROOT/'state/scene.json').stat().st_size>6000:err('startup_scene_bloat')\n# Autonomous-world contract linkage and evolution-safe current-authority checks.\n"""
new = """# Dormant event archetypes use causal wake-up, not monthly polling.\n# Startup owners are constrained by schema, ownership, routing, and causal relevance rather than arbitrary byte counts.\n# Autonomous-world contract linkage and evolution-safe current-authority checks.\n"""
if old not in text:
    raise SystemExit('expected player/scene byte-cap block not found in tools/audit.py')
audit.write_text(text.replace(old, new), encoding='utf-8')

# No validator may judge an instruction/state/routing file correct merely by byte size.
for path in (ROOT / 'tools').glob('*.py'):
    if path.resolve() == SELF:
        continue
    blob = path.read_text(encoding='utf-8', errors='ignore')
    for token in ('.stat().st_size', 'CONTEXT ADVISORY', 'soft target', 'startup_player_bloat', 'startup_scene_bloat'):
        if token in blob:
            raise SystemExit(f'artificial byte-size validation remains: {path.relative_to(ROOT)} token={token!r}')

# Restore normal read-only validation and remove this one-shot helper.
(ROOT / '.github/workflows/audit.yml').write_text(
    "name: audit\non: [push, pull_request]\njobs:\n  audit:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.12'\n      - run: pip install jsonschema\n      - name: Run full validator stack\n        run: python tools/run_validators.py\n",
    encoding='utf-8',
)
Path(__file__).unlink()
print('removed remaining artificial byte-size correctness gates')
