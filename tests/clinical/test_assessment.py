"""Assessment framework tests: rules_v1, review workflow, repetition."""

from __future__ import annotations

import pytest

from deeptutor.assessment.llm import LlmAssessorNotImplemented, assess_step
from deeptutor.assessment.rules import assess_attempt
from deeptutor.assessment.service import AssessmentService
from deeptutor.clinical.attempts import REQUIRED_STEP_TYPES, AttemptService
from deeptutor.clinical.case_import import case_template
from deeptutor.clinical.service import ClinicalCaseService
from deeptutor.teaching.database import connect, migrate
from deeptutor.teaching.service import (
    NotFoundError,
    PermissionDeniedError,
    TeachingError,
    TeachingService,
)


@pytest.fixture()
def env(tmp_path):
    conn = connect(tmp_path / "assess.db")
    migrate(conn)
    teaching = TeachingService(conn)
    cases = ClinicalCaseService(conn)
    attempts = AttemptService(conn)
    assessments = AssessmentService(conn)

    payload = case_template()
    payload["case_code"] = "RESP-L2-960"
    case, _ = cases.create_case(payload, actor_id="author-1")
    cases.submit_for_review(case.case_id, actor_id="author-1")
    cases.record_review(case.case_id, reviewer_id="r1", decision="approve")
    cases.record_review(case.case_id, reviewer_id="r2", decision="approve")
    case = cases.publish(case.case_id, actor_id="admin-1")

    course = teaching.create_course("default", "RESP", "呼吸", created_by="admin-1")
    cls = teaching.create_class(course.course_id, "1班", created_by="admin-1")
    teaching.add_member(cls.class_id, "admin-1", "course_admin", actor_id="admin-1")
    teaching.add_member(cls.class_id, "teacher-1", "teacher", actor_id="admin-1")
    teaching.add_member(cls.class_id, "student-1", "student", actor_id="admin-1")
    teaching.add_member(cls.class_id, "student-2", "student", actor_id="admin-1")
    assignment = teaching.create_assignment(
        cls.class_id, case.case_id, "训练", actor_id="teacher-1", publish=True
    )
    yield type("Env", (), {
        "conn": conn, "teaching": teaching, "cases": cases, "attempts": attempts,
        "assessments": assessments, "assignment": assignment, "case": case,
    })()
    conn.close()


def _submitted_attempt(env, *, thin_differential=False):
    attempt = env.attempts.create_attempt(env.assignment.assignment_id, student_id="student-1")
    contents = {
        "problem_presentation": "青年男性，急性起病，喘息伴夜间不能平卧，既往哮喘病史，接触花粉后加重。",
        "differential_diagnosis": "与 COPD 相似但患者年轻无吸烟史，鉴别排除。" if not thin_differential else "就是哮喘。",
        "key_evidence": "双肺广泛哮鸣音，肺功能示阻塞性通气功能障碍，支气"
                        "管舒张试验阳性，嗜酸性粒细胞和 IgE 升高。",
        "investigation": "选择肺功能+舒张试验、血气分析，因为需评估阻塞程度与低氧。",
        "disposition": "雾化+全身激素+氧疗，因为中重度发作需住院观察。",
    }
    for st in REQUIRED_STEP_TYPES:
        env.attempts.add_step(attempt.attempt_id, actor_id="student-1", step_type=st, content=contents[st])
    env.attempts.submit(attempt.attempt_id, actor_id="student-1")
    return attempt


def test_rules_v1_flags_thin_differentiation_only(env):
    attempt = _submitted_attempt(env, thin_differential=True)
    run = env.assessments.run_assessment(attempt.attempt_id, actor_id="teacher-1")
    assert run["engine"] == "rules_v1"
    assert run["summary"]["error_candidates"] >= 1
    diff = [s for s in run["scores"] if s["error_type"] == "differential_exclusion"]
    assert diff, "thin differentiation must be flagged"
    assert diff[0]["needs_human_review"] == 1 and diff[0]["review_status"] == "pending"
    assert diff[0]["confidence"] <= 0.5


def test_rules_v1_clean_attempt_fewer_findings(env):
    attempt = _submitted_attempt(env)
    run = env.assessments.run_assessment(attempt.attempt_id, actor_id="teacher-1")
    assert not [s for s in run["scores"] if s["error_type"] == "differential_exclusion"]


def test_assessment_requires_staff_and_submitted_attempt(env):
    attempt = env.attempts.create_attempt(env.assignment.assignment_id, student_id="student-1")
    with pytest.raises(PermissionDeniedError):
        env.assessments.run_assessment(attempt.attempt_id, actor_id="student-1")
    _submitted_attempt(env)
    with pytest.raises(PermissionDeniedError):
        env.assessments.run_assessment(attempt.attempt_id, actor_id="student-1")
    with pytest.raises(TeachingError):
        env.assessments.run_assessment(attempt.attempt_id, actor_id="teacher-1", engine="llm_local")


def test_llm_stub_fails_loudly():
    with pytest.raises(LlmAssessorNotImplemented):
        assess_step({}, {}, {})


def test_review_workflow_persists_original_and_final(env):
    attempt = _submitted_attempt(env, thin_differential=True)
    run = env.assessments.run_assessment(attempt.attempt_id, actor_id="teacher-1")
    score = next(s for s in run["scores"] if s["error_type"] == "differential_exclusion")

    reviewed = env.assessments.record_review(
        score["score_id"], teacher_id="teacher-1", action="override",
        final_error_type="decision_rationale", comment="实际是决策依据不足",
    )
    assert reviewed["final_error_type"] == "decision_rationale"
    after = env.assessments.get_run(run["run_id"], actor_id="teacher-1")
    row = next(s for s in after["scores"] if s["score_id"] == score["score_id"])
    # The original tag stays visible; only review_status moves (留痕).
    assert row["error_type"] == "differential_exclusion"
    assert row["review_status"] == "overridden"
    # Double review is refused.
    with pytest.raises(TeachingError, match="already reviewed"):
        env.assessments.record_review(score["score_id"], teacher_id="teacher-1", action="agree")


def test_review_queue_scopes_to_class_and_pending(env):
    attempt = _submitted_attempt(env, thin_differential=True)
    run = env.assessments.run_assessment(attempt.attempt_id, actor_id="teacher-1")
    score = run["scores"][0]
    queue = env.assessments.review_queue(env.assignment.class_id, actor_id="teacher-1")
    assert any(item["score_id"] == score["score_id"] for item in queue)
    for item in env.assessments.review_queue(env.assignment.class_id, actor_id="teacher-1"):
        env.assessments.record_review(item["score_id"], teacher_id="teacher-1", action="dismiss")
    assert not env.assessments.review_queue(env.assignment.class_id, actor_id="teacher-1")


def test_rubric_snapshot_idempotent_per_version(env):
    attempt = _submitted_attempt(env)
    env.assessments.run_assessment(attempt.attempt_id, actor_id="teacher-1")
    env.assessments.run_assessment(attempt.attempt_id, actor_id="teacher-1")
    count = env.conn.execute("SELECT COUNT(*) FROM rubric_versions").fetchone()[0]
    assert count == 1


def test_error_repetition_threshold(env):
    from datetime import datetime, timedelta, timezone

    from deeptutor.teaching.models import utc_now

    # Plant confirmed differential_exclusion hits for student-1 on a real
    # run/step pair (FKs require real run_id and step_id).
    attempt = _submitted_attempt(env, thin_differential=True)
    run = env.assessments.run_assessment(attempt.attempt_id, actor_id="teacher-1")
    real_step_id = run["scores"][0]["step_id"]
    run_id = run["run_id"]

    def plant(when):
        score_id = "s" + when[:19].replace(":", "").replace("-", "")
        env.conn.execute(
            "INSERT INTO assessment_scores (score_id, run_id, step_id, error_type, confidence, created_at) VALUES (?,?,?,?,?,?)",
            (score_id, run_id, real_step_id, "differential_exclusion", 0.3, when),
        )
        env.conn.execute(
            "INSERT INTO human_reviews (review_id, score_id, teacher_id, action, final_error_type, created_at) VALUES (?,?,?,?,?,?)",
            ("r" + score_id, score_id, "teacher-1", "agree", None, when),
        )
    base = datetime.now(timezone.utc)
    for i in range(2):
        plant((base - timedelta(days=i)).isoformat(timespec="seconds"))
    report = env.assessments.error_repetition("student-1")
    # The real run's pending finding is not confirmed, planted ones are 2 < 3.
    assert report["confirmed_counts"].get("differential_exclusion", 0) == 2
    assert "differential_exclusion" not in report["compensation_triggered"]
    plant((base - timedelta(days=2)).isoformat(timespec="seconds"))
    report = env.assessments.error_repetition("student-1")
    assert report["confirmed_counts"]["differential_exclusion"] == 3
    assert report["compensation_triggered"] == ["differential_exclusion"]


def test_rules_overlap_needs_real_terms():
    findings = assess_attempt(
        {},
        [{"step_id": "s1", "step_type": "key_evidence", "content": "患者有发热咳嗽"}],
        {"key_evidence": ["支气管舒张试验阳性"]},
    )
    assert any(f["error_type"] == "evidence_integration" for f in findings["findings"])
