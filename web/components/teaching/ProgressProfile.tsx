"use client";

/**
 * Student progress profile (Sprint 5): L1-L4 attempt distribution,
 * teacher-confirmed error trends and triggered compensations.  Aggregates
 * teaching-domain records only (Mastery Path data is a different scope).
 */

import { useEffect, useState } from "react";

import {
  ERROR_TYPE_LABELS,
  LEVELS,
  ProgressProfile,
  teachingApi,
} from "@/components/teaching/teaching-api";

export default function ProgressProfilePage() {
  const [profile, setProfile] = useState<ProgressProfile | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const data = await teachingApi.myProgress();
        if (alive) setProfile(data);
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <h1 className="text-xl font-semibold">我的训练画像</h1>
      {error && <p className="rounded border border-red-300 bg-red-50 p-2 text-sm text-red-700">{error}</p>}
      {!profile && !error && <p className="text-sm text-gray-500">加载中…</p>}

      {profile && (
        <>
          <section className="rounded border p-4">
            <h2 className="mb-3 font-medium">L1-L4 尝试分布</h2>
            <div className="space-y-2">
              {LEVELS.map((level) => {
                const d = profile.level_distribution[level] ?? {
                  attempts: 0,
                  submitted: 0,
                  reviewed: 0,
                };
                const max = Math.max(
                  1,
                  ...Object.values(profile.level_distribution).map((x) => x.attempts),
                );
                return (
                  <div key={level} className="flex items-center gap-3 text-sm">
                    <span className="w-8 font-medium">{level}</span>
                    <div className="h-4 flex-1 rounded bg-gray-100">
                      <div
                        className="h-4 rounded bg-blue-500"
                        style={{ width: `${(d.attempts / max) * 100}%` }}
                      />
                    </div>
                    <span className="w-40 text-xs text-gray-600">
                      尝试 {d.attempts} · 提交 {d.submitted} · 已复核 {d.reviewed}
                    </span>
                  </div>
                );
              })}
            </div>
          </section>

          <section className="rounded border p-4">
            <h2 className="mb-3 font-medium">教师确认的错误类型</h2>
            {Object.keys(profile.error_trends).length === 0 ? (
              <p className="text-sm text-gray-500">暂无确认的错误记录。</p>
            ) : (
              <div className="space-y-2">
                {Object.entries(profile.error_trends).map(([type, trend]) => (
                  <div key={type} className="flex items-center gap-3 text-sm">
                    <span className="w-28">{ERROR_TYPE_LABELS[type] ?? type}</span>
                    <div className="h-4 flex-1 rounded bg-gray-100">
                      <div
                        className="h-4 rounded bg-red-400"
                        style={{
                          width: `${Math.min(100, (trend.total / Math.max(1, ...Object.values(profile.error_trends).map((x) => x.total))) * 100)}%`,
                        }}
                      />
                    </div>
                    <span className="w-32 text-xs text-gray-600">
                      累计 {trend.total} · 近30天 {trend.last_30d}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="rounded border p-4">
            <h2 className="mb-2 font-medium">系统性补偿训练</h2>
            {profile.compensation_triggered.length === 0 ? (
              <p className="text-sm text-gray-500">
                未触发补偿（同一错误类型 {profile.compensation_window_days} 天内达{" "}
                {profile.compensation_threshold} 次触发）。
              </p>
            ) : (
              <div className="space-y-1 text-sm">
                <p className="text-red-700">以下错误类型已触发补偿训练：</p>
                {profile.compensation_triggered.map((type) => (
                  <p key={type} className="rounded bg-red-50 px-2 py-1">
                    {ERROR_TYPE_LABELS[type] ?? type}
                  </p>
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
