from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str):
    return json.loads((ROOT / rel).read_text())


def test_current_save_contains_only_current_campaign_truth() -> None:
    meta = _read('state/meta.json')
    history = _read('state/history/events/index.json')
    assert isinstance(meta.get('revision'), int) and meta['revision'] >= 1
    assert history.get('archives', []) == []
    assert all(row.get('kind') not in {'explicit_repair', 'campaign_truth_correction'} for row in history.get('events', []))
    assert all(row.get('kind') != 'scene_consequence' for row in history.get('events', []))
    serialized = json.dumps(history)
    state_serialized = ''.join(path.read_text(encoding='utf-8') for path in (ROOT / 'state').rglob('*.json'))
    for forbidden in ('request_id', 'surface_digest', 'repair_replay', 'transaction_id'):
        assert forbidden not in serialized
    for forbidden in (
        'order_state_correction',
        'operational_order_40bcfe922894bddb5f',
        'operational_order_68c2c676557270777a',
        'operational_order_12ad00c6933a69a455',
    ):
        assert forbidden not in state_serialized
    assert not any('repair' in key or 'migration' in key or 'baseline' in key for key in meta)
    assert _read('state/runtime.json')['world_time'] == meta['time']
    assert not (ROOT / 'state/mem/memory-episodes.json').exists()
    assert not (ROOT / 'state/career/merit-and-career-history.json').exists()
    for retired in (
        'state/time',
        'state/agency/agency-constraints.json',
        'state/app/role-slots.json',
        'state/order/standing-orders.json',
        'state/index/geography-index.json',
        'game/data/training/contracts.json',
        'game/data/people/canon-capability-calibration.json',
        'game/data/mechanics/rules-runtime-parity.json',
    ):
        assert not (ROOT / retired).exists()

    locations = _read('game/data/world/locations.json')
    routes = _read('game/data/world/routes.json')
    location_rows = locations.get('locations', locations)
    if isinstance(location_rows, dict):
        location_ids = location_rows
    else:
        location_ids = {row.get('id'): row for row in location_rows if isinstance(row, dict)}
    assert not any(str(ref).startswith('loc_flavor_') for ref in location_ids)
    local_routes = routes.get('local_routes', [])
    assert not any(str(row.get('id', '')).startswith('local_flavor_') for row in local_routes if isinstance(row, dict))


def test_debug_autonomy_attempts_are_not_campaign_state() -> None:
    for rel in [
        'state/char/shin.json', 'state/char/sei-kyou.json', 'state/char/ei-sei.json',
        'state/char/hyou.json', 'state/char/ketsu-shi.json',
    ]:
        runtime = _read(rel).get('runtime', {})
        assert 'autonomous_action_attempts' not in runtime
        assert 'autonomous_material_actions' not in runtime
        assert 'last_autonomous_action_at' not in runtime

