import { Tag } from "antd";

export interface StatusMeta {
  label: string;
  color: string;
}

/**
 * 全局状态字典：把各模块（流程/报销/考勤/公文…）的状态码统一成中文标签 + 品牌色。
 * 页面如需扩展，传入 map 覆盖即可，避免每个页面各自硬编码颜色。
 */
export const STATUS_PRESET: Record<string, StatusMeta> = {
  // 通用流程
  draft: { label: "草稿", color: "default" },
  running: { label: "审批中", color: "processing" },
  pending: { label: "待处理", color: "processing" },
  approved: { label: "已通过", color: "success" },
  rejected: { label: "已驳回", color: "error" },
  canceled: { label: "已取消", color: "default" },
  withdrawn: { label: "已撤回", color: "default" },
  archived: { label: "已归档", color: "default" },
  // 报销
  submitted: { label: "已提交", color: "processing" },
  paid: { label: "已打款", color: "success" },
  // 考勤
  normal: { label: "正常", color: "success" },
  late: { label: "迟到", color: "warning" },
  early: { label: "早退", color: "warning" },
  absent: { label: "缺卡", color: "error" },
  leave: { label: "请假", color: "processing" },
  overtime: { label: "加班", color: "processing" },
  // 启用态
  active: { label: "启用", color: "success" },
  enabled: { label: "启用", color: "success" },
  disabled: { label: "停用", color: "default" },
  inactive: { label: "停用", color: "default" },
  // 消息
  unread: { label: "未读", color: "processing" },
  read: { label: "已读", color: "default" },
};

export interface StatusTagProps {
  status?: string | null;
  /** 覆盖/补充全局字典 */
  map?: Record<string, StatusMeta>;
  /** 字典未命中时的兜底文案 */
  fallback?: string;
}

export default function StatusTag({ status, map, fallback }: StatusTagProps) {
  if (!status) return <Tag>-</Tag>;
  const meta = map?.[status] ?? STATUS_PRESET[status];
  if (!meta) return <Tag>{fallback ?? status}</Tag>;
  return <Tag color={meta.color}>{meta.label}</Tag>;
}
