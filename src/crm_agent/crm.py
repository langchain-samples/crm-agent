"""A dummy in-memory CRM.

This module is the single source of truth for both the data and its *shape*.
The ``SCHEMA`` dict declares every entity and field once; the validators and the
``get_crm_schema`` tool both read from it, so the agent can discover exactly what
the validators will enforce. There is no database — records live in module-level
dicts and reset whenever the process restarts.

Mutations return ``(record, errors)``. Errors are returned as structured data
(never raised) so the agent can read them, fix its arguments, and retry.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# --- Field type vocabulary -------------------------------------------------
# Each field declares a `type` from this set. Validation is driven entirely by
# the schema below, so adding a field never requires touching the validators.
#   string   free text
#   email    text containing "@"
#   phone    free text (kept loose on purpose)
#   int      whole number (bools rejected)
#   currency non-negative number (int or float)
#   percent  int in [0, 100]
#   date     "YYYY-MM-DD"
#   bool     true/false
#   list     list of strings (e.g. tags)
#   enum     one of `enum` values
#   ref      id of a record in `ref` entity


def _field(
    type: str,
    *,
    required: bool = False,
    readonly: bool = False,
    computed: bool = False,
    enum: list[str] | None = None,
    ref: str | None = None,
    default: Any = None,
    description: str = "",
) -> dict[str, Any]:
    return {
        "type": type,
        "required": required,
        "readonly": readonly,
        "computed": computed,
        "enum": enum,
        "ref": ref,
        "default": default,
        "description": description,
    }


SCHEMA: dict[str, dict[str, Any]] = {
    "contacts": {
        "label": "Contact",
        "id_prefix": "cont",
        "fields": {
            "id": _field("string", readonly=True, description="Stable record id."),
            "first_name": _field("string", required=True, description="Given name."),
            "last_name": _field("string", required=True, description="Family name."),
            "email": _field("email", required=True, description="Primary email."),
            "phone": _field("phone", description="Phone number, any format."),
            "title": _field("string", description="Job title."),
            "lifecycle_stage": _field(
                "enum",
                enum=["lead", "mql", "sql", "customer", "churned"],
                default="lead",
                description="Where the contact sits in the funnel.",
            ),
            "owner": _field("string", description="Sales rep who owns the contact."),
            "company_id": _field(
                "ref", ref="companies", description="Company this contact belongs to."
            ),
            "tags": _field("list", default=[], description="Free-form labels."),
            "created_at": _field("date", readonly=True),
            "updated_at": _field("date", readonly=True),
        },
    },
    "companies": {
        "label": "Company",
        "id_prefix": "comp",
        "fields": {
            "id": _field("string", readonly=True, description="Stable record id."),
            "name": _field("string", required=True, description="Company name."),
            "domain": _field("string", description="Primary web domain."),
            "industry": _field(
                "enum",
                enum=["saas", "fintech", "healthcare", "ecommerce", "manufacturing", "other"],
                description="Industry vertical.",
            ),
            "employee_count": _field("int", description="Headcount."),
            "annual_revenue": _field("currency", description="Annual revenue, USD."),
            "tier": _field(
                "enum",
                enum=["A", "B", "C"],
                description="Account tier (A = strategic).",
            ),
            "is_target_account": _field(
                "bool", default=False, description="Flagged for outbound focus."
            ),
            "tags": _field("list", default=[], description="Free-form labels."),
            "created_at": _field("date", readonly=True),
            "updated_at": _field("date", readonly=True),
        },
    },
    "deals": {
        "label": "Deal",
        "id_prefix": "deal",
        "fields": {
            "id": _field("string", readonly=True, description="Stable record id."),
            "name": _field("string", required=True, description="Deal name."),
            "stage": _field(
                "enum",
                enum=[
                    "prospecting",
                    "qualification",
                    "proposal",
                    "negotiation",
                    "closed_won",
                    "closed_lost",
                ],
                default="prospecting",
                description="Pipeline stage.",
            ),
            "amount": _field("currency", required=True, description="Total deal value."),
            "currency": _field(
                "enum", enum=["USD", "EUR", "GBP"], default="USD", description="Deal currency."
            ),
            "probability": _field(
                "percent", default=10, description="Win probability, 0-100."
            ),
            "close_date": _field("date", description="Expected close date."),
            "contact_id": _field(
                "ref", ref="contacts", description="Primary contact on the deal."
            ),
            "company_id": _field("ref", ref="companies", description="Company on the deal."),
            "weighted_amount": _field(
                "currency",
                computed=True,
                readonly=True,
                description="amount * probability / 100. Recomputed on every write.",
            ),
            "created_at": _field("date", readonly=True),
            "updated_at": _field("date", readonly=True),
        },
    },
    "activities": {
        "label": "Activity",
        "id_prefix": "act",
        "fields": {
            "id": _field("string", readonly=True, description="Stable record id."),
            "type": _field(
                "enum",
                enum=["call", "email", "meeting", "note", "task"],
                required=True,
                description="Kind of activity.",
            ),
            "subject": _field("string", required=True, description="Short summary line."),
            "notes": _field("string", description="Longer free-form notes."),
            "due_date": _field("date", description="Due date for tasks."),
            "completed": _field("bool", default=False, description="Whether it is done."),
            "related_entity": _field(
                "enum",
                enum=["contacts", "companies", "deals"],
                description="Which entity `related_id` points at.",
            ),
            "related_id": _field(
                "ref",
                ref="*",
                description="Id of the related record (entity given by `related_entity`).",
            ),
            "created_at": _field("date", readonly=True),
            "updated_at": _field("date", readonly=True),
        },
    },
}


# --- Store -----------------------------------------------------------------

_STORE: dict[str, dict[str, dict[str, Any]]] = {entity: {} for entity in SCHEMA}
_COUNTERS: dict[str, int] = {entity: 0 for entity in SCHEMA}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _next_id(entity: str) -> str:
    _COUNTERS[entity] += 1
    return f"{SCHEMA[entity]['id_prefix']}_{_COUNTERS[entity]:03d}"


# --- Validation ------------------------------------------------------------


def _err(field: str | None, code: str, message: str) -> dict[str, str]:
    return {"field": field, "code": code, "message": message}


def _valid_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _check_type(entity: str, name: str, spec: dict[str, Any], value: Any) -> list[dict]:
    """Validate one field value against its spec. Returns a list of errors."""
    t = spec["type"]
    if value is None:
        return []
    if t in ("string", "phone"):
        if not isinstance(value, str):
            return [_err(name, "type", f"{name} must be a string.")]
    elif t == "email":
        if not isinstance(value, str) or "@" not in value:
            return [_err(name, "type", f"{name} must be a valid email address.")]
    elif t == "int":
        if not isinstance(value, int) or isinstance(value, bool):
            return [_err(name, "type", f"{name} must be a whole number.")]
    elif t == "currency":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return [_err(name, "type", f"{name} must be a number.")]
        if value < 0:
            return [_err(name, "range", f"{name} must be non-negative.")]
    elif t == "percent":
        if not isinstance(value, int) or isinstance(value, bool):
            return [_err(name, "type", f"{name} must be a whole number.")]
        if not 0 <= value <= 100:
            return [_err(name, "range", f"{name} must be between 0 and 100.")]
    elif t == "date":
        if not _valid_date(value):
            return [_err(name, "type", f"{name} must be a date formatted YYYY-MM-DD.")]
    elif t == "bool":
        if not isinstance(value, bool):
            return [_err(name, "type", f"{name} must be true or false.")]
    elif t == "list":
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            return [_err(name, "type", f"{name} must be a list of strings.")]
    elif t == "enum":
        if value not in spec["enum"]:
            allowed = ", ".join(spec["enum"])
            return [_err(name, "enum", f"{name} must be one of: {allowed}.")]
    elif t == "ref":
        return _check_ref(entity, name, spec, value)
    return []


def _check_ref(entity: str, name: str, spec: dict[str, Any], value: Any) -> list[dict]:
    if not isinstance(value, str):
        return [_err(name, "type", f"{name} must be a record id (string).")]
    target = spec["ref"]
    if target == "*":  # dynamic ref (activities.related_id)
        return []  # cross-checked against related_entity in _validate
    if value not in _STORE[target]:
        return [_err(name, "ref", f"{name} references unknown {target} id '{value}'.")]
    return []


def _validate(entity: str, fields: dict[str, Any], *, partial: bool) -> list[dict]:
    """Validate a create (partial=False) or update (partial=True) payload."""
    errors: list[dict] = []
    spec_fields = SCHEMA[entity]["fields"]

    for name, value in fields.items():
        if name not in spec_fields:
            errors.append(_err(name, "unknown", f"{entity} has no field '{name}'."))
            continue
        spec = spec_fields[name]
        if spec["readonly"] or spec["computed"]:
            errors.append(
                _err(name, "readonly", f"{name} is read-only and cannot be set.")
            )
            continue
        errors.extend(_check_type(entity, name, spec, value))

    # Required fields must be present on create.
    if not partial:
        for name, spec in spec_fields.items():
            if spec["required"] and fields.get(name) in (None, ""):
                errors.append(_err(name, "required", f"{name} is required."))

    # Dynamic ref cross-check for activities.
    if entity == "activities" and fields.get("related_id"):
        rel = fields.get("related_entity")
        if not rel:
            errors.append(
                _err(
                    "related_entity",
                    "required",
                    "related_entity is required when related_id is set.",
                )
            )
        elif rel in _STORE and fields["related_id"] not in _STORE[rel]:
            errors.append(
                _err(
                    "related_id",
                    "ref",
                    f"related_id references unknown {rel} id '{fields['related_id']}'.",
                )
            )

    return errors


# --- Computed fields -------------------------------------------------------


def _apply_computed(entity: str, record: dict[str, Any]) -> None:
    if entity == "deals":
        amount = record.get("amount") or 0
        probability = record.get("probability") or 0
        record["weighted_amount"] = round(amount * probability / 100, 2)


# --- Public operations -----------------------------------------------------


def list_entities() -> list[str]:
    return list(SCHEMA)


def get_schema(entity: str | None = None) -> dict[str, Any]:
    """Return the schema for one entity or all entities."""
    if entity is None:
        return {name: get_schema(name) for name in SCHEMA}
    if entity not in SCHEMA:
        return {"error": f"Unknown entity '{entity}'. Known: {', '.join(SCHEMA)}."}
    meta = SCHEMA[entity]
    fields = {}
    for name, spec in meta["fields"].items():
        info = {"type": spec["type"]}
        if spec["required"]:
            info["required"] = True
        if spec["readonly"]:
            info["readonly"] = True
        if spec["computed"]:
            info["computed"] = True
        if spec["enum"]:
            info["allowed_values"] = spec["enum"]
        if spec["ref"]:
            info["references"] = spec["ref"]
        if spec["default"] is not None:
            info["default"] = spec["default"]
        if spec["description"]:
            info["description"] = spec["description"]
        fields[name] = info
    return {"entity": entity, "label": meta["label"], "fields": fields}


def get_record(entity: str, record_id: str) -> dict[str, Any] | None:
    if entity not in SCHEMA:
        return None
    record = _STORE[entity].get(record_id)
    return dict(record) if record else None


def search_records(
    entity: str, filters: dict[str, Any] | None = None, limit: int = 20
) -> list[dict[str, Any]]:
    if entity not in SCHEMA:
        return []
    filters = filters or {}
    results = []
    for record in _STORE[entity].values():
        if all(record.get(k) == v for k, v in filters.items()):
            results.append(dict(record))
        if len(results) >= limit:
            break
    return results


def create_record(
    entity: str, fields: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[dict]]:
    if entity not in SCHEMA:
        return None, [_err(None, "unknown_entity", f"Unknown entity '{entity}'.")]
    errors = _validate(entity, fields, partial=False)
    if errors:
        return None, errors

    record: dict[str, Any] = {}
    for name, spec in SCHEMA[entity]["fields"].items():
        if name in fields:
            record[name] = fields[name]
        elif spec["default"] is not None:
            record[name] = spec["default"]
        elif not spec["readonly"] and not spec["computed"]:
            record[name] = None

    record["id"] = _next_id(entity)
    record["created_at"] = _now()
    record["updated_at"] = record["created_at"]
    _apply_computed(entity, record)
    _STORE[entity][record["id"]] = record
    return dict(record), []


def update_record(
    entity: str, record_id: str, fields: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[dict]]:
    if entity not in SCHEMA:
        return None, [_err(None, "unknown_entity", f"Unknown entity '{entity}'.")]
    record = _STORE[entity].get(record_id)
    if record is None:
        return None, [_err(None, "not_found", f"No {entity} with id '{record_id}'.")]
    errors = _validate(entity, fields, partial=True)
    if errors:
        return None, errors

    record.update(fields)
    record["updated_at"] = _now()
    _apply_computed(entity, record)
    return dict(record), []


# --- Seed data -------------------------------------------------------------


def _seed() -> None:
    if any(_STORE.values()):
        return

    acme, _ = create_record(
        "companies",
        {
            "name": "Acme Corp",
            "domain": "acme.com",
            "industry": "manufacturing",
            "employee_count": 1200,
            "annual_revenue": 85_000_000,
            "tier": "A",
            "is_target_account": True,
            "tags": ["strategic", "midwest"],
        },
    )
    globex, _ = create_record(
        "companies",
        {
            "name": "Globex",
            "domain": "globex.io",
            "industry": "saas",
            "employee_count": 240,
            "annual_revenue": 18_000_000,
            "tier": "B",
        },
    )

    jane, _ = create_record(
        "contacts",
        {
            "first_name": "Jane",
            "last_name": "Diaz",
            "email": "jane.diaz@acme.com",
            "title": "VP Operations",
            "lifecycle_stage": "sql",
            "owner": "daniel",
            "company_id": acme["id"],
            "tags": ["champion"],
        },
    )
    create_record(
        "contacts",
        {
            "first_name": "Sam",
            "last_name": "Okafor",
            "email": "sam@globex.io",
            "title": "Eng Manager",
            "lifecycle_stage": "mql",
            "owner": "daniel",
            "company_id": globex["id"],
        },
    )

    create_record(
        "deals",
        {
            "name": "Acme platform rollout",
            "stage": "qualification",
            "amount": 120_000,
            "probability": 40,
            "close_date": "2026-09-30",
            "contact_id": jane["id"],
            "company_id": acme["id"],
        },
    )
    create_record(
        "deals",
        {
            "name": "Globex pilot",
            "stage": "proposal",
            "amount": 45_000,
            "probability": 55,
            "close_date": "2026-08-15",
            "company_id": globex["id"],
        },
    )

    create_record(
        "activities",
        {
            "type": "call",
            "subject": "Discovery call with Jane",
            "notes": "Discussed rollout timeline and procurement.",
            "completed": True,
            "related_entity": "contacts",
            "related_id": jane["id"],
        },
    )


_seed()
