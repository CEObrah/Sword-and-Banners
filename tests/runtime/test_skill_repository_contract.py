from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / 'plugins/sword-and-banners/skill/sword-and-banners-game-master'


def test_sword_skill_is_self_contained():
    texts = '\n'.join(
        path.read_text(encoding='utf-8', errors='ignore')
        for path in SKILL.rglob('*.md')
    ).lower()
    assert 'shinobi' not in texts


def test_skill_runtime_paths_and_default_verification_exist():
    ooc = (SKILL / 'references/ooc-dev.md').read_text(encoding='utf-8')
    repo_map = (SKILL / 'references/repository-map.md').read_text(encoding='utf-8')
    architecture = (SKILL / 'references/runtime-architecture.md').read_text(encoding='utf-8')
    interface = (SKILL / 'references/player-interface.md').read_text(encoding='utf-8')

    for path in (
        'runtime/sword_runtime/api/interaction_surface.py',
        'runtime/sword_runtime/api/mcp_extensions.py',
        'runtime/sword_runtime/api/stable_operations.py',
        'state/index/owner-index.json',
        'state/index/location-formation-index.json',
        'state/index/commander-formation-index.json',
        'state/information/index.json',
        'tools/quick_check.py',
        'tools/test_changed.py',
    ):
        assert (ROOT / path).exists(), path
        assert path in repo_map or path in ooc

    assert 'python tools/quick_check.py' in ooc
    assert 'python tools/test_changed.py <changed paths>' in ooc
    assert 'interaction_action' in architecture and 'interaction_action' in interface
    assert 'scene_consequence' in architecture and 'scene_consequence' in interface


def test_player_facing_alias_policy_does_not_require_retired_house_guard_identity():
    interface = (SKILL / 'references/player-interface.md').read_text(encoding='utf-8')
    github_dev = (SKILL / 'references/github-development.md').read_text(encoding='utf-8')

    assert 'formation_tang_wei_house_guard' not in interface
    assert 'presentation aliases' in interface.lower()
    assert 'do not edit a formation, person, house, place, or other mutable owner merely to change how the gm labels it in prose' in interface.lower()
    assert 'never edit `state/` on the live/default branch merely to change prose' in github_dev.lower()


def test_royal_council_sovereign_participation_is_explicit():
    playbook = (SKILL / 'references/scene-playbook.md').read_text(encoding='utf-8').lower()

    assert 'sovereign participation at royal councils' in playbook
    assert 'do not leave the sovereign as passive scenery' in playbook
    assert 'military expertise does not displace institutional authority' in playbook
    assert 'do not fabricate binding authority in dialogue' in playbook


def test_railway_watch_policy_matches_runtime_neutral_boundary():
    railway = (ROOT / 'railway.toml').read_text(encoding='utf-8')
    for pattern in (
        '!/state/**',
        '!/plugins/**',
        '!/docs/**',
        '!/tests/**',
        '!/tools/**',
        '!/.github/**',
        '!/README.md',
    ):
        assert f'"{pattern}"' in railway


def test_retired_skill_directory_and_references_are_absent():
    retired = "sword-and-banners-" + "skill"
    retired_path = ROOT / "plugins" / "sword-and-banners" / retired
    assert not retired_path.exists()

    text_suffixes = {".py", ".json", ".md", ".toml", ".yml", ".yaml", ".txt"}
    stale = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.is_symlink() or ".git" in path.parts:
            continue
        if path.is_relative_to(ROOT / "state"):
            continue
        if path.suffix not in text_suffixes and path.name not in {"Dockerfile"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if retired in text:
            stale.append(path.relative_to(ROOT).as_posix())
    assert stale == []
