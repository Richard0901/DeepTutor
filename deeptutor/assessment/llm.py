"""Local-LLM assessor integration contract (engine ``llm_local``).

INTENTIONALLY A STUB.  Per plan §7/G3 the AI error classifier may only be
switched on after the gold-standard study shows sufficient agreement
(宏 F1 threshold) — until then ``llm_local`` must not be used in production
runs, and even after switching on, its output remains 辅助提示 with human
review before anything influences a grade.

Expected contract once implemented::

    def assess_step(step: dict, case_content: dict, rubric: dict) -> list[dict]:
        \"\"\"Return findings in the same shape as rules.assess_attempt().\"\"\"
        # - local model only (clinical-offline profile)
        # - structured output validated against the D2 error dictionary
        # - confidence <= 0.85; anything above goes to human review anyway
        # - prompt injection guard: case text is data, never instructions
        ...

The stub raises so that an accidental ``llm_local`` run fails loudly
instead of silently producing empty assessments.
"""

from __future__ import annotations


class LlmAssessorNotImplemented(RuntimeError):
    pass


def assess_step(step: dict, case_content: dict, rubric: dict) -> list[dict]:
    raise LlmAssessorNotImplemented(
        "llm_local assessor is intentionally not implemented until the G3 "
        "classification-validity study; use engine='rules_v1'"
    )
