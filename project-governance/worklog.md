# 变更与工作日志

> 按日期倒序记录。每条注明涉及的工作包（WP）与证据位置。已完成事项必须有对应 commit 或文档；未完成事项如实标注。

## 2026-10-06（第二批）— WP4 学员训练闭环 + HTTP 权限测试 + clinical-offline 最小版 + 管理文档

**代码（本批 commit 1）**：

1. **WP4 学员训练与结构化推理轨迹**（`deeptutor/clinical/attempts.py` + migration 0003 + 5 个 API 路由）：
   - 尝试生命周期：仅 open 作业 + 在读学生 + published 病例；多次重练留痕（append-only）
   - 六类推理步骤（问题表征/鉴别诊断/关键证据/检查选择/处置方案/再评估），前五类必填齐备才能提交；提交后锁定不可改
   - 教师复核：仅本班 teacher/course_admin，支持逐步标记 + 意见；跨班教师/学员一律拒绝
2. **HTTP 层权限测试**（`tests/api/`）：教学路由 4 项 + 临床路由（双审/发布/训练全旅程）4 项 + 学习面映射 2 项；采用仓库惯例（独立 app + contextvar 注入 + `DEEPTUTOR_TEACHING_DB` 隔离）
3. **学习面映射扩展**（`deeptutor/api/routers/auth.py`）：`/api/v1/teaching`、`/api/v1/clinical` 加入学习账号可用面（此前学员一律 403）；课程级权限仍由服务层裁决
4. **clinical-offline 最小可行版**：`deeptutor/deployment/offline.py` 启动守卫（该模式下 auth 未启用拒绝启动）+ `configs/clinical-offline/`（7 个设置模板、compose、nginx 边界代理示例、README 声明"网络层 egress 拒绝必须由宿主/网络策略落实"）
5. **治理 CI**：`.github/workflows/governance.yml`（CycloneDX SBOM + pip-audit + 许可证清单，产物随构建上传）
6. **测试 64 项全部通过**（含既有 36 项不回归）+ ruff 清洁 + 全链路演练（建课程→建班→导入 10 病例→双审发布→作业→五步训练→提交→复核）

**管理文档（本批 commit 2）**：D1 病例计数口径、D2 八类错误字典两份决策签字稿；10 月月度进度填报（含 7-9 月补报口径）；专家病例生产指引一页。

**v0.1.0-governed-baseline 打标状态**：SBOM（CI 产出）、clinical-offline 配置、migration 骨架三项条件就绪；**唯一未满足项为 D1-D4 签字**——签字完成前不打标（不把待办表述为已完成）。

**安全提醒**：本地 `data/user/settings/model_catalog.json` 存有开发期使用的真实 API 密钥（8 月知识库搭建时填入；该目录已被 .gitignore 排除、未入库）。离线部署前必须轮换/清除，见 `configs/clinical-offline/README.md`。

**待办（下次）**：虚拟患者状态机原型（Sprint 3/WP6）；评估助手初评框架（WP7）；完整 10 项服务层离线硬闸门（G3 前）；D1-D4 签字与伦理备案（人工）。

---

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
