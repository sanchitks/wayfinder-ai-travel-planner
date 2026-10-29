"""LangGraph wiring: orchestrator -> (parallel workers) -> compile.

    START -> orchestrator --(targets)--> logistics ----\
                         \-------------> accommodation -> compile -> END
                          \------------> experience ---/
                           \---(none)-------------------^

State is checkpointed per session (thread_id), which is what makes surgical
refinement possible: unchanged worker results persist between turns.
"""

from __future__ import annotations

import inspect

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from .. import models
from . import state as state_mod
from .accommodation import accommodation_node
from .experience import experience_node
from .logistics import logistics_node
from .orchestrator import compile_node, orchestrator_node, route_workers
from .state import PlannerState


def _pydantic_types(*modules) -> list[tuple[str, str]]:
    return [
        (mod.__name__, name)
        for mod in modules
        for name, obj in vars(mod).items()
        if inspect.isclass(obj) and issubclass(obj, BaseModel) and obj.__module__ == mod.__name__
    ]


def build_graph():
    builder = StateGraph(PlannerState)
    builder.add_node("orchestrator", orchestrator_node)
    builder.add_node("logistics", logistics_node)
    builder.add_node("accommodation", accommodation_node)
    builder.add_node("experience", experience_node)
    builder.add_node("compile", compile_node)

    builder.add_edge(START, "orchestrator")
    builder.add_conditional_edges("orchestrator", route_workers, ["logistics", "accommodation", "experience", "compile", END])
    for worker in ("logistics", "accommodation", "experience"):
        builder.add_edge(worker, "compile")
    builder.add_edge("compile", END)

    serde = JsonPlusSerializer(allowed_msgpack_modules=_pydantic_types(models, state_mod))
    return builder.compile(checkpointer=InMemorySaver(serde=serde))


planner = build_graph()
