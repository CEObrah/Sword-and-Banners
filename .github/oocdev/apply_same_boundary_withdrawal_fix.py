from pathlib import Path

path = Path("runtime/sword_runtime/battle_command.py")
text = path.read_text()
needle = '''        if not active_mission_refs:\n            continue\n        sector = sectors[sector_ref]\n'''
replacement = '''        if not active_mission_refs:\n            continue\n        # A withdrawal that became effective at this exact chronology boundary is\n        # terminal evidence first, not an invitation for the standing mission\n        # review to overwrite it in the same instant.  If the wider battle does\n        # not terminate, a later lawful review/counter-order may still retask it.\n        if all(\n            isinstance(assignments.get(ref), Mapping)\n            and assignments[ref].get("order") == "withdraw"\n            and not assignments[ref].get("pending_order")\n            and str(assignments[ref].get("updated_at") or "") == at\n            for ref in active_mission_refs\n        ):\n            continue\n        sector = sectors[sector_ref]\n'''
if replacement in text:
    raise SystemExit("same-boundary withdrawal guard already present")
if text.count(needle) != 1:
    raise SystemExit(f"expected one patch site, found {text.count(needle)}")
path.write_text(text.replace(needle, replacement, 1))
