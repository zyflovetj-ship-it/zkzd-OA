"""仓储层：仅负责数据查询与外部调用，避免 N+1（selectinload）。"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Announcement,
    AnnouncementRead,
    Attendance,
    AttendanceSetting,
    AuditLog,
    Department,
    Document,
    DocumentVersion,
    ExpenseClaim,
    FieldWorkOrder,
    LeaveRequest,
    OfficialDocEvent,
    Menu,
    ModelEntity,
    ModelRecord,
    Notification,
    OfficialDocument,
    OvertimeRequest,
    Permission,
    RefreshToken,
    Role,
    RolePermission,
    Signature,
    User,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowTask,
    DeadLetter,
)


# ---------- 认证 / 刷新令牌 ----------
class RefreshTokenRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, user_id: int, token_hash: str, expires_at: datetime) -> RefreshToken:
        obj = RefreshToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
        self.session.add(obj)
        await self.session.commit()
        await self.session.refresh(obj)
        return obj

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        res = await self.session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        return res.scalar_one_or_none()

    async def revoke(self, obj: RefreshToken) -> None:
        obj.revoked = True
        await self.session.commit()


# ---------- 用户 / 角色 / 部门 ----------
class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_username(self, username: str) -> User | None:
        res = await self.session.execute(
            select(User)
            .where(User.username == username)
            .options(selectinload(User.role), selectinload(User.department))
        )
        return res.scalar_one_or_none()

    async def get_by_id(self, user_id: int) -> User | None:
        res = await self.session.execute(
            select(User)
            .where(User.id == user_id)
            .options(selectinload(User.role), selectinload(User.department))
        )
        return res.scalar_one_or_none()

    async def list(self, skip: int = 0, limit: int = 50, q: str | None = None) -> list[User]:
        stmt = (
            select(User)
            .options(selectinload(User.role), selectinload(User.department))
            .order_by(User.id)
        )
        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(
                or_(User.username.ilike(pattern), User.full_name.ilike(pattern))
            )
        stmt = stmt.offset(skip).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def create(self, user: User) -> User:
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        # 响应模型 UserOut 要读 role_name（user.role.name）；异步会话里惰性加载会抛
        # MissingGreenlet → POST /api/users 500，故创建后强制带关系取回一次。
        return (await self.get_with_relations(user.id)) or user

    async def get_with_relations(self, user_id: int) -> User | None:
        """按 id 取用户并强制刷新 role / department（populate_existing 覆盖身份映射里的旧值）。"""
        res = await self.session.execute(
            select(User)
            .where(User.id == user_id)
            .options(selectinload(User.role), selectinload(User.department))
            .execution_options(populate_existing=True)
        )
        return res.scalar_one_or_none()

    async def count(self) -> int:
        res = await self.session.execute(select(func.count()).select_from(User))
        return int(res.scalar_one())

    async def count_by_role(self) -> list[dict]:
        """按角色分组统计人数（运维中心角色矩阵）；单次分组查询避免 N+1。"""
        res = await self.session.execute(
            select(func.coalesce(Role.name, "未分配"), func.count(User.id))
            .join(Role, Role.id == User.role_id, isouter=True)
            .group_by(func.coalesce(Role.name, "未分配"))
            .order_by(func.coalesce(Role.name, "未分配"))
        )
        return [{"role": r[0], "count": int(r[1])} for r in res.all()]

    async def count_by_department(self) -> list[dict]:
        """按部门分组统计人数（报表中心部门柱状图）；单次分组查询避免 N+1。"""
        res = await self.session.execute(
            select(func.coalesce(Department.name, "未分配"), func.count(User.id))
            .join(Department, Department.id == User.department_id, isouter=True)
            .group_by(func.coalesce(Department.name, "未分配"))
            .order_by(func.coalesce(Department.name, "未分配"))
        )
        return [{"department": r[0], "count": int(r[1])} for r in res.all()]

    async def list_all(self) -> list[User]:
        """监控看板需把审批人 id 映射为姓名，一次性取全量用户避免 N+1。"""
        res = await self.session.execute(select(User).order_by(User.id))
        return list(res.scalars().all())

    async def list_ids(self) -> list[int]:
        """全量用户 id（公告广播通知用）。"""
        res = await self.session.execute(select(User.id))
        return list(res.scalars().all())

    async def list_ids_by_roles(self, role_names: list[str]) -> list[int]:
        """按角色名取用户 id（如请假审批通知管理员/经理）。"""
        if not role_names:
            return []
        stmt = (
            select(User.id)
            .join(Role, User.role_id == Role.id)
            .where(Role.name.in_(role_names))
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def exists_username(self, username: str, exclude_id: int | None = None) -> bool:
        stmt = select(func.count()).select_from(User).where(User.username == username)
        if exclude_id is not None:
            stmt = stmt.where(User.id != exclude_id)
        res = await self.session.execute(stmt)
        return int(res.scalar_one()) > 0


class RoleRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list(self) -> list[Role]:
        res = await self.session.execute(select(Role).order_by(Role.id))
        return list(res.scalars().all())

    async def get_by_name(self, name: str) -> Role | None:
        res = await self.session.execute(select(Role).where(Role.name == name))
        return res.scalar_one_or_none()

    async def get_by_id(self, role_id: int) -> Role | None:
        res = await self.session.execute(select(Role).where(Role.id == role_id))
        return res.scalar_one_or_none()

    async def create(self, role: Role) -> Role:
        self.session.add(role)
        await self.session.commit()
        await self.session.refresh(role)
        return role

    async def count_users(self, role_id: int) -> int:
        """删除护栏：角色下仍有用户时禁止删除，避免产生孤儿的 role_id。"""
        res = await self.session.execute(
            select(func.count()).select_from(User).where(User.role_id == role_id)
        )
        return int(res.scalar_one())

    async def count(self) -> int:
        """角色总数（运维中心统计用）。"""
        res = await self.session.execute(select(func.count()).select_from(Role))
        return int(res.scalar_one())

    async def delete(self, role: Role) -> None:
        await self.session.delete(role)
        await self.session.commit()


class DepartmentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list(self) -> list[Department]:
        res = await self.session.execute(select(Department).order_by(Department.id))
        return list(res.scalars().all())

    async def get_by_id(self, dept_id: int) -> Department | None:
        res = await self.session.execute(select(Department).where(Department.id == dept_id))
        return res.scalar_one_or_none()

    async def create(self, dept: Department) -> Department:
        self.session.add(dept)
        await self.session.commit()
        await self.session.refresh(dept)
        return dept

    async def exists_name(self, name: str, exclude_id: int | None = None) -> bool:
        stmt = select(func.count()).select_from(Department).where(Department.name == name)
        if exclude_id is not None:
            stmt = stmt.where(Department.id != exclude_id)
        res = await self.session.execute(stmt)
        return int(res.scalar_one()) > 0

    async def count(self) -> int:
        res = await self.session.execute(select(func.count()).select_from(Department))
        return int(res.scalar_one())


# ---------- 权限 / 菜单 ----------
class PermissionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list(self, category: str | None = None, ptype: str | None = None) -> list[Permission]:
        stmt = select(Permission).order_by(Permission.category, Permission.id)
        if category:
            stmt = stmt.where(Permission.category == category)
        if ptype:
            stmt = stmt.where(Permission.type == ptype)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def count(self) -> int:
        """权限点总数（运维中心统计用）。"""
        res = await self.session.execute(select(func.count()).select_from(Permission))
        return int(res.scalar_one())

    async def get_by_id(self, perm_id: int) -> Permission | None:
        res = await self.session.execute(select(Permission).where(Permission.id == perm_id))
        return res.scalar_one_or_none()

    async def get_by_code(self, code: str) -> Permission | None:
        res = await self.session.execute(select(Permission).where(Permission.code == code))
        return res.scalar_one_or_none()

    async def exists_code(self, code: str, exclude_id: int | None = None) -> bool:
        stmt = select(func.count()).select_from(Permission).where(Permission.code == code)
        if exclude_id is not None:
            stmt = stmt.where(Permission.id != exclude_id)
        res = await self.session.execute(stmt)
        return int(res.scalar_one()) > 0

    async def create(self, perm: Permission) -> Permission:
        self.session.add(perm)
        await self.session.commit()
        await self.session.refresh(perm)
        return perm

    async def assign(self, role_id: int, perm_id: int) -> None:
        exists = await self.session.execute(
            select(RolePermission).where(
                RolePermission.role_id == role_id, RolePermission.permission_id == perm_id
            )
        )
        if exists.scalar_one_or_none():
            return
        self.session.add(RolePermission(role_id=role_id, permission_id=perm_id))
        await self.session.commit()

    async def revoke(self, role_id: int, perm_id: int) -> None:
        res = await self.session.execute(
            select(RolePermission).where(
                RolePermission.role_id == role_id, RolePermission.permission_id == perm_id
            )
        )
        obj = res.scalar_one_or_none()
        if obj:
            await self.session.delete(obj)
            await self.session.commit()

    async def list_for_role(self, role_id: int) -> list[Permission]:
        res = await self.session.execute(
            select(Permission)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role_id)
            .order_by(Permission.category, Permission.id)
        )
        return list(res.scalars().all())

    async def codes_for_role(self, role_id: int) -> list[str]:
        res = await self.session.execute(
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role_id)
        )
        return [r[0] for r in res.all()]


class MenuRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list(self) -> list[Menu]:
        res = await self.session.execute(select(Menu).order_by(Menu.order, Menu.id))
        return list(res.scalars().all())

    async def count(self) -> int:
        """菜单总数（运维中心统计用）。"""
        res = await self.session.execute(select(func.count()).select_from(Menu))
        return int(res.scalar_one())

    async def get_by_id(self, menu_id: int) -> Menu | None:
        res = await self.session.execute(select(Menu).where(Menu.id == menu_id))
        return res.scalar_one_or_none()

    async def exists_path(self, path: str, exclude_id: int | None = None) -> bool:
        stmt = select(func.count()).select_from(Menu).where(Menu.path == path)
        if exclude_id is not None:
            stmt = stmt.where(Menu.id != exclude_id)
        res = await self.session.execute(stmt)
        return int(res.scalar_one()) > 0

    async def create(self, menu: Menu) -> Menu:
        self.session.add(menu)
        await self.session.commit()
        await self.session.refresh(menu)
        return menu

    async def update(self, menu: Menu) -> Menu:
        await self.session.commit()
        await self.session.refresh(menu)
        return menu


# ---------- 考勤 / 请假 ----------
class LeaveRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, leave: LeaveRequest) -> LeaveRequest:
        self.session.add(leave)
        await self.session.commit()
        await self.session.refresh(leave)
        return leave

    async def get(self, leave_id: int) -> LeaveRequest | None:
        res = await self.session.execute(
            select(LeaveRequest)
            .where(LeaveRequest.id == leave_id)
            .options(selectinload(LeaveRequest.user))
        )
        return res.scalar_one_or_none()

    async def list(
        self,
        user_id: int | None = None,
        department_id: int | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> list[LeaveRequest]:
        stmt = (
            select(LeaveRequest)
            .options(selectinload(LeaveRequest.user))
            .order_by(LeaveRequest.created_at.desc())
        )
        if user_id is not None:
            stmt = stmt.where(LeaveRequest.user_id == user_id)
        if department_id is not None:
            # 数据范围=本部门：按请假人所属部门过滤
            stmt = stmt.join(User, User.id == LeaveRequest.user_id).where(
                User.department_id == department_id
            )
        stmt = stmt.offset(skip).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def count(self, user_id: int | None = None) -> int:
        """请假单计数；传 user_id 则只统计该用户。"""
        stmt = select(func.count()).select_from(LeaveRequest)
        if user_id is not None:
            stmt = stmt.where(LeaveRequest.user_id == user_id)
        res = await self.session.execute(stmt)
        return int(res.scalar_one())

    async def count_this_month(self) -> int:
        """本月请假单计数（报表中心 KPI）；按 created_at >= 本月首日过滤。"""
        now = datetime.now()
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        stmt = (
            select(func.count())
            .select_from(LeaveRequest)
            .where(LeaveRequest.created_at >= start)
        )
        res = await self.session.execute(stmt)
        return int(res.scalar_one())


# ---------- 公告 / 文档 ----------
class AnnouncementRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, ann: Announcement) -> Announcement:
        self.session.add(ann)
        await self.session.commit()
        await self.session.refresh(ann)
        return ann

    async def get(self, ann_id: int) -> Announcement | None:
        res = await self.session.execute(select(Announcement).where(Announcement.id == ann_id))
        return res.scalar_one_or_none()

    async def list(self, published_only: bool = False, skip: int = 0, limit: int = 50) -> list[Announcement]:
        stmt = select(Announcement).order_by(Announcement.pinned.desc(), Announcement.created_at.desc())
        if published_only:
            stmt = stmt.where(Announcement.published.is_(True))
        stmt = stmt.offset(skip).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def count(self) -> int:
        """公告总数（运维中心统计用）。"""
        res = await self.session.execute(select(func.count()).select_from(Announcement))
        return int(res.scalar_one())


# ---------- 内容引擎：文档中心 ----------
class DocumentRepository:
    """文档中心仓储：列表/计数走物理列过滤（category/index + title ilike），避免内存过滤。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, doc: Document) -> Document:
        self.session.add(doc)
        await self.session.commit()
        await self.session.refresh(doc)
        return doc

    async def get(self, doc_id: int) -> Document | None:
        res = await self.session.execute(select(Document).where(Document.id == doc_id))
        return res.scalar_one_or_none()

    async def list(
        self, category: str | None = None, q: str | None = None,
        offset: int = 0, limit: int = 50,
    ) -> list[Document]:
        stmt = select(Document).order_by(Document.created_at.desc())
        if category and category != "all":
            stmt = stmt.where(Document.category == category)
        if q:
            stmt = stmt.where(Document.title.ilike(f"%{q}%"))
        stmt = stmt.offset(offset).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def count(self, category: str | None = None, q: str | None = None) -> int:
        stmt = select(func.count()).select_from(Document)
        if category and category != "all":
            stmt = stmt.where(Document.category == category)
        if q:
            stmt = stmt.where(Document.title.ilike(f"%{q}%"))
        res = await self.session.execute(stmt)
        return int(res.scalar_one())

    async def delete(self, doc: Document) -> None:
        await self.session.delete(doc)
        await self.session.commit()


# ---------- 审批工作流（图结构引擎） ----------
from app.models import (  # noqa: E402
    FormDefinition,
    WorkflowDelegation,
    WorkflowNodeLog,
    WorkflowVersion,
)


class WorkflowRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    # ---- 表单定义 ----
    async def create_form(self, form: FormDefinition) -> FormDefinition:
        self.session.add(form)
        await self.session.commit()
        await self.session.refresh(form)
        return form

    async def list_forms(self) -> list[FormDefinition]:
        res = await self.session.execute(select(FormDefinition).order_by(FormDefinition.id))
        return list(res.scalars().all())

    async def get_form(self, form_id: int) -> FormDefinition | None:
        res = await self.session.execute(
            select(FormDefinition).where(FormDefinition.id == form_id)
        )
        return res.scalar_one_or_none()

    # ---- 流程定义 ----
    async def create_definition(self, wf: WorkflowDefinition) -> WorkflowDefinition:
        self.session.add(wf)
        await self.session.commit()
        await self.session.refresh(wf)
        return wf

    async def list_definitions(self, status: str | None = None) -> list[WorkflowDefinition]:
        stmt = select(WorkflowDefinition).order_by(WorkflowDefinition.id)
        if status:
            stmt = stmt.where(WorkflowDefinition.status == status)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_definition(self, wf_id: int) -> WorkflowDefinition | None:
        res = await self.session.execute(
            select(WorkflowDefinition).where(WorkflowDefinition.id == wf_id)
        )
        return res.scalar_one_or_none()

    # ---- 版本 ----
    async def create_version(self, ver: WorkflowVersion) -> WorkflowVersion:
        self.session.add(ver)
        await self.session.commit()
        await self.session.refresh(ver)
        return ver

    async def get_version(self, ver_id: int) -> WorkflowVersion | None:
        res = await self.session.execute(
            select(WorkflowVersion).where(WorkflowVersion.id == ver_id)
        )
        return res.scalar_one_or_none()

    async def list_versions(self, def_id: int) -> list[WorkflowVersion]:
        res = await self.session.execute(
            select(WorkflowVersion)
            .where(WorkflowVersion.definition_id == def_id)
            .order_by(WorkflowVersion.version.desc())
        )
        return list(res.scalars().all())

    async def get_published_version(self, def_id: int) -> WorkflowVersion | None:
        res = await self.session.execute(
            select(WorkflowVersion)
            .where(
                WorkflowVersion.definition_id == def_id,
                WorkflowVersion.status == "published",
            )
            .order_by(WorkflowVersion.version.desc())
        )
        return res.scalars().first()

    # ---- 实例 ----
    async def create_instance(self, inst: WorkflowInstance) -> WorkflowInstance:
        self.session.add(inst)
        await self.session.commit()
        await self.session.refresh(inst)
        # 必须再以 eager load 取回：响应模型 WorkflowInstanceOut 要序列化 tasks，
        # 而异步会话里触发惰性加载会抛 MissingGreenlet（接口 500）。
        loaded = await self.get_instance(inst.id)
        return loaded if loaded is not None else inst

    async def get_instance(self, inst_id: int) -> WorkflowInstance | None:
        res = await self.session.execute(
            select(WorkflowInstance)
            .where(WorkflowInstance.id == inst_id)
            .options(
                selectinload(WorkflowInstance.tasks),
                selectinload(WorkflowInstance.logs),
                selectinload(WorkflowInstance.version),
                selectinload(WorkflowInstance.definition),
            )
        )
        return res.scalar_one_or_none()

    async def list_instances(
        self, initiator_id: int | None = None, status: str | None = None
    ) -> list[WorkflowInstance]:
        stmt = (
            select(WorkflowInstance)
            .options(selectinload(WorkflowInstance.tasks))
            .order_by(WorkflowInstance.created_at.desc())
        )
        if initiator_id is not None:
            stmt = stmt.where(WorkflowInstance.initiator_id == initiator_id)
        if status:
            stmt = stmt.where(WorkflowInstance.status == status)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    # ---- 任务 ----
    async def get_task(self, task_id: int) -> WorkflowTask | None:
        res = await self.session.execute(
            select(WorkflowTask)
            .where(WorkflowTask.id == task_id)
            # 连带把 instance.tasks 一起取回：审批动作返回 WorkflowInstanceOut，
            # 序列化 tasks 若走惰性加载会抛 MissingGreenlet（500）。
            .options(
                selectinload(WorkflowTask.instance).selectinload(WorkflowInstance.tasks)
            )
        )
        return res.scalar_one_or_none()

    async def list_tasks(
        self, instance_id: int, node_id: str | None = None
    ) -> list[WorkflowTask]:
        stmt = select(WorkflowTask).where(WorkflowTask.instance_id == instance_id)
        if node_id:
            stmt = stmt.where(WorkflowTask.node_id == node_id)
        stmt = stmt.order_by(WorkflowTask.id)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def pending_for(self, user_id: int) -> list[WorkflowTask]:
        """待办：指派给我且实例仍在流转。"""
        res = await self.session.execute(
            select(WorkflowTask)
            .join(WorkflowInstance, WorkflowInstance.id == WorkflowTask.instance_id)
            .where(
                WorkflowTask.status == "pending",
                WorkflowTask.approver_id == user_id,
                WorkflowInstance.status == "running",
            )
            .order_by(WorkflowTask.id)
        )
        return list(res.scalars().all())

    async def done_for(self, user_id: int) -> list[WorkflowTask]:
        """已办：我已处理过的任务。"""
        res = await self.session.execute(
            select(WorkflowTask)
            .where(
                WorkflowTask.approver_id == user_id,
                WorkflowTask.status.in_(["approved", "rejected", "transferred"]),
            )
            .order_by(WorkflowTask.decided_at.desc())
        )
        return list(res.scalars().all())

    async def notified_for(self, user_id: int) -> list[WorkflowTask]:
        """抄送我：notify 节点产生的知会任务。"""
        res = await self.session.execute(
            select(WorkflowTask)
            .where(WorkflowTask.approver_id == user_id, WorkflowTask.node_type == "notify")
            .order_by(WorkflowTask.id.desc())
        )
        return list(res.scalars().all())

    # ---- 流转日志 ----
    async def add_log(self, log: WorkflowNodeLog) -> WorkflowNodeLog:
        self.session.add(log)
        await self.session.commit()
        return log

    async def list_logs(self, instance_id: int) -> list[WorkflowNodeLog]:
        res = await self.session.execute(
            select(WorkflowNodeLog)
            .where(WorkflowNodeLog.instance_id == instance_id)
            .order_by(WorkflowNodeLog.id)
        )
        return list(res.scalars().all())

    async def list_logs_for_instances(self, instance_ids: list[int]) -> list[WorkflowNodeLog]:
        """监控看板：批量取在途实例的流转日志，避免逐实例查询。"""
        if not instance_ids:
            return []
        res = await self.session.execute(
            select(WorkflowNodeLog).where(WorkflowNodeLog.instance_id.in_(instance_ids))
        )
        return list(res.scalars().all())

    # ---- 监控看板聚合查询 ----
    async def list_tasks_status(self, status: str) -> list[WorkflowTask]:
        """指定状态的全部任务（org-wide），供超时与待办统计。"""
        res = await self.session.execute(
            select(WorkflowTask)
            .where(WorkflowTask.status == status)
            .order_by(WorkflowTask.created_at)
        )
        return list(res.scalars().all())

    async def count_active_delegations(self, now: datetime) -> int:
        res = await self.session.execute(
            select(func.count())
            .select_from(WorkflowDelegation)
            .where(
                WorkflowDelegation.active.is_(True),
                WorkflowDelegation.start_at <= now,
                WorkflowDelegation.end_at >= now,
            )
        )
        return int(res.scalar_one())

    async def get_versions(self, ids: list[int]) -> list[WorkflowVersion]:
        """按 id 批量取版本（含 graph），用于解析在途实例当前节点名。"""
        if not ids:
            return []
        res = await self.session.execute(
            select(WorkflowVersion).where(WorkflowVersion.id.in_(ids))
        )
        return list(res.scalars().all())

    # ---- 委托 ----
    async def active_delegations(
        self, from_user_id: int, definition_id: int | None
    ) -> list[WorkflowDelegation]:
        # 委托表存 naive UTC（DateTime 列不带时区），查询参数同样用 naive，
        # 否则 PostgreSQL 下 aware 参数会与 timestamp without time zone 冲突。
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        stmt = select(WorkflowDelegation).where(
            WorkflowDelegation.from_user_id == from_user_id,
            WorkflowDelegation.active.is_(True),
            WorkflowDelegation.start_at <= now,
            WorkflowDelegation.end_at >= now,
        )
        res = await self.session.execute(stmt)
        rows = list(res.scalars().all())
        # 精确到流程的委托优先，其次通用委托
        scoped = [d for d in rows if d.definition_id == definition_id]
        return scoped or [d for d in rows if d.definition_id is None]

    # ---- 门户工作台聚合查询 ----
    async def pending_with_instance(self, user_id: int, limit: int = 5) -> list[WorkflowTask]:
        """待我审批：当前用户 pending 任务，并预加载所属实例（避免 N+1）。"""
        res = await self.session.execute(
            select(WorkflowTask)
            .options(selectinload(WorkflowTask.instance))
            .join(WorkflowInstance, WorkflowInstance.id == WorkflowTask.instance_id)
            .where(
                WorkflowTask.status == "pending",
                WorkflowTask.approver_id == user_id,
                WorkflowInstance.status == "running",
            )
            .order_by(WorkflowTask.id)
            .limit(limit)
        )
        return list(res.scalars().all())

    async def running_for_user(self, user_id: int, limit: int = 5) -> list[WorkflowInstance]:
        """我发起的在途流程（running）。"""
        res = await self.session.execute(
            select(WorkflowInstance)
            .where(
                WorkflowInstance.initiator_id == user_id,
                WorkflowInstance.status == "running",
            )
            .order_by(WorkflowInstance.started_at.desc())
            .limit(limit)
        )
        return list(res.scalars().all())

    async def count_pending(self) -> int:
        """全公司在途待办任务数（管理员/经理统计用）。"""
        res = await self.session.execute(
            select(func.count())
            .select_from(WorkflowTask)
            .join(WorkflowInstance, WorkflowInstance.id == WorkflowTask.instance_id)
            .where(WorkflowTask.status == "pending", WorkflowInstance.status == "running")
        )
        return int(res.scalar_one())

    # ---- 运维中心聚合查询 ----
    async def recent_instances(self, limit: int = 10) -> list[WorkflowInstance]:
        """最近实例（运维中心）；预加载定义，发起人名由服务层一次性映射避免 N+1。"""
        res = await self.session.execute(
            select(WorkflowInstance)
            .options(selectinload(WorkflowInstance.definition))
            .order_by(WorkflowInstance.created_at.desc())
            .limit(limit)
        )
        return list(res.scalars().all())

    async def count_instances_by_status(self) -> dict[str, int]:
        """按状态聚合实例数（运维中心）。"""
        res = await self.session.execute(
            select(WorkflowInstance.status, func.count())
            .group_by(WorkflowInstance.status)
        )
        return {str(r[0]): int(r[1]) for r in res.all()}

    async def count_for_initiator(self, user_id: int, status: str | None = None) -> int:
        """按发起人统计实例数（报表中心个人视图：在途流程数）。"""
        stmt = select(func.count()).select_from(WorkflowInstance).where(
            WorkflowInstance.initiator_id == user_id
        )
        if status:
            stmt = stmt.where(WorkflowInstance.status == status)
        res = await self.session.execute(stmt)
        return int(res.scalar_one())

    async def trend(self, days: int = 30) -> list[dict]:
        """近 N 天「发起量 / 完成量」趋势（报表中心）。

        日期分桶在 Python 侧完成（同 AuditRepository.stats），规避 SQLite/PostgreSQL
        日期函数方言差异；仅取窗口内的 started_at / finished_at 两列，不捞整行。
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        cutoff = (now - timedelta(days=days - 1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        cutoff_day = cutoff.date().isoformat()
        res = await self.session.execute(
            select(WorkflowInstance.started_at, WorkflowInstance.finished_at).where(
                or_(
                    WorkflowInstance.started_at >= cutoff,
                    WorkflowInstance.finished_at >= cutoff,
                )
            )
        )
        started: dict[str, int] = {}
        finished: dict[str, int] = {}
        for s, f in res.all():
            if s is not None:
                s = s.replace(tzinfo=None) if s.tzinfo else s
                d = s.date().isoformat()
                if d >= cutoff_day:
                    started[d] = started.get(d, 0) + 1
            if f is not None:
                f = f.replace(tzinfo=None) if f.tzinfo else f
                d = f.date().isoformat()
                if d >= cutoff_day:
                    finished[d] = finished.get(d, 0) + 1
        out: list[dict] = []
        for i in range(days - 1, -1, -1):
            day = (now - timedelta(days=i)).date().isoformat()
            out.append(
                {"date": day, "started": started.get(day, 0), "finished": finished.get(day, 0)}
            )
        return out

    async def list_running_overdue(self, sla_days: int) -> list[WorkflowInstance]:
        """返回超时且未升级的运行中实例，作为调度幂等扫描的边界。

        status='running' 且 started_at 早于 now-sla_days，且 escalated_at IS NULL。
        """
        cutoff = datetime.utcnow() - timedelta(days=sla_days)
        stmt = (
            select(WorkflowInstance)
            .where(
                WorkflowInstance.status == "running",
                WorkflowInstance.started_at < cutoff,
                WorkflowInstance.escalated_at.is_(None),
            )
            .order_by(WorkflowInstance.started_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def mark_escalated(self, instance_id: int) -> None:
        """标记实例已升级（写入 escalated_at），保证升级通知仅触发一次。"""
        inst = await self.get_instance(instance_id)
        if inst is not None:
            inst.escalated_at = datetime.utcnow()
            self.session.add(inst)
            await self.session.commit()

    async def list_pending_tasks(self, instance_id: int) -> list[WorkflowTask]:
        """返回该实例当前待审批的任务（status='pending'），供超时自动转交使用。"""
        stmt = (
            select(WorkflowTask)
            .where(
                WorkflowTask.instance_id == instance_id,
                WorkflowTask.status == "pending",
            )
            .options(selectinload(WorkflowTask.instance))
        )
        return list((await self.session.execute(stmt)).scalars().all())


# ---------- 调度死信 ----------


class SchedulerRepository:
    """后台任务死信存储：失败落盘并支持按 (task_name, ref_id) 去重。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def write_dead_letter(
        self, task_name: str, ref_id: int | None, payload: dict, error: str
    ) -> DeadLetter:
        dl = DeadLetter(
            task_name=task_name, ref_id=ref_id, payload=payload or {}, error=error
        )
        self.session.add(dl)
        await self.session.commit()
        await self.session.refresh(dl)
        return dl

    async def exists_dead_letter(self, task_name: str, ref_id: int | None) -> bool:
        from sqlalchemy import exists

        stmt = select(
            exists().where(
                DeadLetter.task_name == task_name,
                DeadLetter.ref_id == ref_id,
            )
        )
        return bool((await self.session.execute(stmt)).scalar())


# ---------- 电子签单 ----------
class SignatureRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, sig: Signature) -> Signature:
        self.session.add(sig)
        await self.session.commit()
        await self.session.refresh(sig)
        return sig

    async def list_by_ref(self, ref_type: str, ref_id: int) -> list[Signature]:
        res = await self.session.execute(
            select(Signature)
            .where(Signature.ref_type == ref_type, Signature.ref_id == ref_id)
            .order_by(Signature.signed_at.desc())
        )
        return list(res.scalars().all())


# ---------- 建模引擎：自定义实体 / 数据行 ----------
# 说明：记录数据存 JSON 列，JSON 字段在 SQLite/PostgreSQL 上的查询与索引语法不同，
# 因此不在仓储层拼方言 SQL，改为「取行 + 服务层过滤」，并以 MAX_SCAN 限制单次扫描行数。
MAX_SCAN = 2000


class ModelEntityRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, entity: ModelEntity) -> ModelEntity:
        self.session.add(entity)
        await self.session.commit()
        await self.session.refresh(entity)
        return entity

    async def get(self, entity_id: int) -> ModelEntity | None:
        res = await self.session.execute(
            select(ModelEntity).where(ModelEntity.id == entity_id)
        )
        return res.scalar_one_or_none()

    async def get_by_code(self, code: str) -> ModelEntity | None:
        res = await self.session.execute(
            select(ModelEntity).where(ModelEntity.code == code)
        )
        return res.scalar_one_or_none()

    async def list(self, status: str | None = None) -> list[ModelEntity]:
        stmt = select(ModelEntity).order_by(ModelEntity.id.desc())
        if status:
            stmt = stmt.where(ModelEntity.status == status)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def delete(self, entity: ModelEntity) -> None:
        await self.session.delete(entity)
        await self.session.commit()

    async def count(self, status: str | None = None) -> int:
        stmt = select(func.count()).select_from(ModelEntity)
        if status:
            stmt = stmt.where(ModelEntity.status == status)
        res = await self.session.execute(stmt)
        return int(res.scalar_one())

    async def count_records_map(self) -> dict[int, int]:
        """按实体分组统计记录数（单次 group by，避免逐实体 count 造成 N+1）。"""
        res = await self.session.execute(
            select(ModelRecord.entity_id, func.count()).group_by(ModelRecord.entity_id)
        )
        return {int(r[0]): int(r[1]) for r in res.all()}


class ModelRecordRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, rec: ModelRecord) -> ModelRecord:
        self.session.add(rec)
        await self.session.commit()
        await self.session.refresh(rec)
        return rec

    async def get(self, rec_id: int) -> ModelRecord | None:
        res = await self.session.execute(
            select(ModelRecord).where(ModelRecord.id == rec_id)
        )
        return res.scalar_one_or_none()

    async def list_by_entity(
        self, entity_id: int, offset: int = 0, limit: int = MAX_SCAN
    ) -> list[ModelRecord]:
        res = await self.session.execute(
            select(ModelRecord)
            .where(ModelRecord.entity_id == entity_id)
            .order_by(ModelRecord.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(res.scalars().all())

    async def count_by_entity(self, entity_id: int) -> int:
        res = await self.session.execute(
            select(func.count())
            .select_from(ModelRecord)
            .where(ModelRecord.entity_id == entity_id)
        )
        return int(res.scalar_one())

    async def update(self, rec: ModelRecord) -> ModelRecord:
        await self.session.commit()
        await self.session.refresh(rec)
        return rec

    async def delete(self, rec: ModelRecord) -> None:
        await self.session.delete(rec)
        await self.session.commit()

    async def count(self) -> int:
        res = await self.session.execute(select(func.count()).select_from(ModelRecord))
        return int(res.scalar_one())

    async def count_today(self, start: datetime) -> int:
        res = await self.session.execute(
            select(func.count())
            .select_from(ModelRecord)
            .where(ModelRecord.created_at >= start)
        )
        return int(res.scalar_one())

    async def top_entities(self, limit: int = 8) -> list[tuple[int, int]]:
        """记录数最多的实体（建模概览用），返回 (entity_id, count)。"""
        res = await self.session.execute(
            select(ModelRecord.entity_id, func.count())
            .group_by(ModelRecord.entity_id)
            .order_by(func.count().desc())
            .limit(limit)
        )
        return [(int(r[0]), int(r[1])) for r in res.all()]


# ---------- 日志中心：审计日志（查询维度全部为物理列，可直接下推数据库） ----------
class AuditRepository:
    """审计日志仓储：列表/计数/聚合统计/清理，均走 AuditLog 的物理列，无需服务层内存过滤。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, log: AuditLog) -> AuditLog:
        self.session.add(log)
        await self.session.commit()
        await self.session.refresh(log)
        return log

    def _apply_filters(self, stmt, *, actor_id=None, module=None, action=None, status=None,
                       target_type=None, q=None, start=None, end=None):
        if actor_id is not None:
            stmt = stmt.where(AuditLog.actor_id == actor_id)
        if module:
            stmt = stmt.where(AuditLog.module == module)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        if status:
            stmt = stmt.where(AuditLog.status == status)
        if target_type:
            stmt = stmt.where(AuditLog.target_type == target_type)
        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(
                or_(
                    AuditLog.path.ilike(pattern),
                    AuditLog.actor_name.ilike(pattern),
                    AuditLog.message.ilike(pattern),
                )
            )
        if start:
            stmt = stmt.where(AuditLog.created_at >= start)
        if end:
            stmt = stmt.where(AuditLog.created_at <= end)
        return stmt

    async def list_logs(self, *, actor_id=None, module=None, action=None, status=None,
                        target_type=None, q=None, start=None, end=None,
                        offset: int = 0, limit: int = 50) -> list[AuditLog]:
        stmt = self._apply_filters(
            select(AuditLog).order_by(AuditLog.created_at.desc()),
            actor_id=actor_id, module=module, action=action, status=status,
            target_type=target_type, q=q, start=start, end=end,
        )
        stmt = stmt.offset(offset).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def count_logs(self, *, actor_id=None, module=None, action=None, status=None,
                         target_type=None, q=None, start=None, end=None) -> int:
        stmt = self._apply_filters(
            select(func.count()).select_from(AuditLog),
            actor_id=actor_id, module=module, action=action, status=status,
            target_type=target_type, q=q, start=start, end=end,
        )
        res = await self.session.execute(stmt)
        return int(res.scalar_one())

    async def stats(self) -> dict:
        """聚合：总量、按模块、按状态、近 14 天趋势。趋势在 Python 侧分桶，规避 SQLite/PG 方言差异。"""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        cutoff = now - timedelta(days=14)

        total = await self._count_where()
        success = await self._count_where(AuditLog.status == "success")
        failed = await self._count_where(AuditLog.status == "failed")
        by_module = await self._group_count(AuditLog.module)
        by_status = await self._group_count(AuditLog.status)

        rows = await self.session.execute(
            select(AuditLog.created_at).where(AuditLog.created_at >= cutoff)
        )
        day_counts: dict[str, int] = {}
        for (ts,) in rows.all():
            dt = ts.replace(tzinfo=None) if ts.tzinfo else ts
            day = dt.date().isoformat()
            day_counts[day] = day_counts.get(day, 0) + 1

        trend: list[dict] = []
        for d in range(13, -1, -1):
            day = (now - timedelta(days=d)).date()
            trend.append({"date": day.isoformat(), "count": day_counts.get(day.isoformat(), 0)})

        return {
            "total": total,
            "success": success,
            "failed": failed,
            "by_module": by_module,
            "by_status": by_status,
            "trend": trend,
        }

    async def _count_where(self, *conds) -> int:
        stmt = select(func.count()).select_from(AuditLog)
        for c in conds:
            stmt = stmt.where(c)
        res = await self.session.execute(stmt)
        return int(res.scalar_one())

    async def _group_count(self, col) -> list[dict]:
        res = await self.session.execute(
            select(col, func.count()).group_by(col).order_by(func.count().desc())
        )
        return [{"key": r[0] or "unknown", "count": int(r[1])} for r in res.all()]

    async def purge_before(self, cutoff: datetime) -> int:
        """清理 cutoff 之前的审计记录；返回删除行数（0 行不执行删除，避免空事务）。"""
        res = await self.session.execute(
            select(func.count()).select_from(AuditLog).where(AuditLog.created_at < cutoff)
        )
        deleted = int(res.scalar_one())
        if deleted == 0:
            return 0
        await self.session.execute(
            AuditLog.__table__.delete().where(AuditLog.created_at < cutoff)
        )
        await self.session.commit()
        return deleted

    async def get_log_detail(self, log_id: int) -> AuditLog | None:
        """获取单条审计日志详情（含 before/after value, correlation_id, duration_ms）"""
        res = await self.session.execute(
            select(AuditLog).where(AuditLog.id == log_id)
        )
        return res.scalar_one_or_none()

    async def list_logs_with_correlation(
        self, correlation_id: str, offset: int = 0, limit: int = 50
    ) -> list[AuditLog]:
        """按关联 ID 查询关联的审计日志"""
        res = await self.session.execute(
            select(AuditLog)
            .where(AuditLog.correlation_id == correlation_id)
            .order_by(AuditLog.created_at.desc())
            .offset(offset).limit(limit)
        )
        return list(res.scalars().all())

    async def count_by_correlation(self, correlation_id: str) -> int:
        """统计指定关联 ID 的日志数量"""
        res = await self.session.execute(
            select(func.count()).select_from(AuditLog).where(AuditLog.correlation_id == correlation_id)
        )
        return int(res.scalar_one())

    async def stats_duration(self, module: str | None = None) -> dict:
        """统计请求耗时分布"""
        stmt = select(AuditLog.duration_ms).where(AuditLog.duration_ms.is_not(None))
        if module:
            stmt = stmt.where(AuditLog.module == module)
        res = await self.session.execute(stmt)
        durations = [r[0] for r in res.all() if r[0] is not None]
        if not durations:
            return {"avg": 0, "p50": 0, "p95": 0, "p99": 0, "max": 0, "count": 0}
        durations.sort()
        n = len(durations)
        return {
            "avg": sum(durations) / n,
            "p50": durations[n // 2],
            "p95": durations[int(n * 0.95)],
            "p99": durations[int(n * 0.99)],
            "max": durations[-1],
            "count": n,
        }


# ---------- 消息中心：通知收件箱 ----------
class NotificationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_for_user(
        self, user_id: int, only_unread: bool = False, limit: int = 50, offset: int = 0
    ) -> list[Notification]:
        stmt = (
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
        )
        if only_unread:
            stmt = stmt.where(Notification.is_read.is_(False))
        stmt = stmt.limit(limit).offset(offset)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def count_for_user(self, user_id: int, only_unread: bool = False) -> int:
        stmt = select(func.count()).select_from(Notification).where(
            Notification.user_id == user_id
        )
        if only_unread:
            stmt = stmt.where(Notification.is_read.is_(False))
        res = await self.session.execute(stmt)
        return int(res.scalar_one())

    async def get_owned(self, nid: int, user_id: int) -> Notification | None:
        res = await self.session.execute(
            select(Notification).where(
                Notification.id == nid, Notification.user_id == user_id
            )
        )
        return res.scalar_one_or_none()

    async def mark_read(self, nid: int, user_id: int) -> None:
        await self.session.execute(
            Notification.__table__.update()
            .where(Notification.id == nid, Notification.user_id == user_id)
            .values(is_read=True)
        )
        await self.session.commit()

    async def mark_all_read(self, user_id: int) -> int:
        res = await self.session.execute(
            select(func.count()).select_from(Notification).where(
                Notification.user_id == user_id, Notification.is_read.is_(False)
            )
        )
        n = int(res.scalar_one())
        if n == 0:
            return 0
        await self.session.execute(
            Notification.__table__.update()
            .where(Notification.user_id == user_id, Notification.is_read.is_(False))
            .values(is_read=True)
        )
        await self.session.commit()
        return n


# ---------- 考勤管理 ----------
class AttendanceRepository:
    """考勤：一天一行 upsert + 按人/按月区间查询（关联 user 一次取回防 N+1）。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_day(self, user_id: int, day: date) -> Attendance | None:
        res = await self.session.execute(
            select(Attendance).where(Attendance.user_id == user_id, Attendance.day == day)
        )
        return res.scalar_one_or_none()

    async def create(self, rec: Attendance) -> Attendance:
        self.session.add(rec)
        await self.session.commit()
        await self.session.refresh(rec)
        return rec

    async def update(self, rec: Attendance) -> Attendance:
        await self.session.commit()
        await self.session.refresh(rec)
        return rec

    async def list_month(
        self, user_id: int | None, year: int, month: int, limit: int = 800
    ) -> list[Attendance]:
        start = date(year, month, 1)
        end = date(year + (1 if month == 12 else 0), 1 if month == 12 else month + 1, 1)
        stmt = (
            select(Attendance)
            .where(Attendance.day >= start, Attendance.day < end)
            .options(selectinload(Attendance.user))
            .order_by(Attendance.day)
        )
        if user_id is not None:
            stmt = stmt.where(Attendance.user_id == user_id)
        stmt = stmt.limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def list_range(
        self, *, start: date, end: date, user_id: int | None = None,
        status: str | None = None, offset: int = 0, limit: int = 50,
    ) -> list[Attendance]:
        stmt = (
            select(Attendance)
            .where(Attendance.day >= start, Attendance.day <= end)
            .options(selectinload(Attendance.user))
            .order_by(Attendance.day.desc(), Attendance.user_id)
        )
        if user_id is not None:
            stmt = stmt.where(Attendance.user_id == user_id)
        if status:
            stmt = stmt.where(Attendance.status == status)
        stmt = stmt.offset(offset).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def count_range(
        self, *, start: date, end: date, user_id: int | None = None, status: str | None = None
    ) -> int:
        stmt = select(func.count()).select_from(Attendance).where(
            Attendance.day >= start, Attendance.day <= end
        )
        if user_id is not None:
            stmt = stmt.where(Attendance.user_id == user_id)
        if status:
            stmt = stmt.where(Attendance.status == status)
        res = await self.session.execute(stmt)
        return int(res.scalar_one())

    async def group_by_user_month(
        self, year: int, month: int
    ) -> list[tuple[int, int, int, int, int]]:
        """按人汇总当月 (user_id, 出勤, 免出勤标记, 迟到, 早退)。

        出勤 = 有上班打卡；免出勤 = 无打卡但被标记请假/出差/远程；二者都不算缺勤。
        """
        start = date(year, month, 1)
        end = date(year + (1 if month == 12 else 0), 1 if month == 12 else month + 1, 1)
        attended = case((Attendance.check_in.is_not(None), 1), else_=0)
        excused = case(
            (
                and_(
                    Attendance.check_in.is_(None),
                    Attendance.status.in_(["leave", "travel", "remote"]),
                ),
                1,
            ),
            else_=0,
        )
        late = case((Attendance.late_minutes > 0, 1), else_=0)
        early = case((Attendance.early_minutes > 0, 1), else_=0)
        res = await self.session.execute(
            select(
                Attendance.user_id,
                func.coalesce(func.sum(attended), 0),
                func.coalesce(func.sum(excused), 0),
                func.coalesce(func.sum(late), 0),
                func.coalesce(func.sum(early), 0),
            )
            .where(Attendance.day >= start, Attendance.day < end)
            .group_by(Attendance.user_id)
        )
        return [(r[0], int(r[1]), int(r[2]), int(r[3]), int(r[4])) for r in res.all()]

    async def get(self, rid: int) -> Attendance | None:
        res = await self.session.execute(
            select(Attendance)
            .where(Attendance.id == rid)
            .options(selectinload(Attendance.user))
        )
        return res.scalar_one_or_none()

    # ---- 班次设置（单行） ----
    async def get_settings(self) -> AttendanceSetting | None:
        res = await self.session.execute(select(AttendanceSetting).limit(1))
        return res.scalar_one_or_none()

    async def save_settings(self, setting: AttendanceSetting) -> AttendanceSetting:
        existing = await self.get_settings()
        if existing is None:
            self.session.add(setting)
            await self.session.commit()
            await self.session.refresh(setting)
            return setting
        for field in ("name", "work_start", "work_end", "late_grace_minutes", "workdays", "updated_by"):
            value = getattr(setting, field, None)
            if value is not None:
                setattr(existing, field, value)
        await self.session.commit()
        await self.session.refresh(existing)
        return existing


class OvertimeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, item: OvertimeRequest) -> OvertimeRequest:
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def get(self, oid: int) -> OvertimeRequest | None:
        res = await self.session.execute(
            select(OvertimeRequest)
            .where(OvertimeRequest.id == oid)
            .options(selectinload(OvertimeRequest.user))
        )
        return res.scalar_one_or_none()

    async def list(
        self, user_id: int | None = None, status: str | None = None,
        offset: int = 0, limit: int = 50,
    ) -> list[OvertimeRequest]:
        stmt = (
            select(OvertimeRequest)
            .options(selectinload(OvertimeRequest.user))
            .order_by(OvertimeRequest.day.desc(), OvertimeRequest.id.desc())
        )
        if user_id is not None:
            stmt = stmt.where(OvertimeRequest.user_id == user_id)
        if status:
            stmt = stmt.where(OvertimeRequest.status == status)
        res = await self.session.execute(stmt.offset(offset).limit(limit))
        return list(res.scalars().all())

    async def count(self, user_id: int | None = None, status: str | None = None) -> int:
        stmt = select(func.count()).select_from(OvertimeRequest)
        if user_id is not None:
            stmt = stmt.where(OvertimeRequest.user_id == user_id)
        if status:
            stmt = stmt.where(OvertimeRequest.status == status)
        res = await self.session.execute(stmt)
        return int(res.scalar_one())

    async def approved_hours(self, user_id: int, start: date, end: date) -> float:
        res = await self.session.execute(
            select(func.coalesce(func.sum(OvertimeRequest.hours), 0.0)).where(
                OvertimeRequest.user_id == user_id,
                OvertimeRequest.status == "approved",
                OvertimeRequest.day >= start,
                OvertimeRequest.day < end,
            )
        )
        return float(res.scalar_one())


# ---------- 外勤申请（考勤外勤关联） ----------
class FieldWorkRepository:
    """外勤申请单：按人/状态/日期区间查询，打卡与导入按「已通过 + 日期覆盖」关联。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, item: FieldWorkOrder) -> FieldWorkOrder:
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def get(self, oid: int) -> FieldWorkOrder | None:
        res = await self.session.execute(
            select(FieldWorkOrder)
            .where(FieldWorkOrder.id == oid)
            .options(selectinload(FieldWorkOrder.user))
        )
        return res.scalar_one_or_none()

    async def list(
        self, *, user_id: int | None = None, status: str | None = None,
        start: date | None = None, end: date | None = None,
        offset: int = 0, limit: int = 50,
    ) -> list[FieldWorkOrder]:
        stmt = (
            select(FieldWorkOrder)
            .options(selectinload(FieldWorkOrder.user))
            .order_by(FieldWorkOrder.start_date.desc(), FieldWorkOrder.id.desc())
        )
        if user_id is not None:
            stmt = stmt.where(FieldWorkOrder.user_id == user_id)
        if status:
            stmt = stmt.where(FieldWorkOrder.status == status)
        if start is not None:
            stmt = stmt.where(FieldWorkOrder.end_date >= start)
        if end is not None:
            stmt = stmt.where(FieldWorkOrder.start_date <= end)
        res = await self.session.execute(stmt.offset(offset).limit(limit))
        return list(res.scalars().all())

    async def count(
        self, *, user_id: int | None = None, status: str | None = None,
        start: date | None = None, end: date | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(FieldWorkOrder)
        if user_id is not None:
            stmt = stmt.where(FieldWorkOrder.user_id == user_id)
        if status:
            stmt = stmt.where(FieldWorkOrder.status == status)
        if start is not None:
            stmt = stmt.where(FieldWorkOrder.end_date >= start)
        if end is not None:
            stmt = stmt.where(FieldWorkOrder.start_date <= end)
        return int((await self.session.execute(stmt)).scalar_one())

    async def approved_covering(
        self, *, start: date, end: date, user_ids: list[int] | None = None,
    ) -> list[FieldWorkOrder]:
        """日期区间 [start, end] 内已通过的外勤单（打卡/导入做关联用，一次查询防 N+1）。"""
        stmt = select(FieldWorkOrder).where(
            FieldWorkOrder.status == "approved",
            FieldWorkOrder.start_date <= end,
            FieldWorkOrder.end_date >= start,
        )
        if user_ids is not None:
            if not user_ids:
                return []
            stmt = stmt.where(FieldWorkOrder.user_id.in_(user_ids))
        res = await self.session.execute(stmt.order_by(FieldWorkOrder.start_date))
        return list(res.scalars().all())


# ---------- 审批委托（代审） ----------
class DelegationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list(self, from_user_id: int | None = None) -> list[WorkflowDelegation]:
        stmt = select(WorkflowDelegation).order_by(WorkflowDelegation.start_at.desc())
        if from_user_id is not None:
            stmt = stmt.where(WorkflowDelegation.from_user_id == from_user_id)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get(self, did: int) -> WorkflowDelegation | None:
        res = await self.session.execute(
            select(WorkflowDelegation).where(WorkflowDelegation.id == did)
        )
        return res.scalar_one_or_none()

    async def create(self, item: WorkflowDelegation) -> WorkflowDelegation:
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def update(self, item: WorkflowDelegation) -> WorkflowDelegation:
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def delete(self, item: WorkflowDelegation) -> None:
        await self.session.delete(item)
        await self.session.commit()


# ---------- 报销单 ----------
class ExpenseRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, claim: ExpenseClaim) -> ExpenseClaim:
        self.session.add(claim)
        await self.session.commit()
        await self.session.refresh(claim)
        return claim

    async def get(self, eid: int) -> ExpenseClaim | None:
        res = await self.session.execute(
            select(ExpenseClaim)
            .where(ExpenseClaim.id == eid)
            .options(selectinload(ExpenseClaim.user))
        )
        return res.scalar_one_or_none()

    async def get_by_workflow(self, instance_id: int) -> ExpenseClaim | None:
        res = await self.session.execute(
            select(ExpenseClaim).where(ExpenseClaim.workflow_instance_id == instance_id)
        )
        return res.scalar_one_or_none()

    async def _base(self, *, user_id: int | None, status: str | None, month: str | None, q: str | None):
        stmt = select(ExpenseClaim).options(selectinload(ExpenseClaim.user))
        if user_id is not None:
            stmt = stmt.where(ExpenseClaim.user_id == user_id)
        if status and status != "all":
            stmt = stmt.where(ExpenseClaim.status == status)
        if q:
            stmt = stmt.where(
                or_(ExpenseClaim.code.ilike(f"%{q}%"), ExpenseClaim.description.ilike(f"%{q}%"))
            )
        if month:
            # month 形如 2026-09：按 occur_date 落在该月过滤
            try:
                y, m = (int(x) for x in month.split("-"))
                start = date(y, m, 1)
                end = date(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1)
                stmt = stmt.where(ExpenseClaim.occur_date >= start, ExpenseClaim.occur_date < end)
            except ValueError:
                pass
        return stmt

    async def list(
        self, *, user_id: int | None = None, status: str | None = None,
        month: str | None = None, q: str | None = None,
        offset: int = 0, limit: int = 50,
    ) -> list[ExpenseClaim]:
        stmt = await self._base(user_id=user_id, status=status, month=month, q=q)
        stmt = stmt.order_by(ExpenseClaim.created_at.desc()).offset(offset).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def count(
        self, *, user_id: int | None = None, status: str | None = None,
        month: str | None = None, q: str | None = None,
    ) -> int:
        stmt = await self._base(user_id=user_id, status=status, month=month, q=q)
        res = await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        return int(res.scalar_one())

    async def sum_amount(
        self, *, user_id: int | None = None, status: str | None = None,
        month: str | None = None, q: str | None = None,
    ) -> float:
        stmt = await self._base(user_id=user_id, status=status, month=month, q=q)
        # 必须引用子查询的列：直接用 ExpenseClaim.amount 会与子查询形成笛卡尔积
        sub = stmt.subquery()
        res = await self.session.execute(
            select(func.coalesce(func.sum(sub.c.amount), 0.0)).select_from(sub)
        )
        return float(res.scalar_one())

    async def group_by_status(self, month: str | None = None) -> list[dict]:
        stmt = await self._base(user_id=None, status=None, month=month, q=None)
        sub = stmt.subquery()
        res = await self.session.execute(
            select(
                sub.c.status,
                func.count(sub.c.id),
                func.coalesce(func.sum(sub.c.amount), 0.0),
            )
            .select_from(sub)
            .group_by(sub.c.status)
        )
        return [
            {"status": r[0], "count": int(r[1]), "amount": float(r[2])} for r in res.all()
        ]

    async def group_by_type(self, month: str | None = None) -> list[dict]:
        stmt = await self._base(user_id=None, status=None, month=month, q=None)
        sub = stmt.subquery()
        res = await self.session.execute(
            select(
                sub.c.claim_type,
                func.count(sub.c.id),
                func.coalesce(func.sum(sub.c.amount), 0.0),
            )
            .select_from(sub)
            .group_by(sub.c.claim_type)
        )
        return [
            {"type": r[0], "count": int(r[1]), "amount": float(r[2])} for r in res.all()
        ]

    async def update(self, claim: ExpenseClaim) -> ExpenseClaim:
        await self.session.commit()
        await self.session.refresh(claim)
        return claim

    async def delete(self, claim: ExpenseClaim) -> None:
        await self.session.delete(claim)
        await self.session.commit()


# ---------- 公文 ----------
class OfficialDocRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, doc: OfficialDocument) -> OfficialDocument:
        self.session.add(doc)
        await self.session.commit()
        await self.session.refresh(doc)
        return doc

    async def get(self, did: int) -> OfficialDocument | None:
        res = await self.session.execute(
            select(OfficialDocument).where(OfficialDocument.id == did)
        )
        return res.scalar_one_or_none()

    async def get_by_doc_no(self, doc_no: str) -> OfficialDocument | None:
        res = await self.session.execute(
            select(OfficialDocument).where(OfficialDocument.doc_no == doc_no)
        )
        return res.scalar_one_or_none()

    async def get_max_seq(self, year: int, prefix: str) -> int:
        """获取指定年份和前缀的最大序号"""
        res = await self.session.execute(
            select(func.coalesce(func.max(OfficialDocument.seq), 0)).where(
                OfficialDocument.doc_no.like(f"{prefix}-{year}-%")
            )
        )
        return int(res.scalar_one())

    async def _base(self, *, direction: str | None, status: str | None, q: str | None):
        stmt = select(OfficialDocument)
        if direction and direction in ("in", "out"):
            stmt = stmt.where(OfficialDocument.direction == direction)
        if status and status != "all":
            stmt = stmt.where(OfficialDocument.status == status)
        if q:
            stmt = stmt.where(
                or_(
                    OfficialDocument.doc_no.ilike(f"%{q}%"),
                    OfficialDocument.title.ilike(f"%{q}%"),
                    OfficialDocument.from_org.ilike(f"%{q}%"),
                )
            )
        return stmt

    async def list(
        self, *, direction: str | None = None, status: str | None = None,
        q: str | None = None, offset: int = 0, limit: int = 50,
    ) -> list[OfficialDocument]:
        stmt = await self._base(direction=direction, status=status, q=q)
        stmt = stmt.order_by(OfficialDocument.created_at.desc()).offset(offset).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def count(
        self, *, direction: str | None = None, status: str | None = None, q: str | None = None
    ) -> int:
        stmt = await self._base(direction=direction, status=status, q=q)
        res = await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        return int(res.scalar_one())

    async def update(self, doc: OfficialDocument) -> OfficialDocument:
        await self.session.commit()
        await self.session.refresh(doc)
        return doc

    async def delete(self, doc: OfficialDocument) -> None:
        await self.session.delete(doc)
        await self.session.commit()


# ---------- 公文流转事件（时间线） ----------
class OfficialDocEventRepository:
    """公文事件：记录状态变更、传阅、归档等操作，供前端时间线可视化。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, event: "OfficialDocEvent") -> "OfficialDocEvent":
        self.session.add(event)
        await self.session.commit()
        await self.session.refresh(event)
        return event

    async def list_by_doc(self, doc_id: int) -> list["OfficialDocEvent"]:
        res = await self.session.execute(
            select(OfficialDocEvent)
            .where(OfficialDocEvent.doc_id == doc_id)
            .order_by(OfficialDocEvent.created_at.desc())
        )
        return list(res.scalars().all())


# ---------- 文档版本 / 公告阅读回执 ----------
class DocumentVersionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_doc(self, document_id: int) -> list[DocumentVersion]:
        res = await self.session.execute(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version.desc())
        )
        return list(res.scalars().all())

    async def get(self, vid: int) -> DocumentVersion | None:
        res = await self.session.execute(
            select(DocumentVersion).where(DocumentVersion.id == vid)
        )
        return res.scalar_one_or_none()

    async def create(self, item: DocumentVersion) -> DocumentVersion:
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def max_version(self, document_id: int) -> int:
        res = await self.session.execute(
            select(func.coalesce(func.max(DocumentVersion.version), 0)).where(
                DocumentVersion.document_id == document_id
            )
        )
        return int(res.scalar_one())


class AnnouncementReadRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def has_read(self, announcement_id: int, user_id: int) -> bool:
        res = await self.session.execute(
            select(AnnouncementRead.id).where(
                AnnouncementRead.announcement_id == announcement_id,
                AnnouncementRead.user_id == user_id,
            )
        )
        return res.scalar_one_or_none() is not None

    async def mark_read(self, announcement_id: int, user_id: int) -> bool:
        """标记已读；已存在则不重复计数，返回是否为本次新增。"""
        if await self.has_read(announcement_id, user_id):
            return False
        self.session.add(AnnouncementRead(announcement_id=announcement_id, user_id=user_id))
        await self.session.commit()
        return True

    async def count_readers(self, announcement_id: int) -> int:
        res = await self.session.execute(
            select(func.count()).select_from(AnnouncementRead).where(
                AnnouncementRead.announcement_id == announcement_id
            )
        )
        return int(res.scalar_one())

    async def list_readers(self, announcement_id: int, limit: int = 200):
        """返回 [(AnnouncementRead, 用户显示名)]，一次 join 取回姓名避免 N+1。"""
        res = await self.session.execute(
            select(AnnouncementRead, User.username, User.full_name)
            .join(User, User.id == AnnouncementRead.user_id)
            .where(AnnouncementRead.announcement_id == announcement_id)
            .order_by(AnnouncementRead.read_at.desc())
            .limit(limit)
        )
        return [
            (row[0], row[2] or row[1]) for row in res.all()
        ]

    async def count_users(self) -> int:
        res = await self.session.execute(
            select(func.count()).select_from(User).where(User.is_active.is_(True))
        )
        return int(res.scalar_one())
