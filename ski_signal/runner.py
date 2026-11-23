import logging
import os
import json
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ski_signal.alerts import record_sent_alerts, select_alerts, storm_windows
from ski_signal.budget import reserve_search, stalest_first
from ski_signal.config import load_config
from ski_signal.email import render_email, send_email, write_dry_run
from ski_signal.models import (
    ArchiveClimatology,
    DepthObservation,
    EnsembleForecast,
    EnsoObservation,
    FxObservation,
    FlightObservation,
    HotelObservation,
    SkiEvent,
)
from ski_signal.scoring import (
    base_eligible,
    base_score,
    candidate_departures,
    crowds_events_score,
    enso_class,
    flight_score,
    forecast_window_median,
    lodging_score,
    run_date,
    snow_score,
    snow_window_in_horizon,
    total_score,
    yen_score,
)
from ski_signal.sources import amedas, enso, fx, niseko_events, openmeteo
from ski_signal.sources.common import redact_api_key
from ski_signal.sources.serpapi_flights import fetch_flights
from ski_signal.sources.serpapi_hotels import fetch_hotels
from ski_signal.storage import LocalStore, S3SnapshotWriter, Store, configured_store


LOGGER = logging.getLogger(__name__)


def _record_dataclass(value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        value = [asdict(item) if hasattr(item, "__dataclass_fields__") else item for item in value]
    elif hasattr(value, "__dataclass_fields__"):
        value = asdict(value)
    return json.loads(
        json.dumps(value, default=lambda item: item.isoformat())
    )


def _date(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def _fetch(
    name: str,
    function: Any,
    status: dict[str, str],
) -> Any | None:
    try:
        result = function()
        status[name] = "fresh"
        return result
    except Exception:
        LOGGER.exception("%s source failed", name)
        status[name] = "stale/unavailable"
        return None


def _snapshot(name: str, value: Any, enabled: bool = True) -> None:
    bucket = os.environ.get("RAW_SNAPSHOT_BUCKET")
    if not enabled or not bucket:
        return
    try:
        S3SnapshotWriter(bucket, os.environ.get("AWS_REGION")).write(
            f"{date.today().isoformat()}/{name}.json",
            _record_dataclass(value) if hasattr(value, "__dataclass_fields__") else value,
        )
    except Exception:
        LOGGER.exception("Could not write %s raw snapshot", name)


def _persist_source(store: Store, key: str, value: Any, source: str) -> None:
    try:
        store.put(key, value)
    except Exception:
        LOGGER.exception("Could not persist %s source data", source)


def _cached_events(raw: list[dict[str, Any]]) -> list[SkiEvent]:
    return [
        SkiEvent(
            title=item["title"],
            start_date=_date(item["start_date"]),
            end_date=_date(item["end_date"]),
            url=item["url"],
            source=item["source"],
        )
        for item in raw
    ]


def _cached_forecast(raw: dict[str, Any]) -> EnsembleForecast:
    return EnsembleForecast(
        [_date(value) for value in raw["dates"]],
        raw["members"],
        raw["source_url"],
    )


def _cached_climatology(raw: dict[str, Any]) -> ArchiveClimatology:
    return ArchiveClimatology(
        [_date(value) for value in raw["dates"]],
        raw["snowfall_cm"],
        raw["source_url"],
    )


def _load_sources(
    config: dict[str, Any],
    store: Store,
    today: date,
    *,
    snapshots_enabled: bool,
) -> tuple[
    dict[str, DepthObservation | None],
    dict[str, EnsembleForecast | None],
    dict[str, ArchiveClimatology | None],
    EnsoObservation | None,
    FxObservation | None,
    list[SkiEvent] | None,
    dict[str, dict[str, str]],
]:
    depths: dict[str, DepthObservation | None] = {}
    forecasts: dict[str, EnsembleForecast | None] = {}
    climatologies: dict[str, ArchiveClimatology | None] = {}
    statuses: dict[str, dict[str, str]] = {}
    season = today.year if today.month >= 10 else today.year - 1
    for key, resort in config["resorts"].items():
        status: dict[str, str] = {}
        depths[key] = _fetch(
            "amedas",
            lambda resort=resort: amedas.fetch_depth(resort["amedas"]),
            status,
        )
        if depths[key]:
            _persist_source(
                store,
                f"observation:depth:{key}",
                {"fetched_at": datetime.now(ZoneInfo(config["timezone_run"])).isoformat(),
                 **_record_dataclass(depths[key])},
                "amedas",
            )
            _snapshot(f"amedas-{key}", depths[key], snapshots_enabled)
        forecast = _fetch(
            "openmeteo_ensemble",
            lambda resort=resort: openmeteo.fetch_ensemble(
                resort["lat"],
                resort["lon"],
                resort["elevation_m"],
                config["snow"]["forecast_horizon_days"],
            ),
            status,
        )
        if forecast:
            forecasts[key] = forecast
            value = {
                "fetched_at": datetime.now(ZoneInfo(config["timezone_run"])).isoformat(),
                **_record_dataclass(forecast),
            }
            _persist_source(store, f"observation:forecast:{key}", value, "openmeteo_ensemble")
            _snapshot(f"forecast-{key}", forecast, snapshots_enabled)
        else:
            cached = store.get(f"observation:forecast:{key}")
            forecasts[key] = _cached_forecast(cached) if cached else None

        climate_key = f"climatology:{key}:{season}"
        cached_climate = store.get(climate_key)
        if cached_climate:
            climatologies[key] = _cached_climatology(cached_climate)
            status["openmeteo_archive"] = "fresh"
        else:
            climate = _fetch(
                "openmeteo_archive",
                lambda resort=resort: openmeteo.fetch_climatology(
                    resort["lat"],
                    resort["lon"],
                    years=config["snow"]["climatology_years"],
                    today=today,
                ),
                status,
            )
            climatologies[key] = climate
            if climate:
                _persist_source(store, climate_key, _record_dataclass(climate), "openmeteo_archive")
                _snapshot(f"climatology-{key}", climate, snapshots_enabled)
        statuses[key] = status

    global_status: dict[str, str] = {}
    enso_observation = _fetch("enso", enso.fetch_enso, global_status)
    if enso_observation:
        _persist_source(store, "observation:enso", _record_dataclass(enso_observation), "enso")
        _snapshot("enso", enso_observation, snapshots_enabled)
    fx_observation = _fetch(
        "fx",
        lambda: fx.fetch_usd_jpy(today, config["yen"]["lookback_days"]),
        global_status,
    )
    if fx_observation:
        _persist_source(store, "observation:fx", _record_dataclass(fx_observation), "fx")
        _snapshot("fx", fx_observation, snapshots_enabled)

    cached_events = store.get("observation:events")
    event_list = _fetch(
        "niseko_events",
        lambda: niseko_events.fetch_events(config["crowds_events"]["nightlife_keywords"], today),
        global_status,
    )
    if event_list is not None:
        _persist_source(
            store,
            "observation:events",
            {
                "fetched_at": datetime.now(ZoneInfo(config["timezone_run"])).isoformat(),
                "events": [_record_dataclass(event) for event in event_list],
            },
            "niseko_events",
        )
        _snapshot("niseko-events", event_list, snapshots_enabled)
    elif cached_events:
        event_list = _cached_events(cached_events["events"])
    for resort_status in statuses.values():
        resort_status.update(global_status)
    return depths, forecasts, climatologies, enso_observation, fx_observation, event_list, statuses


def _refresh_serpapi(
    config: dict[str, Any],
    store: Store,
    departures: list[date],
    today: date,
    *,
    no_serpapi: bool,
    forecasts: dict[str, EnsembleForecast | None] | None = None,
    depths: dict[str, DepthObservation | None] | None = None,
) -> tuple[dict[tuple[str, date], dict[str, Any]], dict[tuple[str, date], dict[str, Any]], dict[str, str]]:
    flight_records: dict[tuple[str, date], dict[str, Any]] = {}
    hotel_records: dict[tuple[str, date], dict[str, Any]] = {}
    status: dict[str, str] = {}
    for key, record in store.scan("observation:flight:"):
        parts = key.split(":")
        flight_records[(parts[-2], date.fromisoformat(parts[-1]))] = record
    for key, record in store.scan("observation:hotel:"):
        parts = key.split(":")
        hotel_records[(parts[-2], date.fromisoformat(parts[-1]))] = record

    api_key = os.environ.get("SERPAPI_API_KEY")
    if no_serpapi or not api_key:
        status["serpapi"] = "skipped" if no_serpapi else "stale/unavailable"
        return flight_records, hotel_records, status

    groups = config["flight_groups"]
    flight_candidates: list[tuple[str, date, str]] = []
    for departure in departures:
        for group_name in groups:
            key = f"observation:flight:{group_name}:{departure.isoformat()}"
            flight_candidates.append((group_name, departure, key))
    flight_stale = {
        key: flight_records.get((group, departure), {})
        for group, departure, key in flight_candidates
    }
    selected_flights = set(stalest_first(
        [(key, None) for _, _, key in flight_candidates],
        flight_stale,
        config["serpapi"]["daily_flight_searches"],
    ))

    checkins: set[tuple[str, date]] = set()
    for departure in departures:
        for resort_key in config["resorts"]:
            checkin = departure + timedelta(days=config["trip"]["hotel_checkin_offset_days"])
            checkins.add((resort_key, checkin))
    hotel_candidates = [
        (resort_key, checkin, f"observation:hotel:{resort_key}:{checkin.isoformat()}")
        for resort_key, checkin in checkins
    ]
    hotel_stale = {
        key: hotel_records.get((resort_key, checkin), {})
        for resort_key, checkin, key in hotel_candidates
    }
    selected_hotels = set(stalest_first(
        [(key, None) for _, _, key in hotel_candidates],
        hotel_stale,
        config["serpapi"]["daily_hotel_searches"],
    ))
    alert_pairs: set[tuple[str, date]] = set()
    for resort_key, forecast in (forecasts or {}).items():
        depth = (depths or {}).get(resort_key)
        if forecast is None or depth is None:
            continue
        for storm in storm_windows(
            forecast, today=today, depth_cm=depth.depth_cm, config=config
        ):
            start = date.fromisoformat(storm["window_start"])
            end = date.fromisoformat(storm["window_end"])
            for departure in departures:
                if departure + timedelta(days=1) <= end and departure + timedelta(days=7) >= start:
                    alert_pairs.add((resort_key, departure))
    extra_limit = config["serpapi"]["alert_refresh_searches"]
    for resort_key, departure in sorted(alert_pairs, key=lambda pair: (pair[1], pair[0])):
        flight_key = f"observation:flight:{config['resorts'][resort_key]['flight_group']}:{departure.isoformat()}"
        if flight_key not in selected_flights:
            selected_flights.add(flight_key)
            extra_limit -= 1
            if extra_limit <= 0:
                break
    extra_limit = config["serpapi"]["alert_refresh_searches"]
    for resort_key, departure in sorted(alert_pairs, key=lambda pair: (pair[1], pair[0])):
        checkin = departure + timedelta(days=config["trip"]["hotel_checkin_offset_days"])
        hotel_key = f"observation:hotel:{resort_key}:{checkin.isoformat()}"
        if hotel_key not in selected_hotels:
            selected_hotels.add(hotel_key)
            extra_limit -= 1
            if extra_limit <= 0:
                break

    authorize = lambda: reserve_search(
        store,
        api_key=api_key,
        monthly_cap=config["serpapi"]["monthly_cap"],
        today=today,
    )
    for group, departure, key in flight_candidates:
        if key not in selected_flights:
            continue
        try:
            observation = fetch_flights(
                api_key=api_key,
                departure_id=",".join(config["origins"]),
                arrival_id=groups[group]["arrival_id"],
                departure=departure,
                return_date=departure + timedelta(days=config["trip"]["return_offset_days"]),
                adults=config["party_adults"],
                authorize=authorize,
            )
            record = {
                "fetched_at": datetime.now(ZoneInfo(config["timezone_run"])).isoformat(),
                **_record_dataclass(observation),
            }
            store.put(key, record)
            flight_records[(group, departure)] = record
        except Exception as error:
            LOGGER.error(
                "Flight quote or budget check failed for %s on %s: %s",
                group,
                departure,
                redact_api_key(str(error)),
            )
            status["serpapi_flights"] = "stale/unavailable"
    for resort_key, checkin, key in hotel_candidates:
        if key not in selected_hotels:
            continue
        resort = config["resorts"][resort_key]
        try:
            observation = fetch_hotels(
                api_key=api_key,
                query=resort["hotel_query"],
                checkin=checkin,
                checkout=checkin + timedelta(days=config["trip"]["hotel_nights"]),
                adults=config["party_adults"],
                authorize=authorize,
            )
            record = {
                "fetched_at": datetime.now(ZoneInfo(config["timezone_run"])).isoformat(),
                **_record_dataclass(observation),
            }
            store.put(key, record)
            hotel_records[(resort_key, checkin)] = record
        except Exception as error:
            LOGGER.error(
                "Hotel quote or budget check failed for %s on %s: %s",
                resort_key,
                checkin,
                redact_api_key(str(error)),
            )
            status["serpapi_hotels"] = "stale/unavailable"
    if not status:
        status["serpapi"] = "fresh"
    return flight_records, hotel_records, status


def _record_events(record: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not record:
        return []
    return [
        {
            "title": event.title,
            "start_date": event.start_date.isoformat(),
            "end_date": event.end_date.isoformat(),
            "url": event.url,
            "source": event.source,
        }
        for event in record
    ]


def run_signal(
    *,
    dry_run: bool = False,
    force_digest: bool = False,
    no_serpapi: bool = False,
    config: dict[str, Any] | None = None,
    store: Store | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    store = store or (
        LocalStore(os.environ.get("LOCAL_DATA_DIR", ".localdata"))
        if dry_run
        else configured_store()
    )
    today = run_date(config, now)
    departures = candidate_departures(today, config)
    depths, forecasts, climatologies, enso_observation, fx_observation, events, statuses = _load_sources(
        config, store, today, snapshots_enabled=not dry_run
    )
    flight_records, hotel_records, serp_status = _refresh_serpapi(
        config,
        store,
        departures,
        today,
        no_serpapi=no_serpapi,
        forecasts={
            key: forecast
            for key, forecast in forecasts.items()
            if statuses[key].get("openmeteo_ensemble") == "fresh"
        },
        depths=depths,
    )
    for source_status in statuses.values():
        source_status.update(serp_status)

    anomaly = enso_observation.anomaly if enso_observation else None
    event_values = events
    combos: list[dict[str, Any]] = []
    depth_values: dict[str, float | None] = {}
    horizon_medians: dict[str, float | None] = {}
    for resort_key, resort in config["resorts"].items():
        observation = depths[resort_key]
        depth_cm = observation.depth_cm if observation else None
        depth_values[resort_key] = depth_cm
        status = statuses[resort_key]
        forecast = forecasts[resort_key]
        climate = climatologies[resort_key]
        horizon_median = None
        horizon_dates: tuple[str, str] | None = None
        horizon_day_count = 0
        if forecast is not None and status.get("openmeteo_ensemble") == "fresh":
            try:
                horizon_median = forecast_window_median(
                    forecast, min(forecast.dates), max(forecast.dates)
                )
                horizon_dates = (min(forecast.dates).isoformat(), max(forecast.dates).isoformat())
                horizon_day_count = len(forecast.dates)
            except Exception:
                LOGGER.exception("Could not summarize forecast horizon for %s", resort_key)
                status["openmeteo_ensemble"] = "stale/unavailable"
        horizon_medians[resort_key] = horizon_median
        for departure in departures:
            trip_start = departure + timedelta(days=1)
            trip_end = departure + timedelta(days=7)
            in_horizon = snow_window_in_horizon(
                departure,
                max(forecast.dates) if forecast is not None and forecast.dates else None,
            )
            eligible = depth_cm is None or base_eligible(
                depth_cm,
                config,
                in_horizon=in_horizon,
            )
            flight_group = resort["flight_group"]
            flight_record = flight_records.get((flight_group, departure))
            if not flight_record:
                flight_record = store.get(
                    f"observation:flight:{flight_group}:{departure.isoformat()}"
                )
            flight = flight_record or {}
            flight_value = flight_score(
                flight.get("price"),
                tuple(flight["price_range"]) if flight.get("price_range") else None,
                flight.get("price_level"),
                config,
            )
            checkin = departure + timedelta(days=config["trip"]["hotel_checkin_offset_days"])
            hotel_record = hotel_records.get((resort_key, checkin)) or store.get(
                f"observation:hotel:{resort_key}:{checkin.isoformat()}"
            )
            all_hotel_rows = store.scan(f"observation:hotel:{resort_key}:")
            hotel_prices = [
                row["lowest_total"]
                for _, row in all_hotel_rows
                if row.get("lowest_total") is not None
            ]
            lodging_value = lodging_score(
                hotel_record.get("lowest_total") if hotel_record else None,
                hotel_prices,
                config,
            )
            crowd_value, crowd_details = crowds_events_score(
                resort_key, departure, event_values, config
            )

            details: dict[str, Any] = {
                "base": 0.5,
                "forecast": 0.5,
                "climatology": 0.5,
                "crowd": crowd_details["crowd"],
                "events": crowd_details["events"],
                "crowd_daily_levels": crowd_details["daily_levels"],
                "snow_window_median_cm": None,
                "horizon_median_cm": horizon_median,
                "horizon_dates": horizon_dates,
                "horizon_day_count": horizon_day_count,
                "enso_class": enso_class(anomaly, config) if anomaly is not None else "neutral",
            }
            snow_value = 0.5
            if depth_cm is not None:
                details["base"] = base_score(depth_cm, config)
            if not eligible:
                snow_value = 0.0
            elif in_horizon and forecast is not None:
                if status.get("openmeteo_ensemble") == "fresh":
                    try:
                        snow_value, snow_details = snow_score(
                            depth_cm=depth_cm,
                            forecast=forecast,
                            climatology=climate or ArchiveClimatology([], [], ""),
                            anomaly=anomaly or 0.0,
                            region=resort["region"],
                            departure=departure,
                            config=config,
                        )
                        details.update(snow_details)
                    except Exception:
                        LOGGER.exception("Forecast scoring failed for %s / %s", resort_key, departure)
                        status["openmeteo_ensemble"] = "stale/unavailable"
            elif (
                climate is not None
                and anomaly is not None
                and status.get("openmeteo_archive") == "fresh"
                and status.get("enso") == "fresh"
            ):
                try:
                    snow_value, snow_details = snow_score(
                        depth_cm=depth_cm,
                        forecast=forecast,
                        climatology=climate,
                        anomaly=anomaly,
                        region=resort["region"],
                        departure=departure,
                        config=config,
                    )
                    details.update(snow_details)
                except Exception:
                    LOGGER.exception("Climatology scoring failed for %s / %s", resort_key, departure)
            if forecast is None:
                status["openmeteo_ensemble"] = "stale/unavailable"
            if depth_cm is None and "base" not in details:
                details["base"] = 0.5

            fx_value = (
                yen_score(fx_observation.rate, fx_observation.p10, fx_observation.p90)
                if fx_observation
                else 0.5
            )
            components = {
                "snow": snow_value,
                "crowds_events": crowd_value,
                "flights": flight_value,
                "lodging": lodging_value,
                "yen": fx_value,
            }
            score = total_score(components, config, eligible=eligible)
            stale_sources = sorted(
                name for name, value in status.items() if value != "fresh"
            )
            combo = {
                "resort_key": resort_key,
                "resort": resort["name"],
                "departure": departure.isoformat(),
                "trip_start": trip_start.isoformat(),
                "trip_end": trip_end.isoformat(),
                "eligible": eligible,
                "depth_cm": depth_cm,
                "base_gate_cm": config["snow"]["base_gate_cm"],
                "components": components,
                "details": details,
                "total_score": score,
                "flight": {
                    "price": flight.get("price"),
                    "price_range": flight.get("price_range"),
                    "price_level": flight.get("price_level"),
                    "url": flight.get("google_flights_url"),
                },
                "hotels": hotel_record.get("properties", []) if hotel_record else [],
                "events": _record_events(event_values) if resort.get("events") else [],
                "source_status": dict(status),
                "stale_sources": stale_sources,
            }
            combos.append(combo)

    forecast_map = {
        key: value
        for key, value in forecasts.items()
        if value is not None and statuses[key].get("openmeteo_ensemble") == "fresh"
    }
    storm_depths = {
        key: value for key, value in depth_values.items() if value is not None
    }
    alerts = select_alerts(
        combos,
        forecast_map,
        storm_depths,
        today=today,
        config=config,
        store=store,
        force_digest=force_digest,
    )
    for alert in alerts:
        alert["resort"] = config["resorts"].get(alert.get("resort_key"), {}).get(
            "name", alert.get("resort_key", "All resorts")
        )
    html_document = render_email(
        combos,
        alerts,
        today=today,
        weights=config["weights"],
        enso_anomaly=anomaly,
        enso_class=enso_class(anomaly, config) if anomaly is not None else "neutral",
        usd_jpy=fx_observation.rate if fx_observation else None,
        digest=any(alert["type"] == "weekly_digest" for alert in alerts),
    )
    if dry_run:
        output_path = write_dry_run(html_document, today)
        LOGGER.info("Dry-run email written to %s", output_path)
        record_sent_alerts(alerts, today=today, store=store)
    elif alerts:
        send_email(
            html_document,
            to=config["email_to"],
            source=config["email_from"],
            subject=f"Japan ski trip signal — {today.isoformat()}",
        )
        record_sent_alerts(alerts, today=today, store=store)
        output_path = None
    else:
        output_path = None
    return {
        "today": today.isoformat(),
        "combos": combos,
        "alerts": alerts,
        "html_path": str(output_path) if output_path else None,
        "depths": {key: depth_values[key] for key in depth_values},
        "depths_by_station": {
            config["resorts"][key]["amedas_name"]: depth for key, depth in depth_values.items()
        },
        "forecast_horizon_median_cm": horizon_medians,
        "enso_anomaly": anomaly,
        "usd_jpy": fx_observation.rate if fx_observation else None,
        "event_count": len(event_values),
    }
