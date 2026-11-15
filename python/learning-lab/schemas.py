from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from typing import Literal
from typing import Any, Literal

class TravelRequest(BaseModel):
    departure_city: str = Field(min_length=1)
    budget: float = Field(gt=0)
    days: int = Field(ge=1, le=30)
    interests: list[str] = Field(default_factory=list)
    knowledge_question: str = Field(
        default="我想找当地吃饭的地方",
        min_length=1,)
    
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
class HotelResult(BaseModel):
    city: str
    price_per_night: float = Field(gt=0)
    nights: int = Field(ge=0)
    total_cost: float = Field(ge=0)
    provider: str = "demo"
    quote_reference: str
    quoted_at: datetime
class BudgetResult(BaseModel):
    total_cost: float = Field(ge=0)
    remaining: float
    within_budget: bool
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

    
 
