"""统一日志格式与 logger 命名规范。

约定：格式 ``%(asctime)s %(levelname)s %(name)s %(message)s``；
logger 命名 ``lumencafe.<module>``。在 main.py 启动时调用一次 setup_logging。
"""
import logging
import sys

_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def setup_logging(level: str = "INFO") -> None:
    """初始化根 logger：统一格式与级别，handler 只挂一次（幂等）。"""
    root = logging.getLogger()
    if getattr(root, "_lumencafe_configured", False):
        root.setLevel(level.upper())
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(handler)
    root.setLevel(level.upper())
    root._lumencafe_configured = True  # type: ignore[attr-defined]


def get_logger(module: str) -> logging.Logger:
    """按规范返回 ``lumencafe.<module>`` 命名的 logger。"""
    return logging.getLogger(f"lumencafe.{module}")
