// 与后端 Pydantic Schema 对齐的前端类型
export interface UserOut {
  id: number;
  username: string;
  full_name: string;
  email: string;
  is_active: boolean;
  role_id: number;
  role_name: string;
  department_id: number | null;
  created_at: string;
}

export interface Role {
  id: number;
  name: string;
  description: string;
  data_scope?: string; // all | dept | self
}

export interface RoleCreate {
  name: string;
  description?: string;
  data_scope?: "all" | "dept" | "self";
}

// 组织权限中心：权限点
export interface PermissionOut {
  id: number;
  code: string;
  name: string;
  category: string;
  type: string; // menu | operation
  description: string;
}

// 导航菜单（后端按权限过滤后下发）
export interface MenuOut {
  id: number;
  parent_id: number | null;
  name: string;
  path: string;
  icon: string;
  order: number;
  permission_code: string;
}

// 登录态概览：在 UserOut 基础上附带权限码与数据范围
export interface MeOut extends UserOut {
  permissions: string[]; // ["*"] 表示管理员通配
  data_scope: string;
}

export interface DepartmentOut {
  id: number;
  name: string;
  parent_id: number | null;
  manager_id: number | null;
  created_at: string;
}

export interface LeaveOut {
  id: number;
  user_id: number;
  leave_type: string;
  start_date: string;
  end_date: string;
  reason: string;
  status: string;
  approver_id: number | null;
  rejection_reason: string;
  reviewed_at: string | null;
  created_at: string;
}

export interface AnnouncementAttachment {
  document_id: number;
  title: string;
  file_url: string;
}

export interface AnnouncementOut {
  id: number;
  title: string;
  content: string;
  author_id: number;
  pinned: boolean;
  published: boolean;
  attachments: AnnouncementAttachment[];
  expires_at: string | null;
  read_count: number;
  created_at: string;
  updated_at: string;
}

// 消息中心：通知收件箱（type: system | leave | workflow | announcement）
export interface NotificationOut {
  id: number;
  type: string;
  title: string;
  body: string;
  link: string;
  is_read: boolean;
  created_at: string;
}

export interface NotificationsPage {
  items: NotificationOut[];
  total: number;
  unread: number;
  limit: number;
  offset: number;
}

// ===== 工作流图结构（与 backend/workflow_engine.graph 约定对齐） =====
export type WFNodeType =
  | "start"
  | "approval"
  | "countersign"
  | "condition"
  | "join"
  | "notify"
  | "end";

export interface AssigneeSpec {
  type: "user" | "role" | "dept_manager" | "initiator";
  value?: string | number; // user -> 用户ID；role -> 角色名
}

export interface WFGraphNode {
  id: string;
  type: WFNodeType;
  name?: string;
  assignee?: AssigneeSpec; // approval 单审批人
  assignees?: AssigneeSpec[]; // countersign / notify 多审批人
  strategy?: "all" | "any" | "ratio"; // countersign 会签策略
  ratio?: number | null; // countersign ratio 策略阈值
  parallel?: boolean; // condition 是否并行分支
  x?: number; // 设计器坐标（前端专用，引擎忽略）
  y?: number;
}

export type ConditionOp = ">" | "<" | ">=" | "<=" | "==" | "!=" | "in" | "not_in" | "contains";
export interface ConditionRule {
  field: string;
  op: ConditionOp;
  value: string | number | string[];
}
export interface ConditionGroup {
  op: "and" | "or";
  rules: ConditionRule[];
}
export interface WFGraphEdge {
  id: string;
  source: string;
  target: string;
  condition?: ConditionGroup | null;
}
export interface WFGraph {
  nodes: WFGraphNode[];
  edges: WFGraphEdge[];
}

// ===== 后端 DTO（与 Pydantic Schema 对齐） =====
export interface FormField {
  key: string;
  label: string;
  type: "text" | "number" | "date" | "select" | "textarea";
  required?: boolean;
  options?: string[];
}
export interface FormDefinitionOut {
  id: number;
  code: string;
  name: string;
  fields: FormField[];
  created_at: string;
  updated_at: string;
}
export interface FormDefinitionCreate {
  code: string;
  name: string;
  fields: FormField[];
}

export interface WorkflowDefinitionOut {
  id: number;
  code: string;
  name: string;
  category: string;
  description: string;
  icon: string;
  status: string; // draft | published | locked
  current_version: number;
  created_at: string;
  updated_at: string;
}
export interface WorkflowDefinitionCreate {
  code: string;
  name: string;
  category?: string;
  description?: string;
  icon?: string;
}

export interface WorkflowVersionOut {
  id: number;
  definition_id: number;
  version: number;
  graph: WFGraph;
  form_id: number | null;
  status: string; // draft | published | archived
  published_at: string | null;
  remark: string;
  created_at: string;
}
export interface WorkflowVersionSave {
  graph: WFGraph;
  form_id?: number | null;
  remark?: string;
}

export interface WorkflowTaskOut {
  id: number;
  instance_id: number;
  node_id: string;
  node_name: string;
  node_type: string;
  approver_id: number | null;
  origin_approver_id: number | null;
  mode: string;
  status: string; // pending | approved | rejected | canceled
  comment: string;
  seq: number;
  created_at: string;
  decided_at: string | null;
}

export interface WorkflowInstanceOut {
  id: number;
  code: string;
  definition_id: number;
  version_id: number;
  title: string;
  initiator_id: number;
  form_data: Record<string, any>;
  current_nodes: string[];
  status: string; // running | approved | rejected | canceled
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  tasks: WorkflowTaskOut[];
}

export interface WorkflowLogOut {
  id: number;
  node_id: string;
  node_name: string;
  action: string;
  operator_id: number | null;
  comment: string;
  created_at: string;
}

export interface WorkflowReview {
  approve: boolean;
  comment?: string | null;
}
export interface WorkflowTransfer {
  to_user_id: number;
  comment?: string | null;
}
export interface WorkflowAddSign {
  user_ids: number[];
  before?: boolean;
  comment?: string | null;
}
export interface WorkflowUrge {
  comment?: string | null;
}

export interface SignatureOut {
  id: number;
  ref_type: string;
  ref_id: number;
  signer_id: number;
  content_hash: string;
  comment: string;
  signed_at: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

// ===== 流程监控看板（与 backend WorkflowStatsOut 对齐） =====
export interface WorkflowStatsOut {
  generated_at: string;
  sla_days: number;
  definitions: Record<string, number>; // draft|published|locked
  instances: Record<string, number>; // running|approved|rejected|canceled
  tasks: Record<string, number>; // pending|overdue
  delegations_active: number;
  by_definition: Array<{
    definition_id: number;
    name: string;
    code: string;
    total: number;
    running: number;
    approved: number;
    rejected: number;
    canceled: number;
  }>;
  trend: Array<{ date: string; started: number; finished: number }>;
  overdue_tasks: Array<{
    task_id: number;
    instance_id: number;
    instance_code: string;
    instance_title: string;
    node_name: string;
    approver_id: number | null;
    approver_name: string;
    created_at: string | null;
    due_at: string | null;
  }>;
  running_instances: Array<{
    id: number;
    code: string;
    title: string;
    definition_name: string;
    initiator: string;
    current_nodes: Array<{ node_id: string; name: string; type: string }>;
    started_at: string | null;
    progress: number;
  }>;
}

// ===== 内容门户：角色化工作台概览（与 backend PortalOverviewOut 对齐） =====
export interface PortalTaskOut {
  task_id: number;
  instance_id: number;
  instance_code: string;
  instance_title: string;
  node_name: string;
  created_at: string | null;
}

export interface PortalInstanceOut {
  id: number;
  code: string;
  title: string;
  status: string;
  started_at: string | null;
}

export interface PortalLeaveOut {
  id: number;
  leave_type: string;
  status: string;
  start_date: string;
  end_date: string;
}

export interface PortalAnnouncementOut {
  id: number;
  title: string;
  pinned: boolean;
  created_at: string;
}

export interface PortalOverviewOut {
  role: string;
  is_admin: boolean;
  stats: Record<string, number>;
  pending_tasks: PortalTaskOut[];
  my_instances_running: PortalInstanceOut[];
  recent_leave: PortalLeaveOut[];
  announcements: PortalAnnouncementOut[];
}

// ===== 运维中心：系统运行概览（与 backend OpsOverviewOut 对齐） =====
export interface OpsUserByRole {
  role: string;
  count: number;
}

export interface OpsInstance {
  id: number;
  code: string;
  title: string;
  status: string;
  started_at: string | null;
  initiator: string;
}

export interface OpsOverviewOut {
  generated_at: string;
  db_backend: string;
  counts: Record<string, number>;
  instances_by_status: Record<string, number>;
  users_by_role: OpsUserByRole[];
  recent_instances: OpsInstance[];
}

// ===== 报表中心：统一数据看板（与 backend DashboardXxxOut 对齐） =====
export interface DashboardPersonalOut {
  my_unread: number;
  my_pending_approvals: number;
  my_leaves: number;
  my_running: number;
}

export interface DashboardKpiOut {
  users_total: number;
  departments_total: number;
  workflow_instances: number;
  workflow_active: number;
  workflow_done: number;
  leaves_this_month: number;
  announcements_total: number;
  audit_total: number;
}

export interface StatusSlice {
  status: string;
  count: number;
}

export interface TrendPoint {
  date: string;
  started: number;
  finished: number;
}

export interface DeptHead {
  department: string;
  count: number;
}

export interface ActivityItem {
  id: number;
  title: string;
  type: string;
  status: string | null;
  at: string | null;
  actor: string | null;
}

export interface DashboardOrgOut {
  kpi: DashboardKpiOut;
  workflow_status: StatusSlice[];
  workflow_trend: TrendPoint[];
  trend_days: number;
  department_headcount: DeptHead[];
  recent_activities: ActivityItem[];
}

export interface DashboardOut {
  generated_at: string;
  has_org_scope: boolean;
  personal: DashboardPersonalOut;
  org: DashboardOrgOut | null;
}

// ===== 建模引擎：自定义实体 + 动态数据（与 backend ModelXxx 对齐） =====
export type ModelFieldType =
  | "text"
  | "textarea"
  | "number"
  | "money"
  | "date"
  | "datetime"
  | "bool"
  | "select"
  | "radio"
  | "multiselect"
  | "email";

export interface ModelField {
  key: string;
  label: string;
  type: ModelFieldType;
  required: boolean;
  unique: boolean;
  options: string[];
  default: any;
}

export interface ModelEntityOut {
  id: number;
  code: string;
  name: string;
  category: string;
  icon: string;
  description: string;
  fields: ModelField[];
  display_field: string;
  status: string; // draft | published
  record_count: number;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface ModelRecordOut {
  id: number;
  entity_id: number;
  serial_no: string;
  data: Record<string, any>;
  created_by: number | null;
  updated_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface ModelRecordsPage {
  total: number;
  offset: number;
  limit: number;
  items: ModelRecordOut[];
}

export interface ModelStatsOut {
  generated_at: string;
  entities: number;
  entities_published: number;
  records: number;
  records_today: number;
  by_entity: { entity_id: number; name: string; count: number }[];
}

// ===== 日志中心：审计日志（与 backend Audit* 对齐） =====
export interface AuditLogOut {
  id: number;
  actor_id: number | null;
  actor_name: string;
  module: string;
  action: string;
  target_type: string;
  target_id: string;
  method: string;
  path: string;
  status: string; // success | failed
  status_code: number;
  message: string;
  detail: Record<string, any>;
  ip: string;
  request_id: string;
  created_at: string;
}

export interface AuditLogsPage {
  items: AuditLogOut[];
  total: number;
}

export interface AuditStatsOut {
  generated_at: string;
  total: number;
  success: number;
  failed: number;
  by_module: { key: string; count: number }[];
  by_status: { key: string; count: number }[];
  trend: { date: string; count: number }[];
}

export const FIELD_TYPE_LABELS: Record<ModelFieldType, string> = {
  text: "单行文本",
  textarea: "多行文本",
  number: "整数",
  money: "金额",
  date: "日期",
  datetime: "日期时间",
  bool: "是/否",
  select: "下拉单选",
  radio: "单选按钮",
  multiselect: "多选",
  email: "邮箱",
};

// ===== 内容引擎：文档中心（与 backend Document* 对齐） =====
export type DocCategory =
  | "general"
  | "policy"
  | "contract"
  | "report"
  | "training"
  | "other";

export interface DocumentOut {
  id: number;
  title: string;
  category: string;
  file_type: string;
  file_size: number;
  description: string;
  file_url: string;
  current_version: number;
  owner_id: number;
  owner_name: string;
  created_at: string;
  updated_at: string;
}

export interface DocumentUpdate {
  title?: string;
  category?: string;
  description?: string;
}

export interface DocumentsPage {
  items: DocumentOut[];
  total: number;
  offset: number;
  limit: number;
}

/** 文档版本历史（每次上传新文件追加一行，当前版本见 DocumentOut.current_version） */
export interface DocumentVersionOut {
  id: number;
  document_id: number;
  version: number;
  file_type: string;
  file_size: number;
  file_url: string;
  note: string;
  uploader_name: string;
  created_at: string;
}

/** 公告阅读回执（幂等：同一用户只计一次） */
export interface AnnouncementReadOut {
  announcement_id: number;
  read: boolean;
  read_count: number;
}

export interface AnnouncementReaderItem {
  user_id: number;
  user_name: string;
  read_at: string;
}

/** 公告阅读明细（发布者/管理员可见） */
export interface AnnouncementReadersOut {
  announcement_id: number;
  read_count: number;
  total_users: number;
  readers: AnnouncementReaderItem[];
}

export const DOC_CATEGORY_LABELS: Record<string, string> = {
  general: "常规",
  policy: "制度文件",
  contract: "合同",
  report: "报告",
  training: "培训资料",
  other: "其他",
};
