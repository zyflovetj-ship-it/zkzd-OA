"""结构化 JSON 日志，贯穿 request_id，不记录密码/令牌等敏感数据。"""
import json
import logging
import sys
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_RESERVED = set(logging.makeLogRecord({}).__dict__.keys())


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log: dict = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        if record.exc_info:
            log["exc"] = self.formatException(record.exc_info)
        for key, val in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                log[key] = val
        return json.dumps(log, ensure_ascii=False)


class StructLogger(logging.Logger):
    """支持 `logger.info("msg", key=value)` 写法的结构化日志器。

    标准库 Logger 的 `info/warning/error` 只接受 `extra={...}`，本项目调用点却统一
    使用关键字字段（如 `logger.info("startup", env=...)`），直接调用会抛
    `TypeError: _log() got an unexpected keyword argument`，导致应用无法启动。
    这里把额外关键字合并进 LogRecord，再由 JsonFormatter 输出为 JSON 字段。
    """

    def _log(  # noqa: PLR0913
        self,
        level,
        msg,
        args,
        exc_info=None,
        extra=None,
        stack_info=False,
        stacklevel=1,
        **kwargs,
    ):
        merged: dict = dict(extra or {})
        merged.update(kwargs)
        super()._log(
            level,
            msg,
            args,
            exc_info=exc_info,
            extra=merged or None,
            stack_info=stack_info,
            stacklevel=stacklevel,
        )


# 让后续 getLogger() 创建的即为 StructLogger（已创建的对象由 get_logger 兜底包装）
logging.setLoggerClass(StructLogger)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not isinstance(logger, StructLogger):
        logger = StructLogger(name, logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
