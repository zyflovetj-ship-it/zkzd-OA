// 审批委托（代审）：本页面所需的类型 + 接口封装。
// 委托生效后，时段内委托人名下的审批任务会被分派给受托人。
import api from "./client";

/** 一条委托记录（GET/POST/PATCH 返回体） */
export interface Delegation {
  id: number;
  from_user_id: number;
  from_user_name: string;
  to_user_id: number;
  to_user_name: string;
  definition_id: number | null; // null = 全部流程
  definition_name: string;
  start_at: string; // "YYYY-MM-DDTHH:mm:ss"（本地时间语义，不带时区）
  end_at: string;
  active: boolean;
  created_at: string;
}

/** 新建委托请求体 */
export interface DelegationCreate {
  to_user_id: number;
  start_at: string;
  end_at: string;
  definition_id?: number | null;
  active?: boolean;
}

/** 编辑委托请求体（字段均可选） */
export interface DelegationUpdate {
  to_user_id?: number;
  start_at?: string;
  end_at?: string;
  definition_id?: number | null;
  active?: boolean;
}

/** 冲突预检命中项：overlap=时段重叠，cycle=委托成环（A→B→…→A） */
export interface DelegationConflict {
  type: "overlap" | "cycle";
  message: string;
  conflict_id?: number;
  chain?: number[];
}

export interface DelegationConflictCheck {
  conflicts: DelegationConflict[];
  blocking: boolean;
}

export const delegationsApi = {
  /** all=true 需要管理员或 wf:monitor 权限；默认（false）只返回自己的委托 */
  list: (all: boolean = false) =>
    api
      .get<Delegation[]>("/api/workflows/delegations", { params: { all } })
      .then((r) => r.data),
  create: (body: DelegationCreate) =>
    api.post<Delegation>("/api/workflows/delegations", body).then((r) => r.data),
  update: (id: number, body: DelegationUpdate) =>
    api.patch<Delegation>(`/api/workflows/delegations/${id}`, body).then((r) => r.data),
  remove: (id: number) =>
    api
      .delete<{ message: string }>(`/api/workflows/delegations/${id}`)
      .then((r) => r.data),
  /** 冲突预检（dry-run）：不创建委托，返回重叠/成环冲突供表单实时提示 */
  checkConflicts: (body: DelegationCreate) =>
    api
      .post<DelegationConflictCheck>("/api/workflows/delegations/check-conflicts", body)
      .then((r) => r.data),
};
