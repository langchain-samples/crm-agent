"""Minimal offline eval for the CRM agent (OPTIONAL).

Runs a few CRM tasks through the compiled agent and scores them with deterministic
code evaluators — did the agent call the right tool, and did the CRM end up in the
expected state? No LLM judge, no golden dataset required.

Run:  uv run evals/run_eval.py

This script loads ``.env`` itself, so you do not need ``--env-file``. It needs the
same env as the agent (ANTHROPIC_API_KEY + a workspace-scoped LANGSMITH_API_KEY),
because importing the agent pulls its prompt/skills from the Hub. Note: if the
LangSmith key is missing, the SDK does not raise a clear auth error — it sends an
unauthenticated request and returns a confusing 404 "Commit not found" for the
prompt pull. We load the key up front and check for it so the failure is obvious.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env BEFORE importing the agent: importing crm_agent.agent constructs the
# graph, which pulls the prompt/skills from the Hub and therefore needs the key.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

if not os.environ.get("LANGSMITH_API_KEY"):
    sys.exit(
        "LANGSMITH_API_KEY is not set. Add a workspace-scoped key to .env "
        "(see .env.example). Without it the Hub pull fails with a misleading "
        "404 'Commit not found'."
    )

from langchain_core.messages import AIMessage  # noqa: E402 - must follow load_dotenv
from langsmith import Client, evaluate  # noqa: E402

from crm_agent import crm  # noqa: E402
from crm_agent.agent import agent  # noqa: E402

EXAMPLES = [
    {
        "inputs": {"question": "What fields does a Deal have, and what are the allowed stages?"},
        "expect_tool": "get_crm_schema",
    },
    {
        "inputs": {"question": "Create a new company named Initech in the saas industry."},
        "expect_tool": "create_record",
        "expect_company": "Initech",
    },
]


def target(inputs: dict) -> dict:
    """Invoke the agent and flatten the graph state into simple fields."""
    result = agent.invoke({"messages": [("user", inputs["question"])]})
    messages = result["messages"]
    tool_calls = [
        tc["name"]
        for m in messages
        if isinstance(m, AIMessage)
        for tc in (m.tool_calls or [])
    ]
    answer = next(
        (m.content for m in reversed(messages) if isinstance(m, AIMessage) and m.content),
        "",
    )
    return {"answer": answer, "tool_calls": tool_calls}


def called_expected_tool(inputs, outputs, reference_outputs) -> dict:
    expected = reference_outputs.get("expect_tool")
    score = int(expected in outputs.get("tool_calls", [])) if expected else 1
    return {
        "key": "called_expected_tool",
        "score": score,
        "comment": f"expected={expected}, called={outputs.get('tool_calls')}",
    }


def company_created(inputs, outputs, reference_outputs) -> dict:
    name = reference_outputs.get("expect_company")
    if not name:
        return {"key": "company_created", "score": 1, "comment": "n/a"}
    found = bool(crm.search_records("companies", {"name": name}))
    return {"key": "company_created", "score": int(found), "comment": f"{name} present={found}"}


def main() -> None:
    client = Client()
    dataset_name = "crm-agent-smoke"
    if not client.has_dataset(dataset_name=dataset_name):
        ds = client.create_dataset(dataset_name=dataset_name)
        client.create_examples(
            dataset_id=ds.id,
            inputs=[e["inputs"] for e in EXAMPLES],
            outputs=[{k: v for k, v in e.items() if k != "inputs"} for e in EXAMPLES],
        )

    evaluate(
        target,
        data=dataset_name,
        evaluators=[called_expected_tool, company_created],
        experiment_prefix="crm-agent",
        max_concurrency=1,  # shared writable CRM/memory backend — avoid races
    )


if __name__ == "__main__":
    main()
