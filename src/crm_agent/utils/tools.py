"""CRM tools for the agent.

These five tools are deliberately small, generic, and composable rather than one
narrow tool per entity/operation. That design choice — and the conventions every
tool follows — is documented in ``docs/TOOL_DESIGN.md``. In short:

* The docstring is the description the model reads, so it is written for the model.
* Arguments are typed; returns are JSON-serializable dicts.
* Failures come back as data (``{"ok": False, "errors": [...]}``), never as raised
  exceptions, so the agent can read the problem and retry with fixed arguments.
* ``get_crm_schema`` lets the agent discover fields and allowed enum values instead
  of guessing them.
"""

from __future__ import annotations

from typing import Any

from crm_agent import crm

VALID_ENTITIES = "contacts, companies, deals, activities"


def get_crm_schema(entity: str | None = None) -> dict[str, Any]:
    """Describe the CRM's entities and fields. Call this FIRST when you are unsure
    which fields exist, which are required, or what values an enum field accepts.

    For each field it returns the type and, when relevant, whether it is required,
    read-only, or computed; the allowed values for enum fields; the entity a
    reference field points to; and any default. Read-only and computed fields
    (ids, timestamps, deals.weighted_amount) cannot be set via create or update.

    Args:
        entity: One of contacts, companies, deals, activities. Omit to get the
            schema for every entity at once.

    Returns:
        The schema for the requested entity, or for all entities when omitted.
    """
    return crm.get_schema(entity)


def search_records(
    entity: str, filters: dict[str, Any] | None = None, limit: int = 20
) -> dict[str, Any]:
    """Find records of an entity, optionally filtered by exact field matches.

    Use this to look up a record's id before reading or updating it (for example,
    find a deal by name, or all contacts at a company).

    Args:
        entity: One of contacts, companies, deals, activities.
        filters: Optional map of field -> exact value to match (e.g.
            {"stage": "proposal"} or {"company_id": "comp_001"}). All conditions
            must match. Omit to return the first records of the entity.
        limit: Maximum number of records to return (default 20).

    Returns:
        {"ok": True, "count": N, "records": [...]} on success, or
        {"ok": False, "errors": [...]} if the entity is unknown.
    """
    if entity not in crm.SCHEMA:
        return _unknown_entity(entity)
    records = crm.search_records(entity, filters, limit)
    return {"ok": True, "count": len(records), "records": records}


def get_record(entity: str, record_id: str) -> dict[str, Any]:
    """Read a single record in full by its id.

    Args:
        entity: One of contacts, companies, deals, activities.
        record_id: The record's id (e.g. "deal_001"). Use search_records first if
            you only know a name or email.

    Returns:
        {"ok": True, "record": {...}} on success, or
        {"ok": False, "errors": [...]} if the entity or id is unknown.
    """
    if entity not in crm.SCHEMA:
        return _unknown_entity(entity)
    record = crm.get_record(entity, record_id)
    if record is None:
        return {
            "ok": False,
            "errors": [
                {
                    "field": None,
                    "code": "not_found",
                    "message": f"No {entity} with id '{record_id}'.",
                }
            ],
        }
    return {"ok": True, "record": record}


def create_record(entity: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Create a new record. Validates all fields before writing.

    Call get_crm_schema(entity) first if unsure which fields are required or what
    enum values are allowed. Do not pass id, created_at, updated_at, or any
    computed field — they are set automatically. Reference fields (e.g.
    company_id, contact_id) must point at ids that already exist, so create
    referenced records first.

    Args:
        entity: One of contacts, companies, deals, activities.
        fields: Map of field name -> value for the new record.

    Returns:
        {"ok": True, "record": {...}} with the created record (including its new
        id and computed fields), or {"ok": False, "errors": [...]} listing each
        validation problem so you can fix the fields and retry.
    """
    if entity not in crm.SCHEMA:
        return _unknown_entity(entity)
    record, errors = crm.create_record(entity, fields)
    if errors:
        return {"ok": False, "errors": errors}
    return {"ok": True, "record": record}


def update_record(
    entity: str, record_id: str, fields: dict[str, Any]
) -> dict[str, Any]:
    """Update fields on an existing record. Validates before writing and returns
    the full updated record so you can confirm the change.

    Only the fields you pass are changed; everything else is left as-is. You
    cannot set read-only or computed fields (ids, timestamps,
    deals.weighted_amount) — weighted_amount is recomputed automatically when you
    change a deal's amount or probability.

    Args:
        entity: One of contacts, companies, deals, activities.
        record_id: The id of the record to update.
        fields: Map of field name -> new value.

    Returns:
        {"ok": True, "record": {...}} with the full updated record, or
        {"ok": False, "errors": [...]} if the record is missing or a value is
        invalid.
    """
    if entity not in crm.SCHEMA:
        return _unknown_entity(entity)
    record, errors = crm.update_record(entity, record_id, fields)
    if errors:
        return {"ok": False, "errors": errors}
    return {"ok": True, "record": record}


def _unknown_entity(entity: str) -> dict[str, Any]:
    return {
        "ok": False,
        "errors": [
            {
                "field": "entity",
                "code": "unknown_entity",
                "message": f"Unknown entity '{entity}'. Valid entities: {VALID_ENTITIES}.",
            }
        ],
    }


CRM_TOOLS = [
    get_crm_schema,
    search_records,
    get_record,
    create_record,
    update_record,
]
