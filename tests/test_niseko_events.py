from datetime import date
from pathlib import Path

from ski_signal.config import load_config
from ski_signal.scoring import events_score
from ski_signal.sources.niseko_events import parse_events


def test_niseko_village_fixture_parses_six_dated_events():
    config = load_config()
    source = "https://www.niseko-village.com/events/"
    html = (Path(__file__).parent / "fixtures" / "niseko-village-events.html").read_text(
        encoding="utf-8"
    )
    events = parse_events(
        html,
        source_url=source,
        keywords=config["crowds_events"]["nightlife_keywords"],
        today=date(2026, 11, 22),
    )
    assert len(events) == 6
    fireworks = next(event for event in events if event.title == "Christmas Day Fireworks")
    assert fireworks.start_date == date(2026, 12, 25)
    assert fireworks.end_date == date(2026, 12, 25)
    assert all(event.start_date <= event.end_date for event in events)


def test_nightlife_keywords_use_title_and_description_only_with_word_boundaries():
    config = load_config()
    html = """
    <ul>
      <li class="event">
        <h3>Barbecue Social</h3>
        <address>DJ Bar</address>
        <time datetime="2026-12-01">December 1, 2026</time>
      </li>
      <li class="event">
        <h3>Winter Gathering</h3>
        <div class="event-description">Live music on the mountain</div>
        <address>Barbecue Lounge</address>
        <time datetime="2026-12-02">December 2, 2026</time>
      </li>
    </ul>
    """

    events = parse_events(
        html,
        source_url="https://example.com/events/",
        keywords=config["crowds_events"]["nightlife_keywords"],
        today=date(2026, 11, 22),
    )

    assert [event.title for event in events] == ["Winter Gathering"]


def test_successful_empty_fetch_and_unavailable_events_have_distinct_scores():
    config = load_config()
    trip_days = [date(2026, 12, 25)]
    assert events_score([], trip_days, config) == 0
    assert events_score(None, trip_days, config) == 0.5
