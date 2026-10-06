# 变更与工作日志

> 按日期倒序记录。每条注明涉及的工作包（WP）与证据位置。已完成事项必须有对应 commit 或文档；未完成事项如实标注。

## 2026-10-06 — Sprint 0 + Sprint 2 后端首版（WP2/WP3 部分）

**提交内容**（本次 commit）：

1. **教学领域数据库骨架（WP2 首版）** — `deeptutor/teaching/`
   - `database.py`：中央教学库连接（WAL + 外键）与版本化 migration runner（up/down/idempotent，`DEEPTUTOR_TEACHING_DB` 可覆盖路径）；默认库 `data/system/clinical_learning.db`
   - `migrations.py`：0001 教学组织（tenants/courses/course_versions/teaching_classes/class_memberships）+ 0002 病例内容（clinical_cases/case_versions/case_dimensions/case_knowledge_points/case_review_records/assignments），含回滚脚本
   - `service.py`：课程/班级/成员/作业业务逻辑，课程内角色（course_admin/teacher/reviewer/student）与权限校验；硬约束"作业只能引用已发布病例"在服务层强制
2. **病例框架（WP3 首版）** — `deeptutor/clinical/`
   - 版本不可变 + 双审发布状态机：draft → under_review → (2 个不同审核人 approve) → approved → published；驳回留痕；已发布版本不可改，修订走新版本 + `publish_new_version` 显式取代
   - `schemas.py`：病例导入模板校验（L1-L4、四维评分 1-5、八类错误字典、来源声明 real-patient 拒收）
   - `case_import.py`：批量导入（逐文件校验、整批报告、模板文件拒导、重复码跳过）
3. **种子病例 10 个** — `deeptutor/clinical/seed_cases/`（L1×3 / L2×3 / L3×2 / L4×2）
   - 4 个由 ai-companion 原型病例转换（`scripts/convert_companion_cases.py`，错误类型码映射到八类工作字典并在 source.note 留痕）
   - 6 个新合成病例（气胸、急性支气管炎、CAP+Curb-65、肺栓塞初诊、肺占位鉴别、极寒批量伤员战救情境）
   - 全部标记 `origin=synthetic`、状态 draft，正式使用前需医学双审（符合 G0 闸门"仅合成数据开发"）
4. **API 路由** — `deeptutor/api/routers/teaching.py`（10 路由）+ `clinical_cases.py`（12 路由），挂载于 `/api/v1/teaching`、`/api/v1/clinical`，复用上游认证
5. **CLI** — `scripts/import_clinical_cases.py`（导入/模板导出，已用种子病例实测导入 10 个）
6. **测试 36 项全部通过** — `tests/teaching/`（migration、服务规则、权限越界）+ `tests/clinical/`（生命周期、双审、导入、种子覆盖）；ruff 通过
   - 注：本地轻量验证用 `pytest --noconftest`（根 conftest 需完整依赖环境）；完整开发环境直接 `pytest` 即可

**对应验收项（SKILL.md）**：Sprint 0 后端交付全部完成；"migration up/down 正常工作" ✓；`GET /api/v1/teaching/courses` 可用（依赖完整环境启动后验证）；Sprint 2 后端交付的病例框架/导入模板/服务层完成，attempts（结构化推理轨迹）未开始。

**待办（下次）**：WP4 学员尝试与结构化推理轨迹（`clinical/attempts.py`）；RBAC 越权 HTTP 层测试；SBOM 与 clinical-offline 配置（v0.1.0-governed-baseline 打标条件）。

---

## 2026-10-06 — G0 基线建立

- fork Richard0901/DeepTutor 建立并校验：本地 v1.5.2 快照与上游 `b7283548` 零源码差异，基线上移至上游 v1.6.13（`f07029cf`）
- 原快照归档 SHA-256 登记于 `G0-baseline-registration.md`
- D1-D12 决策清单登记，尚无签字项
