from decimal import Decimal

from exchange_rates import convert_hotel_to_cny
from schemas import BudgetRound, BudgetResult, PlanningState


class BudgetAgent:
    def run(self, state: PlanningState) -> BudgetResult:
        if state.preferences.hotel_check_in and state.hotel is None:
            return BudgetResult(total_cost=None, remaining=None, within_budget=None, reason="no_hotel_offer")
        if (
            state.flight is None
            or state.hotel is None
            or state.activity is None
        ):
            raise ValueError("预算检查前，需要先取得航班、酒店和活动结果")

        flight_cost = Decimal(str(state.flight.round_trip_cost))
        hotel_cost = Decimal(str(state.hotel.total_cost))
        activity_cost = Decimal(str(state.activity.total_cost))
        conversion = None
        if state.hotel.currency != "CNY":
            # 回路只调整活动；同一任务沿用第一次预算校验时的汇率。
            conversion = state.hotel.conversion
            if conversion is None and state.budget_result:
                conversion = state.budget_result.hotel_conversion
            if conversion is None and not state.hotel.unpriced_offer_count:
                conversion = convert_hotel_to_cny(hotel_cost, state.hotel.currency)
            if conversion is None:
                return BudgetResult(total_cost=None, remaining=None, within_budget=None,
                                    reason="exchange_rate_unavailable")
            hotel_cost = conversion.amount_cny

        total_cost = flight_cost + hotel_cost + activity_cost
        budget = Decimal(str(state.preferences.budget))
        remaining = budget - total_cost
        hotel_limit = budget - flight_cost - activity_cost
        prior = state.budget_result.rounds if state.budget_result else []
        rounds = [item for item in prior if item.round_index < state.adjustment_count]
        rounds.append(BudgetRound(
            round_index=state.adjustment_count,
            activity_plan=state.activity.plan_type,
            flight_cny=flight_cost,
            hotel_cny=hotel_cost,
            activity_cny=activity_cost,
            total_cny=total_cost,
            saved_since_previous_cny=rounds[-1].total_cny - total_cost if rounds else None,
        ))

        return BudgetResult(
            rounds=rounds,
            hotel_budget_limit_cny=hotel_limit if hotel_limit >= 0 else None,
            hotel_conversion=conversion,
            total_cost=total_cost,
            remaining=remaining,
            within_budget=total_cost <= budget,
        )
