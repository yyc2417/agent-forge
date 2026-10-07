# Benchmark 模块设计文档

> **状态**：✅ 阶段 5已完成
> **代码位置**：`benchmark/`
> **最后更新**：2026-10-07（超时分级/期望值 judge/报告异常明细，见 ADR-006；数字待 v2 重跑后校准）

---

## 模块定位

Benchmark 系统是 AgentForge 的量化评测框架，用数据回答"多 Agent 协作何时有价值"。它自动运行标准任务集，对比单 Agent 和多 Agent 的表现，生成 Markdown 报告。

**核心结论**（2026-10-07 v3，编排优化后 A/B）：
> "我设计了定制 benchmark，在 20 个分级任务上对比单 Agent 与多 Agent 编排（每任务 3 次取中位数）。第一轮实测后我复审自己的评测系统，修掉 4 个测量有效性问题得到干净基线（单 100% vs 多 95%，多 Agent 成本 4.5 倍）；接着做三项编排优化（复杂度门控/审查交接/判定双通道）再同日 A/B：成功率持平，多 Agent 编排开销从 +416%/+353% 收窄到 +76%/+51%，超时清零，hard-03 上多 Agent 首次反超单 Agent。业内标准 2025 年调研过一轮（SWE-bench/GAIA/AgentBench），2026 年复查了 MultiAgentBench、AppWorld 等新套件：结论仍成立——最对口的 MultiAgentBench 也用 LLM-as-judge 评协作，'确定性判据评多 Agent 协作'没有现成解。"

---

## 架构设计

```
benchmark/
├── tasks/          # 25 个标准任务（8 easy + 8 medium + 4 hard + 5 expert）
│   ├── easy/       # 文件操作、Shell 命令、简单计算
│   ├── medium/     # 函数编写、代码分析、多文件操作
│   ├── hard/       # 完整类实现、代码重构、报告生成（超时 240s）
│   └── expert/     # 去重重构/规格实现/跨文件修 bug/约定扩展/全库盘点
│                   #   + fixture_project.py（确定性库存管理应用，ADR-008）
├── judge.py        # 自动评判器（5 种评判类型）
├── metrics.py      # 指标采集（TaskMetrics + MetricsCollector）
├── runner.py       # 执行引擎（BenchmarkRunner，分层团队工厂）
└── reporter.py     # 报告生成器（Markdown + 异常明细）
```

### 核心类

| 类 | 职责 |
|---|------|
| `TaskDefinition` | 任务定义（id, description, judge_config, timeout） |
| `Judge` | 自动评判（contains/file_exists/file_contains/regex/custom） |
| `MetricsCollector` | 指标采集（wall_time, tokens, messages, success） |
| `BenchmarkRunner` | 执行引擎（加载任务 → 隔离执行 → 超时控制 → 聚合） |
| `Reporter` | Markdown 报告生成 |
| `TaskMetrics` | 单次运行的指标快照 |
| `BenchmarkSummary` | 多任务汇总统计 |

---

## 执行流程

```
1. 加载任务（load_all_tasks 扫描 tasks/ 目录）
    │
2. 对每个任务，执行 3 轮（消除 LLM 随机性）
    │
3. 每轮内部：
    ├── 创建临时目录（隔离执行）
    ├── 创建独立 Bus + CostTracker
    ├── 运行 Agent（单/多模式）
    ├── Judge 评判
    └── 清理临时目录
    │
4. 聚合 3 轮结果（中位数 + 多数投票）
    │
5. 生成 Markdown 报告
```

### 隔离执行

每个任务在独立的临时目录中运行：
- `tempfile.mkdtemp()` 创建临时目录
- 任务在 worker 线程中执行，线程内 `set_sandbox_root(work_dir)`
  把所有文件工具锚定到本任务的临时目录（线程局部，并发安全）
- 不再使用 `os.chdir()`——旧实现的进程级 cwd 切换在任务执行期间
  会被并发 runner 踩踏，已从根上移除
- 任务结束后删除临时目录

### 超时控制

每个任务默认 120 秒超时（`task.timeout` 可覆盖），防止卡住的任务
拖垮整轮 benchmark：
- setup / Agent / judge / teardown 在 worker 线程中执行，
  主线程 `join(timeout)` 等待
- 超时则本次运行记为失败（errors 记录 `task timeout after Ns`），
  继续下一任务
- 线程无法被强杀：卡死的调用（如 LLM 网络挂起）会残留为 daemon
  线程，随进程退出回收

**超时分级**（2026-10-07，ADR-006）：hard 层 4 个任务统一
`timeout: 240`——2026-09-13 实测中 hard-04 双模式在 120s 预算内
超时失败，最重任务需要更大的预算；easy/medium 维持 120s。

### 可重复性

同一任务跑 3 次取中位数：
- `wall_time` 取中位数
- `success` 用多数投票（超过半数成功则判定成功）
- 消除 LLM 输出的随机性干扰

---

## 评判系统

### 5 种评判类型

| 类型 | 说明 | 示例 |
|------|------|------|
| `contains` | Agent 输出包含指定字符串 | 输出包含 "5050" |
| `file_exists` | 指定文件已创建 | `hello.py` 存在 |
| `file_contains` | 指定文件包含指定内容 | `fibonacci.py` 包含 `def fibonacci` |
| `regex` | 正则匹配 Agent 输出 | 输出匹配 `\d+` |
| `custom` | 调用自定义 judge 函数 | 检查类方法齐全 + 可 import |

### 设计原则

- 尽量用简单规则（contains/regex），少用 LLM 评判
- LLM 评判有偏差，数字对比更可靠
- 评判规则足够宽松以容纳合理变体，又足够严格以区分成功/失败
- **期望值判定优先于格式匹配**（2026-10-07，ADR-006）：regex 类
  judge 匹配的是"输出长什么样"，Agent 算对但表述不同就会被误判
  （medium-07 双模式"失败"即此问题）。需要验证计算结果的任务改用
  custom judge：setup 构造已知答案的数据，judge 时从工作目录重算
  ground truth，对输出做宽容解析（如"文件名与行数同行出现"）。

---

## 报告格式

以下为 2026-10-07 v3（编排优化后）全量实测报告的总体部分（完整数据见 [benchmark-results.md](../benchmark-results.md)）：

```markdown
# AgentForge Benchmark Report
> 生成时间：2026-10-07 14:03

## 总体对比
| 指标 | 单 Agent | 多 Agent | 差异 |
|------|---------|----------|------|
| 总完成率 | 20/20 (100%) | 19/20 (95%) | -5% |
| 平均耗时 | 11.9s | 20.9s | +76% |
| 平均 Token | 18976 | 28712 | +51% |

## 按难度分
| 难度 | 单 Agent | 多 Agent |
|------|---------|----------|
| easy (8) | 8/8 (100%) | 8/8 (100%) |
| medium (8) | 8/8 (100%) | 7/8 (88%) |
| hard (4) | 4/4 (100%) | 4/4 (100%) |

## 各任务详情
[每个任务的完成状态、耗时、token 消耗]

## 异常与超时明细（本轮无异常，本节不输出）
```

---

## 使用方式

```python
# 快速模式（5 个 easy 任务，1 次运行）
from benchmark import run_benchmark
single, multi, report = run_benchmark(quick=True)

# 完整模式（25 个任务，3 次运行；expert 层已建待测，实测数字以报告为准）
single, multi, report = run_benchmark()

# 按难度过滤
single, multi, report = run_benchmark(difficulty="easy")
```

---

## Expert 难度层（2026-10-07 建成，实测待执行）

任务集的第四层（ADR-008），补测 v1–v3 实测未覆盖的三个假设：

| 假设 | 内容 | 对应任务 |
|------|------|---------|
| H1 异质角色 | analyst/writer 的专用 prompt+工具集的价值（expert 层多模式为四人团队，其余层维持 coder+reviewer 两人队） | expert-02/03/04 |
| H2 长链条依赖 | 有明确阶段顺序的任务中计划结构化的收益 | expert-01/02 |
| H3 上下文规模 | 信息量大到单 Agent 上下文吃紧时分而治之的收益 | expert-05 |

- **Fixture**：`tasks/expert/fixture_project.py`——确定性库存管理应用（约 15 文件），预埋重复代码 / 遗留 bug / 元数据头三类种子；构建即 pytest 全绿由测试固化
- **判据范式**（借自 AppWorld 状态单测，见业内对比）：验终态（真实跑 pytest / import 探针，只看返回码）+ 查副作用（保护文件与 pristine 逐文件比对）+ 隐藏验收测试（judge 时写入）
- **可满足性**：每任务的金路径/失败路径零 API 测试——judge 对正确终态必过、对错误终态必拒

---

## 与业内 Benchmark 的对比（2026-10 复查版）

| Benchmark | 出品方 | 测什么 | 为什么不用（判据 / 工具面 / 基础设施） |
|-----------|--------|--------|--------------------------------------|
| SWE-bench (Lite/Verified) | Princeton | 单 agent 代码修复（真实 GitHub Issue） | 单 agent 能力域；每任务需 checkout 特定 commit + 安装依赖 + Docker，远超本框架单任务 240s 预算 |
| GAIA | Meta | 多跳推理 + 工具调用 | 大部分任务需要网页浏览，与文件/shell 工具沙箱不匹配 |
| AgentBench | THU | 8 个环境的 agent 能力 | 偏任务覆盖面，无协作维度 |
| **MultiAgentBench (MARBLE)** | 清华（ACL 2025） | 多 Agent 协作与竞争（6 场景） | **主题最对口**，但判据是 LLM-as-judge + milestone 检测器——与本项目确定性判据原则冲突；需要 MySQL+Redis docker-compose；任务基于 SWE-bench-lite/Commit0，超出单任务预算 |
| **AppWorld** | Stony Brook（ACL 2024） | 交互式工具使用（9 App / 457 API） | 判据范式已被本项目借鉴（状态单测，见 ADR-008）；但 REST API 世界与文件/shell 工具沙箱不重合，集成需独立适配层；license 同意后 train/dev 仅 90/57 题可用 |
| **TheAgentCompany** | CMU | 长程公司场景任务 | 需自托管 GitLab/RocketChat/ownCloud 全家桶，基础设施成本不成立 |
| **HiddenBench** | arXiv（2026-02） | 分布式信息下的集体推理 | 概念上贴近"上下文规模"假设，harness 不可直接复用，列为跟踪对象 |

**核心发现（2026 版）**：业内仍没有"确定性判据的多 Agent 协作 benchmark"——主题最对口的 MultiAgentBench 也用 LLM-as-judge 评协作，反证"规则判据 + 自建任务集"路线的难度与价值。新套件的可借鉴处在于范式而非套件本身：AppWorld 的状态单测（验终态 + 查副作用）与 MARBLE 的 milestone 拆解已分别落入 expert 层判据设计（ADR-008）。

---

> 最后更新：2026-10-07
