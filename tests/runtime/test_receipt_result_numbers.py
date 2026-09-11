import math

import pytest

from sword_runtime.tx.canonical import canonical_json_bytes, thaw_json
from sword_runtime.tx.receipts import IdempotencyReceipt, normalize_receipt_result


def _receipt(result):
    return IdempotencyReceipt(
        request_id="req-fractional-result",
        request_digest="0" * 64,
        transaction_id="tx-fractional-result",
        campaign_id="sword-banner-tang-wei-main",
        committed_revision=37,
        committed_at="245-BCE-12-07T18:22:48+08:00",
        result=result,
    )


def test_fractional_result_values_become_canonical_decimal_strings():
    receipt = _receipt(
        {
            "standing_training": {
                "remaining_credit_hours": 0.570833,
                "nested": [2.094444, 1, True, None],
            }
        }
    )

    result = thaw_json(receipt.result)
    assert result["standing_training"]["remaining_credit_hours"] == "0.570833"
    assert result["standing_training"]["nested"] == ["2.094444", 1, True, None]
    canonical_json_bytes(receipt.to_record())


def test_receipt_result_normalization_does_not_change_integer_semantics():
    assert normalize_receipt_result({"hours": 1, "ok": True}) == {"hours": 1, "ok": True}


@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan])
def test_non_finite_result_values_still_fail_closed(value):
    with pytest.raises(TypeError, match="non-finite"):
        _receipt({"bad": value})
