"use client";

/**
 * Student home: my classes -> assignments -> my attempts, with one-click
 * entry into the training workspace.
 */

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import {
  Assignment,
  AttemptView,
  TeachingClass,
  teachingApi,
} from "@/components/teaching/teaching-api";

const STATUS_LABELS: Record<string, string> = {
  in_progress: "进行中",
  submitted: "已提交待复核",
  reviewed: "已复核",
  open: "进行中",
  closed: "已结束",
  draft: "未发布",
};

export default function StudentHome() {
  const router = useRouter();
  const [classes, setClasses] = useState<TeachingClass[]>([]);
  const [selectedClass, setSelectedClass] = useState("");
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [attempts, setAttempts] = useState<Record<string, AttemptView[]>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const list = await teachingApi.listMyClasses();
        if (!alive) return;
        setClasses(list);
        if (list.length > 0) setSelectedClass(list[0].class_id);
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const reload = useCallback(async () => {
    if (!selectedClass) return;
    try {
      const list = await teachingApi.listAssignments(selectedClass);
      setAssignments(list);
      const map: Record<string, AttemptView[]> = {};
      for (const a of list) {
        map[a.assignment_id] = await teachingApi
          .listAttempts(a.assignment_id)
          .catch(() => []);
      }
      setAttempts(map);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [selectedClass]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const startOrOpen = async (assignment: Assignment) => {
    setBusy(true);
    try {
      const existing = attempts[assignment.assignment_id] ?? [];
      const open = existing.find((a) => a.status === "in_progress");
      const attempt = open ?? (await teachingApi.createAttempt(assignment.assignment_id));
      router.push(`/learn/attempts/${attempt.attempt_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-5 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">我的训练任务</h1>
        <a className="text-sm text-blue-600 hover:underline" href="/learn/progress">
          我的训练画像 →
        </a>
      </div>
      {error && <p className="rounded border border-red-300 bg-red-50 p-2 text-sm text-red-700">{error}</p>}

      {classes.length === 0 ? (
        <p className="text-sm text-gray-500">
          尚未加入任何班级。请先由教师在「课程管理」中将你加入班级。
        </p>
      ) : (
        <div className="flex items-center gap-2 text-sm">
          <span>班级：</span>
          <select
            className="rounded border p-2"
            value={selectedClass}
            onChange={(e) => setSelectedClass(e.target.value)}
          >
            {classes.map((c) => (
              <option key={c.class_id} value={c.class_id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
      )}

      {assignments.map((a) => (
        <section key={a.assignment_id} className="space-y-2 rounded border p-4">
          <div className="flex items-center justify-between">
            <h2 className="font-medium">{a.title}</h2>
            <span className="text-xs text-gray-500">{STATUS_LABELS[a.status] ?? a.status}</span>
          </div>
          {a.description && <p className="text-sm text-gray-600">{a.description}</p>}
          <ul className="space-y-1">
            {(attempts[a.assignment_id] ?? []).map((t) => (
              <li key={t.attempt_id} className="flex items-center justify-between text-xs">
                <span>
                  尝试 · {STATUS_LABELS[t.status] ?? t.status} ·{" "}
                  {new Date(t.started_at).toLocaleString("zh-CN")}
                </span>
                <a className="text-blue-600 hover:underline" href={`/learn/attempts/${t.attempt_id}`}>
                  打开
                </a>
              </li>
            ))}
            {(attempts[a.assignment_id] ?? []).length === 0 && (
              <li className="text-xs text-gray-400">尚无训练记录</li>
            )}
          </ul>
          <button
            className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white disabled:opacity-50"
            disabled={busy || a.status !== "open"}
            onClick={() => startOrOpen(a)}
          >
            {a.status === "open" ? "开始训练 / 继续" : "任务未开放"}
          </button>
        </section>
      ))}
      {selectedClass && assignments.length === 0 && (
        <p className="text-sm text-gray-500">该班级暂无任务。</p>
      )}
    </div>
  );
}
