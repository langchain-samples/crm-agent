# Tool design best practices

How the CRM tools in [`src/crm_agent/utils/tools.py`](../src/crm_agent/utils/tools.py)
are built, and why. Every principle below maps to a concrete tool so you can read
the rule and then read the code that follows it.

The CRM itself lives in [`src/crm_agent/crm.py`](../src/crm_agent/crm.py): one
declarative `SCHEMA` drives both the `get_crm_schema` tool and the validators, so
what the agent can *discover* is exactly what the system will *enforce*.

---

## 1. The docstring is the tool description — write it for the model

The model never sees your function body, only its name, signature, and docstring.
Treat the docstring as a prompt: say what the tool does, when to reach for it, and
what each argument means.

`get_crm_schema` opens with *"Call this FIRST when you are unsure which fields
exist…"* — that one line steers the agent to discover the schema instead of
guessing field names. `create_record`'s docstring tells the model not to pass
`id`/timestamps and to create referenced records first; that prevents whole
classes of failed calls before they happen.

## 2. Type every argument; return JSON-serializable data

Typed parameters (`entity: str`, `filters: dict | None`, `limit: int`) become the
tool's input schema, so the model is constrained to well-formed calls. Returns are
plain dicts/lists — never custom objects, datetimes, or anything that won't
serialize cleanly into the transcript.

## 3. Return failures as data, never as exceptions

A raised exception is dead weight in an agent loop: the model can't see it and
can't recover. Every CRM tool returns a uniform envelope instead:

```json
{"ok": true,  "record": { ... }}
{"ok": false, "errors": [{"field": "stage", "code": "enum",
                          "message": "stage must be one of: prospecting, …"}]}
```

`create_record`/`update_record` push *all* validation problems back at once, each
with a `field`, a machine-readable `code`, and a human-readable `message`. The
agent reads the list, fixes its arguments, and retries. Validation lives in
`crm.py` (`_validate`) and returns these structures directly — it never raises.

## 4. Give the agent an introspection tool

`get_crm_schema` returns, per field: type, whether it's required / read-only /
computed, the `allowed_values` for enums, the entity a reference points to, and
defaults. The agent can answer "what fields does a Deal have?" and learn the exact
enum spelling (`negotiation`, not `Negotiation`) without you hard-coding any of it
into the prompt. When the schema changes, the tool's output changes with it — no
prompt edit required.

## 5. Prefer a small generic surface over many narrow tools

We expose **five** tools — `get_crm_schema`, `search_records`, `get_record`,
`create_record`, `update_record` — that work across all four entities, rather than
~20 entity-specific tools (`create_contact`, `update_deal_stage`, …).

**Why generic here:** the operations are genuinely uniform (CRUD over a typed
schema), so one set of tools keeps the model's tool list short, avoids
near-duplicate descriptions the model has to disambiguate, and means a new entity
costs zero new tools. The `entity` argument plus `get_crm_schema` carries the
specificity.

**When to go narrow instead:** if an operation has its own preconditions, side
effects, or irreversibility (`refund_payment`, `send_contract`), give it a
dedicated tool with a focused description and arguments — don't bury it behind a
generic `do_action(kind=…)`. Narrow tools are also better when different
operations need very different guardrails or permissions.

## 6. Read before write; echo the full record back

`update_record` is a read-modify-write: only the fields you pass change, the rest
are untouched, and it returns the **complete** updated record (not just "ok") so
the agent can confirm the result and quote it back to the user. Pair it with
`search_records` → `get_record` to resolve a name into an id before mutating.

## 7. Own ids, timestamps, and computed fields — don't let the model set them

`id`, `created_at`, and `updated_at` are marked `readonly`; `deals.weighted_amount`
is `computed`. The tools reject any attempt to set them (`code: "readonly"`) and
the store assigns/derives them itself. `weighted_amount` is recomputed on every
write from `amount * probability / 100`, so it can never drift out of sync with
the fields it depends on.

## 8. Cap and shape results

`search_records` takes a `limit` (default 20) and returns `{"count", "records"}`.
Tools that can return unbounded data should always bound it — an agent that pulls
10,000 rows into context is a failure mode, not a feature. Expose filtering
(`filters`) so the agent narrows server-side rather than reading everything and
filtering in its head.

## 9. Surface and enforce constraints in the same place

Enum `allowed_values` and reference targets appear in `get_crm_schema` *and* are
enforced by the validators, because both read the one `SCHEMA`. The agent is never
told one set of rules while the system enforces another. A bad enum yields
`code: "enum"` with the allowed list inline; a dangling foreign key yields
`code: "ref"` naming the unknown id.

## 10. Name tools so they don't overlap

`get_record` (one, by id) vs `search_records` (many, by filter) vs `get_crm_schema`
(metadata, not data) are distinct enough that the model rarely picks the wrong one.
Avoid pairs whose descriptions could both plausibly answer the same request —
overlap is where tool-selection mistakes come from. Verb + noun, consistent across
the set (`get_/search_/create_/update_`), makes the intended use obvious.

---

### Quick checklist for a new tool

- [ ] Docstring written for the model: purpose, when to use, every arg explained.
- [ ] Arguments typed; return value JSON-serializable.
- [ ] Errors returned as structured data with `field` / `code` / `message`.
- [ ] No way to set ids, timestamps, or computed fields.
- [ ] Results bounded (limit/pagination) and filterable.
- [ ] Constraints the agent sees == constraints the system enforces.
- [ ] Name and description don't overlap an existing tool.
