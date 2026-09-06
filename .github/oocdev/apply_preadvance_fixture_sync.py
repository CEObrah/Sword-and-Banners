from pathlib import Path

path = Path("tests/runtime/test_campaign_arrival_lifecycle_regression.py")
text = path.read_text()
needle = '''    monkeypatch.setattr(\n        production.ProductionCampaignPlanner,\n        "_reconcile_campaign_entry_authority",\n        lambda self: calls.append("entry_authority") or ["operation.test"],\n        raising=False,\n    )\n'''
replacement = '''    monkeypatch.setattr(\n        production,\n        "reconcile_undelivered_campaign_decisions",\n        lambda self: calls.append("undelivered_decisions") or [],\n    )\n    monkeypatch.setattr(\n        production.ProductionCampaignPlanner,\n        "_reconcile_campaign_entry_authority",\n        lambda self: calls.append("entry_authority") or ["operation.test"],\n        raising=False,\n    )\n'''
if text.count(needle) != 1:
    raise SystemExit(f"expected one pre-advance fixture insertion site, found {text.count(needle)}")
text = text.replace(needle, replacement, 1)
needle2 = '''    monkeypatch.setattr(\n        production.ProductionTimeIntegrationMixin,\n        "_prepare_scheduler_for_advance",\n        lambda self, target_text: calls.append(("scheduler", target_text)),\n    )\n'''
replacement2 = '''    monkeypatch.setattr(\n        production,\n        "reconcile_legacy_qin_command_support_state",\n        lambda self: calls.append("legacy_qin_support") or [],\n    )\n    monkeypatch.setattr(\n        production,\n        "sync_campaign_decision_delivery_routes",\n        lambda self: calls.append("delivery_routes") or [],\n    )\n    monkeypatch.setattr(\n        production.ProductionTimeIntegrationMixin,\n        "_prepare_scheduler_for_advance",\n        lambda self, target_text: calls.append(("scheduler", target_text)),\n    )\n    monkeypatch.setattr(\n        production,\n        "reconcile_overdue_qin_command_support_routes",\n        lambda self: calls.append("overdue_qin_support") or [],\n    )\n'''
if text.count(needle2) != 1:
    raise SystemExit(f"expected one scheduler fixture insertion site, found {text.count(needle2)}")
text = text.replace(needle2, replacement2, 1)
old_expected = '''    assert calls == [\n        "entry_authority",\n        "arrival",\n        ("follow_on", ["operation.test"]),\n        "command_decisions",\n        "follow_on_semantics",\n        ("scheduler", "244-BCE-11-15T08:22:48+08:00"),\n    ]\n'''
new_expected = '''    assert calls == [\n        "undelivered_decisions",\n        "entry_authority",\n        "arrival",\n        ("follow_on", ["operation.test"]),\n        "command_decisions",\n        "follow_on_semantics",\n        "legacy_qin_support",\n        "delivery_routes",\n        ("scheduler", "244-BCE-11-15T08:22:48+08:00"),\n        "overdue_qin_support",\n    ]\n'''
if text.count(old_expected) != 1:
    raise SystemExit(f"expected one call-order assertion, found {text.count(old_expected)}")
path.write_text(text.replace(old_expected, new_expected, 1))
