"""Content identities shared by the built runtime, Skill handshake and ZIP."""
from __future__ import annotations

import hashlib
import json
import re
import importlib.metadata
import platform
from pathlib import Path

SKILL_PATH = "plugins/sword-and-banners/skill/sword-and-banners-game-master"
SOURCE_ROOT = Path(__file__).resolve().parents[2]
_TOKEN = re.compile(rb'(?m)^GM_SKILL_CONTRACT_TOKEN(?:: | = ")[0-9a-f]{64}"?$')


def _tree_hash(root: Path, paths) -> str:
    digest = hashlib.sha256()
    for path in sorted(set(paths), key=lambda p: p.relative_to(root).as_posix()):
        if path.name == '.DS_Store' or '__pycache__' in path.parts:
            continue
        data = path.read_bytes()
        if path.relative_to(root).as_posix() in {
            SKILL_PATH + '/SKILL.md', 'runtime/sword_runtime/gm_skill_contract.py',
        }:
            data = _TOKEN.sub(b'GM_SKILL_CONTRACT_TOKEN=<normalized>', data)
        digest.update(path.relative_to(root).as_posix().encode() + b'\0' + data + b'\0')
    return digest.hexdigest()


def release_fingerprints(root: object = SOURCE_ROOT) -> dict[str, str]:
    root = Path(root).resolve()
    groups = {
        'runtime_source_sha256': list((root / 'runtime/sword_runtime').rglob('*.py')),
        'mcp_contract_sha256': [
            *(root / 'runtime/sword_runtime/api').glob('*.py'),
            *(root / 'runtime/sword_runtime/commands').glob('*.py'),
            root / 'runtime/sword_runtime/command_contracts.py',
        ],
        'state_schema_sha256': list((root / 'game/schemas').glob('*.json')),
        'release_lineage_sha256': list((root / 'runtime/contracts').glob('*.json')),
        'game_content_sha256': [p for p in (root / 'game').rglob('*') if p.is_file() and 'schemas' not in p.relative_to(root / 'game').parts],
        'gm_skill_sha256': [p for p in (root / SKILL_PATH).rglob('*') if p.is_file()],
        'dependencies_sha256': [root / 'requirements.txt', root / 'pyproject.toml', root / 'railway.toml'],
    }
    if any(not paths for paths in groups.values()):
        raise ValueError('release identity requires the complete runtime/game/Skill tree')
    result = {key: _tree_hash(root, paths) for key, paths in groups.items()}
    result['release_contract_sha256'] = hashlib.sha256(
        json.dumps(result, sort_keys=True, separators=(',', ':')).encode()
    ).hexdigest()
    return result


def runtime_dependencies(root: object = SOURCE_ROOT) -> dict:
    installed, mismatches = {}, []
    for line in (Path(root) / 'requirements.txt').read_text().splitlines():
        match = re.fullmatch(r'([A-Za-z0-9_.-]+)(?:\[[^]]+\])?==([^\s]+)', line.strip())
        if match is None:
            if line.strip() and not line.lstrip().startswith('#'):
                raise ValueError('release dependency declaration is not exactly pinned')
            continue
        name, required = match.groups()
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            actual = None
        installed[name] = actual
        if actual != required:
            mismatches.append(name)
    return {'python': platform.python_version(), 'installed': installed, 'mismatches': mismatches}
