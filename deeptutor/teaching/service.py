"""Business logic for the teaching organization domain.

All writes go through this service — no raw SQL outside it — so the role
rules and tenant scoping stay in one auditable place.  Every record carries
its ``tenant_id``; queries that list content are tenant-scoped.
"""

from __future__ import annotations

import sqlite3
from typing import Any
import uuid

from deeptutor.teaching.models import (
    COURSE_ROLES,
    Assignment,
    ClassMembership,
    Course,
    TeachingClass,
    Tenant,
    utc_now,
)


class TeachingError(Exception):
    """Base class for teaching-domain rule violations."""


class NotFoundError(TeachingError):
    pass


class PermissionDeniedError(TeachingError):
    pass


class ConflictError(TeachingError):
    pass


def _uuid() -> str:
    return uuid.uuid4().hex


class TeachingService:
    """Course / class / membership / assignment management."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # -- tenants ----------------------------------------------------------

    def ensure_tenant(self, tenant_id: str, name: str | None = None) -> Tenant:
        row = self._conn.execute(
            "SELECT * FROM tenants WHERE tenant_id = ?", (tenant_id,)
        ).fetchone()
        if row is not None:
            return Tenant(**dict(row))
        now = utc_now()
        self._conn.execute(
            "INSERT INTO tenants (tenant_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (tenant_id, name or tenant_id, now, now),
        )
        self._conn.commit()
        return Tenant(tenant_id=tenant_id, name=name or tenant_id, created_at=now, updated_at=now)

    # -- courses ----------------------------------------------------------

    def create_course(
        self,
        tenant_id: str,
        code: str,
        title: str,
        *,
        created_by: str,
        description: str = "",
    ) -> Course:
        if not code.strip():
            raise TeachingError("course code must not be empty")
        if not title.strip():
            raise TeachingError("course title must not be empty")
        self.ensure_tenant(tenant_id)
        now = utc_now()
        course_id = _uuid()
        try:
            self._conn.execute(
                """
                INSERT INTO courses (course_id, tenant_id, code, title, description,
                                     created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (course_id, tenant_id, code.strip(), title.strip(), description, created_by, now, now),
            )
            self._conn.execute(
                """
                INSERT INTO course_versions (version_id, course_id, version, changelog,
                                             created_by, created_at)
                VALUES (?, ?, 1, 'initial', ?, ?)
                """,
                (_uuid(), course_id, created_by, now),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError(f"course code '{code}' already exists in tenant '{tenant_id}'") from exc
        self._conn.commit()
        return self.get_course(course_id, tenant_id=tenant_id)

    def get_course(self, course_id: str, *, tenant_id: str | None = None) -> Course:
        row = self._conn.execute(
            "SELECT * FROM courses WHERE course_id = ?", (course_id,)
        ).fetchone()
        if row is None or (tenant_id is not None and row["tenant_id"] != tenant_id):
            raise NotFoundError(f"course '{course_id}' not found")
        return Course(**dict(row))

    def list_courses(self, tenant_id: str) -> list[Course]:
        rows = self._conn.execute(
            "SELECT * FROM courses WHERE tenant_id = ? ORDER BY created_at", (tenant_id,)
        ).fetchall()
        return [Course(**dict(row)) for row in rows]

    # -- classes ----------------------------------------------------------

    def create_class(
        self,
        course_id: str,
        name: str,
        *,
        created_by: str,
        semester: str = "",
    ) -> TeachingClass:
        course = self.get_course(course_id)
        if not name.strip():
            raise TeachingError("class name must not be empty")
        now = utc_now()
        class_id = _uuid()
        self._conn.execute(
            """
            INSERT INTO teaching_classes (class_id, course_id, name, semester,
                                          created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (class_id, course.course_id, name.strip(), semester, created_by, now, now),
        )
        self._conn.commit()
        return self.get_class(class_id, tenant_id=course.tenant_id)

    def get_class(self, class_id: str, *, tenant_id: str | None = None) -> TeachingClass:
        row = self._conn.execute(
            """
            SELECT tc.*, c.tenant_id AS tenant_id FROM teaching_classes tc
            JOIN courses c ON c.course_id = tc.course_id
            WHERE tc.class_id = ?
            """,
            (class_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"class '{class_id}' not found")
        data = dict(row)
        row_tenant = data.pop("tenant_id")
        if tenant_id is not None and row_tenant != tenant_id:
            raise NotFoundError(f"class '{class_id}' not found")
        return TeachingClass(**data)

    def list_classes(self, course_id: str) -> list[TeachingClass]:
        rows = self._conn.execute(
            "SELECT * FROM teaching_classes WHERE course_id = ? ORDER BY created_at",
            (course_id,),
        ).fetchall()
        return [TeachingClass(**dict(row)) for row in rows]

    # -- memberships ------------------------------------------------------

    def add_member(
        self,
        class_id: str,
        user_id: str,
        role: str,
        *,
        actor_id: str,
    ) -> ClassMembership:
        if role not in COURSE_ROLES:
            raise TeachingError(f"unknown course role '{role}'")
        if not user_id.strip():
            raise TeachingError("user_id must not be empty")
        self.get_class(class_id)
        active_count = self._conn.execute(
            "SELECT COUNT(*) FROM class_memberships WHERE class_id = ? AND dropped_at IS NULL",
            (class_id,),
        ).fetchone()[0]
        if active_count > 0:
            # Only course admins and teachers of the class manage memberships;
            # the very first member of an empty class bootstraps without one.
            self.require_role(class_id, actor_id, allowed=("course_admin", "teacher"))
        existing = self._conn.execute(
            "SELECT * FROM class_memberships WHERE class_id = ? AND user_id = ?",
            (class_id, user_id),
        ).fetchone()
        now = utc_now()
        if existing is not None:
            if existing["dropped_at"] is None:
                raise ConflictError(f"user '{user_id}' is already a member of class '{class_id}'")
            self._conn.execute(
                """
                UPDATE class_memberships SET role = ?, dropped_at = NULL, enrolled_at = ?
                WHERE membership_id = ?
                """,
                (role, now, existing["membership_id"]),
            )
            membership_id = existing["membership_id"]
        else:
            membership_id = _uuid()
            self._conn.execute(
                """
                INSERT INTO class_memberships (membership_id, class_id, user_id, role, enrolled_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (membership_id, class_id, user_id, role, now),
            )
        self._conn.commit()
        return self.get_membership(class_id, user_id)

    def remove_member(self, class_id: str, user_id: str, *, actor_id: str) -> None:
        self.require_role(class_id, actor_id, allowed=("course_admin", "teacher"))
        membership = self._conn.execute(
            "SELECT * FROM class_memberships WHERE class_id = ? AND user_id = ? AND dropped_at IS NULL",
            (class_id, user_id),
        ).fetchone()
        if membership is None:
            raise NotFoundError(f"user '{user_id}' is not an active member of class '{class_id}'")
        self._conn.execute(
            "UPDATE class_memberships SET dropped_at = ? WHERE membership_id = ?",
            (utc_now(), membership["membership_id"]),
        )
        self._conn.commit()

    def get_membership(self, class_id: str, user_id: str) -> ClassMembership | None:
        row = self._conn.execute(
            "SELECT * FROM class_memberships WHERE class_id = ? AND user_id = ? AND dropped_at IS NULL",
            (class_id, user_id),
        ).fetchone()
        if row is None:
            return None
        return ClassMembership(**dict(row))

    def list_members(self, class_id: str, *, actor_id: str) -> list[ClassMembership]:
        # Any active member may see the roster; outsiders may not.
        self.require_role(class_id, actor_id, allowed=COURSE_ROLES)
        rows = self._conn.execute(
            "SELECT * FROM class_memberships WHERE class_id = ? AND dropped_at IS NULL ORDER BY enrolled_at",
            (class_id,),
        ).fetchall()
        return [ClassMembership(**dict(row)) for row in rows]

    def require_role(
        self,
        class_id: str,
        user_id: str,
        *,
        allowed: tuple[str, ...] = COURSE_ROLES,
    ) -> ClassMembership:
        membership = self.get_membership(class_id, user_id)
        if membership is None:
            raise PermissionDeniedError(f"user '{user_id}' is not a member of class '{class_id}'")
        if membership.role not in allowed:
            raise PermissionDeniedError(
                f"role '{membership.role}' is not allowed for this action on class '{class_id}'"
            )
        return membership

    def classes_for_user(self, user_id: str, *, tenant_id: str | None = None) -> list[TeachingClass]:
        """Classes the user is an active member of, for access-scoped listings."""
        sql = """
            SELECT tc.* FROM teaching_classes tc
            JOIN class_memberships m ON m.class_id = tc.class_id
            JOIN courses c ON c.course_id = tc.course_id
            WHERE m.user_id = ? AND m.dropped_at IS NULL
        """
        params: list[Any] = [user_id]
        if tenant_id is not None:
            sql += " AND c.tenant_id = ?"
            params.append(tenant_id)
        rows = self._conn.execute(sql + " ORDER BY tc.created_at", params).fetchall()
        return [TeachingClass(**dict(row)) for row in rows]

    # -- assignments ------------------------------------------------------

    def create_assignment(
        self,
        class_id: str,
        case_id: str,
        title: str,
        *,
        actor_id: str,
        description: str = "",
        due_at: str | None = None,
        publish: bool = False,
    ) -> Assignment:
        self.require_role(class_id, actor_id, allowed=("course_admin", "teacher"))
        case = self._conn.execute(
            "SELECT status FROM clinical_cases WHERE case_id = ?", (case_id,)
        ).fetchone()
        if case is None:
            raise NotFoundError(f"case '{case_id}' not found")
        if case["status"] != "published":
            # Plan hard constraint #3: unreviewed cases never reach students.
            raise TeachingError("assignments may only reference published cases")
        assignment_id = _uuid()
        self._conn.execute(
            """
            INSERT INTO assignments (assignment_id, class_id, case_id, title, description,
                                     due_at, status, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                assignment_id,
                class_id,
                case_id,
                title.strip(),
                description,
                due_at,
                "open" if publish else "draft",
                actor_id,
                utc_now(),
            ),
        )
        self._conn.commit()
        return self.get_assignment(assignment_id)

    def get_assignment(self, assignment_id: str) -> Assignment:
        row = self._conn.execute(
            "SELECT * FROM assignments WHERE assignment_id = ?", (assignment_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"assignment '{assignment_id}' not found")
        return Assignment(**dict(row))

    def list_assignments(self, class_id: str, *, actor_id: str) -> list[Assignment]:
        self.require_role(class_id, actor_id, allowed=COURSE_ROLES)
        rows = self._conn.execute(
            "SELECT * FROM assignments WHERE class_id = ? ORDER BY created_at", (class_id,)
        ).fetchall()
        return [Assignment(**dict(row)) for row in rows]

    def set_assignment_status(self, assignment_id: str, status: str, *, actor_id: str) -> Assignment:
        if status not in ("draft", "open", "closed"):
            raise TeachingError(f"unknown assignment status '{status}'")
        assignment = self.get_assignment(assignment_id)
        self.require_role(assignment.class_id, actor_id, allowed=("course_admin", "teacher"))
        self._conn.execute(
            "UPDATE assignments SET status = ? WHERE assignment_id = ?", (status, assignment_id)
        )
        self._conn.commit()
        return self.get_assignment(assignment_id)
