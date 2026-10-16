// 工作流相关展示元数据与格式化辅助（前后端共用）。
import type { AssigneeSpec, WFNodeType } from "./types";

export const NODE_META: Record<WFNodeType, { label: string; color: string }> = {
  start: { label: "开始", color: "#52c41a" },
  approval: { label: "审批", color: "#1677ff" },
  countersign: { label: "会签", color: "#722ed1" },
  condition: { label: "条件分支", color: "#fa8c16" },
  join: { label: "汇聚", color: "#13c2c2" },
  notify: { label: "抄送", color: "#eb2f96" },
  end: { label: "结束", color: "#cf1322" },
};

export const INSTANCE_STATUS: Record<string, { label: string; color: string }> = {
  running: { label: "进行中", color: "processing" },
  approved: { label: "已通过", color: "success" },
  rejected: { label: "已驳回", color: "error" },
  canceled: { label: "已撤回", color: "default" },
};

export const TASK_STATUS: Record<string, { label: string; color: string }> = {
  pending: { label: "待处理", color: "warning" },
  approved: { label: "已通过", color: "success" },
  rejected: { label: "已驳回", color: "error" },
  canceled: { label: "已取消", color: "default" },
};

export const LOG_ACTION: Record<string, string> = {
  enter: "进入节点",
  approve: "通过",
  reject: "驳回",
  transfer: "转办",
  addsign: "加签",
  urge: "催办",
  withdraw: "撤回",
  finish: "节点完成",
  skip: "跳过",
  cancel: "取消",
};

export function assigneeLabel(spec?: AssigneeSpec): string {
  if (!spec) return "（无）";
  switch (spec.type) {
    case "user":
      return `用户#${spec.value}`;
    case "role":
      return `角色:${spec.value}`;
    case "dept_manager":
      return "部门主管";
    case "initiator":
      return "发起人";
    default:
      return String(spec.type);
  }
}
