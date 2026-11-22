from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


TIMEOUT_SECONDS = 20


def session() -> requests.Session:
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        status=2,
        backoff_factor=0.4,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    client = requests.Session()
    client.mount("https://", HTTPAdapter(max_retries=retry))
    client.mount("http://", HTTPAdapter(max_retries=retry))
    client.headers.update({"User-Agent": "japan-ski-signal/0.1"})
    return client


def get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: int = TIMEOUT_SECONDS,
    client: requests.Session | None = None,
) -> dict[str, Any]:
    response = (client or session()).get(url, params=params, timeout=timeout)
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict):
        raise ValueError(f"Expected a JSON object from {response.url}")
    return result


def get_text(
    url: str,
    *,
    timeout: int = TIMEOUT_SECONDS,
    client: requests.Session | None = None,
) -> str:
    response = (client or session()).get(url, timeout=timeout)
    response.raise_for_status()
    return response.text
