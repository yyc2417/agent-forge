# Benchmark 模块设计文档

> **状态**：✅ 阶段 5已完成
> **代码位置**：`benchmark/`
> **最后更新**：2026-10-07（超时分级/期望值 judge/报告异常明细，见 ADR-006；数字待 v2 重跑后校准）

---

## 模块定位

Benchmark 系统是 AgentForge 的量化评测框架，用数据回答"多 Agent 协作何时有价值"。它自动运行标准任务集，对比单 Agent 和多 Agent 的表现，生成 Markdown 报告。

**核心结论**（2026-09-13 全量实测）：
> "我设计了定制 benchmark，在 20 个分级任务上对比单 Agent 与多 Agent 编排（每任务 3 次取中位数）。实测发现：单 Agent 成功率 90%（18/20）高于多 Agent 的 85%（17/20），而多 Agent 的 token 成本约为 3.5 倍、耗时约 3.7 倍——easy 任务上多 Agent 是负收益，编排的价值区间在更复杂的场景。同时我调研了 SWE-bench、GAIA 等业内标准，发现它们都聚焦单 agent 能力，没有测多 agent 协作的维度。"

---

## 架构设计

```
benchmark/
├── tasks/          # 20 个标准任务（8 easy + 8 medium + 4 hard）
│   ├── easy/       # 文件操作、Shell 命令、简单计算
│   ├── medium/     # 函数编写、代码分析、多文件操作
│   └── hard/       # 完整类实现、代码重构、报告生成
├── judge.py        # 自动评判器（5 种评判类型）
├── metrics.py      # 指标采集（TaskMetrics + MetricsCollector）
├── runner.py       # 执行引擎（BenchmarkRunner）
└── reporter.py     # 报告生成器（Markdown）
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

以下为 2026-09-13 全量实测报告的总体部分（完整数据见 [benchmark-results.md](../benchmark-results.md)）：

```markdown
# AgentForge Benchmark Report
> 生成时间：2026-09-13 00:25

## 总体对比
| 指标 | 单 Agent | 多 Agent | 差异 |
|------|---------|----------|------|
| 总完成率 | 18/20 (90%) | 17/20 (85%) | -5% |
| 平均耗时 | 15.3s | 56.3s | +268% |
| 平均 Token | 22,257 | 77,777 | +250% |

## 按难度分
| 难度 | 单 Agent | 多 Agent |
|------|---------|----------|
| easy (8) | 8/8 (100%) | 7/8 (88%) |
| medium (8) | 7/8 (88%) | 7/8 (88%) |
| hard (4) | 3/4 (75%) | 3/4 (75%) |

## 各任务详情
[每个任务的完成状态、耗时、token 消耗]

## 异常与超时明细（2026-10-07 新增，仅在有异常时输出）
[按任务×模式列出去重后的 errors：超时 / judge 异常 / setup 失败]
```

---

## 使用方式

```python
# 快速模式（5 个 easy 任务，1 次运行）
from benchmark import run_benchmark
single, multi, report = run_benchmark(quick=True)

# 完整模式（20 个任务，3 次运行）
single, multi, report = run_benchmark()

# 按难度过滤
single, multi, report = run_benchmark(difficulty="easy")
```

---

## 与业内 Benchmark 的对比

| Benchmark | 出品方 | 测什么 | 为什么不用 |
|-----------|--------|--------|-----------|
| SWE-bench | Princeton | 单 agent 代码修复 | 不测多 agent 协作 |
| GAIA | Meta | 推理 + 工具调用 | 不涉及 agent 分工 |
| AgentBench | THU | 8 个环境的 agent 能力 | 偏任务覆盖面 |

**核心发现**：业内还没有专门测"多 Agent 协作编排质量"的通用 benchmark。

---

> 最后更新：2026-10-07
