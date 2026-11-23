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
        <div class="event-description">A barbecue gathering. Location: The DJ Bar Lounge</div>
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

def test_yearless_event_date_rolls_forward_after_sixty_days():
    events = parse_events(
        """
        <li class="event">
          <h3>Snow Bar Night</h3>
          <div class="event-description">Jan 15</div>
        </li>
        """,
        source_url="https://example.com/events/",
        keywords=["bar"],
        today=date(2026, 12, 10),
    )

    assert len(events) == 1
    assert events[0].start_date == date(2027, 1, 15)


def test_event_datetime_year_takes_precedence_over_visible_yearless_date():
    events = parse_events(
        """
        <li class="event">
          <h3>Snow Bar Night</h3>
          <time datetime="2027-02-10">Jan 15</time>
        </li>
        """,
        source_url="https://example.com/events/",
        keywords=["bar"],
        today=date(2026, 12, 10),
    )

    assert len(events) == 1
    assert events[0].start_date == date(2027, 2, 10)


def test_yearless_range_uses_time_tag_year_and_wraps_forward():
    events = parse_events(
        """
        <li class="event">
          <h3>New Year Bar Night</h3>
          <div class="event-description">December 31 – January 1</div>
          <time datetime="2026-12-31">December 31</time>
        </li>
        """,
        source_url="https://example.com/events/",
        keywords=["bar"],
        today=date(2026, 4, 15),
    )

    assert len(events) == 1
    assert events[0].start_date == date(2026, 12, 31)
    assert events[0].end_date == date(2027, 1, 1)


def test_matching_time_tag_anchors_yearless_range_backwards():
    events = parse_events(
        """
        <li class="event">
          <h3>New Year Bar Night</h3>
          <div class="event-description">December 31 – January 1</div>
          <time datetime="2027-01-01">January 1</time>
        </li>
        """,
        source_url="https://example.com/events/",
        keywords=["bar"],
        today=date(2026, 4, 15),
    )

    assert len(events) == 1
    assert events[0].start_date == date(2026, 12, 31)
    assert events[0].end_date == date(2027, 1, 1)


def test_yearless_date_before_explicit_year_uses_the_explicit_year():
    events = parse_events(
        """
        <li class="event">
          <h3>Snow Bar Night</h3>
          <div class="event-description">January 1 – January 5, 2026</div>
        </li>
        """,
        source_url="https://example.com/events/",
        keywords=["bar"],
        today=date(2026, 4, 15),
    )

    assert len(events) == 1
    assert events[0].start_date == date(2026, 1, 1)
    assert events[0].end_date == date(2026, 1, 5)


def test_yearless_date_before_explicit_next_year_wraps_backward():
    events = parse_events(
        """
        <li class="event">
          <h3>New Year Bar Night</h3>
          <div class="event-description">Dec 30 – Jan 2, 2027</div>
        </li>
        """,
        source_url="https://example.com/events/",
        keywords=["bar"],
        today=date(2026, 4, 15),
    )

    assert len(events) == 1
    assert events[0].start_date == date(2026, 12, 30)
    assert events[0].end_date == date(2027, 1, 2)


def test_matching_yearless_text_and_time_tag_date_collapse_to_one_date():
    events = parse_events(
        """
        <li class="event">
          <h3>Snow Bar Night</h3>
          <time datetime="2027-02-10">February 10</time>
        </li>
        """,
        source_url="https://example.com/events/",
        keywords=["bar"],
        today=date(2026, 4, 15),
    )

    assert len(events) == 1
    assert events[0].start_date == date(2027, 2, 10)
    assert events[0].end_date == date(2027, 2, 10)
def test_partial_time_datetime_uses_date_from_visible_text():
    events = parse_events(
        """
        <li class="event">
          <h3>Snow Bar Night</h3>
          <time datetime="2026-12">December 25, 2026</time>
        </li>
        """,
        source_url="https://example.com/events/",
        keywords=["bar"],
        today=date(2026, 4, 15),
    )

    assert len(events) == 1
    assert events[0].start_date == date(2026, 12, 25)
    assert events[0].end_date == date(2026, 12, 25)
def test_partial_time_datetime_does_not_duplicate_a_text_date():
    events = parse_events(
        """
        <li class="event">
          <h3>Snow Bar Night</h3>
          <div class="event-description">December 25 – December 31</div>
          <time datetime="2026-12">December 25</time>
        </li>
        """,
        source_url="https://example.com/events/",
        keywords=["bar"],
        today=date(2026, 12, 1),
    )

    assert len(events) == 1
    assert events[0].start_date == date(2026, 12, 25)
    assert events[0].end_date == date(2026, 12, 31)


def test_successful_empty_fetch_and_unavailable_events_have_distinct_scores():
    config = load_config()
    trip_days = [date(2026, 12, 25)]
    assert events_score([], trip_days, config) == 0
    assert events_score(None, trip_days, config) == 0.5
