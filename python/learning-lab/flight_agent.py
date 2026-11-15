from schemas import (
    TravelRequest,
    DestinationRecommendation,
    FlightResult,
)
from quote_providers import create_travel_provider


class FlightAgent:
    def __init__(self, provider=None):
        self.provider = provider or create_travel_provider()

    def run(
        self,
        preferences: TravelRequest,
        destination: DestinationRecommendation,
    ) -> FlightResult:
        quote = self.provider.flight(preferences.departure_city, destination.city)

        return FlightResult(
            departure_city=preferences.departure_city,
            arrival_city=destination.city,
            round_trip_cost=quote.amount,
            provider=quote.provider,
            quote_reference=quote.quote_reference,
            quoted_at=quote.quoted_at,
        )
