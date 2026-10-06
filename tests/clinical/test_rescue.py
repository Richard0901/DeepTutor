"""Rescue engine tests (WP9-1): simulated clock, vitals evolution, resource
constraints, evacuation deadline and replay identity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.clinical.attempts import REQUIRED_STEP_TYPES, AttemptService
from deeptutor.clinical.case_import import case_template
from deeptutor.clinical.service import ClinicalCaseService
from deeptutor.clinical.virtual_patient.engine import Action, replay
from deeptutor.clinical.virtual_patient.rescue import (
    RescueConfigError,
    apply_rescue_step,
    parse_rescue_config,
)
from deeptutor.clinical.virtual_patient.service import (
    PatientSessionService,
    SessionStateError,
)
from deeptutor.teaching.database import connect, migrate
from deeptutor.teaching.service import TeachingService

SEED = (
    Path(__file__).resolve().parents[2]
    / "deeptutor"
    / "clinical"
    / "seed_cases"
    / "RESP-L4-003.json"
)


def _rescue_config() -> dict:
    return json.loads(SEED.read_text(encoding="utf-8"))["content"]["patient_script"]["rescue"]


# -- pure config + transition tests -------------------------------------------


def test_rescue_config_validation():
    cfg = parse_rescue_config(_rescue_config())
    assert cfg.time_budget_minutes == 60 and cfg.evac_eta_minutes == 40
    with pytest.raises(RescueConfigError):
        parse_rescue_config({"time_budget_minutes": 0, "evac_eta_minutes": 10})
    with pytest.raises(RescueConfigError):
        parse_rescue_config({"time_budget_minutes": 60, "evac_eta_minutes": "soon"})
    assert parse_rescue_config(None) is None


def test_intervention_and_deterioration_sequence():
    cfg = parse_rescue_config(_rescue_config())
    step = apply_rescue_step(
        cfg, elapsed_minutes=0, vitals={"oxygenSaturation": 78, "heartRate": 118},
        symptoms=(), resources_used={}, interventions_taken=(),
        action_type="order_exam", payload={"exam_name": "高流量湿化氧疗"},
    )
    assert step["error"] is None
    assert step["elapsed_minutes"] == 5  # order_exam costs 5
    assert step["vitals"]["oxygenSaturation"] == 88  # 78 + 10
    assert step["resources_used"] == {"oxygen": 1}

    state = step
    events: list[dict] = []
    # wait 10 -> elapsed 15, exactly crossing the 15-minute checkpoint
    state = apply_rescue_step(
        cfg, elapsed_minutes=state["elapsed_minutes"], vitals=state["vitals"],
        symptoms=state["symptoms"], resources_used=state["resources_used"],
        interventions_taken=state["interventions_taken"],
        action_type="wait", payload={"minutes": 10},
    )
    events.extend(state["rescue_events"])
    assert state["elapsed_minutes"] == 15
    assert "deterioration" in [e["event"] for e in events]
    assert state["vitals"]["oxygenSaturation"] == 84  # 88 - 4
    assert "意识淡漠" in state["symptoms"]

    # the oxygen intervention is single-shot: repeating it has no effect
    # (cost 5 stays below the 30-minute checkpoint so no new deterioration)
    again = apply_rescue_step(
        cfg, elapsed_minutes=state["elapsed_minutes"], vitals=state["vitals"],
        symptoms=state["symptoms"], resources_used=state["resources_used"],
        interventions_taken=state["interventions_taken"],
        action_type="order_exam", payload={"exam_name": "高流量湿化氧疗"},
    )
    assert again["vitals"]["oxygenSaturation"] == 84


def test_resource_shortage_blocks_effect():
    cfg = parse_rescue_config(_rescue_config())
    result = apply_rescue_step(
        cfg, elapsed_minutes=5, vitals={"oxygenSaturation": 88},
        symptoms=(), resources_used={"oxygen": 3}, interventions_taken=(),
        action_type="order_exam", payload={"exam_name": "高流量湿化氧疗"},
    )
    assert any(e["event"] == "resource_shortage" for e in result["rescue_events"])
    assert result["vitals"]["oxygenSaturation"] == 88  # unchanged


def test_time_budget_rejects_action():
    cfg = parse_rescue_config(_rescue_config())
    result = apply_rescue_step(
        cfg, elapsed_minutes=58, vitals={}, symptoms=(), resources_used={},
        interventions_taken=(), action_type="wait", payload={"minutes": 10},
    )
    assert result["error"] and "time budget" in result["error"]


# -- service-level tests --------------------------------------------------------


@pytest.fixture()
def env(tmp_path):
    conn = connect(tmp_path / "rescue.db")
    migrate(conn)
    teaching = TeachingService(conn)
    cases = ClinicalCaseService(conn)
    attempts = AttemptService(conn)

    seed = json.loads(SEED.read_text(encoding="utf-8"))
    payload = case_template()
    payload["case_code"] = seed["case_code"]
    payload["title"] = seed["title"]
    payload["level"] = seed["level"]
    payload["dimensions"] = seed["dimensions"]
    payload["disease"] = seed["disease"]
    payload["content"] = seed["content"]
    case, _ = cases.create_case(payload, actor_id="author-1")
    cases.submit_for_review(case.case_id, actor_id="author-1")
    cases.record_review(case.case_id, reviewer_id="r1", decision="approve")
    cases.record_review(case.case_id, reviewer_id="r2", decision="approve")
    cases.publish(case.case_id, actor_id="admin-1")

    course = teaching.create_course("default", "RESP", "呼吸", created_by="admin-1")
    cls = teaching.create_class(course.course_id, "1班", created_by="admin-1")
    teaching.add_member(cls.class_id, "admin-1", "course_admin", actor_id="admin-1")
    teaching.add_member(cls.class_id, "teacher-1", "teacher", actor_id="admin-1")
    teaching.add_member(cls.class_id, "student-1", "student", actor_id="admin-1")
    assignment = teaching.create_assignment(
        cls.class_id, case.case_id, "战救训练", actor_id="teacher-1", publish=True
    )
    patients = PatientSessionService(conn)
    yield type("Env", (), {
        "conn": conn, "teaching": teaching, "cases": cases, "attempts": attempts,
        "patients": patients, "assignment": assignment, "case": case,
    })()
    conn.close()


def _open_session(env):
    attempt = env.attempts.create_attempt(env.assignment.assignment_id, student_id="student-1")
    session = env.patients.create_session(attempt.attempt_id, actor_id="student-1")
    return attempt, session


def test_rescue_session_view_and_clock(env):
    _attempt, session = _open_session(env)
    sid = session["session_id"]
    view = env.patients.get_session(sid, actor_id="student-1")
    assert view["rescue"]["elapsed_minutes"] == 0
    assert view["rescue"]["vitals"]["oxygenSaturation"] == 78
    assert view["rescue"]["time_budget_minutes"] == 60

    result = env.patients.perform_action(sid, actor_id="student-1", action=Action("begin"))
    assert result["released"]["rescue_events"][0]["event"] == "time"
    view = env.patients.get_session(sid, actor_id="student-1")
    assert view["rescue"]["elapsed_minutes"] == 2  # begin costs 2


def test_wait_reassess_and_deterioration_timeline(env):
    attempt = env.attempts.create_attempt(env.assignment.assignment_id, student_id="student-1")
    session = env.patients.create_session(attempt.attempt_id, actor_id="student-1")
    sid = session["session_id"]
    svc = env.patients

    svc.perform_action(sid, actor_id="student-1", action=Action("begin"))  # t=2
    svc.perform_action(
        sid, actor_id="student-1", action=Action("order_exam", {"exam_name": "高流量湿化氧疗"})
    )  # t=7, SpO2 88
    result = svc.perform_action(
        sid, actor_id="student-1", action=Action("wait", {"minutes": 10})
    )  # t=17, crosses 15-min checkpoint
    assert result["released"]["elapsed_minutes"] == 17
    assert result["released"]["vitals"]["oxygenSaturation"] == 84
    reassess = svc.perform_action(sid, actor_id="student-1", action=Action("reassess"))
    assert reassess["released"]["vitals"]["oxygenSaturation"] == 84
    assert "意识淡漠" in reassess["released"]["symptoms"]
    final = svc.perform_action(
        sid, actor_id="student-1", action=Action("wait", {"minutes": 10})
    )  # t=27+3(reassess)=... reassess cost 3 -> t=20, wait 10 -> t=30
    # crossing the 30-min checkpoint fires on this wait
    assert final["released"]["vitals"]["oxygenSaturation"] == 79  # 84 - 5
    assert "咯血加重" in final["released"]["symptoms"]

    samples = env.conn.execute(
        "SELECT source, elapsed_minutes, vitals_json FROM vital_sign_samples"
        " WHERE session_id = ? ORDER BY seq",
        (sid,),
    ).fetchall()
    assert samples[0]["source"] == "initial" and samples[0]["elapsed_minutes"] == 0
    assert samples[-1]["elapsed_minutes"] == 30
    assert any(row["source"] == "reassess" for row in samples)
    assert env.conn.execute("SELECT COUNT(*) FROM scenario_constraints").fetchone()[0] == 1


def test_outcome_records_evac_metrics(env):
    attempt = env.attempts.create_attempt(env.assignment.assignment_id, student_id="student-1")
    session = env.patients.create_session(attempt.attempt_id, actor_id="student-1")
    sid = session["session_id"]
    svc = env.patients
    svc.perform_action(sid, actor_id="student-1", action=Action("begin"))  # t=2
    svc.perform_action(sid, actor_id="student-1", action=Action("ask_question", {"text": "怎么不好"}))  # t=5
    svc.perform_action(
        sid, actor_id="student-1", action=Action("ask_question", {"text": "上高原第几天了"})
    )  # t=8, both required topics revealed
    svc.perform_action(sid, actor_id="student-1", action=Action("advance_phase"))  # t=10
    svc.perform_action(sid, actor_id="student-1", action=Action("advance_phase"))  # -> disposition, t=12
    final = svc.perform_action(
        sid, actor_id="student-1",
        action=Action("submit_disposition", {"option": "边氧疗边后送：填伤票、战友陪同，立即后送"}),
    )
    outcome = final["released"]["rescue_outcome"]
    assert outcome["disposition_correct"] is True
    assert outcome["elapsed_minutes"] == 17  # 12 + submit 5
    assert outcome["evac_in_time"] is True and outcome["time_remaining_minutes"] == 43


def test_outcome_late_evacuation_fails(env):
    attempt = env.attempts.create_attempt(env.assignment.assignment_id, student_id="student-1")
    session = env.patients.create_session(attempt.attempt_id, actor_id="student-1")
    sid = session["session_id"]
    svc = env.patients
    svc.perform_action(sid, actor_id="student-1", action=Action("begin"))
    svc.perform_action(sid, actor_id="student-1", action=Action("ask_question", {"text": "怎么不好"}))
    svc.perform_action(sid, actor_id="student-1", action=Action("ask_question", {"text": "上高原第几天了"}))
    svc.perform_action(sid, actor_id="student-1", action=Action("advance_phase"))
    svc.perform_action(sid, actor_id="student-1", action=Action("advance_phase"))
    svc.perform_action(sid, actor_id="student-1", action=Action("wait", {"minutes": 40}))  # t=55
    final = svc.perform_action(
        sid, actor_id="student-1",
        action=Action("submit_disposition", {"option": "边氧疗边后送：填伤票、战友陪同，立即后送"}),
    )
    outcome = final["released"]["rescue_outcome"]
    assert outcome["evac_in_time"] is False and outcome["elapsed_minutes"] == 57


def test_replay_identity_with_rescue(env):
    _attempt, session = _open_session(env)
    sid = session["session_id"]
    svc = env.patients
    svc.perform_action(sid, actor_id="student-1", action=Action("begin"))
    svc.perform_action(
        sid, actor_id="student-1", action=Action("order_exam", {"exam_name": "高流量湿化氧疗"})
    )
    svc.perform_action(sid, actor_id="student-1", action=Action("wait", {"minutes": 10}))
    events = svc.list_events(sid, actor_id="student-1")
    script, _hash = svc._script_for_case(env.case.case_id)
    state = replay(script, events)
    view = svc.get_session(sid, actor_id="student-1")
    assert state.elapsed_minutes == view["rescue"]["elapsed_minutes"]
    assert state.vitals == view["rescue"]["vitals"]
    assert state.terminated is False


def test_non_rescue_scripts_reject_wait(env):
    payload = case_template()
    payload["case_code"] = "RESP-L1-971"
    payload["content"]["patient_script"] = {
        "script_version": 2,
        "inquiry_map": [
            {"topic": "主诉", "keywords": ["怎么不好"], "response": "发热咳嗽。", "is_key_info": True}
        ],
        "exam_results": [{"exam_name": "胸片", "result_description": "左下叶实变"}],
        "disposition_options": [{"name": "抗感染治疗", "feedback": "正确", "is_correct": True}],
    }
    case, _ = env.cases.create_case(payload, actor_id="author-1")
    env.cases.submit_for_review(case.case_id, actor_id="author-1")
    env.cases.record_review(case.case_id, reviewer_id="r1", decision="approve")
    env.cases.record_review(case.case_id, reviewer_id="r2", decision="approve")
    env.cases.publish(case.case_id, actor_id="admin-1")
    assignment = env.teaching.create_assignment(
        env.assignment.class_id, case.case_id, "普通训练", actor_id="teacher-1", publish=True
    )
    attempt = env.attempts.create_attempt(assignment.assignment_id, student_id="student-1")
    session = env.patients.create_session(attempt.attempt_id, actor_id="student-1")
    with pytest.raises(SessionStateError, match="not allowed"):
        env.patients.perform_action(
            session["session_id"], actor_id="student-1", action=Action("wait", {"minutes": 5})
        )
    # no vital samples for non-rescue sessions
    count = env.conn.execute(
        "SELECT COUNT(*) FROM vital_sign_samples WHERE session_id = ?",
        (session["session_id"],),
    ).fetchone()[0]
    assert count == 0
