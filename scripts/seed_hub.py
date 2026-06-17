"""Seed the CRM agent's LangSmith Hub context (run once per workspace).

The agent reads its system prompt, two skills, and long-term memory from the
LangSmith Hub and has no local fallback, so these repos must exist before the
agent can start. Run this once against your workspace:

    uv run python scripts/seed_hub.py

It is safe to re-run: each call commits a new version of the same repos. After
seeding, edit the content in LangSmith — the Hub is the source of truth, this
script is only a bootstrap.

Pushes:
  - Prompt Hub: crm-agent-prompt
  - Skill repos: crm-add-customer, crm-advance-deal
  - Agent repo:  crm-agent-memory (holds AGENTS.md)
  - Agent repo:  crm-agent (optional; links the two skills + memory for the Hub UI)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

if not os.environ.get("LANGSMITH_API_KEY"):
    sys.exit(
        "LANGSMITH_API_KEY is not set. Add a workspace-scoped key to .env "
        "(see .env.example) before seeding the Hub."
    )

from langchain_core.prompts import ChatPromptTemplate  # noqa: E402 - after load_dotenv
from langsmith import Client  # noqa: E402
from langsmith.schemas import FileEntry, SkillEntry  # noqa: E402
from langsmith.utils import LangSmithConflictError  # noqa: E402


def _push(label: str, fn) -> None:
    """Run a push, treating an unchanged-content 409 as already-seeded."""
    try:
        print(f"{label}:", fn())
    except LangSmithConflictError as exc:
        if "Nothing to commit" in str(exc):
            print(f"{label}: unchanged (already seeded)")
        else:
            raise

# NB: keep the system prompt free of { } braces — it is stored as a
# ChatPromptTemplate and bare braces would be parsed as template variables.
SYSTEM_PROMPT = """\
You are the CRM Operations Assistant. You help a sales team read and maintain
records in a CRM with four entities: contacts, companies, deals, and activities.

You have five tools:
- get_crm_schema: discover entities, fields, which are required, and allowed enum
  values.
- search_records: find records by exact-match filters (use this to turn a name or
  email into an id).
- get_record: read one record in full by id.
- create_record: create a record after validating it.
- update_record: change fields on an existing record.

Operating principles:
- Discover, do not guess. If you are unsure which fields exist or what an enum
  accepts, call get_crm_schema before writing. Never invent field names, ids, or
  enum values.
- Resolve before you act. Look up records with search_records to get their ids
  before reading or updating them.
- Respect references and order. A reference field (such as company_id or
  contact_id) must point at a record that already exists, so create the referenced
  record first.
- Errors are data. Tools return ok:false with an errors list on failure. Read each
  error, correct the offending fields, and retry — do not give up after one try.
- Confirm changes. After a create or update, report the key fields back to the
  user, including any computed values such as a deal's weighted_amount.
- Never set ids, timestamps, or computed fields; the system owns those.

For multi-step procedures, consult your skills in /skills/ — for example,
onboarding a new customer or advancing a deal through the pipeline. Your standing
conventions live in /memory/AGENTS.md and are always loaded; keep them up to date
as you learn how this team works.
"""

ADD_CUSTOMER_SKILL = """\
---
name: crm-add-customer
description: Onboard a brand-new customer end to end — create the company, its primary contact, and an optional opening deal, in the correct order, with the right links between them.
---

# Onboard a new customer

Use this when asked to add a new customer, account, or company that does not exist
in the CRM yet. Records must be created in dependency order so the links resolve.

## Steps

1. **Check the schema** (once): call `get_crm_schema("companies")`,
   `get_crm_schema("contacts")`, and, if a deal is involved, `get_crm_schema("deals")`
   to confirm required fields and allowed enum values.

2. **Avoid duplicates**: `search_records("companies", {"name": <name>})`. If a match
   already exists, stop and ask the user whether to use it instead of creating a new one.

3. **Create the company first**: `create_record("companies", {...})`.
   - Required: `name`.
   - Helpful: `domain`, `industry` (enum), `employee_count`, `tier`, `is_target_account`.
   - Keep the returned `id` — the contact and deal will reference it.

4. **Create the primary contact**: `create_record("contacts", {...})`.
   - Required: `first_name`, `last_name`, `email`.
   - Set `company_id` to the company id from step 3.
   - Set `lifecycle_stage` to `customer` for a closed customer, or `sql` if it is
     still an opportunity. Set `owner` to the rep (see /memory/AGENTS.md for the default).

5. **(Optional) Opening deal**: if the user mentions a deal value or opportunity,
   `create_record("deals", {...})` with `name`, `amount`, `company_id`, and
   `contact_id` from the steps above. `weighted_amount` is computed for you.

6. **Confirm**: report the new company, contact, and deal ids and their key fields.

## Common pitfalls

- Setting `company_id` on the contact before the company exists → ref error. Create
  the company first.
- Guessing an `industry` or `lifecycle_stage` value → enum error. Use the values
  from `get_crm_schema`.
- Passing `id`/`created_at` → readonly error. Let the system assign them.
"""

ADVANCE_DEAL_SKILL = """\
---
name: crm-advance-deal
description: Advance a deal to a new pipeline stage and log the change as an activity — a multi-tool sequence (look up, read, update, then log).
---

# Advance a deal through the pipeline

Use this when asked to move, progress, or update the stage of a deal. It is a
sequence of tool calls, in order.

## Steps

1. **Find the deal**: `search_records("deals", {"name": <name>})` (or by another
   filter) to get its `id`. If several match, ask the user which one.

2. **Read current state**: `get_record("deals", <id>)` so you can report the
   before/after and know the current stage, amount, and probability.

3. **Confirm valid stages**: `get_crm_schema("deals")` and use the exact `stage`
   enum values (e.g. `prospecting`, `qualification`, `proposal`, `negotiation`,
   `closed_won`, `closed_lost`).

4. **Update the deal**: `update_record("deals", <id>, {...})` with the new `stage`
   and, if given, `probability` and `close_date`. `weighted_amount` recomputes
   automatically from `amount` and `probability`.
   - If the deal is moving to `closed_won`, set `probability` to 100; for
     `closed_lost`, set it to 0.

5. **Log the change**: `create_record("activities", {...})` with `type: "note"`, a
   `subject` like "Stage moved to negotiation", `notes` describing the before/after,
   `related_entity: "deals"`, and `related_id: <id>`.

6. **Report**: summarize the old stage → new stage, the new probability, and the new
   weighted_amount.

## Common pitfalls

- Updating before resolving the id → "not found". Always search/get first.
- Trying to set `weighted_amount` directly → readonly error. Change `amount` or
  `probability` instead.
- Capitalized or misspelled stage values → enum error. Copy them from the schema.
"""

AGENTS_MD = """\
# CRM team conventions

These notes are always loaded. Keep them short and update them as you learn how
this team operates.

## Defaults
- Default deal currency is USD.
- When an owner is not specified, set `owner` to `daniel`.
- New tags should be lowercase.

## Lifecycle stages (contacts)
- `lead` -> `mql` -> `sql` -> `customer`; `churned` for lost customers.
- A person at a signed customer should be `customer`; an active opportunity is `sql`.

## Pipeline stages (deals)
- prospecting -> qualification -> proposal -> negotiation -> closed_won / closed_lost.
- closed_won implies probability 100; closed_lost implies probability 0.

## House rules
- Always log a note activity when you change a deal's stage.
- Confirm record ids back to the user after any create or update.
"""


def main() -> None:
    client = Client()

    prompt_obj = ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT)])
    _push("prompt crm-agent-prompt", lambda: client.push_prompt(
        "crm-agent-prompt",
        object=prompt_obj,
        description="System prompt for the CRM operations agent.",
        tags=["crm"],
    ))

    _push("skill crm-add-customer", lambda: client.push_skill(
        "crm-add-customer",
        files={"SKILL.md": FileEntry(content=ADD_CUSTOMER_SKILL)},
        description="Onboard a new customer: company + primary contact + optional opening deal, in order.",
        tags=["crm"],
    ))

    _push("skill crm-advance-deal", lambda: client.push_skill(
        "crm-advance-deal",
        files={"SKILL.md": FileEntry(content=ADVANCE_DEAL_SKILL)},
        description="Advance a deal to a new pipeline stage and log the change as an activity.",
        tags=["crm"],
    ))

    _push("memory crm-agent-memory", lambda: client.push_agent(
        "crm-agent-memory",
        files={"AGENTS.md": FileEntry(content=AGENTS_MD)},
        description="Long-term memory for the CRM agent (team conventions).",
        tags=["crm"],
    ))

    # Optional: an agent repo that links everything, for the Hub UI composition view.
    try:
        _push("agent crm-agent (linked)", lambda: client.push_agent(
            "crm-agent",
            files={
                "AGENTS.md": FileEntry(content=AGENTS_MD),
                "skills/add-customer": SkillEntry(repo_handle="crm-add-customer"),
                "skills/advance-deal": SkillEntry(repo_handle="crm-advance-deal"),
            },
            description="CRM agent bundle linking its skills and memory.",
            tags=["crm"],
        ))
    except Exception as exc:  # noqa: BLE001 - optional convenience, never block seeding
        print("optional linked agent repo skipped:", exc)


if __name__ == "__main__":
    main()
