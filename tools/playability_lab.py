#!/usr/bin/env python3
"""Run failure-discovery gameplay tests before broad Sword certification."""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HIGH_VALUE_SELECTORS = (
    "tests/runtime/test_campaign_command_to_arrival_e2e.py::test_actionable_campaign_order_reaches_operational_area_without_command_loop",
    "tests/runtime/test_qin_campaign_command_starvation_regression.py::test_pending_directive_promotes_and_physically_reaches_war_without_command_loop",
    "tests/runtime/test_qin_command_support_flow.py::test_campaign_follow_on_request_is_not_double_routed_as_qin_bureau_briefing",
    "tests/runtime/test_semantic_wait_policy.py::test_semantic_wait_any_of_supports_distinct_natural_language_stop_reasons",
    "tests/runtime/test_semantic_wait_provenance.py::test_semantic_wait_stops_when_causal_owner_report_is_delivered",
    "tests/runtime/test_scene_liveness_projection.py::test_active_session_participants_rehydrate_into_writer_cast_after_scene_projection_churn",
    "tests/runtime/test_personal_combat_crossgame_fairness.py::test_linear_melee_body_blocking_is_side_neutral",
    "tests/runtime/test_branch_bootstrap.py::test_new_release_baseline_seeds_new_durability_branch_instead_of_reusing_old_state",
    "tests/runtime/test_branch_bootstrap.py::test_first_bootstrap_rejects_mismatched_release_baseline_digest_without_publishing_branch",
    "tests/runtime/test_branch_bootstrap.py::test_replacement_release_baseline_bad_digest_restores_old_live_branch_and_receipts",
    "tests/runtime/test_branch_bootstrap.py::test_legacy_campaign_branch_naming_migration_preserves_same_baseline_live_state",
    "tests/runtime/test_branch_bootstrap.py::test_existing_replacement_baseline_branch_overrides_stale_volume_and_retires_receipts",
)


def _run_pytest(env: dict[str, str], targets: list[str], *, timeout: int = 240) -> int:
    proc = subprocess.Popen(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *targets],
        cwd=ROOT,
        env=env,
        start_new_session=True,
    )
    try:
        return int(proc.wait(timeout=timeout))
    except subprocess.TimeoutExpired:
        print(f"PLAYABILITY LAB TIMEOUT: {' '.join(targets)}", flush=True)
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
        return 124


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-mutations", action="store_true")
    parser.add_argument("--no-integration", action="store_true")
    args = parser.parse_args()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "runtime")
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    code = _run_pytest(env, ["tests/playability"])
    if code:
        return code
    if not args.no_integration:
        for selector in HIGH_VALUE_SELECTORS:
            print(f"PLAYABILITY SCENARIO: {selector}", flush=True)
            code = _run_pytest(env, [selector], timeout=120)
            if code:
                return code
    if not args.no_mutations:
        second = subprocess.run([sys.executable, "tools/mutation_audit.py"], cwd=ROOT, env=env, check=False)
        if second.returncode:
            return int(second.returncode)
    print("PLAYABILITY LAB PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
