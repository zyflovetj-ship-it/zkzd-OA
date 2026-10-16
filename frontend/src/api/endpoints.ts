// 类型化接口封装：Base URL 走环境变量，令牌由 client 自动附加。
import api from "./client";
import type {
  AnnouncementOut,
  AnnouncementReadOut,
  AnnouncementReadersOut,
  DashboardOut,
  DepartmentOut,
  DocumentOut,
  DocumentUpdate,
  DocumentVersionOut,
  DocumentsPage,
  FormDefinitionCreate,
  FormDefinitionOut,
  LeaveOut,
  MenuOut,
  MeOut,
  ModelEntityOut,
  ModelRecordOut,
  ModelRecordsPage,
  ModelStatsOut,
  PermissionOut,
  Role,
  RoleCreate,
  SignatureOut,
  UserOut,
  WorkflowAddSign,
  WorkflowDefinitionCreate,
  WorkflowDefinitionOut,
  WorkflowInstanceOut,
  WorkflowLogOut,
  WorkflowReview,
  WorkflowTaskOut,
  WorkflowTransfer,
  WorkflowUrge,
  WorkflowStatsOut,
  WorkflowVersionOut,
  WorkflowVersionSave,
  PortalOverviewOut,
  OpsOverviewOut,
  AuditLogOut,
  AuditStatsOut,
  AuditLogsPage,
  NotificationOut,
  NotificationsPage,
} from "../types";

export const usersApi = {
  list: (q?: string) =>
    api
      .get<UserOut[]>("/api/users", { params: q ? { q, limit: 200 } : { limit: 200 } })
      .then((r) => r.data),
  roles: () => api.get<Role[]>("/api/users/roles").then((r) => r.data),
  create: (body: any) => api.post<UserOut>("/api/users", body).then((r) => r.data),
  update: (id: number, body: any) =>
    api.patch<UserOut>(`/api/users/${id}`, body).then((r) => r.data),
};

// 内容门户：角色化工作台概览聚合
export const portalApi = {
  overview: () =>
    api.get<PortalOverviewOut>("/api/portal/overview").then((r) => r.data),
};

// 角色：列表 + 新建/更新（描述与数据范围）/删除
export const rolesApi = {
  list: () => api.get<Role[]>("/api/users/roles").then((r) => r.data),
  create: (body: RoleCreate) =>
    api.post<Role>("/api/users/roles", body).then((r) => r.data),
  update: (id: number, body: { description?: string; data_scope?: string }) =>
    api.patch<Role>(`/api/users/roles/${id}`, body).then((r) => r.data),
  remove: (id: number) =>
    api.delete<{ message: string }>(`/api/users/roles/${id}`).then((r) => r.data),
};

// 组织权限中心：权限点 + 角色授权
export const permApi = {
  list: (category?: string, type?: string) =>
    api
      .get<PermissionOut[]>("/api/permissions", {
        params: { ...(category ? { category } : {}), ...(type ? { type } : {}) },
      })
      .then((r) => r.data),
  create: (body: {
    code: string;
    name: string;
    category?: string;
    type?: string;
    description?: string;
  }) => api.post<PermissionOut>("/api/permissions", body).then((r) => r.data),
  rolePermissions: (roleId: number) =>
    api.get<PermissionOut[]>(`/api/permissions/roles/${roleId}`).then((r) => r.data),
  assign: (roleId: number, permissionId: number) =>
    api
      .post<{ message: string }>(`/api/permissions/roles/${roleId}`, {
        permission_id: permissionId,
      })
      .then((r) => r.data),
  revoke: (roleId: number, permId: number) =>
    api
      .delete<{ message: string }>(`/api/permissions/roles/${roleId}/${permId}`)
      .then((r) => r.data),
};

// 组织权限中心：导航菜单
export const menuApi = {
  list: () => api.get<MenuOut[]>("/api/menus").then((r) => r.data),
  create: (body: {
    parent_id?: number | null;
    name: string;
    path?: string;
    icon?: string;
    order?: number;
    permission_code?: string;
  }) => api.post<MenuOut>("/api/menus", body).then((r) => r.data),
  update: (
    id: number,
    body: {
      parent_id?: number | null;
      name?: string;
      path?: string;
      icon?: string;
      order?: number;
      permission_code?: string;
    }
  ) => api.patch<MenuOut>(`/api/menus/${id}`, body).then((r) => r.data),
};

// 认证态辅助：当前用户可见菜单
export const authApi = {
  menus: () => api.get<MenuOut[]>("/api/auth/menus").then((r) => r.data),
};

export const deptApi = {
  list: () => api.get<DepartmentOut[]>("/api/departments").then((r) => r.data),
  create: (body: any) =>
    api.post<DepartmentOut>("/api/departments", body).then((r) => r.data),
};

export const leaveApi = {
  list: () => api.get<LeaveOut[]>("/api/leave").then((r) => r.data),
  create: (body: any) => api.post<LeaveOut>("/api/leave", body).then((r) => r.data),
  review: (id: number, body: any) =>
    api.post<LeaveOut>(`/api/leave/${id}/review`, body).then((r) => r.data),
};

export const annApi = {
  list: () => api.get<AnnouncementOut[]>("/api/announcements").then((r) => r.data),
  create: (body: any) =>
    api.post<AnnouncementOut>("/api/announcements", body).then((r) => r.data),
  update: (id: number, body: any) =>
    api.patch<AnnouncementOut>(`/api/announcements/${id}`, body).then((r) => r.data),
  // 阅读回执（幂等：同一用户只计一次），打开详情时调用
  read: (id: number) =>
    api.post<AnnouncementReadOut>(`/api/announcements/${id}/read`).then((r) => r.data),
  // 阅读明细（发布者/管理员可见）
  readers: (id: number) =>
    api.get<AnnouncementReadersOut>(`/api/announcements/${id}/readers`).then((r) => r.data),
};

export const wfApi = {
  // ---- 流程定义 ----
  definitions: (status?: string) =>
    api
      .get<WorkflowDefinitionOut[]>("/api/workflows/definitions", {
        params: status ? { status } : {},
      })
      .then((r) => r.data),
  createDef: (body: WorkflowDefinitionCreate) =>
    api.post<WorkflowDefinitionOut>("/api/workflows/definitions", body).then((r) => r.data),
  setDefStatus: (id: number, status: string) =>
    api
      .patch<WorkflowDefinitionOut>(`/api/workflows/definitions/${id}/status`, null, {
        params: { status },
      })
      .then((r) => r.data),

  // ---- 表单定义 ----
  forms: () => api.get<FormDefinitionOut[]>("/api/workflows/forms").then((r) => r.data),
  createForm: (body: FormDefinitionCreate) =>
    api.post<FormDefinitionOut>("/api/workflows/forms", body).then((r) => r.data),

  // ---- 版本 / 流程图 ----
  saveVersion: (defId: number, body: WorkflowVersionSave) =>
    api
      .post<WorkflowVersionOut>(`/api/workflows/definitions/${defId}/versions`, body)
      .then((r) => r.data),
  listVersions: (defId: number) =>
    api
      .get<WorkflowVersionOut[]>(`/api/workflows/definitions/${defId}/versions`)
      .then((r) => r.data),
  publishVersion: (versionId: number) =>
    api
      .post<WorkflowVersionOut>(`/api/workflows/versions/${versionId}/publish`)
      .then((r) => r.data),

  // ---- 实例 ----
  instances: (status?: string) =>
    api
      .get<WorkflowInstanceOut[]>("/api/workflows/instances", {
        params: status ? { status } : {},
      })
      .then((r) => r.data),
  start: (body: {
    definition_id: number;
    title: string;
    form_data?: Record<string, any>;
  }) =>
    api.post<WorkflowInstanceOut>("/api/workflows/instances", body).then((r) => r.data),
  getInstance: (id: number) =>
    api.get<WorkflowInstanceOut>(`/api/workflows/instances/${id}`).then((r) => r.data),
  instanceLogs: (id: number) =>
    api.get<WorkflowLogOut[]>(`/api/workflows/instances/${id}/logs`).then((r) => r.data),

  // ---- 流程中心四个视图 ----
  pending: () => api.get<WorkflowTaskOut[]>("/api/workflows/pending").then((r) => r.data),
  done: () => api.get<WorkflowTaskOut[]>("/api/workflows/done").then((r) => r.data),
  notified: () =>
    api.get<WorkflowTaskOut[]>("/api/workflows/notified").then((r) => r.data),
  mine: () => api.get<WorkflowInstanceOut[]>("/api/workflows/mine").then((r) => r.data),
  stats: () => api.get<WorkflowStatsOut>("/api/workflows/stats").then((r) => r.data),

  // ---- 审批动作 ----
  decide: (taskId: number, body: WorkflowReview) =>
    api
      .post<WorkflowInstanceOut>(`/api/workflows/tasks/${taskId}/decide`, body)
      .then((r) => r.data),
  transfer: (taskId: number, body: WorkflowTransfer) =>
    api
      .post<WorkflowInstanceOut>(`/api/workflows/tasks/${taskId}/transfer`, body)
      .then((r) => r.data),
  addsign: (instanceId: number, nodeId: string, body: WorkflowAddSign) =>
    api
      .post<WorkflowInstanceOut>(
        `/api/workflows/instances/${instanceId}/nodes/${nodeId}/addsign`,
        body
      )
      .then((r) => r.data),
  withdraw: (instanceId: number) =>
    api
      .post<WorkflowInstanceOut>(`/api/workflows/instances/${instanceId}/withdraw`)
      .then((r) => r.data),
  urge: (instanceId: number, body: WorkflowUrge = {}) =>
    api
      .post<{ urged: number }>(`/api/workflows/instances/${instanceId}/urge`, body)
      .then((r) => r.data),
};

export const sigApi = {
  list: (refType: string, refId: number) =>
    api.get<SignatureOut[]>(`/api/signatures/${refType}/${refId}`).then((r) => r.data),
  create: (body: any) => api.post<SignatureOut>("/api/signatures", body).then((r) => r.data),
};

// 运维中心：管理员视角的系统级运行概览
export const opsApi = {
  overview: () =>
    api.get<OpsOverviewOut>("/api/ops/overview").then((r) => r.data),
};

// 报表中心：个人视图恒返回，组织级聚合需 report:view
export const reportApi = {
  overview: (days?: number) =>
    api
      .get<DashboardOut>("/api/dashboard", { params: days ? { days } : {} })
      .then((r) => r.data),
  // 经鉴权端点下载 zip（api 实例自动附带 Bearer 令牌，避免直链绕过权限）
  exportCsv: async (days: number) => {
    const res = await api.get<Blob>("/api/dashboard/export", {
      params: { days },
      responseType: "blob",
    });
    const url = URL.createObjectURL(res.data);
    const a = document.createElement("a");
    a.href = url;
    a.download = `zk-oa-dashboard-${days}d.zip`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },

  // ---- 多维数据立方体：按维度聚合指定指标（需 report:view）----
  cube: (params: {
    metrics?: string; // 逗号分隔：attendance,expense,workflow,official_doc
    dimension?: string;
    start?: string;
    end?: string;
  } = {}) =>
    api
      .get<{
        dimension: string;
        start: string;
        end: string;
        data: Record<string, any[]>;
      }>("/api/dashboard/cube", { params })
      .then((r) => r.data),

  // ---- 趋势分析：近 N 天日趋势 + 7 天移动平均（需 report:view）----
  trends: (params: { days?: number; metrics?: string } = {}) =>
    api
      .get<{
        days: number;
        start: string;
        end: string;
        trends: Record<string, any[]>;
      }>("/api/dashboard/trends", { params })
      .then((r) => r.data),
};

// 建模引擎：自定义实体 + 实体数据（filters 以 JSON 字符串传递）
export const modelApi = {
  entities: () =>
    api.get<ModelEntityOut[]>("/api/models/entities").then((r) => r.data),
  entity: (id: number) =>
    api.get<ModelEntityOut>(`/api/models/entities/${id}`).then((r) => r.data),
  createEntity: (body: any) =>
    api.post<ModelEntityOut>("/api/models/entities", body).then((r) => r.data),
  updateEntity: (id: number, body: any) =>
    api.patch<ModelEntityOut>(`/api/models/entities/${id}`, body).then((r) => r.data),
  removeEntity: (id: number) =>
    api.delete<{ message: string }>(`/api/models/entities/${id}`).then((r) => r.data),
  records: (
    entityId: number,
    params: { filters?: Record<string, any>; q?: string; offset?: number; limit?: number } = {}
  ) => {
    const { filters, ...rest } = params;
    return api
      .get<ModelRecordsPage>(`/api/models/entities/${entityId}/records`, {
        params: { ...rest, ...(filters ? { filters: JSON.stringify(filters) } : {}) },
      })
      .then((r) => r.data);
  },
  createRecord: (entityId: number, data: Record<string, any>) =>
    api
      .post<ModelRecordOut>(`/api/models/entities/${entityId}/records`, { data })
      .then((r) => r.data),
  updateRecord: (recordId: number, data: Record<string, any>) =>
    api
      .patch<ModelRecordOut>(`/api/models/records/${recordId}`, { data })
      .then((r) => r.data),
  removeRecord: (recordId: number) =>
    api.delete<{ message: string }>(`/api/models/records/${recordId}`).then((r) => r.data),
  stats: () => api.get<ModelStatsOut>("/api/models/stats").then((r) => r.data),
};

// 日志中心：审计日志（读侧聚合，写入由后端审计中间件自动完成）
export const auditApi = {
  logs: (params: {
    actor_id?: number;
    module?: string;
    action?: string;
    status?: string;
    q?: string;
    start?: string;
    end?: string;
    offset?: number;
    limit?: number;
  } = {}) =>
    api.get<AuditLogsPage>("/api/audit/logs", { params }).then((r) => r.data),
  stats: () => api.get<AuditStatsOut>("/api/audit/stats").then((r) => r.data),
  purge: (days: number) =>
    api
      .post<{ deleted: number; before: string }>("/api/audit/purge", { days })
      .then((r) => r.data),

  // ---- 导出 CSV（沿用当前筛选条件，blob 下载）----
  exportCsv: async (params: {
    module?: string;
    action?: string;
    status?: string;
    start?: string;
    end?: string;
    limit?: number;
  } = {}) => {
    const res = await api.get<Blob>("/api/audit/export", {
      params,
      responseType: "blob",
    });
    const stamp = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, "");
    const url = URL.createObjectURL(res.data);
    const a = document.createElement("a");
    a.href = url;
    a.download = `audit_logs_${stamp}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
};

// 内容引擎：文档中心 + 文件上传（上传走 multipart，需清除默认 JSON content-type）
export const docApi = {
  list: (params: { category?: string; q?: string; offset?: number; limit?: number } = {}) =>
    api.get<DocumentsPage>("/api/documents", { params }).then((r) => r.data),
  upload: (form: { title: string; category: string; description: string; file: File }) => {
    const fd = new FormData();
    fd.append("title", form.title);
    fd.append("category", form.category);
    fd.append("description", form.description);
    fd.append("file", form.file);
    return api
      .post<DocumentOut>("/api/documents", fd, {
        headers: { "Content-Type": undefined } as any,
      })
      .then((r) => r.data);
  },
  update: (id: number, body: DocumentUpdate) =>
    api.patch<DocumentOut>(`/api/documents/${id}`, body).then((r) => r.data),
  remove: (id: number) =>
    api.delete<{ message: string }>(`/api/documents/${id}`).then((r) => r.data),
  // ---- 版本历史：上传新文件追加版本，旧版本保留可回溯 ----
  versions: (docId: number) =>
    api.get<DocumentVersionOut[]>(`/api/documents/${docId}/versions`).then((r) => r.data),
  addVersion: (docId: number, file: File, note: string) => {
    const fd = new FormData();
    fd.append("note", note);
    fd.append("file", file);
    return api
      .post<DocumentVersionOut>(`/api/documents/${docId}/versions`, fd, {
        headers: { "Content-Type": undefined } as any,
      })
      .then((r) => r.data);
  },
  // 下载指定历史版本（经鉴权端点取 blob，避免直链绕过权限）
  downloadVersion: async (v: DocumentVersionOut) => {
    const res = await api.get<Blob>(v.file_url, { responseType: "blob" });
    const url = URL.createObjectURL(res.data);
    const a = document.createElement("a");
    a.href = url;
    a.download = `v${v.version}.${v.file_type}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
  // 经鉴权端点流式下载（api 实例自动附带 Bearer 令牌，避免直链绕过权限）
  download: async (doc: { file_url: string; title: string; file_type: string }) => {
    const res = await api.get<Blob>(doc.file_url, { responseType: "blob" });
    const blob = res.data;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${doc.title}.${doc.file_type}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
};

// 消息中心：通知收件箱（用户仅可见自己的；标记已读/全部已读）
export const msgApi = {
  list: (params: { unread_only?: boolean; limit?: number; offset?: number } = {}) =>
    api
      .get<NotificationsPage>("/api/notifications", { params })
      .then((r) => r.data),
  markRead: (id: number) =>
    api
      .post<{ message: string }>(`/api/notifications/${id}/read`)
      .then((r) => r.data),
  markAllRead: () =>
    api
      .post<{ message: string }>("/api/notifications/read-all")
      .then((r) => r.data),
};
