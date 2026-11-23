from datetime import date
from typing import Any, Callable
from urllib.parse import urlencode

from ski_signal.models import HotelObservation, HotelProperty
from ski_signal.sources.common import get_json, session


URL = "https://serpapi.com/search.json"
GOOGLE_HOTELS_URL = "https://www.google.com/travel/search"


def _google_hotels_search_url(
    name: str,
    *,
    query: str | None = None,
    checkin: date | None = None,
    checkout: date | None = None,
    adults: int | None = None,
) -> str:
    params = {"q": " ".join(part for part in (name, query) if part)}
    if checkin is not None:
        params["checkin"] = checkin.isoformat()
    if checkout is not None:
        params["checkout"] = checkout.isoformat()
    if adults is not None:
        params["adults"] = str(adults)
    return f"{GOOGLE_HOTELS_URL}?{urlencode(params)}"


def parse_hotels(
    payload: dict[str, Any],
    *,
    query: str | None = None,
    checkin: date | None = None,
    checkout: date | None = None,
    adults: int | None = None,
) -> HotelObservation:
    properties: list[HotelProperty] = []
    prices: list[float] = []
    for hotel in payload.get("properties", []) or []:
        rate = hotel.get("total_rate") or {}
        price = rate.get("extracted_lowest")
        if price is not None:
            price = float(price)
            prices.append(price)
        name = str(hotel.get("name", "Hotel"))
        properties.append(
            HotelProperty(
                name=name,
                price=price,
                url=hotel.get("link")
                or _google_hotels_search_url(
                    name,
                    query=query,
                    checkin=checkin,
                    checkout=checkout,
                    adults=adults,
                ),
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
    return parse_hotels(
        payload,
        query=query,
        checkin=checkin,
        checkout=checkout,
        adults=adults,
    )
