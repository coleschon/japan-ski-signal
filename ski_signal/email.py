import html
import os
from datetime import date
from pathlib import Path
from typing import Any


SOURCE_LABELS = {
    "amedas": "AMeDAS",
    "openmeteo_ensemble": "Open-Meteo forecast",
    "openmeteo_archive": "Open-Meteo climatology",
    "enso": "CPC ENSO",
    "fx": "Frankfurter USD/JPY",
    "niseko_events": "Niseko Village events",
    "serpapi": "SerpApi",
    "serpapi_flights": "SerpApi flights",
    "serpapi_hotels": "SerpApi hotels",
}


def _money(value: Any) -> str:
    return "Unknown" if value is None else f"${float(value):,.0f}"


def _number(value: Any) -> str:
    return "Unknown" if value is None else f"{float(value):g}"


def _link(url: str | None, label: str) -> str:
    if not url:
        return html.escape(label)
    return f'<a href="{html.escape(url, quote=True)}">{html.escape(label)}</a>'


def _depart_label(value: str) -> str:
    departure = date.fromisoformat(value)
    return f"{departure.strftime('%b')} {departure.day}"


def _matching_alerts(combo: dict[str, Any], alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matching = []
    for alert in alerts:
        if alert.get("resort_key") != combo["resort_key"]:
            continue
        if alert["type"] == "book_now" and alert.get("departure") == combo["departure"]:
            matching.append(alert)
        elif alert["type"] == "storm":
            if (
                alert["window_start"] <= combo["trip_end"]
                and alert["window_end"] >= combo["trip_start"]
            ):
                matching.append(alert)
    return matching


def _unavailable_sources(source_status: dict[str, str]) -> list[str]:
    labels = []
    for name, status in source_status.items():
        if status == "fresh":
            continue
        label = SOURCE_LABELS.get(name, name.replace("_", " ").title())
        if status == "skipped":
            label += " (skipped)"
        labels.append(label)
    return labels


def render_email(
    combos: list[dict[str, Any]],
    alerts: list[dict[str, Any]],
    *,
    today: date,
    enso_anomaly: float | None,
    enso_class: str,
    usd_jpy: float | None,
    digest: bool,
) -> str:
    ranked = sorted(combos, key=lambda combo: combo["total_score"], reverse=True)
    alert_text = []
    for alert in alerts:
        if alert["type"] == "storm":
            alert_text.append(
                f'{html.escape(alert["resort"])}: {alert["median_cm"]:.1f} cm median over '
                f'{alert["window_start"]}–{alert["window_end"]} (lead {alert["lead_days"]} days)'
            )
        elif alert["type"] == "book_now":
            alert_text.append(
                f'{html.escape(alert["resort"])} departing {alert["departure"]}: '
                f'book-now score {alert["score"]:.3f}'
            )
        elif alert["type"] == "weekly_digest":
            alert_text.append("Weekly digest scheduled for today.")
    if not alert_text:
        alert_text.append("No new storm or book-now alerts.")
    rows = []
    for combo in ranked:
        components = combo["components"]
        score_cells = "".join(
            f'<td class="score">{components[key]:.2f}</td>'
            for key in ("snow", "crowds_events", "flights", "lodging", "yen")
        )
        depth = combo.get("depth_cm")
        gate = combo.get("base_gate_cm", 30)
        eligibility = (
            f'<small class="ineligible">ineligible (base {_number(depth)} cm '
            f'&lt; {_number(gate)} cm)</small>'
            if not combo["eligible"]
            else ""
        )
        rows.append(
            f'<tr><td class="resort">{html.escape(combo["resort"])}{eligibility}</td>'
            f'<td class="date">{_depart_label(combo["departure"])}</td>'
            f'<td class="score"><strong>{combo["total_score"]:.2f}</strong></td>{score_cells}'
            f'<td class="base">{_number(depth)}</td></tr>'
        )
    cards = []
    top_combos = {(combo["resort_key"], combo["departure"]) for combo in ranked[:5]}
    for combo in ranked:
        matching_alerts = _matching_alerts(combo, alerts)
        if (combo["resort_key"], combo["departure"]) not in top_combos and not matching_alerts:
            continue
        depth = combo.get("depth_cm")
        details = combo["details"]
        fare = combo.get("flight") or {}
        hotels = combo.get("hotels") or []
        hotels_html = "".join(
            f"<li>{_link(hotel.get('url'), hotel.get('name', 'Hotel'))} — {_money(hotel.get('price'))}</li>"
            for hotel in hotels[:3]
        ) or "<li>No hotel quote available.</li>"
        event_rows = [
            event
            for event in combo.get("events", [])
            if event["start_date"] <= combo["trip_end"] and event["end_date"] >= combo["trip_start"]
        ]
        event_html = "".join(
            f"<li>{_link(event.get('url'), event['title'])} "
            f"({event['start_date']}–{event['end_date']})</li>"
            for event in event_rows
        ) or "<li>No matching Niseko events overlap this trip.</li>"
        reasons = [
            html.escape(alert["type"].replace("_", " ").title())
            for alert in matching_alerts
        ]
        reason_text = ", ".join(reasons) if reasons else (
            "Included in the weekly ranked digest." if digest else "Scored for this run."
        )
        horizon_dates = (
            "–".join(details["horizon_dates"])
            if details.get("horizon_dates")
            else "unavailable"
        )
        forecast_text = (
            f"Open-Meteo {details.get('horizon_day_count', 0)}-day forecast "
            f"({horizon_dates}): {_number(details.get('horizon_median_cm'))} cm median total."
        )
        snow_window_median = details.get("snow_window_median_cm")
        if snow_window_median is not None:
            forecast_text += f" Trip snow-window median: {_number(snow_window_median)} cm."
        elif details.get("climatology_raw") is not None:
            forecast_text += (
                f" Beyond forecast range: climatology {details['climatology_raw']:.3f} "
                f"(ENSO {html.escape(details['enso_class'])} "
                f"×{details['climatology_factor']:g}; adjusted "
                f"{details['climatology']:.3f})."
            )
        stale_sources = _unavailable_sources(combo.get("source_status", {}))
        stale_line = (
            "<p>Unavailable/stale: "
            + html.escape(", ".join(stale_sources))
            + "</p>"
            if stale_sources
            else ""
        )
        cards.append(
            f"<section><h3>{html.escape(combo['resort'])} — departure "
            f'<span class="date">{html.escape(_depart_label(combo["departure"]))}</span></h3>'
            f"<p><b>Total {combo['total_score']:.3f}</b> · {reason_text}</p>"
            f"<p>AMeDAS depth: {_number(depth)} cm; source credit: 出典：気象庁ホームページ</p>"
            f"<p>Snow: base {details.get('base', 0.5):.3f}, forecast "
            f"{details.get('forecast', 0.5):.3f}, climatology {details.get('climatology', 0.5):.3f}; "
            f"crowd {details.get('crowd', 0.5):.3f}, events {details.get('events', 0.5):.3f}</p>"
            f"<p>{forecast_text}</p>"
            f"<p>Best fare: {_link(fare.get('url'), _money(fare.get('price')))}. "
            f"Top hotels:</p><ul>{hotels_html}</ul>"
            f"<p>Niseko nightlife events overlapping trip: </p><ul>{event_html}</ul>"
            f"{stale_line}"
            "</section>"
        )
    enso_note = (
        "Unavailable"
        if enso_anomaly is None
        else f"latest anomaly {enso_anomaly:.2f} ({html.escape(enso_class)})"
    )
    heading = "Weekly Japan ski trip signal" if digest else "Japan ski trip alert"
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{margin:0;background:#f1f5f9;color:#172033;font:16px/1.5 Arial,sans-serif}}
.wrap{{max-width:900px;margin:auto;padding:16px}}header,section,.table{{background:#fff;border-radius:10px;padding:16px;margin:12px 0}}
h1,h2,h3{{color:#123b5d}}.table{{overflow-x:auto}}
.ranked-table{{width:100%;table-layout:fixed;border-collapse:collapse;font-size:11px}}
.ranked-table th,.ranked-table td{{padding:5px 3px;border-bottom:1px solid #dbe3ea;text-align:left}}
.ranked-table th{{background:#e9f1f6;white-space:nowrap;font-size:10px}}
.date{{white-space:nowrap}}
.ranked-table .resort{{overflow-wrap:anywhere}}
.ranked-table .score,.ranked-table .base{{white-space:nowrap}}
.ranked-table .score,.ranked-table .base{{text-align:right}}
a{{color:#075985}}small{{color:#a33}}.ineligible{{display:block}}
@media(max-width:620px){{.wrap{{padding:8px}}header,section,.table{{padding:8px}}
.ranked-table{{font-size:8px}}.ranked-table th{{font-size:7.5px}}
.ranked-table th,.ranked-table td{{padding:3px 1px}}}}
</style></head><body><main class="wrap">
<header><h1>{heading}</h1><p>Run date: {today.isoformat()} · ENSO: {enso_note} · USD/JPY: {_number(usd_jpy)}</p>
<h2>Why this fired</h2><ul>{"".join(f"<li>{item}</li>" for item in alert_text)}</ul></header>
<div class="table"><h2>Ranked combinations</h2><table class="ranked-table"><colgroup>
<col style="width:19%"><col style="width:11%"><col style="width:9%"><col style="width:9%">
<col style="width:14%"><col style="width:9%"><col style="width:10%"><col style="width:8%">
<col style="width:11%"></colgroup><thead><tr><th>Resort</th><th>Depart</th>
<th>Total</th><th>Snow</th><th>Crowds/events</th><th>Flights</th><th>Lodging</th><th>Yen</th><th>Base cm</th>
</tr></thead><tbody>{"".join(rows)}</tbody></table></div>
{"".join(cards)}
</main></body></html>"""


def write_dry_run(html_document: str, today: date) -> Path:
    output = Path("out")
    output.mkdir(parents=True, exist_ok=True)
    path = output / f"japan-ski-signal-{today.isoformat()}.html"
    path.write_text(html_document, encoding="utf-8")
    return path


def send_email(html_document: str, *, to: str, source: str, subject: str) -> None:
    import boto3

    boto3.client("ses", region_name=os.environ.get("AWS_REGION")).send_email(
        Source=source,
        Destination={"ToAddresses": [to]},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {"Html": {"Data": html_document, "Charset": "UTF-8"}},
        },
    )
