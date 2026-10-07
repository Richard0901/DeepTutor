"use client";

/**
 * Typed client helpers for the teaching-domain API (/api/v1/teaching and
 * /api/v1/clinical).  Hand-written types on purpose: the generated contracts
 * cover the upstream surface only (see web/contracts/README.md).
 */

import { apiFetch, apiUrl } from "@/lib/api";

export interface Course {
  course_id: string;
  tenant_id: string;
  code: string;
  title: string;
  description: string;
  status: string;
}

export interface TeachingClass {
  class_id: string;
  course_id: string;
  name: string;
  semester: string;
  status: string;
}

export interface Membership {
  membership_id: string;
  class_id: string;
  user_id: string;
  role: string;
}

export interface Assignment {
  assignment_id: string;
  class_id: string;
  case_id: string;
  title: string;
  description: string;
  due_at: string | null;
  status: string;
}

export interface CaseSummary {
  case_id: string;
  case_code: string;
  title: string;
  disease: string;
  level: string;
  status: string;
  dimension_complexity: number;
  dimension_diagnostic: number;
  dimension_decision: number;
  dimension_situational: number;
}

export interface AttemptView {
  attempt_id: string;
  assignment_id: string;
  student_id: string;
  status: string;
  started_at: string;
  submitted_at: string | null;
  review_notes: string;
  class_id: string;
  assignment_title: string;
  case_id: string;
  case_title: string;
  case_level: string;
}

export interface ReasoningStep {
  step_id: string;
  attempt_id: string;
  step_type: string;
  content: string;
  created_at: string;
}

export interface CaseContent {
  chief_complaint: string;
  present_illness: string;
  past_history: string;
  physical_examination: string;
  auxiliary_exams?: { exam_name: string; result: string; is_key_evidence: boolean }[];
  diagnosis?: string;
  patient_script?: {
    profile?: Record<string, unknown>;
    initial_vitals?: Record<string, unknown>;
    inquiry_map?: { topic: string; keywords: string[]; response: string }[];
    exam_results?: { exam_name: string; result_description: string; is_definitive?: boolean }[];
    disposition_options?: { name: string; feedback: string; is_correct: boolean }[];
  } | null;
}

export interface RescueState {
  elapsed_minutes: number;
  time_budget_minutes: number;
  time_remaining_minutes: number;
  vitals: Record<string, number>;
  symptoms: string[];
  resources_used: Record<string, number>;
  evac_eta_minutes: number;
}

export interface PatientSessionView {
  session_id: string;
  status: string;
  phase: string;
  profile: Record<string, unknown>;
  initial_vitals: Record<string, unknown>;
  revealed_topics: string[];
  revealed_results: string[];
  disposition: string | null;
  outcome: Record<string, unknown> | null;
  rescue?: RescueState | null;
}

export const VITAL_LABELS: Record<string, string> = {
  oxygenSaturation: "SpO2%",
  heartRate: "心率",
  respiratoryRate: "呼吸",
  systolicBP: "收缩压",
};

export const VITAL_ORDER = ["oxygenSaturation", "heartRate", "respiratoryRate", "systolicBP"];

export interface PatientEvent {
  action_type: string;
  payload: Record<string, unknown>;
  released: Record<string, unknown>;
  phase_after: string;
}

export interface AssessmentScore {
  score_id: string;
  step_id: string;
  error_type: string | null;
  confidence: number;
  evidence: string;
  suggestion: string;
  review_status: string;
  student_id?: string;
}

export interface AssessmentRun {
  run_id: string;
  attempt_id: string;
  engine: string;
  summary: { flagged_steps: number; error_candidates: number } | null;
  scores: AssessmentScore[];
}

export interface RiskFlag {
  student_id: string;
  reasons: string[];
  confirmed_errors: Record<string, number>;
  attempts_total: number;
  attempts_submitted: number;
  last_activity_at: string | null;
}

export interface Intervention {
  intervention_id: string;
  class_id: string;
  student_id: string;
  teacher_id: string;
  reason: string;
  note: string;
  status: string;
  outcome: string;
}

export interface ClassOverview {
  class_id: string;
  assignments: {
    assignment_id: string;
    title: string;
    status: string;
    attempts_total: number;
    students_started: number;
  }[];
  students: {
    student_id: string;
    attempts_total: number;
    attempts_submitted: number;
    attempts_reviewed: number;
    last_activity_at: string | null;
    confirmed_errors: Record<string, number>;
  }[];
  pending_reviews: number;
  open_interventions: number;
}

export const STEP_LABELS: Record<string, string> = {
  problem_presentation: "问题表征",
  differential_diagnosis: "鉴别诊断",
  key_evidence: "关键证据",
  investigation: "检查选择",
  disposition: "处置方案",
  reassessment: "再评估",
};

export const LEVELS = ["L1", "L2", "L3", "L4"] as const;

async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(apiUrl(path), init);
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { detail?: unknown } | null;
    const detail = body?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((d) => (typeof d === "object" && d && "msg" in d ? String((d as { msg: unknown }).msg) : String(d))).join("；")
          : `HTTP ${res.status}`;
    throw new Error(message);
  }
  return (await res.json()) as T;
}

function jsonInit(method: string, body: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

export const teachingApi = {
  // teaching organization
  listCourses: (tenantId = "default") =>
    getJson<Course[]>(`/api/v1/teaching/courses?tenant_id=${encodeURIComponent(tenantId)}`),
  createCourse: (code: string, title: string, description = "") =>
    getJson<Course>("/api/v1/teaching/courses", jsonInit("POST", { code, title, description })),
  listMyClasses: () => getJson<TeachingClass[]>("/api/v1/teaching/my/classes"),
  listClasses: (courseId: string) =>
    getJson<TeachingClass[]>(`/api/v1/teaching/courses/${courseId}/classes`),
  createClass: (courseId: string, name: string, semester = "") =>
    getJson<TeachingClass>(`/api/v1/teaching/courses/${courseId}/classes`, jsonInit("POST", { name, semester })),
  listMembers: (classId: string) =>
    getJson<Membership[]>(`/api/v1/teaching/classes/${classId}/members`),
  addMember: (classId: string, userId: string, role: string) =>
    getJson<Membership>(`/api/v1/teaching/classes/${classId}/members`, jsonInit("POST", { user_id: userId, role })),
  removeMember: (classId: string, userId: string) =>
    getJson<{ removed: string }>(`/api/v1/teaching/classes/${classId}/members/${userId}`, { method: "DELETE" }),
  listAssignments: (classId: string) =>
    getJson<Assignment[]>(`/api/v1/teaching/classes/${classId}/assignments`),

  // cases
  listCases: (level?: string, status?: string) => {
    const params = new URLSearchParams();
    if (level) params.set("level", level);
    if (status) params.set("case_status", status);
    return getJson<CaseSummary[]>(`/api/v1/clinical/cases?${params.toString()}`);
  },
  caseContent: (caseId: string) => getJson<CaseContent>(`/api/v1/clinical/cases/${caseId}/content`),
  submitForReview: (caseId: string) =>
    getJson<CaseSummary>(`/api/v1/clinical/cases/${caseId}/submit-review`, { method: "POST" }),
  reviewCase: (caseId: string, decision: string, comments = "") =>
    getJson<CaseSummary>(`/api/v1/clinical/cases/${caseId}/reviews`, jsonInit("POST", { decision, comments })),
  publishCase: (caseId: string) =>
    getJson<CaseSummary>(`/api/v1/clinical/cases/${caseId}/publish`, { method: "POST" }),

  // attempts
  listAttempts: (assignmentId: string) =>
    getJson<AttemptView[]>(`/api/v1/clinical/attempts?assignment_id=${encodeURIComponent(assignmentId)}`),
  createAttempt: (assignmentId: string) =>
    getJson<AttemptView>("/api/v1/clinical/attempts", jsonInit("POST", { assignment_id: assignmentId })),
  getAttempt: (attemptId: string) => getJson<AttemptView>(`/api/v1/clinical/attempts/${attemptId}`),
  listSteps: (attemptId: string) => getJson<ReasoningStep[]>(`/api/v1/clinical/attempts/${attemptId}/steps`),
  addStep: (attemptId: string, stepType: string, content: string) =>
    getJson<ReasoningStep>(`/api/v1/clinical/attempts/${attemptId}/steps`, jsonInit("POST", { step_type: stepType, content })),
  submitAttempt: (attemptId: string) =>
    getJson<AttemptView>(`/api/v1/clinical/attempts/${attemptId}/submit`, { method: "POST" }),

  // virtual patient
  latestSession: (attemptId: string) =>
    getJson<PatientSessionView>(`/api/v1/clinical/attempts/${attemptId}/patient-session`),
  createSession: (attemptId: string) =>
    getJson<PatientSessionView>("/api/v1/clinical/patient-sessions", jsonInit("POST", { attempt_id: attemptId })),
  performAction: (sessionId: string, actionType: string, payload: Record<string, string | number>) =>
    getJson<{ released: Record<string, unknown>; state: { phase: string; terminated: boolean } }>(
      `/api/v1/clinical/patient-sessions/${sessionId}/actions`,
      jsonInit("POST", { action_type: actionType, ...payload }),
    ),
  listEvents: (sessionId: string) => getJson<PatientEvent[]>(`/api/v1/clinical/patient-sessions/${sessionId}/events`),

  // assessment + teacher analytics
  runAssessment: (attemptId: string) =>
    getJson<AssessmentRun>(`/api/v1/clinical/attempts/${attemptId}/assess`, { method: "POST" }),
  reviewQueue: (classId: string) =>
    getJson<AssessmentScore[]>(`/api/v1/clinical/teacher/assessment-queue?class_id=${encodeURIComponent(classId)}`),
  reviewScore: (
    scoreId: string,
    action: string,
    finalErrorType: string | null,
    comment: string,
  ) =>
    getJson<Record<string, unknown>>(
      `/api/v1/clinical/assessment-scores/${scoreId}/review`,
      jsonInit("POST", { action, final_error_type: finalErrorType, comment }),
    ),
  dashboard: (classId: string) =>
    getJson<ClassOverview>(`/api/v1/clinical/teacher/classes/${classId}/dashboard`),
  riskFlags: (classId: string) =>
    getJson<RiskFlag[]>(`/api/v1/clinical/teacher/classes/${classId}/risk-flags`),
  recordIntervention: (classId: string, studentId: string, reason: string, note = "") =>
    getJson<Intervention>("/api/v1/clinical/teacher/interventions", jsonInit("POST", { class_id: classId, student_id: studentId, reason, note })),
  resolveIntervention: (interventionId: string, outcome = "") =>
    getJson<Intervention>(`/api/v1/clinical/teacher/interventions/${interventionId}/resolve`, jsonInit("POST", { outcome })),
  listInterventions: (classId: string) =>
    getJson<Intervention[]>(`/api/v1/clinical/teacher/classes/${classId}/interventions`),
};

export const ERROR_TYPE_LABELS: Record<string, string> = {
  symptom_attribution: "症状归因",
  differential_exclusion: "鉴别排除缺失",
  evidence_integration: "证据整合错误",
  decision_rationale: "决策依据缺失",
  logic_breakpoint: "逻辑断点",
  evidence_gap: "证据缺环",
  decision_bias: "决策偏差",
  ethical_blind_spot: "伦理盲区",
};
