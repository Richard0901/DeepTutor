"use client";

/**
 * Student training workspace (Sprint 2/3): case briefing, the six-step
 * structured reasoning form, the deterministic virtual patient consultation
 * and submission with its gates (five required steps + completed
 * consultation for scripted cases).
 */

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import {
  AttemptView,
  CaseContent,
  PatientEvent,
  PatientSessionView,
  ReasoningStep,
  STEP_LABELS,
  teachingApi,
  VITAL_LABELS,
  VITAL_ORDER,
} from "@/components/teaching/teaching-api";

const STEP_ORDER = [
  "problem_presentation",
  "differential_diagnosis",
  "key_evidence",
  "investigation",
  "disposition",
  "reassessment",
] as const;

const PHASE_LABELS: Record<string, string> = {
  initial: "接诊",
  history_taking: "问诊",
  examination: "检查",
  disposition: "处置",
  terminated: "已结束",
};

export default function AttemptWorkspace() {
  const params = useParams<{ attemptId: string }>();
  const attemptId = params.attemptId;

  const [attempt, setAttempt] = useState<AttemptView | null>(null);
  const [content, setContent] = useState<CaseContent | null>(null);
  const [steps, setSteps] = useState<ReasoningStep[]>([]);
  const [session, setSession] = useState<PatientSessionView | null>(null);
  const [events, setEvents] = useState<PatientEvent[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [question, setQuestion] = useState("");
  const [examName, setExamName] = useState("");
  const [disposition, setDisposition] = useState("");
  const [waitMinutes, setWaitMinutes] = useState(10);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const script = content?.patient_script ?? null;
  const inProgress = attempt?.status === "in_progress";

  const reloadCore = useCallback(async () => {
    try {
      const view = await teachingApi.getAttempt(attemptId);
      setAttempt(view);
      const [caseContent, stepList] = await Promise.all([
        teachingApi.caseContent(view.case_id),
        teachingApi.listSteps(attemptId),
      ]);
      setContent(caseContent);
      setSteps(stepList);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [attemptId]);

  const reloadSession = useCallback(async () => {
    try {
      const s = await teachingApi.latestSession(attemptId);
      setSession(s);
      setEvents(await teachingApi.listEvents(s.session_id));
    } catch {
      setSession(null);
      setEvents([]);
    }
  }, [attemptId]);

  useEffect(() => {
    void reloadCore();
    void reloadSession();
  }, [reloadCore, reloadSession]);

  const run = async (fn: () => Promise<unknown>, successNotice = "") => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await fn();
      if (successNotice) setNotice(successNotice);
      await Promise.all([reloadCore(), reloadSession()]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const addStep = (stepType: string) =>
    run(async () => {
      const value = (drafts[stepType] ?? "").trim();
      if (!value) throw new Error("内容不能为空");
      await teachingApi.addStep(attemptId, stepType, value);
      setDrafts({ ...drafts, [stepType]: "" });
    });

  const submit = () => run(() => teachingApi.submitAttempt(attemptId), "已提交，等待教师复核");

  const patientAction = (actionType: string, payload: Record<string, string | number> = {}) =>
    run(async () => {
      if (!session) throw new Error("会话不存在");
      const result = await teachingApi.performAction(session.session_id, actionType, payload);
      const reply = result.released["reply"] ?? result.released["result"] ?? result.released["feedback"];
      if (typeof reply === "string" && reply) setNotice(reply);
    });

  const examOptions = script?.exam_results ?? [];
  const dispositionOptions = script?.disposition_options ?? [];
  const existingTypes = new Set(steps.map((s) => s.step_type));

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6">
      {attempt && (
        <header className="space-y-1">
          <h1 className="text-xl font-semibold">
            {attempt.case_title}{" "}
            <span className="text-sm font-normal text-gray-500">({attempt.case_level})</span>
          </h1>
          <p className="text-sm text-gray-600">
            任务：{attempt.assignment_title} · 状态：
            {attempt.status === "in_progress"
              ? "训练中"
              : attempt.status === "submitted"
                ? "已提交待复核"
                : "已复核"}
          </p>
        </header>
      )}
      {error && <p className="rounded border border-red-300 bg-red-50 p-2 text-sm text-red-700">{error}</p>}
      {notice && <p className="rounded border border-blue-300 bg-blue-50 p-2 text-sm text-blue-800">{notice}</p>}

      {content && (
        <section className="space-y-2 rounded border p-4 text-sm">
          <h2 className="font-medium">病例摘要</h2>
          <p>
            <span className="text-gray-500">主诉：</span>
            {content.chief_complaint}
          </p>
          <p>
            <span className="text-gray-500">现病史：</span>
            {content.present_illness}
          </p>
          <p>
            <span className="text-gray-500">既往史：</span>
            {content.past_history}
          </p>
          <p>
            <span className="text-gray-500">查体：</span>
            {content.physical_examination}
          </p>
          {script && (script.exam_results?.length ?? 0) > 0 && (
            <p className="text-xs text-gray-500">
              可开具检查：{script.exam_results?.map((e) => e.exam_name).join("、")}
            </p>
          )}
        </section>
      )}

      {script && (
        <section className="space-y-3 rounded border p-4">
          <div className="flex items-center justify-between">
            <h2 className="font-medium">虚拟患者问诊</h2>
            <span className="text-sm text-gray-500">
              {session ? PHASE_LABELS[session.phase] ?? session.phase : "未开始"}
            </span>
          </div>

          {!session && (
            <button
              className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white disabled:opacity-50"
              disabled={!inProgress || busy}
              onClick={() => run(() => teachingApi.createSession(attemptId), "问诊已开始")}
            >
              开始接诊
            </button>
          )}

          {session?.rescue && (
            <RescueBar rescue={session.rescue} terminated={session.status === "terminated"} />
          )}

          {session && (
            <div className="space-y-3">
              {session.phase !== "terminated" && (
                <div className="flex flex-wrap gap-2">
                  {session.phase === "initial" && (
                    <button
                      className="rounded border px-3 py-1.5 text-sm"
                      disabled={busy}
                      onClick={() => patientAction("begin")}
                    >
                      开始问诊
                    </button>
                  )}
                  {session.phase !== "initial" && (
                    <>
                      <input
                        className="flex-1 rounded border p-2 text-sm"
                        placeholder="向患者提问，如：你哪里不舒服？以前有什么病史吗？"
                        value={question}
                        onChange={(e) => setQuestion(e.target.value)}
                      />
                      <button
                        className="rounded border px-3 py-1.5 text-sm"
                        disabled={busy || !question.trim()}
                        onClick={() =>
                          patientAction("ask_question", { text: question }).then(() => setQuestion(""))
                        }
                      >
                        提问
                      </button>
                    </>
                  )}
                  {session.phase === "examination" && (
                    <>
                      <select
                        className="rounded border p-2 text-sm"
                        value={examName}
                        onChange={(e) => setExamName(e.target.value)}
                      >
                        <option value="">选择检查…</option>
                        {examOptions.map((e) => (
                          <option key={e.exam_name} value={e.exam_name}>
                            {e.exam_name}
                          </option>
                        ))}
                      </select>
                      <button
                        className="rounded border px-3 py-1.5 text-sm"
                        disabled={busy || !examName}
                        onClick={() => patientAction("order_exam", { exam_name: examName })}
                      >
                        开检查
                      </button>
                    </>
                  )}
                  {session.phase === "disposition" && (
                    <select
                      className="rounded border p-2 text-sm"
                      value={disposition}
                      onChange={(e) => setDisposition(e.target.value)}
                    >
                      <option value="">选择处置方案…</option>
                      {dispositionOptions.map((d) => (
                        <option key={d.name} value={d.name}>
                          {d.name}
                        </option>
                      ))}
                    </select>
                  )}
                  {(session.phase === "history_taking" || session.phase === "examination") && (
                    <button
                      className="rounded border px-3 py-1.5 text-sm"
                      disabled={busy}
                      onClick={() => patientAction("advance_phase")}
                    >
                      进入下一阶段
                    </button>
                  )}
                  {session.rescue && session.phase !== "initial" && (
                    <>
                      <select
                        className="rounded border p-2 text-sm"
                        value={waitMinutes}
                        onChange={(e) => setWaitMinutes(Number(e.target.value))}
                      >
                        {[5, 10, 15, 20].map((m) => (
                          <option key={m} value={m}>
                            观察 {m} 分钟
                          </option>
                        ))}
                      </select>
                      <button
                        className="rounded border px-3 py-1.5 text-sm"
                        disabled={busy}
                        onClick={() => patientAction("wait", { minutes: waitMinutes })}
                      >
                        等待
                      </button>
                      <button
                        className="rounded border px-3 py-1.5 text-sm"
                        disabled={busy}
                        onClick={() => patientAction("reassess")}
                      >
                        再评估
                      </button>
                    </>
                  )}
                  {session.phase === "disposition" && (
                    <button
                      className="rounded bg-green-600 px-3 py-1.5 text-sm text-white"
                      disabled={busy || !disposition}
                      onClick={() => patientAction("submit_disposition", { option: disposition })}
                    >
                      提交处置
                    </button>
                  )}
                </div>
              )}

              {session.outcome && (
                <p className="rounded bg-gray-50 p-2 text-sm">
                  处置结果：
                  {String((session.outcome as { disposition_correct?: boolean }).disposition_correct)
                    ? "✅ 正确"
                    : "❌ 不正确"}
                </p>
              )}

              {session.rescue && session.outcome && (
                <RescueOutcome rescue={session.rescue} outcome={session.outcome} />
              )}

              {events.length > 0 && (
                <details className="text-sm">
                  <summary className="cursor-pointer text-gray-600">
                    问诊记录回放（{events.length} 条）
                  </summary>
                  <ol className="mt-2 space-y-1 border-l pl-3 text-xs text-gray-700">
                    {events.map((e, i) => (
                      <li key={i}>
                        <span className="font-mono text-gray-400">
                          {PHASE_LABELS[e.phase_after] ?? e.phase_after}
                        </span>{" "}
                        {String(e.released["reply"] ?? e.released["result"] ?? e.released["feedback"] ?? "")}
                      </li>
                    ))}
                  </ol>
                </details>
              )}
            </div>
          )}
        </section>
      )}

      <section className="space-y-4">
        <h2 className="font-medium">结构化推理（分步填写）</h2>
        {STEP_ORDER.map((stepType) => (
          <div key={stepType} className="rounded border p-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium">
                {STEP_LABELS[stepType]}
                {stepType !== "reassessment" && (
                  <span className="ml-1 text-xs text-red-500">必填</span>
                )}
              </h3>
            </div>
            <ul className="mt-2 space-y-1">
              {steps
                .filter((s) => s.step_type === stepType)
                .map((s) => (
                  <li key={s.step_id} className="rounded bg-gray-50 p-2 text-sm whitespace-pre-wrap">
                    {s.content}
                  </li>
                ))}
            </ul>
            {inProgress && (
              <div className="mt-2 flex gap-2">
                <textarea
                  className="flex-1 rounded border p-2 text-sm"
                  rows={2}
                  placeholder={`填写${STEP_LABELS[stepType]}…`}
                  value={drafts[stepType] ?? ""}
                  onChange={(e) => setDrafts({ ...drafts, [stepType]: e.target.value })}
                />
                <button
                  className="self-start rounded border px-2 py-1 text-xs"
                  disabled={busy || !(drafts[stepType] ?? "").trim()}
                  onClick={() => addStep(stepType)}
                >
                  添加
                </button>
              </div>
            )}
          </div>
        ))}
      </section>

      <div className="flex items-center gap-3">
        <button
          className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          disabled={!inProgress || busy}
          onClick={submit}
        >
          提交训练
        </button>
        <span className="text-xs text-gray-500">
          提交前需完成 5 个必填步骤{script ? "，并完成虚拟患者问诊" : ""}；提交后不可再修改。
        </span>
      </div>

      {attempt?.status === "reviewed" && (
        <p className="rounded border border-green-300 bg-green-50 p-2 text-sm text-green-800">
          教师复核意见：{attempt.review_notes || "（无）"}
        </p>
      )}
    </div>
  );
}


function RescueBar({
  rescue,
  terminated,
}: {
  rescue: NonNullable<PatientSessionView["rescue"]>;
  terminated: boolean;
}) {
  const overtime = rescue.time_remaining_minutes < 0;
  const lateForEvac = !terminated && rescue.elapsed_minutes > rescue.evac_eta_minutes;
  return (
    <div className="space-y-2 rounded bg-gray-50 p-3">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className={overtime ? "font-medium text-red-600" : "font-medium"}>
          用时 {rescue.elapsed_minutes}/{rescue.time_budget_minutes} 分钟
        </span>
        <span className="text-gray-500">后送窗口 {rescue.evac_eta_minutes} 分钟</span>
        {lateForEvac && <span className="rounded bg-red-100 px-2 text-xs text-red-700">已过后送窗口</span>}
      </div>
      <div className="flex flex-wrap gap-2 text-xs">
        {VITAL_ORDER.filter((k) => k in rescue.vitals).map((k) => (
          <span key={k} className="rounded border bg-white px-2 py-1">
            {VITAL_LABELS[k] ?? k}: <span className="font-medium">{rescue.vitals[k]}</span>
          </span>
        ))}
        {Object.keys(rescue.vitals)
          .filter((k) => !VITAL_ORDER.includes(k))
          .map((k) => (
            <span key={k} className="rounded border bg-white px-2 py-1">
              {k}: <span className="font-medium">{rescue.vitals[k]}</span>
            </span>
          ))}
      </div>
      {rescue.symptoms.length > 0 && (
        <div className="flex flex-wrap gap-1 text-xs">
          {rescue.symptoms.map((s) => (
            <span key={s} className="rounded bg-red-100 px-2 py-0.5 text-red-700">
              {s}
            </span>
          ))}
        </div>
      )}
      {Object.keys(rescue.resources_used).length > 0 && (
        <p className="text-xs text-gray-500">
          资源消耗：
          {Object.entries(rescue.resources_used)
            .map(([k, v]) => `${k} ×${v}`)
            .join("，")}
        </p>
      )}
    </div>
  );
}

function RescueOutcome({
  rescue,
  outcome,
}: {
  rescue: NonNullable<PatientSessionView["rescue"]>;
  outcome: Record<string, unknown>;
}) {
  const ro = outcome["rescue_outcome"] as
    | {
        evac_in_time?: boolean;
        elapsed_minutes?: number;
        time_remaining_minutes?: number;
        final_vitals?: Record<string, number>;
      }
    | undefined;
  if (!ro) return null;
  return (
    <div className="rounded border border-blue-200 bg-blue-50 p-3 text-sm">
      <p className="font-medium">战救结局评估</p>
      <ul className="mt-1 space-y-0.5 text-xs">
        <li>
          后送时机：
          {ro.evac_in_time ? "✅ 在后送窗口内完成处置" : "❌ 错过后送窗口"}
        </li>
        <li>
          用时：{ro.elapsed_minutes} 分钟（剩余 {ro.time_remaining_minutes} 分钟）
        </li>
        {ro.final_vitals && (
          <li>
            最终体征：
            {VITAL_ORDER.filter((k) => k in ro.final_vitals!)
              .map((k) => `${VITAL_LABELS[k] ?? k} ${ro.final_vitals![k]}`)
              .join("，")}
          </li>
        )}
      </ul>
    </div>
  );
}
