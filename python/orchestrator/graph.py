"""LangGraph owns fan-out/fan-in and the bounded budget feedback loop."""

import asyncio
import hashlib
import json
from typing import TypedDict

import httpx
from langgraph.graph import END, START, StateGraph

from agents import (
    ActivityAgent, BudgetAgent, DestinationAgent, FlightAgent, HotelAgent, PreferenceAgent,
)
from models.schemas import PlanningState, TravelPlanState, UserPreferences
from services.rag import Citation, KnowledgeBase, SummaryGenerator
from services.settings import AppSettings


class GraphState(TypedDict, total=False):
    request: dict
    travel: dict
    flight_result: dict
    hotel_result: dict
    activity_result: dict
    citations: list[dict]
    plan: dict
    summary: dict


class TravelGraph:
    def __init__(self, settings: AppSettings, store, knowledge: KnowledgeBase,
                 generator: SummaryGenerator):
        self.settings = settings
        self.store = store
        self.knowledge = knowledge
        self.generator = generator
        self.agents = {
            "flight_result": FlightAgent(), "hotel_result": HotelAgent(),
            "activity_result": ActivityAgent(),
        }
        graph = StateGraph(GraphState)
        graph.add_node("preferences", self.preferences)
        graph.add_node("destination", self.destination)
        for name in self.agents:
            graph.add_node(name, self._make_tool(name))
        graph.add_node("knowledge", self.retrieve)
        graph.add_node("budget", self.budget)
        graph.add_node("adjust", self.adjust)
        graph.add_node("summarize", self.summarize)
        graph.add_edge(START, "preferences")
        graph.add_edge("preferences", "destination")
        branches = [*self.agents, "knowledge"]
        for name in branches:
            graph.add_edge("destination", name)
        graph.add_edge(branches, "budget")
        graph.add_conditional_edges("budget", self.route_budget,
                                    {"adjust": "adjust", "summarize": "summarize"})
        graph.add_edge("adjust", "budget")
        graph.add_edge("summarize", END)
        self.graph = graph.compile()

    async def preferences(self, state: GraphState):
        travel = TravelPlanState(preferences=UserPreferences.model_validate(state["request"]))
        travel = await PreferenceAgent().execute(travel)
        return {"travel": travel.model_dump(mode="json")}

    async def destination(self, state: GraphState):
        travel = TravelPlanState.model_validate(state["travel"])
        travel = await DestinationAgent().execute(travel)
        return {"travel": travel.model_dump(mode="json")}

    def _make_tool(self, name):
        async def run(state: GraphState):
            # Each branch gets its own Pydantic object and writes a distinct graph channel.
            travel = TravelPlanState.model_validate(state["travel"])
            cache_key = hashlib.sha256(json.dumps(
                {"version": "mock-candidates-v2", "tool": name, "travel": state["travel"]},
                sort_keys=True, ensure_ascii=False,
            ).encode()).hexdigest()
            cached = await self.store.cache_get(cache_key)
            if cached is not None:
                return {name: cached}
            for attempt in range(self.settings.tool_attempts):
                try:
                    result = await asyncio.wait_for(
                        self.agents[name].execute(travel.model_copy(deep=True)),
                        timeout=self.settings.tool_timeout,
                    )
                    value = getattr(result, name)
                    if value is None:
                        raise ValueError(f"{name} returned no result")
                    encoded = value.model_dump(mode="json")
                    await self.store.cache_set(cache_key, encoded, self.settings.cache_ttl)
                    return {name: encoded}
                except (TimeoutError, httpx.TransportError):
                    if attempt + 1 == self.settings.tool_attempts:
                        raise
                    await asyncio.sleep(0.05 * (attempt + 1))
        return run

    async def retrieve(self, state: GraphState):
        travel = TravelPlanState.model_validate(state["travel"])
        request = state["request"]
        question = request.get("knowledge_question") or " ".join(
            [*travel.preferences.interests, request.get("notes", "")]
        )
        hits = await self.knowledge.search(travel.selected_destination.city, question)
        return {"citations": [hit.model_dump() for hit in hits]}

    async def budget(self, state: GraphState):
        if "plan" in state:
            travel = TravelPlanState.model_validate(state["plan"])
        else:
            travel = TravelPlanState.model_validate({
                **state["travel"], **{name: state[name] for name in self.agents},
                "max_adjustments": self.settings.max_adjustments,
            })
        travel.state = PlanningState.BUDGET_CHECKING
        travel = await BudgetAgent().execute(travel)
        return {"plan": travel.model_dump(mode="json")}

    @staticmethod
    def route_budget(state: GraphState):
        return "adjust" if state["plan"]["state"] == "adjusting" else "summarize"

    @staticmethod
    async def adjust(state: GraphState):
        # BudgetAgent selected candidates in the last step. Preserve them for the next check.
        return {"plan": state["plan"]}

    async def summarize(self, state: GraphState):
        plan = TravelPlanState.model_validate(state["plan"])
        answer = await self.generator.generate(
            plan.selected_destination.city,
            [Citation.model_validate(c) for c in state["citations"]], state["plan"],
        )
        return {"summary": answer.model_dump()}
