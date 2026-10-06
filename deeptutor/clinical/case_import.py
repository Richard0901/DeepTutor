"""Batch import of case JSON files into the clinical case library.

Usage from code::

    from deeptutor.clinical.case_import import import_directory, write_case_template

    report = import_directory(conn, Path("deeptutor/clinical/seed_cases"))
    report = import_directory(conn, Path("..."), publish_approved=False)

A directory import never stops on the first bad file: every payload is
validated and the report lists per-file errors so a batch of expert-authored
cases can be fixed in one pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from deeptutor.clinical.schemas import TEMPLATE_SCHEMA_VERSION, CaseValidationError
from deeptutor.clinical.service import ClinicalCaseService
from deeptutor.teaching.database import migrate
from deeptutor.teaching.service import ConflictError

TEMPLATE_FILENAME = "case_template.json"


@dataclass
class ImportReport:
    imported: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (file, reason)

    @property
    def ok(self) -> bool:
        return not self.skipped

    def summary(self) -> str:
        lines = [f"imported {len(self.imported)} case(s)"]
        for name, reason in self.skipped:
            lines.append(f"skipped {name}: {reason}")
        return "\n".join(lines)


def case_template() -> dict[str, Any]:
    """Return a filled example of the case import template."""
    return {
        "schema_version": TEMPLATE_SCHEMA_VERSION,
        "case_code": "RESP-L1-000",
        "title": "社区获得性肺炎（示例，导入前请替换全部内容）",
        "disease": "社区获得性肺炎",
        "level": "L1",
        "dimensions": {
            "complexity": 1,
            "diagnostic": 1,
            "decision": 1,
            "situational": 1,
        },
        "dimension_rationale": {
            "complexity": "单一系统、症状典型",
            "diagnostic": "常见病，典型体征即可建立诊断",
            "decision": "标准治疗路径，无冲突决策",
            "situational": "普通门诊环境",
        },
        "knowledge_points": [
            {"code": "resp-cap", "name": "社区获得性肺炎"},
        ],
        "content": {
            "chief_complaint": "发热咳嗽 3 天（示例）",
            "present_illness": "（示例）患者 3 天前受凉后出现发热……",
            "past_history": "（示例）既往体健……",
            "physical_examination": "（示例）T 38.5℃ …… 双肺湿啰音……",
            "auxiliary_exams": [
                {
                    "exam_name": "血常规",
                    "category": "lab",
                    "result": "WBC 12.5×10^9/L，NEUT% 82%",
                    "is_key_evidence": True,
                },
            ],
            "diagnosis": "社区获得性肺炎（示例）",
            "key_evidence": ["（示例）发热、湿啰音、炎性指标升高"],
            "differential_diagnosis": ["（示例）肺结核：……"],
            "common_errors": [
                {
                    "error_type": "differential_exclusion",
                    "description": "（示例）未鉴别肺结核",
                    "trigger_feedback": "（示例）发热患者还需要排除哪些疾病？",
                },
            ],
            "diagnostic_pitfalls": ["（示例）……"],
            "training_objectives": ["（示例）掌握 CAP 的诊断流程"],
            "standard_workflow": ["问诊 → 体格检查 → 胸部影像 → 诊断 → 治疗"],
        },
        "source": {
            "origin": "synthetic",
            "author": "teaching-team",
            "note": "示例模板：真实病例导入前必须完成伦理备案与脱敏（计划 §10）",
        },
        "change_note": "initial import",
    }


def write_case_template(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / TEMPLATE_FILENAME
    path.write_text(
        json.dumps(case_template(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def import_case_file(conn, path: Path, *, tenant_id: str = "default", actor_id: str = "case-import") -> str:
    """Import one JSON file; returns the case_id. Raises on invalid payload."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if path.name == TEMPLATE_FILENAME:
        raise CaseValidationError(["refusing to import the template file itself"])
    service = ClinicalCaseService(conn)
    if _case_exists(service, payload["case_code"], tenant_id):
        raise ConflictError(f"case_code '{payload['case_code']}' already imported")
    case, _version = service.create_case(payload, actor_id=actor_id, tenant_id=tenant_id)
    return case.case_id


def _case_exists(service: ClinicalCaseService, case_code: str, tenant_id: str) -> bool:
    try:
        service.get_case_by_code(case_code, tenant_id=tenant_id)
    except Exception:
        return False
    return True


def import_directory(
    conn,
    directory: Path,
    *,
    tenant_id: str = "default",
    actor_id: str = "case-import",
) -> ImportReport:
    """Import every ``*.json`` file in ``directory`` (not recursive)."""
    migrate(conn)
    report = ImportReport()
    service = ClinicalCaseService(conn)
    for path in sorted(Path(directory).glob("*.json")):
        try:
            if path.name == TEMPLATE_FILENAME:
                raise CaseValidationError(["refusing to import the template file itself"])
            payload = json.loads(path.read_text(encoding="utf-8"))
            if _case_exists(service, payload["case_code"], tenant_id):
                raise ConflictError(f"case_code '{payload['case_code']}' already imported")
            case, _version = service.create_case(payload, actor_id=actor_id, tenant_id=tenant_id)
            report.imported.append(f"{path.name} -> {case.case_code}")
        except (CaseValidationError, ConflictError, json.JSONDecodeError, KeyError) as exc:
            report.skipped.append((path.name, str(exc)))
    return report
