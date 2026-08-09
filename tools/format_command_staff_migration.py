#!/usr/bin/env python3
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for rel in (
    "data/mechanics/command.json",
    "state/cmd/army-registry.json",
    "state/cmd/staff-role-slots.json",
    "state/reg/process-contracts/process_external_state_ecosystem.json",
):
    p=ROOT/rel
    obj=json.loads(p.read_text(encoding="utf-8"))
    p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("formatted touched command/staff owners")
