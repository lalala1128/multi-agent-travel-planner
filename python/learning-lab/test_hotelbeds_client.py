import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest

from hotelbeds_client import HotelbedsClient, HotelbedsConfigurationError
from schemas import HotelSearchRequest


def settings(**overrides):
    values = {
        "hotelbeds_api_key": "test-key",
        "hotelbeds_secret": "test-secret",
        "hotelbeds_base_url": "https://example.test",
        "hotelbeds_client_cert": None,
        "hotelbeds_client_key": None,
        "hotelbeds_timeout_seconds": 15,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def request_body():
    return HotelSearchRequest(
        check_in="2026-12-10",
        check_out="2026-12-12",
        hotel_codes=[3424],
        adults=2,
    )


def test_hotelbeds_search_signs_and_parses_response():
    seen = {}

    def handler(request):
        seen["headers"] = request.headers
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json={
            "hotels": {"hotels": [{
                "code": 3424,
                "name": "Demo Hotel",
                "rooms": [{"rates": [{
                    "net": "125.50",
                    "currency": "EUR",
                    "rateType": "RECHECK",
                    "rateKey": "sensitive-rate-key",
                }]}],
            }]},
        })

    client = HotelbedsClient(
        settings=settings(),
        transport=httpx.MockTransport(handler),
        now=lambda: 1700000000,
    )
    result = client.search(request_body())

    expected = hashlib.sha256(b"test-keytest-secret1700000000").hexdigest()
    assert seen["headers"]["x-signature"] == expected
    assert seen["json"]["stay"]["checkIn"] == "2026-12-10"
    assert result.offers[0].total_price == 125.5
    assert result.offers[0].currency == "EUR"
    assert "sensitive-rate-key" not in result.offers[0].quote_reference


def test_hotelbeds_requires_credentials_and_certificate_for_real_request():
    client = HotelbedsClient(settings=settings(hotelbeds_api_key=None))
    with pytest.raises(HotelbedsConfigurationError):
        client.search(request_body())


def test_hotel_search_rejects_invalid_date_range():
    with pytest.raises(ValueError):
        HotelSearchRequest(
            check_in="2026-12-12",
            check_out="2026-12-10",
            hotel_codes=[3424],
        )
