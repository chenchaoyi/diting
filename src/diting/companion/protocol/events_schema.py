"""Runtime event-shape validation + JSON-Schema generation.

``validate_event`` is the conformance primitive: it checks one decoded
event object against :data:`EVENT_SPEC`. diting-mobile mirrors this
behaviour in Dart against the vendored ``event.schema.json``, which
``build_json_schema`` produces from the same spec — one source, two
artifacts, no drift.
"""

from __future__ import annotations

import re
from typing import Any

from ._schema_spec import EVENT_SPEC, TS_PATTERN
from .errors import ProtocolError

_TS_RE = re.compile(TS_PATTERN)


def _tag_ok(value: Any, tag: str) -> bool:
    if tag == "str":
        return isinstance(value, str)
    if tag == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if tag == "num":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if tag == "bool":
        return isinstance(value, bool)
    if tag == "strarray":
        return isinstance(value, list) and all(isinstance(x, str) for x in value)
    if tag == "str|null":
        return value is None or isinstance(value, str)
    if tag == "int|null":
        return value is None or (
            isinstance(value, int) and not isinstance(value, bool)
        )
    raise AssertionError(f"unknown field tag: {tag!r}")  # pragma: no cover


def validate_event(obj: Any) -> dict[str, Any]:
    """Return ``obj`` if it conforms to the event wire shape, else raise
    :class:`ProtocolError`. Unknown keys, missing required keys, wrong
    types, and bad enum values all fail closed."""
    if not isinstance(obj, dict):
        raise ProtocolError(f"event must be an object, got {type(obj).__name__}")
    ts = obj.get("ts")
    if not isinstance(ts, str) or not _TS_RE.match(ts):
        raise ProtocolError(f"event 'ts' not ISO-8601 with offset: {ts!r}")
    etype = obj.get("type")
    spec = EVENT_SPEC.get(etype) if isinstance(etype, str) else None
    if spec is None:
        raise ProtocolError(f"unknown event type: {etype!r}")
    required: dict[str, str] = spec["required"]
    optional: dict[str, str] = spec["optional"]
    enums: dict[str, list] = spec["enums"]
    allowed = {"ts", "type", *required, *optional}
    unknown = set(obj) - allowed
    if unknown:
        raise ProtocolError(
            f"{etype}: unknown field(s): {', '.join(sorted(unknown))}"
        )
    for field, tag in required.items():
        if field not in obj:
            raise ProtocolError(f"{etype}: missing required field {field!r}")
        if not _tag_ok(obj[field], tag):
            raise ProtocolError(f"{etype}: field {field!r} fails type {tag!r}")
    for field, tag in optional.items():
        if field in obj and not _tag_ok(obj[field], tag):
            raise ProtocolError(f"{etype}: field {field!r} fails type {tag!r}")
    for field, allowed_vals in enums.items():
        if field in obj and obj[field] not in allowed_vals:
            raise ProtocolError(
                f"{etype}: field {field!r}={obj[field]!r} not in {allowed_vals}"
            )
    return obj


# ---------- JSON Schema (draft 2020-12) generation ----------

_TAG_SCHEMA: dict[str, dict] = {
    "str": {"type": "string"},
    "int": {"type": "integer"},
    "num": {"type": "number"},
    "bool": {"type": "boolean"},
    "strarray": {"type": "array", "items": {"type": "string"}},
    "str|null": {"type": ["string", "null"]},
    "int|null": {"type": ["integer", "null"]},
}


def _field_schema(tag: str, enum: list | None) -> dict:
    base = dict(_TAG_SCHEMA[tag])
    if enum is not None:
        base["enum"] = list(enum)
    return base


def build_json_schema() -> dict[str, Any]:
    """Build the draft-2020-12 schema for a single event object: a
    ``oneOf`` over per-type branches, each strict (``additionalProperties:
    false``). This is the vendored ``event.schema.json``."""
    branches = []
    for etype, spec in EVENT_SPEC.items():
        enums: dict[str, list] = spec["enums"]
        props: dict[str, dict] = {
            "ts": {"type": "string", "pattern": TS_PATTERN},
            "type": {"const": etype},
        }
        for field, tag in {**spec["required"], **spec["optional"]}.items():
            props[field] = _field_schema(tag, enums.get(field))
        branches.append({
            "type": "object",
            "required": ["ts", "type", *spec["required"].keys()],
            "properties": props,
            "additionalProperties": False,
        })
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://diting.dev/companion-protocol/v1/event.schema.json",
        "title": "diting companion-protocol event",
        "description": (
            "One diting event object as emitted by EventLogger. English "
            "keys; ISO-8601 local-TZ-with-offset timestamps; omitted None "
            "fields; empty tuples as []."
        ),
        "oneOf": branches,
    }
