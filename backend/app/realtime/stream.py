"""SSE 流生成器：与 Web 框架无关的纯异步生成器，便于独立单测（无需 FastAPI / 数据库）。

职责单一：订阅进程级事件总线 → 先发握手帧 → 循环把投递给该用户的事件序列化为 SSE 帧；
空闲超过 heartbeat_seconds 则发心跳帧保活；客户端断开（Cancel）或正常结束时取消订阅，释放队列。
"""
import asyncio
from typing import AsyncIterator

from app.realtime.events import EventType, RealtimeEvent, get_event_bus


async def sse_stream(user_id: int, heartbeat_seconds: float = 25) -> AsyncIterator[str]:
    """产出标准 SSE 文本帧的生成器；兼容 FastAPI/Starlette 的 StreamingResponse。"""
    bus = get_event_bus()
    queue = await bus.subscribe(user_id)
    try:
        # 握手帧：前端据此确认连接已建立
        yield RealtimeEvent(
            type=EventType.READY.value, payload={"user_id": user_id}
        ).to_sse()
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=heartbeat_seconds)
                yield event.to_sse()
            except asyncio.TimeoutError:
                # 心跳：保活，避免中间代理因空闲断开长连接
                yield RealtimeEvent(type=EventType.PING.value, payload={}).to_sse()
    except asyncio.CancelledError:
        # 客户端断开（刷新/关闭标签页/网络中断）：正常退出
        pass
    finally:
        # 无论何种退出路径都释放订阅，避免队列泄漏
        await bus.unsubscribe(user_id)
