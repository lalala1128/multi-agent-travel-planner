"""按欧洲央行同一天公布的欧元参考汇率估算酒店人民币预算。"""

from datetime import UTC, date, datetime
from decimal import Decimal, DecimalException, ROUND_HALF_UP
from xml.etree import ElementTree

import httpx
from dataclasses import dataclass

from schemas import HotelConversion


ECB_DAILY = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"


@dataclass
class DailyRates:
    rate_date: date
    rates: dict[str, Decimal]

    def convert(self, amount: Decimal, currency: str) -> HotelConversion | None:
        origin = self.rates.get(currency)
        if origin is None:
            return None
        rate = self.rates["CNY"] / origin
        return HotelConversion(
            source_currency=currency, rate_date=self.rate_date, cny_per_unit=rate,
            amount_cny=(amount * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        )


def fetch_daily_rates() -> DailyRates | None:
    try:
        response = httpx.get(ECB_DAILY, timeout=5.0)
        response.raise_for_status()
        day = ElementTree.fromstring(response.content).find(".//{*}Cube[@time]")
        if day is None:
            return None
        rate_date = date.fromisoformat(day.attrib["time"])
        age = (datetime.now(UTC).date() - rate_date).days
        if not 0 <= age <= 7:
            return None
        rates = {}
        for row in day.findall("{*}Cube"):
            value = Decimal(row.attrib["rate"])
            if value.is_finite() and value > 0:
                rates[row.attrib["currency"]] = value
        rates["EUR"] = Decimal(1)
        if "CNY" not in rates:
            return None
        return DailyRates(rate_date, rates)
    except (httpx.HTTPError, ElementTree.ParseError, ValueError, KeyError, DecimalException):
        return None


def convert_hotel_to_cny(amount: Decimal, currency: str) -> HotelConversion | None:
    rates = fetch_daily_rates()
    return rates.convert(amount, currency) if rates else None
