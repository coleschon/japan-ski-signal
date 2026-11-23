from datetime import date
from urllib.parse import parse_qs, urlsplit

from ski_signal.sources.common import redact_api_key
from ski_signal.sources.serpapi_flights import parse_flights
from ski_signal.sources.serpapi_hotels import parse_hotels


def test_flight_search_parses_minimum_and_insights():
    result = parse_flights({
        "best_flights": [{"price": 900}],
        "other_flights": [{"price": 950}],
        "price_insights": {
            "lowest_price": 900,
            "price_level": "typical",
            "typical_price_range": [800, 1000],
        },
        "search_metadata": {"google_flights_url": "https://flights.example"},
    })
    assert result.price == 900
    assert result.price_range == (800, 1000)
    assert result.google_flights_url == "https://flights.example"


def test_serpapi_api_key_is_redacted_from_error_messages():
    message = "GET https://serpapi.com/search.json?engine=google&api_key=secret-token failed"

    redacted = redact_api_key(message)

    assert "secret-token" not in redacted
    assert "api_key=[REDACTED]" in redacted


def test_hotel_parser_sorts_top_three():
    result = parse_hotels(
        {
            "properties": [
                {"name": "B", "link": "https://example.com/b", "total_rate": {"extracted_lowest": 200}},
                {"name": "A", "link": "https://example.com/a", "total_rate": {"extracted_lowest": 100}},
                {"name": "C", "property_token": "opaque-token", "total_rate": {"extracted_lowest": 300}},
                {"name": "D", "total_rate": {"extracted_lowest": 400}},
            ],
        },
        query="Niseko Hirafu",
        checkin=date(2026, 12, 5),
        checkout=date(2026, 12, 11),
        adults=3,
    )
    assert result.lowest_total == 100
    assert [hotel.name for hotel in result.properties] == ["A", "B", "C"]
    c_url = urlsplit(result.properties[2].url)
    assert c_url.netloc == "www.google.com"
    assert c_url.path == "/travel/search"
    assert parse_qs(c_url.query) == {
        "q": ["C Niseko Hirafu"],
        "checkin": ["2026-12-05"],
        "checkout": ["2026-12-11"],
        "adults": ["3"],
    }
