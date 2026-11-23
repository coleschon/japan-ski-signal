from datetime import date

from ski_signal.email import render_email


WEIGHTS = {
    "snow": 0.45,
    "crowds_events": 0.20,
    "flights": 0.20,
    "lodging": 0.10,
    "yen": 0.05,
}


def make_combo(index, *, eligible=True, source_status=None, details=None):
    departure = f"2026-12-{4 + index:02d}"
    return {
        "resort_key": f"resort-{index}",
        "resort": f"Resort {index}",
        "departure": departure,
        "trip_start": departure,
        "trip_end": departure,
        "eligible": eligible,
        "depth_cm": 21 if not eligible else 60,
        "base_gate_cm": 30,
        "total_score": 1.0 - index / 10,
        "components": {
            "snow": 0.4,
            "crowds_events": 0.5,
            "flights": 0.6,
            "lodging": 0.7,
            "yen": 0.8,
        },
        "details": details or {
            "base": 0.2,
            "forecast": 0.5,
            "climatology": 0.75,
            "crowd": 0.5,
            "events": 0.5,
            "horizon_day_count": 15,
            "horizon_dates": ["2026-11-23", "2026-12-07"],
            "horizon_median_cm": 25,
            "snow_window_median_cm": None,
        },
        "source_status": source_status or {"amedas": "fresh"},
        "flight": {},
        "hotels": [],
        "events": [],
    }


def test_digest_compacts_ranked_table_and_limits_detail_cards():
    combos = [make_combo(index) for index in range(7)]
    combos[6]["source_status"] = {"serpapi": "skipped"}
    combos[6]["details"].update(
        {
            "climatology_raw": 0.8,
            "climatology": 0.76,
            "climatology_factor": 0.95,
            "enso_class": "strong_el_nino",
        }
    )
    combos[6]["eligible"] = False
    combos[6]["depth_cm"] = 21
    storm = {
        "type": "storm",
        "resort_key": "resort-6",
        "resort": "Resort 6",
        "window_start": combos[6]["trip_start"],
        "window_end": combos[6]["trip_end"],
        "lead_days": 8,
        "median_cm": 55,
    }
    document = render_email(
        combos,
        [storm, {"type": "weekly_digest", "date": "2026-11-22"}],
        today=date(2026, 11, 22),
        weights=WEIGHTS,
        enso_anomaly=1.97,
        enso_class="strong_el_nino",
        usd_jpy=158.64,
        digest=True,
    )
    assert '<meta charset="utf-8">' in document
    assert all(
        f"<th>{heading}</th>" in document
        for heading in (
            "Resort",
            "Depart",
            "Total",
            "Snow",
            "Crowds/events",
            "Flights",
            "Lodging",
            "Yen",
            "Base cm",
        )
    )
    assert "Dec 4" in document
    assert "ineligible (base 21 cm &lt; 30 cm)" in document
    assert (
        "Beyond forecast range: climatology 0.800 "
        "(ENSO strong_el_nino ×0.95; adjusted 0.760)." in document
    )
    assert "Trip snow-window median:" not in document
    assert "Unavailable/stale: SerpApi (skipped)" in document
    assert (
        "Weights: snow 45% · crowds/events 20% · flights 20% · lodging 10% · yen 5%"
        in document
    )
    assert "Sources:" not in document
    assert document.count("<section>") == 6
    assert "white-space:nowrap" in document


def test_fresh_sources_omit_unavailable_line():
    document = render_email(
        [make_combo(0)],
        [],
        today=date(2026, 11, 22),
        weights=WEIGHTS,
        enso_anomaly=None,
        enso_class="neutral",
        usd_jpy=None,
        digest=False,
    )
    assert "Unavailable/stale:" not in document
