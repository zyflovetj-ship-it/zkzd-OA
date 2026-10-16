"""Pydantic 校验 Schema（边界处校验，绝不信任客户端数据）。"""
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

# ---------- 通用 ----------
class Message(BaseModel):
    message: str


# ---------- 认证 ----------
class LoginRequest(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    password: str = Field(min_length=6, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


# ---------- 用户 / 角色 / 部门 ----------
class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    password: str = Field(min_length=6, max_length=128)
    full_name: str = Field(default="", max_length=100)
    email: str = Field(default="", max_length=120)
    role_id: int
    department_id: int | None = None


class UserUpdate(BaseModel):
    # username 必须存在：服务层 UserService.update 会读取它做重名校验与改名，
    # 缺字段会让每次 PATCH /api/users/{id} 抛 AttributeError → 500。
    username: str | None = Field(default=None, min_length=2, max_length=50)
    full_name: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=120)
    role_id: int | None = None
    department_id: int | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=6, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    full_name: str
    email: str
    is_active: bool
    role_id: int
    role_name: str = ""  # 路由层注入，避免前端用 role_id 硬编码判断权限
    department_id: int | None
    created_at: datetime


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    parent_id: int | None = None
    manager_id: int | None = None


class DepartmentUpdate(BaseModel):
    name: str | None = None
    parent_id: int | None = None
    manager_id: int | None = None


class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    parent_id: int | None
    manager_id: int | None
    created_at: datetime


# ---------- 组织权限中心（权限 / 菜单 / 角色范围） ----------
class RoleCreate(BaseModel):
    """新建角色：name 为稳定英文标识（小写字母开头），不可与已有角色重名。"""
    name: str = Field(min_length=2, max_length=50, pattern="^[a-z][a-z0-9_]*$")
    description: str = Field(default="", max_length=200)
    data_scope: str = Field(default="all", pattern="^(all|dept|self)$")


class RoleUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=200)
    data_scope: str | None = Field(default=None, pattern="^(all|dept|self)$")


class RoleOut(BaseModel):
    """角色对外视图：对齐前端 Role 类型。"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    data_scope: str


class PermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    category: str
    type: str
    description: str


class PermissionCreate(BaseModel):
    code: str = Field(min_length=2, max_length=100, pattern="^[a-z0-9:_]+$")
    name: str = Field(min_length=1, max_length=100)
    category: str = Field(default="general", max_length=50)
    type: str = Field(default="operation", pattern="^(menu|operation)$")
    description: str = Field(default="", max_length=200)


class PermissionAssign(BaseModel):
    permission_id: int


class MenuOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    parent_id: int | None
    name: str
    path: str
    icon: str
    order: int
    permission_code: str


class MenuCreate(BaseModel):
    parent_id: int | None = None
    name: str = Field(min_length=1, max_length=100)
    path: str = Field(default="", max_length=200)
    icon: str = Field(default="", max_length=50)
    order: int = 0
    permission_code: str = Field(default="", max_length=100)


class MenuUpdate(BaseModel):
    parent_id: int | None = None
    name: str | None = Field(default=None, max_length=100)
    path: str | None = Field(default=None, max_length=200)
    icon: str | None = Field(default=None, max_length=50)
    order: int | None = None
    permission_code: str | None = Field(default=None, max_length=100)


class MeOut(BaseModel):
    """登录态概览：用户、角色、权限码、数据范围与可见菜单。"""
    id: int
    username: str
    full_name: str
    email: str
    is_active: bool
    role_id: int
    role_name: str
    department_id: int | None
    created_at: datetime
    permissions: list[str] = []
    data_scope: str = "all"


# ---------- 考勤 / 请假 ----------
class LeaveCreate(BaseModel):
    leave_type: str = Field(pattern="^(annual|sick|personal|other)$")
    start_date: date
    end_date: date
    reason: str = Field(default="", max_length=1000)


class LeaveReview(BaseModel):
    approve: bool
    rejection_reason: str | None = Field(default=None, max_length=500)


class LeaveOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    leave_type: str
    start_date: date
    end_date: date
    reason: str
    status: str
    approver_id: int | None
    rejection_reason: str
    reviewed_at: datetime | None
    created_at: datetime


# ---------- 公告 / 文档 ----------
class AnnouncementCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(default="", max_length=10000)
    pinned: bool = False
    published: bool = True
    # 关联文档中心附件：[{document_id, title, file_url}]
    attachments: list[dict] = Field(default=[], max_length=50)
    expires_at: datetime | None = None


class AnnouncementUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    content: str | None = Field(default=None, max_length=10000)
    pinned: bool | None = None
    published: bool | None = None
    attachments: list[dict] | None = Field(default=None, max_length=50)
    expires_at: datetime | None = None


class AnnouncementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content: str
    author_id: int
    pinned: bool
    published: bool
    attachments: list = []
    expires_at: datetime | None = None
    read_count: int = 0
    created_at: datetime
    updated_at: datetime


class DocumentCreate(BaseModel):
    """纯 JSON 创建（无文件，预留给外部系统对接）；常规上传走 multipart 端点。"""
    title: str = Field(min_length=1, max_length=200)
    category: str = Field(default="general", max_length=50)
    description: str = Field(default="", max_length=500)
    file_url: str = Field(default="", max_length=500)


class DocumentUpdate(BaseModel):
    """文档元数据更新：标题 / 分类 / 描述（文件本身不可经此改写，需重新上传）。"""
    title: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=500)


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    category: str
    file_type: str
    file_size: int
    description: str
    file_url: str
    current_version: int = 1
    owner_id: int
    owner_name: str
    created_at: datetime
    updated_at: datetime


class DocumentsPage(BaseModel):
    """文档列表分页结果（按标题搜索 + 分类过滤，检索直接下推数据库）。"""
    items: list[DocumentOut]
    total: int
    offset: int
    limit: int


# ---------- 审批工作流 ----------
# ---------- 表单定义 ----------
class FormDefinitionCreate(BaseModel):
    code: str = Field(min_length=2, max_length=60)
    name: str = Field(min_length=1, max_length=120)
    # [{"key":"amount","label":"金额","type":"number","required":true,"options":[]}]
    fields: list[dict] = Field(default=[], max_length=200)


class FormDefinitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    fields: list
    created_at: datetime
    updated_at: datetime


# ---------- 流程定义 / 版本 ----------
class WorkflowDefinitionCreate(BaseModel):
    code: str = Field(min_length=2, max_length=60)
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(default="general", max_length=50)
    description: str = Field(default="", max_length=300)
    icon: str = Field(default="", max_length=40)


class WorkflowDefinitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    category: str
    description: str
    icon: str
    status: str
    current_version: int
    created_at: datetime
    updated_at: datetime


class WorkflowVersionSave(BaseModel):
    """保存流程图（草稿）。graph 为节点/连线结构。"""
    graph: dict
    form_id: int | None = None
    remark: str = Field(default="", max_length=300)


class WorkflowVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    definition_id: int
    version: int
    graph: dict
    form_id: int | None
    status: str
    published_at: datetime | None
    remark: str
    created_at: datetime


# ---------- 流程实例 / 任务 ----------
class WorkflowInstanceCreate(BaseModel):
    definition_id: int
    title: str = Field(min_length=1, max_length=200)
    form_data: dict = Field(default={})


class WorkflowTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    instance_id: int
    node_id: str
    node_name: str
    node_type: str
    approver_id: int | None
    origin_approver_id: int | None
    mode: str
    status: str
    comment: str
    seq: int
    created_at: datetime
    decided_at: datetime | None


class WorkflowInstanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    definition_id: int
    version_id: int
    title: str
    initiator_id: int
    form_data: dict
    current_nodes: list
    status: str
    started_at: datetime
    finished_at: datetime | None
    created_at: datetime
    tasks: list[WorkflowTaskOut] = []


class WorkflowReview(BaseModel):
    approve: bool
    comment: str | None = Field(default=None, max_length=500)


class WorkflowTransfer(BaseModel):
    """转办：把当前任务交给他人处理。"""
    to_user_id: int
    comment: str | None = Field(default=None, max_length=500)


class WorkflowAddSign(BaseModel):
    """加签：在当前节点增加审批人。before=true 为前加签（先由加签人审批）。"""
    user_ids: list[int] = Field(min_length=1, max_length=20)
    before: bool = False
    comment: str | None = Field(default=None, max_length=500)


class WorkflowUrge(BaseModel):
    """催办：提醒当前审批人。"""
    comment: str | None = Field(default=None, max_length=500)


# ---------- 流程监控看板 ----------
class WorkflowStatsOut(BaseModel):
    """流程监控看板聚合数据：定义/实例/任务统计、按定义分布、近 14 天趋势、超时与在途快照。"""
    model_config = ConfigDict(from_attributes=True)

    generated_at: datetime
    sla_days: int
    definitions: dict[str, int]
    instances: dict[str, int]
    tasks: dict[str, int]
    delegations_active: int
    by_definition: list[dict]
    trend: list[dict]
    overdue_tasks: list[dict]
    running_instances: list[dict]


# ---------- 内容门户：角色化工作台概览 ----------
class PortalTaskOut(BaseModel):
    """待我审批任务（含所属流程信息）。"""
    task_id: int
    instance_id: int
    instance_code: str
    instance_title: str
    node_name: str
    created_at: datetime | None


class PortalInstanceOut(BaseModel):
    id: int
    code: str
    title: str
    status: str
    started_at: datetime | None


class PortalLeaveOut(BaseModel):
    id: int
    leave_type: str
    status: str
    start_date: date
    end_date: date


class PortalAnnouncementOut(BaseModel):
    id: int
    title: str
    pinned: bool
    created_at: datetime


class PortalOverviewOut(BaseModel):
    """工作台门户聚合：角色、按角色统计、待办/在途/请假/公告四类挂件。"""
    role: str
    is_admin: bool
    stats: dict[str, int]
    pending_tasks: list[PortalTaskOut]
    my_instances_running: list[PortalInstanceOut]
    recent_leave: list[PortalLeaveOut]
    announcements: list[PortalAnnouncementOut]


# ---------- 运维中心：系统运行概览 ----------
class OpsOverviewOut(BaseModel):
    """运维中心：管理员视角的系统级运行概览（实体计数、流程分布、角色矩阵、最近实例）。"""
    generated_at: datetime
    db_backend: str
    counts: dict[str, int]
    instances_by_status: dict[str, int]
    users_by_role: list[dict]
    recent_instances: list[dict]


# ---------- 建模引擎：自定义实体 + 实体数据 ----------
class ModelEntityCreate(BaseModel):
    """新建实体模型；fields 为字段 schema，由服务层做结构与类型校验。"""
    code: str = Field(min_length=2, max_length=60, pattern="^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(default="general", max_length=50)
    icon: str = Field(default="", max_length=40)
    description: str = Field(default="", max_length=300)
    fields: list[dict] = Field(default=[], max_length=100)
    display_field: str = Field(default="", max_length=60)
    status: str = Field(default="draft", pattern="^(draft|published)$")


class ModelEntityUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, max_length=50)
    icon: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, max_length=300)
    fields: list[dict] | None = Field(default=None, max_length=100)
    display_field: str | None = Field(default=None, max_length=60)
    status: str | None = Field(default=None, pattern="^(draft|published)$")


class ModelEntityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    category: str
    icon: str
    description: str
    fields: list
    display_field: str
    status: str
    record_count: int = 0
    created_by: int | None
    created_at: datetime
    updated_at: datetime


class ModelRecordCreate(BaseModel):
    data: dict = Field(default={})


class ModelRecordUpdate(BaseModel):
    """更新记录：data 按字段做局部合并（只覆盖传入的字段）。"""
    data: dict


class ModelRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    entity_id: int
    serial_no: str
    data: dict
    created_by: int | None
    updated_by: int | None
    created_at: datetime
    updated_at: datetime


class ModelRecordsPage(BaseModel):
    """记录分页结果：JSON 数据列不支持方言无关的谓词下推，由服务层过滤后分页。"""
    total: int
    offset: int
    limit: int
    items: list[ModelRecordOut]


class ModelStatsOut(BaseModel):
    """建模引擎概览：实体数、数据量、今日新增与 Top 实体分布。"""
    generated_at: datetime
    entities: int
    entities_published: int
    records: int
    records_today: int
    by_entity: list[dict]


# ---------- 电子签单 ----------
class SignatureCreate(BaseModel):
    ref_type: str = Field(pattern="^(leave_request|document|workflow)$")
    ref_id: int
    signature_data: str = Field(min_length=10, max_length=500000)
    comment: str | None = Field(default=None, max_length=500)


class SignatureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ref_type: str
    ref_id: int
    signer_id: int
    content_hash: str
    comment: str
    signed_at: datetime


# ---------- 日志中心：审计日志 ----------
class AuditLogOut(BaseModel):
    """审计日志对外视图：查询维度（操作人/模块/动作/结果/时间）均为物理列，支持直接下推检索。"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_id: int | None
    actor_name: str
    module: str
    action: str
    target_type: str
    target_id: str
    method: str
    path: str
    status: str
    status_code: int
    message: str
    detail: dict
    ip: str
    request_id: str
    created_at: datetime
    # 增强字段
    before_value: dict | None = None
    after_value: dict | None = None
    correlation_id: str | None = None
    duration_ms: int | None = None


class AuditLogsPage(BaseModel):
    """审计日志分页结果（items 为脱敏后的视图，detail 不含密码/令牌）。"""
    items: list[AuditLogOut]
    total: int


class AuditStatsOut(BaseModel):
    """日志中心概览：总量、成功/失败、按模块/状态分布、近 14 天趋势。"""
    generated_at: datetime
    total: int
    success: int
    failed: int
    by_module: list[dict]
    by_status: list[dict]
    trend: list[dict]


class AuditPurgeRequest(BaseModel):
    """清理 N 天前的审计日志（仅管理员 audit:manage 可调）。"""
    days: int = Field(default=90, ge=1, le=3650)


class AuditLogDetailOut(BaseModel):
    """单条审计日志详情（含 before/after value, correlation_id, duration_ms）"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_id: int | None
    actor_name: str
    module: str
    action: str
    target_type: str
    target_id: str
    method: str
    path: str
    status: str
    status_code: int
    message: str
    detail: dict
    before_value: dict | None = None
    after_value: dict | None = None
    correlation_id: str | None = None
    duration_ms: int | None = None
    ip: str
    request_id: str
    created_at: datetime


class AuditLogsByCorrelationOut(BaseModel):
    """按关联 ID 查询的审计日志分页结果"""
    items: list[AuditLogOut]
    total: int
    offset: int
    limit: int


class AuditDurationStatsOut(BaseModel):
    """请求耗时分布统计"""
    avg: float
    p50: int
    p95: int
    p99: int
    max: int
    count: int


class AuditPurgeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    deleted: int
    before: datetime


# ---------- 消息中心：通知收件箱 ----------
class NotificationOut(BaseModel):
    """单条通知（用户仅可见自己的）。type: system|leave|workflow|announcement。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    title: str
    body: str
    link: str
    is_read: bool
    created_at: datetime


class NotificationsPage(BaseModel):
    """通知列表分页结果（含未读总数，用于顶部铃铛角标）。"""

    items: list[NotificationOut]
    total: int
    unread: int
    limit: int
    offset: int


# ---------- 报表中心：统一数据看板 ----------
class DashboardPersonalOut(BaseModel):
    """个人视图：所有登录用户可见（我的未读/待审批/请假/在途）。"""

    my_unread: int
    my_pending_approvals: int
    my_leaves: int
    my_running: int


class DashboardKpiOut(BaseModel):
    """组织级 KPI 指标卡。"""

    users_total: int
    departments_total: int
    workflow_instances: int
    workflow_active: int
    workflow_done: int
    leaves_this_month: int
    announcements_total: int
    audit_total: int


class StatusSlice(BaseModel):
    status: str
    count: int


class TrendPoint(BaseModel):
    date: str
    started: int
    finished: int


class DeptHead(BaseModel):
    department: str
    count: int


class ActivityItem(BaseModel):
    id: int
    title: str
    type: str
    status: str | None = None
    at: str | None = None
    actor: str | None = None


class DashboardOrgOut(BaseModel):
    """组织级聚合（仅 report:view 可见；员工仅看个人视图）。"""

    kpi: DashboardKpiOut
    workflow_status: list[StatusSlice]
    workflow_trend: list[TrendPoint]
    trend_days: int = 30
    department_headcount: list[DeptHead]
    recent_activities: list[ActivityItem]


class DashboardOut(BaseModel):
    """报表中心聚合：个人视图恒返回，组织级仅在持 report:view 时返回。"""

    generated_at: datetime
    has_org_scope: bool
    personal: DashboardPersonalOut
    org: DashboardOrgOut | None = None


class SchedulerRunOut(BaseModel):
    """后台调度手动触发一轮的结果统计。"""

    scanned: int
    escalated: int
    reassigned: int
    dead_letters: int


# ---------- 考勤管理 ----------
class AttendanceClockOut(BaseModel):
    """打卡结果：返回当日记录，前端据此提示上/下班时间与迟到情况。"""

    day: date
    check_in: datetime | None = None
    check_out: datetime | None = None
    status: str
    late_minutes: int = 0
    early_minutes: int = 0
    message: str = ""
    # GPS字段
    check_in_lat: float | None = None
    check_in_lng: float | None = None
    check_out_lat: float | None = None
    check_out_lng: float | None = None
    check_in_address: str | None = None
    check_out_address: str | None = None
    is_field_work: bool = False
    field_work_address: str | None = None
    field_work_note: str | None = None


class AttendanceRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    user_name: str = ""
    day: date
    check_in: datetime | None = None
    check_out: datetime | None = None
    status: str
    late_minutes: int = 0
    early_minutes: int = 0
    work_minutes: int = 0
    source: str = "clock"
    note: str = ""
    # GPS字段
    check_in_lat: float | None = None
    check_in_lng: float | None = None
    check_out_lat: float | None = None
    check_out_lng: float | None = None
    check_in_address: str | None = None
    check_out_address: str | None = None
    is_field_work: bool = False
    field_work_address: str | None = None
    field_work_note: str | None = None


class AttendanceSummary(BaseModel):
    """单人单月考勤汇总（工作日数按班次设置推导）。"""

    month: str
    expected_workdays: int = 0
    present_days: int = 0
    late_days: int = 0
    early_days: int = 0
    absent_days: int = 0
    leave_days: int = 0
    travel_days: int = 0
    remote_days: int = 0
    overtime_hours: float = 0.0
    avg_work_minutes: int = 0


class AttendanceMeOut(BaseModel):
    records: list[AttendanceRecordOut]
    summary: AttendanceSummary


class AttendanceSettingIn(BaseModel):
    name: str | None = Field(default=None, max_length=60)
    work_start: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    work_end: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    late_grace_minutes: int | None = Field(default=None, ge=0, le=120)
    workdays: list[int] | None = Field(default=None, min_length=1, max_length=7)


class AttendanceSettingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int = 0
    name: str
    work_start: str
    work_end: str
    late_grace_minutes: int
    workdays: list = [1, 2, 3, 4, 5]
    updated_at: datetime | None = None


class AttendanceRecordUpdate(BaseModel):
    """管理员人工修正出勤（请假/出差/远程/补打卡）。"""

    status: str | None = Field(
        default=None, pattern=r"^(normal|late|early|absent|leave|travel|remote)$"
    )
    note: str | None = Field(default=None, max_length=200)
    check_in: datetime | None = None
    check_out: datetime | None = None
    # GPS字段
    check_in_lat: float | None = None
    check_in_lng: float | None = None
    check_out_lat: float | None = None
    check_out_lng: float | None = None
    check_in_address: str | None = None
    check_out_address: str | None = None
    is_field_work: bool | None = None
    field_work_address: str | None = None
    field_work_note: str | None = None


class AttendanceImportRow(BaseModel):
    """考勤导入行数据"""
    user_id: int | None = None
    username: str | None = None  # 或 username 查找用户
    day: date  # YYYY-MM-DD
    check_in: str | None = None  # HH:MM
    check_out: str | None = None  # HH:MM
    status: str | None = Field(default="normal", pattern=r"^(normal|late|early|absent|leave|travel|remote)$")
    late_minutes: int = 0
    early_minutes: int = 0
    work_minutes: int = 0
    source: str = "import"
    note: str | None = None
    # GPS字段
    check_in_lat: float | None = None
    check_in_lng: float | None = None
    check_out_lat: float | None = None
    check_out_lng: float | None = None
    check_in_address: str | None = None
    check_out_address: str | None = None
    is_field_work: bool = False
    field_work_address: str | None = None
    field_work_note: str | None = None


class AttendanceImportResult(BaseModel):
    created: int = 0
    updated: int = 0
    errors: list[str] = Field(default_factory=list)
    # 增量优化：预检模式与统计口径（total=解析行数，linked_field_work=关联回填的外勤单数）
    dry_run: bool = False
    total: int = 0
    linked_field_work: int = 0


class OvertimeCreate(BaseModel):
    day: date
    hours: float = Field(gt=0, le=24)
    reason: str = Field(default="", max_length=500)


class OvertimeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    user_name: str = ""
    day: date
    hours: float
    reason: str
    status: str
    approver_id: int | None = None
    review_comment: str = ""
    reviewed_at: datetime | None = None
    created_at: datetime


class OvertimeReview(BaseModel):
    approve: bool
    comment: str = Field(default="", max_length=500)


class AttendanceStatsRow(BaseModel):
    user_id: int
    username: str
    full_name: str
    present_days: int = 0
    late_days: int = 0
    early_days: int = 0
    absent_days: int = 0
    leave_days: int = 0
    overtime_hours: float = 0.0


class AttendanceStatsOut(BaseModel):
    month: str
    expected_workdays: int = 0
    rows: list[AttendanceStatsRow] = []
    pending_overtime: int = 0


# ---------- 外勤申请（考勤外勤关联） ----------
class FieldWorkCreate(BaseModel):
    start_date: date
    end_date: date
    address: str = Field(default="", max_length=500)
    purpose: str = Field(default="", max_length=300)
    remark: str = Field(default="", max_length=1000)


class FieldWorkReview(BaseModel):
    approve: bool
    comment: str = Field(default="", max_length=500)


class FieldWorkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    user_name: str = ""
    start_date: date
    end_date: date
    address: str = ""
    purpose: str = ""
    remark: str = ""
    status: str = "pending"
    approver_id: int | None = None
    approver_name: str = ""
    review_comment: str = ""
    reviewed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class FieldWorkPage(BaseModel):
    items: list[FieldWorkOut]
    total: int
    offset: int
    limit: int


# ---------- 考勤异常预警 ----------
class AttendanceAlert(BaseModel):
    """单条考勤异常：type 为机器可读类型，level 决定展示优先级。"""

    type: str  # absent/missing_checkout/late_frequent/early_frequent/night_clock/field_no_order/long_absent
    level: str = "medium"  # high/medium/low
    user_id: int
    user_name: str = ""
    day: date | None = None
    period: str = ""
    count: int = 1
    message: str = ""


class AttendanceAlertsOut(BaseModel):
    start: date
    end: date
    threshold: int = 3
    checked_users: int = 0
    total: int = 0
    by_type: list[dict] = []
    alerts: list[AttendanceAlert] = []


class AttendanceAlertNotifyIn(BaseModel):
    start: date | None = None
    end: date | None = None
    threshold: int = Field(default=3, ge=1, le=30)
    limit: int = Field(default=100, ge=1, le=500)


class AttendanceAlertNotifyOut(BaseModel):
    alert_count: int = 0
    notified_users: int = 0


# ---------- 审批委托（代审） ----------
class DelegationCreate(BaseModel):
    to_user_id: int
    start_at: datetime
    end_at: datetime
    definition_id: int | None = None  # 空 = 全部流程
    active: bool = True


class DelegationUpdate(BaseModel):
    to_user_id: int | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    definition_id: int | None = None
    active: bool | None = None


class DelegationOut(BaseModel):
    id: int
    from_user_id: int
    from_user_name: str = ""
    to_user_id: int
    to_user_name: str = ""
    definition_id: int | None = None
    definition_name: str = ""
    start_at: datetime
    end_at: datetime
    active: bool
    created_at: datetime


# ---------- 报销单 ----------
class ExpenseCreate(BaseModel):
    claim_type: str = Field(default="daily", pattern=r"^(travel|daily|entertain|other)$")
    amount: float = Field(ge=0, le=10_000_000)
    occur_date: date
    description: str = Field(default="", max_length=1000)
    attachments: list[dict] = Field(default=[], max_length=50)


class ExpenseUpdate(BaseModel):
    claim_type: str | None = Field(default=None, pattern=r"^(travel|daily|entertain|other)$")
    amount: float | None = Field(default=None, ge=0, le=10_000_000)
    occur_date: date | None = None
    description: str | None = Field(default=None, max_length=1000)
    attachments: list[dict] | None = Field(default=None, max_length=50)


class ExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    user_id: int
    user_name: str = ""
    claim_type: str
    amount: float
    occur_date: date
    description: str
    attachments: list = []
    status: str
    workflow_instance_id: int | None = None
    workflow_code: str = ""
    approver_id: int | None = None
    approver_name: str = ""
    review_comment: str = ""
    reviewed_at: datetime | None = None
    paid_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ExpensePage(BaseModel):
    items: list[ExpenseOut]
    total: int
    offset: int
    limit: int
    # 我的额度视角汇总（admin/manager 看到的是所筛范围）
    sum_amount: float = 0.0


class ExpenseStatusSlice(BaseModel):
    status: str
    count: int
    amount: float = 0.0


class ExpenseStatsOut(BaseModel):
    month: str
    total_count: int = 0
    total_amount: float = 0.0
    pending_count: int = 0
    by_status: list[ExpenseStatusSlice] = []
    by_type: list[ExpenseStatusSlice] = []


class ExpensePaidIn(BaseModel):
    paid: bool = True
    comment: str = Field(default="", max_length=500)


# ---------- 公文 ----------
class OfficialDocCreate(BaseModel):
    doc_no: str | None = Field(default=None, min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=200)
    direction: str = Field(default="in", pattern=r"^(in|out)$")
    from_org: str = Field(default="", max_length=120)
    to_org: str = Field(default="", max_length=120)
    secrecy: str = Field(default="internal", pattern=r"^(public|internal|secret)$")
    content: str = Field(default="", max_length=20000)
    attachments: list[dict] = Field(default=[], max_length=50)


class OfficialDocUpdate(BaseModel):
    doc_no: str | None = Field(default=None, min_length=1, max_length=60)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    direction: str | None = Field(default=None, pattern=r"^(in|out)$")
    from_org: str | None = Field(default=None, max_length=120)
    to_org: str | None = Field(default=None, max_length=120)
    secrecy: str | None = Field(default=None, pattern=r"^(public|internal|secret)$")
    content: str | None = Field(default=None, max_length=20000)
    attachments: list[dict] | None = Field(default=None, max_length=50)


class OfficialDocOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    doc_no: str
    title: str
    direction: str
    from_org: str
    to_org: str
    secrecy: str
    status: str
    content: str
    attachments: list = []
    owner_id: int
    owner_name: str
    read_count: int = 0
    published_at: datetime | None = None
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class OfficialDocPage(BaseModel):
    items: list[OfficialDocOut]
    total: int
    offset: int
    limit: int


class OfficialDocCirculate(BaseModel):
    """传阅：user_ids 为空表示广播给全部可见用户。"""

    user_ids: list[int] = Field(default=[], max_length=500)
    remark: str = Field(default="", max_length=300)


# ---------- 文档版本 / 公告回执 ----------
class DocumentVersionOut(BaseModel):
    id: int
    document_id: int
    version: int
    file_type: str
    file_size: int
    file_url: str = ""
    note: str
    uploader_name: str
    created_at: datetime


class AnnouncementReadOut(BaseModel):
    announcement_id: int
    read: bool
    read_count: int


class AnnouncementReaderItem(BaseModel):
    user_id: int
    user_name: str
    read_at: datetime


class AnnouncementReadersOut(BaseModel):
    announcement_id: int
    read_count: int
    total_users: int
    readers: list[AnnouncementReaderItem] = []


# ---------- 预算/额度 ----------
class BudgetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=1, max_length=40)
    total_amount: float = Field(ge=0, le=10_000_000)
    start_date: date
    end_date: date
    department_id: int | None = None
    category: str | None = Field(default=None, pattern=r"^(travel|daily|entertain|other)$")
    status: str = Field(default="active", pattern=r"^(active|inactive|expired)$")


class BudgetUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    total_amount: float | None = Field(default=None, ge=0, le=10_000_000)
    start_date: date | None = None
    end_date: date | None = None
    department_id: int | None = None
    category: str | None = Field(default=None, pattern=r"^(travel|daily|entertain|other)$")
    status: str | None = Field(default=None, pattern=r"^(active|inactive|expired)$")


class BudgetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    total_amount: float
    used_amount: float = 0
    remaining: float = 0
    start_date: date
    end_date: date
    department_id: int | None = None
    category: str | None = None
    status: str = "active"
    created_at: datetime
    updated_at: datetime


class BudgetPage(BaseModel):
    items: list[BudgetOut]
    total: int
    offset: int
    limit: int


class BudgetQuotaCheck(BaseModel):
    has_budget: bool
    budget_id: int | None = None
    quota_amount: float | None = None  # 匹配预算的总额度
    remaining: float | None = None  # 扣除在途单据后的剩余额度
    exceeded: bool = False
    message: str = ""


# ---------- 发票验真 ----------
class InvoiceVerifyRequest(BaseModel):
    invoice_no: str = Field(min_length=1, max_length=50)
    invoice_code: str | None = Field(default=None, max_length=20)
    amount: float | None = Field(default=None, ge=0)
    buyer_tax_no: str | None = Field(default=None, max_length=18)


class InvoiceCheck(BaseModel):
    name: str
    passed: bool
    message: str


class InvoiceVerifyResponse(BaseModel):
    status: str  # verified/failed
    checks: list[InvoiceCheck]


# ---------- 批量打款 ----------
class BatchPayRequest(BaseModel):
    expense_ids: list[int] = Field(min_length=1, max_length=100)


class BatchPayResult(BaseModel):
    id: int
    success: bool
    code: str = ""
    error: str = ""


class BatchPayResponse(BaseModel):
    total: int
    success: int
    failed: int
    results: list[BatchPayResult]
