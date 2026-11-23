from datetime import date, datetime, timedelta
from statistics import median
from typing import Any

from ski_signal.models import EnsembleForecast
from ski_signal.storage import Store


def storm_windows(
    forecast: EnsembleForecast,
    *,
    today: date,
    depth_cm: float,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    settings = config["alerts"]["storm"]
    if depth_cm < settings["min_base_cm"]:
        return []
    date_index = {day: index for index, day in enumerate(forecast.dates)}
    storms = []
    for start in forecast.dates:
        lead = (start - today).days
        if not settings["lead_days_min"] <= lead <= settings["lead_days_max"]:
            continue
        days = [start + timedelta(days=offset) for offset in range(3)]
        if any(day not in date_index for day in days):
            continue
        totals = []
        for member in forecast.members.values():
            indexes = [date_index[day] for day in days]
            if any(index >= len(member) or member[index] is None for index in indexes):
                continue
            totals.append(sum(float(member[index]) for index in indexes))
        if not totals:
            continue
        storm_median = float(median(totals))
        member_fraction = sum(value >= settings["member_frac_cm"] for value in totals) / len(totals)
        if storm_median >= settings["median_cm"] and member_fraction >= settings["member_frac"]:
            storms.append(
                {
                    "window_start": start.isoformat(),
                    "window_end": days[-1].isoformat(),
                    "lead_days": lead,
                    "median_cm": storm_median,
                    "member_fraction": member_fraction,
                    "base_depth_cm": depth_cm,
                }
            )
    return storms


def select_alerts(
    combos: list[dict[str, Any]],
    forecasts: dict[str, EnsembleForecast],
    depths: dict[str, float | None],
    *,
    today: date,
    config: dict[str, Any],
    store: Store,
    force_digest: bool = False,
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    storm_config = config["alerts"]["storm"]
    for resort, forecast in forecasts.items():
        depth = depths.get(resort)
        if depth is None:
            continue
        storms = storm_windows(forecast, today=today, depth_cm=depth, config=config)
        if not storms:
            continue
        storm = max(storms, key=lambda item: item["median_cm"])
        dedupe_key = f"alert:storm:{resort}"
        prior = store.get(dedupe_key)
        should_send = True
        if prior:
            alerted_at = date.fromisoformat(prior["alerted_at"])
            within_window = (today - alerted_at).days < storm_config["dedupe_days"]
            growth = storm["median_cm"] >= prior["median_cm"] * (1 + storm_config["dedupe_growth"])
            should_send = not within_window or growth
        if should_send:
            alerts.append({"type": "storm", "resort_key": resort, **storm})

    for combo in combos:
        if not combo["eligible"] or combo["total_score"] < config["alerts"]["book_now_score"]:
            continue
        dedupe_key = f"alert:book-now:{combo['resort_key']}:{combo['departure']}"
        if not store.get(dedupe_key):
            alerts.append(
                {
                    "type": "book_now",
                    "resort_key": combo["resort_key"],
                    "departure": combo["departure"],
                    "score": combo["total_score"],
                }
            )

    weekday = config["alerts"]["weekly_digest_weekday"]
    expected_weekday = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}[
        weekday
    ]
    digest_key = f"alert:digest:{today.isoformat()}"
    if today.weekday() == expected_weekday or force_digest:
        if force_digest or not store.get(digest_key):
            alerts.append({"type": "weekly_digest", "date": today.isoformat()})
    return alerts


def record_sent_alerts(
    alerts: list[dict[str, Any]],
    *,
    today: date,
    store: Store,
) -> None:
    for alert in alerts:
        if alert["type"] == "storm":
            key = f"alert:storm:{alert['resort_key']}"
            value = {
                "alerted_at": today.isoformat(),
                "median_cm": alert["median_cm"],
            }
        elif alert["type"] == "book_now":
            key = f"alert:book-now:{alert['resort_key']}:{alert['departure']}"
            value = {"alerted_at": today.isoformat()}
        elif alert["type"] == "weekly_digest":
            key = f"alert:digest:{today.isoformat()}"
            value = {"sent_at": datetime.now().isoformat()}
        else:
            continue
        store.put(key, value)
