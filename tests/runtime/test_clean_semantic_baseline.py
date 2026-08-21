from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str):
    return json.loads((ROOT / rel).read_text())


def test_current_save_contains_only_current_campaign_truth() -> None:
    meta = _read('state/meta.json')
    history = _read('state/history/events/index.json')
    assert meta['revision'] == 1
    assert history.get('archives', []) == []
    assert all(row.get('kind') != 'explicit_repair' for row in history.get('events', []))
    assert all(row.get('kind') != 'scene_consequence' for row in history.get('events', []))
    serialized = json.dumps(history)
    for forbidden in ('request_id', 'surface_digest', 'repair_replay', 'transaction_id'):
        assert forbidden not in serialized
    assert not any('repair' in key or 'migration' in key or 'baseline' in key for key in meta)
    assert _read('state/runtime.json')['world_time'] == meta['time']
    assert not (ROOT / 'state/mem/memory-episodes.json').exists()
    assert not (ROOT / 'state/career/merit-and-career-history.json').exists()


def test_debug_autonomy_attempts_are_not_campaign_state() -> None:
    for rel in [
        'state/char/shin.json', 'state/char/sei-kyou.json', 'state/char/ei-sei.json',
        'state/char/hyou.json', 'state/char/ketsu-shi.json',
    ]:
        runtime = _read(rel).get('runtime', {})
        assert 'autonomous_action_attempts' not in runtime
        assert 'autonomous_material_actions' not in runtime
        assert 'last_autonomous_action_at' not in runtime

