# ADR-008：Expert 任务层设计

> **状态**：已采纳（任务集与判据就绪，实测待执行）
> **日期**：2026-10-07
> **决策者**：宇诚
> **影响范围**：benchmark 评测系统、任务集规模、多 Agent 团队构成
> **前置**：ADR-006（测量有效性）、ADR-007（编排优化）、业内对比表 2026 版（modules/benchmark.md）

---

## 背景

v3 实测（编排优化后）显示：单文件任务上多 Agent 编排开销已收窄到 +76%/+51%，成功率与单 Agent 可比（95% vs 100%）。但任务集全部是"单文件、目标明确"型，**三个假设仍未被覆盖**：

- **H1 异质角色**：analyst/writer 两个 Specialist 存在但从未进过 benchmark（多模式一直只有 coder+reviewer）
- **H2 长链条依赖**：hard-03 多 Agent 反超单 Agent（26.4s vs 34.0s）是唯一支持点，样本为 1
- **H3 上下文规模**：完全没有"信息量大到单 Agent 上下文吃紧"的任务

业内对比表 2026 版的结论：没有可直接套用的现成任务集——主题最对口的 MultiAgentBench 用 LLM-as-judge（与确定性判据原则冲突且需 MySQL+Redis），AppWorld 的 457 个 REST API 与文件/shell 工具面不重合。

---

## 决策 1：自建 fixture 为主路径

### 备选方案

**方案 A：自建确定性 fixture 项目（我们的选择）**
- 迷你"库存管理"应用（约 15 文件，内容全部写死），预埋重复代码 / 遗留 bug / 元数据头三类种子
- 完全掌控难度（DeepSeek Flash 能力圈：单 Agent 能做但要跨多文件）与判据确定性

**方案 B：集成 MultiAgentBench**
- LLM-as-judge 方差会污染"编排质量"对比；MySQL+Redis 基建；任务超出单任务 300s 预算

**方案 C：集成 AppWorld**
- 判据范式最理想，但需要 457 个 API 的适配层 + 本地 App 服务器，成本大于自建

### 决定

选择方案 A。种子的可满足性由测试固化：fixture 构建即 pytest 全绿；种子 bug 的回归测试修复前必须失败。

---

## 决策 2：分层团队（expert 四人，其余层维持两人）

### 备选方案

**方案 A：分层团队（我们的选择）**
- expert 层多模式 = analyst + coder + reviewer + writer（writer/analyst 首次进 benchmark）
- easy/medium/hard 维持 coder + reviewer——**v1–v3 实测数字保持可比**
- expert 层 Coder `max_turns=12`（v3 中 medium-07 的失败根因即探索轮次耗尽）

**方案 B：全层统一四人团队**
- 最简单，但 easy/medium 数字与 v3 失去可比性，需要又一次方法学变更声明

### 决定

选择方案 A。实现为 `AgentFactory` 签名增加 `task` 参数，工厂按 `task.difficulty` 分派。

### 风险

expert 层（四人）与其余层（两人）的对比不再"同一团队配置"——如实记录：expert 层测的正是异质角色假设本身，团队构成是假设的一部分。

---

## 决策 3：判据范式（借 AppWorld 状态单测 + MARBLE milestone）

### 采用的范式

1. **AppWorld"状态单测"**：验终态（真实执行 pytest / import 探针，只看返回码或 ASCII 输出，规避 Windows 编码差异）+ **查副作用**（expert-02 的 `PROTECTED_FILES` 与 pristine 逐文件比对——spec 约束不得改动的文件被改即拒）
2. **隐藏验收测试**：expert-02 的验收测试在 judge 时才写入 work_dir（Agent 事前不可见，防"面向判据编程"）
3. **MARBLE milestone 的确定性近似**：长链条任务的各阶段产物（分析/代码/测试/文档）在 judge 内分别断言；顶层指标仍是成功率，阶段级指标列留作后续
4. **期望值判定**（延续 medium-07 范式）：expert-05 的 ground truth 在 judge 时从 work_dir 实际元数据头重算

### 五个任务与假设的绑定

| ID | 任务 | 假设 | 判据要点 |
|----|------|------|---------|
| expert-01 | 去重重构（提取共享模块 + 更新调用点） | H2 | pytest 全绿 + 重复定义消失 + 新模块合规 |
| expert-02 | 按 spec.md 实现低库存告警（跨 services/cli） | H1+H2 | 隐藏验收测试 + 副作用检查 + CLI 端到端 |
| expert-03 | 跨文件 bug 定位修复 | H1 | 回归测试转绿 + 边界语义行为探针 |
| expert-04 | 按项目约定新增模块 + 补文档 | H1 | 真实导入/存取探针 + 元数据头约定 + 文档登记 |
| expert-05 | 全库盘点报告（逐文件元数据清单） | H3 | 期望值重算 + 逐模块同行匹配 |

### 可满足性验证（实测前的结构性保障）

每任务零 API 测试：金路径（直接构造正确终态，judge 必须通过——证明结构性可满足，fbb9c3d"结构性不可满足"教训的应用）+ 失败路径（缺产物/改保护文件/违反约定/漏报错报全拒绝）+ 假 Agent 全管线。

---

## 决策 4：实测延后，复跑检查清单固化

本轮只交付 benchmark 本身（基础设施 + fixture + 任务 + 判据 + 零 API 测试）。真实 LLM 运行延后，恢复实测时按序执行：

1. **难度校准跑**：每个 expert 任务单 Agent runs=1——检测"伪 expert"（单 Agent 轻松满分则先调任务再全量）
2. **quick 冒烟**：`run_benchmark(quick=True)` 确认主管线无回归
3. **全量**：`run_benchmark(runs=3)` 后台运行（预计比 v3 多 45–60 分钟）
4. **结果回写**：docs/benchmark-results.md 阶段 2 章节 + 文档矩阵 + 面试材料数字校准

某项任务实测中被证伪（如 expert-05 对 Flash 模型过难）→ 如实记录并调任务，不带病测。

---

## 风险与局限

- 金路径测试与真实 Agent 行为有差距（Agent 可能走别的路径到达终态）——校准跑兜底
- 判据过严错杀正确 Agent：pytest 判据只看返回码天然抗格式敏感；解析类判据多格式单测先行
- fixture 的元数据头约定可能被 Agent 忽略（README 写明了，但真实 Agent 未必读）——expert-04 刻意把"遵守约定"作为被测能力

---

> **最后更新**：2026-10-07
