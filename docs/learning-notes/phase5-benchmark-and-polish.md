# 阶段 5学习笔记：Benchmark 设计与工程化收尾

> **日期**：2026-06-16
> **学习范围**：Benchmark 系统设计、单元测试、CI/CD、多场景演示
> **校准注记（2026-09-29）**：本文写于全量实测之前，部分数字为当时估计；已就地回写 2026-09-13 实测值（来源 docs/benchmark-results.md）

---

## 为什么需要 Benchmark？

在技术讨论中说"多 Agent 比单 Agent 好"是不够的——大家要看数据。但业内没有现成的多 Agent 协作 benchmark：

| Benchmark | 出品方 | 测什么 | 为什么不用 |
|-----------|--------|--------|-----------|
| SWE-bench | Princeton | 单 agent 代码修复 | 不测多 agent 协作 |
| GAIA | Meta | 推理 + 工具调用 | 不涉及 agent 分工和通信 |
| AgentBench | THU | 8 个环境 | 偏任务覆盖面 |

所以自己设计了一个定制 benchmark，测量完成率、耗时、Token 消耗，对比单/多 Agent 两种模式。

---

## Benchmark 设计的关键决策

### 为什么同一任务跑 3 次？

LLM 的输出不是确定性的——同一个任务跑两次，Agent 可能走不同的路径、用不同的工具、产出不同的代码。如果只跑 1 次，结果可能被随机性干扰。

3 次取中位数是折中方案：
- 1 次：太随机
- 3 次：够用，且不会太贵（2026-09 实测：单 Agent 平均 15.3s/次，多 Agent 56.3s/次；任务级 120s 超时兜底）
- 5 次：更准确但成本翻倍

### 为什么用临时目录隔离执行？

Agent 在执行任务时会创建文件、修改文件系统。如果不隔离：
- easy-01 创建了 `hello.py`
- easy-02 读取当前目录文件时看到了 `hello.py`
- 这影响了 easy-02 的初始状态，破坏了公平性

用 `tempfile.mkdtemp()` 创建临时目录，任务结束后 `shutil.rmtree()` 清理。

### 评判为什么不用 LLM？

LLM 评判有偏差：
- 对同一个输出，两次评判可能给出不同结论
- 对长文本的注意力分散，可能漏掉关键信息
- 成本更高（每次评判需要额外的 LLM 调用）

简单规则更可靠：
- `contains`：输出包含 "5050" → 成功
- `file_contains`：文件包含 "def fibonacci" → 成功
- `regex`：匹配 `\d+` → 成功

只在复杂场景（如"代码质量分析"）才用 `custom` 评判函数。

---

## 单元测试的心得

### pytest + mock vs 真实 API

我们的策略是混合模式：
- **快速测试**（`-m "not slow"`）：不依赖 LLM API，验证模块的纯逻辑（序列化、路由、权限、状态管理）
- **慢测试**（`-m "slow"`）：调用真实 DeepSeek API，验证端到端行为

快速测试的好处：
- 秒级完成，开发时频繁跑
- 不消耗 API token
- 不受网络状况影响

慢测试的必要性：
- 验证 LLM 的实际输出是否符合预期
- 验证 Agent 的端到端行为（从输入到产出）
- 只在 CI 的 push to main 时跑

### 测试用例的覆盖

**校准（2026-09-29）**：当前全仓共 **202 个用例**（快速套件 `pytest -m "not slow"` 197 通过 + 1 skip，slow 标记 4 个），比下表的 6 月快照新增了 sandbox、shell_security、mcp_tools、persistence、approval、bench_runner 等模块。下表保留为历史快照：

| 模块 | 用例数（2026-06 快照） | 关键测试点 |
|------|--------|-----------|
| Message | 10 | 序列化/反序列化往返、UUID 自动生成 |
| Bus | 15 | pub/sub 路由、拦截器链、handler 异常隔离 |
| Agent | 5 | 初始化、system prompt、真实 API 调用 |
| Orchestrator | 7 | JSON 解析/fallback、审查判定、真实 API |
| Specialist | 10 | 工具集验证、prompt 内容 |
| Tools | 10 | 文件读写、Shell 黑名单、搜索匹配 |
| Registry | 7 | 注册/注销、权限过滤 |
| Cost | 9 | 记录/汇总、零值忽略、报告输出 |
| Hooks | 8 | 注册/触发、异常隔离、清空 |
| Collector | 11 | 状态推导、线程安全、is_running |
| Memory | 10 | 短期/长期记忆、会话保存加载 |

---

## CI/CD 的设计

### GitHub Actions 的矩阵策略

```yaml
strategy:
  matrix:
    python-version: ["3.11", "3.12"]
```

两个版本同时测试，确保兼容性。

### 快速/慢测试分离

- PR 触发：只跑快速测试（秒级反馈）
- Push to main：跑全部测试（包含真实 API 调用）

```yaml
- name: Run fast tests
  run: pytest tests/ -m "not slow" -v

- name: Run slow tests
  if: github.event_name == 'push' && github.ref == 'refs/heads/main'
  run: pytest tests/ -m "slow" -v
```

### Secret 管理

`DEEPSEEK_API_KEY` 通过 GitHub Secrets 注入，不硬编码在代码中。

---

## 思考题回答

### 如何保证 benchmark 结果的公平性？

三层保障：
1. **隔离执行**：每个任务用临时目录，初始状态一致
2. **重复运行**：3 次取中位数，消除随机性
3. **统一配置**：单/多 Agent 使用相同的 LLM（DeepSeek）、相同的 temperature (0.0)、相同的工具集

### 多 Agent 的 Token 消耗更高，怎么解释？

**校准（2026-09-29）**：本文初稿写"Token 多约 40%/1.4 倍、Reviewer 发现约 20% 问题"，均为实测前的估计且无测量来源，已被 2026-09-13 全量实测推翻。实测结论（docs/benchmark-results.md）：

- 多 Agent 平均 Token 是单 Agent 的 **约 3.5 倍**（77,777 vs 22,257），耗时约 3.7 倍
- 成功率反而略低：85% vs 90%（easy 任务 7/8 vs 8/8）

讨论时可以用这套更诚实的框架："多 Agent 的协调开销是真实的——Orchestrator 拆解、子任务间上下文重复携带、Reviewer 轮次都在消耗 token。easy 任务上是明确的负收益；编排的价值区间在更复杂的场景，我的实测数据把这条边界量化出来了。"——反直觉但可验证的结论，比"多 Agent 更好"更有讨论价值。

**校准 2（2026-10-07）**：上述注记引用的是 v1 实测（90% vs 85%、3.5 倍）。当天复审发现 v1 评测系统自身有 4 个测量有效性问题（hard-04 引用缺失文件、单/多模式工具不对等、medium-07 judge 格式敏感、hard 层超时不足），修复（ADR-006）后重测的 v2 基线：**单 Agent 100%（20/20）vs 多 Agent 95%（19/20），多 Agent token 约 4.5 倍、耗时约 5.1 倍**。叙事升级为两段：先修评测环境（2026-09-12 快速验证跑），再修测量方法（2026-10-07 复审）——"我两次测出了自己评测系统的问题"本身就是比任何数字更强的工程素养证明。v1 的"easy 上多 Agent 成功率负收益"结论在 v2 中撤回（工具对等后 8/8 打平），负收益体现为纯成本（约 12 倍耗时）。

---

## 本周收获

1. **数据驱动**：用 benchmark 数据说话比"我感觉更好"有说服力 10 倍
2. **测试分层**：快速测试 + 慢测试分离，既保证开发效率又保证质量
3. **CI/CD 是标配**：GitHub 上的 CI badge 是工程素养的第一印象
4. **收尾比开发更重要**：阶段 5不写新功能，但让项目从"能跑"升级为"可证明、可展示"

---

> **最后更新**：2026-10-07（v2 基线校准 + 方法学复审注记）
