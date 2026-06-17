"""A step-budget guard.

DeepAgents defaults ``recursion_limit`` to 9999, so a non-converging agent can
loop almost indefinitely. We set a real ``recursion_limit`` in ``agent.py`` as a
hard backstop, and this middleware provides a *soft* one: once the agent has taken
roughly ``max_ai_messages`` turns, it injects a system message telling the model to
stop calling tools and give its best final answer. ``create_agent`` has no
``remaining_steps`` to read, so we count AIMessages in the running state.
"""

from __future__ import annotations

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, SystemMessage


class StepBudgetMiddleware(AgentMiddleware):
    """Force a clean final answer as the agent approaches its turn budget."""

    def __init__(self, max_ai_messages: int = 20) -> None:
        super().__init__()
        self.max_ai_messages = max_ai_messages

    def before_model(self, state, runtime):  # noqa: ANN001 - middleware hook signature
        messages = state.get("messages", [])
        ai_turns = sum(1 for m in messages if isinstance(m, AIMessage))
        if ai_turns >= self.max_ai_messages:
            return {
                "messages": [
                    SystemMessage(
                        content=(
                            "You have reached your step budget. Do not call any more "
                            "tools. Summarize what you accomplished, report anything "
                            "left undone, and give your final answer now."
                        )
                    )
                ]
            }
        return None
