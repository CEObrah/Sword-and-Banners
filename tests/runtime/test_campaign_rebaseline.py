from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]


def load(rel):
    return json.loads((ROOT / rel).read_text())


def test_revision_one_rebaseline_is_preserved_as_historical_migration_record():
    """The September 2 rebaseline is provenance, not a perpetual live-state shape."""
    meta = load("state/meta.json")
    manifest = load("docs/CAMPAIGN_REBASELINE_20260902.json")

    assert manifest["old_revision"] == 51
    assert manifest["new_revision"] == 1
    assert manifest["fresh_private_recovery_store_required"] is True
    assert (ROOT / manifest["archived_state"]).is_file()

    # The maintained campaign snapshot is allowed to advance after rebaseline.
    assert int(meta["revision"]) >= int(manifest["new_revision"])
    assert not (ROOT / ".sword-runtime").exists()


def test_current_deployment_uses_split_source_and_campaign_durability_bootstrap():
    """Current source deploys must not collapse live campaign durability into main."""
    railway = (ROOT / "railway.toml").read_text(encoding="utf-8")

    assert "python -m sword_runtime.branch_bootstrap" in railway
    assert "SWORD_GIT_BRANCH=main" not in railway
    assert (ROOT / "runtime/sword_runtime/branch_bootstrap.py").is_file()
    # Source deployment ignores mutable campaign state; branch_bootstrap owns the
    # dedicated campaign durability checkout/reconciliation at service startup.
    assert '"!/state/**"' in railway
