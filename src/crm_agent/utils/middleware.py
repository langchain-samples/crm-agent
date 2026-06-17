"""A simple deterministic input guardrail.

Some policies should hold regardless of what the model decides to do, so they
belong in code, not the prompt. This guardrail inspects the latest user message
before the model runs and refuses a small set of destructive / out-of-scope
requests, ending the run immediately. It is deterministic and adds no extra LLM
call — which is the point of a guardrail.
"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware, AgentState, hook_config
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

BLOCKED_PHRASES = (
    "delete all",
    "drop table",
    "wipe the",
    "erase everything",
    "ignore previous instructions",
    "ignore all previous",
)

REFUSAL = (
    "I can't help with that. I can read and update individual CRM records, but I "
    "won't run bulk deletions, destructive operations, or instructions that try to "
    "override my role. Tell me which record you'd like to view or change."
)


class GuardrailMiddleware(AgentMiddleware):
    """Refuse destructive or out-of-scope requests before the model is called."""

    @hook_config(can_jump_to=["end"])
    def before_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        last_user = next(
            (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
            None,
        )
        if last_user is None:
            return None
        text = (
            last_user.content
            if isinstance(last_user.content, str)
            else str(last_user.content)
        )
        if any(phrase in text.lower() for phrase in BLOCKED_PHRASES):
            return {"messages": [AIMessage(REFUSAL)], "jump_to": "end"}
        return None
