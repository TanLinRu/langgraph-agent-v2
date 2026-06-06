"""Graph Config Manager - Workflow configuration loading and management.

This module extends the existing ConfigManager to support workflow configurations,
stored in config/workflows.json.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent.parent.parent.parent / "config"


class GraphConfigManager:
    """Manages workflow graph configurations."""

    def __init__(self, config_dir: Path | None = None):
        self.config_dir = config_dir or CONFIG_DIR
        self._cache: dict[str, Any] = {}
        self._mtime: float = 0.0

    def _load_workflows(self) -> dict[str, Any]:
        """Load workflows.json with caching."""
        filepath = self.config_dir / "workflows.json"
        if not filepath.exists():
            logger.warning("[GraphConfigManager] workflows.json not found: %s", filepath)
            return {"workflows": []}

        try:
            mtime = filepath.stat().st_mtime
            if mtime == self._mtime:
                return self._cache

            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._cache = data
            self._mtime = mtime
            logger.info("[GraphConfigManager] loaded workflows.json")
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.error("[GraphConfigManager] failed to load workflows.json: %s", e)
            return self._cache or {"workflows": []}

    def _save_workflows(self, data: dict[str, Any]) -> None:
        """Save workflows.json."""
        filepath = self.config_dir / "workflows.json"
        filepath.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self._cache = data
            self._mtime = filepath.stat().st_mtime
            logger.info("[GraphConfigManager] saved workflows.json")
        except OSError as e:
            logger.error("[GraphConfigManager] failed to save workflows.json: %s", e)

    def list_graphs(self) -> list[dict[str, Any]]:
        """List all workflow graphs.

        Returns:
            List of workflow configurations
        """
        data = self._load_workflows()
        return data.get("workflows", [])

    def get_graph(self, graph_id: str) -> dict[str, Any] | None:
        """Get a specific workflow graph configuration.

        Args:
            graph_id: Workflow identifier

        Returns:
            Workflow configuration or None if not found
        """
        workflows = self.list_graphs()
        for wf in workflows:
            if wf.get("id") == graph_id:
                return wf
        return None

    def save_graph(self, graph_id: str, graph_data: dict[str, Any]) -> None:
        """Save/update a workflow graph configuration.

        Args:
            graph_id: Workflow identifier
            graph_data: Workflow configuration
        """
        data = self._load_workflows()
        workflows = data.get("workflows", [])

        # Find and update or append
        found = False
        for i, wf in enumerate(workflows):
            if wf.get("id") == graph_id:
                workflows[i] = graph_data
                found = True
                break

        if not found:
            workflows.append(graph_data)

        data["workflows"] = workflows
        self._save_workflows(data)

    def delete_graph(self, graph_id: str) -> bool:
        """Delete a workflow graph configuration.

        Args:
            graph_id: Workflow identifier

        Returns:
            True if deleted, False if not found
        """
        data = self._load_workflows()
        workflows = data.get("workflows", [])

        for i, wf in enumerate(workflows):
            if wf.get("id") == graph_id:
                workflows.pop(i)
                data["workflows"] = workflows
                self._save_workflows(data)
                return True

        return False

    def get_enabled_graphs(self) -> list[dict[str, Any]]:
        """Get all enabled workflow graphs.

        Returns:
            List of enabled workflow configurations
        """
        return [wf for wf in self.list_graphs() if wf.get("enabled", True)]

    def validate_graph(self, graph_data: dict[str, Any]) -> list[str]:
        """Validate workflow graph configuration.

        Args:
            graph_data: Workflow configuration

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        # Required fields
        if not graph_data.get("id"):
            errors.append("Missing required field: id")
        if not graph_data.get("name"):
            errors.append("Missing required field: name")

        # Validate nodes
        nodes = graph_data.get("nodes", [])
        if not nodes:
            errors.append("No nodes defined")
        else:
            node_ids = set()
            for node in nodes:
                if not node.get("id"):
                    errors.append(f"Node missing id: {node}")
                elif node["id"] in node_ids:
                    errors.append(f"Duplicate node id: {node['id']}")
                else:
                    node_ids.add(node["id"])

                if not node.get("type"):
                    errors.append(f"Node missing type: {node.get('id', 'unknown')}")

        # Validate edges
        edges = graph_data.get("edges", [])
        node_ids = {n.get("id") for n in nodes}
        for edge in edges:
            from_node = edge.get("from")
            to_node = edge.get("to")

            if not from_node or not to_node:
                errors.append(f"Edge missing from/to: {edge}")
            elif from_node not in node_ids:
                errors.append(f"Edge 'from' references unknown node: {from_node}")
            elif to_node not in node_ids:
                errors.append(f"Edge 'to' references unknown node: {to_node}")

        return errors

    def get_graph_summary(self, graph_id: str) -> dict[str, Any] | None:
        """Get workflow summary for frontend display.

        Args:
            graph_id: Workflow identifier

        Returns:
            Summary dict or None if not found
        """
        graph = self.get_graph(graph_id)
        if not graph:
            return None

        return {
            "id": graph.get("id"),
            "name": graph.get("name"),
            "description": graph.get("description", ""),
            "enabled": graph.get("enabled", True),
            "nodes_count": len(graph.get("nodes", [])),
        }


# Global singleton
_graph_config_manager: GraphConfigManager | None = None


def get_graph_config_manager() -> GraphConfigManager:
    """Get the global GraphConfigManager instance."""
    global _graph_config_manager
    if _graph_config_manager is None:
        _graph_config_manager = GraphConfigManager()
    return _graph_config_manager
