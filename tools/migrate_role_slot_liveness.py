from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORLD_TIME = "245-BCE-12-04T07:22:48+08:00"
OLD_REVISION = 19
NEW_REVISION = 20
DEAD_PROCESS = "process_active_canon_roster_monthly"
DEAD_OWNER = "roster.canon_active_world"
ROLE_OWNER = "institution_role_slots"


def load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def dump(rel, data):
    (ROOT / rel).write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def check(cond, msg):
    if not cond:
        raise SystemExit(msg)


def add_once(seq, value):
    if value not in seq:
        seq.append(value)


meta = load("state/meta.json")
check(meta.get("revision") == OLD_REVISION, f"unexpected revision {meta.get('revision')}")
check(meta.get("time") == WORLD_TIME, f"unexpected world time {meta.get('time')}")

# Remove the obsolete name-roster clock and give the real role-slot owner explicit temporal liveness.
frontier = load("state/time/frontier.json")
processes = frontier.get("processes", [])
old = [p for p in processes if p.get("id") == DEAD_PROCESS]
check(len(old) == 1, f"expected exactly one dead roster process, found {len(old)}")
frontier["processes"] = [p for p in processes if p.get("id") != DEAD_PROCESS]
ops = next((p for p in frontier["processes"] if p.get("id") == "process_house_tang_operations_aggregate"), None)
check(ops is not None, "House Tang operations process missing")
coverage = ops.setdefault("coverage", [])
add_once(coverage, ROLE_OWNER)
dump("state/time/frontier.json", frontier)

coverage_req = load("data/runtime/coverage-requirements.json")
req = coverage_req.get("required_owner_ids", [])
check(DEAD_OWNER in req, "stale roster owner no longer present in coverage requirements")
coverage_req["required_owner_ids"] = [x for x in req if x != DEAD_OWNER]
add_once(coverage_req["required_owner_ids"], ROLE_OWNER)
dump("data/runtime/coverage-requirements.json", coverage_req)

# House Tang operations is the liveness owner. Development and life-course processes feed their own domains into the same role owner.
ops_contract = load("state/reg/process-contracts/process_house_tang_operations_aggregate.json")
add_once(ops_contract["standing_orders"], "settle anonymous House Tang role-slot availability, vacancy, retirement state, succession triggers, and materialization handoff without creating secret person sheets")
add_once(ops_contract["standing_orders"], "coordinate due development and life-course effects into the same role-slot owner; no duplicate body or independent hidden clock")
dump("state/reg/process-contracts/process_house_tang_operations_aggregate.json", ops_contract)

dev_contract = load("state/reg/process-contracts/process_house_tang_development_aggregate.json")
add_once(dev_contract["standing_orders"], "for occupied anonymous role slots, convert only evidenced work or training into service-development credit and lawful coarse capability-band change")
add_once(dev_contract["standing_orders"], "role-slot compression grants no exact skill roll, hidden personal achievement, or representation bonus")
dump("state/reg/process-contracts/process_house_tang_development_aggregate.json", dev_contract)

life_contract = load("state/reg/process-contracts/process_canon_life_course_aggregate.json")
add_once(life_contract["standing_orders"], "derive anonymous role-incumbent aging from elapsed time and settle health, retirement, death, vacancy, and succession through the owning institution without inventing identity")
dump("state/reg/process-contracts/process_canon_life_course_aggregate.json", life_contract)

# Delete the process state/contract that belonged only to the removed mutable name roster.
for rel in [
    "state/process-state/process-active-canon-roster-monthly.json",
    "state/reg/process-contracts/process_active_canon_roster_monthly.json",
]:
    p = ROOT / rel
    check(p.exists(), f"expected obsolete file missing: {rel}")
    p.unlink()

# Strengthen the regression test so this stale clock cannot return and role slots cannot silently freeze.
test_path = ROOT / "tools/test_offscreen_scaling.py"
t = test_path.read_text(encoding="utf-8")
anchor = 'if "materialize" not in (R/"rules/siege.md").read_text(encoding="utf-8").lower(): fail("siege_materialization_rule")\n'
check(anchor in t, "offscreen test anchor missing")
extra = '''cov=rj("data/runtime/coverage-requirements.json")\nif "roster.canon_active_world" in cov.get("required_owner_ids",[]): fail("dead_roster_coverage_requirement")\nif "institution_role_slots" not in cov.get("required_owner_ids",[]): fail("role_slots_not_required_live")\nfrontier=rj("state/time/frontier.json")\nfp={p.get("id"):p for p in frontier.get("processes",[])}\nif "process_active_canon_roster_monthly" in fp: fail("dead_roster_process_in_frontier")\nops=fp.get("process_house_tang_operations_aggregate") or {}\nif "institution_role_slots" not in ops.get("coverage",[]): fail("role_slots_not_covered")\nfor rel in ("state/process-state/process-active-canon-roster-monthly.json","state/reg/process-contracts/process_active_canon_roster_monthly.json"):\n    if (R/rel).exists(): fail("dead_roster_process_file:"+rel)\n'''
test_path.write_text(t.replace(anchor, anchor + extra), encoding="utf-8")

# Structural maintenance advances revision but never game time.
meta["revision"] = NEW_REVISION
dump("state/meta.json", meta)

# No active/runtime authority may still depend on the deleted roster/process.
for base in [ROOT / "state", ROOT / "data/runtime", ROOT / "rules"]:
    for p in base.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in {".json", ".md", ".py", ".yml", ".yaml"}:
            continue
        text = p.read_text(encoding="utf-8")
        if DEAD_PROCESS in text or DEAD_OWNER in text or "state/char-roster/index.json" in text:
            raise SystemExit(f"stale active roster dependency survives: {p.relative_to(ROOT)}")

subprocess.run(["python", "tools/run_validators.py"], cwd=ROOT, check=True)

# One-shot helper disappears; normal CI is restored before committing.
(ROOT / "tools/migrate_role_slot_liveness.py").unlink()
(ROOT / ".github/workflows/audit.yml").write_text("""name: audit\non: [push, pull_request]\njobs:\n  audit:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.12'\n      - run: pip install jsonschema\n      - name: Run full validator stack\n        run: python tools/run_validators.py\n""", encoding="utf-8")

subprocess.run(["python", "tools/run_validators.py"], cwd=ROOT, check=True)
check(load("state/meta.json")["time"] == WORLD_TIME, "maintenance advanced world time")
check(load("state/meta.json")["revision"] == NEW_REVISION, "revision mismatch")
check(not (ROOT / "tools/migrate_role_slot_liveness.py").exists(), "one-shot helper survived")

subprocess.run(["git", "config", "user.name", "github-actions[bot]"], cwd=ROOT, check=True)
subprocess.run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], cwd=ROOT, check=True)
subprocess.run(["git", "add", "-A"], cwd=ROOT, check=True)
subprocess.run(["git", "commit", "-m", "Make institutional role slots temporally live"], cwd=ROOT, check=True)
subprocess.run(["git", "push", "origin", "HEAD:maintenance/role-slot-liveness"], cwd=ROOT, check=True)
print("ROLE_SLOT_LIVENESS_COMMITTED")
