from datetime import date, timedelta
from typing import Callable, Any

from ski_signal.models import FlightObservation
from ski_signal.sources.common import get_json, session


URL = "https://serpapi.com/search.json"


def parse_flights(payload: dict[str, Any]) -> FlightObservation:
    prices: list[float] = []
    for key in ("best_flights", "other_flights"):
        for flight in payload.get(key, []) or []:
            if flight.get("price") is not None:
                prices.append(float(flight["price"]))
    insights = payload.get("price_insights") or {}
    if insights.get("lowest_price") is not None:
        prices.append(float(insights["lowest_price"]))
    price_range = insights.get("typical_price_range")
    parsed_range = None
    if isinstance(price_range, (list, tuple)) and len(price_range) >= 2:
        parsed_range = (float(price_range[0]), float(price_range[1]))
    return FlightObservation(
        price=min(prices) if prices else None,
        price_range=parsed_range,
        price_level=insights.get("price_level"),
        google_flights_url=(payload.get("search_metadata") or {}).get("google_flights_url"),
    )


def fetch_flights(
    *,
    api_key: str,
    departure_id: str,
    arrival_id: str,
    departure: date,
    return_date: date,
    adults: int,
    authorize: Callable[[], Any],
) -> FlightObservation:
    authorize()
    payload = get_json(
        URL,
        params={
            "engine": "google_flights",
            "departure_id": departure_id,
            "arrival_id": arrival_id,
            "outbound_date": departure.isoformat(),
            "return_date": return_date.isoformat(),
            "adults": adults,
            "currency": "USD",
            "api_key": api_key,
        },
        client=session(),
    )
    return parse_flights(payload)
