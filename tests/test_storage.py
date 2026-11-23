from decimal import Decimal
from unittest.mock import Mock

from ski_signal.runner import _persist_source
from ski_signal.storage import DynamoStore


def test_dynamo_store_converts_nested_floats_and_decimals():
    store = DynamoStore.__new__(DynamoStore)
    store.table = Mock()
    value = {"depth_cm": 21.5, "members": [1, 0.25], "cached": True}

    store.put("observation:depth:niseko", value)
    saved_item = store.table.put_item.call_args.kwargs["Item"]
    assert saved_item["value"] == {
        "depth_cm": Decimal("21.5"),
        "members": [1, Decimal("0.25")],
        "cached": True,
    }
    assert all(
        not isinstance(item, float)
        for item in (saved_item["value"]["depth_cm"], *saved_item["value"]["members"])
    )

    store.table.get_item.return_value = {"Item": saved_item}
    restored = store.get("observation:depth:niseko")
    assert restored == value
    assert isinstance(restored["depth_cm"], float)
    assert isinstance(restored["members"][0], int)
    assert isinstance(restored["members"][1], float)

    store.table.scan.return_value = {"Items": [saved_item]}
    assert store.scan("observation:") == [
        ("observation:depth:niseko", value)
    ]


def test_source_persistence_failure_does_not_raise(caplog):
    class FailingStore:
        def put(self, key, value):
            raise OSError("storage unavailable")

    _persist_source(FailingStore(), "observation:depth:niseko", {"depth_cm": 21.5}, "amedas")

    assert "Could not persist amedas source data" in caplog.text
