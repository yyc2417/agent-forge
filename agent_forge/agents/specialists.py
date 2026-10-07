"""Specialist Agents —— 专业角色 Agent

继承 BaseAgent，通过定制 name、role、tools 和 system prompt
创建具有特定专业能力的 Agent。

当前提供四个 Specialist：
- CoderAgent：编码专家，负责代码实现
- ReviewerAgent：代码审查专家，负责审查代码质量
- AnalystAgent：需求分析专家，负责项目结构分析和需求拆解
- WriterAgent：技术文档撰写专家，负责整合信息生成报告

设计理念：
    BaseAgent 提供了通用的 ReAct 循环和 Bus 集成。
    Specialist 只需要关注"我是谁"（role）和"我能做什么"（tools + prompt）。
    这是模板方法模式的典型应用：父类定义骨架，子类定制行为。

    与 CrewAI 的对比：
    CrewAI 中创建 Agent 需要 Agent(role=..., goal=..., backstory=...) 三个参数，
    封装较厚但灵活性低。我们的 Specialist 只覆盖 get_system_prompt()，
    整个 ReAct 循环和工具调用逻辑完全透明、可控。

扩展方向（后续按需添加）：
    - ArchitectAgent：架构设计专家
    - TesterAgent：测试用例生成专家
    - ResearcherAgent：信息搜集专家

工具权限接线（阶段 3+）：
    默认使用各角色硬编码的工具列表（向后兼容）；
    传入 registry 参数时，通过 ToolRegistry.bind_tools 按角色权限
    过滤工具（Coder→EXECUTE、Reviewer/Analyst→READ、Writer→WRITE），
    注册表中 requires_approval 的工具会带上审批门（HITL）。
"""

from agent_forge.agents.base import BaseAgent
from agent_forge.tools import (
    ToolPermission,
    ToolRegistry,
    grep_search,
    read_file,
    run_shell,
    write_file,
)


class CoderAgent(BaseAgent):
    """编码专家 —— 负责根据需求编写高质量的 Python 代码。

    工具集：read_file + grep_search + write_file + run_shell（EXECUTE 级权限）
    - read_file：阅读项目结构和已有代码，理解上下文
    - grep_search：在项目中搜索关键模式，定位相关代码
    - write_file：将生成的代码写入文件
    - run_shell：运行代码验证正确性、执行测试

    硬编码工具列表与 registry 路径（bind_tools(EXECUTE) 返回默认注册表
    全部 4 个工具）保持一致——2026-09-13 benchmark 实测后修复：旧硬编码
    列表缺 grep_search，导致单 Agent（ALL_TOOLS）与多 Agent 模式工具
    不对等，easy-05（文件搜索）的对比混入了工具配置差异。

    与 ReviewerAgent 的分工：
    - Coder 负责"写"—— 实现功能、编写代码
    - Reviewer 负责"审"—— 发现问题、给出判定
    - 两者的 system prompt 互补，形成编码-审查闭环
    """

    # 经 ToolRegistry 绑定工具时允许的最大权限级别
    _max_permission = ToolPermission.EXECUTE

    def __init__(self, bus=None, llm=None, registry: ToolRegistry | None = None, approval_callback=None, **kwargs):
        super().__init__(
            name="coder",
            role="资深 Python 工程师，擅长编写简洁、可读、健壮的代码",
            tools=registry.bind_tools(self._max_permission, approval_callback=approval_callback) if registry
            else [read_file, grep_search, write_file, run_shell],
            bus=bus,
            llm=llm,
            max_turns=kwargs.get("max_turns", 8),
            # 阶段 3新增参数透传
            memory=kwargs.get("memory"),
            long_term_memory=kwargs.get("long_term_memory"),
            enable_memory_tools=kwargs.get("enable_memory_tools", False),
            hooks=kwargs.get("hooks"),
            cost_tracker=kwargs.get("cost_tracker"),
        )

    def get_system_prompt(self) -> str:
        return """\
你是 AgentForge 团队中的编码专家。

你的职责是根据需求分析，编写高质量的 Python 代码。

工作原则：
1. 代码简洁、可读、有清晰的注释
2. 遵循 PEP 8 规范
3. 包含基本的错误处理
4. 如果需求不明确，做出合理假设并说明

输出格式：
先简要说明实现思路，然后给出完整代码。
如果需要写入文件，使用 write_file 工具。
"""


class ReviewerAgent(BaseAgent):
    """代码审查专家 —— 负责审查代码质量并给出通过/不通过判定。

    工具集：read_file + grep_search（只读）
    - 审查者只需要"读"代码，不需要修改或执行
    - 这体现了最小权限原则：每个 Agent 只拥有完成任务所需的最小工具集
    - grep_search 用于定位待审查代码（与 registry READ 路径一致）

    判定格式：
    system prompt 要求 Reviewer 首先输出【通过】或【不通过】。
    Orchestrator 据此做条件路由：
    - 【通过】→ 进入汇总阶段
    - 【不通过】→ 回退到 Coder 重新编码

    为什么用中文方括号【】而不是英文 [OK]/[FAIL]？
    - 中文方括号在 LLM 输出中辨识度更高，不容易被混入正文
    - 判定按【通过】/【不通过】标记精确匹配，减少误判
    """

    # 经 ToolRegistry 绑定工具时允许的最大权限级别（只读角色）
    _max_permission = ToolPermission.READ

    def __init__(self, bus=None, llm=None, registry: ToolRegistry | None = None, approval_callback=None, **kwargs):
        super().__init__(
            name="reviewer",
            role="代码审查专家，关注安全性、性能和代码风格",
            tools=registry.bind_tools(self._max_permission, approval_callback=approval_callback) if registry
            else [read_file, grep_search],
            bus=bus,
            llm=llm,
            max_turns=kwargs.get("max_turns", 3),
            # 阶段 3新增参数透传
            memory=kwargs.get("memory"),
            long_term_memory=kwargs.get("long_term_memory"),
            enable_memory_tools=kwargs.get("enable_memory_tools", False),
            hooks=kwargs.get("hooks"),
            cost_tracker=kwargs.get("cost_tracker"),
        )

    def get_system_prompt(self) -> str:
        return """\
你是 AgentForge 团队中的代码审查专家。

你的职责是审查代码质量，给出明确的通过或不通过判定。

可用工具：
- read_file：读取代码文件内容进行审查
- grep_search：在项目中搜索关键模式，定位待审查代码
注意：你只有 read_file 和 grep_search 两个只读工具，
不要尝试调用 run_shell、write_file 或其他工具。
如果任务描述中没有指定文件名，请根据上下文推断（如当前目录下的 .py 文件）。

审查维度：
1. 安全性：是否有注入、越权等风险
2. 性能：是否有明显的性能问题
3. 代码风格：是否符合 PEP 8，命名是否清晰
4. 完整性：是否覆盖了边界情况

输出格式（严格遵守）：
- 首先给出判定：【通过】或【不通过】
- 然后列出发现的问题（如有）
- 最后给出改进建议（如有）

注意：如果代码质量可接受，应该给出【通过】，不要过于苛刻。
只有存在严重问题（安全漏洞、功能缺失、明显 bug）时才给【不通过】。
"""


class AnalystAgent(BaseAgent):
    """需求分析专家 —— 负责分析项目结构和需求拆解。

    工具集：read_file + grep_search
    - read_file：阅读项目文件，理解现有结构和上下文
    - grep_search：搜索代码中的关键模式，定位相关代码

    设计意图：
    Analyst 是"只读"角色——分析需求、理解项目结构、输出分析报告，
    但不修改任何文件。这与 Coder（读写+执行）形成互补。
    """

    # 经 ToolRegistry 绑定工具时允许的最大权限级别（只读角色）
    _max_permission = ToolPermission.READ

    def __init__(self, bus=None, llm=None, registry: ToolRegistry | None = None, approval_callback=None, **kwargs):
        super().__init__(
            name="analyst",
            role="需求分析师，擅长项目结构分析和需求拆解",
            tools=registry.bind_tools(self._max_permission, approval_callback=approval_callback) if registry
            else [read_file, grep_search],
            bus=bus,
            llm=llm,
            max_turns=kwargs.get("max_turns", 5),
            memory=kwargs.get("memory"),
            long_term_memory=kwargs.get("long_term_memory"),
            enable_memory_tools=kwargs.get("enable_memory_tools", False),
            hooks=kwargs.get("hooks"),
            cost_tracker=kwargs.get("cost_tracker"),
        )

    def get_system_prompt(self) -> str:
        return """\
你是 AgentForge 团队中的需求分析专家。

你的职责是分析项目结构和需求，输出清晰的分析报告。

可用工具：
- read_file：读取项目文件内容
- grep_search：在文件中搜索指定文本模式

工作原则：
1. 先了解项目整体结构（目录、关键文件）
2. 深入分析需求涉及的模块和代码
3. 输出结构化的分析报告

输出格式：
- 项目结构概述
- 需求分析（功能点、技术要点）
- 建议方案（如适用）

注意：你只负责分析，不要修改任何文件。
"""


class WriterAgent(BaseAgent):
    """技术文档撰写专家 —— 负责整合信息生成报告文件。

    工具集：read_file + write_file
    - read_file：读取前序 Agent 的产出，理解上下文
    - write_file：将整合后的报告写入文件

    设计意图：
    Writer 是"写入"角色——基于 Analyst 和 Coder 的产出，
    整合为结构清晰的技术报告或文档。与 Analyst（只读）互补。
    """

    # 经 ToolRegistry 绑定工具时允许的最大权限级别（可写不可执行）
    _max_permission = ToolPermission.WRITE

    def __init__(self, bus=None, llm=None, registry: ToolRegistry | None = None, approval_callback=None, **kwargs):
        super().__init__(
            name="writer",
            role="技术文档撰写专家，擅长整合信息生成结构化报告",
            tools=registry.bind_tools(self._max_permission, approval_callback=approval_callback) if registry
            else [read_file, write_file],
            bus=bus,
            llm=llm,
            max_turns=kwargs.get("max_turns", 5),
            memory=kwargs.get("memory"),
            long_term_memory=kwargs.get("long_term_memory"),
            enable_memory_tools=kwargs.get("enable_memory_tools", False),
            hooks=kwargs.get("hooks"),
            cost_tracker=kwargs.get("cost_tracker"),
        )

    def get_system_prompt(self) -> str:
        return """\
你是 AgentForge 团队中的技术文档撰写专家。

你的职责是基于前序 Agent 的产出，整合为结构清晰的技术报告或文档。

可用工具：
- read_file：读取相关文件内容
- write_file：将报告写入文件

工作原则：
1. 仔细阅读前序 Agent 的产出（分析报告、代码等）
2. 整合信息，形成结构化的报告
3. 使用 Markdown 格式，确保报告清晰可读
4. 将报告写入指定文件

输出格式：
- 报告应包含：标题、概述、详细内容、结论
- 使用 Markdown 格式（标题、列表、代码块等）
- 写入文件后，在回复中说明文件路径和内容摘要
"""
