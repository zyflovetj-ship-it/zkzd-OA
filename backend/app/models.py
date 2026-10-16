"""ORM 模型：覆盖员工/部门、考勤/请假、公告/文档、审批工作流、电子签单。"""
from datetime import datetime, date

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    description: Mapped[str] = mapped_column(String(200), default="")
    # 数据范围：all=全部 / dept=本部门 / self=仅本人（对齐泛微组织权限中心）
    data_scope: Mapped[str] = mapped_column(String(20), default="all")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    users: Mapped[list["User"]] = relationship(back_populates="role")
    permissions: Mapped[list["Permission"]] = relationship(
        secondary="role_permissions", back_populates="roles"
    )


class Permission(Base):
    """权限点：可赋给角色；type=menu 用于菜单可见性，type=operation 用于按钮/接口授权。"""
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    # 分类：组织权限 / 人事管理 / 考勤请假 / 公告文档 / 审批工作流 / 电子签单 / 通用
    category: Mapped[str] = mapped_column(String(50), default="general")
    type: Mapped[str] = mapped_column(String(20), default="operation")  # menu | operation
    description: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    roles: Mapped[list["Role"]] = relationship(
        secondary="role_permissions", back_populates="permissions"
    )


class RolePermission(Base):
    """角色-权限关联（多对多）。"""
    __tablename__ = "role_permissions"

    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[int] = mapped_column(
        ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    )


class Menu(Base):
    """导航菜单：parent_id 构成树；permission_code 为空表示所有登录用户可见。"""
    __tablename__ = "menus"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("menus.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(100))
    path: Mapped[str] = mapped_column(String(200), default="")  # 分组节点为空
    icon: Mapped[str] = mapped_column(String(50), default="")  # 前端图标注册表 key
    order: Mapped[int] = mapped_column(Integer, default=0)
    permission_code: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    members: Mapped[list["User"]] = relationship(
        back_populates="department", foreign_keys="User.department_id"
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(120), default="")
    full_name: Mapped[str] = mapped_column(String(100), default="")
    hashed_password: Mapped[str] = mapped_column(String(255))
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    role: Mapped["Role"] = relationship(back_populates="users")
    department: Mapped["Department | None"] = relationship(
        back_populates="members", foreign_keys="[User.department_id]"
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(back_populates="user")


class RefreshToken(Base):
    """服务端存储的刷新令牌，支持吊销与轮换。"""
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")


class LeaveRequest(Base):
    __tablename__ = "leave_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    leave_type: Mapped[str] = mapped_column(String(30))  # annual/sick/personal/other
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/approved/rejected
    approver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    rejection_reason: Mapped[str] = mapped_column(Text, default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(foreign_keys=[user_id])


class Attendance(Base):
    """考勤记录：一天一行（user_id + day 唯一），记录上下班打卡与出勤状态。

    status 由打卡时间结合班次设置自动推导，管理员可人工修正为请假/出差等：
    normal | late | early | absent | leave | travel | remote
    """
    __tablename__ = "attendances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    check_in: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    check_out: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="normal", index=True)
    late_minutes: Mapped[int] = mapped_column(Integer, default=0)
    early_minutes: Mapped[int] = mapped_column(Integer, default=0)
    work_minutes: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(10), default="clock")  # clock | manual
    note: Mapped[str] = mapped_column(String(200), default="")
    # GPS字段：用于外勤打卡与位置记录
    check_in_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    check_in_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    check_out_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    check_out_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    check_in_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    check_out_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_field_work: Mapped[bool] = mapped_column(Boolean, default=False)
    field_work_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    field_work_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 关联的外勤审批单（外勤打卡与外勤申请闭环；无审批单时为 NULL，会触发异常预警）
    field_work_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("field_work_orders.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(foreign_keys=[user_id])


class FieldWorkOrder(Base):
    """外勤申请：审批通过后，区间内打卡自动关联本单并免计迟到/早退。

    status: pending=待审批 / approved=已通过 / rejected=已驳回 / cancelled=已撤回
    """

    __tablename__ = "field_work_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    start_date: Mapped[date] = mapped_column(Date, index=True)
    end_date: Mapped[date] = mapped_column(Date, index=True)
    address: Mapped[str] = mapped_column(String(500), default="")
    purpose: Mapped[str] = mapped_column(String(300), default="")
    remark: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    approver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    review_comment: Mapped[str] = mapped_column(Text, default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(foreign_keys=[user_id])


class AttendanceSetting(Base):
    """班次设置：决定上班/下班时间、迟到宽限与工作日，供打卡判定与月度统计使用。

    约定只有一行（id=1），由管理端整体覆盖更新。
    """
    __tablename__ = "attendance_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(60), default="标准班次")
    work_start: Mapped[str] = mapped_column(String(8), default="09:00")  # HH:MM
    work_end: Mapped[str] = mapped_column(String(8), default="18:00")
    late_grace_minutes: Mapped[int] = mapped_column(Integer, default=0)
    # ISO 星期：1=周一 ... 7=周日
    workdays: Mapped[list] = mapped_column(JSON, default=lambda: [1, 2, 3, 4, 5])
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class OvertimeRequest(Base):
    """加班申请：按天登记小时数，管理员/经理审批后计入加班统计。"""
    __tablename__ = "overtime_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    hours: Mapped[float] = mapped_column(Float, default=1.0)
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    approver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    review_comment: Mapped[str] = mapped_column(Text, default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(foreign_keys=[user_id])


class Announcement(Base):
    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    published: Mapped[bool] = mapped_column(Boolean, default=True)
    # 关联文档（附件）：[{document_id, title, file_url}]，由文档中心选取
    attachments: Mapped[list] = mapped_column(JSON, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 阅读回执快照：用户打开公告时 +1，明细在 announcement_reads
    read_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    author: Mapped["User"] = relationship(foreign_keys=[author_id])


class AnnouncementRead(Base):
    """公告阅读回执：(announcement_id, user_id) 唯一，用于统计谁看过。"""
    __tablename__ = "announcement_reads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    announcement_id: Mapped[int] = mapped_column(ForeignKey("announcements.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    read_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Document(Base):
    """文档中心：存储文档元数据（实际文件落本地上传目录，生产可改走对象存储）。

    设计取舍：file_url 存「逻辑下载地址」/api/documents/{id}/file，由后端鉴权后流式返回，
    避免把原始磁盘路径/静态目录直接暴露给前端（防止绕过权限直链下载）。
    """

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), index=True)
    category: Mapped[str] = mapped_column(String(50), default="general", index=True)
    file_type: Mapped[str] = mapped_column(String(30), default="")  # 扩展名，如 pdf/docx
    file_size: Mapped[int] = mapped_column(Integer, default=0)  # 字节
    description: Mapped[str] = mapped_column(String(500), default="")
    file_url: Mapped[str] = mapped_column(String(500), default="")  # 逻辑下载地址
    # 版本：当前版本号与当前版本的存储 key（历史 key 为空时回落 {id}.{ext} 老格式）
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    current_file_key: Mapped[str] = mapped_column(String(120), default="")
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    owner_name: Mapped[str] = mapped_column(String(50), default="")  # 快照，避免关联查询
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class DocumentVersion(Base):
    """文档版本历史：每次上传新文件追加一行，current_version 指向最新。"""
    __tablename__ = "document_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    file_type: Mapped[str] = mapped_column(String(30), default="")
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    file_key: Mapped[str] = mapped_column(String(120), default="")  # 存储 key，如 12_v2.pdf
    note: Mapped[str] = mapped_column(String(300), default="")
    uploader_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    uploader_name: Mapped[str] = mapped_column(String(50), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ModelEntity(Base):
    """建模引擎：自定义业务实体（低代码），字段 schema 驱动列表、表单渲染与服务端校验。

    采用「元数据 + JSON 数据列」而非动态建表：无需 DDL 迁移即可新增实体，
    代价是 JSON 字段无法建索引，筛选走服务层（见 ModelingService 的扫描上限说明）。
    """
    __tablename__ = "model_entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(50), default="general")
    icon: Mapped[str] = mapped_column(String(40), default="")
    description: Mapped[str] = mapped_column(String(300), default="")
    # [{"key","label","type","required","unique","options":[],"default":null}]
    fields: Mapped[list] = mapped_column(JSON, default=list)
    display_field: Mapped[str] = mapped_column(String(60), default="")  # 列表主展示字段
    # draft：设计中不可录入数据；published：发布后可录入
    status: Mapped[str] = mapped_column(String(20), default="draft")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    records: Mapped[list["ModelRecord"]] = relationship(
        back_populates="entity", cascade="all, delete-orphan"
    )


class ModelRecord(Base):
    """建模引擎：实体数据行，data 为 {field_key: value} 的校验后字典。"""
    __tablename__ = "model_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("model_entities.id"), index=True)
    serial_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    entity: Mapped["ModelEntity"] = relationship(back_populates="records")


class FormDefinition(Base):
    """表单定义：字段 schema 驱动动态表单渲染、校验与流程条件取值。"""
    __tablename__ = "form_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    # [{"key":"amount","label":"金额","type":"number","required":true,"options":[],"default":0}]
    fields: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class WorkflowDefinition(Base):
    """流程定义（承载多版本）。status: draft / published / locked。"""
    __tablename__ = "workflow_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(50), default="general")  # hr/admin/business
    description: Mapped[str] = mapped_column(String(300), default="")
    icon: Mapped[str] = mapped_column(String(40), default="")
    # locked：不可发起新流程，但在途实例可继续流转与查看（对齐泛微流程锁定）
    status: Mapped[str] = mapped_column(String(20), default="draft")
    current_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    versions: Mapped[list["WorkflowVersion"]] = relationship(
        back_populates="definition", cascade="all, delete-orphan"
    )
    instances: Mapped[list["WorkflowInstance"]] = relationship(back_populates="definition")


class WorkflowVersion(Base):
    """流程版本：graph 为节点/连线图结构。发布后不可变，在途实例按发起时版本流转。"""
    __tablename__ = "workflow_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    definition_id: Mapped[int] = mapped_column(
        ForeignKey("workflow_definitions.id"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    # {"nodes":[{"id","type","name","assignee","mode","strategy",...}],
    #  "edges":[{"id","source","target","condition":{"field","op","value"}}]}
    graph: Mapped[dict] = mapped_column(JSON, default=dict)
    form_id: Mapped[int | None] = mapped_column(
        ForeignKey("form_definitions.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft/published/archived
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    remark: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    definition: Mapped["WorkflowDefinition"] = relationship(back_populates="versions")
    instances: Mapped[list["WorkflowInstance"]] = relationship(back_populates="version")


class WorkflowInstance(Base):
    """流程实例：快照发起时的版本与表单数据，支持多节点并行。"""
    __tablename__ = "workflow_instances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)  # 业务单号
    definition_id: Mapped[int] = mapped_column(
        ForeignKey("workflow_definitions.id"), index=True
    )
    version_id: Mapped[int] = mapped_column(ForeignKey("workflow_versions.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    initiator_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    form_data: Mapped[dict] = mapped_column(JSON, default=dict)
    # 当前活跃节点 id 列表（并行分支时为多个）
    current_nodes: Mapped[list] = mapped_column(JSON, default=list)
    # running / approved / rejected / canceled
    status: Mapped[str] = mapped_column(String(20), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # 超时升级标记：后台调度扫描到超时运行中实例后写入，保证升级通知幂等（仅触发一次）
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    definition: Mapped["WorkflowDefinition"] = relationship(back_populates="instances")
    version: Mapped["WorkflowVersion"] = relationship(back_populates="instances")
    tasks: Mapped[list["WorkflowTask"]] = relationship(
        back_populates="instance", cascade="all, delete-orphan",
        order_by="WorkflowTask.id",
    )
    logs: Mapped[list["WorkflowNodeLog"]] = relationship(
        back_populates="instance", cascade="all, delete-orphan",
        order_by="WorkflowNodeLog.id",
    )


class WorkflowTask(Base):
    """节点任务：同一节点会签/加签时为多条任务，seq 为节点内序号。"""
    __tablename__ = "workflow_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instance_id: Mapped[int] = mapped_column(ForeignKey("workflow_instances.id"), index=True)
    node_id: Mapped[str] = mapped_column(String(60), index=True)  # 图节点 id
    node_name: Mapped[str] = mapped_column(String(120))
    node_type: Mapped[str] = mapped_column(String(30))  # approval/countersign/notify
    approver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    origin_approver_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )  # 转办前的原审批人
    # single：单人审批 / countersign：会签 / addsign：加签产生
    mode: Mapped[str] = mapped_column(String(20), default="single")
    # pending/approved/rejected/transferred/skipped/canceled
    status: Mapped[str] = mapped_column(String(20), default="pending")
    comment: Mapped[str] = mapped_column(Text, default="")
    seq: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 超时提醒用

    instance: Mapped["WorkflowInstance"] = relationship(back_populates="tasks")


class WorkflowNodeLog(Base):
    """流转日志：记录节点进出与各类动作，供监控、时间线与效率分析。"""
    __tablename__ = "workflow_node_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instance_id: Mapped[int] = mapped_column(ForeignKey("workflow_instances.id"), index=True)
    node_id: Mapped[str] = mapped_column(String(60))
    node_name: Mapped[str] = mapped_column(String(120), default="")
    # enter/approve/reject/transfer/addsign/urge/withdraw/finish/skip/cancel
    action: Mapped[str] = mapped_column(String(30))
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    instance: Mapped["WorkflowInstance"] = relationship(back_populates="logs")


class WorkflowDelegation(Base):
    """委托/代理：时段内把审批权委托他人，definition_id 为空表示全部流程。"""
    __tablename__ = "workflow_delegations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    to_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    definition_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflow_definitions.id"), nullable=True
    )
    start_at: Mapped[datetime] = mapped_column(DateTime)
    end_at: Mapped[datetime] = mapped_column(DateTime)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Signature(Base):
    """电子签单：记录签署人、签名数据（data URL）、内容哈希与时间戳。"""
    __tablename__ = "signatures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ref_type: Mapped[str] = mapped_column(String(30))  # leave_request / document / workflow
    ref_id: Mapped[int] = mapped_column(Integer, index=True)
    signer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    signature_data: Mapped[str] = mapped_column(Text)  # 前端回传的签名图像 data URL
    content_hash: Mapped[str] = mapped_column(String(64), default="")  # SHA-256 防篡改
    comment: Mapped[str] = mapped_column(Text, default="")
    signed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    signer: Mapped["User"] = relationship(foreign_keys=[signer_id])


class AuditLog(Base):
    """审计日志：谁在什么时间、对什么对象、做了什么操作、结果如何。

    与建模记录的 JSON 数据列不同，这里的查询维度（操作人/模块/结果/时间）全部是物理列，
    因此列表检索与聚合可以直接下推到数据库，无需服务层内存过滤。

    增强字段：
    - before_value / after_value: 变更前后的值（JSON 序列化）
    - correlation_id: 关联 ID，用于串联同一业务流程的多条日志
    - duration_ms: 请求耗时（毫秒）
    """
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    actor_name: Mapped[str] = mapped_column(String(50), default="")  # 快照，用户注销后仍可追溯
    module: Mapped[str] = mapped_column(String(50), default="", index=True)  # auth/user/workflow/...
    action: Mapped[str] = mapped_column(String(40), default="", index=True)  # login/approve/delete...
    target_type: Mapped[str] = mapped_column(String(50), default="")
    target_id: Mapped[str] = mapped_column(String(40), default="")
    method: Mapped[str] = mapped_column(String(10), default="")
    path: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default="success", index=True)  # success/failed
    status_code: Mapped[int] = mapped_column(Integer, default=200)
    message: Mapped[str] = mapped_column(String(300), default="")
    # 脱敏后的上下文：永不写入密码、令牌与签名图片
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    # 增强字段
    before_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 变更前值
    after_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 变更后值
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)  # 关联 ID
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 请求耗时
    ip: Mapped[str] = mapped_column(String(45), default="")
    request_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class Notification(Base):
    """消息中心：统一收件箱（待办/审批/公告/系统通知），用户仅可见自己的。

    type: system | leave | workflow | announcement；link 为前端路由（如 /workflows/instance/12）。
    """

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(32), default="system")
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(String(512), default="")
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship("User")


class DeadLetter(Base):
    """后台任务死信：调度任务处理失败落盘，保留 payload 与错误，供排查与重放。"""

    __tablename__ = "scheduler_dead_letters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_name: Mapped[str] = mapped_column(String(64), index=True)
    # 关联业务主键（如 workflow_instances.id），用于去重：同一 ref 已死信则跳过重通知
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Budget(Base):
    """预算/额度：按「期间 + 部门 + 类别」控制报销可用额度。

    status: active=生效中 / inactive=停用 / expired=已过期
    category: travel/daily/entertain/other/None(全部类别)
    """
    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    total_amount: Mapped[float] = mapped_column(Float, default=0.0)
    used_amount: Mapped[float] = mapped_column(Float, default=0.0)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    category: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    @property
    def remaining(self) -> float:
        return round(float(self.total_amount or 0) - float(self.used_amount or 0), 2)


class ExpenseClaim(Base):
    """费用报销单：草稿 → 提交（挂工作流实例）→ 审批通过/驳回 → 打款。

    status 与 workflow_instance.status 联动：WorkflowService 结束实例时回写本表，
    使报销列表无需 join 流程表即可按状态筛选。
    """
    __tablename__ = "expense_claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)  # BX20260928-0001
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    claim_type: Mapped[str] = mapped_column(String(30), default="daily")  # travel/daily/entertain/other
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    occur_date: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(Text, default="")
    # 关联文档（发票等）：[{document_id, title, file_url}]
    attachments: Mapped[list] = mapped_column(JSON, default=list)
    # draft / submitted / approved / rejected / paid
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    workflow_instance_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflow_instances.id"), nullable=True, index=True
    )
    approver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    review_comment: Mapped[str] = mapped_column(Text, default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 额度/预算控制
    budget_id: Mapped[int | None] = mapped_column(ForeignKey("budgets.id"), nullable=True, index=True)
    quota_amount: Mapped[float | None] = mapped_column(Float, nullable=True)  # 单据额度上限
    remaining_quota: Mapped[float | None] = mapped_column(Float, nullable=True)  # 剩余额度
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(foreign_keys=[user_id])


class OfficialDocument(Base):
    """公文：收发文登记与传阅归档（doc_no 文号唯一、密级、状态流转）。"""
    __tablename__ = "official_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doc_no: Mapped[str] = mapped_column(String(60), unique=True, index=True)  # 文号
    # 序号：用于自动生成文号，格式为 {prefix}-{year}-{seq:04d}
    seq: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(200), index=True)
    direction: Mapped[str] = mapped_column(String(10), default="in")  # in=收文 out=发文
    from_org: Mapped[str] = mapped_column(String(120), default="")
    to_org: Mapped[str] = mapped_column(String(120), default="")
    # public=公开 internal=内部 secret=机密
    secrecy: Mapped[str] = mapped_column(String(20), default="internal")
    # draft / pending / circulated / archived
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    # 关联文档中心附件：[{document_id, title, file_url}]
    attachments: Mapped[list] = mapped_column(JSON, default=list)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    owner_name: Mapped[str] = mapped_column(String(50), default="")
    read_count: Mapped[int] = mapped_column(Integer, default=0)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped["User"] = relationship(foreign_keys=[owner_id])


class OfficialDocEvent(Base):
    """公文流转事件：记录公文状态变更、传阅、归档等操作的时间线。"""
    __tablename__ = "official_doc_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("official_documents.id"), index=True)
    action: Mapped[str] = mapped_column(String(50), index=True)  # create/circulate/archive/status_change
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    actor_name: Mapped[str] = mapped_column(String(50), default="")
    remark: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    doc: Mapped["OfficialDocument"] = relationship(foreign_keys=[doc_id])
    actor: Mapped["User"] = relationship(foreign_keys=[actor_id])
