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

      {overview && (
        <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Metric label="任务数" value={overview.assignments.length} />
          <Metric label="待复核评估" value={overview.pending_reviews} />
          <Metric label="未关闭干预" value={overview.open_interventions} />
          <Metric label="学员数" value={overview.students.length} />
        </section>
      )}

      {overview && (
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

      {flags.length > 0 && (
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

      {queue.length > 0 && (
        <section className="space-y-2 rounded border p-4">
          <h2 className="font-medium">评估复核队列（{queue.length}）</h2>
          {queue.map((s) => (
            <ReviewRow key={s.score_id} score={s} onDone={(msg) => run(() => Promise.resolve(), msg)} classId={classId} reload={reload} />
          ))}
        </section>
      )}

      {interventions.length > 0 && (
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
