from schemas import TravelRequest, DestinationRecommendation


class DestinationAgent:
    def run(
        self,
        preferences: TravelRequest,
    ) -> DestinationRecommendation:
        daily_budget = preferences.budget / preferences.days

        if preferences.destination_city:
            city = preferences.destination_city
            reason = "用户指定目的地"
        elif daily_budget < 500:
            city = "清迈"
            reason = "命中低预算演示规则"
        elif daily_budget < 1000:
            city = "首尔"
            reason = "命中中预算演示规则"
        else:
            city = "东京"
            reason = "命中高预算演示规则"

        return DestinationRecommendation(
            city=city,
            reason=reason,
            daily_budget=round(daily_budget, 2),
        )
