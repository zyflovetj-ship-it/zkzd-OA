// 公文管理：收发文登记 → 传阅 → 归档。
// 类型与接口封装全部收敛在本模块内（不改动共享 types.ts）。
import api from "./client";

// ---- 业务枚举 ----
export type OfficialDocDirection = "in" | "out"; // in=收文、out=发文
export type OfficialDocSecrecy = "public" | "internal" | "secret";
export type OfficialDocStatus = "draft" | "pending" | "circulated" | "archived";

// ---- 公文附件（来自文档中心的引用） ----
export interface OfficialDocAttachment {
  document_id: number;
  title: string;
  file_url: string;
}

// ---- 公文主体 ----
export interface OfficialDoc {
  id: number;
  doc_no: string;
  title: string;
  direction: OfficialDocDirection;
  from_org: string;
  to_org: string;
  secrecy: OfficialDocSecrecy;
  status: OfficialDocStatus;
  content: string;
  attachments: OfficialDocAttachment[];
  owner_id: number;
  owner_name: string;
  read_count: number;
  published_at: string | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface OfficialDocPage {
  items: OfficialDoc[];
  total: number;
  offset: number;
  limit: number;
}

export interface OfficialDocListParams {
  direction?: OfficialDocDirection; // 不传表示全部
  status?: OfficialDocStatus | "all"; // "all" 或不传表示全部
  q?: string;
  offset?: number;
  limit?: number;
}

// 登记 / 编辑请求体（部分更新时字段可省略）
export interface OfficialDocPayload {
  doc_no: string;
  title: string;
  direction: OfficialDocDirection;
  from_org?: string;
  to_org?: string;
  secrecy?: OfficialDocSecrecy;
  content?: string;
  attachments?: OfficialDocAttachment[];
}

// 传阅请求体：user_ids 为空数组 = 广播给全体用户
export interface OfficialDocCirculateBody {
  user_ids: number[];
  remark: string;
}

// ---- 附件候选（文档中心） ----
export interface AttachmentCandidate {
  id: number;
  title: string;
  file_url: string;
  file_type: string;
}

export interface AttachmentCandidatePage {
  items: AttachmentCandidate[];
  total: number;
  offset: number;
  limit: number;
}

// ---- 传阅人员候选 ----
export interface UserCandidate {
  id: number;
  username: string;
  full_name: string;
  is_active: boolean;
}

// ---- 全文检索命中项 ----
export interface OfficialDocSearchHit {
  id: number;
  doc_no: string;
  title: string;
  direction: OfficialDocDirection;
  status: OfficialDocStatus;
  from_org: string;
  to_org: string;
  owner_name: string;
  created_at: string;
  snippet: string; // 正文前 200 字摘要
}

export interface OfficialDocSearchPage {
  items: OfficialDocSearchHit[];
  total: number;
  offset: number;
  limit: number;
}

// ---- 文号预览 ----
export interface DocNoPreview {
  doc_no: string;
  prefix: string;
  year: number;
  seq: number;
}

// ---- 流转时间线 ----
export interface OfficialDocTimelineItem {
  id: number;
  action: string; // create / circulate / archive
  from_status: string | null;
  to_status: string | null;
  actor_name: string;
  remark: string;
  created_at: string;
}

export const officialDocsApi = {
  // 列表：direction/status/q + 分页
  list: (params: OfficialDocListParams = {}) =>
    api.get<OfficialDocPage>("/api/official-docs", { params }).then((r) => r.data),

  // 详情
  get: (id: number) =>
    api.get<OfficialDoc>(`/api/official-docs/${id}`).then((r) => r.data),

  // 登记（文号唯一，重复 409）
  create: (body: OfficialDocPayload) =>
    api.post<OfficialDoc>("/api/official-docs", body).then((r) => r.data),

  // 编辑（部分更新，已归档 422）
  update: (id: number, body: Partial<OfficialDocPayload>) =>
    api.patch<OfficialDoc>(`/api/official-docs/${id}`, body).then((r) => r.data),

  // 删除（已归档 422）
  remove: (id: number) =>
    api.delete<{ message: string }>(`/api/official-docs/${id}`).then((r) => r.data),

  // 传阅：成功后 status → circulated，read_count = 通知到的人数
  circulate: (id: number, body: OfficialDocCirculateBody) =>
    api.post<OfficialDoc>(`/api/official-docs/${id}/circulate`, body).then((r) => r.data),

  // 归档：status 须为 circulated/pending（草稿 422）
  archive: (id: number) =>
    api.post<OfficialDoc>(`/api/official-docs/${id}/archive`).then((r) => r.data),

  // ---- 全文检索：跨 文号/标题/正文/来往单位/登记人，按相关度排序 ----
  search: (q: string, params: { direction?: OfficialDocDirection; status?: string; offset?: number; limit?: number } = {}) =>
    api
      .get<OfficialDocSearchPage>("/api/official-docs/search", {
        params: { q, ...params },
      })
      .then((r) => r.data),

  // ---- 文号预览：登记页实时显示「下一个可用文号」（不创建） ----
  nextDocNo: (direction: OfficialDocDirection = "in") =>
    api
      .get<DocNoPreview>("/api/official-docs/next-doc-no", { params: { direction } })
      .then((r) => r.data),

  // ---- 流转时间线：登记 → 传阅 → 归档 ----
  timeline: (id: number) =>
    api
      .get<OfficialDocTimelineItem[]>(`/api/official-docs/${id}/timeline`)
      .then((r) => r.data),

  // 附件候选：文档中心（表单多选用）
  attachmentCandidates: () =>
    api
      .get<AttachmentCandidatePage>("/api/documents", { params: { limit: 100 } })
      .then((r) => r.data),

  // 传阅人员候选
  userCandidates: () =>
    api.get<UserCandidate[]>("/api/users", { params: { limit: 200 } }).then((r) => r.data),

  // 附件下载：走鉴权 axios 实例拉 blob（自动附带 Bearer 令牌），再触发浏览器保存
  downloadAttachment: async (att: OfficialDocAttachment) => {
    const res = await api.get<Blob>(att.file_url, { responseType: "blob" });
    const url = URL.createObjectURL(res.data);
    const path = att.file_url.split("?")[0];
    const dot = path.lastIndexOf(".");
    const ext = dot > 0 ? path.slice(dot) : "";
    const name =
      ext && !att.title.toLowerCase().endsWith(ext.toLowerCase())
        ? `${att.title}${ext}`
        : att.title;
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
};
