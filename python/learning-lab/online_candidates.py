"""在生成日程前查询住宿和航班候选，记录供应商的查询状态。"""
import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import httpx

from exchange_rates import fetch_daily_rates
from hotelbeds_client import HotelbedsClient, HotelbedsConfigurationError, HotelbedsUpstreamError, HotelbedsResponseError
from settings import load_settings

CENTERS = {"厦门": (24.4798,118.0894), "上海":(31.2304,121.4737), "北京":(39.9042,116.4074),
           "杭州":(30.2741,120.1551), "成都":(30.5728,104.0668), "广州":(23.1291,113.2644),
           "首尔":(37.5665,126.9780), "东京":(35.6812,139.7671), "清迈":(18.7883,98.9853)}
AIRPORTS = {"上海":"SHA","厦门":"XMN","北京":"BJS","广州":"CAN","成都":"CTU","杭州":"HGH",
            "深圳":"SZX","首尔":"SEL","东京":"TYO","清迈":"CNX"}

def hotel_candidates(req):
    result = {"status": "unavailable", "message": ""}
    if not req.start_date or req.days < 2:
        result["message"] = "选择出发日期并安排至少两天，才能查询住宿。"
        return result
    if req.city not in CENTERS:
        result["message"] = "该城市的酒店查询中心尚未配置。"
        return result
    checkout = req.start_date + timedelta(days=req.days-1)
    provider = HotelbedsClient()
    try:
        response = provider.search_area(*CENTERS[req.city], req.start_date, checkout, req.people)
    except HotelbedsConfigurationError:
        result["message"] = "酒店供应商凭据或证书尚未就绪。"
        return result
    except (HotelbedsUpstreamError, HotelbedsResponseError):
        result["message"] = "酒店供应商本次查询失败，请稍后重试。"
        return result
    result["environment"] = "测试报价" if ".test." in provider.settings.hotelbeds_base_url else "正式环境"
    result["offers"] = []
    rates = fetch_daily_rates() if any(o.currency != "CNY" for o in response.offers) else None
    seen = set()
    for offer in sorted(response.offers, key=lambda o: (o.currency, o.total_price)):
        if offer.hotel_code in seen:
            continue
        seen.add(offer.hotel_code)
        converted = rates.convert(Decimal(str(offer.total_price)), offer.currency) if rates else None
        item = offer.model_dump()
        item.update(check_in=req.start_date.isoformat(), check_out=checkout.isoformat(),
                    nights=req.days-1, quoted_at=response.quoted_at.isoformat(),
                    per_room_night=round(offer.total_price / (req.days-1) / offer.rooms, 2),
                    total_cny=offer.total_price if offer.currency == "CNY" else (float(converted.amount_cny) if converted else None),
                    rate_date=converted.rate_date.isoformat() if converted else None)
        result["offers"].append(item)
        if len(result["offers"]) == 5:
            break
    result["status"] = "ok" if result["offers"] else "empty"
    result["message"] = "已查询所选日期，以下为每家酒店最低供应商净价。" if result["offers"] else "所选日期和入住人数未查到可用酒店。"
    return result

async def flight_candidates(client, req):
    result = {"status":"unavailable","message":"航班实时查询尚未配置供应商账号。","items":[]}
    token = load_settings().duffel_access_token
    if not token:
        return result
    if not req.start_date or not req.departure:
        result["message"]="请填写出发城市和日期后查询航班。"
        return result
    origin, dest = AIRPORTS.get(req.departure), AIRPORTS.get(req.city)
    if not origin or not dest or origin==dest:
        result["message"]="该航线的机场代码尚未配置。"
        return result
    result["environment"]="test" if token.startswith("duffel_test_") else "live"
    payload={"data":{"slices":[{"origin":origin,"destination":dest,"departure_date":req.start_date.isoformat()},
                               {"origin":dest,"destination":origin,"departure_date":(req.start_date+timedelta(days=req.days-1)).isoformat()}],
                     "passengers":[{"type":"adult"} for _ in range(req.people)],"cabin_class":"economy"}}
    try:
        response=await client.post("https://api.duffel.com/air/offer_requests",
            params={"return_offers":"true","supplier_timeout":15000},
            headers={"Authorization":"Bearer "+token,"Duffel-Version":"v2","Accept":"application/json"},
            json=payload,timeout=22)
        response.raise_for_status()
        offers=response.json()["data"]["offers"]
        for offer in sorted(offers,key=lambda x:(x["total_currency"],Decimal(x["total_amount"])))[:5]:
            slices=[]
            for part in offer["slices"]:
                slices.append([{"flight":s["marketing_carrier"]["iata_code"]+s["marketing_carrier_flight_number"],
                    "airline":s["marketing_carrier"]["name"],"departure":s["departing_at"],"arrival":s["arriving_at"],
                    "origin":s["origin"]["iata_code"],"destination":s["destination"]["iata_code"]} for s in part["segments"]])
            result["items"].append({"id":"F"+str(len(result["items"])+1),"total_price":float(offer["total_amount"]),
                "currency":offer["total_currency"],"people":req.people,"price_basis":"全体成人往返含税总价",
                "slices":slices,"expires_at":offer["expires_at"],"quoted_at":datetime.now(UTC).isoformat()})
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        if status in {401, 403}:
            result["message"] = "Duffel 令牌无效或权限不足，请检查 .env 后重启 API。"
        elif status == 422:
            result["message"] = "航班查询参数未被供应商接受，请检查日期、机场和人数。"
        else:
            result["message"] = f"航班供应商返回 HTTP {status}，请稍后重试。"
        result["status"] = "error"
        return result
    except (httpx.HTTPError,ValueError,KeyError,TypeError):
        result.update(status="error", message="航班供应商本次未返回可解析的报价。",items=[])
        return result
    result.update(status="ok" if result["items"] else "empty",message="按日期和人数查询的往返经济舱候选。")
    return result

async def fetch_candidates(client,req):
    hotels,flights = await asyncio.gather(asyncio.to_thread(hotel_candidates,req),flight_candidates(client,req))
    return {"hotels":hotels,"flights":flights}
