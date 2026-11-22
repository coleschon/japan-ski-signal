from datetime import date, timedelta

import pytest

from ski_signal.config import load_config
from ski_signal.models import ArchiveClimatology, EnsembleForecast
from ski_signal.scoring import (
    base_eligible,
    base_score,
    crowd_daily_levels,
    enso_adjusted_climatology_score,
    events_score,
    flight_score,
    forecast_score,
    lodging_score,
    snow_score,
    snow_window_in_horizon,
    total_score,
    yen_score,
)


def test_base_gate_and_score():
    config = load_config()
    assert not base_eligible(29, config)
    assert base_eligible(0, config, in_horizon=False)
    assert total_score({name: 1 for name in config["weights"]}, config, eligible=False) == 0
    assert base_score(30, config) == 0
    assert base_score(150, config) == 1
    assert base_score(90, config) == 0.5


def test_base_gate_applies_only_to_in_horizon_snow_windows():
    config = load_config()
    forecast_start = date(2026, 1, 1)
    forecast = EnsembleForecast(
        [forecast_start + timedelta(days=offset) for offset in range(15)],
        {},
        "fixture",
    )
    in_horizon_departure = date(2026, 1, 1)
    assert snow_window_in_horizon(in_horizon_departure, max(forecast.dates))
    assert not base_eligible(21, config, in_horizon=True)
    assert total_score(
        {name: 1 for name in config["weights"]},
        config,
        eligible=base_eligible(21, config, in_horizon=True),
    ) == 0

    beyond_departure = date(2026, 1, 10)
    assert not snow_window_in_horizon(beyond_departure, max(forecast.dates))
    assert base_eligible(0, config, in_horizon=False)
    climate_dates = []
    snowfall = []
    day = date(2020, 12, 1)
    while day <= date(2021, 3, 31):
        climate_dates.append(day)
        snowfall.append(2.0)
        day += timedelta(days=1)
    score, details = snow_score(
        depth_cm=0,
        forecast=forecast,
        climatology=ArchiveClimatology(climate_dates, snowfall, "fixture"),
        anomaly=2.5,
        region="hokkaido",
        departure=beyond_departure,
        config=config,
    )
    expected_climatology = details["climatology"]
    assert expected_climatology != 0.5
    assert score == pytest.approx(
        config["snow"]["beyond_horizon_mix"]["base"] * 0
        + config["snow"]["beyond_horizon_mix"]["climatology"] * expected_climatology
    )
    no_forecast_score, no_forecast_details = snow_score(
        depth_cm=0,
        forecast=None,
        climatology=ArchiveClimatology(climate_dates, snowfall, "fixture"),
        anomaly=2.5,
        region="hokkaido",
        departure=beyond_departure,
        config=config,
    )
    assert no_forecast_details["climatology"] == expected_climatology
    assert no_forecast_score == score
    missing_depth_score, missing_depth_details = snow_score(
        depth_cm=None,
        forecast=None,
        climatology=ArchiveClimatology(climate_dates, snowfall, "fixture"),
        anomaly=2.5,
        region="hokkaido",
        departure=beyond_departure,
        config=config,
    )
    assert base_eligible(0, config, in_horizon=False)
    assert missing_depth_details["base"] == 0.5
    assert missing_depth_score == pytest.approx(
        config["snow"]["beyond_horizon_mix"]["base"] * 0.5
        + config["snow"]["beyond_horizon_mix"]["climatology"] * expected_climatology
    )


def test_forecast_score():
    config = load_config()
    assert forecast_score(50, config) == 0.5
    assert forecast_score(150, config) == 1


def test_enso_factors():
    config = load_config()
    assert enso_adjusted_climatology_score(0.8, 2.5, "honshu", config) == 0.68
    assert enso_adjusted_climatology_score(0.8, 2.5, "hokkaido", config) == 0.76
    assert enso_adjusted_climatology_score(0.99, -0.8, "honshu", config) == 1.0


def test_flight_score():
    config = load_config()
    assert flight_score(900, (800, 1000), None, config) == 0.5
    assert flight_score(700, (800, 1000), None, config) == 1
    assert flight_score(1100, (800, 1000), None, config) == 0
    assert flight_score(None, None, "typical", config) == 0.6
    assert flight_score(None, None, None, config) == 0.5


def test_lodging_unknown_and_percentile():
    config = load_config()
    assert lodging_score(300, [100, 200, 300, 400], config) == 0.5
    assert lodging_score(300, [100, 200, 300, 400, 500], config) == 0.4


def test_yen_score():
    assert round(yen_score(158.64, 140, 160), 3) == 0.932


def test_crowd_daily_max_for_niseko_new_year_week():
    config = load_config()
    departure = date(2026, 12, 28)
    days = [departure + timedelta(days=offset) for offset in range(1, 8)]
    levels = crowd_daily_levels("niseko", days, config)
    assert max(levels.values()) == 1.0
    assert sum(levels.values()) == 6.5
    assert 1 - sum(levels.values()) / len(days) == pytest.approx(1 / 14)


def test_total_score_hand_computed():
    config = load_config()
    components = {
        "snow": 0.1,
        "crowds_events": 0.2,
        "flights": 0.3,
        "lodging": 0.4,
        "yen": 0.5,
    }
    assert abs(total_score(components, config) - 0.21) < 1e-9


def test_climatology_window_score_uses_winter_maximum():
    dates = []
    snowfall = []
    for year in range(2001, 2006):
        current = date(year, 12, 1)
        while current <= date(year + 1, 3, 31):
            dates.append(current)
            snowfall.append(10.0 if current.month == 1 and current.day in range(10, 17) else 1.0)
            current += timedelta(days=1)
    from ski_signal.scoring import climatology_score

    archive = ArchiveClimatology(dates, snowfall, "fixture")
    assert climatology_score(archive, date(2026, 1, 9)) == 1.0


def test_forecast_window_sums_members():
    from ski_signal.scoring import forecast_window_median

    first = date(2026, 1, 1)
    forecast = EnsembleForecast(
        [first + timedelta(days=offset) for offset in range(10)],
        {"member1": [5.0] * 10, "member2": [15.0] * 10},
        "fixture",
    )
    assert forecast_window_median(forecast, first + timedelta(days=1), first + timedelta(days=3)) == 30
