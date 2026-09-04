from __future__ import annotations

import json
from pathlib import Path

from sword_runtime.development import _age_factor


def _training() -> dict:
    root = Path(__file__).resolve().parents[2]
    return json.loads((root / 'game/data/mechanics/training.json').read_text(encoding='utf-8'))


def test_child_physical_and_martial_development_has_real_age_bands():
    rules = _training()
    assert [_age_factor(rules, 'physical_or_martial_skill', age) for age in (5, 8, 11, 14, 18)] == [0.12, 0.32, 0.55, 0.82, 1.12]
    assert [_age_factor(rules, 'physical_attribute', age) for age in (5, 8, 11, 14, 18)] == [0.05, 0.18, 0.38, 0.68, 1.14]


def test_child_cognitive_learning_can_outpace_bodily_maturation():
    rules = _training()
    for age in (5, 8, 11, 14):
        assert _age_factor(rules, 'mental_skill', age) > _age_factor(rules, 'physical_or_martial_skill', age)
        assert _age_factor(rules, 'mental_skill', age) > _age_factor(rules, 'physical_attribute', age)


def test_child_command_learning_remains_age_limited_but_progressive():
    rules = _training()
    values = [_age_factor(rules, 'command_or_civil_skill', age) for age in (5, 8, 11, 14, 16, 20)]
    assert values == [0.08, 0.25, 0.48, 0.72, 0.88, 0.96]
    assert values == sorted(values)
