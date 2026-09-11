from __future__ import annotations

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_packager_keeps_every_campaign_state_file_and_required_release_surface():
    policy = runpy.run_path(str(ROOT / "tools/package_release.py"))
    manifest = policy["package_file_map"](ROOT)
    state_files = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "state").rglob("*")
        if path.is_file()
    }
    packaged_state = {rel for rel in manifest if rel.startswith("state/")}
    assert packaged_state == state_files
    assert set(policy["REQUIRED_PATHS"]).issubset(manifest)


def test_packager_excludes_only_known_transient_release_evidence_and_caches():
    policy = runpy.run_path(str(ROOT / "tools/package_release.py"))
    manifest = policy["package_file_map"](ROOT)
    assert ".release-certification.json" not in manifest
    assert ".release-pytest-shards.json" not in manifest
    assert not any("/__pycache__/" in f"/{rel}/" for rel in manifest)
    assert not any(rel.endswith((".pyc", ".pyo")) for rel in manifest)
    assert not any(rel.startswith("artifacts/") for rel in manifest)


def test_changed_path_router_runs_packaging_contract_for_packager_edits():
    changed = runpy.run_path(str(ROOT / "tools/test_changed.py"))
    selected = set(changed["select"](["tools/package_release.py"]))
    assert "tests/playability/test_release_packaging_contract.py" in selected
