"""Deterministic consultation engine: state transitions and info release.

Every action produces exactly one ``(next_state, released)`` pair computed
purely from ``(state, script, action)`` — no randomness, no LLM, no wall
clock — so an event log replay always reconstructs the identical state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from deeptutor.clinical.virtual_patient.script import (
    FALLBACK_REPLY,
    PatientScript,
    ScriptError,
)


@dataclass(frozen=True)
class PatientState:
    phase: str = "initial"
    revealed_topics: tuple[str, ...] = ()
    revealed_results: tuple[str, ...] = ()   # exam names whose results were released
    disposition: str | None = None
    disposition_correct: bool | None = None
    terminated: bool = False

    def to_json(self) -> dict:
        return {
            "phase": self.phase,
            "revealed_topics": list(self.revealed_topics),
            "revealed_results": list(self.revealed_results),
            "disposition": self.disposition,
            "disposition_correct": self.disposition_correct,
            "terminated": self.terminated,
        }


@dataclass(frozen=True)
class Action:
    action_type: str
    payload: dict = field(default_factory=dict)

    def normalized_payload(self) -> dict[str, Any]:
        if self.action_type == "ask_question":
            return {"text": str(self.payload.get("text", "")).strip()}
        if self.action_type == "order_exam":
            return {"exam_name": str(self.payload.get("exam_name", "")).strip()}
        if self.action_type == "submit_disposition":
            return {"option": str(self.payload.get("option", "")).strip()}
        return {}


@dataclass(frozen=True)
class EngineOutcome:
    next_state: PatientState
    released: dict           # what the student sees (reply / exam result / outcome)
    error: str | None = None  # action rejected (wrong phase, unknown item, ...)


def initial_state() -> PatientState:
    return PatientState()


def _match_topic(script: PatientScript, text: str) -> Any:
    lowered = text.lower()
    for topic in script.inquiry_map:
        if any(k in lowered for k in topic.keywords):
            return topic
    return None


def apply(state: PatientState, script: PatientScript, action: Action) -> EngineOutcome:
    """Pure transition function; raises nothing, reports via ``error``."""
    if state.terminated:
        return EngineOutcome(state, {}, error="session already terminated")
    allowed = script.actions_allowed(state.phase)
    if action.action_type not in allowed:
        return EngineOutcome(
            state,
            {},
            error=f"action '{action.action_type}' is not allowed in phase '{state.phase}'",
        )

    if action.action_type == "begin":
        return EngineOutcome(
            PatientState(phase="history_taking"),
            {"reply": "（患者）医生，你问吧。", "event": "consultation began"},
        )

    if action.action_type == "advance_phase":
        next_phase = {
            "history_taking": "examination",
            "examination": "disposition",
        }.get(state.phase)
        if next_phase is None:
            return EngineOutcome(
                state, {}, error=f"cannot advance from phase '{state.phase}'"
            )
        return EngineOutcome(
            PatientState(
                phase=next_phase,
                revealed_topics=state.revealed_topics,
                revealed_results=state.revealed_results,
            ),
            {"event": f"phase advanced to '{next_phase}'"},
        )

    if action.action_type == "ask_question":
        text = action.normalized_payload()["text"]
        if not text:
            return EngineOutcome(state, {}, error="question text must not be empty")
        topic = _match_topic(script, text)
        if topic is None:
            return EngineOutcome(state, {"reply": FALLBACK_REPLY, "matched_topic": None})
        revealed = state.revealed_topics
        reply_note = "" if topic.topic in revealed else "（新信息）"
        return EngineOutcome(
            PatientState(
                phase=state.phase,
                revealed_topics=tuple(dict.fromkeys((*revealed, topic.topic))),
                revealed_results=state.revealed_results,
            ),
            {
                "reply": f"{reply_note}{topic.response}",
                "matched_topic": topic.topic,
                "is_key_info": topic.is_key_info,
            },
        )

    if action.action_type == "order_exam":
        exam_name = action.normalized_payload()["exam_name"]
        if not exam_name:
            return EngineOutcome(state, {}, error="exam_name must not be empty")
        match = next((e for e in script.exams if e.exam_name == exam_name), None)
        if match is None:
            return EngineOutcome(
                state,
                {},
                error=f"exam '{exam_name}' is not configured for this case",
            )
        repeated = exam_name in state.revealed_results
        return EngineOutcome(
            PatientState(
                phase=state.phase,
                revealed_topics=state.revealed_topics,
                revealed_results=tuple(dict.fromkeys((*state.revealed_results, exam_name))),
            ),
            {
                "exam_name": match.exam_name,
                "result": match.result_description,
                "is_definitive": match.is_definitive,
                "repeat": repeated,
            },
        )

    if action.action_type == "submit_disposition":
        option_name = action.normalized_payload()["option"]
        if not option_name:
            return EngineOutcome(state, {}, error="disposition option must not be empty")
        option = next((d for d in script.dispositions if d.name == option_name), None)
        if option is None:
            return EngineOutcome(
                state,
                {},
                error=f"disposition option '{option_name}' is not configured for this case",
            )
        missing = [
            t
            for t in script.required_revelations
            if t not in state.revealed_topics and t not in state.revealed_results
        ]
        if missing:
            return EngineOutcome(
                state,
                {},
                error="cannot submit disposition: missing required information: "
                + ", ".join(missing),
            )
        return EngineOutcome(
            PatientState(
                phase="terminated",
                revealed_topics=state.revealed_topics,
                revealed_results=state.revealed_results,
                disposition=option.name,
                disposition_correct=option.is_correct,
                terminated=True,
            ),
            {
                "disposition": option.name,
                "is_correct": option.is_correct,
                "feedback": option.feedback,
            },
        )

    raise ScriptError(f"unknown action type '{action.action_type}'")  # pragma: no cover


def replay(script: PatientScript, events: list[dict]) -> PatientState:
    """Rebuild state from stored event rows (payload/released JSON dicts)."""
    state = initial_state()
    for event in events:
        action = Action(
            action_type=event["action_type"],
            payload=event.get("payload", {}),
        )
        outcome = apply(state, script, action)
        if outcome.error is not None:
            raise ScriptError(f"event log replay failed at seq: {outcome.error}")
        state = outcome.next_state
    return state
