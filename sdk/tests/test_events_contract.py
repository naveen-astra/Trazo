"""Contract test: trazo.core.events vs schema/trace-event.v1.schema.json.

TRZ-P1-02 DoD: this job must fail on deliberate drift between the pydantic
models and the JSON Schema. Two independent checks enforce that:
(1) structural comparison of required/optional field names per payload and
envelope, (2) every fixture event round-trips through the models and the
resulting JSON still validates against the schema. The drift tests mutate
a schema copy to prove check (1) actually discriminates.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ValidationError

from trazo.core.events import (
    PAYLOAD_MODEL_BY_KIND,
    EventAdapter,
    _EnvelopeBase,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schema" / "trace-event.v1.schema.json"
EXAMPLES_PATH = REPO_ROOT / "schema" / "examples" / "sample_run.ndjson"

# schema $defs payload name -> event kind (EVENTS.md §2 / schema $defs).
PAYLOAD_DEFN_TO_KIND = {
    "runStartedPayload": "run.started",
    "runFinishedPayload": "run.finished",
    "stepStartedPayload": "step.started",
    "stepFinishedPayload": "step.finished",
    "llmCallPayload": "llm.call",
    "toolCallPayload": "tool.call",
    "memoryReadPayload": "memory.read",
    "memoryWritePayload": "memory.write",
    "agentMessagePayload": "agent.message",
    "planUpdatedPayload": "plan.updated",
    "humanCheckpointPayload": "human.checkpoint",
    "policyDecisionPayload": "policy.decision",
    "detectionRaisedPayload": "detection.raised",
    "sdkDiagnosticPayload": "sdk.diagnostic",
}

# Field alias overrides where the Python attribute name differs from the wire name.
_ALIAS_OVERRIDES = {"schema_": "schema"}


def _load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text())


def _wire_field_names(model: type[BaseModel], *, required_only: bool) -> set[str]:
    names: set[str] = set()
    for name, field in model.model_fields.items():
        if required_only and not field.is_required():
            continue
        names.add(_ALIAS_OVERRIDES.get(name, field.alias or name))
    return names


def payload_contract_errors(schema: dict[str, Any]) -> list[str]:
    """Return mismatch descriptions between schema payload defs and pydantic
    payload models; empty means they agree on field names, required or not."""
    errors: list[str] = []
    defs = schema["$defs"]
    for defn_name, kind in PAYLOAD_DEFN_TO_KIND.items():
        defn = defs.get(defn_name)
        model = PAYLOAD_MODEL_BY_KIND.get(kind)
        if defn is None:
            errors.append(f"{kind}: schema is missing $defs.{defn_name}")
            continue
        if model is None:
            errors.append(f"{kind}: no model registered in PAYLOAD_MODEL_BY_KIND")
            continue
        schema_required = set(defn.get("required", []))
        schema_props = set(defn.get("properties", {}).keys())
        model_required = _wire_field_names(model, required_only=True)
        model_props = _wire_field_names(model, required_only=False)
        if schema_required != model_required:
            errors.append(
                f"{kind}: required fields differ - schema={sorted(schema_required)} "
                f"model={sorted(model_required)}"
            )
        if schema_props != model_props:
            errors.append(
                f"{kind}: property names differ - schema={sorted(schema_props)} "
                f"model={sorted(model_props)}"
            )
    return errors


def envelope_contract_errors(schema: dict[str, Any]) -> list[str]:
    """Compare the schema's top-level envelope fields against _EnvelopeBase.
    kind/payload/fingerprint vary per concrete subclass, so they're checked
    by presence only, not sourced from the shared base."""
    errors: list[str] = []
    schema_required = set(schema.get("required", [])) - {"kind", "payload"}
    schema_props = set(schema.get("properties", {}).keys()) - {"kind", "payload"}
    model_required = _wire_field_names(_EnvelopeBase, required_only=True)
    model_props = _wire_field_names(_EnvelopeBase, required_only=False)
    if schema_required != model_required:
        errors.append(
            f"envelope: required fields differ - schema={sorted(schema_required)} "
            f"model={sorted(model_required)}"
        )
    if schema_props != model_props:
        errors.append(
            f"envelope: property names differ - schema={sorted(schema_props)} "
            f"model={sorted(model_props)}"
        )
    return errors


def test_contract__payload_models_match_schema() -> None:
    assert payload_contract_errors(_load_schema()) == []


def test_contract__envelope_model_matches_schema() -> None:
    assert envelope_contract_errors(_load_schema()) == []


def test_contract__catches_deliberate_drift_new_required_field() -> None:
    """Simulates a schema change (new required payload field) the model
    hasn't picked up yet — the job must flag it."""
    drifted = copy.deepcopy(_load_schema())
    drifted["$defs"]["llmCallPayload"]["required"].append("totally_new_field")
    errors = payload_contract_errors(drifted)
    assert any("llm.call" in e for e in errors)


def test_contract__catches_deliberate_drift_removed_property() -> None:
    """Simulates a schema change that drops a property the model still has."""
    drifted = copy.deepcopy(_load_schema())
    del drifted["$defs"]["toolCallPayload"]["properties"]["side_effect_class"]
    drifted["$defs"]["toolCallPayload"]["required"].remove("side_effect_class")
    errors = payload_contract_errors(drifted)
    assert any("tool.call" in e for e in errors)


def test_contract__examples_valid_against_model_and_schema() -> None:
    """Every fixture event both parses via the pydantic models and, after
    round-tripping to JSON, still validates against the JSON Schema."""
    validator = Draft202012Validator(_load_schema())
    lines = [line for line in EXAMPLES_PATH.read_text().splitlines() if line.strip()]
    assert lines, "fixture must not be empty"
    for line in lines:
        raw = json.loads(line)
        event = EventAdapter.validate_python(raw)
        dumped = EventAdapter.dump_python(
            event, mode="json", by_alias=True, exclude_none=True
        )
        schema_errors = list(validator.iter_errors(dumped))
        assert not schema_errors, (
            f"seq={raw.get('seq')} kind={raw.get('kind')} round-trip failed schema: "
            f"{[e.message for e in schema_errors]}"
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "drop_required_payload_field",
        "unknown_kind",
        "unknown_envelope_field",
    ],
)
def test_contract__invalid_events_rejected_by_both(mutation: str) -> None:
    """The model and the schema must agree on the negative case too, not
    just accept everything."""
    validator = Draft202012Validator(_load_schema())
    lines = EXAMPLES_PATH.read_text().splitlines()
    llm_call_line = next(
        line for line in lines if json.loads(line)["kind"] == "llm.call"
    )
    base = json.loads(llm_call_line)
    bad = copy.deepcopy(base)

    if mutation == "drop_required_payload_field":
        del bad["payload"]["model"]
    elif mutation == "unknown_kind":
        bad["kind"] = "totally.unknown"
    elif mutation == "unknown_envelope_field":
        bad["unexpected_field"] = "x"

    schema_errors = list(validator.iter_errors(bad))
    assert schema_errors, f"schema should reject mutation={mutation}"

    with pytest.raises(ValidationError):
        EventAdapter.validate_python(bad)
