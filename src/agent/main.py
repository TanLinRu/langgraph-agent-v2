import argparse
import asyncio

from src.agent.agent import Agent
from src.agent.config import AgentConfig
from src.agent.db import create_session, load_history, save_turn


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
        config.agent_model_provider = args.provider
    if args.model:
        config.agent_model_name = args.model

    agent = Agent(config)

    if args.input:
        asyncio.run(run_single(agent, args.input))
    elif args.interactive:
        asyncio.run(run_interactive(agent, args.resume))
    else:
        print("Use --input 'message' or --interactive")


if __name__ == "__main__":
    main()
