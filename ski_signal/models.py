from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class DepthObservation:
    station: str
    depth_cm: float
    observed_at: str
    source_url: str


@dataclass
class EnsembleForecast:
    dates: list[date]
    members: dict[str, list[float | None]]
    source_url: str


@dataclass
class ArchiveClimatology:
    dates: list[date]
    snowfall_cm: list[float | None]
    source_url: str


@dataclass
class EnsoObservation:
    anomaly: float
    source_url: str


@dataclass
class FlightObservation:
    price: float | None
    price_range: tuple[float, float] | None
    price_level: str | None
    google_flights_url: str | None
    currency: str = "USD"


@dataclass
class HotelProperty:
    name: str
    price: float | None
    url: str | None


@dataclass
class HotelObservation:
    lowest_total: float | None
    properties: list[HotelProperty] = field(default_factory=list)
    currency: str = "USD"


@dataclass
class FxObservation:
    rate: float
    p10: float
    p90: float
    rates: list[float]


@dataclass
class SkiEvent:
    title: str
    start_date: date
    end_date: date
    url: str
    source: str
    raw: dict[str, Any] = field(default_factory=dict)
