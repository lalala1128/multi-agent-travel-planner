from pipeline import TravelPlanningPipeline
from schemas import TravelRequest
import pytest
import travel_graph
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def offline_knowledge(monkeypatch):
    monkeypatch.setattr(travel_graph.knowledge_agent, "run", lambda **kwargs: [])


@pytest.mark.parametrize("daily,budget,expected,total", [
    (160, 3500, "over_budget", 3900), (0, 3100, "completed", 3100),
])
def test_personal_trip_uses_entered_prices(monkeypatch, daily, budget, expected, total):
    def unexpected(*args, **kwargs):
        pytest.fail("手填预算不应查询外部服务")
    monkeypatch.setattr("hotel_agent.HotelbedsClient.search_city", unexpected)
    monkeypatch.setattr(travel_graph.knowledge_agent, "run", unexpected)
    monkeypatch.setattr(travel_graph.answer_agent, "run", unexpected)
    request = TravelRequest(departure_city="北京", destination_city="厦门", budget=budget, days=5,
                            flight_total_cny=1900, hotel_total_cny=1200, daily_spending_cny=daily,
                            hotel_check_in="2026-12-10", include_knowledge=False)
    result = TravelPlanningPipeline().run(request)
    assert result.destination.city == "厦门"
    assert result.flight.provider == result.hotel.provider == result.activity.provider == "user_input"
    assert result.budget_result.total_cost == total and result.status == expected
    assert result.adjustment_count == 0 and result.knowledge_answer is None


def test_manual_price_requires_destination():
    with pytest.raises(ValidationError):
        TravelRequest(departure_city="北京", budget=3500, days=5, flight_total_cny=1200)


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
