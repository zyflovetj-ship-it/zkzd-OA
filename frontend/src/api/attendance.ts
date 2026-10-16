// 考勤模块接口封装：打卡 / 个人月度考勤 / 全员记录修正 / 统计 / 加班 / 班次设置 / 导出。
// 类型全部定义在本模块内（不改共享 types.ts），令牌由 client 实例自动附加。
import api from "./client";

/** 班次设置（workdays 为 ISO 星期：1=周一 … 7=周日） */
export interface AttendanceSettings {
  id: number;
  name: string;
  work_start: string; // "HH:MM"
  work_end: string; // "HH:MM"
  late_grace_minutes: number;
  workdays: number[];
  updated_at: string | null;
}

/** 班次设置更新体（全部可选） */
export interface AttendanceSettingsUpdate {
  name?: string;
  work_start?: string;
  work_end?: string;
  late_grace_minutes?: number;
  workdays?: number[];
}

/** 打卡结果（同日第三次返回 422，message 为后端提示） */
export interface ClockResult {
  day: string;
  check_in: string | null;
  check_out: string | null;
  status: string;
  late_minutes: number;
  early_minutes: number;
  message: string;
  // GPS字段
  check_in_lat: number | null;
  check_in_lng: number | null;
  check_out_lat: number | null;
  check_out_lng: number | null;
  check_in_address: string | null;
  check_out_address: string | null;
  is_field_work: boolean;
  field_work_address: string | null;
  field_work_note: string | null;
}

/** 单条考勤记录 */
export interface AttendanceRecord {
  id: number;
  user_id: number;
  user_name: string;
  day: string;
  check_in: string | null;
  check_out: string | null;
  status: string; // normal|late|early|absent|leave|travel|remote
  late_minutes: number;
  early_minutes: number;
  work_minutes: number;
  source: string;
  note: string;
  // GPS字段
  check_in_lat: number | null;
  check_in_lng: number | null;
  check_out_lat: number | null;
  check_out_lng: number | null;
  check_in_address: string | null;
  check_out_address: string | null;
  is_field_work: boolean;
  field_work_address: string | null;
  field_work_note: string | null;
}

/** 月度汇总 */
export interface AttendanceSummary {
  month: string;
  expected_workdays: number;
  present_days: number;
  late_days: number;
  early_days: number;
  absent_days: number;
  leave_days: number;
  travel_days: number;
  remote_days: number;
  overtime_hours: number;
  avg_work_minutes: number;
}

/** GET /api/attendance/me 响应 */
export interface MyAttendance {
  records: AttendanceRecord[];
  summary: AttendanceSummary;
}

/** GET /api/attendance/records 分页响应 */
export interface AttendanceRecordsPage {
  items: AttendanceRecord[];
  total: number;
  offset: number;
  limit: number;
}

/** PATCH /api/attendance/records/{id} 请求体 */
export interface AttendanceRecordUpdate {
  status?: string;
  note?: string;
  check_in?: string;
  check_out?: string;
  // GPS字段
  check_in_lat?: number;
  check_in_lng?: number;
  check_out_lat?: number;
  check_out_lng?: number;
  check_in_address?: string;
  check_out_address?: string;
  is_field_work?: boolean;
  field_work_address?: string;
  field_work_note?: string;
}

/** GET /api/attendance/stats 的单行统计 */
export interface AttendanceStatsRow {
  user_id: number;
  username: string;
  full_name: string;
  present_days: number;
  late_days: number;
  early_days: number;
  absent_days: number;
  leave_days: number;
  overtime_hours: number;
}

/** GET /api/attendance/stats 响应 */
export interface AttendanceStats {
  month: string;
  expected_workdays: number;
  rows: AttendanceStatsRow[];
  pending_overtime: number;
}

/** 加班申请 */
export interface Overtime {
  id: number;
  user_id: number;
  user_name: string;
  day: string;
  hours: number;
  reason: string;
  status: "pending" | "approved" | "rejected";
  approver_id: number | null;
  review_comment: string;
  reviewed_at: string | null;
  created_at: string;
}

/** POST /api/attendance/overtime 请求体 */
export interface OvertimeCreate {
  day: string; // "YYYY-MM-DD"
  hours: number; // 0-24
  reason: string;
}

/** POST /api/attendance/overtime/{id}/review 请求体 */
export interface OvertimeReview {
  approve: boolean;
  comment?: string;
}

/** GET /api/attendance/records 查询参数 */
export interface AttendanceRecordsQuery {
  start: string; // "YYYY-MM-DD"
  end: string; // "YYYY-MM-DD"（必须是合法日期）
  user_id?: number;
  status?: string;
  offset?: number;
  limit?: number;
}

/** GET /api/attendance/overtime 查询参数（all=true 需 att:manage） */
export interface OvertimeQuery {
  all?: boolean;
  status?: string;
  offset?: number;
  limit?: number;
}

export interface AttendanceImportResult {
  created: number;
  updated: number;
  errors: string[];
  dry_run?: boolean;
  total?: number;
  linked_field_work?: number;
}

// ---- 外勤申请 ----
export interface FieldWorkOrder {
  id: number;
  user_id: number;
  user_name: string;
  start_date: string;
  end_date: string;
  address: string;
  purpose: string;
  remark: string;
  status: "pending" | "approved" | "rejected";
  approver_id: number | null;
  approver_name: string;
  review_comment: string;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface FieldWorkPage {
  items: FieldWorkOrder[];
  total: number;
  offset: number;
  limit: number;
}

export interface FieldWorkCreate {
  start_date: string;
  end_date: string;
  address: string;
  purpose?: string;
  remark?: string;
}

export interface FieldWorkReview {
  approve: boolean;
  comment?: string;
}

// ---- 考勤异常预警 ----
export interface AttendanceAlert {
  type: string;
  level: string;
  user_id: number;
  user_name: string;
  day?: string;
  period?: string;
  count: number;
  message: string;
}

export interface AttendanceAlertsOut {
  start: string;
  end: string;
  threshold: number;
  checked_users: number;
  total: number;
  by_type: { type: string; count: number }[];
  alerts: AttendanceAlert[];
}

export const attendanceApi = {
  // ---- 班次设置 ----
  settings: () =>
    api.get<AttendanceSettings>("/api/attendance/settings").then((r) => r.data),
  updateSettings: (body: AttendanceSettingsUpdate) =>
    api.put<AttendanceSettings>("/api/attendance/settings", body).then((r) => r.data),

  // ---- 打卡（支持 GPS 参数） ----
  clock: (params?: { lat?: number; lng?: number; address?: string; is_field_work?: boolean; field_work_address?: string; field_work_note?: string }) =>
    api.post<ClockResult>("/api/attendance/clock", params).then((r) => r.data),

  // ---- 我的月度考勤（month 必填，YYYY-MM） ----
  me: (month: string) =>
    api.get<MyAttendance>("/api/attendance/me", { params: { month } }).then((r) => r.data),

  // ---- 全员考勤记录（需 att:manage） ----
  records: (params: AttendanceRecordsQuery) =>
    api.get<AttendanceRecordsPage>("/api/attendance/records", { params }).then((r) => r.data),
  updateRecord: (id: number, body: AttendanceRecordUpdate) =>
    api.patch<AttendanceRecord>(`/api/attendance/records/${id}`, body).then((r) => r.data),

  // ---- 月度统计（需 att:manage） ----
  stats: (month: string) =>
    api.get<AttendanceStats>("/api/attendance/stats", { params: { month } }).then((r) => r.data),

  // ---- 加班 ----
  overtime: (params: OvertimeQuery = {}) =>
    api.get<Overtime[]>("/api/attendance/overtime", { params }).then((r) => r.data),
  createOvertime: (body: OvertimeCreate) =>
    api.post<Overtime>("/api/attendance/overtime", body).then((r) => r.data),
  reviewOvertime: (id: number, body: OvertimeReview) =>
    api.post<Overtime>(`/api/attendance/overtime/${id}/review`, body).then((r) => r.data),

  // ---- 导出 xlsx（经鉴权端点流式下载，api 实例自动附带 Bearer 令牌） ----
  exportMonth: async (month: string) => {
    const res = await api.get<Blob>("/api/attendance/export", {
      params: { month },
      responseType: "blob",
    });
    const url = URL.createObjectURL(res.data);
    const a = document.createElement("a");
    a.href = url;
    a.download = `attendance-${month}.xlsx`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },

  // ---- 导入 xlsx ----
  importMonth: async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await api.post<AttendanceImportResult>("/api/attendance/import", fd, {
      headers: { "Content-Type": undefined } as any,
    });
    return res.data;
  },

  // ---- 导入预检（dry_run=true） ----
  importPreview: async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await api.post<AttendanceImportResult>("/api/attendance/import", fd, {
      headers: { "Content-Type": undefined } as any,
      params: { dry_run: true },
    });
    return res.data;
  },

  // ---- 导入模板下载 ----
  downloadTemplate: async () => {
    const res = await api.get<Blob>("/api/attendance/import/template", {
      responseType: "blob",
    });
    const url = URL.createObjectURL(res.data);
    const a = document.createElement("a");
    a.href = url;
    a.download = "attendance_import_template.xlsx";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },

  // ---- 外勤申请 ----
  fieldWork: (params?: { status?: string; start?: string; end?: string; mine?: boolean; offset?: number; limit?: number }) =>
    api.get<FieldWorkPage>("/api/attendance/field-work", { params }).then((r) => r.data),

  createFieldWork: (body: FieldWorkCreate) =>
    api.post<FieldWorkOrder>("/api/attendance/field-work", body).then((r) => r.data),

  reviewFieldWork: (id: number, body: FieldWorkReview) =>
    api.post<FieldWorkOrder>(`/api/attendance/field-work/${id}/review`, body).then((r) => r.data),

  // ---- 考勤异常预警 ----
  alerts: (params: { start: string; end: string; threshold?: number; limit?: number }) =>
    api.get<AttendanceAlertsOut>("/api/attendance/alerts", { params }).then((r) => r.data),

  notifyAlerts: (params?: { start?: string; end?: string; threshold?: number }) =>
    api.post<{ alert_count: number; notified_users: number }>("/api/attendance/alerts/notify", params).then((r) => r.data),
};