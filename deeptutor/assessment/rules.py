"""Rules v1: deterministic structural checks over reasoning steps.

These checks look at form, not at medical correctness: length, presence of
differentiation language, and reuse of the case's configured examinations.
Every finding is emitted with a low confidence and ``needs_review=True`` —
rules_v1 is a hint generator for teachers, not a grader (plan: AI 分类在
效度验证前只作辅助提示).
"""

from __future__ import annotations

from dataclasses import dataclass

#: Suggestion emitted when a differentiation step names no other condition.
_DIFFERENTIATION_HINTS = ("鉴别", "考虑", "排除", "不符", "不支", "相似", "类似")


@dataclass(frozen=True)
class StepFinding:
    step_id: str
    step_type: str
    error_type: str | None
    confidence: float
    evidence: str
    suggestion: str


def _findings_for_step(step: dict, case_content: dict) -> list[StepFinding]:
    step_id = step["step_id"]
    step_type = step["step_type"]
    text = str(step.get("content", ""))
    findings: list[StepFinding] = []

    if step_type == "problem_presentation":
        if len(text.strip()) < 20:
            findings.append(
                StepFinding(
                    step_id=step_id,
                    step_type=step_type,
                    error_type="evidence_gap",
                    confidence=0.2,
                    evidence=f"problem_presentation length={len(text.strip())}",
                    suggestion="问题表征过简：应归纳患者的人口学特点、主诉与病程要点。",
                )
            )

    elif step_type == "differential_diagnosis":
        if not any(hint in text for hint in _DIFFERENTIATION_HINTS):
            findings.append(
                StepFinding(
                    step_id=step_id,
                    step_type=step_type,
                    error_type="differential_exclusion",
                    confidence=0.3,
                    evidence="no differentiation language detected",
                    suggestion="鉴别诊断应写明与哪些疾病鉴别、支持点与不支持点。",
                )
            )

    elif step_type == "key_evidence":
        case_evidence = case_content.get("key_evidence", []) or []
        if case_evidence and not any(
            _overlap(text, str(item)) >= 2 for item in case_evidence
        ):
            findings.append(
                StepFinding(
                    step_id=step_id,
                    step_type=step_type,
                    error_type="evidence_integration",
                    confidence=0.25,
                    evidence="no overlap with case key evidence",
                    suggestion="关键证据应引用病例中的具体表现（症状/体征/检查结果）。",
                )
            )

    elif step_type == "investigation":
        configured = {
            str(exam.get("exam_name", ""))
            for exam in case_content.get("auxiliary_exams", []) or []
        }
        if configured and text.strip() and not any(name in text for name in configured if name):
            findings.append(
                StepFinding(
                    step_id=step_id,
                    step_type=step_type,
                    error_type="decision_rationale",
                    confidence=0.2,
                    evidence=f"configured exams: {sorted(configured)[:5]}",
                    suggestion="检查选择建议围绕病例可及的检查展开，并说明选择依据。",
                )
            )

    elif step_type == "disposition":
        if not any(k in text for k in ("因为", "依据", "理由", "指征", "原则", "指南")):
            findings.append(
                StepFinding(
                    step_id=step_id,
                    step_type=step_type,
                    error_type="decision_rationale",
                    confidence=0.2,
                    evidence="no explicit rationale language detected",
                    suggestion="处置方案应说明依据（指征/指南/原则）。",
                )
            )

    return findings


def _overlap(text: str, reference: str) -> int:
    """Count shared 2-grams between the student text and a reference string.

    A crude but deterministic proxy for "the student cited case evidence";
    good enough for a hint, never used as a score.
    """
    clean = "".join(ch for ch in reference if "\u4e00" <= ch <= "\u9fff")
    grams = {clean[i : i + 2] for i in range(max(0, len(clean) - 1))} - {"，", "。"}
    return sum(1 for g in grams if g and g in text)


def assess_attempt(attempt: dict, steps: list[dict], case_content: dict) -> dict:
    """Run rules_v1 over all steps; returns the run summary shape."""
    findings: list[StepFinding] = []
    for step in steps:
        findings.extend(_findings_for_step(step, case_content))
    flagged = [f for f in findings if f.error_type]
    return {
        "engine": "rules_v1",
        "steps_checked": len(steps),
        "findings": [
            {
                "step_id": f.step_id,
                "step_type": f.step_type,
                "error_type": f.error_type,
                "confidence": f.confidence,
                "evidence": f.evidence,
                "suggestion": f.suggestion,
            }
            for f in findings
        ],
        "summary": {
            "flagged_steps": len({f.step_id for f in findings}),
            "error_candidates": len(flagged),
        },
    }
