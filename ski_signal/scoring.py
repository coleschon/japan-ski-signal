from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import holidays

from ski_signal.models import ArchiveClimatology, EnsembleForecast, SkiEvent


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def base_eligible(depth_cm: float, config: dict[str, Any]) -> bool:
    return depth_cm >= config["snow"]["base_gate_cm"]


def base_score(depth_cm: float, config: dict[str, Any]) -> float:
    snow = config["snow"]
    return clamp(
        (depth_cm - snow["base_gate_cm"]) / (snow["base_full_cm"] - snow["base_gate_cm"])
    )


def forecast_score(median_sum_cm: float, config: dict[str, Any]) -> float:
    return clamp(median_sum_cm / config["snow"]["forecast_full_cm"])


def enso_class(anomaly: float, config: dict[str, Any]) -> str:
    factors = config["snow"]["enso_factor"]
    for name, rule in factors.items():
        if name == "neutral":
            continue
        if "min_anom" in rule and anomaly >= rule["min_anom"]:
            return name
        if "max_anom" in rule and anomaly <= rule["max_anom"]:
            return name
    return "neutral"


def enso_adjusted_climatology_score(
    climatology_score: float,
    anomaly: float,
    region: str,
    config: dict[str, Any],
) -> float:
    kind = enso_class(anomaly, config)
    return clamp(climatology_score * config["snow"]["enso_factor"][kind][region])


def flight_score(
    price: float | None,
    price_range: tuple[float, float] | None,
    price_level: str | None,
    config: dict[str, Any],
) -> float:
    if price is not None and price_range is not None:
        low, high = price_range
        if high <= low:
            return 1.0 if price <= low else 0.0
        if price <= low:
            return 1.0
        if price >= high:
            return 0.0
        return clamp((high - price) / (high - low))
    fallback = config["flights"]["level_fallback"]
    if price_level in fallback:
        return float(fallback[price_level])
    return config["flights"]["unknown_score"]


def lodging_score(
    price: float | None,
    observations: Iterable[float],
    config: dict[str, Any],
) -> float:
    values = [float(value) for value in observations]
    if price is None or len(values) < config["lodging"]["min_observations"]:
        return config["lodging"]["unknown_score"]
    percentile_rank = sum(value <= price for value in values) / len(values)
    return clamp(1.0 - percentile_rank)


def yen_score(rate: float | None, p10: float | None, p90: float | None) -> float:
    if rate is None or p10 is None or p90 is None or p90 <= p10:
        return 0.5
    return clamp((rate - p10) / (p90 - p10))


def forecast_window_median(
    forecast: EnsembleForecast,
    start: date,
    end: date,
) -> float:
    date_index = {day: index for index, day in enumerate(forecast.dates)}
    days = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
    if any(day not in date_index for day in days):
        raise ValueError("Forecast does not cover the requested snow window")
    totals: list[float] = []
    for values in forecast.members.values():
        selected = [values[date_index[day]] for day in days if date_index[day] < len(values)]
        if len(selected) != len(days) or any(value is None for value in selected):
            continue
        totals.append(sum(float(value) for value in selected))
    if not totals:
        raise ValueError("No complete ensemble members for the requested snow window")
    return float(median(totals))


def _month_day_means(climatology: ArchiveClimatology) -> dict[tuple[int, int], float]:
    samples: dict[tuple[int, int], list[float]] = defaultdict(list)
    for day, snowfall in zip(climatology.dates, climatology.snowfall_cm):
        if snowfall is not None:
            samples[(day.month, day.day)].append(snowfall)
    if not samples:
        raise ValueError("No snowfall data in climatology")
    return {key: sum(values) / len(values) for key, values in samples.items()}


def climatology_score(
    climatology: ArchiveClimatology,
    departure: date,
) -> float:
    means = _month_day_means(climatology)
    trip_days = [departure + timedelta(days=offset) for offset in range(1, 8)]
    trip_total = sum(means.get((day.month, day.day), 0.0) for day in trip_days)

    season_days: list[date] = []
    day = date(2020, 12, 1)
    while day <= date(2021, 3, 31):
        season_days.append(day)
        day += timedelta(days=1)
    windows = [
        sum(means.get((day.month, day.day), 0.0) for day in season_days[index : index + 7])
        for index in range(len(season_days) - 6)
    ]
    maximum = max(windows, default=0.0)
    return clamp(trip_total / maximum) if maximum > 0 else 0.5


def snow_score(
    *,
    depth_cm: float,
    forecast: EnsembleForecast,
    climatology: ArchiveClimatology,
    anomaly: float,
    region: str,
    departure: date,
    config: dict[str, Any],
) -> tuple[float, dict[str, float | str | None]]:
    snow = config["snow"]
    base = base_score(depth_cm, config)
    start = departure - timedelta(days=2)
    end = departure + timedelta(days=7)
    last_forecast_date = max(forecast.dates)
    if end <= last_forecast_date:
        window_median = forecast_window_median(forecast, start, end)
        forecast_value = forecast_score(window_median, config)
        mix = snow["in_horizon_mix"]
        score = mix["base"] * base + mix["forecast"] * forecast_value
        return clamp(score), {
            "base": base,
            "forecast": forecast_value,
            "climatology": 0.5,
            "enso_class": enso_class(anomaly, config),
            "snow_window_median_cm": window_median,
        }
    climate = climatology_score(climatology, departure)
    adjusted = enso_adjusted_climatology_score(climate, anomaly, region, config)
    mix = snow["beyond_horizon_mix"]
    score = mix["base"] * base + mix["climatology"] * adjusted
    return clamp(score), {
        "base": base,
        "forecast": 0.5,
        "climatology": adjusted,
        "enso_class": enso_class(anomaly, config),
        "snow_window_median_cm": None,
    }


def _japan_holidays(days: list[date]) -> Any:
    min_year = min(day.year for day in days)
    max_year = max(day.year for day in days)
    years = set(range(min_year - 1, max_year + 2))
    return holidays.country_holidays("JP", years=years)


def crowd_daily_levels(
    resort: str,
    trip_days: list[date],
    config: dict[str, Any],
) -> dict[date, float]:
    settings = config["crowds_events"]
    japan_holidays = _japan_holidays(trip_days)
    result: dict[date, float] = {}
    for day in trip_days:
        levels = [settings["saturday_level"]] if day.weekday() == 5 else []
        if day in japan_holidays or (
            day.weekday() >= 5
            and (day - timedelta(days=1) in japan_holidays or day + timedelta(days=1) in japan_holidays)
        ):
            levels.append(settings["japan_holiday_long_weekend_level"])
        for period in settings["periods"]:
            if date.fromisoformat(str(period["start"])) <= day <= date.fromisoformat(str(period["end"])):
                level = period["level"].get(resort, period["level"].get("all"))
                if level is not None:
                    levels.append(float(level))
        result[day] = max(levels, default=0.0)
    return result


def events_score(
    events: Iterable[SkiEvent] | None,
    trip_days: list[date],
    config: dict[str, Any],
) -> float:
    if events is None:
        return 0.5
    trip_start, trip_end = min(trip_days), max(trip_days)
    distinct = {
        (event.title.casefold(), event.start_date, event.end_date)
        for event in events
        if event.start_date <= trip_end and event.end_date >= trip_start
    }
    return min(1.0, len(distinct) / config["crowds_events"]["events_full_count"])


def crowds_events_score(
    resort: str,
    departure: date,
    events: Iterable[SkiEvent] | None,
    config: dict[str, Any],
) -> tuple[float, dict[str, Any]]:
    trip_days = [departure + timedelta(days=offset) for offset in range(1, 8)]
    levels = crowd_daily_levels(resort, trip_days, config)
    crowd = clamp(1 - sum(levels.values()) / len(trip_days))
    event_score = events_score(events, trip_days, config)
    if resort == "niseko":
        mix = config["crowds_events"]["niseko_mix"]
        combined = mix["crowd"] * crowd + mix["events"] * event_score
    else:
        combined = crowd
    return clamp(combined), {
        "crowd": crowd,
        "events": event_score,
        "daily_levels": {day.isoformat(): level for day, level in levels.items()},
    }


def total_score(
    components: dict[str, float],
    config: dict[str, Any],
    *,
    eligible: bool = True,
) -> float:
    if not eligible:
        return 0.0
    return sum(config["weights"][name] * components[name] for name in config["weights"])


def candidate_departures(today: date, config: dict[str, Any]) -> list[date]:
    trip = config["trip"]
    weekday = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}[
        trip["candidate_weekday"]
    ]
    first = today + timedelta(days=trip["window_min_days"])
    first += timedelta(days=(weekday - first.weekday()) % 7)
    final = today + timedelta(days=trip["window_max_days"])
    departures = []
    departure = first
    while departure <= final:
        departures.append(departure)
        departure += timedelta(days=7)
    return departures


def run_date(config: dict[str, Any], now: datetime | None = None) -> date:
    zone = ZoneInfo(config["timezone_run"])
    return (now or datetime.now(zone)).astimezone(zone).date()
