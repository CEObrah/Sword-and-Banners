import shutil

import pytest

from sword_runtime.release_identity import SOURCE_ROOT, release_fingerprints
from sword_runtime.deployment_attestation import deployment_attestation, assert_deployment_compatible, DeploymentCompatibilityError
from sword_runtime.api import mcp_security
from sword_runtime.commands import CommandEnvelope
from types import SimpleNamespace


def test_dependency_identity_reports_installed_pin_drift(tmp_path, monkeypatch):
    from sword_runtime import release_identity
    (tmp_path / 'requirements.txt').write_text('mcp==2.0.0\n')
    monkeypatch.setattr(release_identity.importlib.metadata, 'version', lambda name: '2.2.0')
    result = release_identity.runtime_dependencies(tmp_path)
    assert result['installed'] == {'mcp': '2.2.0'}
    assert result['mismatches'] == ['mcp']


def test_release_contract_changes_for_runtime_contract_schema_and_skill(tmp_path):
    for directory in ('runtime', 'game', 'plugins'):
        shutil.copytree(SOURCE_ROOT / directory, tmp_path / directory, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for filename in ('requirements.txt', 'pyproject.toml', 'railway.toml'):
        shutil.copyfile(SOURCE_ROOT / filename, tmp_path / filename)
    previous = release_fingerprints(tmp_path)
    for filename, identity in (
        ('runtime/sword_runtime/engine.py', 'runtime_source_sha256'),
        ('runtime/sword_runtime/api/mcp.py', 'mcp_contract_sha256'),
        ('game/schemas/registry.json', 'state_schema_sha256'),
        ('plugins/sword-and-banners/skill/sword-and-banners-game-master/SKILL.md', 'gm_skill_sha256'),
        ('runtime/contracts/release-campaign-state.json', 'release_lineage_sha256'),
    ):
        path = tmp_path / filename
        path.write_bytes(path.read_bytes() + b'\n')
        current = release_fingerprints(tmp_path)
        assert current[identity] != previous[identity]
        assert current['release_contract_sha256'] != previous['release_contract_sha256']
        previous = current


@pytest.mark.parametrize('environment', [
    {'RAILWAY_PROJECT_ID': 'production'}, {'RAILWAY_GIT_COMMIT_SHA': 'invalid'},
])
def test_missing_production_image_identity_fails_closed(tmp_path, environment):
    assert deployment_attestation(tmp_path, environment)['source_compatible'] is False
    with pytest.raises(DeploymentCompatibilityError, match='image_source_unverifiable'):
        assert_deployment_compatible(tmp_path, environment)


def test_preview_attestation_cannot_cross_release(monkeypatch):
    command = CommandEnvelope('campaign', 'request', 'player', 'scene_consequence', 1, 'now', {'summary': 'x'})
    settings = SimpleNamespace(preview_secret='a' * 48)
    token = mcp_security._preview_attestation(command, settings, now=1000)
    assert mcp_security._verify_preview_attestation(command, token, settings, now=1000)
    monkeypatch.setattr(mcp_security, 'GM_SKILL_CONTRACT_TOKEN', '0' * 64)
    assert not mcp_security._verify_preview_attestation(command, token, settings, now=1000)
