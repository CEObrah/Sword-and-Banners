from __future__ import annotations

import json
from pathlib import Path


def _read(root: Path, rel: str) -> dict:
    return json.loads((root / rel).read_text(encoding="utf-8"))


def test_canonical_qin_parentage_is_first_class_and_routed(campaign):
    root = Path(campaign)
    expected = {
        "parentage.ou_hon.birth_parents": ("char_ou_hon", "char_ousen"),
        "parentage.mou_bu.birth_parents": ("char_mou_bu", "char_mou_gou"),
        "parentage.mou_ten.birth_parents": ("char_mou_ten", "char_mou_bu"),
        "parentage.mou_ki.birth_parents": ("char_mou_ki", "char_mou_bu"),
    }
    family_index = _read(root, "state/family/index.json")
    kinship_index = _read(root, "state/family/kinship-index.json")["person_links"]

    assert family_index["counts"]["parentage"] == 6
    assert family_index["counts"]["kinships"] == 2
    for parentage_id, (child_ref, father_ref) in expected.items():
        path = family_index["parentage"][parentage_id]
        doc = _read(root, path)
        assert doc["schema"] == "family-parentage"
        assert doc["authority"] is True
        assert doc["child_id"] == child_ref
        assert doc["parent_links"] == [
            {"kind": "biological", "parent_id": father_ref, "relation_role": "father"}
        ]
        assert parentage_id in family_index["person_index"][child_ref]["parentage"]
        assert parentage_id in family_index["person_index"][father_ref]["parentage"]
        assert kinship_index[child_ref]["parents"] == [father_ref]
        assert child_ref in kinship_index[father_ref]["children"]

    sibling = _read(root, family_index["kinships"]["kinship.mou_ki_mou_ten.siblings"])
    assert sibling["authority"] is True
    assert sibling["participants"] == ["char_mou_ki", "char_mou_ten"]
    assert sibling["relation_roles"] == {
        "char_mou_ki": "younger_brother",
        "char_mou_ten": "older_brother",
    }
    assert "kinship.mou_ki_mou_ten.siblings" in kinship_index["char_mou_ki"]["kinships"]
    assert "kinship.mou_ki_mou_ten.siblings" in kinship_index["char_mou_ten"]["kinships"]


def test_qin_house_lineage_classification_conserves_population(campaign):
    root = Path(campaign)
    mou = _read(root, "state/houses/house_mou_family.json")["lineage_cohort"]
    ou = _read(root, "state/houses/house_ou_family.json")["lineage_cohort"]

    assert mou["exact_member_refs"] == [
        "char_mou_bu",
        "char_mou_gou",
        "char_mou_ki",
        "char_mou_ten",
    ]
    assert mou["unmaterialized_members"] == {"adults": 13, "children": 4, "elders": 2}
    assert mou["adults"] == 15
    assert mou["children"] == 6
    assert mou["elders"] == 2

    assert ou["exact_member_refs"] == ["char_ou_hon", "char_ousen"]
    assert ou["unmaterialized_members"] == {"adults": 14, "children": 5, "elders": 2}
    assert ou["adults"] == 15
    assert ou["children"] == 6
    assert ou["elders"] == 2

    for ref in ("mou-bu", "mou-ten", "mou-ki"):
        assert _read(root, f"state/char/{ref}.json")["house_ref"] == "house_mou_family"
    assert _read(root, "state/char/ou-hon.json")["house_ref"] == "house_ou_family"


def test_mou_ki_relationship_surface_matches_parentage(campaign):
    root = Path(campaign)
    mou_bu = _read(root, "state/char/mou-bu.json")
    mou_ki = _read(root, "state/char/mou-ki.json")
    assert "rel.char_mou_bu.char_mou_ki.father" in mou_bu["relationship_refs"]
    assert mou_ki["relationship_refs"] == ["rel.char_mou_ki.char_mou_bu.son"]

    edges = {row["edge_ref"]: row for row in _read(root, "state/relationships.json")["edges"]}
    assert edges["rel.char_mou_bu.char_mou_ki.father"]["kind"] == "father"
    assert edges["rel.char_mou_bu.char_mou_ki.father"]["target_ref"] == "char_mou_ki"
    assert edges["rel.char_mou_ki.char_mou_bu.son"]["kind"] == "son"
    assert edges["rel.char_mou_ki.char_mou_bu.son"]["target_ref"] == "char_mou_bu"


def test_heki_and_shou_hei_kun_are_generals_without_free_command_growth(campaign):
    root = Path(campaign)
    heki = _read(root, "state/char/heki.json")
    shk = _read(root, "state/char/shou-hei-kun.json")

    assert heki["rank"] == "general"
    assert heki["military_rank"] == {"durable": True, "grade": "general"}
    assert "General" in heki["role"]
    assert heki["command_assignment"]["current_command_span"] == 500
    assert heki["career_state"]["current_command_span"] == 500
    assert heki["military_command"]["level"] == "500_commander"

    assert shk["rank"] == "general"
    assert shk["military_rank"] == {"durable": True, "grade": "general"}
    assert "General" in shk["role"]
    assert "strategist" in shk["role"].lower()
    assert shk["command_assignment"]["current_command_span"] == 3000
    assert shk["career_state"]["current_command_span"] == 3000
    assert shk["military_command"]["level"] == "3000_commander"

    # The repair's provenance is historical; the live campaign is expected to
    # keep advancing after it.  Do not pin this character-state regression to
    # the campaign revision/time at which the repair was originally authored.
    repair_note = (root / "docs/campaign-repairs/canonical-qin-family-ranks-20260828.md").read_text(encoding="utf-8")
    assert "Campaign revision: `7`" in repair_note
    assert "does not advance chronology" in repair_note
    assert "creates no manpower" in repair_note
