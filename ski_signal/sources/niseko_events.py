import re
from datetime import date, timedelta
from typing import Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ski_signal.models import SkiEvent
from ski_signal.sources.common import get_text


SITE = "https://www.niseko-village.com/events/"
MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
MONTHS = {
    month.lower(): index for index, month in enumerate(MONTH_NAMES, start=1)
}
MONTHS.update(
    {month[:3].lower(): index for index, month in enumerate(MONTH_NAMES, start=1)}
)
MONTH_PATTERN = "|".join(sorted(MONTHS, key=len, reverse=True))
DATE_PATTERNS = (
    re.compile(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b"),
    re.compile(rf"\b({MONTH_PATTERN})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?[,]?\s*(20\d{{2}})?\b", re.I),
    re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({MONTH_PATTERN})\.?[,]?\s*(20\d{{2}})?\b", re.I),
)


def _date_parts(text: str) -> list[tuple[int, int, int | None]]:
    found: list[tuple[int, int, int, int | None]] = []
    for pattern_index, pattern in enumerate(DATE_PATTERNS):
        for match in pattern.finditer(text):
            groups = match.groups()
            try:
                if pattern_index == 0:
                    year, month, day = map(int, groups)
                elif pattern_index == 1:
                    month, day, year = groups
                    month = MONTHS[month.lower()]
                    year = int(year) if year else None
                    day = int(day)
                else:
                    day, month, year = groups
                    month = MONTHS[month.lower()]
                    year = int(year) if year else None
                    day = int(day)
                date(year or 2000, month, day)
                found.append((match.start(), month, day, year))
            except (ValueError, KeyError):
                continue
    return [(month, day, year) for _, month, day, year in sorted(found)]


def _date_in_year(month: int, day: int, year: int, direction: int) -> date:
    for offset in range(8):
        try:
            return date(year + direction * offset, month, day)
        except ValueError:
            if (month, day) != (2, 29):
                raise
    raise ValueError(f"No valid year for {month}-{day} near {year}")


def _assign_text_date_years(
    parts: list[tuple[int, int, int | None]],
    time_dates: list[date],
    today: date,
) -> list[date]:
    if not parts:
        return []

    explicit_indices = [
        index for index, (_, _, year) in enumerate(parts) if year is not None
    ]
    assigned: list[date | None] = [None] * len(parts)
    if explicit_indices:
        anchor = explicit_indices[0]
        month, day, year = parts[anchor]
        assigned[anchor] = date(year, month, day)
        for index in range(anchor - 1, -1, -1):
            month, day, _ = parts[index]
            next_date = assigned[index + 1]
            candidate = _date_in_year(month, day, next_date.year, -1)
            if candidate > next_date:
                candidate = _date_in_year(month, day, next_date.year - 1, -1)
            assigned[index] = candidate
        previous = assigned[anchor]
        for index in range(anchor + 1, len(parts)):
            month, day, year = parts[index]
            if year is None:
                candidate = _date_in_year(month, day, previous.year, 1)
                if candidate < previous:
                    candidate = _date_in_year(month, day, previous.year + 1, 1)
            else:
                candidate = date(year, month, day)
            assigned[index] = candidate
            previous = candidate
    else:
        month, day, _ = parts[0]
        anchor_year = min(time_dates).year if time_dates else today.year
        first = _date_in_year(month, day, anchor_year, 1)
        if not time_dates and first < today - timedelta(days=60):
            first = _date_in_year(month, day, first.year + 1, 1)
        assigned[0] = first
        previous = first
        for index in range(1, len(parts)):
            month, day, _ = parts[index]
            candidate = _date_in_year(month, day, previous.year, 1)
            if candidate < previous:
                candidate = _date_in_year(month, day, previous.year + 1, 1)
            assigned[index] = candidate
            previous = candidate

    return [parsed for parsed in assigned if parsed is not None]


def _dates_from_time_tag(time_tag: Tag) -> list[date]:
    dates = []
    for month, day, year in _date_parts(time_tag.get("datetime", "")):
        if year is not None:
            parsed = date(year, month, day)
            if parsed not in dates:
                dates.append(parsed)
    return dates


def _event_text_date_parts(block: Tag) -> list[tuple[int, int, int | None]]:
    parts = []
    outside_time_text = []
    seen_time_tags = set()

    def flush_outside_time_text():
        if outside_time_text:
            parts.extend(_date_parts(" ".join(outside_time_text)))
            outside_time_text.clear()

    for text in block.find_all(string=True):
        time_tag = text.find_parent("time", attrs={"datetime": True})
        if time_tag is None:
            outside_time_text.append(text.strip())
            continue

        flush_outside_time_text()
        if id(time_tag) in seen_time_tags:
            continue
        seen_time_tags.add(id(time_tag))
        time_dates = _dates_from_time_tag(time_tag)
        time_text_parts = _date_parts(" ".join(time_tag.stripped_strings))
        matching_time_parts = [
            (month, day, year, time_date)
            for month, day, year in time_text_parts
            for time_date in time_dates
            if month == time_date.month
            and day == time_date.day
            and (year is None or year == time_date.year)
        ]
        if not matching_time_parts:
            continue
        for month, day, year in time_text_parts:
            matching_time_date = next(
                (
                    time_date
                    for time_date in time_dates
                    if month == time_date.month
                    and day == time_date.day
                    and (year is None or year == time_date.year)
                ),
                None,
            )
            is_duplicate = matching_time_date is not None and any(
                previous_month == month
                and previous_day == day
                and (
                    previous_year is None
                    or previous_year == matching_time_date.year
                )
                for previous_month, previous_day, previous_year in parts
            )
            if not is_duplicate:
                parts.append((month, day, year))

    flush_outside_time_text()
    return parts


def _time_tag_dates(block: Tag) -> list[date]:
    dates = []
    for time_tag in block.select("time[datetime]"):
        for parsed in _dates_from_time_tag(time_tag):
            if parsed not in dates:
                dates.append(parsed)
    return dates


def _event_blocks(soup: BeautifulSoup) -> Iterable[Tag]:
    seen: set[int] = set()
    for selector in ("article", "li", ".event", ".events-item", ".tribe-events-calendar-list__event"):
        for node in soup.select(selector):
            if id(node) not in seen:
                seen.add(id(node))
                yield node
    if not seen:
        for heading in soup.select("h2, h3"):
            if heading.parent and id(heading.parent) not in seen:
                seen.add(id(heading.parent))
                yield heading.parent


def parse_events(
    html: str,
    *,
    source_url: str,
    keywords: list[str],
    today: date | None = None,
) -> list[SkiEvent]:
    today = today or date.today()
    soup = BeautifulSoup(html, "html.parser")
    patterns = tuple(
        re.compile(rf"\b{re.escape(keyword)}\b", re.I) for keyword in keywords
    )
    events: list[SkiEvent] = []
    seen: set[tuple[str, date, date]] = set()
    for block in _event_blocks(soup):
        text = " ".join(block.stripped_strings)
        if not text:
            continue
        title_node = block.find(["h1", "h2", "h3", "h4"])
        title_text = " ".join(title_node.stripped_strings) if title_node else ""
        description = " ".join(
            " ".join(node.stripped_strings)
            for node in block.select(
                ".tribe-events-calendar-list__event-description, "
                ".event-description, [itemprop='description']"
            )
        )
        description = re.sub(
            r"\b(?:location|venue)\s*:\s*.*?(?=\b(?:time|date)\s*:|$)",
            " ",
            description,
            flags=re.I,
        )
        for venue_node in block.select(
            ".tribe-events-calendar-list__event-venue, address, [itemprop='location']"
        ):
            venue = " ".join(venue_node.stripped_strings)
            if venue:
                description = re.sub(re.escape(venue), " ", description, flags=re.I)
        if not any(pattern.search(f"{title_text} {description}") for pattern in patterns):
            continue
        time_dates = _time_tag_dates(block)
        text_dates = _assign_text_date_years(
            _event_text_date_parts(block),
            time_dates,
            today,
        )
        dates = sorted(set(text_dates + time_dates))
        if not dates:
            continue
        start = min(dates)
        end = max(dates)
        title = title_text or text[:180]
        identity = (title, start, end)
        if identity in seen:
            continue
        seen.add(identity)
        link = block.find("a", href=True)
        events.append(
            SkiEvent(
                title=title,
                start_date=start,
                end_date=end,
                url=urljoin(source_url, link["href"]) if link else source_url,
                source=source_url,
            )
        )
    return events


def fetch_events(keywords: list[str], today: date | None = None) -> list[SkiEvent]:
    return parse_events(get_text(SITE), source_url=SITE, keywords=keywords, today=today)
