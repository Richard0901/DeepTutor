#!/usr/bin/env python3
"""One-off migration: convert the 150-case synthetic library (ai-companion
schema, produced in the parallel authoring workflow) into the clinical case
import template.

    python scripts/convert_case_library.py [source_dir] [target_dir]

Defaults: source ``../分级病例库/data/cases`` (outside this repository),
target ``data/case_library`` (gitignored — the cases stay out of git until
they pass dual expert review, per the plan's 数量服从质量 rule).

Error-type codes are mapped onto the working eight-type dictionary; the
mapping is recorded per case in ``source.note``.  Prototype patient scripts
have no disposition options (and inventing medical content is not a
converter's job), so they are preserved verbatim under
``content.patient_script_wp9`` for the WP9 dynamic engine instead of being
embedded as ``patient_script``.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT.parent / "分级病例库" / "data" / "cases"
DEFAULT_TARGET = REPO_ROOT / "data" / "case_library"

ERROR_TYPE_MAP = {
    # library codes that differ from the working dictionary
    "decision_basis": "decision_rationale",
    "ethics_blindspot": "ethical_blind_spot",
    "logic_break": "logic_breakpoint",
    # ai-companion prototype codes (shared converter lineage)
    "differential_omission": "differential_exclusion",
    "evidence_omission": "evidence_gap",
    "premature_conclusion": "decision_bias",
    "improper_treatment": "decision_bias",
    "logic_jump": "logic_breakpoint",
    "over_testing": "decision_rationale",
    "concept_confusion": "symptom_attribution",
}

DIMENSION_MAP = {
    "symptomComplexity": "complexity",
    "diagnosisDifficulty": "diagnostic",
    "decisionComplexity": "decision",
    "situationalSpecialty": "situational",
}


def convert(raw: dict) -> dict:
    case_code = raw["caseId"].replace("resp-", "RESP-").upper()
    dims = {DIMENSION_MAP[k]: v for k, v in raw["complexity"].items()}
    remapped = sorted({ERROR_TYPE_MAP.get(e["errorType"], e["errorType"]) for e in raw.get("commonErrors", [])})
    content = {
        "chief_complaint": raw["chiefComplaint"],
        "present_illness": raw["presentIllness"],
        "past_history": raw["pastHistory"],
        "physical_examination": raw["physicalExamination"],
        "auxiliary_exams": [
            {
                "exam_name": exam.get("examName", ""),
                "category": exam.get("category", ""),
                "result": exam.get("result", ""),
                "is_key_evidence": bool(exam.get("isKeyEvidence", False)),
            }
            for exam in raw.get("auxiliaryExams", [])
        ],
        "diagnosis": raw["diagnosis"],
        "key_evidence": raw["keyEvidence"],
        "differential_diagnosis": raw["differentialDiagnosis"],
        "common_errors": [
            {
                "error_type": ERROR_TYPE_MAP.get(err["errorType"], err["errorType"]),
                "description": err.get("description", ""),
                "trigger_feedback": err.get("triggerFeedback", err.get("trigger_feedback", "")),
            }
            for err in raw.get("commonErrors", [])
        ],
        "diagnostic_pitfalls": raw.get("diagnosticPitfalls", []),
        "training_objectives": raw["trainingObjectives"],
        "standard_workflow": raw.get("standardWorkflow", []),
        "scoring_rubric": raw.get("scoringRubric"),
    }
    if raw.get("patientScript"):
        content["patient_script_wp9"] = raw["patientScript"]

    source_note = (
        f"converted from 150-case synthetic library ({raw['caseId']}); "
        f"error codes remapped to the working dictionary: {remapped}"
    )
    if raw.get("patientScript"):
        source_note += "; prototype patient script preserved as patient_script_wp9 (no disposition options - WP9)"
    return {
        "schema_version": 1,
        "case_code": case_code,
        "title": raw["title"],
        "disease": raw.get("disease", ""),
        "level": raw["level"],
        "dimensions": dims,
        "knowledge_points": [
            {"code": f"dx-{i:02d}", "name": name}
            for i, name in enumerate(raw.get("knowledgeGraphEntities", {}).get("diagnoses", []), 1)
        ],
        "content": content,
        "source": {
            "origin": "synthetic",
            "author": raw.get("author", "case-library"),
            "note": source_note,
        },
        "change_note": "converted from 150-case synthetic library",
    }


def main() -> int:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    target = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_TARGET
    target.mkdir(parents=True, exist_ok=True)

    files = sorted(source.glob("*.json"))
    if not files:
        print(f"no case files found under {source}", file=sys.stderr)
        return 1
    converted, failed = 0, 0
    for path in files:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            payload = convert(raw)
            out = target / f"{payload['case_code']}.json"
            out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            converted += 1
        except (KeyError, ValueError) as exc:
            print(f"FAILED {path.name}: {exc}", file=sys.stderr)
            failed += 1
    print(f"converted {converted}, failed {failed} -> {target}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
