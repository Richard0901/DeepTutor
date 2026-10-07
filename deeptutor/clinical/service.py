"""Case lifecycle service: versions, dual review, publication.

Workflow (plan WP3 / SKILL.md hard constraints):

    create → draft
    submit_for_review(actor)        draft → under_review
    record_review(reviewer, approve) ×2 distinct reviewers → approved
    record_review(reviewer, reject)  under_review → draft (rejected kept on record)
    publish(actor)                   approved → published
    create_new_version(actor)        published → draft v(n+1); v(n) untouched
                                     until the successor is published
    retire(actor)                    published → retired
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any
import uuid

from deeptutor.teaching.audit import record_audit
from deeptutor.teaching.models import CaseReview, CaseVersion, ClinicalCase, utc_now
from deeptutor.teaching.service import ConflictError, NotFoundError, TeachingError

REQUIRED_APPROVALS = 2


def _uuid() -> str:
    return uuid.uuid4().hex


class CaseStateError(TeachingError):
    """Raised when a lifecycle transition is not allowed."""


def _row_to_case(row: sqlite3.Row) -> ClinicalCase:
    return ClinicalCase(**dict(row))


def _row_to_version(row: sqlite3.Row) -> CaseVersion:
    data = dict(row)
    data["content"] = json.loads(data.pop("content_json"))
    return CaseVersion(**data)


class ClinicalCaseService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # -- creation ---------------------------------------------------------

    def create_case(
        self,
        payload: dict,
        *,
        actor_id: str,
        tenant_id: str = "default",
    ) -> tuple[ClinicalCase, CaseVersion]:
        from deeptutor.clinical.schemas import validate_case_payload

        payload = validate_case_payload(payload)
        from deeptutor.teaching.service import TeachingService

        TeachingService(self._conn).ensure_tenant(tenant_id)
        now = utc_now()
        case_id = _uuid()
        try:
            self._conn.execute(
                """
                INSERT INTO clinical_cases (case_id, tenant_id, case_code, title, disease, level,
                                            dimension_complexity, dimension_diagnostic,
                                            dimension_decision, dimension_situational,
                                            status, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?)
                """,
                (
                    case_id,
                    tenant_id,
                    payload["case_code"].strip(),
                    payload["title"].strip(),
                    payload.get("disease", ""),
                    payload["level"],
                    payload["dimensions"]["complexity"],
                    payload["dimensions"]["diagnostic"],
                    payload["dimensions"]["decision"],
                    payload["dimensions"]["situational"],
                    actor_id,
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError(
                f"case_code '{payload['case_code']}' already exists in tenant '{tenant_id}'"
            ) from exc
        version = self._insert_version(case_id, version=1, payload=payload, actor_id=actor_id,
                                       change_note="initial import", created_at=now)
        self._conn.commit()
        return self.get_case(case_id, tenant_id=tenant_id), version

    def _insert_version(
        self,
        case_id: str,
        *,
        version: int,
        payload: dict,
        actor_id: str,
        change_note: str,
        created_at: str,
    ) -> CaseVersion:
        from deeptutor.clinical.schemas import validate_case_payload

        payload = validate_case_payload(payload)
        content_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        content_hash = hashlib.sha256(content_json.encode("utf-8")).hexdigest()
        version_id = _uuid()
        self._conn.execute(
            """
            INSERT INTO case_versions (version_id, case_id, version, content_json, content_hash,
                                       status, change_note, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, 'draft', ?, ?, ?)
            """,
            (version_id, case_id, version, content_json, content_hash, change_note, actor_id, created_at),
        )
        dims = payload["dimensions"]
        rationale = payload.get("dimension_rationale", {})
        for dim in ("complexity", "diagnostic", "decision", "situational"):
            self._conn.execute(
                "INSERT INTO case_dimensions (id, version_id, dimension, score, rationale) VALUES (?, ?, ?, ?, ?)",
                (_uuid(), version_id, dim, dims[dim], str(rationale.get(dim, ""))),
            )
        for kp in payload.get("knowledge_points", []):
            self._conn.execute(
                "INSERT INTO case_knowledge_points (id, version_id, kp_code, kp_name) VALUES (?, ?, ?, ?)",
                (_uuid(), version_id, kp["code"], kp["name"]),
            )
        self._conn.execute(
            "UPDATE clinical_cases SET current_version_id = ?, updated_at = ? WHERE case_id = ?",
            (version_id, created_at, case_id),
        )
        return CaseVersion(
            version_id=version_id,
            case_id=case_id,
            version=version,
            content=payload,
            content_hash=content_hash,
            created_by=actor_id,
            created_at=created_at,
        )

    # -- reads ------------------------------------------------------------

    def get_case(self, case_id: str, *, tenant_id: str | None = None) -> ClinicalCase:
        row = self._conn.execute(
            "SELECT * FROM clinical_cases WHERE case_id = ?", (case_id,)
        ).fetchone()
        if row is None or (tenant_id is not None and row["tenant_id"] != tenant_id):
            raise NotFoundError(f"case '{case_id}' not found")
        return _row_to_case(row)

    def get_case_by_code(self, case_code: str, *, tenant_id: str = "default") -> ClinicalCase:
        row = self._conn.execute(
            "SELECT * FROM clinical_cases WHERE case_code = ? AND tenant_id = ?",
            (case_code, tenant_id),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"case '{case_code}' not found")
        return _row_to_case(row)

    def list_cases(
        self,
        *,
        tenant_id: str = "default",
        level: str | None = None,
        status: str | None = None,
    ) -> list[ClinicalCase]:
        sql = "SELECT * FROM clinical_cases WHERE tenant_id = ?"
        params: list[Any] = [tenant_id]
        if level is not None:
            sql += " AND level = ?"
            params.append(level)
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        rows = self._conn.execute(sql + " ORDER BY case_code", params).fetchall()
        return [_row_to_case(row) for row in rows]

    def get_version(self, version_id: str) -> CaseVersion:
        row = self._conn.execute(
            "SELECT * FROM case_versions WHERE version_id = ?", (version_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"case version '{version_id}' not found")
        return _row_to_version(row)

    def list_versions(self, case_id: str) -> list[CaseVersion]:
        rows = self._conn.execute(
            "SELECT * FROM case_versions WHERE case_id = ? ORDER BY version", (case_id,)
        ).fetchall()
        return [_row_to_version(row) for row in rows]

    def list_reviews(self, version_id: str) -> list[CaseReview]:
        rows = self._conn.execute(
            "SELECT * FROM case_review_records WHERE version_id = ? ORDER BY created_at",
            (version_id,),
        ).fetchall()
        return [CaseReview(**dict(row)) for row in rows]

    # -- lifecycle --------------------------------------------------------

    def _set_case_status(self, case_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE clinical_cases SET status = ?, updated_at = ? WHERE case_id = ?",
            (status, utc_now(), case_id),
        )

    def _set_version_status(self, version_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE case_versions SET status = ? WHERE version_id = ?", (status, version_id)
        )

    def submit_for_review(self, case_id: str, *, actor_id: str) -> ClinicalCase:
        case = self.get_case(case_id)
        if case.status != "draft":
            raise CaseStateError(f"case '{case_id}' is '{case.status}', only draft cases can enter review")
        version = self.get_version(case.current_version_id)  # type: ignore[arg-type]
        if version.status not in ("draft", "rejected"):
            raise CaseStateError(f"version '{version.version_id}' is '{version.status}'")
        self._set_version_status(version.version_id, "under_review")
        self._set_case_status(case_id, "under_review")
        self._conn.commit()
        return self.get_case(case_id)

    def record_review(
        self,
        case_id: str,
        *,
        reviewer_id: str,
        decision: str,
        comments: str = "",
    ) -> ClinicalCase:
        if decision not in ("approve", "reject", "request_changes"):
            raise TeachingError(f"unknown review decision '{decision}'")
        case = self.get_case(case_id)
        if case.status != "under_review":
            raise CaseStateError(f"case '{case_id}' is '{case.status}', review records apply to under_review cases")
        version = self.get_version(case.current_version_id)  # type: ignore[arg-type]
        if version.created_by == reviewer_id:
            raise CaseStateError("the author cannot review their own case")
        prior = self._conn.execute(
            "SELECT decision FROM case_review_records WHERE version_id = ? AND reviewer_id = ?",
            (version.version_id, reviewer_id),
        ).fetchone()
        if prior is not None:
            raise ConflictError(f"reviewer '{reviewer_id}' already reviewed this version")

        self._conn.execute(
            """
            INSERT INTO case_review_records (review_id, case_id, version_id, reviewer_id,
                                             decision, comments, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (_uuid(), case_id, version.version_id, reviewer_id, decision, comments, utc_now()),
        )
        record_audit(
            self._conn,
            actor_id=reviewer_id,
            action="case_review",
            object_type="case",
            object_id=case_id,
            summary={"decision": decision},
        )
        if decision == "approve":
            approvals = self._conn.execute(
                """
                SELECT COUNT(DISTINCT reviewer_id) FROM case_review_records
                WHERE version_id = ? AND decision = 'approve'
                """,
                (version.version_id,),
            ).fetchone()[0]
            if approvals >= REQUIRED_APPROVALS:
                self._set_version_status(version.version_id, "approved")
                self._set_case_status(case_id, "approved")
        else:
            self._set_version_status(version.version_id, "rejected")
            self._set_case_status(case_id, "draft")
        self._conn.commit()
        return self.get_case(case_id)

    def publish(self, case_id: str, *, actor_id: str) -> ClinicalCase:
        case = self.get_case(case_id)
        if case.status != "approved":
            raise CaseStateError(
                f"case '{case_id}' is '{case.status}'; publication requires {REQUIRED_APPROVALS} distinct approvals"
            )
        version = self.get_version(case.current_version_id)  # type: ignore[arg-type]
        if version.status != "approved":
            raise CaseStateError(f"version '{version.version_id}' is '{version.status}'")
        has_published = self._conn.execute(
            "SELECT 1 FROM case_versions WHERE case_id = ? AND status = 'published' LIMIT 1",
            (case_id,),
        ).fetchone()
        if has_published:
            # A published version already exists — a revision must go through
            # publish_new_version so the old version is superseded explicitly.
            raise CaseStateError("a published version exists; use publish_new_version")
        self._set_version_status(version.version_id, "published")
        self._set_case_status(case_id, "published")
        record_audit(
            self._conn,
            actor_id=actor_id,
            action="case_publish",
            object_type="case",
            object_id=case_id,
            summary={"version_id": version.version_id},
        )
        self._conn.commit()
        return self.get_case(case_id)

    def create_new_version(self, case_id: str, payload: dict, *, actor_id: str) -> CaseVersion:
        """Draft a successor version of a published case; the published
        version stays live and untouched until the successor is published."""
        from deeptutor.clinical.schemas import validate_case_payload

        case = self.get_case(case_id)
        if case.status not in ("published", "draft", "retired"):
            raise CaseStateError(f"case '{case_id}' is '{case.status}'")
        payload = validate_case_payload(payload)
        latest = self._conn.execute(
            "SELECT MAX(version) FROM case_versions WHERE case_id = ?", (case_id,)
        ).fetchone()[0]
        version = self._insert_version(
            case_id,
            version=int(latest) + 1,
            payload=payload,
            actor_id=actor_id,
            change_note=payload.get("change_note", "revision"),
            created_at=utc_now(),
        )
        if case.status == "published":
            self._set_case_status(case_id, "draft")
        self._conn.commit()
        return self.get_version(version.version_id)

    def retire(self, case_id: str, *, actor_id: str) -> ClinicalCase:
        case = self.get_case(case_id)
        if case.status != "published":
            raise CaseStateError(f"case '{case_id}' is '{case.status}', only published cases can retire")
        self._set_case_status(case_id, "retired")
        record_audit(
            self._conn,
            actor_id=actor_id,
            action="case_retire",
            object_type="case",
            object_id=case_id,
        )
        self._conn.commit()
        return self.get_case(case_id)

    def publish_new_version(self, case_id: str, *, actor_id: str) -> ClinicalCase:
        """Publish the case's newest approved version and supersede the old one."""
        case = self.get_case(case_id)
        if case.status != "approved":
            raise CaseStateError(f"case '{case_id}' is '{case.status}'")
        versions = self.list_versions(case_id)
        published = [v for v in versions if v.status == "published"]
        successor = versions[-1]
        if not published:
            raise CaseStateError(f"case '{case_id}' has no published version to supersede")
        if successor.version_id == published[0].version_id:
            raise CaseStateError("no successor version exists")
        if successor.status != "approved":
            raise CaseStateError(f"successor version '{successor.version_id}' is '{successor.status}'")
        self._set_version_status(published[0].version_id, "superseded")
        self._set_version_status(successor.version_id, "published")
        self._set_case_status(case_id, "published")
        self._conn.commit()
        return self.get_case(case_id)
