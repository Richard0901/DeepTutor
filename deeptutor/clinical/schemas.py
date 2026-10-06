"""Validation for case import payloads (the JSON case template).

The template is the contract between clinical experts authoring cases and
the platform.  It keeps the ai-companion prototype's content structure
(chief complaint, exams, differentials, error triggers, ...) while adding
the fields the 申报书 requires for every formal case: unique code, L1-L4
level, the four grading dimensions, knowledge points and provenance.
"""

from __future__ import annotations

from typing import Any

from deeptutor.teaching.models import CASE_LEVELS, DIMENSIONS, ERROR_TYPES

TEMPLATE_SCHEMA_VERSION = 1

# Content keys every case version must carry.  Optional keys may be absent
# but must validate when present.  This list is the D2-adjacent content
# contract; extend it only with a documented decision.
_REQUIRED_CONTENT: tuple[tuple[str, type], ...] = (
    ("chief_complaint", str),
    ("present_illness", str),
    ("past_history", str),
    ("physical_examination", str),
    ("diagnosis", str),
)
_REQUIRED_LIST_CONTENT: tuple[str, ...] = (
    "key_evidence",
    "differential_diagnosis",
    "training_objectives",
)
_OPTIONAL_LIST_CONTENT: tuple[str, ...] = (
    "auxiliary_exams",
    "diagnostic_pitfalls",
    "standard_workflow",
)


class CaseValidationError(ValueError):
    """Raised when a case payload violates the import template."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors) if errors else "invalid case payload")


def validate_case_payload(payload: Any) -> dict:
    """Validate one case import object; returns it unchanged when valid."""
    errors: list[str] = []
    if not isinstance(payload, dict):
        raise CaseValidationError(["payload must be a JSON object"])

    schema_version = payload.get("schema_version", TEMPLATE_SCHEMA_VERSION)
    if schema_version != TEMPLATE_SCHEMA_VERSION:
        errors.append(f"unsupported schema_version {schema_version!r}")

    for key in ("case_code", "title", "level", "dimensions", "content"):
        if key not in payload or payload[key] in (None, ""):
            errors.append(f"missing required field '{key}'")
    if errors:
        raise CaseValidationError(errors)

    if not isinstance(payload["case_code"], str) or not payload["case_code"].strip():
        errors.append("'case_code' must be a non-empty string")
    if not isinstance(payload["title"], str) or not payload["title"].strip():
        errors.append("'title' must be a non-empty string")
    if payload["level"] not in CASE_LEVELS:
        errors.append(f"'level' must be one of {CASE_LEVELS}, got {payload['level']!r}")

    dimensions = payload["dimensions"]
    if not isinstance(dimensions, dict):
        errors.append("'dimensions' must be an object")
    else:
        for dim in DIMENSIONS:
            score = dimensions.get(dim)
            if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 5:
                errors.append(f"dimensions.{dim} must be an integer 1-5, got {score!r}")

    disease = payload.get("disease", "")
    if not isinstance(disease, str):
        errors.append("'disease' must be a string when present")

    kps = payload.get("knowledge_points", [])
    if not isinstance(kps, list):
        errors.append("'knowledge_points' must be a list")
    else:
        for i, kp in enumerate(kps):
            if not isinstance(kp, dict) or not kp.get("code") or not kp.get("name"):
                errors.append(f"knowledge_points[{i}] needs non-empty 'code' and 'name'")

    content = payload["content"]
    if not isinstance(content, dict):
        errors.append("'content' must be an object")
    else:
        for key, expected in _REQUIRED_CONTENT:
            value = content.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"content.{key} must be a non-empty string")
        for key in _REQUIRED_LIST_CONTENT:
            value = content.get(key)
            if not isinstance(value, list) or not value:
                errors.append(f"content.{key} must be a non-empty list")
        for key in _OPTIONAL_LIST_CONTENT:
            if key in content and not isinstance(content[key], list):
                errors.append(f"content.{key} must be a list when present")
        for i, err in enumerate(content.get("common_errors", [])):
            if not isinstance(err, dict) or err.get("error_type") not in ERROR_TYPES:
                errors.append(
                    f"content.common_errors[{i}].error_type must be one of {ERROR_TYPES}"
                )
            elif not str(err.get("description", "")).strip():
                errors.append(f"content.common_errors[{i}].description must be non-empty")

    source = payload.get("source", {})
    if not isinstance(source, dict):
        errors.append("'source' must be an object when present")
    elif source.get("origin") not in ("synthetic", "approved_desensitized", "original"):
        errors.append(
            "source.origin must be 'synthetic', 'approved_desensitized' or 'original' "
            "(real-patient content needs ethics approval before import)"
        )

    if errors:
        raise CaseValidationError(errors)
    return payload
