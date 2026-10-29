"""Required fields of the DA form, read from the register metadata.

The section UI schemas (g2p_register_sections.section_ui_schema) say which
widgets are required (widget-required) and what they are called
(widget-label). That is the one place the rule lives: the staff UI marks the
field, the save and finalize checks (required_fields_mixin.py) and the domain
validator (g2p_register_domain_service_da.py) read the same flag. Making a
field optional is a metadata change, not a code change.

A widget may also carry widget-data-options.actions, a list of
{"action": "show" | "hide" | "require", "condition": {...}}. A hidden widget
is never required; a "require" action makes a widget required while its
condition holds. A condition is {"field", "operator", "value"} (operators
equals, notEquals, in, notIn, empty, notEmpty, contains) or a group
{"and": [...]}, {"or": [...]}, {"not": {...}}.

A widget's data path names the field: "<register_id>.email", or for the geo
widget {"value": "<register_id>.geo_lowest_level_value_id", "hierarchy": ...}.
"""

from __future__ import annotations

import time
from typing import Any

DA_REGISTER_ID = "6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90"
_CACHE_SECONDS = 300


def _field_of(path: Any) -> str | None:
    if isinstance(path, str) and path.strip():
        return path.rsplit(".", 1)[-1].strip() or None
    return None


def _fields_of(path: Any) -> list[str]:
    if isinstance(path, dict):
        return [f for f in (_field_of(v) for v in path.values()) if f]
    field = _field_of(path)
    return [field] if field else []


def _walk(node: Any):
    if isinstance(node, dict):
        if "widget-data-path" in node:
            yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def fields_in_schema(section_ui_schema: Any) -> list[str]:
    """Every field a section's widgets write, in widget order."""
    out: list[str] = []
    for widget in _walk(section_ui_schema):
        for field in _fields_of(widget.get("widget-data-path")):
            if field not in out:
                out.append(field)
    return out


def required_fields_in_schema(section_ui_schema: Any) -> dict[str, str]:
    """{field: label} for the widgets a section marks required."""
    out: dict[str, str] = {}
    for widget in _walk(section_ui_schema):
        if widget.get("widget-readonly") or not widget.get("widget-required"):
            continue
        label = str(widget.get("widget-label") or "").strip()
        for field in _fields_of(widget.get("widget-data-path")):
            out.setdefault(field, label or field.replace("_", " ").title())
    return out


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def missing_labels(required: dict[str, str], record: dict, *, absent_is_missing: bool) -> list[str]:
    """Labels of required fields the record does not fill. With
    absent_is_missing a field the record does not mention counts as empty
    (a new record, or a whole submission); without it only fields the
    record sets to blank count (a partial update)."""
    labels: list[str] = []
    for field, label in required.items():
        if field in record:
            if is_blank(record.get(field)) and label not in labels:
                labels.append(label)
        elif absent_is_missing and label not in labels:
            labels.append(label)
    return labels




# --------------------------------------------------------------- conditions --
def _lookup(record: dict, path: Any) -> Any:
    """A condition's field is a path such as "<register>.species"; the record
    is flat, so the last segment names the value."""
    if not isinstance(path, str):
        return None
    if path in record:
        return record.get(path)
    return record.get(path.rsplit(".", 1)[-1])


def _same(a: Any, b: Any) -> bool:
    if is_blank(a) and is_blank(b):
        return True
    if isinstance(a, bool) or isinstance(b, bool):
        return str(a).lower() == str(b).lower()
    return a == b or str(a) == str(b)


def evaluate_condition(condition: Any, record: dict) -> bool | None:
    """Whether a widget condition holds for the record; None when the condition
    uses something this evaluator does not know (callers then lean towards
    checking the field)."""
    if not isinstance(condition, dict):
        return None
    for key in ("and", "or"):
        if isinstance(condition.get(key), list):
            results = [evaluate_condition(c, record) for c in condition[key]]
            if key == "and":
                if any(r is False for r in results):
                    return False
                return None if any(r is None for r in results) else True
            if any(r is True for r in results):
                return True
            return None if any(r is None for r in results) else False
    if "not" in condition:
        inner = evaluate_condition(condition["not"], record)
        return None if inner is None else not inner
    operator = condition.get("operator")
    value = _lookup(record, condition.get("field"))
    expected = condition.get("value")
    if operator == "empty":
        return is_blank(value)
    if operator == "notEmpty":
        return not is_blank(value)
    if operator == "equals":
        return _same(value, expected)
    if operator == "notEquals":
        return not _same(value, expected)
    if operator in ("in", "notIn"):
        options = expected if isinstance(expected, (list, tuple, set)) else [expected]
        found = any(_same(value, option) for option in options)
        return found if operator == "in" else not found
    if operator == "contains":
        if isinstance(value, (list, tuple, set)):
            return any(_same(item, expected) for item in value)
        return value is not None and str(expected).lower() in str(value).lower()
    return None


def _actions(options: Any, name: str) -> list[dict]:
    actions = options.get("actions") if isinstance(options, dict) else None
    return [a for a in actions or [] if isinstance(a, dict) and a.get("action") == name]


def is_visible(options: Any, record: dict) -> bool:
    """A hide action that holds hides the widget; with show actions it is
    visible only while one of them holds. Without actions it is visible."""
    for action in _actions(options, "hide"):
        if evaluate_condition(action.get("condition"), record) is True:
            return False
    shows = _actions(options, "show")
    if shows:
        return any(evaluate_condition(a.get("condition"), record) is not False for a in shows)
    return True


def is_required(static: Any, options: Any, record: dict) -> bool:
    if static:
        return True
    return any(evaluate_condition(a.get("condition"), record) is not False for a in _actions(options, "require"))


def _title(key: str) -> str:
    return key.replace("_", " ").replace("-", " ").strip().title()


def _widgets(schema: Any):
    """(fields, label, static_required, options, columns) per input widget."""
    for widget in _walk(schema):
        if widget.get("widget-readonly"):
            continue
        columns = [c for c in widget.get("widget-data-columns") or [] if isinstance(c, dict) and c.get("column-key")]
        yield (
            _fields_of(widget.get("widget-data-path")),
            str(widget.get("widget-label") or "").strip(),
            widget.get("widget-required"),
            widget.get("widget-data-options"),
            columns,
        )


def has_requirements(schema: Any) -> bool:
    """Whether any widget of the schema is, or can become, required."""
    for _fields, _label, static, options, columns in _widgets(schema):
        if static or _actions(options, "require"):
            return True
        if any(c.get("widget-required") or _actions(c.get("widget-data-options"), "require") for c in columns):
            return True
    return False


def problems(schema: Any, record: dict, *, absent_is_missing: bool) -> list[str]:
    """What a record leaves unfilled in a section, as readable phrases:
    "fill in Mobile Number", "add at least one Contacts row",
    "Contacts row 2: fill in Phone". Hidden widgets are skipped.
    absent_is_missing as in missing_labels."""
    fill: list[str] = []
    extra: list[str] = []
    for fields, label, static, options, columns in _widgets(schema):
        if not fields or not is_visible(options, record):
            continue
        required = is_required(static, options, record)
        name = label or _title(fields[0])
        if columns:
            field = fields[0]
            if field not in record and not absent_is_missing:
                continue
            rows = [r for r in (record.get(field) or []) if isinstance(r, dict)]
            if required and not rows:
                extra.append(f"add at least one {name} row")
            for number, row in enumerate(rows, 1):
                missing = []
                for column in columns:
                    key = column["column-key"]
                    if not is_visible(column.get("widget-data-options"), row):
                        continue
                    if is_required(column.get("widget-required"), column.get("widget-data-options"), row) \
                            and is_blank(row.get(key)):
                        missing.append(str(column.get("column-label") or column.get("widget-label") or _title(key)))
                if missing:
                    extra.append(f"{name} row {number}: fill in " + ", ".join(missing))
            continue
        if not required:
            continue
        if any((f in record and is_blank(record.get(f))) or (f not in record and absent_is_missing) for f in fields):
            if name not in fill:
                fill.append(name)
    return (["fill in " + ", ".join(fill)] if fill else []) + extra


def describe(section_name: str, phrases: list[str]) -> str:
    return f"{section_name}: " + "; ".join(phrases)


def section_name_of(section: Any) -> str:
    """A readable section name from its description or mnemonic."""
    text = str(getattr(section, "section_description", "") or getattr(section, "section_mnemonic", "") or "")
    return text.strip() or "Section"


_cache: dict[str, tuple[float, list[tuple[str, Any, bool]]]] = {}


def set_sections_for_tests(register_id: str, sections: list[tuple[str, Any, bool]] | None) -> None:
    if sections is None:
        _cache.pop(register_id, None)
    else:
        _cache[register_id] = (float("inf"), list(sections))


async def load_sections(register_id: str = DA_REGISTER_ID) -> list[tuple[str, Any, bool]]:
    """(name, ui schema, is_list) for every section of a register, from the DB."""
    hit = _cache.get(register_id)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    from openg2p_fastapi_common.context import get_async_session_maker
    from openg2p_registry_core.models import G2PRegisterSection
    from sqlalchemy import select

    async with get_async_session_maker()() as session:
        rows = (await session.execute(
            select(G2PRegisterSection).where(G2PRegisterSection.register_id == register_id)
            .order_by(G2PRegisterSection.section_weightage)
        )).scalars().all()
    sections = [(section_name_of(r), r.section_ui_schema, bool(r.is_list)) for r in rows]
    _cache[register_id] = (time.monotonic() + _CACHE_SECONDS, sections)
    return sections


def load_sections_sync(session: Any, register_id: str = DA_REGISTER_ID) -> list[tuple[str, Any, bool]]:
    """load_sections for the synchronous enrichers, which get a plain Session."""
    hit = _cache.get(register_id)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    from openg2p_registry_core.models import G2PRegisterSection
    from sqlalchemy import select

    rows = session.execute(
        select(G2PRegisterSection).where(G2PRegisterSection.register_id == register_id)
        .order_by(G2PRegisterSection.section_weightage)
    ).scalars().all()
    sections = [(section_name_of(r), r.section_ui_schema, bool(r.is_list)) for r in rows]
    _cache[register_id] = (time.monotonic() + _CACHE_SECONDS, sections)
    return sections


def incomplete_reason(record: dict, sections: list[tuple[str, Any, bool]]) -> str | None:
    """The reason "Required: <Section>: fill in <Field>; ..." for a whole record that
    leaves required, visible fields empty; None when it is complete."""
    found = []
    for name, schema, _is_list in sections:
        phrases = problems(schema, record, absent_is_missing=True)
        if phrases:
            found.append(describe(name, phrases))
    return "Required: " + "; ".join(found) if found else None
