"""实时事件总线：进程内 asyncio pub/sub，按用户定向投递，支撑 SSE 推送。

设计要点（对齐全栈专家规范的实时能力要求）：
- 每个在线用户持有独立 asyncio.Queue；事件按 user_ids 定向投递，未指定则广播；
- publish 非阻塞（put_nowait），慢消费者丢弃最旧事件，绝不拖垮发布方（请求处理路径）；
- 仅依赖标准库，无外部依赖；通过 get_event_bus() 获取进程单例，测试可替换；
- RealtimeEvent.to_sse() 序列化为标准 SSE 帧（event: <type>\\ndata: <json>\\n\\n）。
"""
from __future__ import annotations

import asyncio
import enum
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


class EventType(str, enum.Enum):
    """实时事件类型；取值即 SSE 的 event 字段，前端据此路由处理。"""

    # 心跳：保活，避免网关/代理因空闲断开长连接
    PING = "ping"
    # 连接就绪握手
    READY = "ready"
    # 审批任务分派给某人（待办实时提醒）
    WORKFLOW_TASK_ASSIGNED = "workflow.task_assigned"
    # 审批动作发生（通过/驳回/转办/加签/撤回/催办）
    WORKFLOW_DECISION = "workflow.decision"
    # 流程整体状态变化（进行中 / 通过 / 驳回 / 撤回）
    WORKFLOW_STATUS = "workflow.status"
    # 消息中心新增
    NOTIFICATION_CREATED = "notification.created"
    # 公告发布
    ANNOUNCEMENT_PUBLISHED = "announcement.published"


@dataclass
class RealtimeEvent:
    type: str
    payload: dict
    # None => 广播给所有在线用户；指定则仅投递这些 user_id
    user_ids: Optional[list[int]] = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    ts: float = field(default_factory=time.time)

    def to_sse(self) -> str:
        """序列化为标准 SSE 帧（data 为 JSON，event 为类型）。"""
        data = json.dumps(
            {"type": self.type, "id": self.id, "ts": self.ts, "payload": self.payload},
            ensure_ascii=False,
        )
        return f"event: {self.type}\ndata: {data}\n\n"


class EventBus:
    """进程内事件总线：订阅/发布基于 asyncio.Queue，单事件循环内安全。"""

    def __init__(self) -> None:
        self._queues: dict[int, asyncio.Queue] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, user_id: int) -> asyncio.Queue:
        async with self._lock:
            q: asyncio.Queue = asyncio.Queue(maxsize=256)
            self._queues[user_id] = q
            return q

    async def unsubscribe(self, user_id: int) -> None:
        async with self._lock:
            self._queues.pop(user_id, None)

    def online_count(self) -> int:
        return len(self._queues)

    def pending_count(self, user_id: int) -> int:
        """该用户订阅队列中待消费事件数（未订阅返回 0），用于测试与运维观测。"""
        q = self._queues.get(user_id)
        return q.qsize() if q is not None else 0

    async def publish(self, event: RealtimeEvent) -> None:
        """投递事件到目标用户队列；非阻塞，慢消费者丢弃最旧事件。"""
        async with self._lock:
            targets = list(self._queues.keys())
        if event.user_ids:
            target_set = set(event.user_ids)
            targets = [uid for uid in targets if uid in target_set]
        for uid in targets:
            q = self._queues.get(uid)
            if q is None:
                continue
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # 实时性优先：丢弃最旧 1 条后重试，仍满则跳过该用户
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    pass

    def make(
        self,
        etype: "EventType | str",
        payload: dict,
        user_ids: Optional[list[int]] = None,
    ) -> RealtimeEvent:
        value = etype.value if isinstance(etype, EventType) else etype
        return RealtimeEvent(type=value, payload=payload, user_ids=user_ids)


_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """进程级单例；测试可显式构造 EventBus 注入以隔离。"""
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
