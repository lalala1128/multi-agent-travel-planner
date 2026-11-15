"""供应商报价适配层。

工作流只依赖这里的统一接口。当前默认实现是可重复的演示报价；生产环境
必须将 ``TRAVEL_PROVIDER`` 切换为经过审核、已配置凭据的真实适配器。
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from settings import load_settings


class ProviderConfigurationError(RuntimeError):
    """请求了真实报价，但对应供应商尚未完成配置。"""


@dataclass(frozen=True)
class Quote:
    amount: float
    provider: str
    quote_reference: str
    quoted_at: datetime


class DemoTravelProvider:
    """只用于流程、预算回路和自动化测试的确定性报价实现。"""

    name = "demo"
    _flight_prices = {"清迈": 1600, "首尔": 1800, "东京": 2500}

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    def flight(self, departure_city: str, arrival_city: str) -> Quote:
        try:
            amount = self._flight_prices[arrival_city]
        except KeyError as error:
            raise ProviderConfigurationError(f"演示供应商不支持目的地：{arrival_city}") from error
        return Quote(amount, self.name, f"demo-flight-{arrival_city}", self._now())

    def hotel(self, city: str, nights: int) -> Quote:
        return Quote(300, self.name, f"demo-hotel-{city}-{nights}n", self._now())

    def activity(self, city: str, plan_type: str) -> Quote:
        prices = {"standard": 200, "economy": 100, "free": 0}
        if plan_type not in prices:
            raise ValueError("不支持的活动方案")
        return Quote(prices[plan_type], self.name, f"demo-activity-{city}-{plan_type}", self._now())


class LiveProviderNotConfigured:
    """防止把演示数据悄悄当作实时价格返回。"""

    def __init__(self, provider_name: str):
        self.provider_name = provider_name

    def _raise(self):
        raise ProviderConfigurationError(
            f"供应商 {self.provider_name} 未配置。需要实现适配器、配置凭据，并提供出行日期与乘客数。"
        )

    def flight(self, departure_city: str, arrival_city: str) -> Quote:
        self._raise()

    def hotel(self, city: str, nights: int) -> Quote:
        self._raise()

    def activity(self, city: str, plan_type: str) -> Quote:
        self._raise()


def create_travel_provider():
    provider_name = load_settings().travel_provider
    if provider_name == "demo":
        return DemoTravelProvider()
    return LiveProviderNotConfigured(provider_name)
