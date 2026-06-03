"""Agent Streaming 事件格式化工具。

模块职责
--------
提供流式解析 ``astream_events`` 输出到 ``EventType`` 协议的辅助函数。

注意:``Agent.run()`` 直接在 ``core.py`` 中处理 ``astream_events`` 的迭代,
本模块仅放置可复用的格式化工具 (目前服务于 ``agent/core.py``)。
"""

from __future__ import annotations

import re

# 文件路径提取正则 —— 从模型输出中识别代码库文件引用
_FILE_PATH_RE = re.compile(r'(?:src|docs|tests|ui|memory|skills)[/\\][\w./\\-]+\.\w+')
_CODE_FILE_RE = re.compile(r'[\w-]+\.(?:py|ts|js|vue|html|json|md|toml|yaml)')


def extract_file_refs(content: str) -> list[str]:
    """从文本中提取所有出现的文件路径引用。"""
    return list(set(_FILE_PATH_RE.findall(content) + _CODE_FILE_RE.findall(content)))
