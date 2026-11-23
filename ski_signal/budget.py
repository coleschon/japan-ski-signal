from datetime import date
from typing import Any

import requests

from ski_signal.sources.common import TIMEOUT_SECONDS, session as http_session
from ski_signal.storage import Store


class BudgetExceeded(RuntimeError):
    pass


def usage_key(today: date) -> str:
    return f"serpapi-usage:{today:%Y-%m}"


def _account_usage(payload: dict[str, Any]) -> tuple[int, int | None]:
    used = payload.get("this_month_usage")
    searches_left = payload.get("plan_searches_left")
    if used is None and searches_left is None:
        raise ValueError("SerpApi account response lacks usage fields")
    return int(used or 0), None if searches_left is None else int(searches_left)


def reserve_search(
    store: Store,
    *,
    api_key: str,
    monthly_cap: int,
    today: date | None = None,
    session: requests.Session | None = None,
) -> int:
    today = today or date.today()
    key = usage_key(today)
    local_used = int(store.get(key, 0))
    client = session or http_session()
    response = client.get(
        "https://serpapi.com/account.json",
        params={"api_key": api_key},
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    remote_used, plan_left = _account_usage(response.json())
    if max(local_used, remote_used) >= monthly_cap or (plan_left is not None and plan_left <= 0):
        raise BudgetExceeded(f"SerpApi monthly cap reached ({max(local_used, remote_used)}/{monthly_cap})")
    reservation = store.reserve_usage(key, remote_used, monthly_cap)
    if reservation is None:
        raise BudgetExceeded(f"SerpApi monthly cap reached ({monthly_cap}/{monthly_cap})")
    return reservation


def stalest_first(
    candidates: list[tuple[str, Any]],
    observations: dict[str, Any],
    limit: int,
) -> list[str]:
    def timestamp(key: str) -> str:
        value = observations.get(key)
        if isinstance(value, dict):
            return str(value.get("fetched_at", ""))
        return ""

    return [
        key
        for key, _ in sorted(
            candidates,
            key=lambda item: (timestamp(item[0]), item[0]),
        )[:limit]
    ]
