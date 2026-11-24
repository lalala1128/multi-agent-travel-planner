from datetime import UTC, datetime

import pytest
import httpx
import exchange_rates

from hotelbeds_client import HotelbedsClient
from pipeline import TravelPlanningPipeline
from schemas import HotelOffer, HotelSearchResponse, TravelRequest
import travel_graph


@pytest.mark.parametrize(
    "currencies,status,reason,adjustments",
    [
        (["EUR", "CNY"], "completed", None, 1),
        (["EUR"], "over_budget", None, 2),
        (["XYZ"], "budget_unverified", "exchange_rate_unavailable", 0),
        ([], "budget_unverified", "no_hotel_offer", 0),
    ],
)
def test_task_hotel_and_budget(monkeypatch, currencies, status, reason, adjustments):
    calls = []
    fx_calls = []
    def daily_rates(url, **kwargs):
        fx_calls.append(url)
        today = datetime.now(UTC).date()
        xml = f'<Envelope><Cube time="{today}"><Cube currency="CNY" rate="7.25"/></Cube></Envelope>'
        return httpx.Response(200, text=xml, request=httpx.Request("GET", url))

    monkeypatch.setattr(exchange_rates.httpx, "get", daily_rates)
    def search(self, city, start, end):
        calls.append((city, (end - start).days))
        offers = [HotelOffer(hotel_code=1, hotel_name="Sample", total_price=1200,
                             currency=c, quote_reference="sample") for c in currencies]
        return HotelSearchResponse(provider="hotelbeds", quoted_at=datetime.now(UTC), offers=offers)

    monkeypatch.setattr(HotelbedsClient, "search_city", search)
    monkeypatch.setattr(travel_graph, "retrieve_knowledge", lambda state: {"knowledge": []})
    monkeypatch.setattr(travel_graph, "generate_answer", lambda state, **kw: {"knowledge_answer": None})
    request = TravelRequest(departure_city="北京", budget=3500, days=5, hotel_check_in="2026-12-10")
    plan = TravelPlanningPipeline().run(request)
    assert calls == [("首尔", 4)]
    assert (plan.status, plan.budget_result.reason, plan.adjustment_count) == (status, reason, adjustments)
    if currencies == ["EUR"]:
        rounds = plan.budget_result.rounds
        assert [item.round_index for item in rounds] == [0, 1, 2]
        assert [item.activity_plan for item in rounds] == ["standard", "economy", "free"]
        assert [item.total_cny for item in rounds] == [11500, 11000, 10500]
        assert [item.saved_since_previous_cny for item in rounds] == [None, 500, 500]
        assert all(item.hotel_cny == 8700 for item in rounds)
        assert plan.budget_result.hotel_budget_limit_cny == 1700
        assert plan.hotel.total_cost == 1200
        assert plan.budget_result.hotel_conversion.amount_cny == 8700
        assert plan.budget_result.total_cost == 10500
    elif reason is None:
        assert len(plan.budget_result.rounds) == 2
        assert plan.budget_result.hotel_budget_limit_cny == 1200
        assert plan.hotel.currency == "CNY"
        assert plan.budget_result.total_cost == 3500
    else:
        assert plan.budget_result.rounds == []
        assert plan.budget_result.hotel_budget_limit_cny is None
        assert plan.budget_result.total_cost is None
        assert plan.budget_result.within_budget is None
        assert (plan.hotel is None) == (not currencies)

    demo = TravelPlanningPipeline().run(request.model_copy(update={"hotel_check_in": None}))
    assert demo.hotel.provider == "demo"
    assert demo.budget_result.total_cost == 3500
    assert len(calls) == 1
    assert len(fx_calls) == int(any(c != "CNY" for c in currencies))


@pytest.mark.parametrize("budget,expected_status,expected_rounds,hotel_limit", [
    (4000, "completed", 1, 1200),
    (1600, "over_budget", 3, 0),
    (1500, "over_budget", 3, None),
])
def test_hotel_budget_limit(monkeypatch, budget, expected_status, expected_rounds, hotel_limit):
    monkeypatch.setattr(travel_graph, "retrieve_knowledge", lambda state: {"knowledge": []})
    monkeypatch.setattr(travel_graph, "generate_answer", lambda state, **kw: {"knowledge_answer": None})
    plan = TravelPlanningPipeline().run(TravelRequest(departure_city="北京", budget=budget, days=5))
    assert plan.status == expected_status
    assert len(plan.budget_result.rounds) == expected_rounds
    assert plan.budget_result.hotel_budget_limit_cny == hotel_limit


def test_shortlist_compares_stay_totals_and_deduplicates_hotels(monkeypatch):
    from decimal import Decimal
    from hotel_agent import HotelAgent
    from schemas import DestinationRecommendation

    offers = [
        HotelOffer(hotel_code=code, hotel_name=str(code), total_price=price,
                   currency=currency, quote_reference=f"{code}-{price}")
        for code, price, currency in [
            (1, 1000, "CNY"), (2, 140, "EUR"), (2, 100, "EUR"),
            (3, 710, "CNY"), (4, 720, "CNY"), (5, 1, "XYZ"),
        ]
    ]
    response = HotelSearchResponse(provider="hotelbeds", quoted_at=datetime.now(UTC), offers=offers)
    monkeypatch.setattr(HotelbedsClient, "search_city", lambda *args: response)
    rates = exchange_rates.DailyRates(datetime.now(UTC).date(), {"CNY": Decimal(7), "EUR": Decimal(1)})
    monkeypatch.setattr("hotel_agent.fetch_daily_rates", lambda: rates)
    hotel = HotelAgent().run(
        TravelRequest(departure_city="北京", budget=3500, days=5, hotel_check_in="2026-12-10"),
        DestinationRecommendation(city="首尔", reason="test", daily_budget=700),
    )
    assert (hotel.hotel_code, hotel.currency, hotel.total_cost) == (2, "EUR", 100)
    assert [(h.hotel_code, h.total_cny) for h in hotel.shortlist] == [(2, 700), (3, 710), (4, 720)]
    assert hotel.conversion.amount_cny == hotel.shortlist[0].total_cny
    assert hotel.unpriced_offer_count == 1
