"use client";

/**
 * Teacher dashboard (Sprint 4 minimal): class overview, deterministic risk
 * flags with one-click interventions, the pending assessment review queue
 * and the intervention follow-up list.
 */

import { useCallback, useEffect, useState } from "react";

import {
  AssessmentScore,
  ClassOverview,
  ERROR_TYPE_LABELS,
  GradebookData,
  Intervention,
  RiskFlag,
  TeachingClass,
  teachingApi,
} from "@/components/teaching/teaching-api";

const STAFF_ROLES = new Set(["course_admin", "teacher", "reviewer"]);

export default function TeacherDashboard() {
  const [classes, setClasses] = useState<TeachingClass[]>([]);
  const [classId, setClassId] = useState("");
  const [overview, setOverview] = useState<ClassOverview | null>(null);
  const [flags, setFlags] = useState<RiskFlag[]>([]);
  const [queue, setQueue] = useState<AssessmentScore[]>([]);
  const [interventions, setInterventions] = useState<Intervention[]>([]);
  const [gradebook, setGradebook] = useState<GradebookData | null>(null);
  const [tab, setTab] = useState<"overview" | "gradebook">("overview");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const list = await teachingApi.listMyClasses();
        if (!alive) return;
        setClasses(list);
        if (list.length > 0) setClassId(list[0].class_id);
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const reload = useCallback(async () => {
    if (!classId) return;
    try {
      const [ov, rf, q, iv] = await Promise.all([
        teachingApi.dashboard(classId),
        teachingApi.riskFlags(classId),
        teachingApi.reviewQueue(classId),
        teachingApi.listInterventions(classId),
      ]);
      setOverview(ov);
      setFlags(rf);
      setQueue(q);
      setInterventions(iv);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [classId]);

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const [ov, rf, q, iv] = await Promise.all([
          teachingApi.dashboard(classId),
          teachingApi.riskFlags(classId),
          teachingApi.reviewQueue(classId),
          teachingApi.listInterventions(classId),
        ]);
        if (!alive) return;
        setOverview(ov);
        setFlags(rf);
        setQueue(q);
        setInterventions(iv);
        setGradebook(await teachingApi.gradebook(classId).catch(() => null));
        setError("");
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      alive = false;
    };
  }, [classId]);

  const run = async (fn: () => Promise<unknown>, message: string) => {
    setError("");
    setNotice("");
    try {
      await fn();
      setNotice(message);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">教师看板</h1>
        <select className="rounded border p-2 text-sm" value={classId} onChange={(e) => setClassId(e.target.value)}>
          {classes.map((c) => (
            <option key={c.class_id} value={c.class_id}>
              {c.name}
            </option>
          ))}
        </select>
      </div>
      {error && <p className="rounded border border-red-300 bg-red-50 p-2 text-sm text-red-700">{error}</p>}
      {notice && <p className="rounded border border-blue-300 bg-blue-50 p-2 text-sm text-blue-800">{notice}</p>}
      {!classId && <p className="text-sm text-gray-500">尚未加入任何班级（作为教师/管理员）。</p>}

      {classId && (
        <div className="flex gap-2 text-sm">
          <button
            className={`rounded px-3 py-1.5 ${tab === "overview" ? "bg-blue-600 text-white" : "border"}`}
            onClick={() => setTab("overview")}
          >
            学情总览
          </button>
          <button
            className={`rounded px-3 py-1.5 ${tab === "gradebook" ? "bg-blue-600 text-white" : "border"}`}
            onClick={() => setTab("gradebook")}
          >
            成绩册
          </button>
        </div>
      )}

      {tab === "overview" && overview && (
        <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Metric label="任务数" value={overview.assignments.length} />
          <Metric label="待复核评估" value={overview.pending_reviews} />
          <Metric label="未关闭干预" value={overview.open_interventions} />
          <Metric label="学员数" value={overview.students.length} />
        </section>
      )}

      {tab === "overview" && overview && (
        <section className="rounded border p-4">
          <h2 className="mb-2 font-medium">作业完成度</h2>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-gray-500">
                <th className="py-1">任务</th>
                <th>状态</th>
                <th>累计尝试</th>
                <th>已开做学生</th>
              </tr>
            </thead>
            <tbody>
              {overview.assignments.map((a) => (
                <tr key={a.assignment_id} className="border-b">
                  <td className="py-1">{a.title}</td>
                  <td>{a.status}</td>
                  <td>{a.attempts_total}</td>
                  <td>{a.students_started}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {tab === "overview" && flags.length > 0 && (
        <section className="space-y-2 rounded border border-amber-300 bg-amber-50 p-4">
          <h2 className="font-medium">风险队列（{flags.length}）</h2>
          {flags.map((f) => (
            <div key={f.student_id} className="flex flex-wrap items-center justify-between gap-2 rounded bg-white p-2 text-sm">
              <div>
                <span className="font-medium">{f.student_id}</span>
                <span className="ml-2 text-xs text-gray-600">{f.reasons.join("；")}</span>
              </div>
              <button
                className="rounded border border-amber-500 px-2 py-1 text-xs"
                onClick={() =>
                  run(
                    () =>
                      teachingApi.recordIntervention(
                        classId,
                        f.student_id,
                        f.reasons[0] ?? "风险干预",
                        "自动来自风险队列",
                      ),
                    "已记录干预",
                  )
                }
              >
                记录干预
              </button>
            </div>
          ))}
        </section>
      )}

      {tab === "overview" && queue.length > 0 && (
        <section className="space-y-2 rounded border p-4">
          <h2 className="font-medium">评估复核队列（{queue.length}）</h2>
          {queue.map((s) => (
            <ReviewRow key={s.score_id} score={s} onDone={(msg) => run(() => Promise.resolve(), msg)} classId={classId} reload={reload} />
          ))}
        </section>
      )}

      {tab === "gradebook" && gradebook && (
        <GradebookSection gradebook={gradebook} classId={classId} onDone={(m) => run(() => Promise.resolve(), m)} reload={reload} />
      )}

      {tab === "overview" && interventions.length > 0 && (
        <section className="space-y-2 rounded border p-4">
          <h2 className="font-medium">干预记录</h2>
          {interventions.map((i) => (
            <div key={i.intervention_id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span>
                {i.student_id} · {i.reason} ·{" "}
                <span className={i.status === "open" ? "text-amber-600" : "text-green-600"}>
                  {i.status === "open" ? "未关闭" : `已解决：${i.outcome}`}
                </span>
              </span>
              {i.status === "open" && (
                <button
                  className="rounded border px-2 py-1 text-xs"
                  onClick={() =>
                    run(() => teachingApi.resolveIntervention(i.intervention_id, "已完成跟进"), "干预已关闭")
                  }
                >
                  标记解决
                </button>
              )}
            </div>
          ))}
        </section>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded border p-3 text-center">
      <div className="text-2xl font-semibold">{value}</div>
      <div className="text-xs text-gray-500">{label}</div>
    </div>
  );
}

function ReviewRow({
  score,
  classId,
  onDone,
  reload,
}: {
  score: AssessmentScore;
  classId: string;
  onDone: (msg: string) => void;
  reload: () => Promise<void>;
}) {
  const [overrideType, setOverrideType] = useState("");
  const label = score.error_type ? ERROR_TYPE_LABELS[score.error_type] ?? score.error_type : "（无标签）";
  const act = async (action: string) => {
    try {
      await teachingApi.reviewScore(score.score_id, action, action === "override" ? overrideType || null : null, "");
      onDone(`已${action === "agree" ? "确认" : action === "override" ? "改判" : "忽略"}`);
      await reload();
    } catch (e) {
      onDone(e instanceof Error ? e.message : String(e));
    }
  };
  return (
    <div className="space-y-1 rounded bg-gray-50 p-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{score.student_id ?? "学员"}</span>
        <span className="rounded bg-red-100 px-1.5 text-xs text-red-700">{label}</span>
        <span className="text-xs text-gray-500">置信度 {Math.round(score.confidence * 100)}%</span>
      </div>
      <p className="text-xs text-gray-700">建议：{score.suggestion}</p>
      <p className="text-xs text-gray-400">依据：{score.evidence}</p>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <button className="rounded border px-2 py-1" onClick={() => act("agree")}>
          确认
        </button>
        <select className="rounded border p-1" value={overrideType} onChange={(e) => setOverrideType(e.target.value)}>
          <option value="">改判为…</option>
          {Object.entries(ERROR_TYPE_LABELS).map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
        <button className="rounded border px-2 py-1" disabled={!overrideType} onClick={() => act("override")}>
          改判
        </button>
        <button className="rounded border px-2 py-1" onClick={() => act("dismiss")}>
          忽略
        </button>
      </div>
    </div>
  );
}


function GradebookSection({
  gradebook,
  classId,
  onDone,
  reload,
}: {
  gradebook: GradebookData;
  classId: string;
  onDone: (msg: string) => void;
  reload: () => Promise<void>;
}) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  const record = async (studentId: string, title: string, raw: string) => {
    if (!raw.trim()) return;
    try {
      await teachingApi.recordSummative(classId, studentId, title, Number(raw));
      onDone("成绩已记录");
      setDrafts((prev) => ({ ...prev, [`${studentId}:${title}`]: "" }));
      await reload();
    } catch (e) {
      onDone(e instanceof Error ? e.message : String(e));
    }
  };

  const exportCsv = async () => {
    try {
      const csv = await teachingApi.gradebookCsv(classId);
      const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `gradebook-${classId.slice(0, 8)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      onDone(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <section className="space-y-3 rounded border p-4">
      <div className="flex items-center justify-between">
        <h2 className="font-medium">成绩册</h2>
        <button className="rounded border px-2 py-1 text-xs" onClick={() => void exportCsv()}>
          导出 CSV
        </button>
      </div>
      <p className="text-xs text-gray-500">
        40/60 框架占位：过程性组件自动汇总，终结性成绩由教师录入；权重合成待决策冻结后启用。
      </p>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-gray-500">
            <th className="py-1">学员</th>
            <th>尝试/提交/复核</th>
            <th>标记正确</th>
            {gradebook.summative_titles.map((title) => (
              <th key={title}>{title}</th>
            ))}
            <th>录入终结性成绩</th>
          </tr>
        </thead>
        <tbody>
          {gradebook.students.map((s) => (
            <tr key={s.student_id} className="border-b align-top">
              <td className="py-2">{s.student_id}</td>
              <td className="text-xs">
                {s.formative.attempts_total} / {s.formative.attempts_submitted} /{" "}
                {s.formative.attempts_reviewed}
              </td>
              <td className="text-xs">
                {s.formative.marked_correct}/{s.formative.marked_total}
              </td>
              {gradebook.summative_titles.map((title) => (
                <td key={title} className="text-xs">
                  {s.summative[title] ?? "—"}
                </td>
              ))}
              <td>
                <div className="flex gap-1">
                  <input
                    className="w-16 rounded border p-1 text-xs"
                    placeholder="0-100"
                    value={drafts[`${s.student_id}:__new`] ?? ""}
                    onChange={(e) =>
                      setDrafts((prev) => ({ ...prev, [`${s.student_id}:__new`]: e.target.value }))
                    }
                  />
                  <button
                    className="rounded border px-2 py-1 text-xs"
                    disabled={!drafts[`${s.student_id}:__new`]?.trim()}
                    onClick={() => {
                      const title =
                        drafts[`${s.student_id}:__title`] ||
                        gradebook.summative_titles[gradebook.summative_titles.length - 1] ||
                        "终结性评价";
                      void record(s.student_id, title, drafts[`${s.student_id}:__new`] ?? "");
                    }}
                  >
                    记录
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
