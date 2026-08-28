from __future__ import annotations

import json
from pathlib import Path

import pytest

from sword_runtime.startup_integrity import StartupIntegrityError, validate_startup_integrity


def _load(root: Path, rel: str):
    return json.loads((root / rel).read_text(encoding='utf-8'))


def _save(root: Path, rel: str, value) -> None:
    (root / rel).write_text(json.dumps(value, separators=(',', ':')) + '\n', encoding='utf-8')


def test_current_campaign_passes_fast_startup_integrity(campaign: Path) -> None:
    result = validate_startup_integrity(campaign)
    assert result['ok'] is True
    assert result['scheduler_hosts'] == result['scheduler_events']
    assert result['formation_commanders_checked'] > 0


def test_startup_integrity_rejects_split_player_location(campaign: Path) -> None:
    player = _load(campaign, 'state/player.json')
    player['current_location'] = 'loc_qin_eastern_depot'
    _save(campaign, 'state/player.json', player)
    with pytest.raises(StartupIntegrityError, match='player location aliases diverge'):
        validate_startup_integrity(campaign)


def test_startup_integrity_rejects_commander_span_drift(campaign: Path) -> None:
    owners = _load(campaign, 'state/index/owner-index.json')['owners']
    ref = 'char_cmd_qin_kanki_raider_host'
    path = owners[ref]
    person = _load(campaign, path)
    person['career_state']['current_command_span'] -= 500
    _save(campaign, path, person)
    with pytest.raises(StartupIntegrityError, match='commander career span diverges'):
        validate_startup_integrity(campaign)
