"""数据库持久化子包 —— 替代旧 ``checkpoint.py``。

使用方式
--------
>>> from src.agent.db import create_session, load_history, save_message
>>> sid = create_session()
>>> save_message(sid, "human", "你好")

模块一览
--------
===========================  ==============================================
``connection``               ``_get_conn()`` + schema 自动迁移
``sessions``                 会话 CRUD (create / delete / list / rename / ...)
``messages``                 消息 CRUD (load / save / save_turn / load_history)
``tasks``                    任务更新 (task_updates 表)
``tools``                    工具调用记录 + 度量 (tool_usage + metrics)
``compact``                  压缩 (compact_session)
===========================  ==============================================

注意
----
* 本子包的 ``__init__.py`` 导出所有对外函数,外部只应 ``from src.agent.db import ...``
* 旧 ``from src.agent.checkpoint import ...`` 已废弃,请迁移
"""

from src.agent.db.compact import compact_session
from src.agent.db.messages import (
    load_history,
    load_history_with_meta,
    load_messages,
    save_message,
    save_turn,
)
from src.agent.db.sessions import (
    create_session,
    delete_session,
    get_acp_session_id,
    get_session_summary,
    list_sessions,
    rename_session,
    session_exists,
    update_acp_session_id,
    update_session_duration,
    update_session_project_path,
    update_session_status,
)
from src.agent.db.tasks import (
    delete_task_updates,
    delete_task_updates_for_sessions,
    load_task_updates,
    save_task_update,
)
from src.agent.db.tools import get_tool_usage_stats, load_metrics, record_tool_usage, save_metrics

__all__ = [
    "compact_session",
    "create_session",
    "delete_session",
    "delete_task_updates",
    "delete_task_updates_for_sessions",
    "get_acp_session_id",
    "get_session_summary",
    "get_tool_usage_stats",
    "list_sessions",
    "load_history",
    "load_history_with_meta",
    "load_messages",
    "load_metrics",
    "load_task_updates",
    "record_tool_usage",
    "rename_session",
    "save_message",
    "save_metrics",
    "save_task_update",
    "save_turn",
    "session_exists",
    "update_acp_session_id",
    "update_session_duration",
    "update_session_project_path",
    "update_session_status",
]
