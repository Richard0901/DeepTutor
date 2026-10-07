"""Case import tests: template validation, batch import and seed coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.clinical.case_import import (
    ImportReport,
    case_template,
    import_directory,
    write_case_template,
)
from deeptutor.clinical.schemas import CaseValidationError, validate_case_payload
from deeptutor.clinical.service import ClinicalCaseService
from deeptutor.teaching.database import connect, migrate

SEED_CASES = Path(__file__).resolve().parents[2] / "deeptutor" / "clinical" / "seed_cases"


@pytest.fixture()
def conn(tmp_path):
    connection = connect(tmp_path / "import.db")
    migrate(connection)
    yield connection
    connection.close()


def test_template_validates_against_schema():
    assert validate_case_payload(case_template())  # no exception


def test_missing_dimensions_rejected():
    payload = case_template()
    del payload["dimensions"]
    with pytest.raises(CaseValidationError) as excinfo:
        validate_case_payload(payload)
    assert any("dimensions" in e for e in excinfo.value.errors)


def test_dimension_out_of_range_rejected():
    payload = case_template()
    payload["dimensions"]["decision"] = 6
    with pytest.raises(CaseValidationError):
        validate_case_payload(payload)


def test_unknown_error_type_rejected():
    payload = case_template()
    payload["content"]["common_errors"][0]["error_type"] = "free_form_whining"
    with pytest.raises(CaseValidationError) as excinfo:
        validate_case_payload(payload)
    assert any("common_errors" in e for e in excinfo.value.errors)


def test_non_synthetic_origin_must_be_explicit():
    payload = case_template()
    payload["source"]["origin"] = "real_patient"
    with pytest.raises(CaseValidationError):
        validate_case_payload(payload)


def test_batch_import_reports_errors_without_stopping(tmp_path, conn):
    good = case_template()
    good["case_code"] = "RESP-L1-701"
    (tmp_path / "good.json").write_text(json.dumps(good, ensure_ascii=False), encoding="utf-8")

    bad = case_template()
    bad["case_code"] = "RESP-L1-702"
    bad["level"] = "L7"
    (tmp_path / "bad.json").write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")

    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    write_case_template(tmp_path)  # template file must be refused

    report = import_directory(conn, tmp_path)
    assert len(report.imported) == 1
    names = [name for name, _ in report.skipped]
    assert set(names) == {"bad.json", "broken.json", "case_template.json"}
    # The good case is queryable after the batch.
    case = ClinicalCaseService(conn).get_case_by_code("RESP-L1-701")
    assert case.level == "L1"


def test_reimport_same_batch_is_safe(tmp_path, conn):
    payload = case_template()
    payload["case_code"] = "RESP-L1-703"
    (tmp_path / "c.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    first = import_directory(conn, tmp_path)
    second = import_directory(conn, tmp_path)
    assert len(first.imported) == 1
    assert not second.imported
    assert len(second.skipped) == 1 and "already imported" in second.skipped[0][1]


@pytest.mark.skipif(not SEED_CASES.is_dir(), reason="seed cases not present")
def test_seed_cases_all_import_cleanly(conn):
    """The bundled seed library must always pass import validation."""
    report = import_directory(conn, SEED_CASES)
    assert report.ok, report.summary()
    assert len(report.imported) == len(list(SEED_CASES.glob("*.json")))
    service = ClinicalCaseService(conn)
    by_level: dict[str, int] = {}
    for case in service.list_cases():
        by_level[case.level] = by_level.get(case.level, 0) + 1
        assert case.status == "draft"  # seeds are drafts pending dual review
    assert by_level == {"L1": 3, "L2": 3, "L3": 2, "L4": 5}


@pytest.mark.skipif(not SEED_CASES.is_dir(), reason="seed cases not present")
def test_seed_cases_cover_required_fields():
    for path in sorted(SEED_CASES.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        validate_case_payload(payload)
        content = payload["content"]
        assert len(content["key_evidence"]) >= 3
        assert len(content["common_errors"]) >= 2
        assert content["scoring_rubric"]["maxScore"] == 100


def test_import_report_defaults_ok():
    assert ImportReport().ok
