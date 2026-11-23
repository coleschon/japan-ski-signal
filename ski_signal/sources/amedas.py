from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from ski_signal.models import DepthObservation
from ski_signal.sources.common import get_json, get_text


BASE_URL = "https://www.jma.go.jp/bosai/amedas"
JST = ZoneInfo("Asia/Tokyo")


def _parse_latest_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        parsed = datetime.strptime(value, "%Y%m%d%H%M")
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=JST)
    return parsed.astimezone(JST)


def point_block_urls(station: str, latest_time: datetime) -> tuple[str, str]:
    if latest_time.tzinfo is None:
        latest_time = latest_time.replace(tzinfo=JST)
    else:
        latest_time = latest_time.astimezone(JST)
    current = latest_time.replace(
        hour=(latest_time.hour // 3) * 3,
        minute=0,
        second=0,
        microsecond=0,
    )
    previous = current - timedelta(hours=3)
    return (
        f"{BASE_URL}/data/point/{station}/{current:%Y%m%d}_{current:%H}.json",
        f"{BASE_URL}/data/point/{station}/{previous:%Y%m%d}_{previous:%H}.json",
    )


def extract_snow(payload: dict[str, object]) -> tuple[str, float] | None:
    for timestamp in sorted(payload, reverse=True):
        observation = payload[timestamp]
        if not isinstance(observation, dict):
            continue
        snow = observation.get("snow")
        if (
            isinstance(snow, list)
            and len(snow) >= 2
            and snow[0] is not None
            and snow[1] == 0
        ):
            return timestamp, float(snow[0])
    return None


def fetch_depth(station: str) -> DepthObservation:
    latest = _parse_latest_time(get_text(f"{BASE_URL}/data/latest_time.txt").strip())
    current_url, previous_url = point_block_urls(station, latest)
    request_errors = []
    for url in (current_url, previous_url):
        try:
            payload = get_json(url)
        except requests.RequestException as error:
            request_errors.append(error)
            continue
        snow = extract_snow(payload)
        if snow is not None:
            timestamp, depth = snow
            observed = datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(tzinfo=JST)
            return DepthObservation(
                station=str(station),
                depth_cm=depth,
                observed_at=observed.isoformat(),
                source_url=url,
            )
    if len(request_errors) == 2:
        raise request_errors[-1]
    raise ValueError(f"AMeDAS response has no valid snow measurement for {station}")
