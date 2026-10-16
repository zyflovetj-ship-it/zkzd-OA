"""SSE 流生成器运行时冒烟测试（DB 无关，可在无 FastAPI/SQLAlchemy 的环境直接运行）。

覆盖 sse_stream 的核心运行时行为：握手帧、定向投递、用户隔离、心跳保活、断线退订。
这些断言对应 Phase 5「实时检查」中 SSE 端点的真实推送语义；标准环境也可用 pytest 收集。

运行：
- 标准环境：pytest -q tests/test_sse_stream.py
- 无 pytest 的受限环境：python tests/test_sse_stream.py （见文件末尾 __main__）
"""
import asyncio

from app.realtime.events import EventType, RealtimeEvent, get_event_bus
from app.realtime.stream import sse_stream


async def test_ready_frame_first():
    gen = sse_stream(101, heartbeat_seconds=5)
    first = await gen.__anext__()
    assert first.startswith("event: ready\n"), first
    assert "user_id" in first and "101" in first
    await gen.aclose()


async def test_targeted_delivery():
    bus = get_event_bus()
    gen = sse_stream(102, heartbeat_seconds=5)
    await gen.__anext__()  # 握手帧
    await bus.publish(
        RealtimeEvent(
            type=EventType.WORKFLOW_TASK_ASSIGNED.value,
            payload={"title": "报销单"},
            user_ids=[102],
        )
    )
    frame = await gen.__anext__()
    assert "workflow.task_assigned" in frame
    assert "报销单" in frame
    await gen.aclose()


async def test_user_isolation():
    bus = get_event_bus()
    g1 = sse_stream(201, heartbeat_seconds=5)
    g2 = sse_stream(202, heartbeat_seconds=5)
    await g1.__anext__()
    await g2.__anext__()
    # 仅向 201 投递，202 不得收到
    await bus.publish(
        RealtimeEvent(type=EventType.PING.value, payload={}, user_ids=[201])
    )
    frame = await asyncio.wait_for(g1.__anext__(), timeout=1)
    assert "event: ping" in frame
    # 202 的订阅队列应保持为空（证明用户间隔离）
    assert bus.pending_count(202) == 0
    await g1.aclose()
    await g2.aclose()


async def test_heartbeat_ping_on_timeout():
    gen = sse_stream(303, heartbeat_seconds=0.05)
    await gen.__anext__()  # 握手帧
    frame = await asyncio.wait_for(gen.__anext__(), timeout=1)
    assert "event: ping" in frame, frame
    await gen.aclose()


async def test_unsubscribe_on_close():
    bus = get_event_bus()
    before = bus.online_count()
    gen = sse_stream(404, heartbeat_seconds=5)
    await gen.__anext__()
    assert bus.online_count() == before + 1
    await gen.aclose()
    assert bus.online_count() == before


if __name__ == "__main__":
    async def _run_all():
        await test_ready_frame_first()
        await test_targeted_delivery()
        await test_user_isolation()
        await test_heartbeat_ping_on_timeout()
        await test_unsubscribe_on_close()
        print("ALL SSE STREAM TESTS PASSED")

    asyncio.run(_run_all())
