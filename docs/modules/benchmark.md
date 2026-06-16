# Benchmark 模块设计文档

> **状态**：✅ 阶段 5已完成
> **代码位置**：`benchmark/`
> **最后更新**：2026-06-16

---

## 模块定位

Benchmark 系统是 AgentForge 的量化评测框架，用数据证明多 Agent 协作的价值。它自动运行标准任务集，对比单 Agent 和多 Agent 的表现，生成 Markdown 报告。

**核心价值**：
> "我设计了定制 benchmark，专门测量多 agent 协作的编排效率、并行度和纠错率。在 20 个标准任务上，多 agent 完成率从 60% 提升到 85%。同时我调研了 SWE-bench、GAIA 等业内标准，发现它们都聚焦单 agent 能力，没有测多 agent 协作的维度。"

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
- `os.chdir()` 切换工作目录（`threading.Lock` 保护）
- 任务结束后恢复 cwd 并删除临时目录

### 超时控制

每个任务 120 秒超时，防止卡住的任务拖垮整轮 benchmark。

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

---

## 报告格式

```markdown
# AgentForge Benchmark Report
> 生成时间：2026-06-16 14:30

## 总体对比
| 指标 | 单 Agent | 多 Agent | 差异 |
|------|---------|----------|------|
| 总完成率 | 12/20 (60%) | 17/20 (85%) | +25% |
| 平均耗时 | 42.3s | 28.7s | -32% |
| 平均 Token | 8.2K | 12.1K | +48% |

## 按难度分
| 难度 | 单 Agent | 多 Agent |
|------|---------|----------|
| easy (8) | 7/8 (88%) | 8/8 (100%) |
| medium (8) | 4/8 (50%) | 7/8 (88%) |
| hard (4) | 1/4 (25%) | 2/4 (50%) |

## 各任务详情
[每个任务的完成状态、耗时、token 消耗]
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

> 最后更新：2026-06-16
