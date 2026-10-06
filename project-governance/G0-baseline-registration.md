# G0 基线登记表

> 依据《DeepTutor二次开发计划-2026-07-24》阶段 0（恢复基线与治理闸门）要求登记。
> 登记日期：2026-10-06

## 1. 仓库与上游来源

| 项目 | 内容 |
| --- | --- |
| 项目 fork | https://github.com/Richard0901/DeepTutor.git |
| 上游仓库 | https://github.com/HKUDS/DeepTutor |
| 上游许可证 | Apache-2.0（见 `LICENSE`；第三方声明见 `THIRD_PARTY_NOTICES.md`；引用见 `CITATION.cff`） |
| 基线 commit | `f07029cf` — release: v1.6.13 |
| 基线日期 | 2026-10-06 |

## 2. 基线版本决策说明

原《二次开发计划》基于 **v1.5.2 源码快照**（2026-07-19 获取，无 git 历史）。本次登记完成如下校验与决策：

1. **快照完整性校验**：将快照与上游 `release: v1.5.2`（commit `b7283548`）全量比对，源码零差异，唯一差异为 `web/package-lock.json` 中 npm 元数据漂移（dev 标志），系 2026-08-23 本地 `npm install` 所致，非人工改动。
2. **无遗留改动**：快照中不含任何二次开发代码或配置改动。
3. **基线上移决策**：因快照为纯上游代码、本地无历史包袱，将基线直接对齐 fork HEAD `v1.6.13`，吸收上游 v1.5.3–v1.6.13 期间修复（含 RAG 教材图片保留、学习者路由鉴权修复等）。后续二开按计划的"修改隔离原则"在桥接层进行，便于持续同步上游。

## 3. 原快照归档

| 项目 | 内容 |
| --- | --- |
| 归档文件 | `project-governance/archive/deeptutor-snapshot-v1.5.2-20260719.tar.gz`（约 37 MB） |
| SHA-256 | `12bf2b6d7919a580d5f36b5fe5cbd091cac8af3aafb3274e8cd241fb6e7949d2` |
| 内容 | v1.5.2 纯源码（不含 data/、.venv/、node_modules/、构建产物） |
| 留存方式 | 该归档被上游 `.gitignore` 的 `*.tar.gz` 规则排除，仅本地留存；其内容可随时由 fork 历史中 commit `b7283548` 复原 |

## 4. 本地运行数据边界（不入库）

以下内容已由 `.gitignore` 排除，**禁止**提交至任何远端仓库：

- `data/`（826 MB）：运行期数据，含"呼吸系统疾病学习"知识库、会话记录 `chat_history.db`、用户工作区；
- `.venv/`、`node_modules/`、`web/.next/`、`*.egg-info/`、`__pycache__/`。

## 5. v0.1.0-governed-baseline 打标条件（未达成，不提前打标）

- [ ] SBOM（依赖清单与许可证扫描）
- [ ] `clinical-offline` 离线配置清单（云模型/外部搜索/MCP 等默认关闭）
- [ ] 教学领域数据库 migration 骨架（WP2 首版）
- [ ] 决策清单（见 `decisions-register.md`）中 D1–D4 完成签字

## 6. G0 尚未关闭的其他闸门事项

按计划阶段 0 要求，以下事项仍待项目组完成，完成前仅允许使用合成数据开发：

- 伦理审批与数据使用授权编号
- "12 万条历史数据"字段级盘点与授权范围确认
- 病例脱敏流程、留存删除与事件响应草案
- 指标说明书与错误类型字典草案冻结
