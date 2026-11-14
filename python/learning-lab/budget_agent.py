from schemas import PlanningState, BudgetResult


class BudgetAgent:
    def run(self, state: PlanningState) -> BudgetResult:
        if (
            state.flight is None
            or state.hotel is None
            or state.activity is None
        ):
            raise ValueError("预算检查前，需要先取得航班、酒店和活动结果")

        flight_cost = state.flight.round_trip_cost
        hotel_cost = state.hotel.total_cost
        activity_cost = state.activity.total_cost

        total_cost = flight_cost + hotel_cost + activity_cost
        budget = state.preferences.budget
        remaining = budget - total_cost

        return BudgetResult(
            total_cost=total_cost,
            remaining=remaining,
            within_budget=total_cost <= budget,
        )
