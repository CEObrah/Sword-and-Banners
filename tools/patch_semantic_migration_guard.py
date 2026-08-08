#!/usr/bin/env python3
from pathlib import Path
p=Path(__file__).resolve().parent/'migrate_current_semantics.py'
s=p.read_text(encoding='utf-8')
old="text_replace('RUNTIME.md',["
if old not in s:
    raise SystemExit('RUNTIME migration block not found')
p.write_text(s.replace(old,"optional_replace('RUNTIME.md',[",1),encoding='utf-8')
Path(__file__).unlink()
print('runtime prose replacement made idempotent')
