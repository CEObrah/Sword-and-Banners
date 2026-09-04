from pathlib import Path
import runpy


def test_365_day_hosted_horizon_has_explicit_finite_release_budget():
    root = Path(__file__).resolve().parents[2]
    policy = runpy.run_path(str(root / "tools/run_release_suite.py"))
    node = "tests/runtime/test_hosted_horizon_performance.py::test_production_hosted_horizon_is_bounded_atomic_windows[365]"
    assert policy["SERIAL_NODE_TIMEOUTS"][node] == 600
    assert node.startswith("tests/runtime/test_hosted_horizon_performance.py::")
