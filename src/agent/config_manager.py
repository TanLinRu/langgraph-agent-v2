"""Configuration manager — loads agent/tool/skill/CLI config from JSON files with hot reload support."""

import json
import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


class ConfigManager:
    """Manages JSON-based configuration with file watching and hot reload."""

    def __init__(self, config_dir: Path | None = None):
        self.config_dir = config_dir or CONFIG_DIR
        self._cache: dict[str, dict] = {}
        self._mtimes: dict[str, float] = {}
        self._lock = threading.Lock()
        self._watch_thread: threading.Thread | None = None
        self._watching = False

        # Load all configs on init
        self._load_all()

    def _load_all(self):
        """Load all JSON config files."""
        for filename in ["agents.json", "tools.json", "skills.json", "acp_agents.json"]:
            self._load_file(filename)

    def _load_file(self, filename: str) -> dict:
        """Load a single JSON config file, using cache if file hasn't changed."""
        filepath = self.config_dir / filename
        if not filepath.exists():
            logger.warning("[ConfigManager] config file not found: %s", filepath)
            return {}

        try:
            mtime = filepath.stat().st_mtime
        except OSError:
            return {}

        with self._lock:
            # Check if file hasn't changed
            if filename in self._mtimes and self._mtimes[filename] == mtime:
                return self._cache.get(filename, {})

            # Load and parse
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._cache[filename] = data
                self._mtimes[filename] = mtime
                logger.info("[ConfigManager] loaded %s (%d bytes)", filename, filepath.stat().st_size)
                return data
            except (json.JSONDecodeError, OSError) as e:
                logger.error("[ConfigManager] failed to load %s: %s", filename, e)
                return self._cache.get(filename, {})

    def _save_file(self, filename: str, data: dict):
        """Save data to a JSON config file."""
        filepath = self.config_dir / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # Update cache
            with self._lock:
                self._cache[filename] = data
                self._mtimes[filename] = filepath.stat().st_mtime
            logger.info("[ConfigManager] saved %s", filename)
        except OSError as e:
            logger.error("[ConfigManager] failed to save %s: %s", filename, e)

    def start_watching(self, interval: float = 5.0):
        """Start a background thread that checks for file changes."""
        if self._watching:
            return
        self._watching = True
        self._watch_thread = threading.Thread(target=self._watch_loop, args=(interval,), daemon=True)
        self._watch_thread.start()
        logger.info("[ConfigManager] started config watcher (interval=%.1fs)", interval)

    def stop_watching(self):
        """Stop the background file watcher."""
        self._watching = False
        if self._watch_thread:
            self._watch_thread.join(timeout=10)
            self._watch_thread = None

    def _watch_loop(self, interval: float):
        """Background loop that checks for file changes."""
        while self._watching:
            time.sleep(interval)
            self._load_all()

    # ── Agents ──────────────────────────────────────────────────

    def get_agents(self) -> dict[str, dict]:
        """Get all agent configurations."""
        data = self._load_file("agents.json")
        return data.get("agents", {})

    def get_agent(self, agent_id: str) -> dict | None:
        """Get a single agent configuration."""
        agents = self.get_agents()
        return agents.get(agent_id)

    def save_agent(self, agent_id: str, agent_data: dict):
        """Save/update an agent configuration."""
        data = self._load_file("agents.json")
        if "agents" not in data:
            data["agents"] = {}
        data["agents"][agent_id] = agent_data
        self._save_file("agents.json", data)

    def delete_agent(self, agent_id: str):
        """Delete an agent configuration."""
        data = self._load_file("agents.json")
        if "agents" in data and agent_id in data["agents"]:
            del data["agents"][agent_id]
            self._save_file("agents.json", data)

    # ── Tools ───────────────────────────────────────────────────

    def get_tools(self) -> dict[str, dict]:
        """Get all tool configurations."""
        data = self._load_file("tools.json")
        return data.get("tools", {})

    def get_tool(self, tool_name: str) -> dict | None:
        """Get a single tool configuration."""
        tools = self.get_tools()
        return tools.get(tool_name)

    def save_tool(self, tool_name: str, tool_data: dict):
        """Save/update a tool configuration."""
        data = self._load_file("tools.json")
        if "tools" not in data:
            data["tools"] = {}
        data["tools"][tool_name] = tool_data
        self._save_file("tools.json", data)

    # ── Skills ──────────────────────────────────────────────────

    def get_skills(self) -> dict[str, dict]:
        """Get all skill configurations."""
        data = self._load_file("skills.json")
        return data.get("skills", {})

    def get_skill(self, skill_name: str) -> dict | None:
        """Get a single skill configuration."""
        skills = self.get_skills()
        return skills.get(skill_name)

    def get_skills_for_agent(self, agent_id: str) -> list[dict]:
        """Get all enabled skills for a specific agent."""
        skills = self.get_skills()
        result = []
        for name, cfg in skills.items():
            if cfg.get("enabled", True) and agent_id in cfg.get("agents", []):
                result.append({"name": name, **cfg})
        return result

    def save_skill(self, skill_name: str, skill_data: dict):
        """Save/update a skill configuration."""
        data = self._load_file("skills.json")
        if "skills" not in data:
            data["skills"] = {}
        data["skills"][skill_name] = skill_data
        self._save_file("skills.json", data)

    # ── ACP Agents ───────────────────────────────────────────────

    def get_acp_agents(self) -> dict[str, dict]:
        """Get all ACP agent configurations."""
        data = self._load_file("acp_agents.json")
        return data.get("acp_agents", {})

    def get_acp_agent(self, agent_id: str) -> dict | None:
        """Get a single ACP agent configuration."""
        agents = self.get_acp_agents()
        return agents.get(agent_id)

    def save_acp_agent(self, agent_id: str, agent_data: dict):
        """Save/update an ACP agent configuration."""
        data = self._load_file("acp_agents.json")
        if "acp_agents" not in data:
            data["acp_agents"] = {}
        data["acp_agents"][agent_id] = agent_data
        self._save_file("acp_agents.json", data)

    def delete_acp_agent(self, agent_id: str):
        """Delete an ACP agent configuration."""
        data = self._load_file("acp_agents.json")
        if "acp_agents" in data and agent_id in data["acp_agents"]:
            del data["acp_agents"][agent_id]
            self._save_file("acp_agents.json", data)

    # ── Reload ──────────────────────────────────────────────────

    def reload(self):
        """Force reload all config files."""
        with self._lock:
            self._mtimes.clear()
        self._load_all()
        logger.info("[ConfigManager] reloaded all configs")


# Global singleton
_config_manager: ConfigManager | None = None


def get_config_manager() -> ConfigManager:
    """Get the global ConfigManager instance."""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
        _config_manager.start_watching()
    return _config_manager
