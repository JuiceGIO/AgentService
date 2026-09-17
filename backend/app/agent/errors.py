"""Agent 层的异常类型（轻量模块，避免为了一个异常把 MCP 依赖带进导入链）。"""


class PermissionDenied(Exception):
    """工具越权（行级权限校验失败）。由 API 层映射为 HTTP 403。"""
