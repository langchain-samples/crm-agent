# CRM Agent

A [DeepAgents](https://docs.langchain.com/oss/python/deepagents) agent that reads,
creates, and edits records in a dummy multi-entity CRM (Contacts, Companies, Deals,
Activities). It is a worked example of two things:

1. **Tool design** — the CRM tools are built as best-practice exemplars. See
   [`docs/TOOL_DESIGN.md`](docs/TOOL_DESIGN.md).
2. **Context Hub** — the system prompt, two task skills, and long-term memory all
   live in the LangSmith Hub, not in this repo. The agent pulls them at startup.

## Layout

```
src/crm_agent/
  agent.py           compiled graph `agent`; pulls prompt/skills/memory from the Hub
  crm.py             dummy in-memory CRM: one SCHEMA drives data + validation
  utils/tools.py     get_crm_schema / search / get / create / update
  utils/middleware.py  step-budget guard
docs/TOOL_DESIGN.md  tool-creation best practices
evals/run_eval.py    optional offline eval
Makefile             make dev / make deploy
```

The agent's context is hosted in LangSmith as four repos:
`crm-agent-prompt` (Prompt Hub), `crm-add-customer` + `crm-advance-deal` (skill
repos), and `crm-agent-memory` (agent repo, holds `AGENTS.md`). There is **no local
copy** — edit them in LangSmith.

## Run it

```bash
uv sync
cp .env.example .env      # fill in ANTHROPIC_API_KEY and a workspace LANGSMITH_API_KEY
```

The Hub repos must exist before the agent can start (no local fallback). If you
have not seeded them yet, run your one-time seed script, then:

```bash
make dev      # uv run langgraph dev — local server + LangGraph Studio
```

This opens LangGraph Studio. Try:

- *"What fields does a Deal have?"* → calls `get_crm_schema`.
- *"Add Acme Corp as a new customer with contact jane@acme.com"* → loads the
  **crm-add-customer** skill.
- *"Move the Globex pilot to negotiation at 60%, closing next month"* → loads the
  **crm-advance-deal** skill (look up → update → log an activity).

To deploy the graph to a LangSmith Deployment (Beta — requires LangSmith auth and
deployment config):

```bash
make deploy   # uv run langgraph deploy
```

## Notes

- **Model**: calls Anthropic directly (`claude-sonnet-4-6`). If you have
  `ANTHROPIC_BASE_URL` set globally, unset it for this app or it will be routed
  through that proxy.
- **LangSmith auth**: use a **workspace-scoped** key. An org/multi-workspace key
  resolves no tenant — set `LANGSMITH_WORKSPACE_ID` as well in that case.
- The CRM is in-memory and reseeds on every process restart.
