"""The CRM DeepAgent.

All of the agent's *context* — its system prompt, its two skills, and its
long-term memory — lives in the LangSmith Hub, not in this repo. This module
pulls each of those at construction time and assembles them into a compiled
LangGraph graph exposed as the module-level ``agent``.

There is intentionally no local fallback: if the Hub is unreachable or the
workspace key is wrong, construction fails loudly at ``langgraph dev`` startup,
which is exactly when you want to find out.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import (
    CompositeBackend,
    ContextHubBackend,
    FilesystemBackend,
    StateBackend,
)
from langchain.chat_models import init_chat_model
from langsmith import Client

from crm_agent.utils.middleware import GuardrailMiddleware
from crm_agent.utils.tools import CRM_TOOLS

# Hub identifiers — the source of truth for this agent's context.
PROMPT_REPO = "crm-agent-prompt"
MEMORY_REPO = "crm-agent-memory"
SKILL_REPOS = ["crm-add-customer", "crm-advance-deal"]

_client = Client()


def _system_prompt() -> str:
    """Pull the caller-layer system prompt from the LangSmith Prompt Hub."""
    prompt = _client.pull_prompt(PROMPT_REPO)
    return prompt.messages[0].prompt.template


def _stage_skills() -> str:
    """Pull each skill repo from the Hub and stage it on a local temp filesystem
    as ``<skill>/SKILL.md``. Returns the root dir to mount at ``/skills/``.

    The temp dir is created with ``mkdtemp`` (not a context manager) so it lives
    for the whole process — the FilesystemBackend reads from it at runtime.
    """
    root = Path(tempfile.mkdtemp(prefix="crm_agent_skills_"))
    for handle in SKILL_REPOS:
        skill = _client.pull_skill(handle)
        skill_dir = root / handle
        skill_dir.mkdir(parents=True, exist_ok=True)
        for path, entry in skill.files.items():
            content = getattr(entry, "content", None)
            if content is None and isinstance(entry, dict):
                content = entry.get("content")
            (skill_dir / path).parent.mkdir(parents=True, exist_ok=True)
            (skill_dir / path).write_text(content or "", encoding="utf-8")
    return str(root)


def _backend() -> CompositeBackend:
    """Compose the agent's filesystem:

    * default  -> ephemeral scratch (todos, working notes) in graph state.
    * /skills/ -> the two Hub skills, staged locally and served read-only.
    * /memory/ -> durable, agent-writable memory in the Context Hub.
    """
    return CompositeBackend(
        default=StateBackend(),
        routes={
            "/skills/": FilesystemBackend(root_dir=_stage_skills(), virtual_mode=True),
            "/memory/": ContextHubBackend(MEMORY_REPO),
        },
    )


model = init_chat_model("claude-sonnet-4-6", model_provider="anthropic")

agent = create_deep_agent(
    model=model,
    tools=CRM_TOOLS,
    system_prompt=_system_prompt(),
    backend=_backend(),
    skills=["/skills/"],
    memory=["/memory/AGENTS.md"],
    middleware=[GuardrailMiddleware()],
    interrupt_on={"update_record": True},
).with_config({"recursion_limit": 50})
