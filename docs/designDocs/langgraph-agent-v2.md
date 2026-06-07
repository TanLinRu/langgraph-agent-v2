# LangGraph Agent v2 - 完整实现文档

本文档详细描述项目的所有实现细节，可供其他 agent 1:1 复刻源码。

---

## 目录

1. [项目结构](#1-项目结构)
2. [环境配置](#2-环境配置)
3. [后端实现](#3-后端实现)
4. [前端实现](#4-前端实现)
5. [数据库设计](#5-数据库设计)
6. [API 接口](#6-api-接口)
7. [启动命令](#7-启动命令)
8. [关键设计决策](#8-关键设计决策)
9. [已知问题与设计规约](#9-已知问题与设计规约)

---

## 1. 项目结构

```
langgraph-agent-v2/
├── .env.example                    # 环境变量模板
├── .gitignore                      # Git 忽略规则
├── pyproject.toml                  # Python 项目配置
├── server.py                       # FastAPI 服务器入口
├── IMPLEMENTATION.md               # 本文档
│
├── src/
│   ├── __init__.py                 # 空文件
│   └── agent/
│       ├── __init__.py             # 空文件
│       ├── agent.py                # Agent 核心类
│       ├── config.py               # Pydantic 配置
│       ├── state.py                # LangGraph 状态定义
│       ├── models.py               # LLM 模型工厂
│       ├── graph.py                # LangGraph StateGraph
│       ├── supervisor.py           # 多 Agent 编排
│       ├── main.py                 # CLI 入口
│       ├── event_bus.py            # SSE 事件总线
│       ├── error_handler.py        # 错误处理
│       ├── checkpoint.py           # 会话持久化
│       ├── skills.py               # 技能系统
│       │
│       ├── context/
│       │   ├── __init__.py         # 空文件
│       │   ├── _helpers.py         # Token 计数 & 去重
│       │   ├── compression.py      # 上下文压缩
│       │   ├── memory.py           # 记忆管理 (SQLite + ChromaDB)
│       │   └── tool_result_manager.py  # 工具结果截断
│       │
│       ├── prompts/
│       │   ├── __init__.py         # 空文件
│       │   └── system_prompt.py    # 系统提示词模板
│       │
│       └── tools/
│           ├── __init__.py         # TOOLS 列表导出
│           ├── execute_code.py     # 代码执行工具
│           ├── file_ops.py         # 文件操作工具
│           └── search.py           # 文件搜索工具
│
├── tests/
│   ├── __init__.py                 # 空文件
│   ├── conftest.py                 # pytest fixtures
│   ├── test_config.py
│   ├── test_compression.py
│   ├── test_memory.py
│   ├── test_tools.py
│   ├── test_event_bus.py
│   ├── test_error_handler.py
│   ├── test_server.py
│   ├── test_mock_flow.py
│   └── test_real_api.py
│
├── skills/                         # 技能目录 (运行时可选)
│   └── *.md
│
└── ui/                             # Vue 3 前端
    ├── package.json
    ├── tsconfig.json
    ├── vite.config.ts
    └── src/
        ├── main.ts
        ├── env.d.ts
        ├── App.vue
        ├── components/
        │   ├── ChatTab.vue
        │   └── AgentsTab.vue
        ├── stores/
        │   ├── chat.ts
        │   └── agents.ts
        └── utils/
            └── api.ts
```

---

## 2. 环境配置

### 2.1 `.env.example`

```env
# Model Provider: "openai" | "anthropic"
AGENT_MODEL_PROVIDER=openai
AGENT_MODEL_NAME=gpt-4o

# OpenAI-compatible
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.openai.com/v1

# Anthropic
ANTHROPIC_API_KEY=sk-ant-xxx

# Context
AGENT_MAX_TOKENS=128000
AGENT_COMPRESSION_THRESHOLD=0.7

# Storage
AGENT_MEMORY_DB_PATH=memory/agent.db
AGENT_CHROMA_PATH=memory/chroma

# Server
AGENT_SERVER_HOST=0.0.0.0
AGENT_SERVER_PORT=8000
```

### 2.2 `pyproject.toml`

```toml
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "langgraph-agent-v2"
version = "0.1.0"
description = "Simplified AI Agent with multi-agent supervisor, context compression, memory, and SSE"
requires-python = ">=3.11"
dependencies = [
    "langchain>=0.3.0",
    "langgraph>=0.2.0",
    "langgraph-supervisor>=0.0.31",
    "langchain-openai",
    "langchain-anthropic",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "tiktoken",
    "chromadb",
    "sqlite-utils",
    "python-dotenv",
    "fastapi",
    "uvicorn[standard]",
    "sse-starlette",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov",
    "ruff",
    "mypy",
]

[tool.setuptools.packages.find]
where = ["."]

[tool.ruff]
target-version = "py311"
line-length = 120

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W"]

[tool.mypy]
python_version = "3.11"
warn_return_any = true
warn_unused_configs = true

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = [
    "unit: unit tests",
    "integration: integration tests",
    "slow: slow tests",
]
```

### 2.3 `.gitignore`

```gitignore
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
dist/
build/
.eggs/
*.egg
.env
.venv/
venv/
env/
.mypy_cache/
.ruff_cache/
.pytest_cache/
.coverage
htmlcov/
memory/*.db
memory/chroma/
node_modules/
ui/dist/
*.log
.DS_Store
Thumbs.db
```

---

## 3. 后端实现

### 3.1 `src/agent/config.py` - 配置管理

使用 Pydantic Settings 管理配置，通过 `Field(alias=...)` 支持混合环境变量前缀。

```python
import os

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Model ────────────────────────────────────────────────────
    agent_model_provider: str = Field(default="openai", alias="AGENT_MODEL_PROVIDER")
    agent_model_name: str = Field(default="gpt-4o", alias="AGENT_MODEL_NAME")

    # OpenAI-compatible (no AGENT_ prefix)
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")

    # Anthropic (no AGENT_ prefix)
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")

    # ── Context ──────────────────────────────────────────────────
    agent_max_tokens: int = Field(default=128000, alias="AGENT_MAX_TOKENS")
    agent_compression_threshold: float = Field(default=0.7, alias="AGENT_COMPRESSION_THRESHOLD")

    # ── Storage ──────────────────────────────────────────────────
    agent_memory_db_path: str = Field(default="memory/agent.db", alias="AGENT_MEMORY_DB_PATH")
    agent_chroma_path: str = Field(default="memory/chroma", alias="AGENT_CHROMA_PATH")

    # ── Server ───────────────────────────────────────────────────
    agent_server_host: str = Field(default="0.0.0.0", alias="AGENT_SERVER_HOST")
    agent_server_port: int = Field(default=8000, alias="AGENT_SERVER_PORT")

    # ── Convenience properties ───────────────────────────────────
    @property
    def model_provider(self) -> str:
        return self.agent_model_provider

    @property
    def model_name(self) -> str:
        return self.agent_model_name

    @property
    def max_tokens(self) -> int:
        return self.agent_max_tokens

    @property
    def compression_threshold(self) -> float:
        return self.agent_compression_threshold

    @property
    def memory_db_path(self) -> str:
        return self.agent_memory_db_path

    @property
    def chroma_path(self) -> str:
        return self.agent_chroma_path

    @property
    def server_host(self) -> str:
        return self.agent_server_host

    @property
    def server_port(self) -> int:
        return self.agent_server_port
```

**关键设计**:
- 使用 `Field(alias=...)` 而非 `env_prefix`，允许 `OPENAI_API_KEY` 和 `AGENT_*` 两种前缀共存
- 属性只读，测试需设置内部字段名 (如 `config.agent_max_tokens = 100`)

---

### 3.2 `src/agent/state.py` - 状态定义

```python
from typing import Annotated

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages
from typing_extensions import TypedDict


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    task_type: str
    context_tokens: int
    memory_context: str


class SubAgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    task: str
    result: str
```

---

### 3.3 `src/agent/models.py` - LLM 模型工厂

```python
from langchain_core.language_models import BaseChatModel

from src.agent.config import AgentConfig


def resolve_model(config: AgentConfig) -> BaseChatModel:
    if config.model_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model_name=config.model_name,
            anthropic_api_key=config.anthropic_api_key,
        )
    else:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=config.model_name,
            api_key=config.openai_api_key,
            base_url=config.openai_base_url,
            model_kwargs={"enable_thinking": True},
        )
```

**关键设计**:
- OpenAI 模型默认启用 `enable_thinking=True` 支持推理内容

---

### 3.4 `src/agent/agent.py` - Agent 核心类

```python
import json
from collections.abc import AsyncIterator
from typing import Any

import openai
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from src.agent.config import AgentConfig
from src.agent.context.compression import ContextCompressor
from src.agent.context.tool_result_manager import truncate_result
from src.agent.models import resolve_model
from src.agent.tools import TOOLS


class Agent:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.llm = resolve_model(config)
        self.tools = TOOLS
        self.tool_map = {t.name: t for t in self.tools}
        self.llm_with_tools = self.llm.bind_tools(self.tools)
        self.compressor = ContextCompressor(config)

    def _build_system_message(self, memory_context: str = "", summary: str = "") -> SystemMessage:
        from src.agent.prompts.system_prompt import SYSTEM_PROMPT
        from src.agent.skills import get_skills_prompt

        parts = []
        if summary:
            parts.append(f"[Conversation History]\n{summary}")
        if memory_context:
            parts.append(f"[Memory Context]\n{memory_context}")

        extra = "\n\n".join(parts)
        skills_prompt = get_skills_prompt()
        content = SYSTEM_PROMPT.format(
            skills=f"\n\n{skills_prompt}" if skills_prompt else "",
            memory_context=f"\n\n{extra}" if extra else "",
        )
        return SystemMessage(content=content)

    def _log_request(self, label: str, messages: list[BaseMessage], extra: dict[str, Any] | None = None) -> None:
        from src.agent.context._helpers import count_tokens

        token_count = count_tokens(messages)
        threshold = int(self.config.max_tokens * self.config.compression_threshold)
        print(f"\n{'='*70}")
        print(f"[LLM Request] {label}")
        print(f"  Model:     {self.config.model_provider}/{self.config.model_name}")
        print(f"  Base URL:  {self.config.openai_base_url}")
        print(f"  Messages:  {len(messages)}")
        print(f"  Tokens:    ~{token_count} / {self.config.max_tokens} (compress at {threshold})")
        print(f"  Tools:     {[t.name for t in self.tools]}")
        print(f"  ---")
        for i, msg in enumerate(messages):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            preview = content[:150] + "..." if len(content) > 150 else content
            print(f"  [{i}] {msg.type}: {preview}")
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    print(f"       -> tool_call: {tc['name']}({tc['args']})")
        if extra:
            print(f"  ---")
            for k, v in extra.items():
                print(f"  {k}: {v}")
        print(f"{'='*70}\n")

    @staticmethod
    def _messages_to_openai(messages: list[BaseMessage]) -> list[dict]:
        """Convert LangChain messages to OpenAI API format."""
        result = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                result.append({"role": "system", "content": msg.content})
            elif isinstance(msg, HumanMessage):
                result.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                d: dict[str, Any] = {"role": "assistant", "content": msg.content}
                if msg.tool_calls:
                    d["tool_calls"] = [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {"name": tc["name"], "arguments": json.dumps(tc["args"], ensure_ascii=False)},
                        }
                        for tc in msg.tool_calls
                    ]
                result.append(d)
            elif isinstance(msg, ToolMessage):
                result.append({"role": "tool", "tool_call_id": msg.tool_call_id, "content": msg.content})
        return result

    def _get_raw_client(self) -> openai.AsyncOpenAI:
        """Get raw OpenAI async client for streaming with reasoning_content support."""
        return openai.AsyncOpenAI(
            api_key=self.config.openai_api_key,
            base_url=self.config.openai_base_url,
        )

    async def _stream_raw(self, messages: list[BaseMessage]) -> AsyncIterator[dict[str, Any]]:
        """Stream via raw OpenAI client, yielding thinking/content/tool_call events."""
        client = self._get_raw_client()
        openai_messages = self._messages_to_openai(messages)
        tools_spec = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": t.args_schema.schema() if hasattr(t, "args_schema") and t.args_schema else {"type": "object", "properties": {}},
                },
            }
            for t in self.tools
        ]

        print(f"\n[RAW STREAM] Calling {self.config.model_name} with enable_thinking=True")
        stream = await client.chat.completions.create(
            model=self.config.model_name,
            messages=openai_messages,
            tools=tools_spec if tools_spec else None,
            stream=True,
            extra_body={"enable_thinking": True},
        )

        thinking_started = False
        content_parts: list[str] = []
        tool_calls_map: dict[int, dict] = {}
        chunk_count = 0

        async for chunk in stream:
            chunk_count += 1
            delta = chunk.choices[0].delta if chunk.choices else None
            if not delta:
                continue

            # Debug: dump raw delta attributes for first few chunks
            if chunk_count <= 5:
                raw = chunk.model_dump()
                print(f"\n[RAW chunk #{chunk_count}] delta keys: {list(raw.get('choices', [{}])[0].get('delta', {}).keys())}")
                d = raw.get("choices", [{}])[0].get("delta", {})
                if d.get("reasoning_content"):
                    print(f"  reasoning_content: {d['reasoning_content'][:80]}...")
                if d.get("content"):
                    print(f"  content: {d['content'][:80]}...")

            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                if not thinking_started:
                    yield {"type": "thinking_start"}
                    thinking_started = True
                yield {"type": "thinking", "data": reasoning}

            if delta.content:
                content_parts.append(delta.content)

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_map:
                        tool_calls_map[idx] = {"id": "", "name": "", "arguments": ""}
                    entry = tool_calls_map[idx]
                    if tc.id:
                        entry["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            entry["name"] = tc.function.name
                        if tc.function.arguments:
                            entry["arguments"] += tc.function.arguments

        if thinking_started:
            yield {"type": "thinking_done"}

        print(f"\n[RAW STREAM DONE] chunks={chunk_count}, thinking={thinking_started}")
        content = "".join(content_parts)
        tool_calls = []
        for idx in sorted(tool_calls_map):
            entry = tool_calls_map[idx]
            try:
                args = json.loads(entry["arguments"]) if entry["arguments"] else {}
            except json.JSONDecodeError:
                args = {}
            tool_calls.append({"id": entry["id"], "name": entry["name"], "args": args})

        response = AIMessage(content=content, tool_calls=tool_calls if tool_calls else [])
        yield {"type": "_response", "data": response}

    async def _astream_with_thinking(self, messages: list[BaseMessage]) -> AsyncIterator[dict[str, Any]]:
        """Stream LLM response, yielding thinking events. Override _stream_raw for testing."""
        async for event in self._stream_raw(messages):
            yield event

    async def run(self, user_input: str, memory_context: str = "", history: list[BaseMessage] | None = None) -> AsyncIterator[dict[str, Any]]:
        system_msg = self._build_system_message(memory_context)
        messages = [system_msg] + (history or []) + [HumanMessage(content=user_input)]

        # Compress before first call if history makes messages too long
        compressed = False
        if self.compressor.should_compress(messages):
            summary, recent = await self.compressor.compress(messages[1:])  # skip system msg
            system_msg = self._build_system_message(memory_context, summary)
            messages = [system_msg] + recent
            compressed = True

        self._log_request("1st call", messages, {"compressed": compressed})

        # Stream first call with thinking support
        response: AIMessage | None = None
        async for event in self._astream_with_thinking(messages):
            if event["type"] == "_response":
                response = event["data"]
            else:
                yield event

        if response and response.tool_calls:
            yield {"type": "tool_call", "data": [{"name": tc["name"], "args": tc["args"]} for tc in response.tool_calls]}
            messages.append(response)

            for tool_call in response.tool_calls:
                tool_fn = self.tool_map.get(tool_call["name"])
                if tool_fn:
                    try:
                        result = await tool_fn.ainvoke(tool_call["args"])
                    except Exception as e:
                        result = f"Error: {e}"
                    result_str = truncate_result(tool_call["name"], str(result))
                    messages.append(
                        ToolMessage(content=result_str, tool_call_id=tool_call["id"], name=tool_call["name"])
                    )

            # Check if compression is needed before final call (tool results may push over threshold)
            compressed = False
            if self.compressor.should_compress(messages):
                summary, recent = await self.compressor.compress(messages[1:])  # skip system msg
                system_msg = self._build_system_message(memory_context, summary)
                messages = [system_msg] + recent
                compressed = True

            self._log_request("2nd call", messages, {"compressed": compressed})

            # Stream second call with thinking support
            final: AIMessage | None = None
            async for event in self._astream_with_thinking(messages):
                if event["type"] == "_response":
                    final = event["data"]
                else:
                    yield event

            yield {"type": "message", "data": final.content if final else ""}
        else:
            yield {"type": "message", "data": response.content if response else ""}

        yield {"type": "done"}

    async def run_stream(self, user_input: str, memory_context: str = "", history: list[BaseMessage] | None = None) -> AsyncIterator[str]:
        async for event in self.run(user_input, memory_context, history):
            import json
            yield json.dumps(event, ensure_ascii=False)
```

**核心流程**:
1. `run()` 是异步生成器，产出 `{type, data}` 事件
2. 流程: system msg → LLM call 1 → 如有 tool_calls: 执行工具 → 可选压缩 → LLM call 2 → 产出结果
3. 使用原始 OpenAI 客户端流式调用，支持 `reasoning_content` (thinking)
4. 事件类型: `thinking_start`, `thinking`, `thinking_done`, `tool_call`, `message`, `done`

---

### 3.5 `src/agent/graph.py` - LangGraph StateGraph

```python
from langchain_core.messages import AIMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from src.agent.config import AgentConfig
from src.agent.context.compression import ContextCompressor
from src.agent.models import resolve_model
from src.agent.prompts.system_prompt import SYSTEM_PROMPT
from src.agent.state import AgentState
from src.agent.tools import TOOLS


def create_graph(config: AgentConfig | None = None) -> StateGraph:
    config = config or AgentConfig()
    llm = resolve_model(config)
    llm_with_tools = llm.bind_tools(TOOLS)
    tool_node = ToolNode(TOOLS)
    compressor = ContextCompressor(config)

    def _build_system(memory_ctx: str = "", summary: str = "") -> SystemMessage:
        parts = []
        if summary:
            parts.append(f"[Conversation History]\n{summary}")
        if memory_ctx:
            parts.append(f"[Memory Context]\n{memory_ctx}")
        extra = "\n\n".join(parts)
        return SystemMessage(content=SYSTEM_PROMPT.format(memory_context=f"\n\n{extra}" if extra else ""))

    async def think(state: AgentState) -> dict:
        memory_ctx = state.get("memory_context", "")
        existing = state["messages"]

        # Always rebuild the single SystemMessage
        system_msg = _build_system(memory_ctx)
        messages = [system_msg] + list(existing)

        # Compress if needed (skip system msg at index 0)
        if compressor.should_compress(messages[1:]):
            summary, recent = await compressor.compress(messages[1:])
            system_msg = _build_system(memory_ctx, summary)
            messages = [system_msg] + recent

        response: AIMessage = await llm_with_tools.ainvoke(messages)
        return {"messages": [response]}

    async def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return END

    graph = StateGraph(AgentState)
    graph.add_node("think", think)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("think")
    graph.add_conditional_edges("think", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "think")

    return graph.compile()


graph = create_graph()
```

**流程**: `think` node (LLM) → 条件边到 `tools` 或 `END` → `tools` node → 回到 `think`

---

### 3.6 `src/agent/supervisor.py` - 多 Agent 编排

```python
from langchain_core.language_models import BaseChatModel
from langgraph.graph import StateGraph
from langgraph.prebuilt import create_react_agent

from src.agent.config import AgentConfig
from src.agent.models import resolve_model
from src.agent.state import AgentState
from src.agent.tools import TOOLS


def build_sub_agent(
    name: str,
    tools: list,
    system_prompt: str,
    config: AgentConfig,
) -> StateGraph:
    model = resolve_model(config)
    return create_react_agent(model, tools, prompt=system_prompt, name=name)


class SupervisorManager:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.agents: dict[str, StateGraph] = {}

    def register_agent(self, name: str, agent: StateGraph) -> None:
        self.agents[name] = agent

    def build_supervisor(self) -> StateGraph:
        from langgraph_supervisor import create_supervisor

        agent_list = list(self.agents.values())
        model = resolve_model(self.config)
        return create_supervisor(
            agents=agent_list,
            model=model,
            prompt=self._supervisor_prompt(),
        ).compile()

    def _supervisor_prompt(self) -> str:
        agent_descs = []
        for name in self.agents:
            agent_descs.append(f"- **{name}**: delegate to this agent for {name}-related tasks")
        agents_text = "\n".join(agent_descs)
        return f"""You are a supervisor managing specialized agents:

{agents_text}

Analyze the user's request and delegate to the most appropriate agent.
For complex tasks, coordinate multiple agents sequentially."""


def create_default_supervisor(config: AgentConfig) -> SupervisorManager:
    from src.agent.prompts.system_prompt import SUPERVISOR_PROMPT
    from src.agent.tools.execute_code import execute_code
    from src.agent.tools.file_ops import list_directory, read_file, write_file
    from src.agent.tools.search import search_files

    manager = SupervisorManager(config)

    coder = build_sub_agent(
        "coder",
        tools=[execute_code, read_file, write_file],
        system_prompt="You are a coding expert. Write and execute code to solve problems.",
        config=config,
    )
    researcher = build_sub_agent(
        "researcher",
        tools=[search_files, list_directory, read_file],
        system_prompt="You are a research expert. Search and analyze files to find information.",
        config=config,
    )
    analyst = build_sub_agent(
        "analyst",
        tools=[execute_code, read_file, search_files],
        system_prompt="You are a data analyst. Process data and generate insights.",
        config=config,
    )

    manager.register_agent("coder", coder)
    manager.register_agent("researcher", researcher)
    manager.register_agent("analyst", analyst)

    return manager
```

**子 Agent 分工**:
- `coder`: execute_code, read_file, write_file
- `researcher`: search_files, list_directory, read_file
- `analyst`: execute_code, read_file, search_files

---

### 3.7 `src/agent/tools/__init__.py` - 工具导出

```python
from src.agent.tools.execute_code import execute_code
from src.agent.tools.file_ops import list_directory, read_file, write_file
from src.agent.tools.search import search_files

TOOLS = [execute_code, read_file, write_file, list_directory, search_files]

__all__ = ["TOOLS", "execute_code", "read_file", "write_file", "list_directory", "search_files"]
```

---

### 3.8 `src/agent/tools/execute_code.py` - 代码执行工具

```python
import subprocess
import sys
import tempfile
from pathlib import Path

from langchain_core.tools import tool


@tool
def execute_code(code: str, language: str = "python") -> str:
    """Execute code and return the output. Supports Python."""
    if language != "python":
        return f"Unsupported language: {language}"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        tmp_path = f.name

    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Code execution timed out (30s limit)"
    except Exception as e:
        return f"Error: {e}"
    finally:
        Path(tmp_path).unlink(missing_ok=True)
```

---

### 3.9 `src/agent/tools/file_ops.py` - 文件操作工具

```python
from pathlib import Path

from langchain_core.tools import tool


@tool
def read_file(file_path: str, offset: int = 0, limit: int = 2000) -> str:
    """Read the contents of a file."""
    try:
        p = Path(file_path)
        if not p.exists():
            return f"Error: File not found: {file_path}"
        content = p.read_text(encoding="utf-8")
        lines = content.splitlines()
        selected = lines[offset : offset + limit]
        return "\n".join(selected)
    except Exception as e:
        return f"Error reading file: {e}"


@tool
def write_file(file_path: str, content: str) -> str:
    """Write content to a file. Creates parent directories if needed."""
    try:
        p = Path(file_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} bytes to {file_path}"
    except Exception as e:
        return f"Error writing file: {e}"


@tool
def list_directory(path: str = ".") -> str:
    """List files and directories at the given path."""
    try:
        p = Path(path)
        if not p.exists():
            return f"Error: Directory not found: {path}"
        if not p.is_dir():
            return f"Error: Not a directory: {path}"
        entries = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        lines = []
        for entry in entries:
            prefix = "📁 " if entry.is_dir() else "📄 "
            lines.append(f"{prefix}{entry.name}")
        return "\n".join(lines) or "(empty directory)"
    except Exception as e:
        return f"Error listing directory: {e}"
```

---

### 3.10 `src/agent/tools/search.py` - 文件搜索工具

```python
import fnmatch
from pathlib import Path

from langchain_core.tools import tool


@tool
def search_files(pattern: str, path: str = ".", max_results: int = 20) -> str:
    """Search for files matching a glob pattern."""
    try:
        p = Path(path)
        if not p.exists():
            return f"Error: Path not found: {path}"
        matches = []
        for item in p.rglob("*"):
            if len(matches) >= max_results:
                break
            if fnmatch.fnmatch(item.name, pattern):
                rel = item.relative_to(p)
                prefix = "📁 " if item.is_dir() else "📄 "
                matches.append(f"{prefix}{rel}")
        if not matches:
            return f"No files matching '{pattern}' found in {path}"
        header = f"Found {len(matches)} matches" + (" (truncated)" if len(matches) >= max_results else "") + ":"
        return header + "\n" + "\n".join(matches)
    except Exception as e:
        return f"Error searching files: {e}"
```

---

### 3.11 `src/agent/prompts/system_prompt.py` - 系统提示词

```python
SYSTEM_PROMPT = """You are a helpful AI assistant with access to various tools.

When you need to:
- Execute code: use the execute_code tool
- Read or write files: use read_file / write_file tools
- Search for files: use search_files or list_directory tools

Always think step by step before taking action. If a task is complex, break it down into smaller steps.
{skills}
{memory_context}"""

SUPERVISOR_PROMPT = """You are a supervisor managing a team of specialized agents:

- **coder**: Expert at writing and executing code. Use for programming tasks, debugging, code generation.
- **researcher**: Expert at finding information. Use for searching files, looking up documentation, gathering data.
- **analyst**: Expert at data analysis. Use for processing data, generating insights, creating reports.

Analyze the user's request and delegate to the most appropriate agent(s). For complex tasks, you may need to coordinate multiple agents sequentially.

Always explain your reasoning for choosing which agent to delegate to."""
```

---

### 3.12 `src/agent/context/_helpers.py` - 辅助函数

```python
import tiktoken
from langchain_core.messages import BaseMessage


def count_tokens(messages: list[BaseMessage], model: str = "gpt-4o") -> int:
    try:
        enc = tiktoken.encoding_for_model(model)
    except KeyError:
        enc = tiktoken.get_encoding("cl100k_base")
    total = 0
    for msg in messages:
        total += 4  # message overhead
        if isinstance(msg.content, str):
            total += len(enc.encode(msg.content))
        elif isinstance(msg.content, list):
            for part in msg.content:
                if isinstance(part, dict) and "text" in part:
                    total += len(enc.encode(part["text"]))
    return total


def deduplicate_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    seen: set[str] = set()
    result = []
    for msg in messages:
        key = f"{msg.type}:{msg.content[:100] if isinstance(msg.content, str) else str(msg.content)[:100]}"
        if key not in seen:
            seen.add(key)
            result.append(msg)
    return result
```

---

### 3.13 `src/agent/context/compression.py` - 上下文压缩

```python
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from src.agent.config import AgentConfig
from src.agent.context._helpers import count_tokens


class ContextCompressor:
    def __init__(self, config: AgentConfig) -> None:
        self.max_tokens = config.max_tokens
        self.threshold = config.compression_threshold
        self.keep_recent = 5

    def should_compress(self, messages: list[BaseMessage]) -> bool:
        token_count = count_tokens(messages)
        return token_count > int(self.max_tokens * self.threshold)

    def extract_system_and_rest(self, messages: list[BaseMessage]) -> tuple[SystemMessage | None, list[BaseMessage]]:
        """Split messages into (system_message, rest). SystemMessage is always at index 0 if present."""
        if messages and isinstance(messages[0], SystemMessage):
            return messages[0], messages[1:]
        return None, messages

    async def compress(self, messages: list[BaseMessage], llm=None) -> tuple[str, list[BaseMessage]]:
        """Compress old messages into a summary string.

        Returns:
            (summary_text, recent_messages) — caller merges summary into the SystemMessage.
        """
        if len(messages) <= self.keep_recent:
            return "", messages

        recent = messages[-self.keep_recent:]
        old = messages[:-self.keep_recent]

        summary = await self._summarize(old, llm)
        return summary, recent

    async def _summarize(self, messages: list[BaseMessage], llm=None) -> str:
        if llm is None:
            return self._fallback_summary(messages)

        summary_prompt = [
            SystemMessage(content=(
                "Summarize the following conversation history concisely. "
                "Preserve: key facts, decisions made, tool results, and any open questions. "
                "Use the format: [role] key points."
            )),
            HumanMessage(content=self._messages_to_text(messages)),
        ]
        response = await llm.ainvoke(summary_prompt)
        return response.content if isinstance(response.content, str) else str(response.content)

    def _fallback_summary(self, messages: list[BaseMessage]) -> str:
        parts = []
        for msg in messages:
            if isinstance(msg, ToolMessage):
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                if len(content) > 300:
                    content = content[:150] + " ... " + content[-150:]
                parts.append(f"[tool:{msg.name}] {content}")
            elif isinstance(msg, AIMessage):
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                if msg.tool_calls:
                    calls = ", ".join(f"{tc['name']}({tc['args']})" for tc in msg.tool_calls)
                    parts.append(f"[assistant] Called: {calls}")
                elif content:
                    if len(content) > 300:
                        content = content[:300] + "..."
                    parts.append(f"[assistant] {content}")
            elif isinstance(msg, HumanMessage):
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                if len(content) > 300:
                    content = content[:300] + "..."
                parts.append(f"[user] {content}")
        return "\n".join(parts[-15:])

    def _messages_to_text(self, messages: list[BaseMessage]) -> str:
        parts = []
        for msg in messages:
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if isinstance(msg, ToolMessage):
                tc_id = msg.tool_call_id[:8] if msg.tool_call_id else "?"
                if len(content) > 500:
                    content = content[:250] + " ... " + content[-250:]
                parts.append(f"[tool:{msg.name} call_id={tc_id}] {content}")
            elif isinstance(msg, AIMessage):
                if msg.tool_calls:
                    calls = ", ".join(f"{tc['name']}({tc['args']})" for tc in msg.tool_calls)
                    parts.append(f"[assistant] Tool calls: {calls}")
                if content:
                    if len(content) > 500:
                        content = content[:500] + "..."
                    parts.append(f"[assistant] {content}")
            elif isinstance(msg, HumanMessage):
                if len(content) > 500:
                    content = content[:500] + "..."
                parts.append(f"[user] {content}")
        return "\n".join(parts)
```

**关键逻辑**:
- `should_compress()`: token 数 > max_tokens * threshold 时触发
- `compress()`: 返回 `(summary_text, recent_messages)`，调用方合并 summary 到 SystemMessage
- 保留最近 5 条消息 (`keep_recent = 5`)
- 必须始终只有一个 SystemMessage

---

### 3.14 `src/agent/context/memory.py` - 记忆管理

```python
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import chromadb

from src.agent.config import AgentConfig


class MemoryManager:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        Path(config.memory_db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(config.memory_db_path, check_same_thread=False)
        self._init_db()
        self.chroma = chromadb.PersistentClient(path=config.chroma_path)

    def _init_db(self) -> None:
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                namespace TEXT NOT NULL,
                key TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_namespace ON memories(namespace)")
        self.db.commit()

    def store(self, key: str, content: str, namespace: str = "default") -> None:
        now = datetime.now(timezone.utc).isoformat()
        existing = self.db.execute(
            "SELECT id FROM memories WHERE namespace = ? AND key = ?", (namespace, key)
        ).fetchone()

        if existing:
            self.db.execute(
                "UPDATE memories SET content = ?, updated_at = ? WHERE id = ?",
                (content, now, existing[0]),
            )
        else:
            self.db.execute(
                "INSERT INTO memories (id, namespace, key, content, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), namespace, key, content, now, now),
            )
        self.db.commit()

        collection = self.chroma.get_or_create_collection(namespace)
        doc_id = f"{namespace}:{key}"
        collection.upsert(ids=[doc_id], documents=[content], metadatas=[{"key": key}])

    def retrieve(self, query: str, namespace: str = "default", top_k: int = 5) -> list[dict]:
        try:
            collection = self.chroma.get_collection(namespace)
            results = collection.query(query_texts=[query], n_results=top_k)
            items = []
            for i, doc in enumerate(results["documents"][0] if results["documents"] else []):
                items.append({
                    "content": doc,
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                })
            return items
        except Exception:
            return []

    def list_memories(self, namespace: str = "default") -> list[dict]:
        rows = self.db.execute(
            "SELECT key, content, created_at, updated_at FROM memories WHERE namespace = ? ORDER BY updated_at DESC",
            (namespace,),
        ).fetchall()
        return [{"key": r[0], "content": r[1], "created_at": r[2], "updated_at": r[3]} for r in rows]

    def delete(self, key: str, namespace: str = "default") -> None:
        self.db.execute("DELETE FROM memories WHERE namespace = ? AND key = ?", (namespace, key))
        self.db.commit()
        try:
            collection = self.chroma.get_collection(namespace)
            collection.delete(ids=[f"{namespace}:{key}"])
        except Exception:
            pass

    def inject_context(self, query: str, namespace: str = "default", top_k: int = 3) -> str:
        memories = self.retrieve(query, namespace, top_k)
        if not memories:
            return ""
        lines = [m["content"] for m in memories]
        return "\n".join(lines)

    def close(self) -> None:
        self.db.close()
        self.chroma = None
```

**双写策略**: SQLite (元数据) + ChromaDB (向量)

---

### 3.15 `src/agent/context/tool_result_manager.py` - 工具结果截断

```python
"""Tool result truncation — prevents large tool outputs from blowing up context."""

# Max chars per tool type
_LIMITS = {
    "execute_code": 2000,
    "read_file": 4000,
    "write_file": 500,
    "list_directory": 2000,
    "search_files": 2000,
}

_DEFAULT_LIMIT = 2000


def truncate_result(tool_name: str, result: str) -> str:
    """Truncate a tool result if it exceeds the limit for that tool type."""
    limit = _LIMITS.get(tool_name, _DEFAULT_LIMIT)
    if len(result) <= limit:
        return result

    if tool_name == "read_file":
        # Keep head + pointer to full content
        head = result[:limit - 200]
        return f"{head}\n\n... [truncated, {len(result)} chars total]"

    if tool_name == "execute_code":
        # Keep stdout head, truncate stderr if present
        lines = result.split("\n")
        truncated = []
        total = 0
        for line in lines:
            if total + len(line) + 1 > limit - 100:
                truncated.append(f"... [truncated, {len(result)} chars total]")
                break
            truncated.append(line)
            total += len(line) + 1
        return "\n".join(truncated)

    # Generic truncation
    head = result[:limit - 100]
    return f"{head}\n\n... [truncated, {len(result)} chars total]"
```

---

### 3.16 `src/agent/event_bus.py` - SSE 事件总线

```python
import asyncio
import json
from datetime import datetime, timezone
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue]] = {}

    def subscribe(self, stream_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.setdefault(stream_id, []).append(queue)
        return queue

    def unsubscribe(self, stream_id: str, queue: asyncio.Queue) -> None:
        queues = self._subscribers.get(stream_id, [])
        if queue in queues:
            queues.remove(queue)
        if not queues:
            self._subscribers.pop(stream_id, None)

    async def publish(self, stream_id: str, event_type: str, data: Any, agent_name: str = "") -> None:
        event = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_name": agent_name,
        }
        for queue in self._subscribers.get(stream_id, []):
            await queue.put(event)

    def format_sse(self, event: dict) -> str:
        return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


event_bus = EventBus()
```

---

### 3.17 `src/agent/error_handler.py` - 错误处理

```python
import asyncio

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage


class AgentErrorHandler:
    @staticmethod
    async def handle_context_overflow(
        error: Exception,
        messages: list[BaseMessage],
        compressor,
    ) -> list[BaseMessage]:
        clipped = AgentErrorHandler._clip_tail_tool_messages(messages, keep=3)
        return await compressor.compress(clipped)

    @staticmethod
    def handle_tool_error(error: Exception, tool_call_id: str, tool_name: str = "") -> ToolMessage:
        return ToolMessage(
            content=f"Tool execution failed: {error}",
            tool_call_id=tool_call_id,
            name=tool_name,
        )

    @staticmethod
    def handle_dangling_tool_calls(messages: list[BaseMessage]) -> list[BaseMessage]:
        result = []
        pending_tool_call_ids: set[str] = set()

        for msg in messages:
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    pending_tool_call_ids.add(tc["id"])
            elif isinstance(msg, ToolMessage) and msg.tool_call_id:
                pending_tool_call_ids.discard(msg.tool_call_id)
            result.append(msg)

        for tc_id in pending_tool_call_ids:
            result.append(
                ToolMessage(
                    content="[Tool call cancelled - no response]",
                    tool_call_id=tc_id,
                )
            )
        return result

    @staticmethod
    def _clip_tail_tool_messages(messages: list[BaseMessage], keep: int = 3) -> list[BaseMessage]:
        """Remove oldest ToolMessages and their paired AIMessage (with tool_calls).
        Keeps the most recent `keep` ToolMessages intact."""
        # Find all (AIMessage index, ToolMessage index) pairs
        pairs: list[tuple[int | None, int]] = []
        ai_idx_map: dict[str, int] = {}  # tool_call_id -> AIMessage index

        for i, msg in enumerate(messages):
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    ai_idx_map[tc["id"]] = i
            elif isinstance(msg, ToolMessage) and msg.tool_call_id:
                ai_idx = ai_idx_map.get(msg.tool_call_id)
                pairs.append((ai_idx, i))

        if len(pairs) <= keep:
            return messages

        # Remove oldest pairs, but only ToolMessages (keep AIMessage for tool_calls declaration)
        to_remove: set[int] = set()
        for _, tool_idx in pairs[:-keep]:
            to_remove.add(tool_idx)

        return [m for i, m in enumerate(messages) if i not in to_remove]


class RetryHandler:
    def __init__(self, max_retries: int = 3, backoff_factor: float = 1.5) -> None:
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

    async def execute_with_retry(self, func, *args, **kwargs):
        last_error = None
        for attempt in range(self.max_retries):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.backoff_factor**attempt)
        raise last_error
```

---

### 3.18 `src/agent/checkpoint.py` - 会话持久化

```python
"""Session persistence — stores conversation history per session in SQLite."""

import json
import sqlite3
import uuid
from pathlib import Path

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage


_DB_PATH = Path("memory/sessions.db")


def _get_conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            tool_calls TEXT,
            tool_call_id TEXT,
            name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
    """)
    conn.commit()
    return conn


def _serialize_message(msg: BaseMessage) -> dict:
    entry = {"role": msg.type, "content": msg.content}
    if hasattr(msg, "tool_calls") and msg.tool_calls:
        entry["tool_calls"] = json.dumps(msg.tool_calls, ensure_ascii=False)
    if hasattr(msg, "tool_call_id") and msg.tool_call_id:
        entry["tool_call_id"] = msg.tool_call_id
    if hasattr(msg, "name") and msg.name:
        entry["name"] = msg.name
    return entry


def _deserialize_message(row: tuple) -> BaseMessage:
    role, content, tool_calls_json, tool_call_id, name = row
    if role == "human":
        return HumanMessage(content=content)
    elif role == "ai":
        tool_calls = json.loads(tool_calls_json) if tool_calls_json else []
        return AIMessage(content=content, tool_calls=tool_calls)
    elif role == "tool":
        return ToolMessage(content=content, tool_call_id=tool_call_id or "", name=name or "")
    return HumanMessage(content=content)


def create_session() -> str:
    session_id = str(uuid.uuid4())
    conn = _get_conn()
    conn.execute("INSERT INTO sessions (session_id) VALUES (?)", (session_id,))
    conn.commit()
    conn.close()
    return session_id


def session_exists(session_id: str) -> bool:
    conn = _get_conn()
    row = conn.execute("SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    conn.close()
    return row is not None


def load_history(session_id: str) -> list[BaseMessage]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT role, content, tool_calls, tool_call_id, name FROM messages WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    conn.close()
    return [_deserialize_message(row) for row in rows]


def save_turn(session_id: str, user_message: str, assistant_content: str) -> None:
    conn = _get_conn()
    if not session_exists(session_id):
        conn.execute("INSERT INTO sessions (session_id) VALUES (?)", (session_id,))
    conn.execute(
        "INSERT INTO messages (session_id, role, content) VALUES (?, 'human', ?)",
        (session_id, user_message),
    )
    conn.execute(
        "INSERT INTO messages (session_id, role, content) VALUES (?, 'ai', ?)",
        (session_id, assistant_content),
    )
    conn.execute(
        "UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
        (session_id,),
    )
    conn.commit()
    conn.close()


def list_sessions() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT session_id, created_at, updated_at FROM sessions ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()
    return [{"session_id": r[0], "created_at": r[1], "updated_at": r[2]} for r in rows]


def delete_session(session_id: str) -> None:
    conn = _get_conn()
    conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()
```

---

### 3.19 `src/agent/skills.py` - 技能系统

```python
"""Skill management — loads skill definitions from skills/ directory."""

from pathlib import Path


_SKILLS_DIR = Path("skills")


class Skill:
    def __init__(self, name: str, description: str, content: str) -> None:
        self.name = name
        self.description = description
        self.content = content


def load_skills() -> list[Skill]:
    """Scan skills/ directory for .md files and load them as skills."""
    if not _SKILLS_DIR.exists():
        return []

    skills = []
    for path in sorted(_SKILLS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            continue

        # First line as description (or first non-empty line)
        lines = text.split("\n")
        description = ""
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                description = stripped
                break
            if stripped.startswith("# "):
                description = stripped[2:]
                break

        skills.append(Skill(
            name=path.stem,
            description=description,
            content=text,
        ))
    return skills


def get_skills_prompt() -> str:
    """Generate skills section for system prompt injection."""
    skills = load_skills()
    if not skills:
        return ""

    parts = ["[Available Skills]"]
    for skill in skills:
        parts.append(f"\n## {skill.name}\n{skill.content}")
    return "\n".join(parts)


def list_skills() -> list[dict]:
    """Return skill metadata for API responses."""
    return [{"name": s.name, "description": s.description} for s in load_skills()]
```

---

### 3.20 `src/agent/main.py` - CLI 入口

```python
import argparse
import asyncio

from src.agent.agent import Agent
from src.agent.checkpoint import create_session, load_history, save_turn
from src.agent.config import AgentConfig


async def run_single(agent: Agent, user_input: str, session_id: str | None = None) -> str:
    """Run a single turn. Returns the assistant's response content."""
    if session_id is None:
        session_id = create_session()
    history = load_history(session_id)
    assistant_content = ""
    async for event in agent.run(user_input, history=history):
        if event["type"] == "message":
            print(event["data"])
            assistant_content = event["data"]
        elif event["type"] == "tool_call":
            for tc in event["data"]:
                print(f"  [Tool: {tc['name']}({tc['args']})]")
    if assistant_content:
        save_turn(session_id, user_input, assistant_content)
    return assistant_content


async def run_interactive(agent: Agent, resume_session: str | None = None) -> None:
    session_id = resume_session or create_session()
    print(f"Session: {session_id}")
    print("Agent ready. Type 'quit' to exit.\n")
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_input or user_input.lower() == "quit":
            break
        print()
        await run_single(agent, user_input, session_id)
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="LangGraph Agent v2 CLI")
    parser.add_argument("--input", "-i", type=str, help="Single input to process")
    parser.add_argument("--interactive", action="store_true", help="Interactive mode")
    parser.add_argument("--resume", "-r", type=str, nargs="?", const="__LATEST__", help="Resume session")
    parser.add_argument("--provider", type=str, help="Model provider (openai|anthropic)")
    parser.add_argument("--model", type=str, help="Model name")
    args = parser.parse_args()

    config = AgentConfig()
    if args.provider:
        config.model_provider = args.provider
    if args.model:
        config.model_name = args.model

    agent = Agent(config)

    if args.input:
        asyncio.run(run_single(agent, args.input))
    elif args.interactive:
        asyncio.run(run_interactive(agent, args.resume))
    else:
        print("Use --input 'message' or --interactive")


if __name__ == "__main__":
    main()
```

---

### 3.21 `server.py` - FastAPI 服务器

```python
import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.agent.agent import Agent
from src.agent.checkpoint import create_session, delete_session, list_sessions as db_list_sessions, load_history, save_turn
from src.agent.config import AgentConfig
from src.agent.context.memory import MemoryManager
from src.agent.event_bus import event_bus

config = AgentConfig()
agent: Agent | None = None
memory: MemoryManager | None = None


def get_agent() -> Agent:
    global agent
    if agent is None:
        agent = Agent(config)
    return agent


def get_memory() -> MemoryManager:
    global memory
    if memory is None:
        memory = MemoryManager(config)
    return memory


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="LangGraph Agent v2", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request Models ──────────────────────────────────────────────


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class OrchestrateRequest(BaseModel):
    task: str
    session_id: str | None = None


class MemoryStoreRequest(BaseModel):
    key: str
    content: str
    namespace: str = "default"


class MemoryQueryRequest(BaseModel):
    query: str
    namespace: str = "default"
    top_k: int = 5


# ── Chat ────────────────────────────────────────────────────────


@app.post("/chat")
async def chat(request: ChatRequest):
    session_id = request.session_id or create_session()
    memory_context = get_memory().inject_context(request.message)
    history = load_history(session_id)

    async def stream():
        assistant_content = ""
        async for event in get_agent().run(request.message, memory_context, history):
            event["session_id"] = session_id
            if event["type"] == "message":
                assistant_content = event["data"]
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        if assistant_content:
            save_turn(session_id, request.message, assistant_content)

    return StreamingResponse(stream(), media_type="text/event-stream")


# ── Multi-Agent Orchestration ───────────────────────────────────


@app.post("/api/orchestrate")
async def orchestrate(request: OrchestrateRequest):
    from src.agent.supervisor import create_default_supervisor

    session_id = request.session_id or str(uuid.uuid4())
    supervisor_mgr = create_default_supervisor(config)
    supervisor = supervisor_mgr.build_supervisor()

    async def stream():
        try:
            from langchain_core.messages import HumanMessage

            result = supervisor.astream({"messages": [HumanMessage(content=request.task)]})
            async for chunk in result:
                event = {
                    "type": "update",
                    "data": str(chunk),
                    "session_id": session_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'session_id': session_id}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'data': str(e), 'session_id': session_id}, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


# ── SSE Events ──────────────────────────────────────────────────


@app.get("/api/events/stream/{stream_id}")
async def sse_stream(stream_id: str):
    async def event_generator():
        queue = event_bus.subscribe(stream_id)
        try:
            while True:
                event = await queue.get()
                yield event_bus.format_sse(event)
        except asyncio.CancelledError:
            pass
        finally:
            event_bus.unsubscribe(stream_id, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ── Sessions ────────────────────────────────────────────────────


@app.get("/api/sessions")
async def list_sessions_endpoint():
    return {"sessions": db_list_sessions()}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    history = load_history(session_id)
    if not history:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = [{"type": m.type, "content": m.content} for m in history]
    return {"session_id": session_id, "messages": messages}


@app.delete("/api/sessions/{session_id}")
async def delete_session_endpoint(session_id: str):
    delete_session(session_id)
    return {"status": "ok"}


# ── Skills ──────────────────────────────────────────────────────


@app.get("/api/skills")
async def list_skills_endpoint():
    from src.agent.skills import list_skills
    return {"skills": list_skills()}


# ── Tools ───────────────────────────────────────────────────────


@app.get("/api/tools")
async def list_tools():
    return {
        "tools": [
            {"name": t.name, "description": t.description}
            for t in get_agent().tools
        ]
    }


# ── Memory ──────────────────────────────────────────────────────


@app.post("/api/memory/store")
async def memory_store(request: MemoryStoreRequest):
    get_memory().store(request.key, request.content, request.namespace)
    return {"status": "ok"}


@app.post("/api/memory/query")
async def memory_query(request: MemoryQueryRequest):
    results = get_memory().retrieve(request.query, request.namespace, request.top_k)
    return {"results": results}


@app.get("/api/memory/list/{namespace}")
async def memory_list(namespace: str = "default"):
    return {"memories": get_memory().list_memories(namespace)}


@app.delete("/api/memory/{namespace}/{key}")
async def memory_delete(namespace: str, key: str):
    get_memory().delete(key, namespace)
    return {"status": "ok"}


# ── Health ──────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok", "model": f"{config.model_provider}/{config.model_name}"}


if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (may fail on Windows)")
    args = parser.parse_args()

    uvicorn.run("server:app", host=config.server_host, port=config.server_port, reload=args.reload)
```

---

## 4. 前端实现

### 4.1 `ui/package.json`

```json
{
  "name": "langgraph-agent-v2-ui",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vue-tsc -b && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "@vue-flow/background": "^1.3.0",
    "@vue-flow/controls": "^1.1.0",
    "@vue-flow/core": "^1.30.0",
    "highlight.js": "^11.11.1",
    "katex": "^0.17.0",
    "marked": "^18.0.4",
    "marked-highlight": "^2.2.4",
    "pinia": "^2.1.0",
    "vue": "^3.4.0"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.0.0",
    "typescript": "~5.3.0",
    "vite": "^5.0.0",
    "vue-tsc": "^2.0.0"
  }
}
```

### 4.2 `ui/tsconfig.json`

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "module": "ESNext",
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "preserve",
    "strict": true,
    "noUnusedLocals": false,
    "noUnusedParameters": false,
    "noFallthroughCasesInSwitch": true,
    "paths": {
      "@/*": ["./src/*"]
    }
  },
  "include": ["src/**/*.ts", "src/**/*.vue"]
}
```

### 4.3 `ui/vite.config.ts`

```typescript
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/chat': 'http://localhost:8000',
      '/api': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
})
```

### 4.4 `ui/src/main.ts`

```typescript
import { createPinia } from 'pinia'
import { createApp } from 'vue'
import App from './App.vue'

const app = createApp(App)
app.use(createPinia())
app.mount('#app')
```

### 4.5 `ui/src/env.d.ts`

```typescript
/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}
```

### 4.6 `ui/src/utils/api.ts` - API 工具函数

```typescript
export interface ChatMessage {
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
  toolCalls?: Array<{ name: string; args: Record<string, unknown> }>
  agentName?: string
  thinking?: string
}

export async function* streamChat(message: string, sessionId?: string): AsyncGenerator<Record<string, unknown>> {
  const res = await fetch('/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId }),
  })

  if (!res.ok || !res.body) {
    throw new Error(`HTTP ${res.status}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          yield JSON.parse(line.slice(6))
        } catch {}
      }
    }
  }
}

export async function* streamOrchestrate(task: string, sessionId?: string): AsyncGenerator<Record<string, unknown>> {
  const res = await fetch('/api/orchestrate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task, session_id: sessionId }),
  })

  if (!res.ok || !res.body) {
    throw new Error(`HTTP ${res.status}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          yield JSON.parse(line.slice(6))
        } catch {}
      }
    }
  }
}

export async function listTools(): Promise<Array<{ name: string; description: string }>> {
  const res = await fetch('/api/tools')
  const data = await res.json()
  return data.tools
}

export async function listSessions(): Promise<string[]> {
  const res = await fetch('/api/sessions')
  const data = await res.json()
  return data.sessions
}
```

### 4.7 `ui/src/stores/chat.ts` - Chat Store

```typescript
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { streamChat, type ChatMessage } from '../utils/api'

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  const isLoading = ref(false)
  const streamingActive = ref(false) // true when first event received (thinking/message)
  const sessionId = ref<string | null>(null)

  async function sendMessage(content: string) {
    messages.value.push({ role: 'user', content })
    isLoading.value = true

    let thinkingContent = ''
    let assistantMsg: ChatMessage | null = null

    function ensureAssistantMsg(): ChatMessage {
      if (!assistantMsg) {
        assistantMsg = { role: 'assistant', content: '' }
        messages.value.push(assistantMsg)
        streamingActive.value = true
      }
      return assistantMsg
    }

    try {
      for await (const event of streamChat(content, sessionId.value || undefined)) {
        if (event.session_id) {
          sessionId.value = event.session_id as string
        }

        if (event.type === 'thinking_start') {
          thinkingContent = ''
        } else if (event.type === 'thinking') {
          thinkingContent += event.data as string
          const msg = ensureAssistantMsg()
          msg.thinking = thinkingContent
        } else if (event.type === 'thinking_done') {
          // no-op, thinking content is already on the message
        } else if (event.type === 'tool_call') {
          const msg = ensureAssistantMsg()
          msg.toolCalls = event.data as Array<{ name: string; args: Record<string, unknown> }>
        } else if (event.type === 'message') {
          const msg = ensureAssistantMsg()
          msg.content = event.data as string
        } else if (event.type === 'error') {
          messages.value.push({ role: 'system', content: `Error: ${event.data}` })
        }
      }
    } catch (e: any) {
      messages.value.push({ role: 'system', content: `Connection error: ${e.message}` })
    } finally {
      isLoading.value = false
      streamingActive.value = false
    }
  }

  function clearMessages() {
    messages.value = []
    sessionId.value = null
  }

  return { messages, isLoading, streamingActive, sessionId, sendMessage, clearMessages }
})
```

### 4.8 `ui/src/stores/agents.ts` - Agents Store

```typescript
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { listTools } from '../utils/api'

export const useAgentsStore = defineStore('agents', () => {
  const tools = ref<Array<{ name: string; description: string }>>([])
  const isLoading = ref(false)

  async function fetchTools() {
    isLoading.value = true
    try {
      tools.value = await listTools()
    } finally {
      isLoading.value = false
    }
  }

  return { tools, isLoading, fetchTools }
})
```

### 4.9 `ui/src/App.vue` - 主应用组件

```vue
<script setup lang="ts">
import { ref } from 'vue'
import AgentsTab from './components/AgentsTab.vue'
import ChatTab from './components/ChatTab.vue'

const currentTab = ref<'chat' | 'agents'>('chat')
</script>

<template>
  <div class="app">
    <div class="bg-orbs">
      <div class="orb orb-1"></div>
      <div class="orb orb-2"></div>
      <div class="orb orb-3"></div>
    </div>
    <header class="header">
      <h1>LangGraph Agent v2</h1>
      <nav class="nav">
        <button :class="{ active: currentTab === 'chat' }" @click="currentTab = 'chat'">Chat</button>
        <button :class="{ active: currentTab === 'agents' }" @click="currentTab = 'agents'">Agents</button>
      </nav>
    </header>
    <main class="main">
      <ChatTab v-if="currentTab === 'chat'" />
      <AgentsTab v-if="currentTab === 'agents'" />
    </main>
  </div>
</template>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: #0a0a1a;
  color: rgba(255, 255, 255, 0.9);
  overflow: hidden;
}

.app {
  height: 100vh;
  display: flex;
  flex-direction: column;
  position: relative;
}

/* ── Animated background orbs ──────────────────────────────────── */
.bg-orbs {
  position: fixed;
  inset: 0;
  z-index: 0;
  overflow: hidden;
  pointer-events: none;
}

.orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.5;
  animation: float 20s ease-in-out infinite;
}

.orb-1 {
  width: 400px; height: 400px;
  background: radial-gradient(circle, #6366f1, #8b5cf6);
  top: -10%; left: -5%;
  animation-duration: 22s;
}

.orb-2 {
  width: 350px; height: 350px;
  background: radial-gradient(circle, #06b6d4, #3b82f6);
  bottom: -10%; right: -5%;
  animation-duration: 18s;
  animation-delay: -5s;
}

.orb-3 {
  width: 300px; height: 300px;
  background: radial-gradient(circle, #ec4899, #f43f5e);
  top: 50%; left: 50%;
  transform: translate(-50%, -50%);
  animation-duration: 25s;
  animation-delay: -10s;
}

@keyframes float {
  0%, 100% { transform: translate(0, 0) scale(1); }
  25% { transform: translate(30px, -40px) scale(1.05); }
  50% { transform: translate(-20px, 20px) scale(0.95); }
  75% { transform: translate(15px, 35px) scale(1.02); }
}

/* ── Glass header ──────────────────────────────────────────────── */
.header {
  position: relative;
  z-index: 10;
  padding: 14px 24px;
  display: flex;
  align-items: center;
  gap: 24px;
  background: rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.header h1 {
  font-size: 18px;
  font-weight: 600;
  background: linear-gradient(135deg, #c7d2fe, #a5b4fc);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.nav { display: flex; gap: 4px; }

.nav button {
  padding: 6px 16px;
  border: 1px solid transparent;
  background: transparent;
  color: rgba(255, 255, 255, 0.5);
  cursor: pointer;
  border-radius: 8px;
  font-size: 14px;
  transition: all 0.2s;
}

.nav button:hover {
  color: rgba(255, 255, 255, 0.8);
  background: rgba(255, 255, 255, 0.05);
}

.nav button.active {
  background: rgba(255, 255, 255, 0.1);
  border-color: rgba(255, 255, 255, 0.12);
  color: #fff;
  backdrop-filter: blur(12px);
}

.main { flex: 1; overflow: hidden; position: relative; z-index: 1; }

/* ── Scrollbar ─────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.15); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: rgba(255, 255, 255, 0.25); }
</style>
```

**设计特点**:
- 深色主题 (#0a0a1a)
- 毛玻璃效果 (backdrop-filter: blur)
- 动态背景光球动画
- 渐变文字标题

### 4.10 `ui/src/components/ChatTab.vue` - 聊天组件

```vue
<script setup lang="ts">
import { nextTick, ref, watch, computed } from 'vue'
import { Marked } from 'marked'
import { markedHighlight } from 'marked-highlight'
import hljs from 'highlight.js'
import katex from 'katex'
import { useChatStore } from '../stores/chat'

const marked = new Marked(
  { breaks: true, gfm: true },
  markedHighlight({
    langPrefix: 'hljs language-',
    highlight(code: string, lang: string) {
      if (lang && hljs.getLanguage(lang)) {
        return hljs.highlight(code, { language: lang }).value
      }
      return hljs.highlightAuto(code).value
    },
  }),
)

function renderMath(tex: string, displayMode: boolean): string {
  try {
    return katex.renderToString(tex, { displayMode, throwOnError: false, trust: true })
  } catch {
    return displayMode ? `<pre class="math-block">${tex}</pre>` : `<code>${tex}</code>`
  }
}

function renderMd(text: string): string {
  // Extract and protect LaTeX blocks before markdown parsing
  const blocks: string[] = []
  let processed = text.replace(/\$\$([\s\S]*?)\$\$/g, (_m, tex) => {
    // Skip if contains Chinese characters (KaTeX can't handle them)
    if (/[一-鿿]/.test(tex)) return _m
    const placeholder = `%%MATH_BLOCK_${blocks.length}%%`
    blocks.push(renderMath(tex.trim(), true))
    return placeholder
  })
  // Inline math: $...$  (but not $$)
  processed = processed.replace(/\$([^$\n]+?)\$/g, (_m, tex) => {
    // Skip if contains Chinese characters
    if (/[一-鿿]/.test(tex)) return _m
    const placeholder = `%%MATH_INLINE_${blocks.length}%%`
    blocks.push(renderMath(tex.trim(), false))
    return placeholder
  })

  let html = marked.parse(processed) as string

  // Restore math blocks
  blocks.forEach((block, i) => {
    html = html.replace(`%%MATH_BLOCK_${i}%%`, block)
    html = html.replace(`%%MATH_INLINE_${i}%%`, block)
  })
  return html
}

const chat = useChatStore()
const input = ref('')
const messagesRef = ref<HTMLElement | null>(null)
const thinkingExpanded = ref<Set<number>>(new Set())
const thinkingLive = ref<Set<number>>(new Set()) // indices with active thinking animation

function formatArgs(args: Record<string, unknown>): string {
  const entries = Object.entries(args)
  if (entries.length === 0) return ''
  return entries.map(([k, v]) => {
    const val = typeof v === 'string' ? v : JSON.stringify(v)
    const display = val.length > 120 ? val.slice(0, 120) + '...' : val
    return `${k}: ${display}`
  }).join(', ')
}

function toggleThinking(index: number) {
  if (thinkingExpanded.value.has(index)) {
    thinkingExpanded.value.delete(index)
  } else {
    thinkingExpanded.value.add(index)
  }
}

// Auto-expand thinking when it starts, collapse when done
watch(() => chat.messages.map(m => m.thinking), () => {
  const msgs = chat.messages
  for (let i = 0; i < msgs.length; i++) {
    if (msgs[i].thinking && !thinkingExpanded.value.has(i)) {
      thinkingExpanded.value.add(i)
      thinkingLive.value.add(i)
    }
  }
}, { deep: true })

// When loading stops, mark all thinking as done
watch(() => chat.isLoading, (loading) => {
  if (!loading) {
    thinkingLive.value.clear()
  }
})

async function send() {
  const msg = input.value.trim()
  if (!msg || chat.isLoading) return
  input.value = ''
  await chat.sendMessage(msg)
}

watch(() => chat.messages.length, async () => {
  await nextTick()
  messagesRef.value?.scrollTo({ top: messagesRef.value.scrollHeight, behavior: 'smooth' })
})
</script>

<template>
  <div class="chat-tab">
    <div class="messages" ref="messagesRef">
      <div v-if="chat.messages.length === 0" class="empty">
        <div class="empty-icon">✦</div>
        <p>Start a conversation with the agent</p>
      </div>
      <template v-for="(msg, i) in chat.messages" :key="i">
      <div v-if="msg.role !== 'assistant' || msg.content || msg.thinking || msg.toolCalls?.length" :class="['msg', msg.role]">
        <div class="msg-role">{{ msg.role }}</div>
        <div v-if="msg.thinking" class="thinking-block" :class="{ 'is-live': thinkingLive.has(i) }">
          <button class="thinking-toggle" @click="toggleThinking(i)">
            <span class="thinking-icon">{{ thinkingExpanded.has(i) ? '▾' : '▸' }}</span>
            <span v-if="thinkingLive.has(i)" class="thinking-label">
              Thinking<span class="thinking-dots"><span>.</span><span>.</span><span>.</span></span>
            </span>
            <span v-else>Thinking process</span>
          </button>
          <Transition name="thinking-expand">
            <div v-if="thinkingExpanded.has(i)" class="thinking-content">
              {{ msg.thinking }}<span v-if="thinkingLive.has(i)" class="cursor-blink">|</span>
            </div>
          </Transition>
        </div>
        <div class="msg-content md-body" v-if="msg.content" v-html="renderMd(msg.content)"></div>
        <div v-if="msg.toolCalls?.length" class="tool-calls">
          <div v-for="(tc, j) in msg.toolCalls" :key="j" class="tool-call">
            <div class="tool-header">
              <span class="tool-icon">&#9881;</span>
              <span class="tool-name">{{ tc.name }}</span>
            </div>
            <div v-if="tc.name === 'execute_code' && tc.args.code" class="tool-code-wrap">
              <details>
                <summary>Show code</summary>
                <pre class="tool-code"><code>{{ tc.args.code }}</code></pre>
              </details>
            </div>
            <div v-else class="tool-args">{{ formatArgs(tc.args) }}</div>
          </div>
        </div>
      </div>
      </template>
      <div v-if="chat.isLoading && !chat.streamingActive" class="msg assistant loading">
        <div class="msg-role">assistant</div>
        <div class="msg-content">
          <span class="dot"></span><span class="dot"></span><span class="dot"></span>
        </div>
      </div>
    </div>
    <form class="input-bar" @submit.prevent="send">
      <input v-model="input" placeholder="Type a message..." :disabled="chat.isLoading" />
      <button type="submit" :disabled="chat.isLoading || !input.trim()">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M22 2L11 13" /><path d="M22 2L15 22L11 13L2 9L22 2Z" />
        </svg>
      </button>
    </form>
  </div>
</template>

<style>
/* Global styles for rendered content (not scoped) */
@import 'highlight.js/styles/github-dark.css';
@import 'katex/dist/katex.min.css';
</style>

<style scoped>
.chat-tab {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 12px;
}

.empty-icon {
  font-size: 40px;
  opacity: 0.3;
}

.empty p {
  color: rgba(255, 255, 255, 0.3);
  font-size: 15px;
}

/* ── Message bubbles ───────────────────────────────────────────── */
.msg {
  padding: 14px 18px;
  border-radius: 16px;
  max-width: 75%;
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  animation: fadeIn 0.25s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

.msg.user {
  background: rgba(99, 102, 241, 0.2);
  border-color: rgba(99, 102, 241, 0.25);
  align-self: flex-end;
  border-bottom-right-radius: 4px;
}

.msg.assistant {
  background: rgba(255, 255, 255, 0.06);
  border-color: rgba(255, 255, 255, 0.1);
  align-self: flex-start;
  border-bottom-left-radius: 4px;
}

.msg.system {
  background: rgba(239, 68, 68, 0.12);
  border-color: rgba(239, 68, 68, 0.2);
  align-self: center;
  font-size: 13px;
  text-align: center;
}

.msg-role {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.4);
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.msg-content {
  line-height: 1.6;
  color: rgba(255, 255, 255, 0.88);
  animation: contentFadeIn 0.4s ease-out;
}

@keyframes contentFadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ── Markdown rendered content ───────────────────────────────── */
.md-body :deep(h1),
.md-body :deep(h2),
.md-body :deep(h3),
.md-body :deep(h4) {
  margin: 16px 0 8px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.95);
}
.md-body :deep(h1) { font-size: 1.4em; }
.md-body :deep(h2) { font-size: 1.2em; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 4px; }
.md-body :deep(h3) { font-size: 1.05em; }

.md-body :deep(p) { margin: 6px 0; }

.md-body :deep(ul),
.md-body :deep(ol) {
  margin: 6px 0;
  padding-left: 20px;
}

.md-body :deep(blockquote) {
  margin: 8px 0;
  padding: 4px 12px;
  border-left: 3px solid rgba(99, 102, 241, 0.5);
  background: rgba(99, 102, 241, 0.06);
  border-radius: 0 6px 6px 0;
  color: rgba(255, 255, 255, 0.7);
}

.md-body :deep(code) {
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 0.9em;
  background: rgba(0, 0, 0, 0.3);
  padding: 1px 5px;
  border-radius: 4px;
  color: #e0b0ff;
}

.md-body :deep(pre) {
  margin: 8px 0;
  padding: 12px;
  background: rgba(0, 0, 0, 0.35);
  border-radius: 8px;
  overflow-x: auto;
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.md-body :deep(pre code) {
  background: none;
  padding: 0;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.85);
}

.md-body :deep(table) {
  margin: 8px 0;
  border-collapse: collapse;
  width: 100%;
  font-size: 13px;
}

.md-body :deep(th),
.md-body :deep(td) {
  padding: 6px 10px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  text-align: left;
}

.md-body :deep(th) {
  background: rgba(255, 255, 255, 0.06);
  font-weight: 600;
}

.md-body :deep(hr) {
  margin: 12px 0;
  border: none;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.md-body :deep(a) {
  color: #818cf8;
  text-decoration: none;
}
.md-body :deep(a:hover) {
  text-decoration: underline;
}

.md-body :deep(strong) {
  color: rgba(255, 255, 255, 0.95);
  font-weight: 600;
}

/* KaTeX display math */
.md-body :deep(.katex-display) {
  margin: 8px 0;
  padding: 8px 12px;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 6px;
  overflow-x: auto;
}

.md-body :deep(.katex) {
  font-size: 1.05em;
  color: rgba(255, 255, 255, 0.9);
}

/* ── Tool calls ────────────────────────────────────────────────── */
.tool-calls {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.tool-call {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 8px;
  overflow: hidden;
  font-size: 12px;
}

.tool-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  background: rgba(99, 102, 241, 0.06);
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
}

.tool-icon {
  color: rgba(129, 140, 248, 0.6);
  font-size: 11px;
}

.tool-name {
  color: #818cf8;
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-weight: 500;
}

.tool-args {
  padding: 8px 12px;
  color: rgba(255, 255, 255, 0.4);
  font-family: 'SF Mono', 'Fira Code', monospace;
  line-height: 1.5;
  word-break: break-all;
}

.tool-code-wrap details {
  cursor: pointer;
}

.tool-code-wrap summary {
  padding: 6px 12px;
  color: rgba(255, 255, 255, 0.4);
  font-size: 11px;
  user-select: none;
}

.tool-code-wrap summary:hover {
  color: rgba(255, 255, 255, 0.6);
}

.tool-code {
  margin: 0;
  padding: 10px 12px;
  background: rgba(0, 0, 0, 0.3);
  font-size: 12px;
  line-height: 1.5;
  color: rgba(255, 255, 255, 0.7);
  overflow-x: auto;
  max-height: 200px;
}

/* ── Thinking block ──────────────────────────────────────────── */
.thinking-block {
  margin-bottom: 10px;
  border: 1px solid rgba(139, 92, 246, 0.2);
  border-radius: 8px;
  overflow: hidden;
  transition: border-color 0.3s;
}

.thinking-block.is-live {
  border-color: rgba(139, 92, 246, 0.45);
  box-shadow: 0 0 12px rgba(139, 92, 246, 0.1);
}

.thinking-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 8px 12px;
  background: rgba(139, 92, 246, 0.08);
  border: none;
  color: rgba(139, 92, 246, 0.8);
  font-size: 12px;
  cursor: pointer;
  transition: background 0.2s;
}

.thinking-toggle:hover {
  background: rgba(139, 92, 246, 0.15);
}

.thinking-icon {
  font-size: 10px;
  width: 14px;
  text-align: center;
}

.thinking-label {
  display: inline-flex;
  align-items: center;
}

.thinking-dots span {
  animation: dotPulse 1.4s ease-in-out infinite;
}
.thinking-dots span:nth-child(2) { animation-delay: 0.2s; }
.thinking-dots span:nth-child(3) { animation-delay: 0.4s; }

@keyframes dotPulse {
  0%, 60%, 100% { opacity: 0.2; }
  30% { opacity: 1; }
}

.thinking-content {
  padding: 12px;
  font-size: 13px;
  line-height: 1.6;
  color: rgba(255, 255, 255, 0.5);
  white-space: pre-wrap;
  max-height: 400px;
  overflow-y: auto;
  background: rgba(0, 0, 0, 0.15);
}

.cursor-blink {
  animation: blink 0.8s step-end infinite;
  color: rgba(139, 92, 246, 0.8);
  font-weight: bold;
}

@keyframes blink {
  50% { opacity: 0; }
}

/* Thinking expand/collapse transition */
.thinking-expand-enter-active,
.thinking-expand-leave-active {
  transition: all 0.3s ease;
  overflow: hidden;
}

.thinking-expand-enter-from,
.thinking-expand-leave-to {
  opacity: 0;
  max-height: 0;
  padding-top: 0;
  padding-bottom: 0;
}

.thinking-expand-enter-to,
.thinking-expand-leave-from {
  opacity: 1;
  max-height: 400px;
}

/* ── Loading dots ──────────────────────────────────────────────── */
.loading .msg-content {
  display: flex;
  gap: 4px;
  padding: 4px 0;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.4);
  animation: bounce 1.4s ease-in-out infinite;
}

.dot:nth-child(2) { animation-delay: 0.2s; }
.dot:nth-child(3) { animation-delay: 0.4s; }

@keyframes bounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}

/* ── Input bar ─────────────────────────────────────────────────── */
.input-bar {
  padding: 16px 24px;
  display: flex;
  gap: 10px;
  background: rgba(255, 255, 255, 0.03);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.input-bar input {
  flex: 1;
  padding: 12px 16px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  color: rgba(255, 255, 255, 0.9);
  font-size: 14px;
  outline: none;
  transition: all 0.2s;
}

.input-bar input::placeholder {
  color: rgba(255, 255, 255, 0.25);
}

.input-bar input:focus {
  border-color: rgba(99, 102, 241, 0.5);
  background: rgba(255, 255, 255, 0.08);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.input-bar button {
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(99, 102, 241, 0.25);
  border: 1px solid rgba(99, 102, 241, 0.3);
  border-radius: 12px;
  color: #c7d2fe;
  cursor: pointer;
  transition: all 0.2s;
  flex-shrink: 0;
}

.input-bar button:hover:not(:disabled) {
  background: rgba(99, 102, 241, 0.4);
  border-color: rgba(99, 102, 241, 0.5);
  transform: scale(1.05);
}

.input-bar button:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}
</style>
```

**功能特点**:
- Markdown 渲染 (marked + highlight.js)
- LaTeX 数学公式 (KaTeX)
- Thinking 过程可折叠/展开
- 代码块语法高亮
- 工具调用展示

### 4.11 `ui/src/components/AgentsTab.vue` - 工具列表组件

```vue
<script setup lang="ts">
import { onMounted } from 'vue'
import { useAgentsStore } from '../stores/agents'

const store = useAgentsStore()

onMounted(() => {
  store.fetchTools()
})
</script>

<template>
  <div class="agents-tab">
    <h2>Available Tools</h2>
    <div class="tools-list">
      <div v-for="tool in store.tools" :key="tool.name" class="tool-card">
        <div class="tool-icon">⚙</div>
        <h3>{{ tool.name }}</h3>
        <p>{{ tool.description }}</p>
      </div>
      <div v-if="store.tools.length === 0 && !store.isLoading" class="empty">
        No tools available. Make sure the server is running.
      </div>
    </div>
  </div>
</template>

<style scoped>
.agents-tab {
  padding: 28px;
  overflow-y: auto;
  height: 100%;
}

.agents-tab h2 {
  margin-bottom: 20px;
  font-size: 16px;
  color: rgba(255, 255, 255, 0.5);
  letter-spacing: 0.5px;
}

.tools-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}

.tool-card {
  background: rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 16px;
  padding: 20px;
  transition: all 0.25s;
}

.tool-card:hover {
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.15);
  transform: translateY(-2px);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
}

.tool-icon {
  font-size: 24px;
  margin-bottom: 12px;
  opacity: 0.6;
}

.tool-card h3 {
  font-size: 14px;
  color: #818cf8;
  margin-bottom: 8px;
  font-family: 'SF Mono', 'Fira Code', monospace;
}

.tool-card p {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.5);
  line-height: 1.5;
}

.empty {
  color: rgba(255, 255, 255, 0.3);
  text-align: center;
  padding: 60px;
  grid-column: 1 / -1;
}
</style>
```

---

## 5. 数据库设计

### 5.1 会话数据库 (memory/sessions.db)

**sessions 表**:
```sql
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

**messages 表**:
```sql
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,          -- 'human', 'ai', 'tool'
    content TEXT NOT NULL,
    tool_calls TEXT,             -- JSON string of tool calls
    tool_call_id TEXT,
    name TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
)
```

### 5.2 记忆数据库 (memory/agent.db)

**memories 表**:
```sql
CREATE TABLE memories (
    id TEXT PRIMARY KEY,         -- UUID
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,    -- ISO format
    updated_at TEXT NOT NULL     -- ISO format
)

CREATE INDEX idx_namespace ON memories(namespace)
```

### 5.3 向量数据库 (memory/chroma/)

使用 ChromaDB 持久化存储，每个 namespace 对应一个 collection。

---

## 6. API 接口

### 6.1 聊天接口

**POST /chat**
- 请求体: `{ "message": "string", "session_id": "string|null" }`
- 响应: SSE 流，事件格式 `data: {"type": "string", "data": "any", "session_id": "string"}\n\n`
- 事件类型:
  - `thinking_start`: 思考开始
  - `thinking`: 思考内容片段
  - `thinking_done`: 思考结束
  - `tool_call`: 工具调用
  - `message`: 最终回复
  - `done`: 完成
  - `error`: 错误

### 6.2 多 Agent 编排

**POST /api/orchestrate**
- 请求体: `{ "task": "string", "session_id": "string|null" }`
- 响应: SSE 流

### 6.3 会话管理

- `GET /api/sessions` - 列出所有会话
- `GET /api/sessions/{session_id}` - 获取会话历史
- `DELETE /api/sessions/{session_id}` - 删除会话

### 6.4 技能管理

- `GET /api/skills` - 列出所有技能

### 6.5 工具管理

- `GET /api/tools` - 列出所有工具

### 6.6 记忆管理

- `POST /api/memory/store` - 存储记忆
- `POST /api/memory/query` - 语义搜索
- `GET /api/memory/list/{namespace}` - 列出记忆
- `DELETE /api/memory/{namespace}/{key}` - 删除记忆

### 6.7 健康检查

- `GET /health` - 返回 `{"status": "ok", "model": "provider/name"}`

---

## 7. 启动命令

```bash
# 后端
pip install -e .
python server.py

# 前端
cd ui
npm install
npm run dev

# CLI
python -m src.agent.main --input "your message"
python -m src.agent.main --interactive
```

---

## 8. 关键设计决策

1. **配置管理**: 使用 `Field(alias=...)` 支持混合环境变量前缀
2. **上下文压缩**: token 数超过阈值时自动压缩，保留最近 5 条消息
3. **记忆系统**: SQLite (元数据) + ChromaDB (向量) 双写
4. **流式响应**: 使用原始 OpenAI 客户端支持 `reasoning_content`
5. **工具结果截断**: 防止大输出撑爆上下文
6. **技能系统**: 从 `skills/` 目录加载 `.md` 文件注入系统提示词

---

## 9. 已知问题与设计规约

### 9.1 前端规约

#### Thinking 动画 - 无逐字效果

**现状**: Thinking 内容通过 `{{ msg.thinking }}` 直接渲染，没有 typewriter 逐字效果。

**实现方式**:
- `thinkingLive` ref 追踪活跃的 thinking 状态
- `is-live` class 添加紫色发光边框
- `thinking-dots` 动画显示 "Thinking..."
- `cursor-blink` 光标闪烁效果

**问题**: 如果后端数据来得快，thinking 内容会一次性全部渲染完毕，动画效果几乎不可见。

**代码位置**: `ui/src/components/ChatTab.vue:124-136`
```vue
<div v-if="msg.thinking" class="thinking-block" :class="{ 'is-live': thinkingLive.has(i) }">
  <button class="thinking-toggle" @click="toggleThinking(i)">
    <span class="thinking-icon">{{ thinkingExpanded.has(i) ? '▾' : '▸' }}</span>
    <span v-if="thinkingLive.has(i)" class="thinking-label">
      Thinking<span class="thinking-dots"><span>.</span><span>.</span><span>.</span></span>
    </span>
    <span v-else>Thinking process</span>
  </button>
  <Transition name="thinking-expand">
    <div v-if="thinkingExpanded.has(i)" class="thinking-content">
      {{ msg.thinking }}<span v-if="thinkingLive.has(i)" class="cursor-blink">|</span>
    </div>
  </Transition>
</div>
```

#### Assistant 空消息 - 边界情况未完全处理

**现状**: 第122行条件判断正确过滤空消息，但存在边界情况。

**问题**: 如果 `thinking_start` 事件后 thinking 内容为空（直接 `thinking_done`），`ensureAssistantMsg()` 不会被调用，导致：
1. Assistant 消息未创建
2. Loading 状态持续到 `message` 事件到来

**事件流时序**:
```
thinking_start → (无 thinking 事件) → thinking_done → _response → message
                                      ↑
                                      此时 assistantMsg 还未创建
```

**代码位置**: `ui/src/stores/chat.ts:33-39`
```typescript
if (event.type === 'thinking_start') {
  thinkingContent = ''  // 未创建 assistant 消息
} else if (event.type === 'thinking') {
  thinkingContent += event.data as string
  const msg = ensureAssistantMsg()  // 只有这里才创建
  msg.thinking = thinkingContent
}
```

**修复建议**: 在 `thinking_start` 事件时立即调用 `ensureAssistantMsg()`。

#### LaTeX Unicode 字符处理 - 已解决

**现状**: `renderMd` 函数中包含中文字符检查，跳过包含中文的数学公式。

**实现**: 使用正则 `/[一-鿿]/` 检测中文字符，匹配则跳过 KaTeX 渲染。

**代码位置**: `ui/src/components/ChatTab.vue:35-36`
```typescript
// Skip if contains Chinese characters (KaTeX can't handle them)
if (/[一-鿿]/.test(tex)) return _m
```

---

### 9.2 后端规约

#### `execute_code` 工具 - args_schema 可能为空

**现状**: LangChain `@tool` 装饰器从函数签名自动生成 schema，但 `_stream_raw` 构建 tools_spec 时有 fallback。

**问题**: 如果 `args_schema` 为 None，会 fallback 到空 schema `{"type": "object", "properties": {}}`，可能导致 LLM 无法正确调用工具。

**代码位置**: `src/agent/agent.py:110-114`
```python
tools_spec = [
    {
        "type": "function",
        "function": {
            "name": t.name,
            "description": t.description or "",
            "parameters": t.args_schema.schema() if hasattr(t, "args_schema") and t.args_schema else {"type": "object", "properties": {}},
        },
    }
    for t in self.tools
]
```

**风险**: 低。LangChain `@tool` 装饰器通常会正确生成 schema。

#### Tool Call ID 空值处理

**现状**: `_stream_raw` 中解析 tool_calls 时，如果 `tc.id` 为空字符串会被跳过。

**问题**: 某些 OpenAI 兼容 API 可能返回空 id，导致 tool_call_id 为空。

**代码位置**: `src/agent/agent.py:162-163`
```python
if tc.id:
    entry["id"] = tc.id
```

**风险**: 低。标准 OpenAI API 通常返回有效 id。

#### Memory 双写无事务保证

**现状**: `MemoryManager.store()` 先写 SQLite，再写 ChromaDB，无事务包装。

**问题**: 如果 ChromaDB 写入失败，数据不一致（SQLite 有，ChromaDB 无），但不会抛异常。

**代码位置**: `src/agent/context/memory.py:33-53`
```python
def store(self, key: str, content: str, namespace: str = "default") -> None:
    # SQLite 写入
    self.db.execute(...)
    self.db.commit()

    # ChromaDB 写入（无 try-catch）
    collection = self.chroma.get_or_create_collection(namespace)
    collection.upsert(ids=[doc_id], documents=[content], metadatas=[{"key": key}])
```

**风险**: 中。ChromaDB 写入失败时数据不一致，但 `retrieve()` 会 fallback 到空列表。

**修复建议**: 添加 try-catch 包装 ChromaDB 操作，或在 SQLite 中记录同步状态。

#### Context 压缩 - 基本正确

**现状**: 
- `should_compress()`: token 数 > max_tokens * threshold 时触发
- `compress()`: 保留最近 5 条消息，返回 `(summary_text, recent_messages)`
- 必须始终只有一个 SystemMessage

**规约**: 压缩后调用方必须将 summary 合并到 SystemMessage，不能有多个 SystemMessage。

**代码位置**: `src/agent/context/compression.py:13-36`

#### 事件流规约

**SSE 事件格式**: `data: {"type": "string", "data": "any", "session_id": "string"}\n\n`

**事件类型**:
| 类型             | 说明         | 触发时机                     |
| ---------------- | ------------ | ---------------------------- |
| `thinking_start` | 思考开始     | 检测到 reasoning_content     |
| `thinking`       | 思考内容片段 | 每个 reasoning_content delta |
| `thinking_done`  | 思考结束     | 流结束                       |
| `tool_call`      | 工具调用     | LLM 返回 tool_calls          |
| `message`        | 最终回复     | LLM 返回 content             |
| `done`           | 完成         | run() 结束                   |
| `error`          | 错误         | 异常时                       |

**规约**: `_response` 类型是内部类型，不会暴露给前端。

---

### 9.3 需要修复的问题

| 优先级 | 问题                            | 位置         | 修复建议                                      |
| ------ | ------------------------------- | ------------ | --------------------------------------------- |
| P1     | Thinking 无逐字效果             | ChatTab.vue  | 添加 typewriter 动画或缓冲渲染                |
| P1     | thinking_start 未创建 assistant | chat.ts:33   | 在 thinking_start 时调用 ensureAssistantMsg() |
| P2     | Memory 双写无事务               | memory.py:33 | 添加 try-catch 或事务包装                     |
| P3     | tool_call id 空值               | agent.py:162 | 添加 id 有效性检查                            |
| P3     | args_schema 空 fallback         | agent.py:110 | 添加 schema 验证                              |