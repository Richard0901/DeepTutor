"""Patient session service: sessions, actions, event log and replay.

The service owns persistence; the engine owns truth.  Every accepted action
appends exactly one event; session state is always reconstructible from the
event log via :func:`deeptutor.clinical.virtual_patient.engine.replay`.
"""

from __future__ import annotations

import json
import sqlite3
import uuid

from deeptutor.clinical.virtual_patient.engine import (
    Action,
    PatientState,
    apply,
    replay,
)
from deeptutor.clinical.virtual_patient.script import (
    PatientScript,
    ScriptError,
    script_from_content,
)
from deeptutor.teaching.models import utc_now
from deeptutor.teaching.service import NotFoundError, PermissionDeniedError, TeachingError


def _uuid() -> str:
    return uuid.uuid4().hex


class SessionStateError(TeachingError):
    pass


class PatientSessionService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # -- helpers -----------------------------------------------------------

    def _session_row(self, session_id: str) -> sqlite3.Row:
        row = self._conn.execute(
            "SELECT * FROM patient_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"patient session '{session_id}' not found")
        return row

    def _script_for_case(self, case_id: str) -> tuple[PatientScript, str]:
        row = self._conn.execute(
            "SELECT current_version_id FROM clinical_cases WHERE case_id = ?", (case_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"case '{case_id}' not found")
        # content_json stores the whole case payload; the script lives under
        # the payload's "content" key.
        content = json.loads(
            self._conn.execute(
                "SELECT content_json FROM case_versions WHERE version_id = ?",
                (row["current_version_id"],),
            ).fetchone()["content_json"]
        ).get("content", {})
        script = script_from_content(content)
        if script is None:
            raise TeachingError("this case has no usable virtual patient script")
        return script, script.content_hash()

    def _events(self, session_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM patient_events WHERE session_id = ? ORDER BY seq", (session_id,)
        ).fetchall()
        return [
            {
                "action_type": row["action_type"],
                "payload": json.loads(row["payload_json"]),
                "released": json.loads(row["released_json"]),
                "phase_after": row["phase_after"],
            }
            for row in rows
        ]

    def _replay_state(self, session_row: sqlite3.Row, script: PatientScript) -> PatientState:
        try:
            return replay(script, self._events(session_row["session_id"]))
        except ScriptError as exc:
            # A stored log must always replay; failure means tampering or a bug.
            raise TeachingError(f"session '{session_row['session_id']}' event log is inconsistent: {exc}") from exc

    # -- workflow ------------------------------------------------------------

    def create_session(self, attempt_id: str, *, actor_id: str) -> dict:
        attempt = self._conn.execute(
            "SELECT * FROM case_attempts WHERE attempt_id = ?", (attempt_id,)
        ).fetchone()
        if attempt is None:
            raise NotFoundError(f"attempt '{attempt_id}' not found")
        if attempt["student_id"] != actor_id:
            raise PermissionDeniedError("only the attempt owner can open a patient session")
        if attempt["status"] != "in_progress":
            raise SessionStateError(
                f"attempt '{attempt_id}' is '{attempt['status']}'; sessions belong to in-progress attempts"
            )
        case_id = self._conn.execute(
            "SELECT case_id FROM assignments WHERE assignment_id = ?",
            (attempt["assignment_id"],),
        ).fetchone()["case_id"]
        script, script_hash = self._script_for_case(case_id)
        self._ensure_scenario_constraints(case_id)
        session_id = _uuid()
        now = utc_now()
        self._conn.execute(
            """
            INSERT INTO patient_sessions (session_id, attempt_id, case_id, student_id,
                                          script_hash, status, phase, started_at, created_at)
            VALUES (?, ?, ?, ?, ?, 'active', 'initial', ?, ?)
            """,
            (session_id, attempt_id, case_id, actor_id, script_hash, now, now),
        )
        if script.rescue is not None:
            import json as _json

            self._conn.execute(
                """
                INSERT INTO vital_sign_samples (sample_id, session_id, seq, elapsed_minutes,
                                                vitals_json, source, trigger, created_at)
                VALUES (?, ?, 0, 0, ?, 'initial', 'session start', ?)
                """,
                (
                    _uuid(),
                    session_id,
                    _json.dumps(script.initial_vitals_numeric(), ensure_ascii=False),
                    now,
                ),
            )
        self._conn.commit()
        return self.get_session(session_id, actor_id=actor_id)

    def _ensure_scenario_constraints(self, case_id: str) -> None:
        """Snapshot the case version's rescue config into scenario_constraints
        (idempotent per case version; a queryable index of rescue cases)."""
        row = self._conn.execute(
            """
            SELECT cc.current_version_id, cv.content_json FROM clinical_cases cc
            JOIN case_versions cv ON cv.version_id = cc.current_version_id
            WHERE cc.case_id = ?
            """,
            (case_id,),
        ).fetchone()
        if row is None:
            return
        existing = self._conn.execute(
            "SELECT 1 FROM scenario_constraints WHERE case_version_id = ?",
            (row["current_version_id"],),
        ).fetchone()
        if existing is not None:
            return
        from deeptutor.clinical.virtual_patient.script import script_from_content

        script = script_from_content(json.loads(row["content_json"]).get("content", {}))
        if script is None or script.rescue is None:
            return
        import json as _json

        self._conn.execute(
            """
            INSERT OR IGNORE INTO scenario_constraints (constraint_id, case_id, case_version_id,
                                                        constraint_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                _uuid(),
                case_id,
                row["current_version_id"],
                _json.dumps(script.rescue.content_hash_input(), ensure_ascii=False),
                utc_now(),
            ),
        )

    def perform_action(self, session_id: str, *, actor_id: str, action: Action) -> dict:
        row = self._session_row(session_id)
        if row["student_id"] != actor_id:
            raise PermissionDeniedError("only the session owner can act")
        if row["status"] != "active":
            raise SessionStateError(f"session '{session_id}' is '{row['status']}'")
        script, script_hash = self._script_for_case(row["case_id"])
        if script_hash != row["script_hash"]:
            raise TeachingError("case script changed after the session started; start a new session")

        state = self._replay_state(row, script)
        outcome = apply(state, script, action)
        if outcome.error is not None:
            raise SessionStateError(outcome.error)

        seq = self._conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM patient_events WHERE session_id = ?",
            (session_id,),
        ).fetchone()[0]
        now = utc_now()
        self._conn.execute(
            """
            INSERT INTO patient_events (event_id, session_id, seq, action_type,
                                        payload_json, released_json, phase_after, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _uuid(),
                session_id,
                seq,
                action.action_type,
                json.dumps(action.normalized_payload(), ensure_ascii=False),
                json.dumps(outcome.released, ensure_ascii=False),
                outcome.next_state.phase,
                now,
            ),
        )
        terminated = outcome.next_state.terminated
        self._conn.execute(
            """
            UPDATE patient_sessions
            SET phase = ?, status = ?, outcome_json = ?, terminated_at = ?
            WHERE session_id = ?
            """,
            (
                outcome.next_state.phase,
                "terminated" if terminated else "active",
                json.dumps(outcome.next_state.to_json(), ensure_ascii=False) if terminated else None,
                now if terminated else None,
                session_id,
            ),
        )
        if script.rescue is not None:
            self._conn.execute(
                """
                INSERT INTO vital_sign_samples (sample_id, session_id, seq, elapsed_minutes,
                                                vitals_json, source, trigger, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _uuid(),
                    session_id,
                    seq,
                    outcome.next_state.elapsed_minutes,
                    json.dumps(outcome.next_state.vitals, ensure_ascii=False),
                    "reassess" if action.action_type == "reassess" else "action",
                    action.action_type,
                    now,
                ),
            )
        self._conn.commit()
        return {
            "session_id": session_id,
            "seq": seq,
            "released": outcome.released,
            "state": outcome.next_state.to_json(),
        }

    # -- reads -----------------------------------------------------------------

    def get_session(self, session_id: str, *, actor_id: str) -> dict:
        row = self._session_row(session_id)
        if row["student_id"] != actor_id:
            # Teachers read attempts through the analytics layer (WP8); the
            # patient dialogue itself stays private to the student for now.
            raise NotFoundError(f"patient session '{session_id}' not found")
        script, _hash = self._script_for_case(row["case_id"])
        state = self._replay_state(row, script)
        outcome = None
        if row["outcome_json"]:
            outcome = json.loads(row["outcome_json"])
        response = {
            "session_id": row["session_id"],
            "attempt_id": row["attempt_id"],
            "case_id": row["case_id"],
            "status": row["status"],
            "phase": state.phase,
            "profile": script.profile,
            "initial_vitals": script.initial_vitals,
            "revealed_topics": list(state.revealed_topics),
            "revealed_results": list(state.revealed_results),
            "disposition": state.disposition,
            "outcome": outcome,
            "started_at": row["started_at"],
            "terminated_at": row["terminated_at"],
        }
        if script.rescue is not None:
            response["rescue"] = {
                "elapsed_minutes": state.elapsed_minutes,
                "time_budget_minutes": script.rescue.time_budget_minutes,
                "time_remaining_minutes": script.rescue.time_budget_minutes - state.elapsed_minutes,
                "vitals": state.vitals or script.initial_vitals_numeric(),
                "symptoms": list(state.symptoms),
                "resources_used": state.resources_used,
                "evac_eta_minutes": script.rescue.evac_eta_minutes,
            }
        return response

    def list_events(self, session_id: str, *, actor_id: str) -> list[dict]:
        self.get_session(session_id, actor_id=actor_id)  # visibility gate
        return self._events(session_id)

    def latest_session(self, attempt_id: str, *, actor_id: str) -> dict:
        """Most recent session of the attempt, or raise NotFoundError."""
        row = self._conn.execute(
            "SELECT session_id FROM patient_sessions WHERE attempt_id = ?"
            " ORDER BY created_at DESC LIMIT 1",
            (attempt_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"no patient session for attempt '{attempt_id}'")
        return self.get_session(row["session_id"], actor_id=actor_id)

    def has_terminated_session(self, attempt_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM patient_sessions WHERE attempt_id = ? AND status = 'terminated' LIMIT 1",
            (attempt_id,),
        ).fetchone()
        return row is not None
