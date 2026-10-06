"""Assessment framework (plan WP7): first-pass evaluation of reasoning steps.

Layering:
- ``rules.py``  — deterministic structural checks (engine ``rules_v1``);
- ``llm.py``    — the integration contract for the local-LLM assessor
  (``engine`` ``llm_local``), intentionally a stub until the error-type
  classification validity study (G3) is done;
- ``service.py`` — persistence, review workflow, repetition detection.

Hard rules from the plan: every first-pass tag is an 辅助提示 with
``needs_human_review=1``; nothing here enters formal grades; teacher
reviews are append-only records and never overwrite the original score.
"""
