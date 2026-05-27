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

        system_msg = _build_system(memory_ctx)
        messages = [system_msg] + list(existing)

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
