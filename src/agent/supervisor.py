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
