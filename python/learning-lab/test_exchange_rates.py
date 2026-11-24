from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from exchange_rates import convert_hotel_to_cny


@pytest.mark.parametrize("age,usd,expected", [
    (0, "2", Decimal("3.63")), (7, "2", Decimal("3.63")),
    (8, "2", None), (-1, "2", None), (0, "0", None), (0, "NaN", None),
])
def test_cross_rate_and_validity(monkeypatch, age, usd, expected):
    day = datetime.now(UTC).date() - timedelta(days=age)
    xml = (f'<Cube xmlns="urn:example"><Cube time="{day}">'
           f'<Cube currency="CNY" rate="7.25"/><Cube currency="USD" rate="{usd}"/>'
           '</Cube></Cube>')
    def fetch(url, **kwargs):
        return httpx.Response(200, text=xml, request=httpx.Request("GET", url))
    monkeypatch.setattr(httpx, "get", fetch)
    result = convert_hotel_to_cny(Decimal("1"), "USD")
    assert (result.amount_cny if result else None) == expected


def test_timeout_leaves_budget_unverified(monkeypatch):
    def offline(*args, **kwargs):
        raise httpx.ReadTimeout("timeout")
    monkeypatch.setattr(httpx, "get", offline)
    assert convert_hotel_to_cny(Decimal("10"), "EUR") is None
