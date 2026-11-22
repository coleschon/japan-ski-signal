from datetime import date
from typing import Any, Callable
from urllib.parse import urljoin

from ski_signal.models import HotelObservation, HotelProperty
from ski_signal.sources.common import get_json, session


URL = "https://serpapi.com/search.json"


def parse_hotels(payload: dict[str, Any]) -> HotelObservation:
    properties: list[HotelProperty] = []
    prices: list[float] = []
    for hotel in payload.get("properties", []) or []:
        rate = hotel.get("total_rate") or {}
        price = rate.get("extracted_lowest")
        if price is not None:
            price = float(price)
            prices.append(price)
        properties.append(
            HotelProperty(
                name=str(hotel.get("name", "Hotel")),
                price=price,
                url=hotel.get("link") or hotel.get("property_token"),
            )
        )
    properties.sort(key=lambda property_: float("inf") if property_.price is None else property_.price)
    return HotelObservation(min(prices) if prices else None, properties[:3])


def fetch_hotels(
    *,
    api_key: str,
    query: str,
    checkin: date,
    checkout: date,
    adults: int,
    authorize: Callable[[], Any],
) -> HotelObservation:
    authorize()
    payload = get_json(
        URL,
        params={
            "engine": "google_hotels",
            "q": query,
            "check_in_date": checkin.isoformat(),
            "check_out_date": checkout.isoformat(),
            "adults": adults,
            "currency": "USD",
            "api_key": api_key,
        },
        client=session(),
    )
    return parse_hotels(payload)
