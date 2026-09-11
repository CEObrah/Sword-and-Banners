#!/usr/bin/env python3
"""Prove critical Sword regressions can detect intentionally restored bugs.

Each mutant is applied only inside a disposable full repository copy. The
canonical tree and campaign state are never edited. A mutation is considered
killed only when its baseline selector passes in the real candidate, the mutated
source still compiles, and the same selector then fails.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Mutation:
    name: str
    relpath: str
    replacements: tuple[tuple[str, str], ...]
    selector: str


MUTATIONS = (
    Mutation(
        "playability-lab-critical-chain-omission",
        "tools/playability_lab.py",
        (('    "tests/runtime/test_campaign_command_to_arrival_e2e.py::test_actionable_campaign_order_reaches_operational_area_without_command_loop",\n', ''),),
        'tests/playability/test_playability_lab_scope.py::test_failure_discovery_lab_runs_real_campaign_and_combat_chains_before_broad_release',
    ),
    Mutation(
        "response-courier-priority",
        "runtime/sword_runtime/campaign_report_projection.py",
        (("for bucket in (response, material, routine):", "for bucket in (material, routine, response):"),),
        "tests/playability/test_campaign_report_projection_fuzz.py",
    ),
    Mutation(
        "delivered-report-resurrection",
        "runtime/sword_runtime/campaign_report_projection.py",
        ((
            'return str(row.get("delivery_status", "")) != "delivered"',
            "return True",
        ),),
        "tests/playability/test_campaign_report_projection_fuzz.py",
    ),
    Mutation(
        "route-unresolved-fake-in-flight",
        "runtime/sword_runtime/api/command_discovery.py",
        ((
            'isinstance(row, Mapping) and str(row.get("delivery_status", "")) == "in_transit"\n            for row in pending_rows',
            'isinstance(row, Mapping) and str(row.get("delivery_status", "")) != "delivered"\n            for row in pending_rows',
        ),),
        "tests/playability/test_campaign_report_projection_fuzz.py::test_route_unresolved_is_pending_but_never_relabelled_as_physically_in_flight",
    ),
    Mutation(
        "release-revision-pin-bypass",
        "tools/verify_release_state.py",
        (("for key in expected:", 'for key in ("campaign_id", "player_id", "time"):'),),
        "tests/runtime/test_release_campaign_state_contract.py::test_release_contract_rejects_a_stale_or_advanced_campaign_snapshot",
    ),
    Mutation(
        "deployment-doc-start-command-drift",
        "docs/RUNTIME_SERVICE_DEPLOYMENT.md",
        ((
            "PYTHONPATH=/app/runtime python -m sword_runtime.branch_bootstrap",
            "PYTHONPATH=/app/runtime python -m sword_runtime.bootstrap",
        ),),
        "tests/playability/test_delivery_chain_contract.py::test_deployment_docs_cannot_drift_from_railway_start_command_again",
    ),
    Mutation(
        "release-checkpoint-deployment-doc-fingerprint-bypass",
        "tools/run_release_suite.py",
        ((
            '    "docs/RUNTIME_SERVICE_DEPLOYMENT.md",\n    "docs/RAILWAY_IAC_MIGRATION.md",\n',
            '',
        ),),
        "tests/playability/test_delivery_chain_contract.py::test_resumable_release_evidence_is_invalidated_by_deployment_runbook_changes",
    ),
    Mutation(
        "package-state-exclusion",
        "tools/package_release.py",
        ((
            "return rel.as_posix() not in TRANSIENT_EXACT_PATHS",
            'return rel.as_posix() not in TRANSIENT_EXACT_PATHS and rel.parts[0] != "state"',
        ),),
        "tests/playability/test_release_packaging_contract.py::test_packager_keeps_every_campaign_state_file_and_required_release_surface",
    ),
    Mutation(
        "source-release-baseline-digest-bypass",
        "runtime/sword_runtime/branch_bootstrap.py",
        ((
            "        if _release_baseline(settings, source_commit) is not None:\n            baseline_errors = verify_release_baseline_core(settings.campaign_root)",
            "        if _release_baseline(settings, source_commit) is not None:\n            baseline_errors = []",
        ),),
        "tests/runtime/test_branch_bootstrap.py::test_first_bootstrap_rejects_mismatched_release_baseline_digest_without_publishing_branch",
    ),
    Mutation(
        "replacement-release-baseline-digest-bypass",
        "runtime/sword_runtime/branch_bootstrap.py",
        ((
            "        baseline_errors = verify_release_baseline_core(settings.campaign_root)\n        if baseline_errors:\n            _run(settings, \"checkout\", \"-B\", current_branch, old_head)",
            "        baseline_errors = []\n        if baseline_errors:\n            _run(settings, \"checkout\", \"-B\", current_branch, old_head)",
        ),),
        "tests/runtime/test_branch_bootstrap.py::test_replacement_release_baseline_bad_digest_restores_old_live_branch_and_receipts",
    ),
    Mutation(
        "release-baseline-branch-isolation-bypass",
        "runtime/sword_runtime/branch_bootstrap.py",
        ((
            "branch_name = _baseline_campaign_branch(identity[0], baseline_id)",
            'branch_name = f"campaign/{identity[0]}"',
        ),),
        "tests/runtime/test_branch_bootstrap.py::test_new_release_baseline_seeds_new_durability_branch_instead_of_reusing_old_state",
    ),
    Mutation(
        "legacy-branch-migration-state-loss",
        "runtime/sword_runtime/branch_bootstrap.py",
        ((
            "        if current_branch == legacy_branch:",
            "        if False and current_branch == legacy_branch:",
        ),),
        "tests/runtime/test_branch_bootstrap.py::test_legacy_campaign_branch_naming_migration_preserves_same_baseline_live_state",
    ),
    Mutation(
        "release-baseline-recovery-store-reuse",
        "runtime/sword_runtime/branch_bootstrap.py",
        ((
            '            _retire_recovery_store(\n                settings,\n                retired_head=old_head,\n                new_baseline_id=new_baseline_id,\n            )',
            "            pass",
        ),),
        "tests/runtime/test_branch_bootstrap.py::test_new_release_baseline_seeds_new_durability_branch_instead_of_reusing_old_state",
    ),
    Mutation(
        "existing-release-baseline-branch-switch-bypass",
        "runtime/sword_runtime/branch_bootstrap.py",
        ((
            "        if release_lineage_change:",
            "        if False and release_lineage_change:",
        ),),
        "tests/runtime/test_branch_bootstrap.py::test_existing_replacement_baseline_branch_overrides_stale_volume_and_retires_receipts",
    ),
    Mutation(
        "split-branch-source-tracking-bypass",
        "runtime/sword_runtime/deployment_attestation.py",
        ((
            'source_branch = str(source.get("SWORD_SOURCE_BRANCH") or branch)',
            'source_branch = branch',
        ),),
        "tests/playability/test_delivery_chain_contract.py::test_split_campaign_branch_still_tracks_original_source_branch_for_stale_image_detection",
    ),
    Mutation(
        "production-source-attestation-bypass",
        "runtime/sword_runtime/deployment_attestation.py",
        ((
            'if attestation.get("source_compatible") is not True:\n        raise DeploymentCompatibilityError(str(attestation.get("source_sync_status") or "deployment_source_incompatible"))',
            'if False:\n        raise DeploymentCompatibilityError(str(attestation.get("source_sync_status") or "deployment_source_incompatible"))',
        ),),
        "tests/playability/test_delivery_chain_contract.py::test_production_deployment_guard_rejects_stale_runtime_image",
    ),
    Mutation(
        "app-startup-deployment-guard-bypass",
        "runtime/sword_runtime/api/app.py",
        ((
            "    assert_deployment_compatible(campaign_root)",
            "    public_deployment_health(campaign_root)",
        ),),
        "tests/playability/test_delivery_chain_contract.py::test_app_entrypoint_calls_deployment_guard_before_runtime_recovery",
    ),
    Mutation(
        "gm-skill-handshake-bypass",
        "runtime/sword_runtime/gm_skill_contract.py",
        (("and secrets.compare_digest(value, GM_SKILL_CONTRACT_TOKEN)", "and True"),),
        "tests/playability/test_delivery_chain_contract.py::test_get_play_context_fails_closed_for_missing_or_stale_skill_token",
    ),
    Mutation(
        "get-play-context-release-lineage-proof-omission",
        "runtime/sword_runtime/api/mcp.py",
        ((
            '        "release_baseline_id": baseline_id,\n',
            '',
        ),),
        "tests/playability/test_delivery_chain_contract.py::test_get_play_context_fails_closed_for_missing_or_stale_skill_token",
    ),
    Mutation(
        "get-play-context-deployment-guard-bypass",
        "runtime/sword_runtime/api/mcp.py",
        ((
            "deployment = assert_deployment_compatible(operations.runtime.root)",
            'deployment = {"source_sync_status": "bypassed"}',
        ),),
        "tests/playability/test_delivery_chain_contract.py::test_get_play_context_fails_closed_for_missing_or_stale_skill_token",
    ),
    Mutation(
        "changed-path-normal-module-timeout-fallback-bypass",
        "tools/test_changed.py",
        ((
            "if timed_out:\n                    print(\n                        f\"test_changed: normal module timeout; certifying every node: {test}\",",
            "if False:\n                    print(\n                        f\"test_changed: normal module timeout; certifying every node: {test}\",",
        ),),
        "tests/runtime/test_release_suite_harness_policy.py::test_changed_bounds_normal_modules_and_falls_back_to_node_certification",
    ),
    Mutation(
        "interaction-surface-node-isolation-bypass",
        "tools/test_changed.py",
        ((
            '    "tests/runtime/test_hosted_horizon_performance.py",\n    "tests/runtime/test_interaction_surface.py",\n    "tests/runtime/test_long_horizon.py",\n',
            '    "tests/runtime/test_hosted_horizon_performance.py",\n    "tests/runtime/test_long_horizon.py",\n',
        ),),
        "tests/runtime/test_release_suite_harness_policy.py::test_interaction_surface_uses_node_isolation_in_changed_path_gate",
    ),
    Mutation(
        "fifty-year-release-budget-collapse",
        "tools/run_release_suite.py",
        ((
            '    "tests/runtime/test_rules_parity_adversarial.py::test_fifty_year_world_produces_exact_human_and_interstate_history": 180,\n',
            '    "tests/runtime/test_rules_parity_adversarial.py::test_fifty_year_world_produces_exact_human_and_interstate_history": 90,\n',
        ),),
        "tests/runtime/test_release_suite_harness_policy.py::test_fifty_year_world_history_has_explicit_finite_release_budget",
    ),
    Mutation(
        "changed-path-cleanup-timeout-bypass",
        "tools/test_changed.py",
        ((
            "            timeout=15,\n",
            "",
        ),),
        "tests/runtime/test_release_suite_harness_policy.py::test_changed_bounds_disposable_cleanup_so_green_tests_cannot_hang_on_rm",
    ),
)


def _env(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "runtime")
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _run(root: Path, selector: str, *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", selector],
        cwd=root,
        env=_env(root),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )


def _copy_candidate(target: Path) -> None:
    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {
            name
            for name in names
            if name in {".git", ".pytest_cache", "__pycache__", "artifacts", ".release-certification.json"}
            or name.endswith(".pyc")
        }

    shutil.copytree(ROOT, target, ignore=ignore)


def _apply(root: Path, mutation: Mutation) -> None:
    path = root / mutation.relpath
    text = path.read_text(encoding="utf-8")
    for old, new in mutation.replacements:
        count = text.count(old)
        if count != 1:
            raise RuntimeError(
                f"{mutation.name}: expected one replacement target in {mutation.relpath}, found {count}"
            )
        text = text.replace(old, new, 1)
    if path.suffix == ".py":
        compile(text, str(path), "exec")
    path.write_text(text, encoding="utf-8")


def _exercise_mutation(mutation: Mutation) -> tuple[str, str]:
    with tempfile.TemporaryDirectory(prefix=f"sword-mut-{mutation.name}-") as tmp:
        candidate = Path(tmp) / "repo"
        _copy_candidate(candidate)
        _apply(candidate, mutation)
        result = _run(candidate, mutation.selector)
    output = result.stdout
    if result.returncode == 0:
        return "survived", output
    if "ERROR collecting" in output or "ImportError" in output:
        return "invalid_test_failure", output
    if re.search(r"\b[1-9][0-9]* failed\b", output.lower()) is None:
        return "invalid_non_assertion_failure", output
    return "killed", output


def run(selected: tuple[Mutation, ...]) -> int:
    unique_selectors = tuple(dict.fromkeys(mutation.selector for mutation in selected))
    requested_baseline_workers = int(os.environ.get("SWORD_MUTATION_BASELINE_WORKERS", "6"))
    baseline_workers = max(1, min(requested_baseline_workers, len(unique_selectors)))
    with ThreadPoolExecutor(max_workers=baseline_workers) as pool:
        futures = {selector: pool.submit(_run, ROOT, selector) for selector in unique_selectors}
        baseline_cache = {selector: futures[selector].result() for selector in unique_selectors}
    for selector in unique_selectors:
        result = baseline_cache[selector]
        if result.returncode != 0:
            print(f"MUTATION AUDIT BASELINE FAIL: {selector}")
            print(result.stdout[-8000:])
            return 1

    requested_workers = int(os.environ.get("SWORD_MUTATION_WORKERS", "6"))
    workers = max(1, min(requested_workers, len(selected)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {mutation: pool.submit(_exercise_mutation, mutation) for mutation in selected}
        results = {mutation: futures[mutation].result() for mutation in selected}

    killed = 0
    for mutation in selected:
        status, output = results[mutation]
        if status == "killed":
            killed += 1
            print(f"MUTATION KILLED: {mutation.name}")
            continue
        if status == "survived":
            label = "MUTATION SURVIVED"
        elif status == "invalid_test_failure":
            label = "MUTATION INVALID TEST FAILURE"
        else:
            label = "MUTATION INVALID NON-ASSERTION FAILURE"
        print(f"{label}: {mutation.name}")
        print(output[-8000:])
        return 1
    print(f"MUTATION AUDIT PASS: killed={killed}/{len(selected)} workers={workers}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mutation", action="append", default=[])
    args = parser.parse_args()
    if args.mutation:
        wanted = set(args.mutation)
        selected = tuple(m for m in MUTATIONS if m.name in wanted)
        missing = wanted - {m.name for m in selected}
        if missing:
            print("unknown mutation(s): " + ", ".join(sorted(missing)))
            return 2
    else:
        selected = MUTATIONS
    return run(selected)


if __name__ == "__main__":
    raise SystemExit(main())
