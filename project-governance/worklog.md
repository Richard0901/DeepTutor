# 变更与工作日志

> 按日期倒序记录。每条注明涉及的工作包（WP）与证据位置。已完成事项必须有对应 commit 或文档；未完成事项如实标注。

## 2026-10-06（第五批）— WP8 教师看板最小版（班级聚合 + 风险规则 + 干预闭环）

**代码（本批 commit）**：

1. **migration 0006**：`teacher_interventions`（干预记录，open/resolved + outcome 留痕）。**口径偏差声明**：计划 §4.3 的 `risk_flags`/`analytics_snapshots` 表暂缓——风险项改为读取时确定性计算（规则透明、随代码版本化），待多批次数据量上来后再做持久化快照（WP9+）。
2. **AnalyticsService（`deeptutor/analytics/service.py`）**：
   - `class_overview`：作业完成度（总尝试数/开做学生数）、学生维度指标（提交/复核次数、教师确认错误类型分布、最后活动时间）、待复核数、未关闭干预数；仅本班教职工可见；
   - `risk_flags`：确定性规则——无任何尝试、有提交无复核、尝试停留 in_progress 超 7 天（证据带 attempt_id 前缀）、教师确认错误 ≥3 次触发重复（与 WP7 阈值一致）；每条带证据字段；
   - 干预闭环：记录（校验目标必须是本班学生）→ 解决（outcome + resolved_at）→ 列表，跨班一律拒绝。
3. **API 路由 5 个**：`/teacher/classes/{id}/dashboard`、`/risk-flags`、`/interventions`（GET+POST）、`/teacher/interventions/{id}/resolve`（挂 `/api/v1/clinical`）。
4. **测试 +6**（看板权限/尝试计数/风险规则与消除/过期尝试/干预闭环与越权/跨班不可见），全库 **87 项通过**，ruff 清洁。

**MVP 后端就此齐装**：计划阶段 2（G2）要求的后端能力——课程/班级/病例双审发布/学员训练六步轨迹/虚拟患者确定性问诊/评估初评+人工复核/教师看板+干预闭环/40/60 之外的治理闸门——全部就绪；缺前端页面与真实病例内容（人工路径）。

**待办（下次）**：前端最小可用版（学员训练页 + 教师看板/复核页，Sprint 4-5 前端项）；LLM 初评待 G3 效度研究；战救动态引擎 WP9。

---

## 2026-10-06（第四批）— WP7 评估助手框架（规则初评 v1 + 人工复核）

**代码（本批 commit）**：

1. **migration 0005**：`rubric_versions`（按病例版本快照评分量规，幂等）+ `assessment_runs` + `assessment_scores`（error_type CHECK 锁定八类字典，confidence 0-1，needs_human_review 默认 1）+ `human_reviews`（agree/override/dismiss 追加式留痕）。
2. **规则初评 v1（`assessment/rules.py`）**：确定性结构检查——问题表征过简（evidence_gap 提示）、鉴别语言缺失（differential_exclusion）、关键证据与病例要点 2-gram 重叠检测（evidence_integration）、检查选择脱离病例配置（decision_rationale）、处置缺依据语言（decision_rationale）。全部低置信度（≤0.3）且强制 needs_human_review=1——按计划口径，AI 分类在效度验证（G3 金标准研究）前只是教师提示，不进正式成绩。
3. **LLM 评估桩（`assessment/llm.py`）**：`llm_local` 引擎显式未实现并 fail-loud（服务层拒绝该引擎），文件内写明集成契约（本地模型、结构化输出校验、置信度上限、提示注入防护），待 G3 后接入。
4. **服务（`assessment/service.py`）**：评估运行（仅本班教职工、仅已提交尝试）、量规快照幂等、复核队列（按班级过滤 pending）、教师复核（原始标签永不改写，只移 review_status；override 需给出 final_error_type 或 final_is_correct）、**错误重复检测**（仅统计教师确认的 agree/override，D2 草案阈值 14 天/≥3 次触发系统性补偿，窗口与阈值参数化）。
5. **API 路由 4 个**：POST `/attempts/{id}/assess`、GET `/assessment-runs/{id}`、GET `/teacher/assessment-queue`、POST `/assessment-scores/{id}/review`。
6. **测试 +9**（规则命中/清洁尝试/权限与引擎限制/LLM 桩 fail-loud/复核留痕与二次复核拒绝/队列范围与清理/量规快照幂等/重复阈值触发/overlap 检测），全库 **81 项通过**，ruff 清洁。

**待办（下次）**：WP8 教师看板最小版（班级聚合/风险队列/干预记录）；复核结论与尝试教师复核（`attempts.record_review`）的联动口径；LLM 初评待 G3 效度研究。

---

## 2026-10-06（第三批）— WP6 虚拟患者 MVP（Sprint 3）

**代码（本批 commit）**：

1. **migration 0004**：`patient_sessions`（会话）+ `patient_events`（追加式事件日志，session_id+seq 唯一）。状态快照表按计划 §4.3 暂缓——当前事件量级下回放即读，README/worklog 留痕，事件量增长后再加缓存。
2. **脚本 schema（`virtual_patient/script.py`）**：`script_version: 2`，snake_case 字段（inquiry_map/exam_results/disposition_options/phase_actions/required_revelations），兼容 ai-companion 原型 camelCase 字段的归一化读取；`progressionScript`/`disclosureRules` 原样保留为 WP9 输入，本引擎不消费。格式不合法的脚本（如 L4 批量伤员情境）按"无脚本"处理并留待 WP9。
3. **确定性引擎（`virtual_patient/engine.py`）**：五阶段（initial→history_taking→examination→disposition→terminated），动作白名单按相位配置；关键词匹配释放问诊信息（含"新信息"标注与未命中兜底话术）；检查结果按配置释放；处置需 `required_revelations` 齐备，提交即终止并给出正误反馈。纯函数转换（state, script, action）→(next_state, released)，无随机、无时钟、无 LLM，事件重放可逐字节复原状态。
4. **会话服务（`virtual_patient/service.py`）**：仅本人 + in_progress 尝试可开会话；每次动作追加一个事件；会话状态由事件回放重建（日志不一致即报错）；脚本变更后旧会话拒绝继续动作。
5. **提交门槛集成**：带脚本的病例，学员尝试提交前必须完成至少一次已终止的问诊会话（SKILL Sprint 3 验收项"未到终态前不能提交最终答案"）。
6. **API 路由 4 个**：POST/GET `/patient-sessions`、POST `/{id}/actions`、GET `/{id}/events`（挂 `/api/v1/clinical`）。
7. **种子升级**：RESP-L2-001 患者脚本转为 v2 schema（11 问诊话题 + 4 项检查 + 3 个处置选项），转换留痕字段 `converted_from`。
8. **测试**：新增 8 项（脚本校验/相位门控/信息释放/处置门槛/事件重放一致性/所有权/全流程/无脚本病例不设门槛），全库 72 项通过，ruff 清洁。
9. **全链路演练**：L2-001 导入→双审发布→作业→五步训练→提交被门槛拦截→问诊会话（begin→5 问→进检查相→肺功能→进处置相→提交处置）→提交放行→教师复核，10 个事件完整可回放。

**修复记录**：批次 1 清理插桩时误删 `AttemptService.record_review`（截断重写法所致），本批发现并恢复，HTTP 层测试可覆盖该方法。经验教训：尾部重写类编辑后必须跑全量回归。

**待办（下次）**：WP7 评估助手初评框架（量规版本、AI 初评占位、错误标注、低置信度转人工）；患者脚本的内容生产指引并入专家指引；会话详情页前端（Sprint 3 前端项）。

---

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
