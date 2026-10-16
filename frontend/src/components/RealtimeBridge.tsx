import { useEffect } from "react";
import { App } from "antd";
import { useQueryClient } from "@tanstack/react-query";
import { connectEventStream, type RealtimeEventPayload } from "../api/events";

/**
 * 实时桥接：订阅后端 SSE 事件流，把事件转化为两类动作——
 * ① 即时提示（toast）；② 失效相关 React Query 缓存，让列表与未读角标即时刷新
 *   （由此替代消息中心 30s 轮询带来的可见延迟）。
 *
 * 组件无 UI 输出，仅承载副作用；依赖 antd <App> 上下文提供的 message 实例。
 */
export default function RealtimeBridge() {
  const { message } = App.useApp();
  const qc = useQueryClient();

  useEffect(() => {
    const asNumber = (v: unknown) => (typeof v === "number" ? v : undefined);

    const invalidate = (...keys: unknown[][]) => {
      for (const key of keys) {
        void qc.invalidateQueries({ queryKey: key });
      }
    };

    const disconnect = connectEventStream({
      onEvent: (type: string, payload: RealtimeEventPayload) => {
        const title = (payload.title as string) ?? "流程";
        switch (type) {
          case "notification.created":
            // 仅静默刷新未读角标与消息列表：具体业务事件各自负责弹提示，避免重复打扰
            invalidate(["notifications"]);
            break;
          case "announcement.published":
            message.info(`新公告：${title}`, 5);
            invalidate(["announcements"], ["notifications"]);
            break;
          case "workflow.task_assigned":
            message.info(`新待办：${title}`, 4);
            invalidate(["wf-pending"], ["wf-notified"], ["notifications"]);
            break;
          case "workflow.status": {
            const status = payload.status as string;
            if (status === "approved") message.success(`流程通过：${title}`, 4);
            else if (status === "rejected") message.warning(`流程被驳回：${title}`, 4);
            else if (status === "canceled") message.info(`流程已撤回：${title}`, 4);
            invalidate(["wf-pending"], ["wf-done"], ["wf-mine"], ["wf-stats"]);
            const iid = asNumber(payload.instance_id);
            if (iid !== undefined) invalidate(["wf-instance", iid]);
            break;
          }
          case "workflow.decision": {
            const action = payload.action as string;
            if (action === "urge") message.warning(`催办：${title}（请尽快处理）`, 5);
            else if (action === "approve" || action === "reject")
              message.info(`流程进展：${title}`, 3);
            invalidate(["wf-pending"], ["wf-done"]);
            const iid = asNumber(payload.instance_id);
            if (iid !== undefined) invalidate(["wf-instance-logs", iid]);
            break;
          }
          default:
            break;
        }
      },
    });
    return () => disconnect();
  }, [message, qc]);

  return null;
}
