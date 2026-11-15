from schemas import (
    TravelRequest,
    DestinationRecommendation,
    ActivityResult,
)
from quote_providers import create_travel_provider


class ActivityAgent:
    def __init__(self, provider=None):
        self.provider = provider or create_travel_provider()

    def run(
        self,
        preferences: TravelRequest,
        destination: DestinationRecommendation,
        plan_type: str = "standard",
    ) -> ActivityResult:
        quote = self.provider.activity(destination.city, plan_type)

        return ActivityResult(
            city=destination.city,
            plan_type=plan_type,
            daily_cost=quote.amount,
            total_cost=preferences.days * quote.amount,
            provider=quote.provider,
            quote_reference=quote.quote_reference,
            quoted_at=quote.quoted_at,
        )
