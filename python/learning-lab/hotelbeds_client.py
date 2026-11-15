"""Hotelbeds 酒店可用性查询客户端。

只实现 Availability（/hotels）查询；不执行核价或预订，避免在学习项目中产生订单。
"""

import hashlib
import logging
import ssl
import time
from datetime import UTC, datetime

import httpx

from schemas import HotelOffer, HotelSearchRequest, HotelSearchResponse
from settings import load_settings


logger = logging.getLogger(__name__)


class HotelbedsConfigurationError(RuntimeError):
    pass


class HotelbedsUpstreamError(RuntimeError):
    pass


class HotelbedsResponseError(RuntimeError):
    pass


class HotelbedsClient:
    """封装签名、mTLS 和 Hotelbeds 响应解析，不记录密钥与原始 rateKey。"""

    def __init__(self, settings=None, transport=None, now=None):
        self.settings = settings or load_settings()
        self.transport = transport
        self.now = now or time.time

    def _validate_configuration(self):
        required = {
            "HOTELBEDS_API_KEY": self.settings.hotelbeds_api_key,
            "HOTELBEDS_SECRET": self.settings.hotelbeds_secret,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise HotelbedsConfigurationError("Hotelbeds 凭据未配置")
        if self.transport is None and (
            not self.settings.hotelbeds_client_cert or not self.settings.hotelbeds_client_key
        ):
            raise HotelbedsConfigurationError("Hotelbeds mTLS 客户端证书未配置")

    def _signature(self, timestamp: int) -> str:
        source = f"{self.settings.hotelbeds_api_key}{self.settings.hotelbeds_secret}{timestamp}"
        return hashlib.sha256(source.encode("utf-8")).hexdigest()

    def _ssl_context(self):
        context = ssl.create_default_context()
        context.load_cert_chain(
            certfile=self.settings.hotelbeds_client_cert,
            keyfile=self.settings.hotelbeds_client_key,
        )
        return context

    @staticmethod
    def _payload(request: HotelSearchRequest) -> dict:
        return {
            "stay": {
                "checkIn": request.check_in.isoformat(),
                "checkOut": request.check_out.isoformat(),
            },
            "occupancies": [{
                "rooms": request.rooms,
                "adults": request.adults,
                "children": 0,
            }],
            "hotels": {"hotel": request.hotel_codes},
        }

    @staticmethod
    def _rate_reference(rate_key: str, hotel_code: int) -> str:
        digest = hashlib.sha256(rate_key.encode("utf-8")).hexdigest()[:16]
        return f"hotelbeds-{hotel_code}-{digest}"

    def _parse(self, body: dict) -> list[HotelOffer]:
        offers = []
        for hotel in body.get("hotels", {}).get("hotels", []):
            try:
                hotel_code = int(hotel["code"])
            except (KeyError, TypeError, ValueError):
                continue
            hotel_name = str(hotel.get("name") or f"Hotelbeds {hotel_code}")
            for room in hotel.get("rooms", []):
                for rate in room.get("rates", []):
                    try:
                        amount = float(rate["net"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    rate_key = str(rate.get("rateKey", ""))
                    if not rate_key:
                        continue
                    offers.append(HotelOffer(
                        hotel_code=hotel_code,
                        hotel_name=hotel_name,
                        total_price=amount,
                        currency=str(rate.get("currency") or hotel.get("currency") or "UNKNOWN"),
                        rate_type=rate.get("rateType"),
                        quote_reference=self._rate_reference(rate_key, hotel_code),
                    ))
        return offers

    def search(self, request: HotelSearchRequest) -> HotelSearchResponse:
        self._validate_configuration()
        timestamp = int(self.now())
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Api-key": self.settings.hotelbeds_api_key,
            "X-Signature": self._signature(timestamp),
        }
        client_options = {
            "base_url": self.settings.hotelbeds_base_url.rstrip("/"),
            "timeout": self.settings.hotelbeds_timeout_seconds,
        }
        if self.transport is not None:
            client_options["transport"] = self.transport
        else:
            client_options["verify"] = self._ssl_context()

        try:
            with httpx.Client(**client_options) as client:
                response = client.post("/hotel-api/1.0/hotels", headers=headers, json=self._payload(request))
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPError as error:
            logger.warning("Hotelbeds availability request failed: %s", type(error).__name__)
            raise HotelbedsUpstreamError("Hotelbeds 上游服务不可用") from error
        except ValueError as error:
            raise HotelbedsResponseError("Hotelbeds 返回格式不可解析") from error

        if not isinstance(body, dict):
            raise HotelbedsResponseError("Hotelbeds 返回格式不可解析")
        return HotelSearchResponse(
            provider="hotelbeds",
            quoted_at=datetime.now(UTC),
            offers=self._parse(body),
        )
