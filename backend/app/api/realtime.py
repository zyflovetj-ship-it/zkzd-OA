"""实时事件 SSE 端点：已登录用户订阅自身事件流，带心跳与断开清理。

安全要点：
- 必须携带有效 Bearer 令牌（get_current_user 鉴权），未登录返回 401；
- 令牌仅经 Authorization 头传递，绝不进入 URL 查询参数；
- 每个用户仅收到定向投递给其 user_id 的事件，互不可见；
- 心跳帧保活，避免网关/代理因空闲断开长连接；
- 客户端断开时通过 finally 取消订阅，释放队列（逻辑在 app.realtime.stream.sse_stream）。
"""
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.models import User
from app.realtime.stream import sse_stream

settings = get_settings()
router = APIRouter(prefix="/api", tags=["realtime"])

HEARTBEAT_SECONDS = settings.sse_heartbeat_seconds


@router.get("/events/stream")
async def event_stream(user: User = Depends(get_current_user)):
    return StreamingResponse(
        sse_stream(user.id, HEARTBEAT_SECONDS),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 关闭反向代理缓冲，保证实时推送
        },
    )
