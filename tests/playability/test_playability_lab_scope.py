from __future__ import annotations

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_failure_discovery_lab_runs_real_campaign_and_combat_chains_before_broad_release():
    lab = runpy.run_path(str(ROOT / "tools/playability_lab.py"))
    selectors = set(lab["HIGH_VALUE_SELECTORS"])
    assert {
        "tests/runtime/test_campaign_command_to_arrival_e2e.py::test_actionable_campaign_order_reaches_operational_area_without_command_loop",
        "tests/runtime/test_qin_campaign_command_starvation_regression.py::test_pending_directive_promotes_and_physically_reaches_war_without_command_loop",
        "tests/runtime/test_semantic_wait_policy.py::test_semantic_wait_any_of_supports_distinct_natural_language_stop_reasons",
        "tests/runtime/test_scene_liveness_projection.py::test_active_session_participants_rehydrate_into_writer_cast_after_scene_projection_churn",
        "tests/runtime/test_personal_combat_crossgame_fairness.py::test_linear_melee_body_blocking_is_side_neutral",
        "tests/runtime/test_branch_bootstrap.py::test_new_release_baseline_seeds_new_durability_branch_instead_of_reusing_old_state",
        "tests/runtime/test_branch_bootstrap.py::test_first_bootstrap_rejects_mismatched_release_baseline_digest_without_publishing_branch",
        "tests/runtime/test_branch_bootstrap.py::test_replacement_release_baseline_bad_digest_restores_old_live_branch_and_receipts",
        "tests/runtime/test_branch_bootstrap.py::test_legacy_campaign_branch_naming_migration_preserves_same_baseline_live_state",
        "tests/runtime/test_branch_bootstrap.py::test_existing_replacement_baseline_branch_overrides_stale_volume_and_retires_receipts",
    }.issubset(selectors)


def test_playability_lab_does_not_run_duplicate_high_value_scenarios():
    lab = runpy.run_path(str(ROOT / "tools/playability_lab.py"))
    selectors = tuple(lab["HIGH_VALUE_SELECTORS"])
    assert len(selectors) == len(set(selectors))


def test_playability_lab_has_hard_timeouts_and_disables_plugin_noise():
    source = (ROOT / "tools/playability_lab.py").read_text(encoding="utf-8")
    assert "except subprocess.TimeoutExpired" in source
    assert "start_new_session=True" in source
    assert "os.killpg(proc.pid, signal.SIGKILL)" in source
    assert "for selector in HIGH_VALUE_SELECTORS:" in source
    assert 'env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"' in source
    assert 'env["PYTHONDONTWRITEBYTECODE"] = "1"' in source
    assert '[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *targets]' in source
    assert "pytest_exit_runner.py" not in source
    assert not (ROOT / "tools/pytest_exit_runner.py").exists()


def test_changed_path_router_runs_lab_scope_contract_for_lab_edits():
    changed = runpy.run_path(str(ROOT / "tools/test_changed.py"))
    selected = set(changed["select"](["tools/playability_lab.py"]))
    assert "tests/playability/test_playability_lab_scope.py" in selected
