from datetime import date, timedelta

from ski_signal.models import FxObservation
from ski_signal.sources.common import get_json


BASE_URL = "https://api.frankfurter.dev/v1"


def fetch_usd_jpy(today: date, lookback_days: int) -> FxObservation:
    latest = get_json(f"{BASE_URL}/latest", params={"base": "USD", "symbols": "JPY"})
    rate = float(latest["rates"]["JPY"])
    start = (today - timedelta(days=lookback_days)).isoformat()
    series = get_json(
        f"{BASE_URL}/{start}..{today.isoformat()}",
        params={"base": "USD", "symbols": "JPY"},
    )
    values = sorted(float(row["JPY"]) for row in series["rates"].values() if "JPY" in row)
    if not values:
        raise ValueError("Frankfurter returned no USD/JPY history")
    return FxObservation(rate, _percentile(values, 0.1), _percentile(values, 0.9), values)


def _percentile(values: list[float], quantile: float) -> float:
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * quantile
    lower = int(position)
    fraction = position - lower
    upper = min(lower + 1, len(values) - 1)
    return values[lower] * (1 - fraction) + values[upper] * fraction
