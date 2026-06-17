# CRM Agent

## Overview

A [Deep Agents](https://docs.langchain.com/oss/python/deepagents) agent that reads,
creates, and edits records in a dummy multi-entity CRM (Contacts, Companies, Deals,
Activities). It is a worked example of two things: **tool design** — the CRM tools
are built as best-practice exemplars (see [`docs/TOOL_DESIGN.md`](docs/TOOL_DESIGN.md))
— and the **LangSmith Context Hub**, where the agent's system prompt, two task
skills, and long-term memory all live (not in this repo), pulled at startup. It also
shows a deterministic guardrail middleware and human-in-the-loop interrupts on file
writes.

### Layout

```
src/crm_agent/
  agent.py             compiled graph `agent`; pulls prompt/skills/memory from the Hub
  crm.py               dummy in-memory CRM: one SCHEMA drives data + validation
  utils/tools.py       get_crm_schema / search / get / create / update
  utils/middleware.py  guardrail middleware (refuses destructive requests)
docs/TOOL_DESIGN.md    tool-creation best practices
evals/run_eval.py      optional offline eval
scripts/seed_hub.py    one-time: create the agent's Hub repos in your workspace
Makefile               make dev / make deploy
```

The agent's context is hosted in LangSmith as four repos: `crm-agent-prompt`
(Prompt Hub), `crm-add-customer` + `crm-advance-deal` (skill repos), and
`crm-agent-memory` (agent repo, holds `AGENTS.md`). There is **no local copy** —
once seeded, edit them in LangSmith.

## Quickstart

Prerequisites: [uv](https://docs.astral.sh/uv/), an Anthropic API key, and a
**workspace-scoped** LangSmith API key.

```bash
uv sync
cp .env.example .env      # fill in ANTHROPIC_API_KEY and LANGSMITH_API_KEY
```

Seed the Context Hub once (creates the prompt, two skills, and memory repos in your
LangSmith workspace). The agent has no local fallback, so this must run before first
launch:

```bash
uv run python scripts/seed_hub.py
```

Run the agent locally in LangGraph Studio:

```bash
make dev                  # uv run langgraph dev
```

Then try, in Studio:

- *"What fields does a Deal have?"* → calls `get_crm_schema`.
- *"Add Acme Corp as a new customer with contact jane@acme.com"* → loads the
  **crm-add-customer** skill.
- *"Move the Globex pilot to negotiation at 60%, closing next month"* → loads the
  **crm-advance-deal** skill (look up → update → log an activity).

Deploy the graph to a LangSmith Deployment (Beta — requires LangSmith auth and
deployment config):

```bash
make deploy               # uv run langgraph deploy
```

## Configuration

Set in `.env` (see [`.env.example`](.env.example)):

| Variable | Required | Purpose |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | yes | The agent calls Anthropic directly (`claude-sonnet-4-6`). |
| `LANGSMITH_API_KEY` | yes | **Workspace-scoped** key for the workspace holding the Hub repos. |
| `LANGSMITH_TRACING` | no | `true` to send traces to LangSmith. |
| `LANGSMITH_PROJECT` | no | Trace project name. |
| `LANGSMITH_WORKSPACE_ID` | no | Only if your key is org/multi-workspace scoped (else Hub pulls 404). |

To change the model, edit the `init_chat_model(...)` call in
[`src/crm_agent/agent.py`](src/crm_agent/agent.py).

## Additional notes

- **In-memory CRM**: the dummy CRM resets and reseeds on every process restart.
- **Guardrail**: a `before_model` middleware deterministically refuses destructive /
  out-of-scope requests (bulk deletes, prompt-injection attempts).
- **Human-in-the-loop**: `interrupt_on={"write_file": True, "edit_file": True}` pauses
  for approval before the agent writes or edits any file (e.g. updating its own
  `/memory/AGENTS.md`). The checkpointer needed to pause/resume is supplied by the
  runtime (`langgraph dev` / a LangSmith Deployment); approve or reject in LangGraph
  Studio. Routine CRM reads/writes go through the tools, not the filesystem, so they
  are *not* interrupted.
- **Anthropic base URL**: if you have `ANTHROPIC_BASE_URL` set globally, unset it for
  this app or the model calls will be routed through that proxy.
- **Evals** (optional): `uv run evals/run_eval.py` runs a small offline eval.

## License

Released under the [MIT License](LICENSE).
