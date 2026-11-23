import traceback
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import requests

from ski_signal.sources import amedas, enso
from ski_signal.sources.common import get_json, get_text


FIXTURES = Path(__file__).parent / "fixtures"
JST = ZoneInfo("Asia/Tokyo")


@pytest.mark.parametrize("fetcher", [get_json, get_text])
def test_source_request_errors_redact_api_keys(fetcher):
    class Client:
        def get(self, url, **kwargs):
            response = requests.Response()
            response.status_code = 500
            response.reason = "Internal Server Error"
            response.url = url
            return response

    with pytest.raises(requests.HTTPError) as raised:
        fetcher("https://example.com/data?api_key=SECRET", client=Client())

    formatted = "".join(
        traceback.format_exception(raised.type, raised.value, raised.tb)
    )
    assert "SECRET" not in str(raised.value)
    assert "SECRET" not in formatted


def test_amedas_block_paths_use_three_hour_blocks_and_roll_over():
    current, previous = amedas.point_block_urls(
        "16217",
        datetime(2026, 11, 23, 8, 30, tzinfo=JST),
    )
    assert current.endswith("/16217/20261123_06.json")
    assert previous.endswith("/16217/20261123_03.json")
    midnight, prior_night = amedas.point_block_urls(
        "16217",
        datetime(2026, 11, 23, 0, 20, tzinfo=JST),
    )
    assert midnight.endswith("/16217/20261123_00.json")
    assert prior_night.endswith("/16217/20261122_21.json")


def test_amedas_extracts_latest_usable_hourly_snow():
    fixture = json.loads((FIXTURES / "amedas_point_block.json").read_text())
    assert amedas.extract_snow(fixture) == ("20261123080000", 21.0)


def test_amedas_falls_back_to_previous_block_at_midnight(monkeypatch):
    requested = []
    monkeypatch.setattr(
        amedas,
        "get_text",
        lambda url: "2026-11-23T00:20:00+09:00",
    )

    def get_json(url):
        requested.append(url)
        if url.endswith("/20261123_00.json"):
            return {"20261123001000": {"snow": [None, 0]}}
        return json.loads((FIXTURES / "amedas_previous_block.json").read_text())

    monkeypatch.setattr(
        amedas,
        "get_json",
        get_json,
    )
    result = amedas.fetch_depth("16217")
    assert requested == [
        "https://www.jma.go.jp/bosai/amedas/data/point/16217/20261123_00.json",
        "https://www.jma.go.jp/bosai/amedas/data/point/16217/20261122_21.json",
    ]
    assert result.depth_cm == 21
    assert result.observed_at == "2026-11-22T23:00:00+09:00"


def test_amedas_falls_back_after_current_block_http_error(monkeypatch):
    requested = []
    monkeypatch.setattr(
        amedas,
        "get_text",
        lambda url: "2026-11-23T08:30:00+09:00",
    )

    def get_json(url):
        requested.append(url)
        if url.endswith("/20261123_06.json"):
            raise requests.HTTPError("404 Not Found")
        return {"20261123080000": {"snow": [21, 0]}}

    monkeypatch.setattr(amedas, "get_json", get_json)
    result = amedas.fetch_depth("16217")

    assert requested == [
        "https://www.jma.go.jp/bosai/amedas/data/point/16217/20261123_06.json",
        "https://www.jma.go.jp/bosai/amedas/data/point/16217/20261123_03.json",
    ]
    assert result.depth_cm == 21


def test_cpc_enso_parses_latest_roni_and_oni_rows():
    roni = "SEAS YR ANOM\nDJF 2026 0.55\nJFM 2026 0.71\n"
    oni = "SEAS YR TOTAL ANOM\nDJF 2026 26.00 0.65\nJFM 2026 26.50 0.80\n"
    assert enso.parse_anomaly(roni) == 0.71
    assert enso.parse_anomaly(oni) == 0.80
