from pathlib import Path

path = Path("tests/runtime/test_player_story_flow.py")
text = path.read_text(encoding="utf-8")

constants_old = '''QUALIFICATION_REF = "event_ouki_preliminary_review_disposition_001"\nFORMATION_REF = "formation_qin_mobile_reserve"\n'''
constants_new = '''QUALIFICATION_REF = "event_ouki_preliminary_review_disposition_001"\nFORMATION_REF = "formation_qin_mobile_reserve"\nTEST_OPERATION_REF = "operation_test_player_story_qin_vacancy"\nTEST_OPERATION_PATH = "state/operations/operation_test_player_story_qin_vacancy.json"\n'''
if constants_old not in text:
    raise RuntimeError("player-story fixture constants insertion point not found")
text = text.replace(constants_old, constants_new, 1)

fixture_old = '''    qin = copy.deepcopy(planner.read("state/states/qin.json"))\n    for row in qin.get("appointments", {}).values():\n'''
fixture_new = '''    # The command-offer lifecycle is the subject of this test, so give it one\n    # exact synthetic operation owner instead of inheriting whichever real\n    # campaign operations happen to exist in the supplied save.\n    operation = {\n        "schema": "sword-operation",\n        "owner_id": TEST_OPERATION_REF,\n        "operation_ref": TEST_OPERATION_REF,\n        "kind": "test_qin_field_operation",\n        "status": "active",\n        "administrative_authority": "state_qin",\n        "administrative_authorities": ["state_qin"],\n        "institutional_owner_ref": "state_qin",\n        "formation_refs": [FORMATION_REF],\n        "objective_refs": ["arc_ryo_fui_northern_wei_campaign"],\n        "objective": "Disposable test operation for one exact Qin command vacancy",\n    }\n    planner.put(TEST_OPERATION_PATH, operation)\n    operation_index = copy.deepcopy(planner.read("state/operations/index.json"))\n    operation_index["operations"] = {TEST_OPERATION_REF: TEST_OPERATION_PATH}\n    operation_index["active_battlefield_operation_refs"] = []\n    planner.put("state/operations/index.json", operation_index)\n\n    qin = copy.deepcopy(planner.read("state/states/qin.json"))\n    for row in qin.get("appointments", {}).values():\n'''
if fixture_old not in text:
    raise RuntimeError("player-story operation fixture insertion point not found")
text = text.replace(fixture_old, fixture_new, 1)

assertions_old = '''    events = [get_causal_event(planner, ref) for ref in refs]\n    summaries = [str(row.get("summary", "")) for row in events if row is not None]\n    assert any("Inner Walls has completed" in summary for summary in summaries)\n    assert any("Inner Walls" in summary for summary in summaries)\n    assert any("family hall" in summary for summary in summaries)\n    assert all(row.get("provenance", {}).get("kind") == "causal_runtime_settlement" for row in events if row is not None)\n'''
assertions_new = '''    events = [get_causal_event(planner, ref) for ref in refs]\n    house_events = [\n        row for row in events\n        if row is not None and row.get("process_kind") == "house_development_digest"\n    ]\n    family_events = [\n        row for row in events\n        if row is not None and row.get("process_kind") == "family_initiative"\n    ]\n    assert house_events\n    assert family_events\n    assert any("unified House force has completed" in str(row.get("summary", "")) for row in house_events)\n    assert any("Current conserved establishments:" in str(row.get("summary", "")) for row in house_events)\n    assert any("invitation rather than a command" in str(row.get("summary", "")) for row in family_events)\n    assert all(row.get("provenance", {}).get("kind") == "causal_runtime_settlement" for row in events if row is not None)\n'''
if assertions_old not in text:
    raise RuntimeError("stale player-story digest assertions not found")
text = text.replace(assertions_old, assertions_new, 1)

path.write_text(text, encoding="utf-8")
