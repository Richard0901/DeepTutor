"""Virtual patient MVP tests: script validation, deterministic engine,
event-sourced sessions and the submit gate."""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.clinical.attempts import REQUIRED_STEP_TYPES, AttemptService, AttemptStateError
from deeptutor.clinical.case_import import case_template
from deeptutor.clinical.service import ClinicalCaseService
from deeptutor.clinical.virtual_patient.engine import Action, PatientState, apply, replay
from deeptutor.clinical.virtual_patient.script import (
    ScriptError,
    load_script,
    script_from_content,
)
from deeptutor.clinical.virtual_patient.service import PatientSessionService
from deeptutor.teaching.database import connect, migrate
from deeptutor.teaching.service import (
    NotFoundError,
    PermissionDeniedError,
    TeachingError,
    TeachingService,
)

SEEDS = Path(__file__).resolve().parents[2] / "deeptutor" / "clinical" / "seed_cases"


def _script_config():
    return {
        "script_version": 2,
        "profile": {"name": "张先生", "age": 35, "gender": "男"},
        "initial_vitals": {"heartRate": 102},
        "inquiry_map": [
            {"topic": "主诉", "keywords": ["怎么不好", "哪里不舒服"], "response": "喘得厉害。", "is_key_info": True},
            {"topic": "既往史", "keywords": ["以前", "病史"], "response": "哮喘五年。", "is_key_info": True},
            {"topic": "家族史", "keywords": ["家族", "母亲"], "response": "母亲有哮喘。", "is_key_info": False},
        ],
        "exam_results": [
            {"exam_name": "肺功能", "result_description": "舒张试验阳性", "is_definitive": True},
            {"exam_name": "血常规", "result_description": "EOS 升高"},
        ],
        "disposition_options": [
            {"name": "雾化+激素住院", "feedback": "正确", "is_correct": True},
            {"name": "仅雾化", "feedback": "欠妥", "is_correct": False},
        ],
        "required_revelations": ["主诉"],
    }


@pytest.fixture()
def env(tmp_path):
    conn = connect(tmp_path / "vp.db")
    migrate(conn)
    teaching = TeachingService(conn)
    cases = ClinicalCaseService(conn)
    attempts = AttemptService(conn)
    patients = PatientSessionService(conn)

    # A case with a script.
    payload = case_template()
    payload["case_code"] = "RESP-L2-950"
    payload["content"]["patient_script"] = _script_config()
    scripted, _ = cases.create_case(payload, actor_id="author-1")
    _publish(cases, scripted.case_id)

    # A case without a script.
    plain_payload = case_template()
    plain_payload["case_code"] = "RESP-L2-951"
    plain, _ = cases.create_case(plain_payload, actor_id="author-1")
    _publish(cases, plain.case_id)

    course = teaching.create_course("default", "RESP", "呼吸", created_by="admin-1")
    cls = teaching.create_class(course.course_id, "1班", created_by="admin-1")
    teaching.add_member(cls.class_id, "admin-1", "course_admin", actor_id="admin-1")
    teaching.add_member(cls.class_id, "teacher-1", "teacher", actor_id="admin-1")
    teaching.add_member(cls.class_id, "student-1", "student", actor_id="admin-1")
    a1 = teaching.create_assignment(cls.class_id, scripted.case_id, "L2训练", actor_id="teacher-1", publish=True)
    a2 = teaching.create_assignment(cls.class_id, plain.case_id, "无脚本训练", actor_id="teacher-1", publish=True)

    yield type("Env", (), {
        "conn": conn, "teaching": teaching, "cases": cases, "attempts": attempts,
        "patients": patients, "a1": a1, "a2": a2,
    })()
    conn.close()


def _publish(cases, case_id):
    cases.submit_for_review(case_id, actor_id="author-1")
    cases.record_review(case_id, reviewer_id="r1", decision="approve")
    cases.record_review(case_id, reviewer_id="r2", decision="approve")
    cases.publish(case_id, actor_id="admin-1")


# -- script schema -----------------------------------------------------------


def test_seed_l2_script_loads_and_plain_case_has_no_script():
    import json

    payload = json.loads((SEEDS / "RESP-L2-001.json").read_text(encoding="utf-8"))
    script = script_from_content(payload["content"])
    assert script is not None and len(script.inquiry_map) >= 5 and len(script.exams) >= 3
    assert any(d.is_correct for d in script.dispositions)
    # L4 mass-casualty script is WP9-shaped and must be treated as "no script".
    payload4 = json.loads((SEEDS / "RESP-L4-001.json").read_text(encoding="utf-8"))
    assert script_from_content(payload4["content"]) is None


def test_script_validation_rejects_bad_configs():
    cfg = _script_config()
    with pytest.raises(ScriptError):
        load_script({**cfg, "inquiry_map": []})
    with pytest.raises(ScriptError):
        load_script({**cfg, "disposition_options": [{"name": "x", "is_correct": False}]})
    with pytest.raises(ScriptError):
        load_script({**cfg, "phase_actions": {"nonexistent_phase": ["begin"]}})


# -- engine determinism --------------------------------------------------------


def test_phase_gating_and_wrong_phase_actions():
    script = load_script(_script_config())
    state = PatientState()
    wrong = apply(state, script, Action("ask_question", {"text": "怎么不好"}))
    assert wrong.error and "not allowed" in wrong.error
    began = apply(state, script, Action("begin"))
    assert began.next_state.phase == "history_taking"
    asked = apply(began.next_state, script, Action("ask_question", {"text": "你哪里不舒服？"}))
    assert asked.next_state.revealed_topics == ("主诉",)
    assert asked.released["is_key_info"] is True and "新信息" in asked.released["reply"]
    repeat = apply(asked.next_state, script, Action("ask_question", {"text": "哪里不舒服？"}))
    assert "新信息" not in repeat.released["reply"]
    fallback = apply(began.next_state, script, Action("ask_question", {"text": "今天天气如何"}))
    assert fallback.released["matched_topic"] is None


def test_disposition_gate_requires_revelations_and_terminates():
    script = load_script(_script_config())
    state = PatientState(phase="disposition")
    blocked = apply(state, script, Action("submit_disposition", {"option": "雾化+激素住院"}))
    assert blocked.error and "missing required information" in blocked.error
    revealed = PatientState(phase="disposition", revealed_topics=("主诉",))
    ok = apply(revealed, script, Action("submit_disposition", {"option": "雾化+激素住院"}))
    assert ok.next_state.terminated and ok.next_state.disposition_correct is True
    unknown = apply(revealed, script, Action("submit_disposition", {"option": "不存在的方案"}))
    assert unknown.error and "not configured" in unknown.error
    after = apply(ok.next_state, script, Action("ask_question", {"text": "怎么不好"}))
    assert after.error and "terminated" in after.error


def test_replay_reconstructs_identical_state():
    script = load_script(_script_config())
    events = []
    state = PatientState()
    for action, payload in [
        ("begin", {}),
        ("ask_question", {"text": "你哪里不舒服？"}),
        ("ask_question", {"text": "以前有什么病史吗"}),
        ("advance_phase", {}),
        ("order_exam", {"exam_name": "肺功能"}),
        ("advance_phase", {}),
        ("submit_disposition", {"option": "雾化+激素住院"}),
    ]:
        act = Action(action, payload)
        outcome = apply(state, script, act)
        assert outcome.error is None, outcome.error
        events.append({"action_type": action, "payload": act.normalized_payload()})
        state = outcome.next_state
    assert replay(script, events).to_json() == state.to_json()


# -- service behavior -----------------------------------------------------------


def _full_steps(env, attempt_id):
    for st in REQUIRED_STEP_TYPES:
        env.attempts.add_step(attempt_id, actor_id="student-1", step_type=st, content=st)


def test_session_requires_owner_and_in_progress_attempt(env):
    # Use the plain case: lifecycle checks must not depend on the script gate.
    attempt = env.attempts.create_attempt(env.a2.assignment_id, student_id="student-1")
    with pytest.raises(PermissionDeniedError):
        env.patients.create_session(attempt.attempt_id, actor_id="student-x")
    _full_steps(env, attempt.attempt_id)
    env.attempts.submit(attempt.attempt_id, actor_id="student-1")
    # A submitted attempt no longer accepts sessions.
    with pytest.raises(TeachingError, match="in-progress"):
        env.patients.create_session(attempt.attempt_id, actor_id="student-1")


def test_full_consultation_flow_and_submit_gate(env):
    attempt = env.attempts.create_attempt(env.a1.assignment_id, student_id="student-1")
    _full_steps(env, attempt.attempt_id)
    with pytest.raises(AttemptStateError, match="virtual patient"):
        env.attempts.submit(attempt.attempt_id, actor_id="student-1")

    session = env.patients.create_session(attempt.attempt_id, actor_id="student-1")
    sid = session["session_id"]
    assert session["phase"] == "initial" and session["profile"]["name"] == "张先生"

    # Outsiders can neither see nor act on the session.
    with pytest.raises(NotFoundError):
        env.patients.get_session(sid, actor_id="student-x")
    with pytest.raises(PermissionDeniedError):
        env.patients.perform_action(sid, actor_id="student-x", action=Action("begin"))

    env.patients.perform_action(sid, actor_id="student-1", action=Action("begin"))
    asked = env.patients.perform_action(
        sid, actor_id="student-1", action=Action("ask_question", {"text": "你哪里不舒服？"})
    )
    assert "新信息" in asked["released"]["reply"]
    env.patients.perform_action(sid, actor_id="student-1", action=Action("ask_question", {"text": "以前有什么病史吗"}))

    # Wrong phase for exams before advancing; then exam works.
    from deeptutor.clinical.virtual_patient.service import SessionStateError

    with pytest.raises(SessionStateError, match="not allowed"):
        env.patients.perform_action(
            sid, actor_id="student-1", action=Action("order_exam", {"exam_name": "肺功能"})
        )
    env.patients.perform_action(sid, actor_id="student-1", action=Action("advance_phase"))
    exam = env.patients.perform_action(
        sid, actor_id="student-1", action=Action("order_exam", {"exam_name": "肺功能"})
    )
    assert exam["released"]["is_definitive"] is True
    with pytest.raises(SessionStateError, match="not configured"):
        env.patients.perform_action(
            sid, actor_id="student-1", action=Action("order_exam", {"exam_name": "不存在的检查"})
        )

    env.patients.perform_action(sid, actor_id="student-1", action=Action("advance_phase"))
    # Phase gate: required_revelations=["主诉"] were revealed in history_taking.
    final = env.patients.perform_action(
        sid, actor_id="student-1", action=Action("submit_disposition", {"option": "雾化+激素住院"})
    )
    assert final["released"]["is_correct"] is True
    assert final["state"]["terminated"] is True

    # Terminated sessions reject further actions...
    with pytest.raises(SessionStateError, match="terminated"):
        env.patients.perform_action(
            sid, actor_id="student-1", action=Action("ask_question", {"text": "怎么不好"})
        )
    # ...but the consultation is fully replayable.
    events = env.patients.list_events(sid, actor_id="student-1")
    assert [e["action_type"] for e in events] == [
        "begin", "ask_question", "ask_question", "advance_phase",
        "order_exam", "advance_phase", "submit_disposition",
    ]
    script, _hash = env.patients._script_for_case(env.a1.case_id if hasattr(env.a1, "case_id") else _case_id(env))
    assert replay(script, events).terminated is True

    # The submit gate now passes and the attempt can be graded.
    submitted = env.attempts.submit(attempt.attempt_id, actor_id="student-1")
    assert submitted.status == "submitted"
    reviewed = env.attempts.record_review(attempt.attempt_id, reviewer_id="teacher-1", notes="ok")
    assert reviewed.status == "reviewed"


def _case_id(env):
    return env.conn.execute("SELECT case_id FROM assignments WHERE assignment_id = ?", (env.a1.assignment_id,)).fetchone()[0]


def test_plain_case_has_no_session_gate(env):
    attempt = env.attempts.create_attempt(env.a2.assignment_id, student_id="student-1")
    _full_steps(env, attempt.attempt_id)
    # No script -> submit works without any patient session.
    assert env.attempts.submit(attempt.attempt_id, actor_id="student-1").status == "submitted"
    # But a session on a submitted attempt is refused for lifecycle reasons.
    with pytest.raises(TeachingError, match="in-progress"):
        env.patients.create_session(attempt.attempt_id, actor_id="student-1")
    # And a fresh in-progress attempt on the plain case refuses sessions
    # because the case carries no usable script.
    fresh = env.attempts.create_attempt(env.a2.assignment_id, student_id="student-1")
    with pytest.raises(TeachingError, match="no usable virtual patient"):
        env.patients.create_session(fresh.attempt_id, actor_id="student-1")
