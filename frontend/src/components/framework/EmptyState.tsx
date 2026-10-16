import type { ReactNode } from "react";
import { Button, Empty } from "antd";

export interface EmptyStateProps {
  description?: ReactNode;
  /** 主操作按钮（如「新建第一条」） */
  action?: ReactNode;
  actionText?: string;
  onAction?: () => void;
  compact?: boolean;
}

/** 空态：统一中文文案与可选主操作，避免各页面直接裸用 AntD Empty */
export default function EmptyState({
  description = "暂无数据",
  action,
  actionText,
  onAction,
  compact = false,
}: EmptyStateProps) {
  return (
    <div className="zk-empty" style={compact ? { padding: "20px 0" } : undefined}>
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={description}
        style={{ marginBottom: action || actionText ? 16 : 0 }}
      >
        {action ??
          (actionText ? (
            <Button type="primary" onClick={onAction}>
              {actionText}
            </Button>
          ) : null)}
      </Empty>
    </div>
  );
}
