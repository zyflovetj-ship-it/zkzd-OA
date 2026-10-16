// 报销模块：类型定义 + 接口封装。
// 为避免改动共享 types.ts，本模块所需类型全部在此声明；令牌由 client 实例自动附加。
import api from "./client";

export type ExpenseClaimType = "travel" | "daily" | "entertain" | "other";
export type ExpenseStatus = "draft" | "submitted" | "approved" | "rejected" | "paid";

/** 附件引用：文档中心条目快照（提交时由所选文档组装而成） */
export interface ExpenseAttachment {
  document_id: number;
  title: string;
  file_url: string;
}

export interface Expense {
  id: number;
  code: string;
  user_id: number;
  user_name: string;
  claim_type: ExpenseClaimType;
  amount: number;
  occur_date: string; // YYYY-MM-DD
  description: string;
  attachments: ExpenseAttachment[];
  status: ExpenseStatus;
  workflow_instance_id: number | null;
  workflow_code: string;
  approver_id: number | null;
  approver_name: string;
  review_comment: string;
  reviewed_at: string | null;
  paid_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ExpensePage {
  items: Expense[];
  total: number;
  offset: number;
  limit: number;
  /** 当前筛选范围内的金额合计 */
  sum_amount: number;
}

/** 统计分桶：by_status 存状态码、by_type 存类型码（后端契约字段名统一为 status） */
export interface ExpenseStatsBucket {
  status: string;
  count: number;
  amount: number;
}

export interface ExpenseStats {
  month: string;
  total_count: number;
  total_amount: number;
  pending_count: number;
  by_status: ExpenseStatsBucket[];
  by_type: ExpenseStatsBucket[];
}

export interface ExpenseListParams {
  status?: string;
  month?: string; // YYYY-MM
  q?: string;
  mine?: boolean;
  offset?: number;
  limit?: number;
}

/** 新建 / 编辑报销单的提交体（PATCH 字段与 POST 一致） */
export interface ExpenseInput {
  claim_type: ExpenseClaimType;
  amount: number;
  occur_date: string; // YYYY-MM-DD
  description: string;
  attachments: ExpenseAttachment[];
}

export interface ExpensePaidInput {
  paid: boolean;
  comment?: string;
}

export interface ExpenseImportResult {
  created: number;
  errors: string[];
}

// ---- 预算 / 额度 ----
export type BudgetStatus = "active" | "inactive" | "expired";

export interface Budget {
  id: number;
  name: string;
  code: string;
  total_amount: number;
  used_amount: number; // 按在途单据实时聚合（非缓存列）
  remaining: number;
  start_date: string; // YYYY-MM-DD
  end_date: string;
  department_id: number | null;
  category: ExpenseClaimType | null; // null = 全部类别
  status: BudgetStatus;
  created_at: string;
  updated_at: string;
}

export interface BudgetPage {
  items: Budget[];
  total: number;
  offset: number;
  limit: number;
}

export interface BudgetInput {
  name: string;
  code: string;
  total_amount: number;
  start_date: string;
  end_date: string;
  department_id?: number | null;
  category?: ExpenseClaimType | null;
  status?: BudgetStatus;
}

export interface QuotaCheck {
  has_budget: boolean;
  budget_id: number | null;
  quota_amount: number | null;
  remaining: number | null;
  exceeded: boolean;
  message: string;
}

// ---- 发票验真 ----
export interface InvoiceVerifyInput {
  invoice_no: string;
  invoice_code?: string;
  amount?: number;
  buyer_tax_no?: string;
}

export interface InvoiceCheck {
  name: string;
  passed: boolean;
  message: string;
}

export interface InvoiceVerifyResult {
  status: "verified" | "failed";
  checks: InvoiceCheck[];
}

// ---- 批量打款 ----
export interface BatchPayResult {
  id: number;
  success: boolean;
  code: string;
  error: string;
}

export interface BatchPayResponse {
  total: number;
  success: number;
  failed: number;
  results: BatchPayResult[];
}

/** 附件候选：文档中心条目（仅报销模块用到的字段） */
export interface ExpenseDocOption {
  id: number;
  title: string;
  file_url: string;
  file_type: string;
  file_size: number;
}

export interface ExpenseDocsPage {
  items: ExpenseDocOption[];
  total: number;
  offset: number;
  limit: number;
}

// 经鉴权端点下载 blob：api 实例自动附带 Bearer 令牌，避免直链绕过权限
function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// file_url 是需鉴权的接口地址，不含可靠文件名：按标题 + URL 扩展名推导下载名
function attachmentFilename(att: ExpenseAttachment): string {
  const path = att.file_url.split("?")[0];
  const last = path.slice(path.lastIndexOf("/") + 1);
  const dot = last.lastIndexOf(".");
  const ext = dot > 0 && last.length - dot <= 6 ? last.slice(dot) : "";
  const base = att.title || `附件${att.document_id}`;
  return ext && !base.toLowerCase().endsWith(ext.toLowerCase()) ? `${base}${ext}` : base;
}

export const expensesApi = {
  // ---- 列表 / 统计 / 详情 ----
  list: (params: ExpenseListParams = {}) =>
    api.get<ExpensePage>("/api/expenses", { params }).then((r) => r.data),
  stats: (month?: string) =>
    api
      .get<ExpenseStats>("/api/expenses/stats", { params: month ? { month } : {} })
      .then((r) => r.data),
  get: (id: number) => api.get<Expense>(`/api/expenses/${id}`).then((r) => r.data),

  // ---- 新建 / 编辑 / 删除（仅草稿可改，草稿与已驳回可删） ----
  create: (body: ExpenseInput) =>
    api.post<Expense>("/api/expenses", body).then((r) => r.data),
  update: (id: number, body: ExpenseInput) =>
    api.patch<Expense>(`/api/expenses/${id}`, body).then((r) => r.data),
  remove: (id: number) =>
    api.delete<{ message: string }>(`/api/expenses/${id}`).then((r) => r.data),

  // ---- 流程动作 ----
  // 提交：后端自动发布内置审批流程 expense-claim；无附件或流程未发布会返回 422
  submit: (id: number) =>
    api.post<Expense>(`/api/expenses/${id}/submit`).then((r) => r.data),
  // 打款 / 撤销打款（需 expense:manage，仅 approved 可打款）
  markPaid: (id: number, body: ExpensePaidInput) =>
    api.post<Expense>(`/api/expenses/${id}/paid`, body).then((r) => r.data),

  // ---- 批量打款（需 expense:manage）：逐条处理，返回成功/失败明细 ----
  batchPay: (expenseIds: number[]) =>
    api.post<BatchPayResponse>("/api/expenses/batch-pay", {
      expense_ids: expenseIds,
    }).then((r) => r.data),

  // ---- 预算 / 额度（需 expense:manage）----
  budgets: (params: { status?: string; offset?: number; limit?: number } = {}) =>
    api.get<BudgetPage>("/api/expenses/budgets", { params }).then((r) => r.data),
  createBudget: (body: BudgetInput) =>
    api.post<Budget>("/api/expenses/budgets", body).then((r) => r.data),
  updateBudget: (id: number, body: Partial<BudgetInput>) =>
    api.patch<Budget>(`/api/expenses/budgets/${id}`, body).then((r) => r.data),
  // 额度预检：报销页在填金额/类别后即可提示剩余额度
  quotaCheck: (params: { amount: number; occur_date: string; category?: string }) =>
    api.get<QuotaCheck>("/api/expenses/budgets/quota-check", { params }).then((r) => r.data),

  // ---- 发票验真（本地校验：格式/唯一性/买方税号校验位）----
  verifyInvoice: (body: InvoiceVerifyInput) =>
    api.post<InvoiceVerifyResult>("/api/expenses/invoice/verify", body).then((r) => r.data),

  // ---- Excel 导出（blob 下载，文件名 expenses-{month|all}.xlsx） ----
  exportExcel: async (month?: string) => {
    const res = await api.get<Blob>("/api/expenses/export", {
      params: month ? { month } : {},
      responseType: "blob",
    });
    saveBlob(res.data, `expenses-${month || "all"}.xlsx`);
  },

  // ---- Excel 导入（multipart，字段名 file；表头需含 金额/日期/类型/说明） ----
  importExcel: async (file: File): Promise<ExpenseImportResult> => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await api.post<ExpenseImportResult>("/api/expenses/import", fd, {
      // multipart 的 boundary 由浏览器生成：需清除实例默认的 application/json
      headers: { "Content-Type": undefined },
    });
    return res.data;
  },

  // ---- 附件候选：文档中心（需 doc:view，所有角色可用） ----
  docOptions: (limit = 100) =>
    api
      .get<ExpenseDocsPage>("/api/documents", { params: { limit } })
      .then((r) => r.data),

  // ---- 导入模板下载 ----
  downloadTemplate: async () => {
    const res = await api.get<Blob>("/api/expenses/import/template", {
      responseType: "blob",
    });
    saveBlob(res.data, "expense_import_template.xlsx");
  },

  // ---- 附件下载：file_url 是需鉴权的接口地址，走 api 实例拉 blob ----
  downloadAttachment: async (att: ExpenseAttachment) => {
    const res = await api.get<Blob>(att.file_url, { responseType: "blob" });
    saveBlob(res.data, attachmentFilename(att));
  },
};
