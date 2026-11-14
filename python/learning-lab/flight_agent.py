from schemas import (
    TravelRequest,
    DestinationRecommendation,
    FlightResult,
)


class FlightAgent:
    def run(
        self,
        preferences: TravelRequest,
        destination: DestinationRecommendation,
    ) -> FlightResult:
        # 用于学习的单人往返模拟报价
        mock_prices = {
            "清迈": 1600,
            "首尔": 1800,
            "东京": 2500,
        }

        price = mock_prices[destination.city]

        return FlightResult(
            departure_city=preferences.departure_city,
            arrival_city=destination.city,
            round_trip_cost=price,
        )