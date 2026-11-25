import asyncio
from types import SimpleNamespace

import httpx
import pytest

import online_plan
from online_plan import OnlinePlanError, OnlineRequest, generate_online_plan


@pytest.mark.parametrize("mode", ["valid", "unavailable", "invalid_citation"])
def test_search_before_generation(monkeypatch, mode):
    calls = []
    def handle(request):
        calls.append(request)
        if request.method == "GET":
            assert "authorization" not in request.headers
            if mode == "unavailable":
                return httpx.Response(503)
            page = {"title":"厦门", "pageid":15, "extract":"鼓浪屿可安排步行游览。"}
            return httpx.Response(200, json={"query":{"pages":{"15":page}}})
        assert len([r for r in calls if r.method == "GET"]) == 2
        import json
        content = json.dumps({
            "days": [{"sources": [1], "stops": [
                {"start": start, "end": end, "place": "鼓浪屿", "activity": "散步",
                 "transport": "步行，预留15分钟", "attraction_id": "A1"}
                for start, end in [("09:00","10:00"),("10:30","11:30"),("13:00","14:00"),("15:00","16:00")]
            ]}],
            "attractions": [{"id": "A"+str(i), "name": "鼓浪屿", "address":"厦门",
                "suggested_minutes":90,"price_cny":50,"price_basis":"门票",
                "price_evidence":"凭空的票价","opening_hours":"09:00–18:00",
                "hours_evidence":"凭空的时间","booking":"待核实","sources":[1]} for i in range(1,4)],
            "budget_note":"估算","verify_before_departure":"查天气"
        })
        if mode == "invalid_citation":
            content = content.replace("[1]", "[88]")
        return httpx.Response(200,json={"choices":[{"message":{"content":content}}]})

    async def no_candidates(*args):
        return {"hotels":{"status":"unavailable"},"flights":{"status":"unavailable"}}
    async def no_official(*args):
        return []
    monkeypatch.setattr(online_plan, "fetch_candidates", no_candidates)
    monkeypatch.setattr(online_plan, "official_sources", no_official)
    client_cls = httpx.AsyncClient
    monkeypatch.setattr(online_plan.httpx,"AsyncClient",lambda **kw:client_cls(transport=httpx.MockTransport(handle),**kw))
    monkeypatch.setattr(online_plan,"AnswerAgent",lambda:SimpleNamespace(
        api_key="unit-test",base_url="https://model.test",model="test"))
    req = OnlineRequest(city="厦门", days=1, needs="想散步")
    if mode == "valid":
        result = asyncio.run(generate_online_plan(req))
        assert result["plan"]["days"][0]["sources"] == [1]
        assert result["plan"]["attractions"][0]["price_cny"] is None
        assert result["plan"]["attractions"][0]["opening_hours"] == "本次资料未核实营业时间"
        assert result["plan"]["days"][0]["stops"][0]["estimated_cost_cny"] is None
        assert result["budget"]["flight_status"] == "unavailable"
        assert result["sources"][0]["url"] == "https://zh.wikivoyage.org/?curid=15"
    else:
        with pytest.raises(OnlinePlanError):
            asyncio.run(generate_online_plan(req))
        assert sum(r.method=="POST" for r in calls) == (2 if mode=="invalid_citation" else 0)

def test_overlapping_schedule_is_rejected():
    from pydantic import ValidationError
    from online_plan import DayPlan
    stops = [{"start": "09:00", "end": "10:00", "place": "公园", "activity": "散步", "transport": "步行"}] * 4
    with pytest.raises(ValidationError):
        DayPlan(sources=[1], stops=stops)


def test_hotel_query_uses_actual_occupancy(monkeypatch):
    from hotelbeds_client import HotelbedsClient
    from datetime import date
    captured = []
    provider = HotelbedsClient()
    monkeypatch.setattr(provider, "_availability", lambda payload: captured.append(payload))
    provider.search_area(24.4, 118.0, date(2026, 12, 1), date(2026, 12, 5), 2)
    assert captured[0]["occupancies"] == [{"rooms": 1, "adults": 2, "children": 0}]
    assert captured[0]["stay"] == {"checkIn": "2026-12-01", "checkOut": "2026-12-05"}


def test_flight_payload_and_price_scope(monkeypatch):
    from datetime import date
    from online_candidates import flight_candidates
    monkeypatch.setenv("DUFFEL_ACCESS_TOKEN", "duffel_test_mock")
    def handle(request):
        import json
        body = json.loads(request.content)["data"]
        assert len(body["passengers"]) == 2
        assert body["slices"][1]["departure_date"] == "2026-12-05"
        segment = {"marketing_carrier":{"iata_code":"MF","name":"厦门航空"},
                   "marketing_carrier_flight_number":"8518",
                   "departing_at":"2026-12-01T07:10:00","arriving_at":"2026-12-01T09:15:00",
                   "origin":{"iata_code":"SHA"},"destination":{"iata_code":"XMN"}}
        return httpx.Response(200, json={"data":{"offers":[{
            "id":"off_test","total_amount":"1200.00","total_currency":"CNY",
            "expires_at":"2026-11-25T12:00:00Z","slices":[{"segments":[segment]}]
        }]}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return await flight_candidates(client, OnlineRequest(city="厦门",departure="上海",
                days=5,people=2,start_date=date(2026,12,1),needs="轻松旅行"))
    result = asyncio.run(run())
    assert result["environment"] == "test"
    assert result["items"][0]["total_price"] == 1200
    assert result["items"][0]["people"] == 2


def test_flight_auth_error_is_explained(monkeypatch):
    from online_candidates import flight_candidates
    monkeypatch.setenv("DUFFEL_ACCESS_TOKEN", "duffel_test_mock")

    def handle(request):
        return httpx.Response(401, request=request, json={"error": {"message": "invalid"}})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return await flight_candidates(client, OnlineRequest(
                city="厦门", departure="上海", days=2, people=1,
                start_date="2026-12-01", needs="轻松旅行"))

    result = asyncio.run(run())
    assert result["status"] == "error"
    assert "令牌无效" in result["message"]
