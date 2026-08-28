from __future__ import annotations

import copy
import json

from sword_runtime.chariot_platforms import operational_chariot_capacity
from sword_runtime.unit_duties import assign_phase_duties


def test_chariot_role_is_bounded_by_platforms_and_shared_conserved_horses(campaign):
    rules = json.loads((campaign / "game/data/mechanics/formation.json").read_text())["chariot_platforms"]
    forming = json.loads((campaign / "state/formations/qin-chariot-screen.json").read_text())
    forming_cap = operational_chariot_capacity(forming, rules)
    assert forming_cap["crew_personnel"] == 2000
    assert forming_cap["physical_platforms"] == 120
    assert forming_cap["operational_platforms"] == 120
    assert forming_cap["operational_crew"] == 360

    kankoku = json.loads((campaign / "state/formations/qin-kankoku-mobile-reserve.json").read_text())
    cap = operational_chariot_capacity(kankoku, rules)
    assert cap["physical_platforms"] == 333
    assert cap["crew_personnel"] == 1000
    assert cap["chariot_horses"] == 1000
    assert cap["direct_rider_horses"] == 3000
    assert cap["operational_platforms"] == 333  # 3 horses per platform from the shared pool
    assert cap["operational_crew"] == 999

    no_horses = copy.deepcopy(kankoku)
    no_horses.setdefault("mounts", {})["horse"] = 0
    assert operational_chariot_capacity(no_horses, rules)["operational_platforms"] == 0

    wrecked = copy.deepcopy(kankoku)
    wrecked["chariot_platform_condition_pct"] = 0
    assert operational_chariot_capacity(wrecked, rules)["operational_platforms"] == 0


def test_unit_duty_solver_covers_distinct_phase_duties_and_never_creates_bodies(campaign):
    registry = json.loads((campaign / "game/data/mechanics/unit-duties.json").read_text())
    group = {"units": [
        {"kind": "formation", "ref": "qin_inf"},
        {"kind": "formation", "ref": "qin_cav"},
        {"kind": "formation", "ref": "qin_missile"},
        {"kind": "formation", "ref": "house_guard"},
    ]}
    formations = {
        "qin_inf": {"formation_class": "unit", "owner_force_ref": "force_state_qin", "administrative_owner": "state_qin", "personnel": 1000, "authorized_strength": 1000, "composition": {"line_infantry": 1000}, "readiness": 90, "cohesion": 90, "morale": 90},
        "qin_cav": {"formation_class": "unit", "owner_force_ref": "force_state_qin", "administrative_owner": "state_qin", "personnel": 1000, "authorized_strength": 1000, "composition": {"cavalry": 1000}, "readiness": 90, "cohesion": 90, "morale": 90},
        "qin_missile": {"formation_class": "unit", "owner_force_ref": "force_state_qin", "administrative_owner": "state_qin", "personnel": 1000, "authorized_strength": 1000, "composition": {"archer": 1000}, "readiness": 90, "cohesion": 90, "morale": 90},
        "house_guard": {"formation_class": "unit", "owner_force_ref": "force_house_tang", "administrative_owner": "house_tang", "personnel": 3000, "authorized_strength": 3000, "composition": {"household_retainer": 3000}, "readiness": 95, "cohesion": 95, "morale": 95},
    }
    before = {ref: int(row["personnel"]) for ref, row in formations.items()}
    rows = assign_phase_duties(
        phase="march",
        group=group,
        formations_by_ref=formations,
        people_by_ref={},
        doctrine={"unit_duty_policy": {"eligible_force_refs": ["force_state_qin"], "eligible_administrative_owners": ["state_qin"]}},
        registry=registry,
    )
    assert {row["formation_ref"] for row in rows} == {"qin_inf", "qin_cav", "qin_missile"}
    assert len({row["duty_id"] for row in rows}) == 3
    assert all(row["formation_ref"] != "house_guard" for row in rows)
    assert {ref: int(row["personnel"]) for ref, row in formations.items()} == before
