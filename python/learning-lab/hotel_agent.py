from schemas import (
    TravelRequest,
    DestinationRecommendation,
    HotelResult,
)
from quote_providers import create_travel_provider


class HotelAgent:
    def __init__(self, provider=None):
        self.provider = provider or create_travel_provider()

    def run(
        self,
        preferences: TravelRequest,
        destination: DestinationRecommendation,
    ) -> HotelResult:
        nights = preferences.days - 1
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
