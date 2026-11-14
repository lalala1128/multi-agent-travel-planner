from pipeline import TravelPlanningPipeline
from schemas import TravelRequest


def test_adjust_to_economy():
    request = TravelRequest(
        departure_city="北京",
        budget=3500,
        days=5,
    )

    result = TravelPlanningPipeline().run(request)

    assert result.activity.plan_type == "economy"
    assert result.adjustment_count == 1
    assert result.budget_result.total_cost == 3500
    assert result.status == "completed"
def test_stop_when_still_over_budget():
    request = TravelRequest(
        departure_city="北京",
        budget=2500,
        days=5,
    )

    result = TravelPlanningPipeline().run(request)

    assert result.activity.plan_type == "free"
    assert result.adjustment_count == 2
    assert result.budget_result.within_budget is False
    assert result.status == "over_budget"
def test_complete_without_adjustment():
    request = TravelRequest(
        departure_city="北京",
        budget=5000,
        days=5,
    )

    result = TravelPlanningPipeline().run(request)

    # 在下面补充四条 assert
    assert result.activity.plan_type == "standard"
   
    assert result.adjustment_count == 0
    assert result.budget_result.within_budget is True
    assert result.status == "completed"   