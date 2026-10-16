"""EventBus 单元测试：与数据库无关，验证定向投递 / 广播 / 退订 / 队列溢出保护 /
服务层发射接线。

这些测试在任意标准环境（pip install pytest pytest-asyncio 后 pytest -q）下可直接运行，
不连接数据库（服务层用例使用哑 session，仅验证事件发射、不触碰 DB），
用于守护实时事件总线的核心语义。
"""
import asyncio

from app.realtime.events import EventBus, EventType, RealtimeEvent
from app.services import NotificationService


async def test_publish_targets_only_subscribed_user():
    bus = EventBus()
    q1 = await bus.subscribe(1)
    q2 = await bus.subscribe(2)
    await bus.publish(
        RealtimeEvent(type=EventType.WORKFLOW_TASK_ASSIGNED.value, payload={"x": 1}, user_ids=[1])
    )
    ev = await asyncio.wait_for(q1.get(), timeout=1)
    assert ev.payload["x"] == 1
    assert q2.empty()


async def test_publish_broadcast_reaches_all():
    bus = EventBus()
    q1 = await bus.subscribe(1)
    q2 = await bus.subscribe(2)
    await bus.publish(RealtimeEvent(type=EventType.PING.value, payload={}))
    assert not q1.empty()
    assert not q2.empty()


async def test_unsubscribe_stops_delivery():
    bus = EventBus()
    q = await bus.subscribe(7)
    await bus.unsubscribe(7)
    await bus.publish(
        RealtimeEvent(type=EventType.PING.value, payload={}, user_ids=[7])
    )
    assert q.empty()


async def test_queue_overflow_does_not_raise():
    bus = EventBus()
    q = await bus.subscribe(3)
    # 填满队列（maxsize=256）后继续发布：验证不抛异常且队列不无限增长（溢出丢弃最旧）
    for _ in range(300):
        await bus.publish(
            RealtimeEvent(type=EventType.PING.value, payload={}, user_ids=[3])
        )
    assert q.qsize() <= 256


class _DummySession:
    """哑 session：仅用于验证服务层事件发射接线，不触碰数据库。"""


async def test_notification_service_emit_reaches_bus():
    bus = EventBus()
    queue = await bus.subscribe(5)
    svc = NotificationService(_DummySession(), event_bus=bus)
    await svc._emit(EventType.NOTIFICATION_CREATED, {"title": "新公告"}, user_ids=[5])
    ev = await asyncio.wait_for(queue.get(), timeout=1)
    assert ev.payload["title"] == "新公告"


async def test_service_emit_without_bus_is_noop():
    """未注入总线时发射应静默跳过且不抛异常，保证离线 / 单测场景零副作用。"""
    svc = NotificationService(_DummySession())
    await svc._emit(EventType.NOTIFICATION_CREATED, {})
