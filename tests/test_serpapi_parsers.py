from ski_signal.config import load_config
from ski_signal.scoring import flight_score
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
    assert flight_score(result.price, result.price_range, result.price_level, load_config()) == 0.5


def test_hotel_parser_sorts_top_three():
    result = parse_hotels({
        "properties": [
            {"name": "B", "link": "https://example.com/b", "total_rate": {"extracted_lowest": 200}},
            {"name": "A", "link": "https://example.com/a", "total_rate": {"extracted_lowest": 100}},
            {"name": "C", "total_rate": {"extracted_lowest": 300}},
            {"name": "D", "total_rate": {"extracted_lowest": 400}},
        ]
    })
    assert result.lowest_total == 100
    assert [hotel.name for hotel in result.properties] == ["A", "B", "C"]
