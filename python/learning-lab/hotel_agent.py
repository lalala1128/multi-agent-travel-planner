from schemas import (
    TravelRequest,
    DestinationRecommendation,
    HotelResult,
)


class HotelAgent:
    def run(
        self,
        preferences: TravelRequest,
        destination: DestinationRecommendation,
    ) -> HotelResult:
        # 用于学习的单间每晚模拟报价
        price_per_night = 300

        nights = preferences.days - 1
        total_cost = price_per_night * nights

        return HotelResult(
            city=destination.city,
            price_per_night=price_per_night,
            nights=nights,
            total_cost=total_cost,
        )