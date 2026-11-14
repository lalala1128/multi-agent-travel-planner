from schemas import (
    TravelRequest,
    DestinationRecommendation,
    ActivityResult,
)


class ActivityAgent:
    def run(
        self,
        preferences: TravelRequest,
        destination: DestinationRecommendation,
        plan_type: str = "standard",
    ) -> ActivityResult:
        mock_prices = {
            "standard": 200,
            "economy": 100,
            "free": 0,
        }

        if plan_type not in mock_prices:
            raise ValueError("不支持的活动方案")

        daily_cost = mock_prices[plan_type]
        total_cost = preferences.days * daily_cost

        return ActivityResult(
            city=destination.city,
            plan_type=plan_type,
            daily_cost=daily_cost,
            total_cost=total_cost,
        )