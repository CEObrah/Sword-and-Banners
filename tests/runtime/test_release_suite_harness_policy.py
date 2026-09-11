from pathlib import Path
import runpy


def test_365_day_hosted_horizon_has_explicit_finite_release_budget():
    root = Path(__file__).resolve().parents[2]
    policy = runpy.run_path(str(root / "tools/run_release_suite.py"))
    node = "tests/runtime/test_hosted_horizon_performance.py::test_production_hosted_horizon_is_bounded_atomic_windows[365]"
    assert policy["SERIAL_NODE_TIMEOUTS"][node] == 600
    assert node.startswith("tests/runtime/test_hosted_horizon_performance.py::")


def test_90_day_hosted_horizon_has_explicit_finite_release_budget():
    root = Path(__file__).resolve().parents[2]
    policy = runpy.run_path(str(root / "tools/run_release_suite.py"))
    node = "tests/runtime/test_hosted_horizon_performance.py::test_production_hosted_horizon_is_bounded_atomic_windows[90]"
    assert policy["SERIAL_NODE_TIMEOUTS"][node] == 180
    assert node.startswith("tests/runtime/test_hosted_horizon_performance.py::")


def test_120_day_deterministic_replay_has_explicit_finite_release_budget():
    root = Path(__file__).resolve().parents[2]
    policy = runpy.run_path(str(root / "tools/run_release_suite.py"))
    node = "tests/runtime/test_living_world_intelligence.py::test_current_campaign_120_day_replay_is_stable_for_same_saved_seed"
    assert policy["SERIAL_NODE_TIMEOUTS"][node] == 360
    assert node.startswith("tests/runtime/test_living_world_intelligence.py::")


def test_long_horizon_uses_serial_node_certification_with_finite_budgets():
    root = Path(__file__).resolve().parents[2]
    policy = runpy.run_path(str(root / "tools/run_release_suite.py"))
    module = "tests/runtime/test_long_horizon.py"
    assert module in policy["NODE_ONLY_MODULES"]
    assert module in policy["SERIAL_NODE_MODULES"]
    assert module not in policy["SERIAL_MODULES"]
    expected = {
        f"{module}::test_horizons_are_bounded_and_alive",
        f"{module}::test_20_year_world_changes_without_global_scans",
        f"{module}::test_named_person_identity_survives_5_and_20_years",
    }
    assert all(policy["SERIAL_NODE_TIMEOUTS"][node] == 180 for node in expected)



def test_fifty_year_world_history_has_explicit_finite_release_budget():
    root = Path(__file__).resolve().parents[2]
    release = runpy.run_path(str(root / "tools/run_release_suite.py"))
    changed = runpy.run_path(str(root / "tools/test_changed.py"))
    node = "tests/runtime/test_rules_parity_adversarial.py::test_fifty_year_world_produces_exact_human_and_interstate_history"
    assert release["SERIAL_NODE_TIMEOUTS"][node] == 180
    assert changed["SERIAL_NODE_TIMEOUTS"][node] == 180
    assert "tests/runtime/test_rules_parity_adversarial.py" in release["NODE_ONLY_MODULES"]
    assert "tests/runtime/test_rules_parity_adversarial.py" in changed["NODE_ONLY_MODULES"]

def test_changed_runs_selected_modules_in_disposable_isolated_basetemps():
    root = Path(__file__).resolve().parents[2]
    policy = runpy.run_path(str(root / "tools/test_changed.py"))
    assert policy["TEST_CHANGED_TMP_BASE"].parent == Path("/tmp/sword-test-changed")
    assert policy["TEST_CHANGED_TMP_BASE"].name == policy["TEST_CHANGED_NAMESPACE"]
    assert policy["TEST_CHANGED_RUN_BASE"].parent == Path("/tmp/sword-test-changed-runs")
    assert policy["TEST_CHANGED_RUN_BASE"].name == policy["TEST_CHANGED_NAMESPACE"]
    assert policy["TEST_CHANGED_RUN_BASE"] != policy["TEST_CHANGED_TMP_BASE"]

    source = (root / "tools/test_changed.py").read_text(encoding="utf-8")
    assert 'for index, test in enumerate(tests, start=1)' in source
    assert 'f"--basetemp={basetemp}"' in source
    assert '_clean_path(basetemp, cwd=cwd)' in source
    assert '[sys.executable, "tools/run_pytest_module.py", "-q", *tests]' not in source


def test_changed_checkpoints_completed_modules_with_content_keyed_resume():
    root = Path(__file__).resolve().parents[2]
    policy = runpy.run_path(str(root / "tools/test_changed.py"))
    assert policy["TEST_CHANGED_CHECKPOINT_DIR"] == policy["TEST_CHANGED_TMP_BASE"] / "checkpoints"

    source = (root / "tools/test_changed.py").read_text(encoding="utf-8")
    assert "def _checkpoint_key(changed_paths: list[str], tests: list[str])" in source
    assert "_fingerprint_path(digest, rel)" in source
    assert "passed.add(test)" in source
    assert "_save_checkpoint(checkpoint_path, passed, passed_nodes)" in source
    assert "(checkpointed)" in source
    assert "checkpoint_path.unlink(missing_ok=True)" in source
    assert "TEST_CHANGED_NAMESPACE = hashlib.sha256(str(ROOT.resolve())" in source
    assert "fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)" in source


def test_release_harness_checkpoints_parallel_successes_before_batch_teardown():
    root = Path(__file__).resolve().parents[2]
    source = (root / "tools/run_release_suite.py").read_text(encoding="utf-8")
    module_batch = source[source.index("    def flush_normal_batch() -> None:"):source.index("    for index, path in enumerate(modules, start=1):")]
    assert "for future in as_completed(futures):" in module_batch
    assert "if code == 0:" in module_batch
    assert "mark_passed(module)" in module_batch
    assert "host/tool timeout between parallel siblings" in module_batch

    node_batch = source[source.index("    for offset in range(0, len(parallel), NODE_PARALLELISM):"):source.index("    if not set(nodes).issubset(already):")]
    assert "already.add(node)" in node_batch
    assert "_save_checkpoint(checkpoint)" in node_batch
    assert "external executor" in node_batch


def test_changed_qin_campaign_handoff_gate_covers_physical_arrival_and_starvation():
    root = Path(__file__).resolve().parents[2]
    policy = runpy.run_path(str(root / "tools/test_changed.py"))
    expected = {
        "tests/runtime/test_qin_command_support_flow.py",
        "tests/runtime/test_qin_command_support_mid_advance.py",
        "tests/runtime/test_qin_campaign_command_starvation_regression.py",
        "tests/runtime/test_campaign_command_to_arrival_e2e.py",
        "tests/runtime/test_command_staff_continuity.py",
        "tests/runtime/test_vitality_qin_briefing.py",
    }
    assert expected.issubset(policy["QIN_CAMPAIGN_HANDOFF_TESTS"])

    source = (root / "tools/test_changed.py").read_text(encoding="utf-8")
    assert '"tests/runtime/test_campaign_movement_intent_skill_handoff.py"' in source


def test_changed_vitality_gate_includes_qin_delivery_diagnostics_without_full_world_replay():
    root = Path(__file__).resolve().parents[2]
    policy = runpy.run_path(str(root / "tools/test_changed.py"))
    selected = set(policy["select"](["runtime/sword_runtime/vitality.py"]))
    assert policy["VITALITY_TESTS"].issubset(selected)
    assert {
        "tests/runtime/test_vitality_campaign_order_delivery.py",
        "tests/runtime/test_vitality_qin_briefing.py",
        "tests/runtime/test_vitality_qin_pending_response.py",
        "tests/runtime/test_vitality_report_eligibility.py",
        "tests/runtime/test_campaign_event_liveness.py",
        "tests/runtime/test_player_story_flow.py",
    }.issubset(selected)
    assert "tests/runtime/test_living_world_intelligence.py" not in selected
    assert "tests/runtime/test_world_arcs.py" not in selected


def test_changed_personal_combat_gate_covers_crossgame_fairness_and_doctrine_owners():
    root = Path(__file__).resolve().parents[2]
    policy = runpy.run_path(str(root / "tools/test_changed.py"))
    expected = {
        "tests/runtime/test_personal_combat_crossgame_fairness.py",
        "tests/runtime/test_mass_battle_crossgame_fairness.py",
        "tests/runtime/test_battlefield_scale_model.py",
        "tests/runtime/test_wei_combat_doctrine.py",
        "tests/runtime/test_personal_combat_multi_actor.py",
        "tests/runtime/test_personal_combat_physical_rework.py",
        "tests/runtime/test_personal_combat_balance_lab.py",
    }
    for changed in (
        "runtime/sword_runtime/personal_combat.py",
        "runtime/sword_runtime/combat_tactics.py",
        "runtime/sword_runtime/combat_commitment.py",
        "runtime/sword_runtime/combat_geometry.py",
        "runtime/sword_runtime/combat_doctrine.py",
        "game/rules/combat.md",
        "game/data/mil/doctrine-records/doc.tang_wei.personal_combat.json",
    ):
        selected = set(policy["select"]([changed]))
        assert expected.issubset(selected), (changed, expected - selected)

def test_changed_shards_heavy_multi_actor_combat_with_node_level_resume():
    root = Path(__file__).resolve().parents[2]
    policy = runpy.run_path(str(root / "tools/test_changed.py"))
    modules = {
        "tests/runtime/test_personal_combat_multi_actor.py",
        "tests/runtime/test_personal_combat_physical_rework.py",
    }
    assert modules.issubset(policy["NODE_ONLY_MODULES"])
    assert policy["NODE_TIMEOUT_SECONDS"] == 90

    source = (root / "tools/test_changed.py").read_text(encoding="utf-8")
    assert "def _collect_nodes(module: str, *, cwd: Path)" in source
    assert "passed_nodes" in source
    assert "already.add(node)" in source
    assert "node certification incomplete" in source
    assert "def _run_bounded(" in source
    assert "start_new_session=True" in source
    assert "os.killpg(proc.pid, signal.SIGKILL)" in source

def test_isolated_pytest_runner_keeps_repository_root_importable():
    root = Path(__file__).resolve().parents[2]
    source = (root / "tools/run_pytest_module.py").read_text(encoding="utf-8")
    assert "ROOT = Path(__file__).resolve().parents[1]" in source
    assert "sys.path.insert(0, str(ROOT))" in source



def test_staff_continuity_uses_native_temp_isolation_in_both_release_gates():
    root = Path(__file__).resolve().parents[2]
    changed = runpy.run_path(str(root / "tools/test_changed.py"))
    release = runpy.run_path(str(root / "tools/run_release_suite.py"))
    module = "tests/runtime/test_command_staff_continuity.py"
    assert module in changed["NATIVE_TEMP_MODULES"]
    assert module in release["NATIVE_TEMP_MODULES"]
    assert module not in changed["NODE_ONLY_MODULES"]
    assert module not in release["NODE_ONLY_MODULES"]

def test_changed_routes_pytest_runner_and_gate_self_changes_to_release_harness_regressions():
    root = Path(__file__).resolve().parents[2]
    policy = runpy.run_path(str(root / "tools/test_changed.py"))
    expected = policy["RELEASE_HARNESS_TESTS"]
    assert expected.issubset(set(policy["select"](["tools/run_pytest_module.py"])))
    assert expected.issubset(set(policy["select"](["tools/test_changed.py"])))


def test_release_harness_certifies_playability_tests_and_mutation_audit():
    root = Path(__file__).resolve().parents[2]
    source = (root / "tools/run_release_suite.py").read_text(encoding="utf-8")
    assert '"tests/playability"' in source
    assert 'ROOT / "tests/playability"' in source
    assert "_run_skill_contract_guard()" in source
    assert "_run_playability_lab()" in source
    assert "_run_mutation_audit()" in source
    assert source.index("_run_playability_lab()", source.index("def main()")) < source.index(
        "_run_mutation_audit()", source.index("def main()")
    )
    assert '"tools/playability_lab.py", "--no-mutations"' in source

    policy = runpy.run_path(str(root / "tools/test_changed.py"))
    assert policy["PLAYABILITY_DELIVERY_TESTS"].issubset(
        set(policy["select"](["runtime/sword_runtime/api/mcp.py"]))
    )
    assert policy["PLAYABILITY_HANDOFF_TESTS"].issubset(
        set(policy["select"](["runtime/sword_runtime/campaign_report_projection.py"]))
    )



def test_changed_bounds_normal_modules_and_falls_back_to_node_certification():
    root = Path(__file__).resolve().parents[2]
    policy = runpy.run_path(str(root / "tools/test_changed.py"))
    assert policy["NODE_TIMEOUT_SECONDS"] == 90
    source = (root / "tools/test_changed.py").read_text(encoding="utf-8")
    assert "def _run_bounded(" in source
    assert "start_new_session=True" in source
    assert "os.killpg(proc.pid, signal.SIGKILL)" in source
    assert "tempfile.NamedTemporaryFile" in source
    normal_start = source.index('            basetemp = run_root / f"{index:03d}-{token}"')
    normal_end = source.index("    finally:\n        _clean_path(run_root, cwd=cwd)", normal_start)
    normal_block = source[normal_start:normal_end]
    assert 'if timed_out:\n                    print(\n                        f"test_changed: normal module timeout; certifying every node: {test}",' in normal_block
    assert "native-temp module timeout; certifying every node" in source
    assert "def _certify_module_nodes(" in source


def test_interaction_surface_uses_node_isolation_in_changed_path_gate():
    root = Path(__file__).resolve().parents[2]
    changed = runpy.run_path(str(root / "tools/test_changed.py"))
    assert "tests/runtime/test_interaction_surface.py" in changed["NODE_ONLY_MODULES"]
    assert "tests/runtime/test_interaction_surface.py" not in changed["NATIVE_TEMP_MODULES"]


def test_every_mutation_target_is_unambiguous_before_execution():
    root = Path(__file__).resolve().parents[2]
    audit = runpy.run_path(str(root / "tools/mutation_audit.py"))
    for mutation in audit["MUTATIONS"]:
        source = (root / mutation.relpath).read_text(encoding="utf-8")
        for old, _new in mutation.replacements:
            assert source.count(old) == 1, f"ambiguous mutation target: {mutation.name} in {mutation.relpath}"


def test_changed_bounds_disposable_cleanup_so_green_tests_cannot_hang_on_rm():
    root = Path(__file__).resolve().parents[2]
    source = (root / "tools/test_changed.py").read_text(encoding="utf-8")
    start = source.index("def _clean_path(path: Path, *, cwd: Path) -> None:")
    end = source.index("\n\ndef _fingerprint_path", start)
    cleanup = source[start:end]
    assert "timeout=15" in cleanup
    assert "stdout=subprocess.DEVNULL" in cleanup
    assert "except subprocess.TimeoutExpired" in cleanup
    assert "cleanup timeout ignored for disposable path" in cleanup
