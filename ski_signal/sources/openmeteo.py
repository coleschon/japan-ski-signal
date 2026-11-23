from datetime import date, timedelta
from typing import Any

from ski_signal.models import ArchiveClimatology, EnsembleForecast
from ski_signal.sources.common import get_json


ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def _daily_dates(payload: dict[str, Any]) -> list[date]:
    daily = payload.get("daily")
    if not isinstance(daily, dict) or not isinstance(daily.get("time"), list):
        raise ValueError("Open-Meteo response is missing daily dates")
    return [date.fromisoformat(value) for value in daily["time"]]


def fetch_ensemble(
    latitude: float,
    longitude: float,
    elevation_m: int,
    forecast_days: int,
) -> EnsembleForecast:
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": "snowfall_sum",
        "models": "ecmwf_ifs025",
        "forecast_days": forecast_days,
        "elevation": elevation_m,
        "timezone": "Asia/Tokyo",
    }
    payload = get_json(ENSEMBLE_URL, params=params)
    daily = payload.get("daily", {})
    members = {
        key: [None if value is None else float(value) for value in values]
        for key, values in daily.items()
        if key.startswith("snowfall_sum_member") and isinstance(values, list)
    }
    if not members:
        raise ValueError("Open-Meteo response contains no snowfall ensemble members")
    return EnsembleForecast(_daily_dates(payload), members, ENSEMBLE_URL)


def fetch_climatology(
    latitude: float,
    longitude: float,
    *,
    years: int,
    today: date,
) -> ArchiveClimatology:
    start = today.replace(year=today.year - years)
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start.isoformat(),
        "end_date": (today - timedelta(days=1)).isoformat(),
        "daily": "snowfall_sum",
        "timezone": "Asia/Tokyo",
    }
    payload = get_json(ARCHIVE_URL, params=params)
    snowfall = payload.get("daily", {}).get("snowfall_sum")
    if not isinstance(snowfall, list):
        raise ValueError("Open-Meteo archive response has no snowfall_sum")
    return ArchiveClimatology(
        _daily_dates(payload),
        [None if value is None else float(value) for value in snowfall],
        ARCHIVE_URL,
    )
