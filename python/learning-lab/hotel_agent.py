from datetime import timedelta
from decimal import Decimal
from exchange_rates import fetch_daily_rates
from hotelbeds_client import HotelbedsClient
from schemas import (
    TravelRequest,
    DestinationRecommendation,
    HotelResult,
    RankedHotel,
)
from quote_providers import create_travel_provider


class HotelAgent:
    def __init__(self, provider=None):
        self.provider = provider or create_travel_provider()

    def run(
        self,
        preferences: TravelRequest,
        destination: DestinationRecommendation,
    ) -> HotelResult | None:
        nights = preferences.days - 1
        if preferences.hotel_check_in is not None:
            start = preferences.hotel_check_in
            response = HotelbedsClient().search_city(destination.city, start, start + timedelta(days=nights))
            if not response.offers:
                return None
            rates = fetch_daily_rates() if any(o.currency != "CNY" for o in response.offers) else None
            by_hotel = {}
            unpriced = 0
            for offer in response.offers:
                amount = Decimal(str(offer.total_price))
                conversion = None
                if offer.currency != "CNY":
                    conversion = rates.convert(amount, offer.currency) if rates else None
                    if conversion is None:
                        unpriced += 1
                        continue
                    amount = conversion.amount_cny
                rank = (amount, offer.hotel_code, offer.quote_reference)
                previous = by_hotel.get(offer.hotel_code)
                if previous is None or rank < previous[0]:
                    by_hotel[offer.hotel_code] = (rank, offer, conversion)

            ranked = sorted(by_hotel.values(), key=lambda item: item[0])[:3]
            shortlist = [
                RankedHotel(**offer.model_dump(), total_cny=rank[0])
                for rank, offer, _ in ranked
            ]
            if ranked:
                _, best, conversion = ranked[0]
            else:
                # 无可折算报价时沿用原币种展示，预算节点会标记待核算。
                currency = response.offers[0].currency
                best = min((o for o in response.offers if o.currency == currency), key=lambda o: o.total_price)
                conversion = None
            return HotelResult(
                shortlist=shortlist, unpriced_offer_count=unpriced, conversion=conversion,
                city=destination.city, hotel_code=best.hotel_code, hotel_name=best.hotel_name,
                price_per_night=round(best.total_price / nights, 2), nights=nights,
                total_cost=best.total_price, currency=best.currency, provider=response.provider,
                quote_reference=best.quote_reference, quoted_at=response.quoted_at,
            )
        quote = self.provider.hotel(destination.city, nights)

        return HotelResult(
            city=destination.city,
            price_per_night=quote.amount,
            nights=nights,
            total_cost=quote.amount * nights,
            provider=quote.provider,
            quote_reference=quote.quote_reference,
            quoted_at=quote.quoted_at,
        )
