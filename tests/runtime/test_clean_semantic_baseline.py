from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str):
    return json.loads((ROOT / rel).read_text())


def test_current_save_has_no_dev_generated_semantic_history() -> None:
    meta = _read('state/meta.json')
    history = _read('state/history/events/index.json')
    assert meta['revision'] == 1
    assert history['baseline_ref'] == meta['baseline_ref']
    assert history['events'] == []
    assert history['archives'] == []
    assert history['archived_event_count'] == 0
    assert history['next_archive_seq'] == 1

    memory = _read('state/mem/memory-episodes.json')
    assert [row['record_id'] for row in memory['records']] == ['overview']
    assert memory['runtime']['last_settled_at'] == meta['time']


def test_debug_autonomy_histories_do_not_survive_the_clean_baseline() -> None:
    for rel in [
        'state/char/shin.json', 'state/char/sei-kyou.json', 'state/char/ei-sei.json',
        'state/char/hyou.json', 'state/char/ketsu-shi.json',
    ]:
        runtime = _read(rel).get('runtime', {})
        assert 'autonomous_action_attempts' not in runtime
        assert 'autonomous_material_actions' not in runtime
        assert 'last_autonomous_action_at' not in runtime

    house = _read('state/houses/house_shou_bun_kun_household.json')
    assert house.get('world_arc_priorities') == []
    assert house.get('material_directives') == []
    for rel in ['state/states/qin.json', 'state/states/wei.json']:
        state = _read(rel)
        assert state.get('world_arc_priorities') == []
        assert state.get('strategic_directives') == []
