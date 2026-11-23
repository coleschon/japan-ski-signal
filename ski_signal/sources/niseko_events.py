import re
from datetime import date
from typing import Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ski_signal.models import SkiEvent
from ski_signal.sources.common import get_text


SITE = "https://www.niseko-village.com/events/"
MONTHS = {
    month.lower(): index
    for index, month in enumerate(
        ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"),
        start=1,
    )
}
MONTH_PATTERN = "|".join(MONTHS)
DATE_PATTERNS = (
    re.compile(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b"),
    re.compile(rf"\b({MONTH_PATTERN})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?[,]?\s*(20\d{{2}})?\b", re.I),
    re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({MONTH_PATTERN})\.?[,]?\s*(20\d{{2}})?\b", re.I),
)


def _date_matches(text: str, default_year: int) -> list[date]:
    found: list[tuple[int, int, int, int]] = []
    for pattern_index, pattern in enumerate(DATE_PATTERNS):
        for match in pattern.finditer(text):
            groups = match.groups()
            try:
                if pattern_index == 0:
                    year, month, day = map(int, groups)
                elif pattern_index == 1:
                    month, day, year = groups
                    month = MONTHS[month.lower()]
                    year = int(year) if year else default_year
                    day = int(day)
                else:
                    day, month, year = groups
                    month = MONTHS[month.lower()]
                    year = int(year) if year else default_year
                    day = int(day)
                found.append((match.start(), year, month, day))
            except (ValueError, KeyError):
                continue
    dates: list[date] = []
    for _, year, month, day in sorted(found):
        try:
            parsed = date(year, month, day)
        except ValueError:
            continue
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
        if not any(pattern.search(f"{title_text} {description}") for pattern in patterns):
            continue
        dates = _date_matches(text, today.year)
        if not dates:
            for time_tag in block.select("time[datetime]"):
                dates.extend(_date_matches(time_tag.get("datetime", ""), today.year))
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
