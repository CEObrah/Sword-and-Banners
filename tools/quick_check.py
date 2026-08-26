#!/usr/bin/env python3
"""Fast source/structure gate for ordinary Sword development.

This intentionally does not replace the deeper release/conservation suite.  It
checks the things that should be true on every branch: Python compiles, active
JSON parses, every schema-bearing object uses a registered schema, and those
objects validate against that schema.
"""
from __future__ import annotations

import compileall
import json
import re
from pathlib import Path

from jsonschema import validators

ROOT = Path(__file__).resolve().parents[1]


def all_json(root: Path):
    for path in root.rglob("*.json"):
        if any(part in {".git", ".pytest_cache", "__pycache__"} for part in path.parts):
            continue
        yield path


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"invalid JSON: {path.relative_to(ROOT)}: {exc}") from exc



ROUTED_PATH_RE = re.compile(r"(?:(?:runtime|game|state|plugins|tools|tests)/[A-Za-z0-9_./{}*\-]+(?:\.py|\.json|\.md))")
RETIRED_FORMATION_KEYS = {"food_kg", "fodder_kg", "fodder", "prepared_training_ground_area", "army_train_ref"}
RETIRED_OPERATION_KEYS = {"food_kg", "fodder_kg", "fodder", "convoy_dispatched", "convoy_received", "formation_logistics_at_review"}
MERCHANT_NPC_RE = re.compile(r"(?:^|[_ -])(merchant|caravan broker)(?:$|[_ -])", re.IGNORECASE)


def _runtime_sources_text() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (ROOT / "runtime" / "sword_runtime").rglob("*.py")
    )


def validate_repository_routes() -> None:
    docs = [
        ROOT / "runtime" / "contracts" / "repository-map.json",
        ROOT / "plugins" / "sword-and-banners" / "skills" / "sword-and-banners-game-master" / "references" / "repository-map.md",
    ]
    runtime_text = _runtime_sources_text()
    missing: list[str] = []
    for doc in docs:
        text = doc.read_text(encoding="utf-8")
        for ref in sorted(set(ROUTED_PATH_RE.findall(text))):
            base = ref.split("#", 1)[0]
            if any(ch in base for ch in "*{}"):  # registered wildcard/lazy families
                continue
            target = ROOT / base
            if target.exists():
                continue
            if base.startswith("state/") and base in runtime_text:
                continue
            missing.append(base)
    if missing:
        raise SystemExit(f"repository map points at missing authorities: {missing[:12]}")


def _walk_dicts(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def validate_retired_state_concepts(parsed: dict[Path, object]) -> None:
    retired_hits: list[str] = []
    for path, value in parsed.items():
        if path.is_relative_to(ROOT / "state" / "formations"):
            for obj in _walk_dicts(value):
                bad = RETIRED_FORMATION_KEYS.intersection(obj)
                if bad:
                    retired_hits.append(f"{path.relative_to(ROOT)}:{sorted(bad)}")
        if path.is_relative_to(ROOT / "state" / "operations"):
            for obj in _walk_dicts(value):
                bad = RETIRED_OPERATION_KEYS.intersection(obj)
                dynamic = sorted(k for k in obj if isinstance(k, str) and k.startswith("state_operation_supply_convoy_"))
                if bad or dynamic:
                    retired_hits.append(f"{path.relative_to(ROOT)}:{sorted(bad)}{dynamic}")
    forbidden_paths = (
        "state/logistics/army-trains",
        "runtime/sword_runtime/army_train_logistics.py",
        "runtime/sword_runtime/mission_contracts.py",
        "game/data/mechanics/mission-contracts.json",
        "state/loot",
        # Rebaselined dead/projection owners and duplicate policy registries.
        "state/time",
        "state/agency/agency-constraints.json",
        "state/app/role-slots.json",
        "state/order/standing-orders.json",
        "state/index/geography-index.json",
        "game/data/training/contracts.json",
        "game/data/people/canon-capability-calibration.json",
        "game/data/mechanics/rules-runtime-parity.json",
        # Retired paper-only organization/world surfaces from the 2026-08-24 rebaseline.
        "game/data/organization/formation-templates.json",
        "game/data/organization/reconstitution-policies.json",
        "game/data/organization/standing-procedures.json",
        "game/data/organization/unit-model.json",
        "game/data/content/world-event-archetypes.json",
        "game/data/mechanics/world-representation-authority.json",
        "game/data/world/regional-lords.json",
        "game/schemas/formation.schema.json",
        "game/schemas/unit.schema.json",
        "game/schemas/formation-library.schema.json",
        "game/schemas/unit-model.schema.json",
        "game/schemas/reconstitution-policies.schema.json",
        "game/schemas/standing-procedures.schema.json",
        "game/schemas/sword-regional-lord-catalog.schema.json",
    )
    for rel in forbidden_paths:
        if (ROOT / rel).exists():
            retired_hits.append(rel)
    # Mercenary reconstitution is derived from current force/cohort state; the
    # removed paper policy reference must not be recreated in hot state.
    for path, value in parsed.items():
        if not path.is_relative_to(ROOT / "state"):
            continue
        for obj in _walk_dicts(value):
            if "reconstitution_policy_ref" in obj:
                retired_hits.append(f"{path.relative_to(ROOT)}:reconstitution_policy_ref")

    if retired_hits:
        raise SystemExit(f"retired gameplay concepts returned: {retired_hits[:10]}")

    # The removed siege commodity mini-economy must not return to executable or
    # current-state authority. All siege construction uses one conserved unit.
    resource_hits: list[str] = []
    for base in (ROOT / "runtime", ROOT / "game", ROOT / "state"):
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".json", ".md"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "timber_tonnes" in text or "iron_tonnes" in text:
                resource_hits.append(path.relative_to(ROOT).as_posix())
    if resource_hits:
        raise SystemExit(f"retired siege commodity bookkeeping returned: {resource_hits[:10]}")

    # Routine commerce stays aggregate and must not require persistent merchant
    # characters merely for markets to function.
    person_roots = [ROOT / "state" / "char", ROOT / "state" / "person" / "person-lite"]
    person_paths = [ROOT / "state" / "player.json"]
    for root in person_roots:
        if root.exists():
            person_paths.extend(root.rglob("*.json"))
    merchant_hits: list[str] = []
    role_keys = {"role", "occupation", "career", "profession", "billet"}
    for path in person_paths:
        value = parsed.get(path)
        if value is None and path.exists():
            value = load_json(path)
        for obj in _walk_dicts(value):
            for key in role_keys:
                raw = obj.get(key)
                if isinstance(raw, str) and MERCHANT_NPC_RE.search(raw):
                    merchant_hits.append(f"{path.relative_to(ROOT)}:{key}={raw}")
    if merchant_hits:
        raise SystemExit(f"persistent merchant NPC role returned: {merchant_hits[:10]}")


def validate_scheduler_host_kinds(parsed: dict[Path, object]) -> None:
    import ast
    import sys
    runtime_root = ROOT / "runtime"
    if str(runtime_root) not in sys.path:
        sys.path.insert(0, str(runtime_root))
    from sword_runtime.time_integration import SUPPORTED_HOST_KINDS

    created: set[str] = set()
    for path in (ROOT / "runtime" / "sword_runtime").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            values = {}
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    values[key.value] = value
            if not {"host_id", "kind", "next_due"}.issubset(values):
                continue
            kind = values["kind"]
            if isinstance(kind, ast.Constant) and isinstance(kind.value, str):
                created.add(kind.value)
    runtime = parsed.get(ROOT / "state" / "runtime.json")
    current = set()
    if isinstance(runtime, dict):
        current = {str(host.get("kind")) for host in runtime.get("hosts", {}).values() if isinstance(host, dict)}
    unknown = sorted((created | current) - set(SUPPORTED_HOST_KINDS))
    if unknown:
        raise SystemExit(f"scheduler host kinds lack explicit dispatch registration: {unknown}")


def validate_command_dispatch_registry() -> None:
    import ast
    import sys
    runtime_root = ROOT / "runtime"
    if str(runtime_root) not in sys.path:
        sys.path.insert(0, str(runtime_root))
    from sword_runtime.command_integration import COMMAND_LAYER_METHODS
    from sword_runtime.engine import RepositoryCommandPlanner
    from sword_runtime.production_runtime_planner import ProductionCampaignPlanner

    declared = set(COMMAND_LAYER_METHODS)
    discovered: set[str] = set()
    exact_dispatch_owners: list[str] = []
    cooperative: list[str] = []
    for path in (ROOT / "runtime" / "sword_runtime").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "super()._dispatch(command" in text:
            cooperative.append(path.relative_to(ROOT).as_posix())
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name == "_dispatch":
                exact_dispatch_owners.append(path.name)
            elif node.name.startswith("_command_layer_"):
                discovered.add(node.name)
    if discovered != declared:
        raise SystemExit(f"command layer registry mismatch: unregistered={sorted(discovered-declared)} stale={sorted(declared-discovered)}")
    if cooperative:
        raise SystemExit(f"cooperative top-level _dispatch chain returned: {cooperative}")
    if sorted(exact_dispatch_owners) != ["command_integration.py", "engine.py"]:
        raise SystemExit(f"unexpected top-level _dispatch owners: {sorted(exact_dispatch_owners)}")
    owners = [cls for cls in ProductionCampaignPlanner.__mro__ if "_dispatch" in cls.__dict__]
    if len(owners) != 2 or owners[0].__module__ != "sword_runtime.command_integration" or owners[1] is not RepositoryCommandPlanner:
        raise SystemExit(f"hosted command dispatch ownership drifted: {[cls.__module__ for cls in owners]}")




def validate_static_record_routes(parsed: dict[Path, object]) -> None:
    """Validate demand-loaded static indexes and refs that schema checks cannot see.

    A registered logical ref is executable input. It must never point to a missing
    file, and current formation doctrine/training refs must resolve through the
    registered indexes rather than surviving as dead save strings.
    """
    indexed: dict[str, dict[str, str]] = {}
    for rel in (
        "game/data/loadouts.json",
        "game/data/mil/doctrines.json",
        "game/data/mil/training.json",
    ):
        doc = parsed.get(ROOT / rel)
        if not isinstance(doc, dict):
            raise SystemExit(f"static routing index missing: {rel}")
        routes = doc.get("record_index")
        if not isinstance(routes, dict):
            raise SystemExit(f"static routing index has no record_index: {rel}")
        clean: dict[str, str] = {}
        missing: list[str] = []
        for ref, target in routes.items():
            if not isinstance(ref, str) or not isinstance(target, str) or not target:
                raise SystemExit(f"invalid static record route in {rel}: {ref!r} -> {target!r}")
            clean[ref] = target
            if not (ROOT / target).is_file():
                missing.append(f"{ref}->{target}")
        if missing:
            raise SystemExit(f"static record routes point at missing files in {rel}: {missing[:10]}")
        indexed[rel] = clean

    doctrine_index = indexed["game/data/mil/doctrines.json"]
    training_index = indexed["game/data/mil/training.json"]
    role_doc = parsed.get(ROOT / "game/data/mil/doctrine-role-profiles.json")
    overlay_doc = parsed.get(ROOT / "game/data/mil/institution-doctrine-overlays.json")
    roles = role_doc.get("profiles", {}) if isinstance(role_doc, dict) else {}
    overlays = overlay_doc.get("overlays", {}) if isinstance(overlay_doc, dict) else {}
    bad_doctrine_refs: list[str] = []
    checked_paths: set[str] = set()
    for logical_ref, target in doctrine_index.items():
        if target in checked_paths:
            continue
        checked_paths.add(target)
        record = parsed.get(ROOT / target)
        if not isinstance(record, dict):
            record = load_json(ROOT / target)
        doctrine = record.get("doctrine") if isinstance(record, dict) else None
        if not isinstance(doctrine, dict):
            bad_doctrine_refs.append(f"{logical_ref}:missing_doctrine_object")
            continue
        role_ref = doctrine.get("role_profile_ref")
        if isinstance(role_ref, str):
            role_key = role_ref.rsplit("#", 1)[-1]
            if role_key not in roles:
                bad_doctrine_refs.append(f"{logical_ref}:unknown_role:{role_key}")
        overlay_ref = doctrine.get("institution_overlay_ref")
        if isinstance(overlay_ref, str):
            overlay_key = overlay_ref.rsplit("#", 1)[-1]
            if overlay_key not in overlays:
                bad_doctrine_refs.append(f"{logical_ref}:unknown_overlay:{overlay_key}")
    if bad_doctrine_refs:
        raise SystemExit(f"doctrine records contain unresolved static refs: {bad_doctrine_refs[:10]}")

    # Closed doctrine policy is executable input, not descriptive prose.  Every
    # registered choice/capability/child doctrine must resolve through the one
    # canonical policy registry so a typo cannot silently become inert policy.
    policy_registry = parsed.get(ROOT / "game/data/mil/doctrine-policy-registry.json")
    if not isinstance(policy_registry, dict):
        raise SystemExit("closed doctrine policy registry missing")
    command_choices = policy_registry.get("command_choices", {})
    formation_choices = policy_registry.get("formation_choices", {})
    compatibility_requirements = policy_registry.get("compatibility_requirements", {})
    closed_errors: list[str] = []
    for logical_ref, target in doctrine_index.items():
        record = parsed.get(ROOT / target)
        if not isinstance(record, dict):
            record = load_json(ROOT / target)
        doctrine = record.get("doctrine") if isinstance(record, dict) else None
        if not isinstance(doctrine, dict):
            continue
        for policy_key, registry_rows in (("command_policy_v2", command_choices), ("formation_policy_v2", formation_choices), ("formation_policy", formation_choices)):
            policy = doctrine.get(policy_key)
            if policy is None:
                continue
            if not isinstance(policy, dict):
                closed_errors.append(f"{logical_ref}:{policy_key}:not_object")
                continue
            for dimension, choice in policy.items():
                allowed = registry_rows.get(dimension) if isinstance(registry_rows, dict) else None
                if not isinstance(allowed, dict):
                    closed_errors.append(f"{logical_ref}:{policy_key}:unknown_dimension:{dimension}")
                elif choice not in allowed:
                    closed_errors.append(f"{logical_ref}:{policy_key}:{dimension}:unknown_choice:{choice}")
        compatibility = doctrine.get("compatibility", [])
        if compatibility is not None:
            if not isinstance(compatibility, list):
                closed_errors.append(f"{logical_ref}:compatibility:not_array")
            else:
                for capability in compatibility:
                    if not isinstance(capability, str) or capability not in compatibility_requirements:
                        closed_errors.append(f"{logical_ref}:unknown_compatibility:{capability}")
        role_policy_refs = doctrine.get("role_policy_refs", {})
        if role_policy_refs is not None:
            if not isinstance(role_policy_refs, dict):
                closed_errors.append(f"{logical_ref}:role_policy_refs:not_object")
            else:
                for role, child_ref in role_policy_refs.items():
                    if not isinstance(role, str) or not isinstance(child_ref, str) or child_ref not in doctrine_index:
                        closed_errors.append(f"{logical_ref}:role_policy_refs:{role}:unresolved:{child_ref}")
    if closed_errors:
        raise SystemExit(f"doctrine records violate closed policy registry: {closed_errors[:10]}")

    formation_root = ROOT / "state" / "formations"
    unresolved: list[str] = []
    for path in formation_root.glob("*.json"):
        formation = parsed.get(path)
        if not isinstance(formation, dict):
            continue
        doctrine_ref = formation.get("doctrine_ref")
        if isinstance(doctrine_ref, str) and doctrine_ref and doctrine_ref not in doctrine_index:
            unresolved.append(f"{path.name}:doctrine:{doctrine_ref}")
        training_ref = formation.get("training_ref")
        if isinstance(training_ref, str) and training_ref and training_ref not in training_index:
            unresolved.append(f"{path.name}:training:{training_ref}")
    if unresolved:
        raise SystemExit(f"current formations contain unresolved static refs: {unresolved[:10]}")

def validate_troop_role_registry(parsed: dict[Path, object]) -> None:
    registry = parsed.get(ROOT / "game/data/organization/troop-types.json")
    profiles = parsed.get(ROOT / "game/data/mil/combat-role-profiles.json")
    if not isinstance(registry, dict) or not isinstance(registry.get("types"), dict):
        raise SystemExit("troop-type registry missing types map")
    if any(isinstance(registry.get(key), dict) and "combat_class" in registry.get(key, {}) for key in registry if key not in {"types", "class_defaults"}):
        raise SystemExit("troop-type entries must live only under troop-types.json#types")
    role_profiles = profiles.get("profiles", {}) if isinstance(profiles, dict) else {}
    if not isinstance(role_profiles, dict):
        raise SystemExit("combat-role profile registry missing profiles map")
    unresolved: list[str] = []
    for path in (ROOT / "state/formations").glob("*.json"):
        formation = parsed.get(path)
        if not isinstance(formation, dict):
            continue
        comp = formation.get("composition")
        if not isinstance(comp, dict):
            continue
        for role, value in comp.items():
            if max(0, int(value or 0)) > 0 and role not in role_profiles:
                unresolved.append(f"{path.name}:missing_combat_role_profile:{role}")
    if unresolved:
        raise SystemExit(f"formation troop roles lack executable combat profiles: {unresolved[:10]}")


def validate_population_projection(parsed: dict[Path, object]) -> None:
    qin = parsed.get(ROOT / "state" / "population" / "qin.json")
    tang = parsed.get(ROOT / "state" / "population" / "tang-manor.json")
    if not isinstance(qin, dict) or not isinstance(tang, dict):
        raise SystemExit("Tang/Qin population authority missing")
    sites = ((qin.get("local_population") or {}).get("sites") or {})
    row = sites.get("loc_tang_manor") if isinstance(sites, dict) else None
    if not isinstance(row, dict):
        raise SystemExit("Qin Tang Manor local population partition missing")
    parent_total = int(row.get("civilian_population", -1))
    detail_total = int(tang.get("population_total", -2))
    detail_sum = sum(max(0, int(v)) for v in (tang.get("strata") or {}).values())
    if parent_total != detail_total or detail_sum != detail_total:
        raise SystemExit(
            f"Tang detailed population drifted from Qin local civilian authority: parent={parent_total} detail={detail_total} strata={detail_sum}"
        )
    demography = tang.get("demography") if isinstance(tang.get("demography"), dict) else {}
    if not tang.get("subset_of_parent") or demography.get("authority") != "parent_population_only":
        raise SystemExit("Tang detailed population regained an independent demographic authority")
    if "birth_rate_per_thousand" in demography or "death_rate_per_thousand" in demography:
        raise SystemExit("Tang detailed population regained duplicate birth/death rates")
    runtime = parsed.get(ROOT / "state" / "runtime.json")
    if isinstance(runtime, dict):
        if "host_population_tang_manor" in (runtime.get("hosts") or {}):
            raise SystemExit("Tang detailed population duplicate scheduler host returned")
        if any(isinstance(row, dict) and row.get("target_host") == "host_population_tang_manor" for row in runtime.get("events", [])):
            raise SystemExit("Tang detailed population duplicate scheduler event returned")

def main() -> int:
    compile_roots = [ROOT / "runtime" / "sword_runtime", ROOT / "tools"]
    for root in compile_roots:
        if not compileall.compile_dir(root, quiet=1):
            raise SystemExit(f"python syntax compilation failed: {root.relative_to(ROOT)}")

    for required in (
        "game/schemas/registry.json",
        "game/data/mechanics/command-catalog.json",
        "game/data/mechanics/unit-duties.json",
        "game/data/mechanics/battlefield-sustainment.json",
        "runtime/contracts/repository-map.json",
        "tools/test_changed.py",
        "tools/run_release_suite.py",
        "plugins/sword-and-banners/skills/sword-and-banners-game-master/SKILL.md",
    ):
        if not (ROOT / required).is_file():
            raise SystemExit(f"required authority missing: {required}")

    # Parse every active game/state/contract JSON before doing schema work.
    parsed: dict[Path, object] = {}
    for base in (ROOT / "game", ROOT / "state", ROOT / "runtime" / "contracts"):
        for path in all_json(base):
            parsed[path] = load_json(path)

    registry = load_json(ROOT / "game" / "schemas" / "registry.json")
    if not isinstance(registry, dict):
        raise SystemExit("game/schemas/registry.json must be an object")

    schema_validators = {}
    for schema_id, filename in sorted(registry.items()):
        schema_path = ROOT / "game" / "schemas" / str(filename)
        if not schema_path.is_file():
            raise SystemExit(f"registered schema file missing: {schema_id} -> {filename}")
        document = load_json(schema_path)
        cls = validators.validator_for(document)
        cls.check_schema(document)
        schema_validators[str(schema_id)] = cls(document)

    unknown: list[tuple[str, str]] = []
    invalid: list[tuple[str, str, str]] = []
    for path, value in parsed.items():
        if not (path.is_relative_to(ROOT / "game") or path.is_relative_to(ROOT / "state")):
            continue
        stack = [value]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                schema_id = current.get("schema")
                if isinstance(schema_id, str):
                    validator = schema_validators.get(schema_id)
                    rel = path.relative_to(ROOT).as_posix()
                    if validator is None:
                        unknown.append((rel, schema_id))
                    else:
                        errors = list(validator.iter_errors(current))
                        if errors:
                            invalid.append((rel, schema_id, errors[0].message))
                stack.extend(current.values())
            elif isinstance(current, list):
                stack.extend(current)

    if unknown:
        raise SystemExit(f"unregistered active schemas: {unknown[:8]}")
    if invalid:
        raise SystemExit(f"active schema validation failures: {invalid[:5]}")

    validate_repository_routes()
    validate_retired_state_concepts(parsed)
    validate_static_record_routes(parsed)
    validate_troop_role_registry(parsed)
    validate_population_projection(parsed)
    validate_scheduler_host_kinds(parsed)
    validate_command_dispatch_registry()

    print(
        "quick_check: PASS "
        f"({len(parsed)} JSON files parsed; {len(schema_validators)} registered schemas validated)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
