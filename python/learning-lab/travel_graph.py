from langgraph.graph import StateGraph, START, END
from collections.abc import Callable
from knowledge_agent import KnowledgeAgent
from schemas import KnowledgeChunk
from schemas import PlanningState, TravelRequest
from preference_agent import PreferenceAgent
from destination_agent import DestinationAgent
from flight_agent import FlightAgent
from hotel_agent import HotelAgent
from activity_agent import ActivityAgent
from budget_agent import BudgetAgent
from answer_agent import AnswerAgent

flight_agent = FlightAgent()
hotel_agent = HotelAgent()
activity_agent = ActivityAgent()
budget_agent = BudgetAgent()
knowledge_agent = KnowledgeAgent()
preference_agent = PreferenceAgent()
destination_agent = DestinationAgent()
answer_agent = AnswerAgent()
def collect_preferences(state: PlanningState):
    result = preference_agent.run(state.preferences)
    return {"preferences": result}


def recommend_destination(state: PlanningState):
    result = destination_agent.run(state.preferences)
    return {"destination": result}
def search_flight(state: PlanningState):
    result = flight_agent.run(
        state.preferences,
        state.destination,
    )
    return {"flight": result}


def search_hotel(state: PlanningState):
    result = hotel_agent.run(
        state.preferences,
        state.destination,
    )
    return {"hotel": result}


def plan_activity(state: PlanningState):
    result = activity_agent.run(
        state.preferences,
        state.destination,
        
    )
    return {"activity": result}


def check_budget(state: PlanningState):
    result = budget_agent.run(state)
    return {"budget_result": result}

def route_after_budget(state: PlanningState):
    if state.budget_result.within_budget is None:
        return "budget_unverified"
    if state.budget_result.within_budget:
        return "completed"

    if state.adjustment_count < 2:
        return "adjust"

    return "over_budget"


def finish_plan(state: PlanningState):
    return {"status": "completed"}


def report_over_budget(state: PlanningState):
    return {"status": "over_budget"}

def adjust_activity(state: PlanningState):
    if state.adjustment_count == 0:
        plan_type = "economy"
    else:
        plan_type = "free"

    result = activity_agent.run(
        state.preferences,
        state.destination,
        plan_type=plan_type,
    )

    return {
        "activity": result,
        "adjustment_count": state.adjustment_count + 1,
    }
def retrieve_knowledge(state: PlanningState):
    matches = knowledge_agent.run(
        city=state.destination.city,
        question=state.preferences.knowledge_question,
    )

    chunks = []

    for item in matches:
        chunk = KnowledgeChunk.model_validate(item)
        chunks.append(chunk)

    return {"knowledge": chunks}
def generate_answer(state: PlanningState, on_retry=None):
    result = answer_agent.run(
        question=state.preferences.knowledge_question,
        chunks=state.knowledge,
        on_retry=on_retry,
    )

    return {"knowledge_answer": result}


def build_graph(
    on_node_complete: Callable[[str], None] | None = None,
    on_node_retry: Callable[[str, int, Exception], None] | None = None,
):
    """构建图；回调仅在节点正常返回后执行。"""
    def tracked(node_name: str, handler):
        def wrapped(state: PlanningState):
            update = handler(state)
            if on_node_complete is not None:
                on_node_complete(node_name)
            return update
        return wrapped

    builder = StateGraph(PlanningState)
    builder.add_node("preferences", tracked("preferences", collect_preferences))
    builder.add_node("destination", tracked("destination", recommend_destination))
    builder.add_node("flight", tracked("flight", search_flight))
    builder.add_node("hotel", tracked("hotel", search_hotel))
    builder.add_node("activity", tracked("activity", plan_activity))
    builder.add_node("budget", tracked("budget", check_budget))
    builder.add_node("completed", tracked("completed", finish_plan))
    builder.add_node("over_budget", tracked("over_budget", report_over_budget))
    builder.add_node("budget_unverified", tracked("budget_unverified", lambda state: {"status": "budget_unverified"}))
    builder.add_node("adjust", tracked("adjust", adjust_activity))
    builder.add_node("knowledge", tracked("knowledge", retrieve_knowledge))
    def answer_with_retry_event(state: PlanningState):
        return generate_answer(
            state,
            on_retry=(
                (lambda attempt, error: on_node_retry("answer", attempt, error))
                if on_node_retry is not None else None
            ),
        )
    builder.add_node("answer", tracked("answer", answer_with_retry_event))

    builder.add_edge(START, "preferences")
    builder.add_edge("preferences", "destination")
    builder.add_edge("destination", "flight")
    builder.add_edge("destination", "hotel")
    builder.add_edge("destination", "activity")
    builder.add_edge("destination", "knowledge")
    builder.add_edge(["flight", "hotel", "activity", "knowledge"], "budget")
    builder.add_conditional_edges(
        "budget",
        route_after_budget,
        {
            "completed": "completed",
            "adjust": "adjust",
            "over_budget": "over_budget",
            "budget_unverified": "budget_unverified",
        },
    )
    builder.add_edge("adjust", "budget")
    builder.add_edge("completed", "answer")
    builder.add_edge("over_budget", "answer")
    builder.add_edge("budget_unverified", "answer")
    builder.add_edge("answer", END)

    return builder.compile()


# 保留默认图，方便直接运行本文件或旧代码导入。
graph = build_graph()

if __name__ == "__main__":
    request = TravelRequest(
        departure_city="北京",
        budget=2500,
        days=5,
    )

    initial_state = PlanningState(preferences=request)

    output = graph.invoke(initial_state)

    result = PlanningState.model_validate(output)

    print(result.model_dump_json(indent=2))
