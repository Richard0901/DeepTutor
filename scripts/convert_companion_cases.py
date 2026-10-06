#!/usr/bin/env python3
"""One-off migration: convert ai-companion prototype mock cases into the
clinical case import template used by ``deeptutor/clinical``.

The prototype lives outside this repository (``../ai-companion/data/cases``).
Rerun it if the prototype gains new cases::

    python scripts/convert_companion_cases.py [source_dir] [target_dir]

Error-type codes are mapped to the working eight-type error dictionary
(plan §5.3, pending the D2 decision); the mapping is recorded per case in
``source.note`` so the provisional mapping stays visible until D2 signs off.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT.parent / "ai-companion" / "data" / "cases"
DEFAULT_TARGET = REPO_ROOT / "deeptutor" / "clinical" / "seed_cases"

ERROR_TYPE_MAP = {
    "differential_omission": "differential_exclusion",
    "evidence_omission": "evidence_gap",
    "premature_conclusion": "decision_bias",
    "improper_treatment": "decision_bias",
    "logic_jump": "logic_breakpoint",
    "over_testing": "decision_rationale",
    "concept_confusion": "symptom_attribution",
}

DISEASE_BY_CASE = {
    "mock-l1-001": "社区获得性肺炎",
    "mock-l2-001": "支气管哮喘",
    "mock-l3-001": "COPD急性加重合并肺栓塞",
    "mock-l4-001": "胸肺战创伤（高原批量伤员）",
}

DIMENSION_MAP = {
    "symptomComplexity": "complexity",
    "diagnosisDifficulty": "diagnostic",
    "decisionComplexity": "decision",
    "situationalSpecialty": "situational",
}


def convert_case(raw: dict, script: dict | None) -> dict:
    case_code = raw["caseId"].replace("mock-", "RESP-").upper()  # mock-l2-001 -> RESP-L2-001
    dims = {DIMENSION_MAP[k]: v for k, v in raw["complexity"].items()}
    content = {
        "chief_complaint": raw["chiefComplaint"],
        "present_illness": raw["presentIllness"],
        "past_history": raw["pastHistory"],
        "physical_examination": raw["physicalExamination"],
        "auxiliary_exams": [
            {
                "exam_name": exam["examName"],
                "category": exam["category"],
                "result": exam["result"],
                "is_key_evidence": exam["isKeyEvidence"],
            }
            for exam in raw.get("auxiliaryExams", [])
        ],
        "diagnosis": raw["diagnosis"],
        "key_evidence": raw["keyEvidence"],
        "differential_diagnosis": raw["differentialDiagnosis"],
        "common_errors": [
            {
                "error_type": ERROR_TYPE_MAP[err["errorType"]],
                "description": err["description"],
                "trigger_feedback": err.get("triggerFeedback", ""),
                "prototype_error_type": err["errorType"],
            }
            for err in raw.get("commonErrors", [])
        ],
        "diagnostic_pitfalls": raw.get("diagnosticPitfalls", []),
        "training_objectives": raw["trainingObjectives"],
        "standard_workflow": raw.get("standardWorkflow", []),
        "scoring_rubric": raw.get("scoringRubric"),
    }
    if script is not None:
        content["patient_script"] = script
    return {
        "schema_version": 1,
        "case_code": case_code,
        "title": raw["title"],
        "disease": DISEASE_BY_CASE[raw["caseId"]],
        "level": raw["level"],
        "dimensions": dims,
        "knowledge_points": [
            {"code": f"dx-{i:02d}", "name": name}
            for i, name in enumerate(raw.get("knowledgeGraphEntities", {}).get("diagnoses", []), 1)
        ],
        "content": content,
        "source": {
            "origin": "synthetic",
            "author": raw.get("author", "mock-dev"),
            "note": (
                "converted from ai-companion prototype case "
                f"{raw['caseId']}; error_type codes mapped to the working "
                "eight-type dictionary pending D2 sign-off "
                f"({sorted({e['errorType'] for e in raw.get('commonErrors', [])})})"
            ),
        },
        "change_note": "converted from ai-companion prototype",
    }


def main() -> int:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    target = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_TARGET
    target.mkdir(parents=True, exist_ok=True)

    mains = sorted(p for p in source.glob("mock-l*-*.json") if "患者脚本" not in p.name)
    if not mains:
        print(f"no prototype cases found under {source}", file=sys.stderr)
        return 1
    converted = 0
    for path in mains:
        raw = json.loads(path.read_text(encoding="utf-8"))
        script = None
        script_path = path.with_name(path.stem + "-患者脚本.json")
        if script_path.exists():
            script = json.loads(script_path.read_text(encoding="utf-8"))
        payload = convert_case(raw, script)
        out = target / f"{payload['case_code']}.json"
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"converted {path.name} -> {out.relative_to(REPO_ROOT)}")
        converted += 1
    print(f"done: {converted} case(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
