"""Tools — dynamically loaded from config/tools.json."""

import importlib
import logging

logger = logging.getLogger(__name__)


def _load_tools_from_config():
    """Load tools dynamically from config/tools.json."""
    from src.agent.config_manager import get_config_manager

    cm = get_config_manager()
    tools_config = cm.get_tools()
    tools = []

    for name, cfg in tools_config.items():
        try:
            mod = importlib.import_module(cfg["module"])
            tool_func = getattr(mod, cfg["func"])
            tools.append(tool_func)
            logger.debug("[Tools] loaded: %s from %s", name, cfg["module"])
        except Exception as e:
            logger.warning("[Tools] failed to load %s: %s", name, e)

    return tools


def get_tools_config():
    """Get tools configuration dict."""
    from src.agent.config_manager import get_config_manager
    return get_config_manager().get_tools()


TOOLS = _load_tools_from_config()

__all__ = ["TOOLS", "get_tools_config"]
