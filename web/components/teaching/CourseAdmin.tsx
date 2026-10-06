"use client";

/**
 * Course administration (Sprint 0 acceptance): courses, classes and
 * memberships on the central teaching database.
 */

import { useCallback, useEffect, useState } from "react";

import {
  Course,
  Membership,
  TeachingClass,
  teachingApi,
} from "@/components/teaching/teaching-api";

const ROLES = ["course_admin", "teacher", "reviewer", "student"] as const;
const ROLE_LABELS: Record<string, string> = {
  course_admin: "课程管理员",
  teacher: "教师",
  reviewer: "复核员",
  student: "学员",
};

export default function CourseAdmin() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [classes, setClasses] = useState<Record<string, TeachingClass[]>>({});
  const [members, setMembers] = useState<Record<string, Membership[]>>({});
  const [error, setError] = useState("");
  const [newCourse, setNewCourse] = useState({ code: "", title: "" });
  const [newClass, setNewClass] = useState<Record<string, string>>({});
  const [newMember, setNewMember] = useState<Record<string, { user: string; role: string }>>({});

  const loadAll = useCallback(async () => {
    const list = await teachingApi.listCourses();
    const classMap: Record<string, TeachingClass[]> = {};
    const memberMap: Record<string, Membership[]> = {};
    for (const course of list) {
      const courseClasses = await teachingApi.listClasses(course.course_id);
      classMap[course.course_id] = courseClasses;
      for (const cls of courseClasses) {
        memberMap[cls.class_id] = await teachingApi.listMembers(cls.class_id).catch(() => []);
      }
    }
    return { list, classMap, memberMap };
  }, []);

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const { list, classMap, memberMap } = await loadAll();
        if (!alive) return;
        setCourses(list);
        setClasses(classMap);
        setMembers(memberMap);
        setError("");
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      alive = false;
    };
  }, [loadAll]);

  const reload = () => {
    void (async () => {
      try {
        const { list, classMap, memberMap } = await loadAll();
        setCourses(list);
        setClasses(classMap);
        setMembers(memberMap);
        setError("");
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
  };

  const action = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6">
      <h1 className="text-xl font-semibold">课程管理</h1>
      {error && <p className="rounded border border-red-300 bg-red-50 p-2 text-sm text-red-700">{error}</p>}

      <section className="space-y-2 rounded border p-4">
        <h2 className="font-medium">新建课程</h2>
        <div className="flex gap-2">
          <input
            className="w-32 rounded border p-2 text-sm"
            placeholder="课程代码"
            value={newCourse.code}
            onChange={(e) => setNewCourse({ ...newCourse, code: e.target.value })}
          />
          <input
            className="flex-1 rounded border p-2 text-sm"
            placeholder="课程名称"
            value={newCourse.title}
            onChange={(e) => setNewCourse({ ...newCourse, title: e.target.value })}
          />
          <button
            className="rounded bg-blue-600 px-3 py-2 text-sm text-white disabled:opacity-50"
            disabled={!newCourse.code || !newCourse.title}
            onClick={() =>
              action(async () => {
                await teachingApi.createCourse(newCourse.code, newCourse.title);
                setNewCourse({ code: "", title: "" });
              })
            }
          >
            创建
          </button>
        </div>
      </section>

      {courses.map((course) => (
        <section key={course.course_id} className="space-y-3 rounded border p-4">
          <div>
            <h2 className="font-medium">
              {course.title} <span className="text-sm text-gray-500">({course.code})</span>
            </h2>
            <p className="text-xs text-gray-500">状态：{course.status}</p>
          </div>

          <div className="space-y-2">
            {(classes[course.course_id] ?? []).map((cls) => (
              <div key={cls.class_id} className="rounded bg-gray-50 p-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium">{cls.name}</span>
                  <span className="text-xs text-gray-500">{cls.semester}</span>
                </div>
                <ul className="mt-2 space-y-1">
                  {(members[cls.class_id] ?? []).map((m) => (
                    <li key={m.membership_id} className="flex items-center justify-between text-xs">
                      <span>
                        {m.user_id} · {ROLE_LABELS[m.role] ?? m.role}
                      </span>
                      <button
                        className="text-red-600 hover:underline"
                        onClick={() => action(() => teachingApi.removeMember(cls.class_id, m.user_id))}
                      >
                        移除
                      </button>
                    </li>
                  ))}
                  {(members[cls.class_id] ?? []).length === 0 && (
                    <li className="text-xs text-gray-400">暂无成员</li>
                  )}
                </ul>
                <div className="mt-2 flex gap-2">
                  <input
                    className="w-32 rounded border p-1 text-xs"
                    placeholder="用户 ID"
                    value={newMember[cls.class_id]?.user ?? ""}
                    onChange={(e) =>
                      setNewMember({
                        ...newMember,
                        [cls.class_id]: { user: e.target.value, role: newMember[cls.class_id]?.role ?? "student" },
                      })
                    }
                  />
                  <select
                    className="rounded border p-1 text-xs"
                    value={newMember[cls.class_id]?.role ?? "student"}
                    onChange={(e) =>
                      setNewMember({
                        ...newMember,
                        [cls.class_id]: { user: newMember[cls.class_id]?.user ?? "", role: e.target.value },
                      })
                    }
                  >
                    {ROLES.map((r) => (
                      <option key={r} value={r}>
                        {ROLE_LABELS[r]}
                      </option>
                    ))}
                  </select>
                  <button
                    className="rounded border px-2 py-1 text-xs"
                    disabled={!newMember[cls.class_id]?.user}
                    onClick={() =>
                      action(() =>
                        teachingApi.addMember(
                          cls.class_id,
                          newMember[cls.class_id].user,
                          newMember[cls.class_id].role,
                        ),
                      )
                    }
                  >
                    添加成员
                  </button>
                </div>
              </div>
            ))}
            <div className="flex gap-2">
              <input
                className="flex-1 rounded border p-1 text-xs"
                placeholder="班级名称，如 2026级五年制1班"
                value={newClass[course.course_id] ?? ""}
                onChange={(e) => setNewClass({ ...newClass, [course.course_id]: e.target.value })}
              />
              <button
                className="rounded border px-2 py-1 text-xs"
                disabled={!newClass[course.course_id]}
                onClick={() =>
                  action(async () => {
                    await teachingApi.createClass(course.course_id, newClass[course.course_id]);
                    setNewClass({ ...newClass, [course.course_id]: "" });
                  })
                }
              >
                新建班级
              </button>
            </div>
          </div>
        </section>
      ))}
    </div>
  );
}
