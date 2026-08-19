from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str):
    return json.loads((ROOT / rel).read_text())


def test_current_save_has_only_explicit_post_baseline_repair_history() -> None:
    meta = _read('state/meta.json')
    history = _read('state/history/events/index.json')
    repair = meta.get('last_progression_integrity_repair', {})
    assert meta['revision'] == 6
    assert history['baseline_ref'] == meta['baseline_ref']
    assert history['archives'] == []
    assert history['archived_event_count'] == 0
    assert history['next_archive_seq'] == 1
    expected_ids = [
        'repair_progression_integrity_244_bce_07_29',
        'repair_training_fairness_canon_244_bce_07_29',
        'repair_universal_active_training_244_bce_07_29',
        'repair_universal_training_hierarchy_final_244_bce_07_29',
        'repair_bastion_standing_training_tracking_244_bce_07_29',
    ]
    assert [row['event_id'] for row in history['events']] == expected_ids
    assert all(row['kind'] == 'explicit_repair' for row in history['events'])
    assert all(row['at'] == meta['time'] for row in history['events'])

    event = history['events'][0]
    assert event['event_id'] == repair['event_ref'] == 'repair_progression_integrity_244_bce_07_29'
    assert event['at'] == repair['at'] == meta['time']
    assert event['repaired_exact_people'] == [
        'char_duan_jin', 'char_mou_ki', 'char_mu_zhen', 'char_ou_ken', 'char_qiu_ren',
        'char_sei_kai', 'char_shen_rui', 'char_shou_bun_kun', 'char_shou_hei_kun',
        'char_wei_jian', 'char_zhao_fen',
    ]
    assert event['repaired_exact_hours'] == repair['repaired_exact_hours'] == 8792

    universal = meta['last_universal_training_repair']
    assert universal['event_ref'] == 'repair_universal_active_training_244_bce_07_29'
    assert universal['migration_ref'] == 'universal_active_48h_week_v1'
    finalization = meta['last_universal_training_hierarchy_finalization']
    assert finalization['event_ref'] == 'repair_universal_training_hierarchy_final_244_bce_07_29'
    assert finalization['migration_ref'] == 'universal_training_hierarchy_final_v1'

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
