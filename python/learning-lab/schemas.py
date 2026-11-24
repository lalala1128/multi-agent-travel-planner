from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

class TravelRequest(BaseModel):
    departure_city: str = Field(min_length=1)
    destination_city: str | None = Field(default=None, min_length=1, max_length=80)
    flight_total_cny: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    hotel_total_cny: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    daily_spending_cny: float | None = Field(default=None, ge=0, allow_inf_nan=False,
                                             description="每天固定预留的餐饮、当地交通和活动总额")
    budget: float = Field(gt=0)
    days: int = Field(ge=1, le=30)
    interests: list[str] = Field(default_factory=list)
    include_knowledge: bool = True
    hotel_check_in: date | None = Field(default=None, description="提供入住日期时按推荐城市查询 Hotelbeds，按一位成人一间房、days - 1 晚计算。")
    knowledge_question: str = Field(
        default="我想找当地吃饭的地方",
        min_length=1,)

    @model_validator(mode="after")
    def validate_hotel_stay(self):
        if self.destination_city:
            self.destination_city = self.destination_city.strip()
            if not self.destination_city:
                raise ValueError("目的地不能为空")
            if self.destination_city not in {"东京", "首尔", "清迈"} and (
                self.hotel_total_cny is None or self.flight_total_cny is None or self.daily_spending_cny is None
            ):
                raise ValueError("该城市支持手填预算，请填写机票、住宿和每日当地开销")
        if (self.flight_total_cny is not None or self.hotel_total_cny is not None) and not self.destination_city:
            raise ValueError("录入机票或住宿报价时，请指定对应目的地")
        if self.hotel_total_cny is not None and self.days < 2:
            raise ValueError("录入住宿费用至少需要一晚")
        if self.hotel_check_in and self.days < 2:
            raise ValueError("酒店询价至少需要一晚住宿，请设置 days >= 2")
        return self

class DestinationRecommendation(BaseModel):
    city: str
    reason: str
    daily_budget: float
class FlightResult(BaseModel):
    departure_city: str
    arrival_city: str
    round_trip_cost: float = Field(gt=0)
    provider: str = "demo"
    quote_reference: str
    quoted_at: datetime
class RankedHotel(BaseModel):
    hotel_code: int
    hotel_name: str
    quote_reference: str
    total_price: float
    currency: str
    total_cny: Decimal


class HotelResult(BaseModel):
    city: str
    price_per_night: float = Field(ge=0)
    currency: str = "CNY"
    hotel_name: str | None = None
    hotel_code: int | None = None
    shortlist: list[RankedHotel] = Field(default_factory=list)
    unpriced_offer_count: int = 0
    conversion: "HotelConversion | None" = None
    nights: int = Field(ge=0)
    total_cost: float = Field(ge=0)
    provider: str = "demo"
    quote_reference: str
    quoted_at: datetime
class HotelSearchRequest(BaseModel):
    check_in: date
    check_out: date
    hotel_codes: list[int] = Field(min_length=1, max_length=20)
    adults: int = Field(default=1, ge=1, le=9)
    rooms: int = Field(default=1, ge=1, le=9)

    @model_validator(mode="after")
    def validate_stay(self):
        if self.check_out <= self.check_in:
            raise ValueError("离店日期必须晚于入住日期")
        return self

class HotelOffer(BaseModel):
    hotel_code: int
    hotel_name: str
    total_price: float = Field(ge=0)
    currency: str
    rate_type: str | None = None
    quote_reference: str

class HotelSearchResponse(BaseModel):
    provider: str
    quoted_at: datetime
    offers: list[HotelOffer]
class HotelConversion(BaseModel):
    source_currency: str
    cny_per_unit: Decimal = Field(gt=0)
    rate_date: date
    source: Literal["ECB"] = "ECB"
    amount_cny: Decimal = Field(ge=0)


class BudgetRound(BaseModel):
    round_index: int = Field(ge=0)
    activity_plan: str
    flight_cny: Decimal
    hotel_cny: Decimal
    activity_cny: Decimal
    total_cny: Decimal
    saved_since_previous_cny: Decimal | None


class BudgetResult(BaseModel):
    total_cost: float | None = Field(ge=0)
    remaining: float | None
    within_budget: bool | None
    currency: Literal["CNY"] = "CNY"
    rounds: list[BudgetRound] = Field(default_factory=list)
    hotel_budget_limit_cny: Decimal | None = Field(default=None, ge=0, description="固定本轮航班和活动后，整段住宿可用的最高金额；预算无法核算或其他费用已超预算时为空。")
    hotel_conversion: HotelConversion | None = None
    reason: Literal["no_hotel_offer", "currency_mismatch", "exchange_rate_unavailable"] | None = None
class ActivityResult(BaseModel):
    city: str
    plan_type: str = "standard"
    daily_cost: float = Field(ge=0)
    total_cost: float = Field(ge=0)
    provider: str = "demo"
    quote_reference: str
    quoted_at: datetime
class KnowledgeChunk(BaseModel):
    id: str
    city: str
    source: str
    chunk_index: int
    text: str
    score: float
class GroundedAnswer(BaseModel):
    answer: str = Field(min_length=1)
    citations: list[str]
class PlanningState(BaseModel):
    preferences: TravelRequest
    destination: DestinationRecommendation | None = None
    flight: FlightResult | None = None
    hotel: HotelResult | None = None
    budget_result: BudgetResult | None = None
    activity: ActivityResult | None = None
    status: str = "planning"
    adjustment_count: int = Field(default=0, ge=0)
    knowledge: list[KnowledgeChunk] = Field(default_factory=list)
    knowledge_answer: GroundedAnswer | None = None


class TaskRecord(BaseModel):
    id: str
    status: Literal["queued", "running", "succeeded", "failed"] = "queued"
    request: TravelRequest
    result: PlanningState | None = None
    error: str | None = None
    error_stage: str | None = None
    error_location: str | None = None
    created_at: datetime
    updated_at: datetime
class TaskEvent(BaseModel):
    id: int = Field(ge=1)
    event: Literal["queued", "running", "progress", "succeeded", "failed"]
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    @field_validator("data", mode="before")
    @classmethod
    def normalize_lua_empty_object(cls, value):
        # Redis Lua cjson 会把空 table 编码为 []；事件语义仍应是空对象。
        return {} if value == [] else value

    
 
