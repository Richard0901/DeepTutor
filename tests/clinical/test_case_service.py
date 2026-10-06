"""Clinical case lifecycle tests: versions, dual review, publication gates."""

from __future__ import annotations

import pytest

from deeptutor.clinical.case_import import case_template
from deeptutor.clinical.service import (
    REQUIRED_APPROVALS,
    CaseStateError,
    ClinicalCaseService,
)
from deeptutor.teaching.database import connect, migrate
from deeptutor.teaching.service import ConflictError


@pytest.fixture()
def svc(tmp_path):
    conn = connect(tmp_path / "clinical.db")
    migrate(conn)
    yield ClinicalCaseService(conn)
    conn.close()


def _payload(case_code="RESP-L2-100"):
    payload = case_template()
    payload["case_code"] = case_code
    payload["level"] = "L2"
    return payload


def _to_published(svc, case_id, author="author-1"):
    svc.submit_for_review(case_id, actor_id=author)
    svc.record_review(case_id, reviewer_id="reviewer-1", decision="approve")
    svc.record_review(case_id, reviewer_id="reviewer-2", decision="approve")
    return svc.publish(case_id, actor_id="admin-1")


def test_create_case_stores_four_dimensions_and_knowledge_points(svc):
    case, version = svc.create_case(_payload(), actor_id="author-1")
    assert case.status == "draft"
    assert case.level == "L2"
    assert case.dimension_situational == 1
    dims = svc._conn.execute(
        "SELECT dimension, score FROM case_dimensions WHERE version_id = ?", (version.version_id,)
    ).fetchall()
    assert {row["dimension"] for row in dims} == {"complexity", "diagnostic", "decision", "situational"}
    kps = svc._conn.execute(
        "SELECT kp_name FROM case_knowledge_points WHERE version_id = ?", (version.version_id,)
    ).fetchall()
    assert any(row["kp_name"] == "社区获得性肺炎" for row in kps)


def test_duplicate_case_code_rejected(svc):
    svc.create_case(_payload("RESP-L1-500"), actor_id="author-1")
    with pytest.raises(ConflictError):
        svc.create_case(_payload("RESP-L1-500"), actor_id="author-1")


def test_publish_requires_dual_approval(svc):
    case, _ = svc.create_case(_payload("RESP-L1-501"), actor_id="author-1")
    with pytest.raises(CaseStateError):
        svc.publish(case.case_id, actor_id="admin-1")  # still draft
    svc.submit_for_review(case.case_id, actor_id="author-1")
    svc.record_review(case.case_id, reviewer_id="reviewer-1", decision="approve")
    with pytest.raises(CaseStateError):
        svc.publish(case.case_id, actor_id="admin-1")  # only one approval
    assert svc.record_review(case.case_id, reviewer_id="reviewer-2", decision="approve").status == "approved"
    assert svc.publish(case.case_id, actor_id="admin-1").status == "published"


def test_author_cannot_review_own_case(svc):
    case, _ = svc.create_case(_payload("RESP-L1-502"), actor_id="author-1")
    svc.submit_for_review(case.case_id, actor_id="author-1")
    with pytest.raises(CaseStateError):
        svc.record_review(case.case_id, reviewer_id="author-1", decision="approve")


def test_rejection_returns_case_to_draft_and_keeps_record(svc):
    case, _ = svc.create_case(_payload("RESP-L1-503"), actor_id="author-1")
    svc.submit_for_review(case.case_id, actor_id="author-1")
    case = svc.record_review(case.case_id, reviewer_id="reviewer-1", decision="reject", comments="证据不足")
    assert case.status == "draft"
    version = svc.get_version(case.current_version_id)
    assert version.status == "rejected"
    reviews = svc.list_reviews(version.version_id)
    assert len(reviews) == 1 and reviews[0].decision == "reject"


def test_same_reviewer_cannot_approve_twice(svc):
    case, _ = svc.create_case(_payload("RESP-L1-504"), actor_id="author-1")
    svc.submit_for_review(case.case_id, actor_id="author-1")
    svc.record_review(case.case_id, reviewer_id="reviewer-1", decision="approve")
    with pytest.raises(ConflictError):
        svc.record_review(case.case_id, reviewer_id="reviewer-1", decision="approve")
    assert svc.get_case(case.case_id).status == "under_review"


def test_published_version_is_immutable_revision_creates_new_version(svc):
    case, v1 = svc.create_case(_payload("RESP-L1-505"), actor_id="author-1")
    _to_published(svc, case.case_id)
    payload2 = _payload("RESP-L1-505")
    payload2["title"] = "修订后的标题"
    new_version = svc.create_new_version(case.case_id, payload2, actor_id="author-1")
    assert new_version.version == 2 and new_version.status == "draft"
    assert svc.get_case(case.case_id).status == "draft"
    # v1 stays published and byte-identical while the successor is drafted.
    stored_v1 = svc.get_version(v1.version_id)
    assert stored_v1.status == "published"
    assert stored_v1.content_hash == v1.content_hash
    # The successor must pass dual review again; plain publish is refused so
    # the supersession goes through publish_new_version explicitly.
    svc.submit_for_review(case.case_id, actor_id="author-1")
    svc.record_review(case.case_id, reviewer_id="reviewer-1", decision="approve")
    svc.record_review(case.case_id, reviewer_id="reviewer-2", decision="approve")
    with pytest.raises(CaseStateError):
        svc.publish(case.case_id, actor_id="admin-1")
    case = svc.publish_new_version(case.case_id, actor_id="admin-1")
    assert case.status == "published"
    assert svc.get_version(v1.version_id).status == "superseded"
    assert svc.get_version(new_version.version_id).status == "published"


def test_invalid_payload_rejected(svc):
    payload = _payload("RESP-L1-506")
    payload["level"] = "L9"
    from deeptutor.clinical.schemas import CaseValidationError

    with pytest.raises(CaseValidationError) as excinfo:
        svc.create_case(payload, actor_id="author-1")
    assert any("level" in e for e in excinfo.value.errors)
    assert REQUIRED_APPROVALS == 2
