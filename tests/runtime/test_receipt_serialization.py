from types import SimpleNamespace

from sword_runtime.api.operations import CampaignOperations, _receipt_record
from sword_runtime.tx.canonical import freeze_json


def _receipt():
    return SimpleNamespace(
        request_id="request.test",
        transaction_id="transaction.test",
        campaign_id="campaign.test",
        committed_revision=7,
        committed_at="245-BCE-01-01T00:00:00+08:00",
        result=freeze_json(
            {
                "wake_required": True,
                "wake": {
                    "kind": "campaign_event",
                    "refs": ["event.test"],
                },
            }
        ),
    )


def test_receipt_record_recursively_thaws_nested_json() -> None:
    record = _receipt_record(SimpleNamespace(status="committed", receipt=_receipt()))
    assert isinstance(record["result"], dict)
    assert isinstance(record["result"]["wake"], dict)
    assert isinstance(record["result"]["wake"]["refs"], list)
    assert record["result"]["wake"]["refs"] == ["event.test"]


def test_duplicate_receipt_recursively_thaws_nested_json() -> None:
    receipt = _receipt()
    runtime = SimpleNamespace(
        coordinator=SimpleNamespace(lookup_receipt=lambda command: receipt)
    )
    operations = object.__new__(CampaignOperations)
    operations.runtime = runtime
    record = operations.lookup_command_receipt(object())
    assert record is not None
    assert record["status"] == "duplicate"
    assert isinstance(record["result"]["wake"], dict)
    assert record["result"]["wake"]["refs"] == ["event.test"]
