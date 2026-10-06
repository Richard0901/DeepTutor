"use client";

/**
 * Case library: level/status filters plus the review-publication lifecycle
 * actions (draft -> under_review -> approved x2 -> published).
 */

import { useCallback, useEffect, useState } from "react";

import { CaseSummary, LEVELS, teachingApi } from "@/components/teaching/teaching-api";

const STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  under_review: "待审",
  approved: "已通过",
  published: "已发布",
  retired: "已下架",
};

export default function CaseLibrary() {
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [level, setLevel] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");

  const fetchCases = useCallback(
    async (lvl: string, st: string) => teachingApi.listCases(lvl || undefined, st || undefined),
    [],
  );

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const data = await fetchCases(level, status);
        if (alive) {
          setCases(data);
          setError("");
        }
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      alive = false;
    };
  }, [fetchCases, level, status]);

  const reload = () => {
    void (async () => {
      try {
        setCases(await fetchCases(level, status));
        setError("");
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
  };

  const act = async (fn: () => Promise<unknown>, done: () => void) => {
    try {
      await fn();
      done();
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-6">
      <h1 className="text-xl font-semibold">分级病例库</h1>
      {error && <p className="rounded border border-red-300 bg-red-50 p-2 text-sm text-red-700">{error}</p>}

      <div className="flex gap-3 text-sm">
        <select className="rounded border p-2" value={level} onChange={(e) => setLevel(e.target.value)}>
          <option value="">全部层级</option>
          {LEVELS.map((l) => (
            <option key={l} value={l}>
              {l}
            </option>
          ))}
        </select>
        <select className="rounded border p-2" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">全部状态</option>
          {Object.entries(STATUS_LABELS).map(([v, label]) => (
            <option key={v} value={v}>
              {label}
            </option>
          ))}
        </select>
      </div>

      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-gray-500">
            <th className="py-2">编号</th>
            <th>标题</th>
            <th>层级</th>
            <th>四维评分（复杂/诊断/决策/情境）</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {cases.map((c) => (
            <tr key={c.case_id} className="border-b align-top">
              <td className="py-2 font-mono text-xs">{c.case_code}</td>
              <td>{c.title}</td>
              <td>{c.level}</td>
              <td className="text-xs text-gray-600">
                {c.dimension_complexity} / {c.dimension_diagnostic} / {c.dimension_decision} /{" "}
                {c.dimension_situational}
              </td>
              <td>{STATUS_LABELS[c.status] ?? c.status}</td>
              <td className="space-x-2 py-2">
                {c.status === "draft" && (
                  <button
                    className="rounded border px-2 py-1 text-xs"
                    onClick={() => act(() => teachingApi.submitForReview(c.case_id), () => undefined)}
                  >
                    送审
                  </button>
                )}
                {c.status === "under_review" && (
                  <>
                    <button
                      className="rounded bg-green-600 px-2 py-1 text-xs text-white"
                      onClick={() => act(() => teachingApi.reviewCase(c.case_id, "approve"), () => undefined)}
                    >
                      通过
                    </button>
                    <button
                      className="rounded border px-2 py-1 text-xs"
                      onClick={() =>
                        act(
                          () => teachingApi.reviewCase(c.case_id, "reject", "驳回修改"),
                          () => undefined,
                        )
                      }
                    >
                      驳回
                    </button>
                  </>
                )}
                {c.status === "approved" && (
                  <button
                    className="rounded bg-blue-600 px-2 py-1 text-xs text-white"
                    onClick={() => act(() => teachingApi.publishCase(c.case_id), () => undefined)}
                  >
                    发布
                  </button>
                )}
              </td>
            </tr>
          ))}
          {cases.length === 0 && (
            <tr>
              <td colSpan={6} className="py-4 text-center text-gray-400">
                暂无病例
              </td>
            </tr>
          )}
        </tbody>
      </table>
      <p className="text-xs text-gray-500">
        发布需两名不同审核人通过（双审）；未发布病例不会进入学员训练。
      </p>
    </div>
  );
}
