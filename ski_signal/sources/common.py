import re
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


TIMEOUT_SECONDS = 20
API_KEY_PATTERN = re.compile(r"(?i)(api_key=)[^&\s\"']+")


def redact_api_key(message: str) -> str:
    return API_KEY_PATTERN.sub(r"\1[REDACTED]", message)


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
    try:
        response = (client or session()).get(url, params=params, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as error:
        message = redact_api_key(str(error))
        try:
            sanitized = type(error)(
                message,
                request=error.request,
                response=error.response,
            )
        except TypeError:
            try:
                sanitized = type(error)(message)
            except TypeError:
                sanitized = requests.RequestException(message)
        raise sanitized from None
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
    try:
        response = (client or session()).get(url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as error:
        message = redact_api_key(str(error))
        try:
            sanitized = type(error)(
                message,
                request=error.request,
                response=error.response,
            )
        except TypeError:
            try:
                sanitized = type(error)(message)
            except TypeError:
                sanitized = requests.RequestException(message)
        raise sanitized from None
    return response.text
