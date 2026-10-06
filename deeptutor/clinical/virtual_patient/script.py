"""Patient script config: validation for the JSON-driven consultation engine.

A patient script lives in the case version payload as ``content.patient_script``
with ``script_version: 2``.  The schema is snake_case; the ai-companion
prototype's camelCase fields (patientProfile/initialVitals/inquiryMap/
examResults) are normalized on load.  ``progressionScript`` and
``disclosureRules`` from the prototype are preserved verbatim as WP9 input
but ignored by this engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any

PHASES: tuple[str, ...] = ("initial", "history_taking", "examination", "disposition", "terminated")
ACTION_TYPES: tuple[str, ...] = ("begin", "ask_question", "order_exam", "advance_phase", "submit_disposition")

#: Default action permissions per phase (scripts may override per phase).
#: ``advance_phase`` moves the consultation forward one phase; scripts that
#: want a strictly linear flow simply omit it from earlier phases.
DEFAULT_PHASE_ACTIONS: dict[str, tuple[str, ...]] = {
    "initial": ("begin",),
    "history_taking": ("ask_question", "advance_phase"),
    "examination": ("ask_question", "order_exam", "advance_phase"),
    "disposition": ("ask_question", "order_exam", "submit_disposition"),
    "terminated": (),
}

FALLBACK_REPLY = "（患者）我没太听明白，您能换个问法吗？"


class ScriptError(ValueError):
    """Raised when a patient script config is invalid."""


@dataclass(frozen=True)
class InquiryTopic:
    topic: str
    keywords: tuple[str, ...]
    response: str
    is_key_info: bool


@dataclass(frozen=True)
class ExamItem:
    exam_name: str
    result_description: str
    cost: str = ""
    is_definitive: bool = False


@dataclass(frozen=True)
class DispositionOption:
    name: str
    feedback: str
    is_correct: bool = False


@dataclass(frozen=True)
class PatientScript:
    raw: dict
    inquiry_map: tuple[InquiryTopic, ...]
    exams: tuple[ExamItem, ...]
    dispositions: tuple[DispositionOption, ...]
    profile: dict = field(default_factory=dict)
    initial_vitals: dict = field(default_factory=dict)
    phase_actions: dict[str, tuple[str, ...]] = field(default_factory=dict)
    required_revelations: tuple[str, ...] = ()

    def actions_allowed(self, phase: str) -> tuple[str, ...]:
        return self.phase_actions.get(phase, DEFAULT_PHASE_ACTIONS.get(phase, ()))

    def content_hash(self) -> str:
        canonical = json.dumps(self.raw, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _norm_inquiry(raw_list: list) -> list[InquiryTopic]:
    topics: list[InquiryTopic] = []
    for i, item in enumerate(raw_list):
        if not isinstance(item, dict):
            raise ScriptError(f"inquiry_map[{i}] must be an object")
        topic = str(item.get("topic", "")).strip()
        response = str(item.get("response", "")).strip()
        keywords = item.get("keywords", [])
        if not topic or not response:
            raise ScriptError(f"inquiry_map[{i}] needs non-empty topic and response")
        if not isinstance(keywords, list) or not keywords:
            raise ScriptError(f"inquiry_map[{i}].keywords must be a non-empty list")
        topics.append(
            InquiryTopic(
                topic=topic,
                keywords=tuple(str(k).lower() for k in keywords if str(k).strip()),
                response=response,
                is_key_info=bool(item.get("is_key_info", False)),
            )
        )
    return topics


def _norm_exams(raw_list: list) -> list[ExamItem]:
    exams: list[ExamItem] = []
    for i, item in enumerate(raw_list):
        if not isinstance(item, dict):
            raise ScriptError(f"exam_results[{i}] must be an object")
        name = str(item.get("exam_name") or item.get("examName", "")).strip()
        result = str(item.get("result_description") or item.get("resultDescription", "")).strip()
        if not name or not result:
            raise ScriptError(f"exam_results[{i}] needs non-empty exam_name and result_description")
        exams.append(
            ExamItem(
                exam_name=name,
                result_description=result,
                cost=str(item.get("cost", "")),
                is_definitive=bool(item.get("is_definitive", item.get("isDefinitive", False))),
            )
        )
    return exams


def load_script(config: Any) -> PatientScript:
    """Validate a patient script payload; returns the frozen script object."""
    if not isinstance(config, dict):
        raise ScriptError("patient_script must be a JSON object")

    raw_inquiries = config.get("inquiry_map") or config.get("inquiryMap")
    raw_exams = config.get("exam_results") or config.get("examResults")
    if not isinstance(raw_inquiries, list) or not raw_inquiries:
        raise ScriptError("patient_script.inquiry_map must be a non-empty list")
    if not isinstance(raw_exams, list) or not raw_exams:
        raise ScriptError("patient_script.exam_results must be a non-empty list")

    raw_dispositions = config.get("disposition_options") or config.get("dispositionOptions")
    if not isinstance(raw_dispositions, list) or not raw_dispositions:
        raise ScriptError(
            "patient_script.disposition_options must be a non-empty list "
            "(each entry: name/feedback/is_correct)"
        )
    dispositions: list[DispositionOption] = []
    for i, item in enumerate(raw_dispositions):
        if not isinstance(item, dict) or not str(item.get("name", "")).strip():
            raise ScriptError(f"disposition_options[{i}] needs a non-empty name")
        dispositions.append(
            DispositionOption(
                name=str(item["name"]).strip(),
                feedback=str(item.get("feedback", "")).strip(),
                is_correct=bool(item.get("is_correct", False)),
            )
        )
    if not any(d.is_correct for d in dispositions):
        raise ScriptError("at least one disposition option must be correct")

    phase_actions_raw = config.get("phase_actions", {})
    phase_actions: dict[str, tuple[str, ...]] = {}
    if not isinstance(phase_actions_raw, dict):
        raise ScriptError("phase_actions must be an object")
    for phase, actions in phase_actions_raw.items():
        if phase not in PHASES:
            raise ScriptError(f"phase_actions has unknown phase '{phase}'")
        if not isinstance(actions, list) or any(a not in ACTION_TYPES for a in actions):
            raise ScriptError(f"phase_actions['{phase}'] must list known action types")
        phase_actions[phase] = tuple(actions)

    profile = config.get("profile") or config.get("patientProfile") or {}
    vitals = config.get("initial_vitals") or config.get("initialVitals") or {}
    if not isinstance(profile, dict) or not isinstance(vitals, dict):
        raise ScriptError("profile/initial_vitals must be objects")

    required = config.get("required_revelations", [])
    if not isinstance(required, list) or any(not str(t).strip() for t in required):
        raise ScriptError("required_revelations must be a list of topic names")

    return PatientScript(
        raw=config,
        inquiry_map=tuple(_norm_inquiry(raw_inquiries)),
        exams=tuple(_norm_exams(raw_exams)),
        dispositions=tuple(dispositions),
        profile=dict(profile),
        initial_vitals=dict(vitals),
        phase_actions=phase_actions,
        required_revelations=tuple(str(t).strip() for t in required),
    )


def script_from_content(content: dict) -> PatientScript | None:
    """Extract and validate the patient script from a case content payload.

    Returns ``None`` when the case carries no script (or an unparseable one —
    e.g. a WP9 mass-casualty scenario), so callers treat the case as
    "no virtual patient available".
    """
    raw = content.get("patient_script") if isinstance(content, dict) else None
    if not isinstance(raw, dict):
        return None
    try:
        return load_script(raw)
    except ScriptError:
        return None
