#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from jsonschema import validators as jsonschema_validators

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from sword_runtime.command_contracts import COMMAND_PAYLOAD_KEYS
from sword_runtime.engine import COMMAND_TYPES
from sword_runtime.sim.calendar import CampaignTime

checks: list[tuple[str, bool, str]] = []


def check(name, fn):
    try:
        detail = fn()
        checks.append((name, True, "" if detail is None else str(detail)))
    except Exception as exc:
        checks.append((name, False, f"{type(exc).__name__}: {exc}"))


def j(path: str):
    return json.load(open(ROOT / path))


def ok(value, message: str = "failed"):
    assert value, message
    return None


check("architecture_roots", lambda: ok(all((ROOT / x).is_dir() for x in ("runtime", "game", "state"))))
check(
    "cross_game_runtime_separation",
    lambda: ok(
        not re.search(
            r"(^|\n)\s*(from|import)\s+shinobi",
            "\n".join(p.read_text(errors="ignore") for p in (ROOT / "runtime/sword_runtime").rglob("*.py")),
            re.I,
        )
    ),
)
check(
    "registered_top_level_schemas",
    lambda: (
        lambda reg: ok(
            all(
                not isinstance(d := json.load(open(p)), dict)
                or not isinstance(d.get("schema"), str)
                or d["schema"] in reg
                for p in list((ROOT / "state").rglob("*.json")) + list((ROOT / "game").rglob("*.json"))
            )
        )
    )(j("game/schemas/registry.json")),
)
check(
    "unique_mutable_authority",
    lambda: (
        lambda owners: ok(len(owners) == len(set(owners)) and all((ROOT / p).is_file() for p in owners.values()))
    )(j("state/index/owner-index-gold.json")["owners"]),
)


def active_owner_routing():
    owners = j("state/index/owner-index-gold.json")["owners"]
    for path in (ROOT / "state").rglob("*.json"):
        doc = json.load(open(path))
        if isinstance(doc, dict) and isinstance(doc.get("owner_id"), str):
            ok(owners.get(doc["owner_id"]) == path.relative_to(ROOT).as_posix(), f"unrouted active owner {doc['owner_id']}")


check("all_active_owner_ids_routed", active_owner_routing)
check(
    "single_relationship_authority",
    lambda: ok(
        (ROOT / "state/relationships-gold.json").is_file()
        and not (ROOT / "state/rel").exists()
        and (ROOT / "archive/legacy-execution/relationships-pre-gold").is_dir()
    ),
)
check(
    "retired_execution_paths",
    lambda: ok(
        all(not (ROOT / p).exists() for p in ("state/process-state", "state/unit", "state/force-pool", "game/data/runtime"))
        and (ROOT / "archive/legacy-execution").is_dir()
    ),
)
check(
    "current_only_runtime_router",
    lambda: ok(
        set(j("runtime/contracts/repository-map.json"))
        == {
            "runtime_authority",
            "game_authority",
            "campaign_authority",
            "transaction_entrypoint",
            "scheduler_owner",
            "owner_index",
            "player_interface",
            "ordinary_gameplay_mutation",
            "legacy_execution_authority",
        }
    ),
)
check(
    "unversioned_gameplay_tree",
    lambda: ok(not re.search(r"\bversion\b|\bv[0-9]+\b|release[- ]history", (ROOT / "game/rules/process.md").read_text(), re.I)),
)
check(
    "semantic_command_surface",
    lambda: ok(len(COMMAND_TYPES) >= 45 and set(j("game/data/mechanics/command-catalog.json")["commands"]) == set(COMMAND_TYPES)),
)


def safe_horizon():
    runtime = j("state/runtime.json")
    for host in runtime["hosts"].values():
        if host.get("next_due"):
            ok(CampaignTime.parse(host["resolved_through"]) <= CampaignTime.parse(host["safe_through"]) < CampaignTime.parse(host["next_due"]))


check("scheduler_safe_horizons", safe_horizon)
check(
    "zero_global_polling",
    lambda: ok(all(j("state/runtime.json")["metrics"][k] == 0 for k in ("global_person_scans", "global_faction_scans", "global_force_scans", "global_house_scans"))),
)
check(
    "autonomous_actor_coverage",
    lambda: (
        lambda rt: ok(
            sum(1 for h in rt["hosts"].values() if h["kind"] == "state") == 7
            and sum(1 for h in rt["hosts"].values() if h["kind"] == "house") >= 10
            and sum(1 for h in rt["hosts"].values() if h["kind"] == "institution") >= 42
            and sum(1 for h in rt["hosts"].values() if h["kind"] == "faction") >= 15
        )
    )(j("state/runtime.json")),
)
check(
    "mercenary_causal_hosts",
    lambda: (
        lambda rt: ok(
            sum(1 for h in rt["hosts"].values() if h.get("kind") == "mercenary") == 60
            and sum(1 for h in rt["hosts"].values() if h.get("kind") == "person") >= 70
            and sum(1 for h in rt["hosts"].values() if h.get("kind") == "interstate") == 1
        )
    )(j("state/runtime.json")),
)


def active_mercenary_schema_integrity():
    registry = j("game/schemas/registry.json")
    compiled = {}
    for path in (ROOT / "state/merc").rglob("*.json"):
        doc = json.load(open(path))
        schema_id = doc.get("schema")
        ok(isinstance(schema_id, str) and schema_id in registry, f"unregistered mercenary schema in {path.relative_to(ROOT)}")
        if schema_id not in compiled:
            schema = j("game/schemas/" + registry[schema_id])
            cls = jsonschema_validators.validator_for(schema)
            cls.check_schema(schema)
            compiled[schema_id] = cls(schema)
        errors = list(compiled[schema_id].iter_errors(doc))
        ok(not errors, f"{path.relative_to(ROOT)}: {errors[0].message if errors else 'invalid'}")


check("active_mercenary_schema_integrity", active_mercenary_schema_integrity)


def rules_runtime_parity():
    parity = j("game/data/mechanics/rules-runtime-parity.json")
    entries = parity.get("entries", [])
    refs = [str(entry.get("rule_ref")) for entry in entries]
    actual = {p.relative_to(ROOT).as_posix() for p in (ROOT / "game/rules").rglob("*.md")}
    ok(set(refs) == actual, f"parity coverage mismatch missing={sorted(actual-set(refs))} extra={sorted(set(refs)-actual)}")
    ok(len(refs) == len(set(refs)), "duplicate rule parity entries")
    engine = (ROOT / "runtime/sword_runtime/engine.py").read_text()
    development = (ROOT / "runtime/sword_runtime/development.py").read_text()
    host_kinds = {str(h.get("kind")) for h in j("state/runtime.json")["hosts"].values()}
    for entry in entries:
        status = str(entry.get("implementation_status"))
        commands = {str(x) for x in entry.get("production_commands", [])}
        hooks = [str(x) for x in entry.get("runtime_hooks", [])]
        hosts = {str(x) for x in entry.get("causal_host_kinds", [])}
        ok(commands <= set(COMMAND_TYPES), f"{entry['rule_ref']} lists nonproduction commands {sorted(commands-set(COMMAND_TYPES))}")
        ok(hosts <= host_kinds, f"{entry['rule_ref']} lists missing host kinds {sorted(hosts-host_kinds)}")
        for hook in hooks:
            token = hook.split(".")[-1]
            ok(token in engine or token in development, f"{entry['rule_ref']} lists missing runtime hook {hook}")
        if status in {"live", "mixed"}:
            ok(bool(commands or hooks or hosts), f"{entry['rule_ref']} claims {status} without executable production hook")
        if status in {"mixed", "descriptive", "deferred"}:
            ok(bool(str(entry.get("deferred_scope", "")).strip()), f"{entry['rule_ref']} {status} entry must state nonimplemented/descriptive scope")


check("rules_to_runtime_parity", rules_runtime_parity)


def exact_person_causal_hosts():
    owners = j("state/index/owner-index-gold.json")["owners"]
    chars = {ref for ref in owners if str(ref).startswith("char_")}
    hosted = {str(h.get("owner_ref")) for h in j("state/runtime.json")["hosts"].values() if h.get("kind") == "person"}
    ok(chars <= hosted, f"exact people without person hosts: {sorted(chars-hosted)[:8]}")


check("exact_person_causal_hosts", exact_person_causal_hosts)
check(
    "autonomous_interstate_history_loop",
    lambda: (
        lambda rt, cfg, idx: ok(
            sum(1 for h in rt["hosts"].values() if h.get("kind") == "interstate") == 1
            and bool(cfg.get("theaters"))
            and idx.get("interstate_warring_states") == "state/politics/interstate-history.json"
        )
    )(j("state/runtime.json"), j("game/data/world/autonomous-theaters.json"), j("state/index/owner-index-gold.json")["owners"]),
)
check("hostile_rules_parity_suite_mandatory", lambda: ok("tests/runtime/test_rules_parity_adversarial.py" in (ROOT / "tools/run_gold_suite.py").read_text()))
check("command_wide_hostile_matrix_mandatory", lambda: ok("tests/runtime/test_hostile_command_matrix.py" in (ROOT / "tools/run_gold_suite.py").read_text()))


def command_payload_contract_coverage():
    catalog = set(j("game/data/mechanics/command-catalog.json")["commands"])
    ok(set(COMMAND_PAYLOAD_KEYS) == catalog, f"payload contract drift missing={sorted(catalog-set(COMMAND_PAYLOAD_KEYS))} extra={sorted(set(COMMAND_PAYLOAD_KEYS)-catalog)}")


check("command_payload_contract_coverage", command_payload_contract_coverage)


def hostile_contract_registry():
    contract = j("game/data/mechanics/command-hostile-contracts.json")
    catalog = set(j("game/data/mechanics/command-catalog.json")["commands"])
    ok(contract.get("schema") == "sword-hostile-command-contracts.v1", "wrong hostile contract schema")
    ok(set(contract.get("commands", {})) == catalog, "hostile contract command drift")
    ok({"unknown_field", "wrong_actor", "stale_revision", "impossible_chronology", "internal_preview"} <= set(contract.get("universal_attacks", [])), "hostile contract missing universal attacks")
    ok(all(bool(value) for value in contract.get("commands", {}).values()), "every command needs at least one command-specific hostile dimension")


check("hostile_command_contract_registry", hostile_contract_registry)
check(
    "server_owned_chronology_and_preview_security",
    lambda: (
        lambda src: ok(
            "submitted_at must equal authoritative campaign world time" in src
            and "contested outcomes are execute-only" in src.lower()
            and "command.command_type" in src
        )
    )((ROOT / "runtime/sword_runtime/engine.py").read_text()),
)
check(
    "player_authority_is_capability_scoped",
    lambda: (
        lambda authority: ok(
            authority["actor_ref"] == j("state/meta.json")["player_id"]
            and authority.get("state_offices") == []
            and all(
                role.get("authority_ref") not in {"state_qin", "state_zhao", "state_chu", "state_wei", "state_han", "state_yan", "state_qi"}
                for role in authority.get("roles", [])
            )
        )
    )(j("state/authority/char-tang-wei.json")),
)


def populations():
    for state in ("qin", "zhao", "chu", "wei", "han", "yan", "qi"):
        pop = j(f"state/population/{state}.json")
        ok(pop["population_total"] == sum(pop["strata"].values()), state)


check("population_conservation", populations)


def forces():
    for state in ("qin", "zhao", "chu", "wei", "han", "yan", "qi"):
        force = j(f"state/forces/state-{state}.json")
        total = sum(force["available_by_role"].values())
        total += sum(v["personnel"] if isinstance(v, dict) else v for v in force["allocated_to_formations"].values())
        total += sum(v.get("personnel", 1) if isinstance(v, dict) else v for v in force["materialized_people"].values())
        ok(total == force["headcount"], state)


check("force_conservation", forces)


def mounts():
    for state in ("qin", "zhao", "chu", "wei", "han", "yan", "qi"):
        mount = j(f"state/mounts/{state}.json")
        ok(sum(mount["types"].values()) == mount["total"] and sum(mount["health"].values()) == mount["total"], state)


check("mount_conservation", mounts)
check("champions_protection_doctrine", lambda: ok(all(j(f"state/formations/{name}.json")["doctrine_behavior"]["primary_success_condition"] == "Tang Wei returns alive" for name in ("tang-champions-first", "tang-champions-second"))))
check("ownership_command_distinction", lambda: (lambda formation: ok(formation["owner_force_ref"] == "force_house_tang" and "command_authority" in formation and formation["administrative_owner"] != formation["owner_force_ref"]))(j("state/formations/tang-champions-first.json")))
check("formation_material_units_explicit", lambda: ok(all("equipment_units_by_role" in json.load(open(path)) and "logistics" in json.load(open(path)) and "mounts" in json.load(open(path)) for path in (ROOT / "state/formations").glob("*.json"))))
check("house_tang_single_treasury_authority", lambda: (lambda house, idx: ok("treasury_silver" not in house and house.get("treasury_ref") == "treasury_house_tang" and idx.get("treasury_house_tang") == "state/treasury/treasury-house-tang.json"))(j("state/houses/house_tang.json"), j("state/index/owner-index-gold.json")["owners"]))
check("information_knowledge_boundary", lambda: ok("knowers" in j("game/schemas/sword-information.schema.json")["required"]))
check("canon_future_not_predetermined", lambda: (lambda canon: ok(canon.get("future_commitments") in ([], None) and bool(canon.get("conditional_future_pressures"))))(j("game/data/history/canon-background.json")))
check("world_density", lambda: ok(len(j("game/data/world/noble-houses.json")["houses"]) >= 40 and len(j("game/data/world/locations.json")["locations"]) >= 70 and len(j("game/data/world/routes.json")["routes"]) >= 50))
check("location_functionality", lambda: ok(any("supply" in x.get("functions", []) for x in j("game/data/world/locations.json")["locations"]) and any(x.get("flavor_only") for x in j("game/data/world/locations.json")["locations"])))


def routes():
    refs = {x["ref"] for x in j("game/data/world/locations.json")["locations"]}
    for route in j("game/data/world/routes.json")["routes"]:
        ok(route["a"] in refs and route["b"] in refs and route["hours"] > 0)


check("route_integrity", routes)
check("economy_balance", lambda: (lambda economy, treasury: ok(economy["service_issue"]["standard_service_kit_is_state_issue"] and float(economy["wages"]["professional_soldier_monthly_silver"]) > float(economy["wages"]["unskilled_monthly_silver"]) and economy["prices_silver"]["common_sword"] <= 2 * float(economy["wages"]["professional_soldier_monthly_silver"]) and treasury["stable_monthly_flows"]["revenue_silver"] > treasury["stable_monthly_flows"]["expense_silver"] and treasury["silver"] >= treasury["stable_monthly_flows"]["expense_silver"] * 12))(j("game/data/mechanics/economy-gold.json"), j("state/treasury/treasury-house-tang.json")))
check("institution_functionality", lambda: ok(len(list((ROOT / "state/institutions").glob("*.json"))) == 42 and all("capacity" in json.load(open(path)) for path in (ROOT / "state/institutions").glob("*.json"))))
check("siege_fail_closed_authority", lambda: ok(j("game/data/world/fortification-profiles.json")["profiles"][0]["materialization_required"] is True and "garrison_formation_refs" in j("game/schemas/sword-fortification.schema.json")["required"]))

SKILL_ROOT = ROOT / "plugins/sword-and-banners/skills/sword-and-banners-game-master"
PLAYER_INTERFACE = SKILL_ROOT / "references/player-interface.md"
RUNTIME_ARCHITECTURE = SKILL_ROOT / "references/runtime-architecture.md"

check(
    "railway_service_readiness",
    lambda: ok(
        (ROOT / "railway.toml").is_file()
        and not (ROOT / "railway.json").exists()
        and '"**"' in (ROOT / "railway.toml").read_text()
        and '"!/state/**"' in (ROOT / "railway.toml").read_text()
        and (ROOT / "runtime/sword_runtime/bootstrap.py").is_file()
        and (ROOT / "runtime/sword_runtime/api/mcp.py").is_file()
        and "mcp==2.0.0" in (ROOT / "pyproject.toml").read_text()
        and "from mcp.server.mcpserver import MCPServer" in (ROOT / "runtime/sword_runtime/api/mcp.py").read_text()
        and "mcp.server.fastmcp" not in (ROOT / "runtime/sword_runtime/api/mcp.py").read_text()
    ),
)
check("player_interface_semantic_only", lambda: ok("do not edit campaign json manually" in PLAYER_INTERFACE.read_text().lower() and "semantic command" in PLAYER_INTERFACE.read_text().lower()))
check("git_campaign_canonical", lambda: ok((ROOT / ".git").is_dir() and "state/" in RUNTIME_ARCHITECTURE.read_text() and "Git" in RUNTIME_ARCHITECTURE.read_text()))
check(
    "canonical_skill_docs",
    lambda: ok(
        (SKILL_ROOT / "SKILL.md").is_file()
        and all((SKILL_ROOT / "references" / name).is_file() for name in ("narration.md", "player-interface.md", "runtime-architecture.md", "repository-map.md", "ooc-dev.md", "live-play-review.md", "choices.md"))
        and (ROOT / "docs/RUNTIME_SERVICE_DEPLOYMENT.md").is_file()
        and all(not (ROOT / name).exists() for name in ("AGENTS.md", "DEPLOYMENT.md", "PLAYER_INTERFACE.md", "REPOSITORY_MAP.md", "RUNTIME.md", "VOICE.md"))
    ),
)
check("gold_ci_release_gate", lambda: (lambda workflow: ok("tools/run_gold_suite.py" in workflow and "tools/run_validators.py" not in workflow))((ROOT / ".github/workflows/audit.yml").read_text()))
check("wal_pending_only_hot_recovery", lambda: (lambda wal, coordinator: ok("recoverable_records" in wal and "pending_directory" in wal and "terminal_directory" in wal and "self.wal.recoverable_records()" in coordinator))((ROOT / "runtime/sword_runtime/tx/wal.py").read_text(), (ROOT / "runtime/sword_runtime/tx/coordinator.py").read_text()))
check("gold_soak_is_mandatory", lambda: (lambda suite, gate: ok("tools/run_gold_soak_gate.py" in suite and "TRANSACTIONS = 1000" in gate and "run_one('replay-a'" in gate and "run_one('replay-b'" in gate and "final_root_hash" in gate and "MAX_GROWTH_RATIO" in gate))((ROOT / "tools/run_gold_suite.py").read_text(), (ROOT / "tools/run_gold_soak_gate.py").read_text()))
check("no_shadow_legacy_indexes", lambda: ok(not (ROOT / "state/index/owners").exists() and not (ROOT / "state/index/owners.json").exists() and not (ROOT / "state/index/units.json").exists() and not (ROOT / "state/reg").exists() and not (ROOT / "state/org").exists() and not (ROOT / "state/train").exists()))
check("no_retired_process_refs", lambda: ok(not re.search(r"registry_processes#|state/(?:process-state|unit|force-pool|reg|org)/", "\n".join(p.read_text(errors="ignore") for p in list((ROOT / "state").rglob("*.json")) + list((ROOT / "game").rglob("*.json"))), re.I)))
check("sword_only_schema_vocabulary", lambda: ok('"shinobi"' not in "\n".join(p.read_text(errors="ignore").lower() for p in (ROOT / "game/schemas").glob("*.json"))))

failed = [entry for entry in checks if not entry[1]]
for name, passed, detail in checks:
    print("PASS" if passed else "FAIL", name, detail)
print(f"PRODUCTION AUDIT: {len(checks)-len(failed)}/{len(checks)} PASS")
if failed:
    raise SystemExit(1)
