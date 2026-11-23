from datetime import date, datetime
from decimal import Decimal
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import ski_signal.runner as runner
from ski_signal.config import load_config
from ski_signal.models import DepthObservation
from ski_signal.runner import _persist_source, run_signal
from ski_signal.storage import DynamoStore, LocalStore


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

def test_dynamo_store_serializes_dataclass_observations_as_field_dicts():
    store = DynamoStore.__new__(DynamoStore)
    store.table = Mock()
    observation = DepthObservation(
        station="16217",
        depth_cm=21.5,
        observed_at="2026-11-23T08:00:00+09:00",
        source_url="https://example.com/amedas",
    )

    store.put("observation:depth:niseko", observation)
    saved_item = store.table.put_item.call_args.kwargs["Item"]
    assert saved_item["value"] == {
        "station": "16217",
        "depth_cm": Decimal("21.5"),
        "observed_at": "2026-11-23T08:00:00+09:00",
        "source_url": "https://example.com/amedas",
    }

    store.table.get_item.return_value = {"Item": saved_item}
    restored = store.get("observation:depth:niseko")
    assert isinstance(restored, dict)
    assert isinstance(restored["depth_cm"], float)
    assert restored["depth_cm"] == 21.5


def test_source_persistence_failure_does_not_raise(caplog):
    class FailingStore:
        def put(self, key, value):
            raise OSError("storage unavailable")

    _persist_source(FailingStore(), "observation:depth:niseko", {"depth_cm": 21.5}, "amedas")

    assert "Could not persist amedas source data" in caplog.text


def test_run_signal_completes_when_event_fetch_fails_without_cache(tmp_path, monkeypatch):
    config = load_config()
    config["resorts"] = {"niseko": config["resorts"]["niseko"]}
    store = LocalStore(tmp_path / "store")

    def unavailable(*args, **kwargs):
        raise RuntimeError("source unavailable")

    monkeypatch.setattr(runner.amedas, "fetch_depth", unavailable)
    monkeypatch.setattr(runner.openmeteo, "fetch_ensemble", unavailable)
    monkeypatch.setattr(runner.openmeteo, "fetch_climatology", unavailable)
    monkeypatch.setattr(runner.enso, "fetch_enso", unavailable)
    monkeypatch.setattr(runner.fx, "fetch_usd_jpy", unavailable)
    monkeypatch.setattr(runner.niseko_events, "fetch_events", unavailable)
    monkeypatch.setattr(
        runner,
        "candidate_departures",
        lambda today, config: [date(2026, 12, 4)],
    )
    monkeypatch.setattr(
        runner,
        "write_dry_run",
        lambda document, today: tmp_path / "digest.html",
    )

    result = run_signal(
        dry_run=True,
        force_digest=True,
        no_serpapi=True,
        config=config,
        store=store,
        now=datetime(2026, 11, 22, 12, tzinfo=ZoneInfo("America/Los_Angeles")),
    )

    assert store.get("observation:events") is None
    assert result["event_count"] == 0
    assert result["combos"][0]["events"] == []
    assert result["combos"][0]["source_status"]["niseko_events"] == "stale/unavailable"
