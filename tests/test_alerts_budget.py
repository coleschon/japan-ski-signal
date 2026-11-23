import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from ski_signal.alerts import record_sent_alerts, select_alerts, storm_windows
from ski_signal.budget import BudgetExceeded, reserve_search, stalest_first, usage_key
from ski_signal.config import load_config
from ski_signal.models import EnsembleForecast
from ski_signal.storage import LocalStore


FIXTURES = Path(__file__).parent / "fixtures"


def fixture_forecast() -> EnsembleForecast:
    raw = json.loads((FIXTURES / "storm_ensemble.json").read_text())
    return EnsembleForecast(
        [date.fromisoformat(value) for value in raw["dates"]],
        raw["members"],
        "fixture",
    )


def overlapping_storm_forecast(snowfall: float) -> EnsembleForecast:
    first = date(2026, 1, 1)
    dates = [first + timedelta(days=offset) for offset in range(15)]
    members = {f"member{index:02d}": [0.0] * 15 for index in range(12)}
    for values in members.values():
        values[8:12] = [snowfall] * 4
    return EnsembleForecast(dates, members, "fixture")


class AccountSession:
    def __init__(self, used=0, left=100):
        self.used = used
        self.left = left

    def get(self, url, params, timeout):
        return AccountResponse({"this_month_usage": self.used, "plan_searches_left": self.left})


class AccountResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_storm_qualifies_at_eight_days_only():
    config = load_config()
    forecast = fixture_forecast()
    storms = storm_windows(forecast, today=date(2026, 1, 1), depth_cm=60, config=config)
    assert any(storm["window_start"] == "2026-01-09" for storm in storms)
    assert not storm_windows(
        forecast, today=date(2026, 1, 4), depth_cm=60, config=config
    )
    assert not storm_windows(
        forecast, today=date(2026, 1, 1), depth_cm=40, config=config
    )


def test_storm_window_uses_configured_duration():
    config = load_config()
    config["alerts"]["storm"]["window_hours"] = 48
    today = date(2026, 1, 1)
    dates = [today + timedelta(days=offset) for offset in range(15)]
    members = {f"member{index:02d}": [0.0] * 15 for index in range(12)}
    for values in members.values():
        values[8:11] = [20.0, 20.0, 20.0]
    forecast = EnsembleForecast(dates, members, "fixture")

    assert storm_windows(
        forecast,
        today=today,
        depth_cm=60,
        config=config,
    ) == []


def test_overlapping_storms_collapse_and_dedupe_after_delivery(tmp_path):
    config = load_config()
    store = LocalStore(tmp_path)
    forecast = overlapping_storm_forecast(20)
    windows = storm_windows(forecast, today=date(2026, 1, 1), depth_cm=60, config=config)
    assert len(windows) == 2
    first = select_alerts(
        [], {"niseko": forecast}, {"niseko": 60},
        today=date(2026, 1, 1), config=config, store=store,
    )
    first_storms = [alert for alert in first if alert["type"] == "storm"]
    assert len(first_storms) == 1
    assert store.get("alert:storm:niseko") is None
    record_sent_alerts(first, today=date(2026, 1, 1), store=store)
    repeated = select_alerts(
        [], {"niseko": forecast}, {"niseko": 60},
        today=date(2026, 1, 2), config=config, store=store,
    )
    assert not any(alert["type"] == "storm" for alert in repeated)
    grown = overlapping_storm_forecast(25)
    grown_alerts = select_alerts(
        [], {"niseko": grown}, {"niseko": 60},
        today=date(2026, 1, 2), config=config, store=store,
    )
    grown_storms = [alert for alert in grown_alerts if alert["type"] == "storm"]
    assert len(grown_storms) == 1
    assert grown_storms[0]["median_cm"] == pytest.approx(
        first_storms[0]["median_cm"] * 1.25
    )


def test_alert_dedupe_is_written_only_after_delivery_and_force_digest_bypasses(tmp_path):
    config = load_config()
    store = LocalStore(tmp_path)
    today = date(2026, 1, 5)
    combo = {
        "eligible": True,
        "resort_key": "niseko",
        "departure": "2026-02-06",
        "total_score": 1.0,
    }
    alerts = select_alerts(
        [combo], {}, {}, today=today, config=config, store=store, force_digest=True
    )
    assert {alert["type"] for alert in alerts} == {"book_now", "weekly_digest"}
    assert store.get("alert:book-now:niseko:2026-02-06") is None
    assert store.get("alert:digest:2026-01-05") is None
    record_sent_alerts(alerts, today=today, store=store)
    repeated = select_alerts(
        [combo], {}, {}, today=today, config=config, store=store, force_digest=True
    )
    assert [alert["type"] for alert in repeated] == ["weekly_digest"]


def test_budget_refuses_at_cap(tmp_path):
    today = date(2026, 1, 10)
    store = LocalStore(tmp_path)
    store.put(usage_key(today), 2)
    with pytest.raises(BudgetExceeded):
        reserve_search(
            store,
            api_key="test",
            monthly_cap=2,
            today=today,
            session=AccountSession(used=2),
        )


def test_budget_records_reservation_and_stalest_first(tmp_path):
    today = date(2026, 1, 10)
    store = LocalStore(tmp_path)
    assert reserve_search(
        store,
        api_key="test",
        monthly_cap=4,
        today=today,
        session=AccountSession(),
    ) == 1
    assert store.get(usage_key(today)) == 1
    values = {
        "new": {"fetched_at": "2026-01-03"},
        "old": {"fetched_at": "2025-12-03"},
    }
    assert stalest_first([("new", None), ("missing", None), ("old", None)], values, 2) == [
        "missing",
        "old",
    ]
