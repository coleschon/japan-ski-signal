import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from ski_signal.alerts import select_alerts, storm_windows
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


def test_storm_dedupe_and_growth(tmp_path):
    config = load_config()
    store = LocalStore(tmp_path)
    forecast = fixture_forecast()
    first = select_alerts(
        [], {"niseko": forecast}, {"niseko": 60},
        today=date(2026, 1, 1), config=config, store=store,
    )
    assert any(alert["type"] == "storm" for alert in first)
    repeated = select_alerts(
        [], {"niseko": forecast}, {"niseko": 60},
        today=date(2026, 1, 3), config=config, store=store,
    )
    assert not any(alert["type"] == "storm" for alert in repeated)
    grown = fixture_forecast()
    for values in grown.members.values():
        values[8:11] = [30, 30, 30]
    grown_alerts = select_alerts(
        [], {"niseko": grown}, {"niseko": 60},
        today=date(2026, 1, 3), config=config, store=store,
    )
    assert any(alert["type"] == "storm" for alert in grown_alerts)


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
