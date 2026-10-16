"""服务层：承载业务规则与编排，多步写入放入事务；不依赖 HTTP 类型。"""
from __future__ import annotations

import hashlib
import os
import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select, or_, case, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import get_settings
from app.core.db import engine
from app.core.storage import get_storage
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, UnauthorizedError, ValidationError
from app.core.logging import get_logger
from app.model_fields import clean_data, normalize_fields, record_matches
from app.realtime.events import EventBus, EventType, RealtimeEvent
from app.models import (
    Announcement,
    AnnouncementRead,
    Attendance,
    AttendanceSetting,
    AuditLog,
    Budget,
    Department,
    Document,
    DocumentVersion,
    ExpenseClaim,
    FieldWorkOrder,
    LeaveRequest,
    Menu,
    ModelEntity,
    ModelRecord,
    Notification,
    OfficialDocument,
    OvertimeRequest,
    Permission,
    Role,
    RolePermission,
    Signature,
    User,
    WorkflowDelegation,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowNodeLog,
    WorkflowTask,
)
from app.repositories import (
    AnnouncementReadRepository,
    AnnouncementRepository,
    AttendanceRepository,
    AuditRepository,
    DelegationRepository,
    DepartmentRepository,
    DocumentRepository,
    DocumentVersionRepository,
    ExpenseRepository,
    FieldWorkRepository,
    LeaveRepository,
    OfficialDocEventRepository,
    MenuRepository,
    MAX_SCAN,
    ModelEntityRepository,
    ModelRecordRepository,
    NotificationRepository,
    OfficialDocRepository,
    OvertimeRepository,
    PermissionRepository,
    RefreshTokenRepository,
    RoleRepository,
    SignatureRepository,
    SchedulerRepository,
    UserRepository,
    WorkflowRepository,
)
from app.schemas import (
    AnnouncementCreate,
    AnnouncementUpdate,
    AuditLogOut,
    AuditStatsOut,
    DepartmentCreate,
    DepartmentUpdate,
    DocumentOut,
    DocumentUpdate,
    DocumentsPage,
    LeaveCreate,
    NotificationOut,
    LeaveReview,
    MenuCreate,
    MenuUpdate,
    ModelEntityCreate,
    ModelEntityOut,
    ModelEntityUpdate,
    ModelRecordCreate,
    ModelRecordOut,
    ModelRecordsPage,
    ModelStatsOut,
    ModelRecordUpdate,
    OpsOverviewOut,
    PermissionCreate,
    RoleCreate,
    RoleOut,
    RoleUpdate,
    SignatureCreate,
    UserCreate,
    UserUpdate,
    WorkflowDefinitionCreate,
    WorkflowInstanceCreate,
    WorkflowReview,
)

logger = get_logger("documents")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    """把入库后的 naive 时间按 UTC 解释成 aware，避免「naive vs aware」比较抛 TypeError。

    数据库列是 `DateTime`（不带时区）：写入时 aware UTC 会丢掉 tzinfo，读回来即 naive UTC。
    直接 `record.expires_at < datetime.now(timezone.utc)` 会抛
    `TypeError: can't compare offset-naive and offset-aware datetimes`（刷新令牌接口 500）。
    """
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------- 认证 ----------
class AuthService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.users = UserRepository(session)
        self.tokens = RefreshTokenRepository(session)

    async def login(self, username: str, password: str) -> tuple[str, str, User]:
        user = await self.users.get_by_username(username)
        if not user or not user.is_active or not security.verify_password(password, user.hashed_password):
            raise UnauthorizedError("用户名或密码错误")
        access = security.create_access_token(user.id, user.role.name)
        raw_refresh, expire = security.create_refresh_token()
        await self.tokens.create(user.id, _hash_token(raw_refresh), _now() + expire)
        return access, raw_refresh, user

    async def refresh(self, raw_refresh: str) -> tuple[str, str]:
        try:
            payload = security.decode_token(raw_refresh, "refresh")
        except Exception:
            raise UnauthorizedError("刷新令牌无效")
        record = await self.tokens.get_by_hash(_hash_token(raw_refresh))
        if not record or record.revoked:
            raise UnauthorizedError("刷新令牌已失效")
        if _as_utc(record.expires_at) < _now():
            raise UnauthorizedError("刷新令牌已过期")
        user = await self.users.get_by_id(record.user_id)
        if not user or not user.is_active:
            raise UnauthorizedError("用户不可用")
        # 轮换：吊销旧令牌，签发新对
        await self.tokens.revoke(record)
        access = security.create_access_token(user.id, user.role.name)
        new_raw, expire = security.create_refresh_token()
        await self.tokens.create(user.id, _hash_token(new_raw), _now() + expire)
        return access, new_raw

    async def logout(self, raw_refresh: str) -> None:
        record = await self.tokens.get_by_hash(_hash_token(raw_refresh))
        if record:
            await self.tokens.revoke(record)

    async def get_current_user(self, user_id: int) -> User:
        user = await self.users.get_by_id(user_id)
        if not user or not user.is_active:
            raise UnauthorizedError("用户不可用")
        return user


# ---------- 用户 / 部门 ----------
class UserService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.users = UserRepository(session)
        self.roles = RoleRepository(session)

    async def create(self, data: UserCreate) -> User:
        if await self.users.exists_username(data.username):
            raise ConflictError("用户名已存在")
        if not await self.roles.get_by_id(data.role_id):
            raise ValidationError("角色不存在")
        if data.department_id and not await _department_exists(self.session, data.department_id):
            raise ValidationError("部门不存在")
        user = User(
            username=data.username,
            email=data.email,
            full_name=data.full_name,
            hashed_password=security.hash_password(data.password),
            role_id=data.role_id,
            department_id=data.department_id,
        )
        return await self.users.create(user)

    async def update(self, user_id: int, data: UserUpdate, actor: User) -> User:
        """更新用户。actor 为操作者：非管理员仅可编辑自身资料，且不能改角色/启停/部门。"""
        user = await self.users.get_by_id(user_id)
        if not user:
            raise NotFoundError("用户不存在")
        is_admin = actor.role.name == "admin"
        if not is_admin and actor.id != user_id:
            raise ForbiddenError("只能修改自己或需要管理员权限")
        if not is_admin:
            # 普通用户自助修改：剥夺提权字段，防止越权改角色或自行启用
            data = data.model_copy(update={"role_id": None, "is_active": None, "department_id": None})
        if data.username and data.username != user.username:
            if await self.users.exists_username(data.username, exclude_id=user_id):
                raise ConflictError("用户名已存在")
            user.username = data.username
        if data.email is not None:
            user.email = data.email
        if data.full_name is not None:
            user.full_name = data.full_name
        if data.role_id is not None:
            if not await self.roles.get_by_id(data.role_id):
                raise ValidationError("角色不存在")
            user.role_id = data.role_id
        if data.department_id is not None:
            if data.department_id and not await _department_exists(self.session, data.department_id):
                raise ValidationError("部门不存在")
            user.department_id = data.department_id
        if data.is_active is not None:
            user.is_active = data.is_active
        if data.password:
            user.hashed_password = security.hash_password(data.password)
        await self.session.commit()
        await self.session.refresh(user)
        # 角色可能已被改：强制按关系重新取回，避免响应拿到旧 role_name 或惰性加载崩溃
        return (await self.users.get_with_relations(user_id)) or user

    async def list(self, skip: int = 0, limit: int = 50, q: str | None = None) -> list[User]:
        return await self.users.list(skip, limit, q)

    async def get(self, user_id: int) -> User:
        user = await self.users.get_by_id(user_id)
        if not user:
            raise NotFoundError("用户不存在")
        return user


async def _department_exists(session: AsyncSession, dept_id: int) -> bool:
    repo = DepartmentRepository(session)
    return (await repo.get_by_id(dept_id)) is not None


class DepartmentService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.depts = DepartmentRepository(session)

    async def create(self, data: DepartmentCreate) -> Department:
        if await self.depts.exists_name(data.name):
            raise ConflictError("部门名称已存在")
        if data.parent_id and not await self.depts.get_by_id(data.parent_id):
            raise ValidationError("上级部门不存在")
        dept = Department(name=data.name, parent_id=data.parent_id, manager_id=data.manager_id)
        return await self.depts.create(dept)

    async def update(self, dept_id: int, data: DepartmentUpdate) -> Department:
        dept = await self.depts.get_by_id(dept_id)
        if not dept:
            raise NotFoundError("部门不存在")
        if data.name and data.name != dept.name and await self.depts.exists_name(data.name, exclude_id=dept_id):
            raise ConflictError("部门名称已存在")
        if data.name is not None:
            dept.name = data.name
        if data.parent_id is not None:
            dept.parent_id = data.parent_id
        if data.manager_id is not None:
            dept.manager_id = data.manager_id
        await self.session.commit()
        await self.session.refresh(dept)
        return dept

    async def list(self) -> list[Department]:
        return await self.depts.list()


# ---------- 组织权限中心：角色 CRUD ----------
class RoleService:
    """角色增删改查：删除带护栏（admin 不可删、名下仍有用户不可删），权限点编排交给 PermissionService。"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.roles = RoleRepository(session)
        self.users = UserRepository(session)

    async def list(self) -> list[Role]:
        return await self.roles.list()

    async def create(self, data: RoleCreate) -> Role:
        if await self.roles.get_by_name(data.name):
            raise ConflictError("角色名已存在")
        role = Role(name=data.name, description=data.description, data_scope=data.data_scope)
        return await self.roles.create(role)

    async def update(self, role_id: int, data: RoleUpdate) -> Role:
        role = await self.roles.get_by_id(role_id)
        if not role:
            raise NotFoundError("角色不存在")
        if data.description is not None:
            role.description = data.description
        if data.data_scope is not None:
            role.data_scope = data.data_scope
        await self.session.commit()
        await self.session.refresh(role)
        return role

    async def delete(self, role_id: int) -> None:
        role = await self.roles.get_by_id(role_id)
        if not role:
            raise NotFoundError("角色不存在")
        if role.name == "admin":
            raise ForbiddenError("内置管理员角色不可删除")
        if await self.roles.count_users(role_id) > 0:
            raise ConflictError("该角色下仍有用户，无法删除")
        await self.roles.delete(role)


# ---------- 内容门户：角色化工作台 ----------
class PortalService:
    """门户工作台聚合：按角色组装统计与四类挂件，复用各仓储避免重复查询与 N+1。"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.users = UserRepository(session)
        self.depts = DepartmentRepository(session)
        self.leaves = LeaveRepository(session)
        self.anns = AnnouncementRepository(session)
        self.wf = WorkflowRepository(session)

    async def overview(self, user: User) -> dict:
        is_admin = user.role.name == "admin"
        is_manager = user.role.name in ("admin", "manager")

        pending = await self.wf.pending_with_instance(user.id, 5)
        pending_tasks = [
            {
                "task_id": t.id,
                "instance_id": t.instance_id,
                "instance_code": t.instance.code,
                "instance_title": t.instance.title,
                "node_name": t.node_name,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in pending
        ]
        running = await self.wf.running_for_user(user.id, 5)
        my_instances = [
            {
                "id": i.id,
                "code": i.code,
                "title": i.title,
                "status": i.status,
                "started_at": i.started_at.isoformat() if i.started_at else None,
            }
            for i in running
        ]
        my_leave = await self.leaves.list(user_id=user.id, limit=5)
        recent_leave = [
            {
                "id": lv.id,
                "leave_type": lv.leave_type,
                "status": lv.status,
                "start_date": lv.start_date.isoformat() if lv.start_date else None,
                "end_date": lv.end_date.isoformat() if lv.end_date else None,
            }
            for lv in my_leave
        ]
        announcements = await self.anns.list(published_only=True, limit=5)
        announcements_out = [
            {
                "id": a.id,
                "title": a.title,
                "pinned": a.pinned,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in announcements
        ]

        employees = await self.users.count()
        departments = await self.depts.count()
        leave_org = await self.leaves.count()
        leave_mine = await self.leaves.count(user_id=user.id)
        anns_total = len(announcements)
        defs_total = len(await self.wf.list_definitions())
        pending_org = await self.wf.count_pending()

        if is_manager:
            stats = {
                "员工总数": employees,
                "部门总数": departments,
                "请假单": leave_org,
                "公告": anns_total,
                "流程定义": defs_total,
                "待办(全公司)": pending_org,
            }
        else:
            stats = {
                "待我审批": len(pending_tasks),
                "在途流程": len(my_instances),
                "我的请假": leave_mine,
                "公告": anns_total,
            }

        return {
            "role": user.role.name,
            "is_admin": is_admin,
            "stats": stats,
            "pending_tasks": pending_tasks,
            "my_instances_running": my_instances,
            "recent_leave": recent_leave,
            "announcements": announcements_out,
        }


# ---------- 运维中心（P3 建模运维） ----------
class OpsService:
    """运维中心：管理员视角的系统级运行概览。

    聚合各仓储的计数/分组查询，单次分组统计避免 N+1；发起人姓名由 list_all 一次性映射。
    路由层已用 require_roles("admin") 把关，这里再做一次防御性校验。
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.users = UserRepository(session)
        self.depts = DepartmentRepository(session)
        self.roles = RoleRepository(session)
        self.perms = PermissionRepository(session)
        self.menus = MenuRepository(session)
        self.leaves = LeaveRepository(session)
        self.anns = AnnouncementRepository(session)
        self.docs = DocumentRepository(session)
        self.wf = WorkflowRepository(session)

    async def overview(self, actor: User) -> OpsOverviewOut:
        if actor.role.name != "admin":
            raise ForbiddenError("运维中心仅管理员可见")

        users = await self.users.list_all()
        name_of = {u.id: (u.full_name or u.username) for u in users}

        counts = {
            "用户": await self.users.count(),
            "部门": await self.depts.count(),
            "角色": await self.roles.count(),
            "权限点": await self.perms.count(),
            "菜单": await self.menus.count(),
            "请假单": await self.leaves.count(),
            "公告": await self.anns.count(),
            "文档": await self.docs.count(),
            "流程定义": len(await self.wf.list_definitions()),
            "流程实例": sum((await self.wf.count_instances_by_status()).values()),
        }

        instances_by_status = await self.wf.count_instances_by_status()
        users_by_role = await self.users.count_by_role()

        recent = await self.wf.recent_instances(10)
        recent_instances = [
            {
                "id": i.id,
                "code": i.code,
                "title": i.title,
                "status": i.status,
                "started_at": i.started_at.isoformat() if i.started_at else None,
                "initiator": name_of.get(i.initiator_id, f"#{i.initiator_id}"),
            }
            for i in recent
        ]

        try:
            db_backend = engine.dialect.name
        except Exception:
            db_backend = "unknown"

        return OpsOverviewOut(
            generated_at=_now(),
            db_backend=db_backend,
            counts=counts,
            instances_by_status=instances_by_status,
            users_by_role=users_by_role,
            recent_instances=recent_instances,
        )


# ---------- 组织权限中心：权限 / 菜单 ----------
class PermissionService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = PermissionRepository(session)
        self.roles = RoleRepository(session)

    async def list(self, category: str | None = None, ptype: str | None = None) -> list[Permission]:
        return await self.repo.list(category, ptype)

    async def create(self, data: "PermissionCreate") -> Permission:
        if await self.repo.exists_code(data.code):
            raise ConflictError("权限编码已存在")
        perm = Permission(
            code=data.code, name=data.name, category=data.category,
            type=data.type, description=data.description,
        )
        return await self.repo.create(perm)

    async def get(self, perm_id: int) -> Permission:
        perm = await self.repo.get_by_id(perm_id)
        if not perm:
            raise NotFoundError("权限不存在")
        return perm

    async def list_role_permissions(self, role_id: int) -> list[Permission]:
        if not await self.roles.get_by_id(role_id):
            raise ValidationError("角色不存在")
        return await self.repo.list_for_role(role_id)

    async def role_permission_codes(self, role_id: int) -> list[str]:
        return await self.repo.codes_for_role(role_id)

    async def assign(self, role_id: int, perm_id: int) -> None:
        if not await self.roles.get_by_id(role_id):
            raise ValidationError("角色不存在")
        if not await self.repo.get_by_id(perm_id):
            raise ValidationError("权限不存在")
        await self.repo.assign(role_id, perm_id)

    async def revoke(self, role_id: int, perm_id: int) -> None:
        if not await self.roles.get_by_id(role_id):
            raise ValidationError("角色不存在")
        await self.repo.revoke(role_id, perm_id)


class MenuService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = MenuRepository(session)

    def _serialize(self, m: Menu) -> dict:
        return {
            "id": m.id,
            "parent_id": m.parent_id,
            "name": m.name,
            "path": m.path,
            "icon": m.icon,
            "order": m.order,
            "permission_code": m.permission_code,
        }

    async def list_all(self) -> list[dict]:
        return [self._serialize(m) for m in await self.repo.list()]

    async def list_visible(self, codes: list[str]) -> list[dict]:
        """按权限码过滤菜单；命中权限的节点会连带其祖先一并返回（保证父级分组可见）。"""
        all_menus = await self.repo.list()
        if "*" in codes:
            allowed = {m.id for m in all_menus}
        else:
            allowed = {
                m.id for m in all_menus
                if not m.permission_code or m.permission_code in codes
            }
        by_id = {m.id: m for m in all_menus}

        def add_ancestors(mid: int) -> None:
            m = by_id.get(mid)
            if m and m.parent_id is not None and m.parent_id not in allowed:
                allowed.add(m.parent_id)
                add_ancestors(m.parent_id)

        for mid in list(allowed):
            add_ancestors(mid)
        return [self._serialize(m) for m in all_menus if m.id in allowed]

    async def create(self, data: "MenuCreate") -> Menu:
        if data.path and await self.repo.exists_path(data.path):
            raise ConflictError("菜单路径已存在")
        if data.parent_id is not None and not await self.repo.get_by_id(data.parent_id):
            raise ValidationError("上级菜单不存在")
        menu = Menu(
            parent_id=data.parent_id, name=data.name, path=data.path,
            icon=data.icon, order=data.order, permission_code=data.permission_code,
        )
        return await self.repo.create(menu)

    async def update(self, menu_id: int, data: "MenuUpdate") -> Menu:
        menu = await self.repo.get_by_id(menu_id)
        if not menu:
            raise NotFoundError("菜单不存在")
        if data.path is not None and data.path != menu.path:
            if await self.repo.exists_path(data.path, exclude_id=menu_id):
                raise ConflictError("菜单路径已存在")
            menu.path = data.path
        if data.parent_id is not None:
            if data.parent_id == menu.id:
                raise ValidationError("不能将菜单挂到自身")
            menu.parent_id = data.parent_id
        if data.name is not None:
            menu.name = data.name
        if data.icon is not None:
            menu.icon = data.icon
        if data.order is not None:
            menu.order = data.order
        if data.permission_code is not None:
            menu.permission_code = data.permission_code
        return await self.repo.update(menu)


# ---------- 考勤 / 请假 ----------
class LeaveService:
    def __init__(self, session: AsyncSession, *, event_bus: "EventBus | None" = None):
        self.session = session
        self.leaves = LeaveRepository(session)
        self.bus = event_bus

    async def create(self, user_id: int, data: LeaveCreate) -> LeaveRequest:
        if data.end_date < data.start_date:
            raise ValidationError("结束日期不能早于开始日期")
        leave = LeaveRequest(
            user_id=user_id,
            leave_type=data.leave_type,
            start_date=data.start_date,
            end_date=data.end_date,
            reason=data.reason,
        )
        leave = await self.leaves.create(leave)
        # 请假提交即产生待办：通知审批人（管理员 + 经理）
        approvers = await UserRepository(self.session).list_ids_by_roles(["admin", "manager"])
        if approvers:
            owner = await UserRepository(self.session).get_by_id(user_id)
            who = (owner.full_name or owner.username) if owner else f"用户#{user_id}"
            await NotificationService(self.session, event_bus=self.bus).notify_many(
                approvers, "leave", "待审批的请假申请",
                f"{who} 提交了请假申请（{leave.leave_type}），请审批。", "/leave",
            )
        return leave

    async def list(
        self, user_id: int | None = None, department_id: int | None = None
    ) -> list[LeaveRequest]:
        return await self.leaves.list(user_id, department_id)

    async def review(self, leave_id: int, reviewer: User, data: LeaveReview) -> LeaveRequest:
        leave = await self.leaves.get(leave_id)
        if not leave:
            raise NotFoundError("请假单不存在")
        if leave.status != "pending":
            raise ValidationError("该请假单已处理")
        leave.status = "approved" if data.approve else "rejected"
        leave.approver_id = reviewer.id
        leave.reviewed_at = _now()
        if not data.approve:
            leave.rejection_reason = data.rejection_reason or "未通过"
        await self.session.commit()
        await self.session.refresh(leave)
        return leave


# ---------- 公告 / 文档 ----------
class AnnouncementService:
    def __init__(self, session: AsyncSession, *, event_bus: "EventBus | None" = None):
        self.session = session
        self.anns = AnnouncementRepository(session)
        self.bus = event_bus

    async def create(self, author_id: int, data: AnnouncementCreate) -> Announcement:
        ann = Announcement(
            title=data.title,
            content=data.content,
            author_id=author_id,
            pinned=data.pinned,
            published=data.published,
            attachments=data.attachments or [],
            expires_at=data.expires_at,
        )
        ann = await self.anns.create(ann)
        # 发布公告：广播通知全员
        if ann.published:
            await self._notify_published(ann)
        return ann

    async def list(self, published_only: bool = False) -> list[Announcement]:
        return await self.anns.list(published_only)

    async def update(self, ann_id: int, data: AnnouncementUpdate) -> Announcement:
        ann = await self.anns.get(ann_id)
        if not ann:
            raise NotFoundError("公告不存在")
        was_published = ann.published
        if data.title is not None:
            ann.title = data.title
        if data.content is not None:
            ann.content = data.content
        if data.pinned is not None:
            ann.pinned = data.pinned
        if data.published is not None:
            ann.published = data.published
        if data.attachments is not None:
            ann.attachments = data.attachments
        if data.expires_at is not None:
            ann.expires_at = data.expires_at
        await self.session.commit()
        await self.session.refresh(ann)
        # 由未发布变更为已发布：广播通知全员
        if data.published is True and not was_published:
            await self._notify_published(ann)
        return ann

    async def mark_read(self, ann_id: int, user_id: int) -> dict:
        """标记已读（幂等），并同步公告上的阅读人数快照。"""
        ann = await self.anns.get(ann_id)
        if not ann:
            raise NotFoundError("公告不存在")
        created = await AnnouncementReadRepository(self.session).mark_read(ann_id, user_id)
        if created:
            ann.read_count = (ann.read_count or 0) + 1
            await self.session.commit()
            await self.session.refresh(ann)
        return {"announcement_id": ann_id, "read": True, "read_count": ann.read_count or 0}

    async def readers(self, ann_id: int) -> dict:
        """公告阅读明细（作者/管理员可见）：谁看过、多少人看过。"""
        repo = AnnouncementReadRepository(self.session)
        if not await self.anns.get(ann_id):
            raise NotFoundError("公告不存在")
        rows = await repo.list_readers(ann_id)
        return {
            "announcement_id": ann_id,
            "read_count": len(rows),
            "total_users": await repo.count_users(),
            "readers": [
                {"user_id": rec.user_id, "user_name": name, "read_at": rec.read_at}
                for rec, name in rows
            ],
        }

    async def _notify_published(self, ann: Announcement) -> None:
        ids = await UserRepository(self.session).list_ids()
        if ids:
            await NotificationService(self.session, event_bus=self.bus).notify_many(
                ids, "announcement", f"新公告：{ann.title}",
                "点击查看公告详情。", "/announcements",
            )
        # 实时：广播公告发布（前端据此弹提示并刷新公告列表）
        if self.bus is not None:
            try:
                await self.bus.publish(RealtimeEvent(
                    type=EventType.ANNOUNCEMENT_PUBLISHED.value,
                    payload={"id": ann.id, "title": ann.title},
                ))
            except Exception:  # noqa: BLE001
                logger.warning("realtime_emit_failed", type="announcement.published")


# ---------- 内容引擎：文档中心 + 文件上传 ----------
# 允许上传的扩展名白名单（防止可执行文件/非常规类型进入系统）
ALLOWED_EXTENSIONS = {
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
    "png", "jpg", "jpeg", "gif", "txt", "zip", "csv", "md",
}


class DocumentService:
    """文档中心：上传落盘 + 元数据管理。

    安全要点：文件以 {id}.{ext} 落盘（ext 取自受约束白名单，绝不用客户端原始文件名拼路径，
    杜绝路径穿越）；file_url 仅存逻辑下载地址，由鉴权端点流式返回；单文件大小受 max_upload_size 限制。
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = DocumentRepository(session)
        self.settings = get_settings()
        self.storage = get_storage()

    @staticmethod
    def _safe_ext(filename: str) -> str | None:
        """从文件名提取受约束的扩展名；非法字符 / 非白名单类型返回 None。"""
        if not filename or "\x00" in filename:
            return None
        base = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        if "." not in base:
            return None
        ext = base.rsplit(".", 1)[-1].lower()
        return ext if ext in ALLOWED_EXTENSIONS else None

    async def upload_and_create(
        self, user: User, title: str, category: str, description: str, file
    ) -> Document:
        # 1) 扩展名白名单 + 大小校验
        data, size, ext = await self._prepare_file(file)

        # 2) 先建元数据行并 flush 取 id，再以 {id}.{ext} 写入存储，保证一对一、可回滚
        doc = Document(
            title=title,
            category=category,
            file_type=ext,
            file_size=size,
            description=description,
            file_url="",
            owner_id=user.id,
            owner_name=user.full_name or user.username,
        )
        self.session.add(doc)
        await self.session.flush()

        rel_name = f"{doc.id}.{ext}"
        try:
            await self.storage.save(rel_name, data, content_type=file.content_type)
        except (ValidationError, NotFoundError):
            await self.session.rollback()
            raise
        except Exception as exc:
            await self.session.rollback()
            raise ValidationError(f"文件存储失败：{exc}")

        doc.file_url = f"/api/documents/{doc.id}/file"
        doc.current_version = 1
        doc.current_file_key = rel_name
        self.session.add(
            DocumentVersion(
                document_id=doc.id,
                version=1,
                file_type=ext,
                file_size=size,
                file_key=rel_name,
                note="初始版本",
                uploader_id=user.id,
                uploader_name=user.full_name or user.username,
            )
        )
        await self.session.commit()
        await self.session.refresh(doc)
        return doc

    async def _prepare_file(self, file) -> tuple[bytes, int, str]:
        """上传通用校验：扩展名白名单 + 单文件上限 + 非空。"""
        ext = self._safe_ext(file.filename or "")
        if not ext:
            raise ValidationError("不支持的文件类型")
        data = await file.read()
        size = getattr(file, "size", None)
        if size is None:
            size = len(data)
        max_mb = self.settings.max_upload_size // 1024 // 1024
        if size > self.settings.max_upload_size:
            raise ValidationError(f"文件过大，单文件上限 {max_mb}MB")
        if size == 0:
            raise ValidationError("文件内容为空")
        return data, size, ext

    async def list_documents(
        self, category: str | None = None, q: str | None = None,
        offset: int = 0, limit: int = 50,
    ) -> dict:
        items = await self.repo.list(category, q, offset, limit)
        total = await self.repo.count(category, q)
        return {
            "items": [DocumentOut.model_validate(i) for i in items],
            "total": total,
            "offset": offset,
            "limit": limit,
        }

    async def update(self, doc_id: int, data: "DocumentUpdate") -> Document:
        doc = await self.repo.get(doc_id)
        if not doc:
            raise NotFoundError("文档不存在")
        if data.title is not None:
            doc.title = data.title
        if data.category is not None:
            doc.category = data.category
        if data.description is not None:
            doc.description = data.description
        await self.session.commit()
        await self.session.refresh(doc)
        return doc

    async def get_file(self, doc_id: int) -> tuple[str | None, str | None, str]:
        """返回 (本地磁盘路径 或 None, 签名URL 或 None, 下载文件名)；二选一。"""
        doc = await self.repo.get(doc_id)
        if not doc or not doc.file_type:
            raise NotFoundError("该文档无可下载文件")
        # 当前版本存储 key；老数据没有 key 时回落 {id}.{ext} 历史格式
        key = doc.current_file_key or f"{doc.id}.{doc.file_type}"
        download_name = f"{doc.title}.{doc.file_type}"
        local_path, signed_url = await self.storage.get_download(key, download_name)
        return local_path, signed_url, download_name

    # ---- 版本历史 ----
    async def list_versions(self, doc_id: int) -> list[DocumentVersion]:
        if not await self.repo.get(doc_id):
            raise NotFoundError("文档不存在")
        return await DocumentVersionRepository(self.session).list_by_doc(doc_id)

    async def add_version(self, doc_id: int, user: User, file, note: str = "") -> DocumentVersion:
        """上传新文件作为新版本：旧版本文件保留，可回溯下载。"""
        doc = await self.repo.get(doc_id)
        if not doc:
            raise NotFoundError("文档不存在")
        data, size, ext = await self._prepare_file(file)
        version = await DocumentVersionRepository(self.session).max_version(doc_id) + 1
        key = f"{doc_id}_v{version}.{ext}"
        try:
            await self.storage.save(key, data, content_type=file.content_type)
        except (ValidationError, NotFoundError):
            await self.session.rollback()
            raise
        except Exception as exc:
            await self.session.rollback()
            raise ValidationError(f"文件存储失败：{exc}")

        item = DocumentVersion(
            document_id=doc_id,
            version=version,
            file_type=ext,
            file_size=size,
            file_key=key,
            note=note or "",
            uploader_id=user.id,
            uploader_name=user.full_name or user.username,
        )
        self.session.add(item)
        doc.current_version = version
        doc.current_file_key = key
        doc.file_type = ext
        doc.file_size = size
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def get_version_file(self, doc_id: int, version_id: int) -> tuple[str | None, str | None, str]:
        """下载指定历史版本。"""
        doc = await self.repo.get(doc_id)
        if not doc:
            raise NotFoundError("文档不存在")
        ver = await DocumentVersionRepository(self.session).get(version_id)
        if not ver or ver.document_id != doc_id:
            raise NotFoundError("版本不存在")
        key = ver.file_key or (f"{doc.id}.{ver.file_type or doc.file_type}" if ver.version <= 1 else "")
        if not key:
            raise NotFoundError("该版本文件缺失")
        name = f"{doc.title}_v{ver.version}.{ver.file_type or doc.file_type}"
        local_path, signed_url = await self.storage.get_download(key, name)
        return local_path, signed_url, name

    async def delete(self, doc_id: int) -> None:
        doc = await self.repo.get(doc_id)
        if not doc:
            raise NotFoundError("文档不存在")
        # 先删对象（best-effort，失败仅告警，不阻断元数据删除）
        if doc.file_type:
            key = f"{doc.id}.{doc.file_type}"
            try:
                await self.storage.delete(key)
            except Exception:
                logger.warning("doc_file_remove_failed", doc_id=doc_id)
        await self.repo.delete(doc)


# ---------- 消息中心：通知收件箱 ----------
class NotificationService:
    """通知的读写与创建。

    - add：仅落库不提交，供工作流等已在事务内的调用方打包提交（不发射事件，
      由调用方在其自身事件里一并表达，避免重复提醒）。
    - notify / notify_many：落库并立即提交，提交后发射 notification.created，
      供前端实时刷新未读角标与消息列表。
    - 用户仅能操作自己的通知（repo 层按 user_id 过滤）；权限在路由层用 msg:view 把关。
    """

    def __init__(self, session: AsyncSession, *, event_bus: "EventBus | None" = None):
        self.session = session
        self.repo = NotificationRepository(session)
        self.bus = event_bus

    async def _emit(self, etype: "EventType | str", payload: dict, user_ids: "list[int] | None" = None) -> None:
        """发布实时事件；bus 为空时静默跳过，失败只告警不影响主流程。"""
        if self.bus is None:
            return
        try:
            await self.bus.publish(RealtimeEvent(
                type=etype.value if isinstance(etype, EventType) else etype,
                payload=payload,
                user_ids=user_ids,
            ))
        except Exception:  # noqa: BLE001
            logger.warning("realtime_emit_failed", type=str(etype))

    async def list_for_user(
        self, user_id: int, only_unread: bool = False, limit: int = 50, offset: int = 0
    ) -> dict:
        items = await self.repo.list_for_user(user_id, only_unread, limit, offset)
        total = await self.repo.count_for_user(user_id)
        unread = await self.repo.count_for_user(user_id, only_unread=True)
        return {
            "items": [NotificationOut.model_validate(i) for i in items],
            "total": total,
            "unread": unread,
            "limit": limit,
            "offset": offset,
        }

    async def mark_read(self, nid: int, user_id: int) -> None:
        obj = await self.repo.get_owned(nid, user_id)
        if not obj:
            raise NotFoundError("通知不存在")
        await self.repo.mark_read(nid, user_id)

    async def mark_all_read(self, user_id: int) -> int:
        return await self.repo.mark_all_read(user_id)

    async def add(
        self, user_id: int, ntype: str, title: str, body: str, link: str = ""
    ) -> Notification:
        """仅落库（不提交），交由调用方事务统一提交。"""
        n = Notification(user_id=user_id, type=ntype, title=title, body=body, link=link)
        self.session.add(n)
        return n

    async def notify(
        self, user_id: int, ntype: str, title: str, body: str, link: str = ""
    ) -> None:
        self.session.add(
            Notification(user_id=user_id, type=ntype, title=title, body=body, link=link)
        )
        await self.session.commit()
        # 实时：通知目标用户刷新未读角标（由前端决定是否弹提示）
        await self._emit(
            EventType.NOTIFICATION_CREATED,
            {"type": ntype, "title": title, "link": link},
            user_ids=[user_id],
        )

    async def notify_many(
        self, user_ids: list[int], ntype: str, title: str, body: str, link: str = ""
    ) -> int:
        if not user_ids:
            return 0
        for uid in user_ids:
            self.session.add(
                Notification(user_id=uid, type=ntype, title=title, body=body, link=link)
            )
        await self.session.commit()
        await self._emit(
            EventType.NOTIFICATION_CREATED,
            {"type": ntype, "title": title, "link": link},
            user_ids=list(user_ids),
        )
        return len(user_ids)


# ---------- 审批工作流（图结构引擎） ----------
from app.models import (  # noqa: E402
    FormDefinition,
    WorkflowNodeLog,
    WorkflowVersion,
)
from app.workflow_engine import advance, countersign_result  # noqa: E402
from app.schemas import (  # noqa: E402
    FormDefinitionCreate,
    WorkflowAddSign,
    WorkflowTransfer,
    WorkflowUrge,
    WorkflowVersionSave,
)


class WorkflowService:
    """流程服务：编排引擎与持久化，业务规则集中在此，控制器不写逻辑。"""

    def __init__(
        self,
        session: AsyncSession,
        *,
        workflow_repo: "WorkflowRepository | None" = None,
        user_repo: "UserRepository | None" = None,
        notification_service: "NotificationService | None" = None,
        scheduler_repo: "SchedulerRepository | None" = None,
        event_bus: "EventBus | None" = None,
    ):
        # 依赖注入点：默认回退到按 session 现接的仓储/服务；测试可注入 Fake 以隔离数据库。
        self.session = session
        self.repo = workflow_repo or WorkflowRepository(session)
        self.users = user_repo or UserRepository(session)
        self.notifications = notification_service or NotificationService(session, event_bus=event_bus)
        self.scheduler = scheduler_repo or SchedulerRepository(session)
        # 实时事件总线：未注入则关闭实时推送（单测/离线场景安全无副作用）
        self.bus = event_bus

    async def _emit(self, etype: "EventType | str", payload: dict, user_ids: "list[int] | None" = None) -> None:
        """发布实时事件；bus 为空时静默跳过。发布失败只告警不影响主流程。"""
        if self.bus is None:
            return
        try:
            await self.bus.publish(RealtimeEvent(
                type=etype.value if isinstance(etype, EventType) else etype,
                payload=payload,
                user_ids=user_ids,
            ))
        except Exception:  # noqa: BLE001
            logger.warning("realtime_emit_failed", type=str(etype))

    # ---- 表单定义 ----
    async def create_form(self, data: FormDefinitionCreate) -> FormDefinition:
        form = FormDefinition(code=data.code, name=data.name, fields=data.fields)
        self.session.add(form)
        await self.session.commit()
        await self.session.refresh(form)
        return form

    async def list_forms(self) -> list[FormDefinition]:
        return await self.repo.list_forms()

    # ---- 流程定义 ----
    async def create_definition(self, data) -> WorkflowDefinition:
        res = await self.session.execute(
            select(WorkflowDefinition).where(WorkflowDefinition.code == data.code)
        )
        if res.scalar_one_or_none():
            raise ConflictError("流程编码已存在")
        wf = WorkflowDefinition(
            code=data.code,
            name=data.name,
            category=getattr(data, "category", "general"),
            description=getattr(data, "description", ""),
            icon=getattr(data, "icon", ""),
        )
        return await self.repo.create_definition(wf)

    async def list_definitions(self, status: str | None = None) -> list[WorkflowDefinition]:
        return await self.repo.list_definitions(status)

    async def get_definition(self, def_id: int) -> WorkflowDefinition:
        wf = await self.repo.get_definition(def_id)
        if not wf:
            raise NotFoundError("流程定义不存在")
        return wf

    async def set_definition_status(self, def_id: int, status: str) -> WorkflowDefinition:
        """published 可发起；locked 禁止发起但在途实例继续流转（对齐泛微流程锁定）。"""
        if status not in ("draft", "published", "locked"):
            raise ValidationError("状态不合法")
        wf = await self.get_definition(def_id)
        wf.status = status
        await self.session.commit()
        await self.session.refresh(wf)
        return wf

    # ---- 版本 ----
    async def save_version(self, def_id: int, data: WorkflowVersionSave) -> WorkflowVersion:
        await self.get_definition(def_id)
        versions = await self.repo.list_versions(def_id)
        nxt = (versions[0].version + 1) if versions else 1
        ver = WorkflowVersion(
            definition_id=def_id,
            version=nxt,
            graph=data.graph,
            form_id=data.form_id,
            status="draft",
            remark=data.remark,
        )
        return await self.repo.create_version(ver)

    async def publish_version(self, version_id: int) -> WorkflowVersion:
        ver = await self.repo.get_version(version_id)
        if not ver:
            raise NotFoundError("版本不存在")
        if not (ver.graph or {}).get("nodes"):
            raise ValidationError("流程图为空，无法发布")
        # 同流程其它已发布版本归档，保证只有一个生效版本
        for v in await self.repo.list_versions(ver.definition_id):
            if v.status == "published":
                v.status = "archived"
        ver.status = "published"
        ver.published_at = _now()
        definition = await self.repo.get_definition(ver.definition_id)
        definition.current_version = ver.version
        definition.status = "published"
        await self.session.commit()
        await self.session.refresh(ver)
        return ver

    async def list_versions(self, def_id: int) -> list[WorkflowVersion]:
        return await self.repo.list_versions(def_id)

    # ---- 发起 ----
    async def start_instance(self, initiator_id: int, data) -> WorkflowInstance:
        definition = await self.get_definition(data.definition_id)
        if definition.status != "published":
            raise ValidationError("流程未发布或已锁定，无法发起")
        version = await self.repo.get_published_version(definition.id)
        if not version:
            raise ValidationError("流程没有已发布版本")
        graph = version.graph or {}
        instance = WorkflowInstance(
            code="",
            definition_id=definition.id,
            version_id=version.id,
            title=data.title,
            initiator_id=initiator_id,
            form_data=getattr(data, "form_data", {}) or {},
            current_nodes=[],
            status="running",
        )
        self.session.add(instance)
        await self.session.flush()
        instance.code = f"WF{_now().strftime('%Y%m%d')}{instance.id:05d}"

        await self.repo.add_log(
            WorkflowNodeLog(
                instance_id=instance.id, node_id="start", node_name="发起",
                action="enter", operator_id=initiator_id, comment="流程发起",
            )
        )
        to_activate, passed = advance(graph, "start", instance.form_data, set(), {"start"})
        await self._log_passed(instance, graph, passed)
        _, assigned = await self._activate(instance, graph, to_activate)
        await self.session.commit()
        await self._refresh_with_tasks(instance)
        # 实时：给首批待办处理人推送待办提醒
        for uid in assigned:
            await self._emit(
                EventType.WORKFLOW_TASK_ASSIGNED,
                {"instance_id": instance.id, "code": instance.code, "title": instance.title,
                 "node": "", "initiator_id": initiator_id},
                user_ids=[uid],
            )
        return instance

    # ---- 审批动作 ----
    async def decide_task(self, task_id: int, user: User, data) -> WorkflowInstance:
        task = await self.repo.get_task(task_id)
        if not task:
            raise NotFoundError("任务不存在")
        instance = task.instance
        if instance.status != "running":
            raise ValidationError("该审批已结束")
        if task.status != "pending":
            raise ValidationError("任务已处理")
        if task.approver_id != user.id and user.role.name != "admin":
            raise ForbiddenError("该任务不由您处理")

        version = await self.repo.get_version(instance.version_id)
        graph = (version.graph if version else {}) or {}
        nodes = {n["id"]: n for n in graph.get("nodes", [])}
        node = nodes.get(task.node_id, {})

        approve = bool(getattr(data, "approve", False))
        task.status = "approved" if approve else "rejected"
        task.comment = getattr(data, "comment", "") or ""
        task.decided_at = _now()
        await self.repo.add_log(
            WorkflowNodeLog(
                instance_id=instance.id, node_id=task.node_id, node_name=task.node_name,
                action="approve" if approve else "reject",
                operator_id=user.id, comment=task.comment,
            )
        )

        node_tasks = await self.repo.list_tasks(instance.id, task.node_id)
        statuses = [t.status for t in node_tasks if t.node_type != "notify"]
        if task.node_type == "countersign":
            result = countersign_result(
                statuses, node.get("strategy", "all"), node.get("ratio")
            )
        else:
            result = "approved" if approve else "rejected"

        if result is None:
            # 会签尚未形成结论，继续等待其余审批人
            await self.session.commit()
            await self._refresh_with_tasks(instance)
            # 实时：通知发起人已有审批人通过（仍等待其他人）
            await self._emit(
                EventType.WORKFLOW_DECISION,
                {"instance_id": instance.id, "code": instance.code, "title": instance.title,
                 "node": task.node_name, "action": "approve" if approve else "reject",
                 "operator_id": user.id, "pending": True},
                user_ids=[instance.initiator_id],
            )
            return instance

        if result == "rejected":
            for t in node_tasks:
                if t.status == "pending":
                    t.status = "canceled"
            await self.repo.add_log(
                WorkflowNodeLog(
                    instance_id=instance.id, node_id=task.node_id,
                    node_name=task.node_name, action="finish",
                    operator_id=user.id, comment="节点驳回",
                )
            )
            await self._finish_instance(instance, "rejected")
            await self.session.commit()
            await self._refresh_with_tasks(instance)
            # 实时：通知发起人流程被驳回
            await self._emit(
                EventType.WORKFLOW_STATUS,
                {"instance_id": instance.id, "code": instance.code, "title": instance.title,
                 "status": "rejected", "node": task.node_name},
                user_ids=[instance.initiator_id],
            )
            return instance

        await self.repo.add_log(
            WorkflowNodeLog(
                instance_id=instance.id, node_id=task.node_id,
                node_name=task.node_name, action="finish",
                operator_id=user.id, comment="节点通过",
            )
        )
        finished, activated = await self._node_sets(instance)
        to_activate, passed = advance(
            graph, task.node_id, instance.form_data, finished, activated
        )
        await self._log_passed(instance, graph, passed)
        _, assigned = await self._activate(instance, graph, to_activate)
        await self.session.commit()
        await self._refresh_with_tasks(instance)
        # 实时：新节点待办推送 + 发起人状态推进
        for uid in assigned:
            await self._emit(
                EventType.WORKFLOW_TASK_ASSIGNED,
                {"instance_id": instance.id, "code": instance.code, "title": instance.title,
                 "node": task.node_name, "initiator_id": instance.initiator_id},
                user_ids=[uid],
            )
        await self._emit(
            EventType.WORKFLOW_STATUS,
            {"instance_id": instance.id, "code": instance.code, "title": instance.title,
             "status": instance.status, "node": task.node_name,
             "action": "approve" if approve else "reject", "operator_id": user.id},
            user_ids=[instance.initiator_id],
        )
        return instance

    async def transfer_task(self, task_id: int, user: User, data: WorkflowTransfer) -> WorkflowInstance:
        """转办：把待办交给他人，原审批人留痕。"""
        task = await self.repo.get_task(task_id)
        if not task:
            raise NotFoundError("任务不存在")
        if task.status != "pending":
            raise ValidationError("任务已处理")
        if task.approver_id != user.id and user.role.name != "admin":
            raise ForbiddenError("该任务不由您处理")
        target = await self.users.get_by_id(data.to_user_id)
        if not target:
            raise NotFoundError("目标用户不存在")
        task.origin_approver_id = task.approver_id or user.id
        task.approver_id = data.to_user_id
        task.comment = data.comment or ""
        await self.repo.add_log(
            WorkflowNodeLog(
                instance_id=task.instance_id, node_id=task.node_id,
                node_name=task.node_name, action="transfer",
                operator_id=user.id, comment=f"转办给 {target.username}",
            )
        )
        await self.session.commit()
        # 实时：新审批人收到待办，原审批人收到转办通知
        await self._emit(
            EventType.WORKFLOW_TASK_ASSIGNED,
            {"instance_id": task.instance_id, "node": task.node_name,
             "title": task.instance.title if task.instance else "", "transferred": True},
            user_ids=[data.to_user_id],
        )
        return task.instance

    async def addsign(self, instance_id: int, node_id: str, user: User, data: WorkflowAddSign):
        """加签：在当前节点追加审批人，参与会签结论。"""
        instance = await self.repo.get_instance(instance_id)
        if not instance:
            raise NotFoundError("审批实例不存在")
        if instance.status != "running":
            raise ValidationError("该审批已结束")
        if node_id not in (instance.current_nodes or []):
            raise ValidationError("该节点不在当前流转中")
        existing = await self.repo.list_tasks(instance.id, node_id)
        base_seq = max([t.seq for t in existing], default=-1) + 1
        for i, uid in enumerate(data.user_ids):
            if not await self.users.get_by_id(uid):
                raise NotFoundError(f"加签用户 {uid} 不存在")
            self.session.add(
                WorkflowTask(
                    instance_id=instance.id, node_id=node_id,
                    node_name=existing[0].node_name if existing else "",
                    node_type=existing[0].node_type if existing else "countersign",
                    approver_id=uid, mode="addsign", status="pending",
                    seq=(0 if data.before else base_seq) + i,
                )
            )
        await self.repo.add_log(
            WorkflowNodeLog(
                instance_id=instance.id, node_id=node_id,
                node_name=existing[0].node_name if existing else "",
                action="addsign", operator_id=user.id,
                comment=f"加签 {len(data.user_ids)} 人",
            )
        )
        await self.session.commit()
        await self._refresh_with_tasks(instance)
        # 实时：被加签人收到待办
        for uid in data.user_ids:
            await self._emit(
                EventType.WORKFLOW_TASK_ASSIGNED,
                {"instance_id": instance.id, "node": node_id,
                 "title": instance.title, "addsign": True},
                user_ids=[uid],
            )
        return instance

    async def withdraw(self, instance_id: int, user: User) -> WorkflowInstance:
        """撤回：仅发起人本人或管理员可撤回归档自己的在途流程。"""
        instance = await self.repo.get_instance(instance_id)
        if not instance:
            raise NotFoundError("审批实例不存在")
        if instance.initiator_id != user.id and user.role.name != "admin":
            raise ForbiddenError("只能撤回自己发起的流程")
        if instance.status != "running":
            raise ValidationError("流程已结束，无法撤回")
        await self.repo.add_log(
            WorkflowNodeLog(
                instance_id=instance.id, node_id="", node_name="",
                action="withdraw", operator_id=user.id, comment="发起人撤回",
            )
        )
        await self._finish_instance(instance, "canceled")
        await self.session.commit()
        await self._refresh_with_tasks(instance)
        # 实时：通知发起人流程已撤回
        await self._emit(
            EventType.WORKFLOW_STATUS,
            {"instance_id": instance.id, "code": instance.code, "title": instance.title,
             "status": "canceled", "action": "withdraw", "operator_id": user.id},
            user_ids=[instance.initiator_id],
        )
        return instance

    async def urge(self, instance_id: int, user: User, data: WorkflowUrge) -> int:
        """催办：为当前所有待办任务留下提醒记录。"""
        instance = await self.repo.get_instance(instance_id)
        if not instance:
            raise NotFoundError("审批实例不存在")
        if instance.initiator_id != user.id and user.role.name != "admin":
            raise ForbiddenError("只能催办自己发起的流程")
        if instance.status != "running":
            raise ValidationError("流程已结束，无需催办")
        pending = [t for t in await self.repo.list_tasks(instance.id) if t.status == "pending"]
        if not pending:
            raise ValidationError("当前没有待办任务")
        for t in pending:
            await self.repo.add_log(
                WorkflowNodeLog(
                    instance_id=instance.id, node_id=t.node_id,
                    node_name=t.node_name, action="urge", operator_id=user.id,
                    comment=data.comment or "请尽快处理",
                )
            )
        # 实时：提醒当前待办审批人尽快处理
        urged_uids = [t.approver_id for t in pending if t.approver_id]
        if urged_uids:
            await self._emit(
                EventType.WORKFLOW_DECISION,
                {"instance_id": instance.id, "code": instance.code, "title": instance.title,
                 "action": "urge", "operator_id": user.id,
                 "comment": data.comment or "请尽快处理"},
                user_ids=urged_uids,
            )
        return len(pending)

    # ---- 查询 ----
    async def pending_for(self, user: User) -> list[WorkflowTask]:
        return await self.repo.pending_for(user.id)

    async def done_for(self, user: User) -> list[WorkflowTask]:
        return await self.repo.done_for(user.id)

    async def notified_for(self, user: User) -> list[WorkflowTask]:
        return await self.repo.notified_for(user.id)

    async def my_instances(self, user: User) -> list[WorkflowInstance]:
        return await self.repo.list_instances(initiator_id=user.id)

    async def list_instances(
        self, initiator_id: int | None = None, status: str | None = None
    ) -> list[WorkflowInstance]:
        return await self.repo.list_instances(initiator_id, status)

    async def get_instance(self, instance_id: int) -> WorkflowInstance:
        instance = await self.repo.get_instance(instance_id)
        if not instance:
            raise NotFoundError("审批实例不存在")
        return instance

    async def list_logs(self, instance_id: int) -> list[WorkflowNodeLog]:
        return await self.repo.list_logs(instance_id)

    # ---- 监控看板 ----
    async def get_stats(self) -> dict:
        """流程监控看板聚合：定义/实例/任务统计、按定义分布、近 14 天趋势、超时与在途快照。

        超时判定：任务设了 due_at 且已过期，或（未设 due_at 时）按 SLA_DAYS 自创建起算，
        两条规则兼容——当前库尚未回填 due_at，故默认走 SLA 派生，保证看板有真实逾期数据。
        """
        SLA_DAYS = 3
        now = datetime.now(timezone.utc)
        now_naive = now.replace(tzinfo=None)
        sla_cutoff = now_naive - timedelta(days=SLA_DAYS)

        defs = await self.repo.list_definitions()
        instances = await self.repo.list_instances()
        pending_tasks = await self.repo.list_tasks_status("pending")
        delegations = await self.repo.count_active_delegations(now)

        def count_by_status(items, attr: str) -> dict[str, int]:
            out: dict[str, int] = {}
            for it in items:
                s = getattr(it, attr)
                out[s] = out.get(s, 0) + 1
            return out

        definitions_stat = count_by_status(defs, "status")
        instances_stat = count_by_status(instances, "status")
        tasks_stat: dict[str, int] = {"pending": len(pending_tasks)}

        overdue: list = []
        for t in pending_tasks:
            if (t.due_at and t.due_at < now_naive) or (not t.due_at and t.created_at < sla_cutoff):
                overdue.append(t)
        tasks_stat["overdue"] = len(overdue)

        # 按流程定义分布
        def_map = {d.id: d for d in defs}
        by_definition: list[dict] = []
        for d in defs:
            rel = [i for i in instances if i.definition_id == d.id]
            bd = {
                "definition_id": d.id,
                "name": d.name,
                "code": d.code,
                "total": len(rel),
                "running": 0,
                "approved": 0,
                "rejected": 0,
                "canceled": 0,
            }
            for i in rel:
                bd[i.status] = bd.get(i.status, 0) + 1
            by_definition.append(bd)
        by_definition.sort(key=lambda x: x["total"], reverse=True)

        # 近 14 天趋势（按日期聚合，Python 侧完成以避免 SQLite/PG 方言差异）
        trend: list[dict] = []
        for d in range(13, -1, -1):
            day = (now_naive - timedelta(days=d)).date()
            trend.append({"date": day.isoformat(), "started": 0, "finished": 0})
        trend_idx = {t["date"]: t for t in trend}
        for i in instances:
            if i.started_at:
                sd = i.started_at.date().isoformat()
                if sd in trend_idx:
                    trend_idx[sd]["started"] += 1
            if i.finished_at:
                fd = i.finished_at.date().isoformat()
                if fd in trend_idx:
                    trend_idx[fd]["finished"] += 1

        # 在途实例 + 当前节点名（批量取版本与日志，避免 N+1）
        running = [i for i in instances if i.status == "running"]
        version_ids = [i.version_id for i in running]
        versions = {v.id: v for v in await self.repo.get_versions(version_ids)}
        all_logs = await self.repo.list_logs_for_instances([i.id for i in running])
        logs_by_inst: dict[int, list] = {}
        for lg in all_logs:
            logs_by_inst.setdefault(lg.instance_id, []).append(lg)
        users = {u.id: u for u in await self.users.list_all()}
        name_of = lambda uid: (
            (users[uid].full_name or users[uid].username)
            if uid in users else (f"#{uid}" if uid else "—")
        )

        running_instances: list[dict] = []
        for i in running:
            ver = versions.get(i.version_id)
            graph = (ver.graph if ver else {}) or {}
            node_map = {n["id"]: n for n in graph.get("nodes", [])}
            current = [
                {"node_id": nid, "name": node_map.get(nid, {}).get("name", nid),
                 "type": node_map.get(nid, {}).get("type", "")}
                for nid in (i.current_nodes or [])
            ]
            total_nodes = len(graph.get("nodes", [])) or 1
            finished_nodes = len(
                [l for l in logs_by_inst.get(i.id, []) if l.action == "finish"]
            )
            progress = min(100, round(finished_nodes / total_nodes * 100))
            running_instances.append({
                "id": i.id,
                "code": i.code,
                "title": i.title,
                "definition_name": def_map[i.definition_id].name if i.definition_id in def_map else "",
                "initiator": name_of(i.initiator_id),
                "current_nodes": current,
                "started_at": i.started_at.isoformat() if i.started_at else None,
                "progress": progress,
            })

        # 超时任务上下文
        inst_map = {i.id: i for i in instances}
        overdue_tasks: list[dict] = []
        for t in overdue:
            inst = inst_map.get(t.instance_id)
            overdue_tasks.append({
                "task_id": t.id,
                "instance_id": t.instance_id,
                "instance_code": inst.code if inst else "",
                "instance_title": inst.title if inst else "",
                "node_name": t.node_name,
                "approver_id": t.approver_id,
                "approver_name": name_of(t.approver_id),
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "due_at": t.due_at.isoformat() if t.due_at else None,
            })
        overdue_tasks.sort(key=lambda x: x["created_at"] or "")

        return {
            "generated_at": now_naive,
            "sla_days": SLA_DAYS,
            "definitions": definitions_stat,
            "instances": instances_stat,
            "tasks": tasks_stat,
            "delegations_active": delegations,
            "by_definition": by_definition,
            "trend": trend,
            "overdue_tasks": overdue_tasks,
            "running_instances": running_instances,
        }

    # ---- 内部 ----
    async def _refresh_with_tasks(self, instance) -> None:
        """提交后刷新实例并**显式加载 tasks 集合**。

        响应模型 `WorkflowInstanceOut` 要序列化 `tasks`；在异步会话里访问未加载的集合
        会触发惰性 IO，抛 `MissingGreenlet`（接口 500）。注意 `refresh(instance)` 只刷新
        标量列、不加载集合，必须写成 `refresh(instance, ["tasks"])`。
        """
        await self.session.refresh(instance, ["tasks"])

    async def _node_sets(self, instance) -> tuple[set, set]:
        """从流转日志推导已完成/已激活节点集合（供汇聚判断使用）。"""
        logs = await self.repo.list_logs(instance.id)
        finished = {l.node_id for l in logs if l.action == "finish"}
        activated = {l.node_id for l in logs if l.action in ("enter", "finish")}
        return finished, activated

    async def _log_passed(self, instance, graph: dict, passed: list[str]) -> None:
        nodes = {n["id"]: n for n in graph.get("nodes", [])}
        for nid in passed:
            await self.repo.add_log(
                WorkflowNodeLog(
                    instance_id=instance.id, node_id=nid,
                    node_name=(nodes.get(nid) or {}).get("name", ""),
                    action="finish", operator_id=None, comment="自动节点通过",
                )
            )

    async def _activate(self, instance, graph: dict, node_ids: list[str]) -> tuple[list[str], list[int]]:
        """为激活节点建任务；抄送与无人节点自动通过并继续推进；遇结束节点则完结。

        返回 (激活节点列表, 本次新分派任务的用户 id 列表)，供调用方在事务提交后推送实时事件。
        """
        nodes = {n["id"]: n for n in graph.get("nodes", [])}
        queue = list(node_ids)
        activated: list[str] = []
        assigned_uids: list[int] = []
        ended = False

        while queue:
            nid = queue.pop(0)
            node = nodes.get(nid) or {}
            ntype = node.get("type", "approval")
            name = node.get("name", "")

            if ntype == "end":
                ended = True
                await self.repo.add_log(
                    WorkflowNodeLog(
                        instance_id=instance.id, node_id=nid, node_name=name,
                        action="finish", operator_id=None, comment="流程结束",
                    )
                )
                continue

            await self.repo.add_log(
                WorkflowNodeLog(
                    instance_id=instance.id, node_id=nid, node_name=name,
                    action="enter", operator_id=None, comment="",
                )
            )

            specs = node.get("assignees") or (
                [node["assignee"]] if node.get("assignee") else []
            )
            uids: list[int] = []
            for spec in specs:
                uids.extend(await self._resolve_assignees(spec, instance))
            uids = [u for u in dict.fromkeys(uids) if u]

            if ntype == "notify":
                # 抄送：生成知会记录，不阻塞流转，并写入消息中心
                for uid in uids:
                    self.session.add(
                        WorkflowTask(
                            instance_id=instance.id, node_id=nid, node_name=name,
                            node_type="notify", approver_id=uid, status="approved",
                            mode="single", seq=0, decided_at=_now(),
                        )
                    )
                    await self.notifications.add(
                        uid, "workflow", f"流程抄送：{instance.title}",
                        f"节点「{name}」已抄送知会您。", f"/workflows/instance/{instance.id}",
                    )
                await self.repo.add_log(
                    WorkflowNodeLog(
                        instance_id=instance.id, node_id=nid, node_name=name,
                        action="finish", operator_id=None, comment="抄送自动通过",
                    )
                )
                finished, activated_set = await self._node_sets(instance)
                nxt, passed = advance(
                    graph, nid, instance.form_data,
                    finished | {nid}, activated_set | {nid},
                )
                await self._log_passed(instance, graph, passed)
                queue.extend(nxt)
                continue

            if not uids:
                # 审批人为空（如角色无成员）：自动通过，避免流程卡死
                await self.repo.add_log(
                    WorkflowNodeLog(
                        instance_id=instance.id, node_id=nid, node_name=name,
                        action="finish", operator_id=None, comment="无审批人自动通过",
                    )
                )
                finished, activated_set = await self._node_sets(instance)
                nxt, passed = advance(
                    graph, nid, instance.form_data,
                    finished | {nid}, activated_set | {nid},
                )
                await self._log_passed(instance, graph, passed)
                queue.extend(nxt)
                continue

            for seq, uid in enumerate(uids):
                self.session.add(
                    WorkflowTask(
                        instance_id=instance.id, node_id=nid, node_name=name,
                        node_type=ntype,
                        approver_id=uid,
                        mode="countersign" if ntype == "countersign" else "single",
                        status="pending", seq=seq,
                    )
                )
                assigned_uids.append(uid)
                # 通知任务处理人：产生待办
                await self.notifications.add(
                    uid, "workflow", f"待审批：{instance.title}",
                    f"节点「{name}」等待您审批。", f"/workflows/instance/{instance.id}",
                )
            activated.append(nid)

        instance.current_nodes = activated
        if ended:
            await self._finish_instance(instance, "approved")
        return activated, assigned_uids

    async def _finish_instance(self, instance, status: str) -> None:
        instance.status = status
        instance.finished_at = _now()
        instance.current_nodes = []
        for t in await self.repo.list_tasks(instance.id):
            if t.status == "pending":
                t.status = "canceled"
                t.decided_at = _now()
        await self._sync_business_records(instance, status)

    async def _sync_business_records(self, instance, status: str) -> None:
        """业务回写：流程结束时同步关联单据（报销单）状态。

        在调用方事务内完成、**不自行 commit**，保证流程与单据状态原子一致；
        撤回（canceled）时把单据退回草稿并解除关联，允许重新提交。
        """
        claim = await ExpenseRepository(self.session).get_by_workflow(instance.id)
        if claim is None:
            return
        if status == "approved":
            claim.status = "approved"
        elif status == "rejected":
            claim.status = "rejected"
        else:  # canceled：发起人撤回
            claim.status = "draft"
            claim.workflow_instance_id = None
        claim.reviewed_at = instance.finished_at
        if status in ("approved", "rejected"):
            res = await self.session.execute(
                select(WorkflowTask)
                .where(
                    WorkflowTask.instance_id == instance.id,
                    WorkflowTask.status.in_(["approved", "rejected"]),
                    WorkflowTask.approver_id.isnot(None),
                )
                .order_by(WorkflowTask.decided_at.desc())
                .limit(1)
            )
            last = res.scalar_one_or_none()
            if last is not None:
                claim.approver_id = last.approver_id
                claim.review_comment = last.comment or claim.review_comment
        label = {"approved": "已通过", "rejected": "已驳回", "canceled": "已撤回"}.get(status, status)
        await self.notifications.add(
            claim.user_id,
            "workflow",
            f"报销单 {claim.code} {label}",
            f"金额 {claim.amount:g} 元，{label}。",
            "/expenses",
        )

    async def _resolve_assignees(self, spec: dict | None, instance) -> list[int]:
        """解析审批人：user / role / dept_manager / initiator，并应用生效中的委托。"""
        if not spec:
            return []
        stype = spec.get("type")
        value = spec.get("value")
        uids: list[int] = []

        if stype == "user" and value:
            uids = [int(value)]
        elif stype == "role" and value:
            res = await self.session.execute(
                select(User.id).join(Role, Role.id == User.role_id).where(Role.name == value)
            )
            uids = [r[0] for r in res.all()]
        elif stype == "dept_manager":
            initiator = await self.users.get_by_id(instance.initiator_id)
            dept = getattr(initiator, "department", None)
            if dept and dept.manager_id:
                uids = [dept.manager_id]
        elif stype == "initiator":
            uids = [instance.initiator_id]

        out: list[int] = []
        for uid in uids:
            delegations = await self.repo.active_delegations(uid, instance.definition_id)
            out.append(delegations[0].to_user_id if delegations else uid)
        return out

    async def timeout_escalate_all(self, sla_days: int | None = None) -> dict:
        """审批超时自动升级：扫描超时且未升级的运行中实例，按策略处理。

        - 幂等：以 workflow_instances.escalated_at IS NULL 为扫描边界，处理成功后写入标记，
          保证同一实例仅升级一次；失败则写入死信并保持未升级，下一轮调度自然重试。
        - 去重：若同一实例已存在死信（持久化失败），跳过以避免重复轰炸通知。
        - 策略（settings.workflow_timeout_action）：
            notify   = 仅通知 admin/manager（默认，纯提醒）；
            escalate = 通知 + 将实例的待审批任务自动转交至兜底角色审批人（origin_approver_id 留痕）。
        - 返回统计：{scanned, escalated, reassigned, dead_letters}，供调度器日志与手动触发端点返回。
        """
        from app.core.config import get_settings

        settings = get_settings()
        sla = sla_days or settings.workflow_sla_days
        action = settings.workflow_timeout_action
        overdue = await self.repo.list_running_overdue(sla)
        escalated = 0
        reassigned = 0
        dead = 0
        for inst in overdue:
            # 已死信则跳过，避免每次重试都重新通知
            if await self.scheduler.exists_dead_letter(
                "workflow_timeout", inst.id
            ):
                continue
            try:
                admins = await self.users.list_ids_by_roles(
                    ["admin", "manager"]
                )
                if not admins:
                    continue
                body = (
                    f"流程《{inst.title}》于 {inst.started_at:%Y-%m-%d %H:%M} 发起，"
                    f"已超过 SLA {sla} 天仍未审批完成，请及时处理。"
                )
                await self.notifications.notify_many(
                    admins,
                    "workflow",
                    f"审批超时提醒：{inst.title}",
                    body,
                    "/workflows/monitor",
                )
                # 升级策略：将待审批任务自动转交兜底角色审批人（记录留痕，不阻塞原流程）
                if action == "escalate":
                    fallbacks = await self.users.list_ids_by_roles(
                        [settings.workflow_timeout_fallback_role]
                    )
                    if fallbacks:
                        pending = await self.repo.list_pending_tasks(inst.id)
                        for idx, task in enumerate(pending):
                            target = fallbacks[idx % len(fallbacks)]
                            if task.approver_id == target:
                                continue
                            task.origin_approver_id = task.approver_id
                            task.approver_id = target
                            self.session.add(task)
                            await self.repo.add_log(
                                WorkflowNodeLog(
                                    instance_id=inst.id,
                                    node_id=task.node_id,
                                    node_name=task.node_name,
                                    action="escalate",
                                    operator_id=target,
                                    comment=f"超时 {sla} 天自动转交至兜底审批人",
                                )
                            )
                            reassigned += 1
                        await self.session.commit()
                await self.repo.mark_escalated(inst.id)
                escalated += 1
            except Exception as exc:  # noqa: BLE001
                await self.scheduler.write_dead_letter(
                    "workflow_timeout",
                    inst.id,
                    {"instance_id": inst.id, "title": inst.title},
                    str(exc),
                )
                dead += 1
        return {
            "scanned": len(overdue),
            "escalated": escalated,
            "reassigned": reassigned,
            "dead_letters": dead,
        }


# ---------- 电子签单 ----------
class SignatureService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = SignatureRepository(session)

    def _hash_content(self, ref_type: str, ref_id: int, signature_data: str) -> str:
        return hashlib.sha256(f"{ref_type}:{ref_id}:{signature_data}".encode()).hexdigest()

    async def create(self, user_id: int, data: SignatureCreate) -> Signature:
        sig = Signature(
            ref_type=data.ref_type,
            ref_id=data.ref_id,
            signer_id=user_id,
            signature_data=data.signature_data,
            content_hash=self._hash_content(data.ref_type, data.ref_id, data.signature_data),
            comment=data.comment or "",
        )
        return await self.repo.create(sig)

    async def list_by_ref(self, ref_type: str, ref_id: int) -> list[Signature]:
        return await self.repo.list_by_ref(ref_type, ref_id)


# ---------- 建模引擎（P3）：自定义实体 + 动态数据 ----------
class ModelingService:
    """建模引擎：实体建模 + 数据行读写，字段 schema 既是渲染元数据也是服务端校验依据。

    取舍：数据存 JSON 列换取「零 DDL 建表」的灵活性，代价是无法做方言无关的谓词下推，
    因此列表过滤在内存完成并以 SCAN_CAP 限制单次扫描行数（超量需改物理列或 JSONB 索引）。
    """

    SCAN_CAP = MAX_SCAN

    def __init__(self, session: AsyncSession):
        self.session = session
        self.entities = ModelEntityRepository(session)
        self.records = ModelRecordRepository(session)
        self.users = UserRepository(session)

    # ---- 字段 schema / 取值校验：委托给零依赖纯函数模块，异常统一转 422 ----
    def _normalize_fields(self, raw: list[dict] | None) -> list[dict]:
        try:
            return normalize_fields(raw)
        except ValueError as exc:
            raise ValidationError(str(exc))

    def _clean_data(self, fields: list[dict], payload: dict, *, partial: bool = False) -> dict:
        try:
            return clean_data(fields, payload, partial=partial)
        except ValueError as exc:
            raise ValidationError(str(exc))


    async def _assert_unique(
        self, entity_id: int, fields: list[dict], data: dict, exclude_id: int | None = None
    ) -> None:
        rows = await self.records.list_by_entity(entity_id, 0, self.SCAN_CAP)
        for spec in fields:
            if not spec.get("unique"):
                continue
            val = data.get(spec["key"])
            if val in (None, ""):
                continue
            for r in rows:
                if exclude_id is not None and r.id == exclude_id:
                    continue
                if (r.data or {}).get(spec["key"]) == val:
                    raise ConflictError(f"{spec['label']} 已存在：{val}")

    # ---- 序列化 ----
    def _entity_out(self, e: ModelEntity, record_count: int = 0) -> ModelEntityOut:
        return ModelEntityOut(
            id=e.id, code=e.code, name=e.name, category=e.category, icon=e.icon,
            description=e.description, fields=e.fields or [], display_field=e.display_field,
            status=e.status, record_count=record_count, created_by=e.created_by,
            created_at=e.created_at, updated_at=e.updated_at,
        )

    def _record_out(self, r: ModelRecord) -> ModelRecordOut:
        return ModelRecordOut(
            id=r.id, entity_id=r.entity_id, serial_no=r.serial_no, data=r.data or {},
            created_by=r.created_by, updated_by=r.updated_by,
            created_at=r.created_at, updated_at=r.updated_at,
        )

    # ---- 实体 CRUD ----
    async def list_entities(self, status: str | None = None) -> list[ModelEntityOut]:
        rows = await self.entities.list(status)
        counts = await self.entities.count_records_map()
        return [self._entity_out(e, counts.get(e.id, 0)) for e in rows]

    async def get_entity(self, entity_id: int) -> ModelEntityOut:
        entity = await self.entities.get(entity_id)
        if not entity:
            raise NotFoundError("实体不存在")
        return self._entity_out(entity, await self.records.count_by_entity(entity.id))

    async def create_entity(self, data: ModelEntityCreate, actor: User) -> ModelEntityOut:
        if await self.entities.get_by_code(data.code):
            raise ConflictError("实体标识已存在")
        fields = self._normalize_fields(data.fields)
        display = data.display_field or (fields[0]["key"] if fields else "")
        if display and display not in {f["key"] for f in fields}:
            raise ValidationError("主展示字段不在字段列表中")
        entity = ModelEntity(
            code=data.code, name=data.name, category=data.category, icon=data.icon,
            description=data.description, fields=fields, display_field=display,
            status=data.status, created_by=actor.id,
        )
        created = await self.entities.create(entity)
        return self._entity_out(created, 0)

    async def update_entity(self, entity_id: int, data: ModelEntityUpdate) -> ModelEntityOut:
        entity = await self.entities.get(entity_id)
        if not entity:
            raise NotFoundError("实体不存在")
        if data.fields is not None:
            fields = self._normalize_fields(data.fields)
            entity.fields = fields
            if entity.display_field and entity.display_field not in {f["key"] for f in fields}:
                entity.display_field = fields[0]["key"] if fields else ""
        if data.display_field is not None:
            keys = {f["key"] for f in (entity.fields or [])}
            if data.display_field and data.display_field not in keys:
                raise ValidationError("主展示字段不在字段列表中")
            entity.display_field = data.display_field
        for attr in ("name", "category", "icon", "description", "status"):
            value = getattr(data, attr, None)
            if value is not None:
                setattr(entity, attr, value)
        await self.session.commit()
        await self.session.refresh(entity)
        return self._entity_out(entity, await self.records.count_by_entity(entity.id))

    async def delete_entity(self, entity_id: int) -> None:
        entity = await self.entities.get(entity_id)
        if not entity:
            raise NotFoundError("实体不存在")
        count = await self.records.count_by_entity(entity_id)
        if count > 0:
            raise ConflictError(f"实体下仍有 {count} 条数据，请先清理后再删除")
        await self.entities.delete(entity)

    # ---- 数据行 CRUD ----
    async def list_records(
        self, entity_id: int, *, filters: dict | None = None, q: str | None = None,
        offset: int = 0, limit: int = 50,
    ) -> ModelRecordsPage:
        if not await self.entities.get(entity_id):
            raise NotFoundError("实体不存在")
        rows = await self.records.list_by_entity(entity_id, 0, self.SCAN_CAP)
        matched = [r for r in rows if record_matches(r.data or {}, filters, q)]
        page = matched[offset: offset + limit]
        return ModelRecordsPage(
            total=len(matched), offset=offset, limit=limit,
            items=[self._record_out(r) for r in page],
        )

    async def create_record(
        self, entity_id: int, payload: ModelRecordCreate, actor: User
    ) -> ModelRecordOut:
        entity = await self.entities.get(entity_id)
        if not entity:
            raise NotFoundError("实体不存在")
        if entity.status != "published":
            raise ValidationError("实体尚未发布，无法录入数据")
        data = self._clean_data(entity.fields or [], payload.data)
        await self._assert_unique(entity.id, entity.fields or [], data)
        rec = ModelRecord(
            entity_id=entity.id,
            # 占位流水号保证唯一约束不冲突，flush 取到自增 id 后再回写正式编号
            serial_no=f"TMP-{uuid.uuid4().hex[:12]}",
            data=data,
            created_by=actor.id,
        )
        self.session.add(rec)
        await self.session.flush()
        rec.serial_no = f"{entity.code.upper()}-{rec.id:06d}"
        await self.session.commit()
        await self.session.refresh(rec)
        return self._record_out(rec)

    async def update_record(
        self, record_id: int, payload: ModelRecordUpdate, actor: User
    ) -> ModelRecordOut:
        rec = await self.records.get(record_id)
        if not rec:
            raise NotFoundError("数据不存在")
        entity = await self.entities.get(rec.entity_id)
        if not entity:
            raise NotFoundError("所属实体不存在")
        cleaned = self._clean_data(entity.fields or [], payload.data, partial=True)
        merged = {**(rec.data or {}), **cleaned}
        await self._assert_unique(entity.id, entity.fields or [], merged, exclude_id=rec.id)
        rec.data = merged
        rec.updated_by = actor.id
        await self.records.update(rec)
        return self._record_out(rec)

    async def delete_record(self, record_id: int) -> None:
        rec = await self.records.get(record_id)
        if not rec:
            raise NotFoundError("数据不存在")
        await self.records.delete(rec)

    # ---- 概览统计 ----
    async def stats(self) -> ModelStatsOut:
        total = await self.entities.count()
        published = await self.entities.count("published")
        records = await self.records.count()
        # 列为 naive UTC：查询参数同样用 naive，避免 PG 下 aware/naive 类型冲突
        today_start = datetime.now(timezone.utc).replace(
            tzinfo=None, hour=0, minute=0, second=0, microsecond=0
        )
        today = await self.records.count_today(today_start)
        top = await self.records.top_entities(6)
        names = {e.id: e.name for e in await self.entities.list()}
        by_entity = [
            {"entity_id": eid, "name": names.get(eid, "—"), "count": count}
            for eid, count in top
        ]
        return ModelStatsOut(
            generated_at=_now(), entities=total, entities_published=published,
            records=records, records_today=today, by_entity=by_entity,
        )


# ---------- 日志中心（P3 建模运维）：审计日志查询 / 概览 / 清理 ----------
class AuditService:
    """审计中心服务：日志查询、概览统计与清理。

    写入由审计中间件统一完成（覆盖所有变更类请求与关键认证动作），
    服务层只负责读侧聚合，保证「谁在何时对什么做了什么」完整可追溯。
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = AuditRepository(session)

    async def list_logs(
        self, *, actor_id: int | None = None, module: str | None = None,
        action: str | None = None, status: str | None = None,
        q: str | None = None, start=None, end=None,
        offset: int = 0, limit: int = 50,
    ) -> dict:
        items = await self.repo.list_logs(
            actor_id=actor_id, module=module, action=action, status=status,
            q=q, start=start, end=end, offset=offset, limit=limit,
        )
        total = await self.repo.count_logs(
            actor_id=actor_id, module=module, action=action, status=status,
            q=q, start=start, end=end,
        )
        return {
            "items": [AuditLogOut.model_validate(i) for i in items],
            "total": total,
        }

    async def stats(self) -> AuditStatsOut:
        raw = await self.repo.stats()
        return AuditStatsOut(
            generated_at=_now(),
            total=raw["total"], success=raw["success"], failed=raw["failed"],
            by_module=raw["by_module"], by_status=raw["by_status"], trend=raw["trend"],
        )

    async def purge(self, days: int) -> int:
        """清理 N 天前的审计记录；返回删除行数（由审计管理权限把关）。"""
        # 列为 naive UTC，切点同样用 naive，避免 aware/naive 比较类型冲突
        cutoff = (_now() - timedelta(days=days)).replace(tzinfo=None)
        return await self.repo.purge_before(cutoff)

    async def get_log_detail(self, log_id: int) -> dict | None:
        """获取单条审计日志详情（含 before/after value, correlation_id, duration_ms）"""
        log = await self.repo.get_log_detail(log_id)
        if not log:
            return None
        return {
            "id": log.id,
            "actor_id": log.actor_id,
            "actor_name": log.actor_name,
            "module": log.module,
            "action": log.action,
            "target_type": log.target_type,
            "target_id": log.target_id,
            "method": log.method,
            "path": log.path,
            "status": log.status,
            "status_code": log.status_code,
            "message": log.message,
            "detail": log.detail,
            "before_value": log.before_value,
            "after_value": log.after_value,
            "correlation_id": log.correlation_id,
            "duration_ms": log.duration_ms,
            "ip": log.ip,
            "request_id": log.request_id,
            "created_at": log.created_at,
        }

    async def list_logs_by_correlation(
        self, correlation_id: str, offset: int = 0, limit: int = 50
    ) -> dict:
        """按关联 ID 查询关联的审计日志"""
        items = await self.repo.list_logs_with_correlation(correlation_id, offset, limit)
        total = await self.repo.count_by_correlation(correlation_id)
        return {
            "items": [AuditLogOut.model_validate(i) for i in items],
            "total": total,
        }

    async def stats_duration(self, module: str | None = None) -> dict:
        """统计请求耗时分布"""
        return await self.repo.stats_duration(module)

    async def export_logs(self, *, actor_id: int | None = None, module: str | None = None,
                          action: str | None = None, status: str | None = None,
                          start=None, end=None, limit: int = 10000) -> list[dict]:
        """导出审计日志为列表（供前端生成 CSV/Excel）。"""
        items = await self.repo.list_logs(
            actor_id=actor_id, module=module, action=action, status=status,
            start=start, end=end, offset=0, limit=limit,
        )
        return [
            {
                "id": i.id,
                "时间": i.created_at.strftime("%Y-%m-%d %H:%M:%S") if i.created_at else "",
                "操作人": i.actor_name,
                "模块": i.module,
                "动作": i.action,
                "对象": f"{i.target_type}:{i.target_id}" if i.target_id else i.target_type,
                "方法": i.method,
                "路径": i.path,
                "状态": "成功" if i.status == "success" else "失败",
                "HTTP状态码": i.status_code,
                "IP": i.ip,
                "耗时(ms)": i.duration_ms or "",
                "消息": i.message,
            }
            for i in items
        ]


# ---------- 报表中心：统一数据看板 ----------
# KPI 导出中文标签（与 DashboardKpiOut 字段一一对应）
_DASHBOARD_KPI_LABELS: dict[str, str] = {
    "users_total": "用户总数",
    "departments_total": "部门总数",
    "workflow_instances": "流程实例总数",
    "workflow_active": "在途流程",
    "workflow_done": "已办结",
    "leaves_this_month": "本月请假",
    "announcements_total": "公告总数",
    "audit_total": "审计记录",
}

# 流程状态中文标签（导出 CSV 时把裸状态码转可读文案；缺省回退原值）
_DASHBOARD_STATUS_LABELS: dict[str, str] = {
    "draft": "草稿",
    "pending": "待审批",
    "running": "审批中",
    "approved": "已通过",
    "rejected": "已驳回",
    "cancelled": "已撤销",
    "terminated": "已终止",
}


class DashboardService:
    """报表中心聚合：个人视图恒返回；组织级 KPI 与图表受 `report:view` 控制。

    设计取舍：计数与分组全部下推到仓储层 SQL（count / group by），避免把全表捞进内存；
    趋势的日期分桶在 Python 侧完成（同 AuditRepository.stats），规避 SQLite/PG 方言差异。
    权限判定在路由层完成并以 `has_org_scope` 传入，服务层不感知 HTTP 与权限码。
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.users = UserRepository(session)
        self.depts = DepartmentRepository(session)
        self.leaves = LeaveRepository(session)
        self.anns = AnnouncementRepository(session)
        self.wf = WorkflowRepository(session)
        self.notifs = NotificationRepository(session)
        self.audit = AuditRepository(session)

    async def _personal(self, user: User) -> dict:
        """个人视图：所有登录用户可见（未读 / 待我审批 / 我的请假 / 我在途）。"""
        return {
            "my_unread": await self.notifs.count_for_user(user.id, only_unread=True),
            "my_pending_approvals": len(await self.wf.pending_for(user.id)),
            "my_leaves": await self.leaves.count(user_id=user.id),
            "my_running": await self.wf.count_for_initiator(user.id, "running"),
        }

    async def _org(self, days: int = 30) -> dict:
        """组织级聚合：KPI + 流程状态分布 + 近 N 天趋势 + 部门人数 + 最近动态。"""
        status_map = await self.wf.count_instances_by_status()
        kpi = {
            "users_total": await self.users.count(),
            "departments_total": await self.depts.count(),
            "workflow_instances": sum(status_map.values()),
            "workflow_active": int(status_map.get("running", 0)),
            "workflow_done": int(status_map.get("approved", 0))
            + int(status_map.get("rejected", 0)),
            "leaves_this_month": await self.leaves.count_this_month(),
            "announcements_total": await self.anns.count(),
            "audit_total": await self.audit.count_logs(),
        }
        status = [
            {"status": k, "count": int(v)}
            for k, v in sorted(status_map.items(), key=lambda kv: kv[1], reverse=True)
        ]
        headcount = [
            {"department": d["department"], "count": int(d["count"])}
            for d in await self.users.count_by_department()
        ]
        logs = await self.audit.list_logs(limit=8)
        activities = [
            {
                "id": lg.id,
                "title": lg.message or f"{lg.module}.{lg.action}",
                "type": lg.module,
                "status": lg.status,
                "at": lg.created_at.isoformat() if lg.created_at else None,
                "actor": lg.actor_name,
            }
            for lg in logs
        ]
        return {
            "kpi": kpi,
            "workflow_status": status,
            "workflow_trend": await self.wf.trend(days),
            "trend_days": days,
            "department_headcount": headcount,
            "recent_activities": activities,
        }

    async def overview(
        self, user: User, has_org_scope: bool = False, days: int = 30
    ) -> dict:
        """返回 DashboardOut 结构；无组织权限时 org 为 None（前端据此隐藏图表区）。

        `days` 控制组织级趋势窗口（7/30/90），不影响 KPI 等全量聚合。
        """
        out: dict = {
            "generated_at": _now(),
            "has_org_scope": has_org_scope,
            "personal": await self._personal(user),
            "org": None,
        }
        if has_org_scope:
            out["org"] = await self._org(days)
        return out

    async def export_tables(self, days: int = 30) -> dict[str, list[list[str]]]:
        """组织级导出数据：按主题拆成多张 CSV 表（键为文件名，值为 [表头, ...数据行]）。

        服务层只负责把聚合结果规整为二维字符串表，ZIP/字节编码交给路由层，
        保持服务层不依赖 HTTP 响应对象。无 report:view 时路由层不会调用本方法。
        """
        org = await self._org(days)
        tables: dict[str, list[list[str]]] = {}
        tables["kpi.csv"] = [["指标", "数值"]] + [
            [_DASHBOARD_KPI_LABELS.get(k, k), str(v)] for k, v in org["kpi"].items()
        ]
        tables["workflow_status.csv"] = [["状态", "数量"]] + [
            [_DASHBOARD_STATUS_LABELS.get(s["status"], s["status"]), str(s["count"])]
            for s in org["workflow_status"]
        ]
        tables["workflow_trend.csv"] = [["日期", "发起", "完成"]] + [
            [t["date"], str(t["started"]), str(t["finished"])]
            for t in org["workflow_trend"]
        ]
        tables["department_headcount.csv"] = [["部门", "人数"]] + [
            [d["department"], str(d["count"])] for d in org["department_headcount"]
        ]
        tables["recent_activities.csv"] = [
            ["ID", "摘要", "模块", "结果", "操作人", "时间"]
        ] + [
            [
                str(a["id"]),
                a["title"],
                a["type"],
                a["status"] or "",
                a["actor"] or "",
                a["at"] or "",
            ]
            for a in org["recent_activities"]
        ]
        return tables


# =========================================================================
# ---------- 多维报表 + 趋势分析 ----------
# =========================================================================
class ReportService:
    """多维报表服务：跨模块聚合、趋势分析、同比环比。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def cube(self, metrics: list[str], dimension: str = "month",
                   start: date | None = None, end: date | None = None) -> dict:
        """多维数据立方体：按维度聚合指定指标。"""
        if not start:
            start = date.today().replace(day=1)
        if not end:
            end = date.today()

        result: dict[str, list[dict]] = {}
        for metric in metrics:
            if metric == "attendance":
                result["attendance"] = await self._attendance_cube(dimension, start, end)
            elif metric == "expense":
                result["expense"] = await self._expense_cube(dimension, start, end)
            elif metric == "workflow":
                result["workflow"] = await self._workflow_cube(dimension, start, end)
            elif metric == "official_doc":
                result["official_doc"] = await self._official_doc_cube(dimension, start, end)
        return {"dimension": dimension, "start": start, "end": end, "data": result}

    async def _attendance_cube(self, dimension: str, start: date, end: date) -> list[dict]:
        """考勤维度聚合：by user/department/month。"""
        stmt = select(
            Attendance.user_id,
            func.count().label("total"),
            func.sum(case((Attendance.status == "normal", 1), else_=0)).label("normal"),
            func.sum(case((Attendance.status == "late", 1), else_=0)).label("late"),
            func.sum(case((Attendance.status == "absent", 1), else_=0)).label("absent"),
        ).where(
            Attendance.day >= start,
            Attendance.day <= end,
        ).group_by(Attendance.user_id)
        res = await self.session.execute(stmt)
        rows = res.all()
        # 获取用户信息
        user_ids = [r[0] for r in rows]
        if user_ids:
            user_res = await self.session.execute(
                select(User.id, User.full_name, User.username, Department.name)
                .outerjoin(Department, Department.id == User.department_id)
                .where(User.id.in_(user_ids))
            )
            user_map = {r[0]: {"name": r[1] or r[2], "department": r[3] or "未分配"} for r in user_res.all()}
        else:
            user_map = {}
        return [
            {
                "user_id": r[0],
                "user_name": user_map.get(r[0], {}).get("name", f"#{r[0]}"),
                "department": user_map.get(r[0], {}).get("department", "未分配"),
                "total": r[1],
                "normal": int(r[2] or 0),
                "late": int(r[3] or 0),
                "absent": int(r[4] or 0),
                "attendance_rate": round(int(r[2] or 0) / max(r[1], 1) * 100, 1),
            }
            for r in rows
        ]

    async def _expense_cube(self, dimension: str, start: date, end: date) -> list[dict]:
        """报销维度聚合：by type/department/month。"""
        stmt = select(
            ExpenseClaim.claim_type,
            func.count().label("count"),
            func.sum(ExpenseClaim.amount).label("total_amount"),
        ).where(
            ExpenseClaim.created_at >= datetime.combine(start, datetime.min.time()),
            ExpenseClaim.created_at <= datetime.combine(end, datetime.max.time()),
        ).group_by(ExpenseClaim.claim_type)
        res = await self.session.execute(stmt)
        return [
            {"type": r[0] or "other", "count": r[1], "total_amount": float(r[2] or 0)}
            for r in res.all()
        ]

    async def _workflow_cube(self, dimension: str, start: date, end: date) -> list[dict]:
        """流程维度聚合：by status/definition。"""
        stmt = select(
            WorkflowInstance.status,
            func.count().label("count"),
        ).where(
            WorkflowInstance.created_at >= datetime.combine(start, datetime.min.time()),
            WorkflowInstance.created_at <= datetime.combine(end, datetime.max.time()),
        ).group_by(WorkflowInstance.status)
        res = await self.session.execute(stmt)
        return [{"status": r[0], "count": r[1]} for r in res.all()]

    async def _official_doc_cube(self, dimension: str, start: date, end: date) -> list[dict]:
        """公文维度聚合：by direction/status。"""
        stmt = select(
            OfficialDocument.direction,
            OfficialDocument.status,
            func.count().label("count"),
        ).where(
            OfficialDocument.created_at >= datetime.combine(start, datetime.min.time()),
            OfficialDocument.created_at <= datetime.combine(end, datetime.max.time()),
        ).group_by(OfficialDocument.direction, OfficialDocument.status)
        res = await self.session.execute(stmt)
        return [
            {"direction": r[0], "status": r[1], "count": r[2]}
            for r in res.all()
        ]

    async def trends(self, days: int = 30, metrics: list[str] | None = None) -> dict:
        """趋势分析：近 N 天各指标的日趋势 + 同比/环比 + 移动平均。"""
        if not metrics:
            metrics = ["attendance", "expense", "workflow", "official_doc"]
        end = date.today()
        start = end - timedelta(days=days)
        result: dict[str, list[dict]] = {}
        for metric in metrics:
            if metric == "attendance":
                result["attendance"] = await self._attendance_trend(start, end)
            elif metric == "expense":
                result["expense"] = await self._expense_trend(start, end)
            elif metric == "workflow":
                result["workflow"] = await self._workflow_trend(start, end)
            elif metric == "official_doc":
                result["official_doc"] = await self._official_doc_trend(start, end)
        # 添加移动平均（7天）
        for metric, data in result.items():
            if len(data) >= 7:
                values = [d.get("count", 0) for d in data]
                for i in range(6, len(data)):
                    data[i]["moving_avg_7d"] = round(sum(values[i-6:i+1]) / 7, 1)
        return {"days": days, "start": start, "end": end, "trends": result}

    async def _attendance_trend(self, start: date, end: date) -> list[dict]:
        """考勤日趋势：每天的出勤/迟到/缺勤数。"""
        stmt = select(
            Attendance.day,
            func.count().label("total"),
            func.sum(case((Attendance.status == "normal", 1), else_=0)).label("normal"),
            func.sum(case((Attendance.status == "late", 1), else_=0)).label("late"),
            func.sum(case((Attendance.status == "absent", 1), else_=0)).label("absent"),
        ).where(
            Attendance.day >= start,
            Attendance.day <= end,
        ).group_by(Attendance.day).order_by(Attendance.day)
        res = await self.session.execute(stmt)
        return [
            {
                "date": r[0].isoformat(),
                "count": r[1],
                "normal": int(r[2] or 0),
                "late": int(r[3] or 0),
                "absent": int(r[4] or 0),
            }
            for r in res.all()
        ]

    async def _expense_trend(self, start: date, end: date) -> list[dict]:
        """报销日趋势：每天的申请数和金额。"""
        stmt = select(
            func.date(ExpenseClaim.created_at).label("day"),
            func.count().label("count"),
            func.sum(ExpenseClaim.amount).label("amount"),
        ).where(
            ExpenseClaim.created_at >= datetime.combine(start, datetime.min.time()),
            ExpenseClaim.created_at <= datetime.combine(end, datetime.max.time()),
        ).group_by(func.date(ExpenseClaim.created_at)).order_by(func.date(ExpenseClaim.created_at))
        res = await self.session.execute(stmt)
        return [
            {"date": str(r[0]), "count": r[1], "amount": float(r[2] or 0)}
            for r in res.all()
        ]

    async def _workflow_trend(self, start: date, end: date) -> list[dict]:
        """流程日趋势：每天的发起/完成数。"""
        # 发起趋势
        start_stmt = select(
            func.date(WorkflowInstance.created_at).label("day"),
            func.count().label("started"),
        ).where(
            WorkflowInstance.created_at >= datetime.combine(start, datetime.min.time()),
            WorkflowInstance.created_at <= datetime.combine(end, datetime.max.time()),
        ).group_by(func.date(WorkflowInstance.created_at))
        start_res = await self.session.execute(start_stmt)
        started_map = {str(r[0]): r[1] for r in start_res.all()}
        # 完成趋势（status in approved/rejected/terminated，用 finished_at 落点）
        done_stmt = select(
            func.date(WorkflowInstance.finished_at).label("day"),
            func.count().label("finished"),
        ).where(
            WorkflowInstance.status.in_(["approved", "rejected", "terminated"]),
            WorkflowInstance.finished_at.is_not(None),
            WorkflowInstance.finished_at >= datetime.combine(start, datetime.min.time()),
            WorkflowInstance.finished_at <= datetime.combine(end, datetime.max.time()),
        ).group_by(func.date(WorkflowInstance.finished_at))
        done_res = await self.session.execute(done_stmt)
        done_map = {str(r[0]): r[1] for r in done_res.all()}
        # 合并
        all_days = sorted(set(list(started_map.keys()) + list(done_map.keys())))
        return [
            {"date": d, "started": started_map.get(d, 0), "finished": done_map.get(d, 0)}
            for d in all_days
        ]

    async def _official_doc_trend(self, start: date, end: date) -> list[dict]:
        """公文日趋势：每天的收文/发文数。"""
        stmt = select(
            func.date(OfficialDocument.created_at).label("day"),
            OfficialDocument.direction,
            func.count().label("count"),
        ).where(
            OfficialDocument.created_at >= datetime.combine(start, datetime.min.time()),
            OfficialDocument.created_at <= datetime.combine(end, datetime.max.time()),
        ).group_by(func.date(OfficialDocument.created_at), OfficialDocument.direction)
        res = await self.session.execute(stmt)
        day_map: dict[str, dict] = {}
        for r in res.all():
            d = str(r[0])
            if d not in day_map:
                day_map[d] = {"date": d, "in": 0, "out": 0}
            day_map[d][r[1]] = r[2]
        return sorted(day_map.values(), key=lambda x: x["date"])


# =========================================================================
# ---------- 考勤管理（打卡 / 班次 / 加班 / 月度统计） ----------
# =========================================================================
def _attendance_now() -> datetime:
    """考勤时间取服务器本地时间：与班次 HH:MM、day 归属同一时钟，避免 UTC 错位。"""
    return datetime.now()


def _parse_hhmm(value: str, fallback: str) -> time:
    try:
        hh, mm = (int(x) for x in (value or "").split(":", 1))
        return time(min(max(hh, 0), 23), min(max(mm, 0), 59))
    except Exception:  # noqa: BLE001
        hh, mm = (int(x) for x in fallback.split(":"))
        return time(hh, mm)


def _parse_month(month: str) -> tuple[int, int]:
    try:
        y, m = (int(x) for x in month.split("-", 1))
        if not (1 <= m <= 12 and 2000 <= y <= 2100):
            raise ValueError
        return y, m
    except Exception:  # noqa: BLE001
        raise ValidationError("月份格式应为 YYYY-MM")


def _month_range(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = date(year + (1 if month == 12 else 0), 1 if month == 12 else month + 1, 1)
    return start, end


def _daterange(start: date, end: date) -> list[date]:
    """闭区间 [start, end] 的日期列表（预警扫描用；区间上限由调用方校验）。"""
    out: list[date] = []
    cur = start
    while cur <= end:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def _expected_workdays(year: int, month: int, workdays: list | None) -> int:
    days = [1, 2, 3, 4, 5] if not workdays else [int(d) for d in workdays]
    start, end = _month_range(year, month)
    n = 0
    cur = start
    while cur < end:
        if cur.isoweekday() in days:
            n += 1
        cur += timedelta(days=1)
    return n


class AttendanceService:
    """考勤：打卡落库 + 班次判定（迟到/早退/工时）+ 加班审批 + 月度统计。"""

    def __init__(self, session: AsyncSession, *, event_bus: "EventBus | None" = None):
        self.session = session
        self.repo = AttendanceRepository(session)
        self.overtime = OvertimeRepository(session)
        self.fieldwork = FieldWorkRepository(session)
        self.bus = event_bus

    # ---- 班次设置 ----
    async def get_settings(self) -> AttendanceSetting:
        setting = await self.repo.get_settings()
        # 未配置时返回默认值（不落库）：必须显式给值——SQLAlchemy 的列默认在 flush 时
        # 才生效，直接返回 AttendanceSetting() 会让响应模型拿到全 None 而 500。
        if setting is None:
            return AttendanceSetting(
                id=0, name="标准班次", work_start="09:00", work_end="18:00",
                late_grace_minutes=0, workdays=[1, 2, 3, 4, 5],
            )
        if not setting.workdays:
            setting.workdays = [1, 2, 3, 4, 5]
        return setting

    async def save_settings(self, actor_id: int, payload: dict) -> AttendanceSetting:
        clean = {k: v for k, v in (payload or {}).items() if v is not None}
        if not clean:
            raise ValidationError("没有需要更新的字段")
        if "workdays" in clean:
            days = [int(d) for d in clean["workdays"]]
            if not days or len(set(days)) != len(days) or any(d < 1 or d > 7 for d in days):
                raise ValidationError("工作日必须是 1-7 且不重复的非空列表")
            clean["workdays"] = sorted(days)
        if "late_grace_minutes" in clean:
            clean["late_grace_minutes"] = int(clean["late_grace_minutes"])
        candidate = AttendanceSetting(**clean, updated_by=actor_id)
        return await self.repo.save_settings(candidate)

    # ---- 打卡 ----
    def _schedule(self, settings: AttendanceSetting, day: date) -> tuple[datetime, datetime]:
        return (
            datetime.combine(day, _parse_hhmm(settings.work_start, "09:00")),
            datetime.combine(day, _parse_hhmm(settings.work_end, "18:00")),
        )

    async def clock(
        self,
        user: User,
        now: datetime | None = None,
        # GPS参数
        lat: float | None = None,
        lng: float | None = None,
        address: str | None = None,
        is_field_work: bool = False,
        field_work_address: str | None = None,
        field_work_note: str | None = None,
    ) -> tuple[Attendance, str]:
        now = now or _attendance_now()
        today = now.date()
        settings = await self.get_settings()
        start_at, end_at = self._schedule(settings, today)
        rec = await self.repo.get_by_day(user.id, today)
        # 外勤关联：当日存在已通过的外勤单时自动挂接（并免计迟到/早退）
        field_orders = await self.fieldwork.approved_covering(
            start=today, end=today, user_ids=[user.id]
        )
        field_order = field_orders[0] if field_orders else None

        if rec is None or rec.check_in is None:
            grace_end = start_at + timedelta(minutes=max(settings.late_grace_minutes, 0))
            late = int((now - grace_end).total_seconds() // 60) if now > grace_end else 0
            late = max(late, 0)
            if field_order:
                late = 0  # 外勤日不计迟到
            if rec is None:
                rec = Attendance(
                    user_id=user.id,
                    day=today,
                    check_in=now,
                    late_minutes=late,
                    status="late" if late else "normal",
                    source="clock",
                    # GPS字段
                    check_in_lat=lat,
                    check_in_lng=lng,
                    check_in_address=address,
                    is_field_work=bool(is_field_work or field_order),
                    field_work_address=field_work_address
                    or (field_order.address if field_order else None),
                    field_work_note=field_work_note,
                    field_work_order_id=field_order.id if field_order else None,
                )
            else:
                # 管理员已手工标记（请假/出差等）后本人补打卡：保留标记，补上时间
                rec.check_in = now
                rec.late_minutes = late
                rec.source = "clock"
                if rec.status == "absent":
                    rec.status = "late" if late else "normal"
                # 更新GPS信息
                if lat is not None:
                    rec.check_in_lat = lat
                if lng is not None:
                    rec.check_in_lng = lng
                if address is not None:
                    rec.check_in_address = address
                if is_field_work or field_order:
                    rec.is_field_work = True
                if field_work_address is not None:
                    rec.field_work_address = field_work_address
                elif field_order and not rec.field_work_address:
                    rec.field_work_address = field_order.address
                if field_work_note is not None:
                    rec.field_work_note = field_work_note
                if field_order:
                    rec.field_work_order_id = field_order.id
            rec = await self.repo.create(rec) if rec.id is None else await self.repo.update(rec)
            msg = f"上班打卡成功（{now:%H:%M}）"
            if late:
                msg += f"，迟到 {late} 分钟"
            return rec, msg

        if rec.check_out:
            raise ValidationError("今日已完成上、下班打卡")
        early = int((end_at - now).total_seconds() // 60) if now < end_at else 0
        early = max(early, 0)
        if field_order:
            rec.field_work_order_id = rec.field_work_order_id or field_order.id
            rec.is_field_work = True
        if rec.field_work_order_id:
            early = 0  # 外勤日不计早退
        rec.check_out = now
        rec.early_minutes = early
        rec.work_minutes = max(int((now - rec.check_in).total_seconds() // 60), 0)
        # 更新GPS信息
        if lat is not None:
            rec.check_out_lat = lat
        if lng is not None:
            rec.check_out_lng = lng
        if address is not None:
            rec.check_out_address = address
        if rec.late_minutes > 0:
            rec.status = "late"
        elif early > 0:
            rec.status = "early"
        elif rec.status in ("absent",):
            rec.status = "normal"
        rec = await self.repo.update(rec)
        msg = f"下班打卡成功（{now:%H:%M}）"
        if early:
            msg += f"，早退 {early} 分钟"
        return rec, msg

    # ---- 我的月度视图 ----
    async def my_month(self, user_id: int, month: str) -> dict:
        y, m = _parse_month(month)
        records = await self.repo.list_month(user_id, y, m)
        settings = await self.get_settings()
        expected = _expected_workdays(y, m, settings.workdays)
        attended = [r for r in records if r.check_in is not None]
        excused = [r for r in records if r.check_in is None and r.status in ("leave", "travel", "remote")]
        late_days = sum(1 for r in attended if r.late_minutes > 0)
        early_days = sum(1 for r in attended if r.early_minutes > 0)
        absent = max(0, expected - len(attended) - len(excused))
        start, end = _month_range(y, m)
        overtime_hours = await self.overtime.approved_hours(user_id, start, end)
        avg = int(sum(r.work_minutes for r in attended) / len(attended)) if attended else 0
        return {
            "records": records,
            "summary": {
                "month": month,
                "expected_workdays": expected,
                "present_days": len(attended),
                "late_days": late_days,
                "early_days": early_days,
                "absent_days": absent,
                "leave_days": sum(1 for r in records if r.status == "leave"),
                "travel_days": sum(1 for r in records if r.status == "travel"),
                "remote_days": sum(1 for r in records if r.status == "remote"),
                "overtime_hours": round(overtime_hours, 1),
                "avg_work_minutes": avg,
            },
        }

    # ---- 管理端 ----
    async def list_records(
        self, *, start: date, end: date, user_id: int | None = None,
        status: str | None = None, offset: int = 0, limit: int = 50,
    ) -> tuple[list[Attendance], int]:
        items = await self.repo.list_range(
            start=start, end=end, user_id=user_id, status=status, offset=offset, limit=limit
        )
        total = await self.repo.count_range(start=start, end=end, user_id=user_id, status=status)
        return items, total

    async def update_record(self, rec_id: int, payload: dict) -> Attendance:
        rec = await self.repo.get(rec_id)
        if not rec:
            raise NotFoundError("考勤记录不存在")
        data = {k: v for k, v in (payload or {}).items() if v is not None}
        settings = await self.get_settings()
        start_at, end_at = self._schedule(settings, rec.day)
        if "check_in" in data:
            rec.check_in = data["check_in"]
            if rec.check_in:
                grace_end = start_at + timedelta(minutes=max(settings.late_grace_minutes, 0))
                rec.late_minutes = max(int((rec.check_in - grace_end).total_seconds() // 60), 0)
        if "check_out" in data:
            rec.check_out = data["check_out"]
            if rec.check_out:
                rec.early_minutes = max(int((end_at - rec.check_out).total_seconds() // 60), 0)
        if rec.check_in and rec.check_out:
            rec.work_minutes = max(int((rec.check_out - rec.check_in).total_seconds() // 60), 0)
        if "status" in data:
            rec.status = data["status"]
            if rec.status in ("leave", "travel", "remote"):
                # 免出勤标记：清掉迟到早退，避免与打卡语义冲突
                if rec.check_in is None:
                    rec.late_minutes = rec.early_minutes = rec.work_minutes = 0
        if "note" in data:
            rec.note = data["note"]
        rec.source = "manual"
        return await self.repo.update(rec)

    async def stats(self, month: str) -> dict:
        y, m = _parse_month(month)
        settings = await self.get_settings()
        expected = _expected_workdays(y, m, settings.workdays)
        groups = await self.repo.group_by_user_month(y, m)
        user_ids = [g[0] for g in groups]
        names: dict[int, tuple[str, str]] = {}
        if user_ids:
            res = await self.session.execute(
                select(User.id, User.username, User.full_name).where(User.id.in_(user_ids))
            )
            names = {r[0]: (r[1], r[2] or r[1]) for r in res.all()}
        rows = []
        for uid, attended, excused, late, early in groups:
            username, full_name = names.get(uid, (f"#{uid}", f"用户#{uid}"))
            rows.append({
                "user_id": uid,
                "username": username,
                "full_name": full_name,
                "present_days": attended,
                "late_days": late,
                "early_days": early,
                "absent_days": max(0, expected - attended - excused),
                "leave_days": 0,
                "overtime_hours": round(
                    await self.overtime.approved_hours(
                        uid, *_month_range(y, m)
                    ),
                    1,
                ),
            })
        rows.sort(key=lambda r: (-r["present_days"], r["username"]))
        return {
            "month": month,
            "expected_workdays": expected,
            "rows": rows,
            "pending_overtime": await self.overtime.count(status="pending"),
        }
    
    # ---- 考勤批量导入（批量解析 + 预检 dry_run + 外勤关联） ----
    IMPORT_STATUSES = ("normal", "late", "early", "absent", "leave", "travel", "remote")
    # 中文状态别名：模板里写中文也能识别
    IMPORT_STATUS_ALIASES = {
        "正常": "normal", "迟到": "late", "早退": "early", "缺勤": "absent",
        "请假": "leave", "出差": "travel", "远程": "remote", "外勤": "normal",
    }

    @classmethod
    def _import_status(cls, val) -> str | None:
        """状态列 → 合法枚举；无法识别返回 None（调用方按行报错）。"""
        if val is None or str(val).strip() == "":
            return "normal"
        raw = str(val).strip().lower()
        if raw in cls.IMPORT_STATUSES:
            return raw
        return cls.IMPORT_STATUS_ALIASES.get(str(val).strip())

    @staticmethod
    def _import_bool(val) -> bool:
        if val is None:
            return False
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return bool(int(val))
        return str(val).strip().lower() in ("1", "true", "t", "y", "yes", "是", "外勤", "√")

    @staticmethod
    def _import_time(val) -> "time | None":
        if val is None or (isinstance(val, str) and not val.strip()):
            return None
        if isinstance(val, datetime):
            return val.time()
        if isinstance(val, time):
            return val
        raw = str(val).strip()
        for fmt in ("%H:%M:%S", "%H:%M", "%H%M"):
            try:
                return datetime.strptime(raw, fmt).time()
            except ValueError:
                continue
        try:
            return time.fromisoformat(raw)
        except ValueError:
            return None

    @staticmethod
    def _import_day(val) -> "date | None":
        if val is None:
            return None
        if isinstance(val, datetime):
            return val.date()
        if isinstance(val, date):
            return val
        raw = str(val).strip().replace("/", "-").replace(".", "-")
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y%m%d"):
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(raw).date()
        except ValueError:
            return None

    async def import_attendance(
        self, file, actor_id: int, dry_run: bool = False, limit: int = 2000
    ) -> dict:
        """Excel 批量导入考勤。

        - 表头（中/英均可）：用户ID、用户名、日期、上班时间、下班时间、状态、迟到分钟、
          早退分钟、工时分钟、来源、备注、外勤、外勤地址、外勤备注；
        - 用户与既有记录均批量查询（无逐行 SELECT，导入 1000 行也是常数次查询）；
        - dry_run=True 只做解析与校验，不写库——前端先「预检」再确认导入；
        - 外勤列命中外勤审批单（已通过且日期覆盖）时自动回填 field_work_order_id。
        """
        import io as _io

        from openpyxl import load_workbook

        raw = await file.read()
        if not raw:
            raise ValidationError("上传的表格为空")
        try:
            wb = load_workbook(_io.BytesIO(raw), read_only=True, data_only=True)
        except Exception as exc:  # noqa: BLE001
            raise ValidationError(f"无法解析 Excel 文件：{exc}") from exc
        try:
            ws = wb.active
            grid = [list(r) for r in ws.iter_rows(values_only=True)]
        finally:
            wb.close()
        if not grid:
            raise ValidationError("表格为空")
        header = [
            str(c).strip().lower().replace(" ", "") if c is not None else "" for c in grid[0]
        ]
        idx = {name: i for i, name in enumerate(header)}

        def get(row, *names):
            for n in names:
                i = idx.get(n)
                if i is not None and i < len(row):
                    v = row[i]
                    if v is not None and str(v).strip() != "":
                        return v
            return None

        errors: list[str] = []
        parsed: list[dict] = []
        user_ids: set[int] = set()
        usernames: set[str] = set()
        rows_seen = 0

        for n, row in enumerate(grid[1:], start=2):
            if all(c is None or str(c).strip() == "" for c in row):
                continue
            rows_seen += 1
            if len(parsed) >= limit:
                errors.append(f"单次最多导入 {limit} 行，其余行已忽略")
                break
            try:
                uid_raw = get(row, "用户id", "user_id", "uid")
                uname_raw = get(row, "用户名", "用户", "username", "账号")
                if uid_raw is None and not uname_raw:
                    errors.append(f"第 {n} 行：缺少用户（用户ID 或 用户名）")
                    continue

                day = self._import_day(get(row, "日期", "date", "day"))
                if day is None:
                    errors.append(f"第 {n} 行：日期格式错误 {get(row, '日期', 'date', 'day')}")
                    continue

                status = self._import_status(get(row, "状态", "status"))
                if status is None:
                    errors.append(
                        f"第 {n} 行：状态无法识别 {get(row, '状态', 'status')}"
                        f"（可用：{'/'.join(self.IMPORT_STATUSES)} 或中文）"
                    )
                    continue

                check_in_t = self._import_time(get(row, "上班时间", "上班", "check_in", "上班打卡"))
                check_out_t = self._import_time(get(row, "下班时间", "下班", "check_out", "下班打卡"))
                if check_in_t and check_out_t and check_out_t <= check_in_t:
                    errors.append(f"第 {n} 行：下班时间必须晚于上班时间")
                    continue

                def _num(*names, default=0):
                    v = get(row, *names)
                    if v is None:
                        return default
                    try:
                        return int(float(v))
                    except (TypeError, ValueError):
                        raise ValueError(f"{'/'.join(names)} 不是数字：{v}") from None

                parsed.append({
                    "row": n,
                    "user_id": int(uid_raw) if uid_raw is not None else None,
                    "username": str(uname_raw).strip() if uname_raw else None,
                    "day": day,
                    "check_in": datetime.combine(day, check_in_t) if check_in_t else None,
                    "check_out": datetime.combine(day, check_out_t) if check_out_t else None,
                    "status": status,
                    "late_minutes": _num("迟到分钟", "迟到", "late_minutes", "late"),
                    "early_minutes": _num("早退分钟", "早退", "early_minutes", "early"),
                    "work_minutes": _num("工时分钟", "工时", "work_minutes"),
                    "source": str(get(row, "来源", "source") or "import"),
                    "note": str(get(row, "备注", "note", "说明") or "").strip(),
                    "is_field_work": self._import_bool(
                        get(row, "外勤", "是否外勤", "is_field_work")
                    ),
                    "field_work_address": str(
                        get(row, "外勤地址", "field_work_address") or ""
                    ).strip(),
                    "field_work_note": str(
                        get(row, "外勤备注", "field_work_note") or ""
                    ).strip(),
                })
                item = parsed[-1]
                if item["user_id"]:
                    user_ids.add(item["user_id"])
                elif item["username"]:
                    usernames.add(item["username"])
            except ValueError as exc:
                errors.append(f"第 {n} 行：{exc}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"第 {n} 行：{exc}")

        # ---- 批量解析用户（2 次查询覆盖全部行） ----
        user_map: dict[int, User] = {}
        if user_ids:
            res = await self.session.execute(select(User).where(User.id.in_(user_ids)))
            user_map = {u.id: u for u in res.scalars().all()}
        if usernames:
            res = await self.session.execute(select(User).where(User.username.in_(usernames)))
            for u in res.scalars().all():
                user_map.setdefault(u.id, u)
        id_by_name = {u.username: u.id for u in user_map.values()}
        for item in parsed:
            uid = item["user_id"] or id_by_name.get(item["username"] or "")
            if not uid or uid not in user_map:
                errors.append(f"第 {item['row']} 行：未找到用户 {item['username'] or item['user_id']}")
                item["invalid"] = True
            else:
                item["resolved_user_id"] = uid

        valid = [i for i in parsed if not i.get("invalid")]
        linked_field_work = 0
        created = updated = 0

        if valid:
            days = [i["day"] for i in valid]
            uids = sorted({i["resolved_user_id"] for i in valid})
            # 批量取既有记录（避免逐行 get_by_day）
            res = await self.session.execute(
                select(Attendance).where(
                    Attendance.user_id.in_(uids),
                    Attendance.day >= min(days),
                    Attendance.day <= max(days),
                )
            )
            existing = {(r.user_id, r.day): r for r in res.scalars().all()}
            # 批量取已通过的外勤单，按 (user, day) 展开
            orders = await self.fieldwork.approved_covering(
                start=min(days), end=max(days), user_ids=uids
            )
            order_by_key: dict[tuple[int, date], FieldWorkOrder] = {}
            for o in orders:
                d = o.start_date
                while d <= o.end_date:
                    order_by_key.setdefault((o.user_id, d), o)
                    d = d + timedelta(days=1)

            for item in valid:
                if item.get("invalid"):
                    continue
                uid = item["resolved_user_id"]
                day = item["day"]
                order = order_by_key.get((uid, day))
                if order or item["is_field_work"]:
                    linked_field_work += 1
                rec = existing.get((uid, day))
                values = {
                    "check_in": item["check_in"],
                    "check_out": item["check_out"],
                    "status": item["status"],
                    "late_minutes": item["late_minutes"],
                    "early_minutes": item["early_minutes"],
                    "work_minutes": item["work_minutes"],
                    "source": "import",
                    "note": item["note"],
                    "is_field_work": bool(item["is_field_work"] or order),
                    "field_work_order_id": order.id if order else None,
                    "field_work_address": item["field_work_address"]
                    or (order.address if order else None),
                    "field_work_note": item["field_work_note"] or None,
                }
                if rec is None:
                    existing[(uid, day)] = Attendance(user_id=uid, day=day, **values)
                    self.session.add(existing[(uid, day)])
                    created += 1
                else:
                    for k, v in values.items():
                        setattr(rec, k, v)
                    updated += 1

            if not dry_run:
                await self.session.commit()
            else:
                await self.session.rollback()

        return {
            "dry_run": dry_run,
            "total": rows_seen,
            "created": created,
            "updated": updated,
            "linked_field_work": linked_field_work,
            "errors": errors[:50],
        }

    # ---- 外勤申请（外勤关联闭环） ----
    @staticmethod
    def _fieldwork_out(item: FieldWorkOrder) -> dict:
        user = getattr(item, "user", None)
        return {
            "id": item.id,
            "user_id": item.user_id,
            "user_name": (user.full_name or user.username) if user else f"#{item.user_id}",
            "start_date": item.start_date,
            "end_date": item.end_date,
            "address": item.address or "",
            "purpose": item.purpose or "",
            "remark": item.remark or "",
            "status": item.status,
            "approver_id": item.approver_id,
            "approver_name": "",
            "review_comment": item.review_comment or "",
            "reviewed_at": item.reviewed_at,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }

    async def list_field_work(
        self, *, user_id: int | None = None, status: str | None = None,
        start: date | None = None, end: date | None = None,
        offset: int = 0, limit: int = 50,
    ) -> dict:
        items = await self.fieldwork.list(
            user_id=user_id, status=status, start=start, end=end, offset=offset, limit=limit
        )
        rows = [self._fieldwork_out(i) for i in items]
        approver_ids = {r["approver_id"] for r in rows if r["approver_id"]}
        if approver_ids:
            res = await self.session.execute(
                select(User.id, User.username, User.full_name).where(User.id.in_(approver_ids))
            )
            names = {r[0]: (r[2] or r[1]) for r in res.all()}
            for r in rows:
                r["approver_name"] = names.get(r["approver_id"] or 0, "")
        return {
            "items": rows,
            "total": await self.fieldwork.count(
                user_id=user_id, status=status, start=start, end=end
            ),
            "offset": offset,
            "limit": limit,
        }

    async def create_field_work(self, actor: User, payload: dict) -> FieldWorkOrder:
        start_d = payload.get("start_date")
        end_d = payload.get("end_date")
        if not start_d or not end_d:
            raise ValidationError("请选择外勤起止日期")
        if end_d < start_d:
            raise ValidationError("结束日期不能早于开始日期")
        if (end_d - start_d).days > 90:
            raise ValidationError("单次外勤申请最长 90 天")
        if not (payload.get("address") or "").strip():
            raise ValidationError("请填写外勤地点")
        # 同人重叠校验：待审批/已通过的申请不允许区间重叠
        overlapping = await self.fieldwork.list(
            user_id=actor.id, start=start_d, end=end_d, limit=20
        )
        for o in overlapping:
            if o.status in ("pending", "approved"):
                raise ConflictError(
                    f"该日期区间已有{('待审批' if o.status == 'pending' else '已通过')}"
                    f"的外勤申请（{o.start_date} ~ {o.end_date}）"
                )
        return await self.fieldwork.create(
            FieldWorkOrder(
                user_id=actor.id,
                start_date=start_d,
                end_date=end_d,
                address=str(payload.get("address") or "").strip(),
                purpose=str(payload.get("purpose") or "").strip(),
                remark=str(payload.get("remark") or "").strip(),
            )
        )

    async def review_field_work(
        self, order_id: int, reviewer: User, payload: dict
    ) -> FieldWorkOrder:
        item = await self.fieldwork.get(order_id)
        if not item:
            raise NotFoundError("外勤申请不存在")
        if item.status != "pending":
            raise ValidationError("该外勤申请已处理")
        if item.user_id == reviewer.id and reviewer.role.name != "admin":
            raise ForbiddenError("不能审批自己的外勤申请")
        approve = bool(payload.get("approve"))
        item.status = "approved" if approve else "rejected"
        item.approver_id = reviewer.id
        item.review_comment = str(payload.get("comment") or "")
        item.reviewed_at = _now()
        await self.session.commit()
        await self.session.refresh(item)
        # 通知申请人（站内信 + SSE 实时）
        await NotificationService(self.session, event_bus=self.bus).notify(
            item.user_id,
            "attendance",
            f"外勤申请{'已通过' if approve else '已驳回'}",
            (
                f"{item.start_date} ~ {item.end_date} {item.address}"
                + (f"：{item.review_comment}" if item.review_comment else "")
            ),
            "/attendance",
        )
        return item

    # ---- 考勤异常预警 ----
    async def alerts(
        self, *, start: date, end: date, threshold: int = 3, limit: int = 200
    ) -> dict:
        """按日期区间扫描考勤异常，返回可直接渲染的预警列表。

        覆盖 7 类异常：缺勤 / 未打下班卡 / 迟到频繁 / 早退频繁 / 夜间打卡 /
        外勤无审批单 / 连续缺勤。所有聚合在 Python 侧完成，SQLite 与 PG 行为一致。
        """
        if end < start:
            raise ValidationError("结束日期不能早于开始日期")
        if (end - start).days > 92:
            raise ValidationError("预警扫描区间最长 92 天")
        threshold = max(1, min(int(threshold or 3), 30))
        settings = await self.get_settings()
        records = await self.repo.list_range(start=start, end=end, limit=10000)
        res = await self.session.execute(
            select(User.id, User.username, User.full_name).where(User.is_active.is_(True))
        )
        users = {r[0]: (r[1], r[2] or r[1]) for r in res.all()}

        # 免出勤依据：已批准请假 + 已通过外勤单
        res = await self.session.execute(
            select(LeaveRequest.user_id, LeaveRequest.start_date, LeaveRequest.end_date).where(
                LeaveRequest.status == "approved",
                LeaveRequest.start_date <= end,
                LeaveRequest.end_date >= start,
            )
        )
        leaves = [(r[0], r[1], r[2]) for r in res.all()]
        orders = await self.fieldwork.approved_covering(start=start, end=end)

        def _covered_days(pool) -> set[tuple[int, date]]:
            """把 (user, 起, 止) 池展开成 (user, day) 集合：逐人逐日判定从 O(池) 降为 O(1)。"""
            out: set[tuple[int, date]] = set()
            for u, s0, e0 in pool:
                d = max(s0, start)   # 裁剪到扫描区间，避免超长区间展开
                last = min(e0, end)
                while d <= last:
                    out.add((u, d))
                    d += timedelta(days=1)
            return out

        excused_days = _covered_days(leaves) | _covered_days(
            [(o.user_id, o.start_date, o.end_date) for o in orders]
        )
        expected_days = [
            d for d in _daterange(start, end) if d.isoweekday() in (settings.workdays or [1, 2, 3, 4, 5])
        ]
        by_user: dict[int, list[Attendance]] = {}
        for r in records:
            by_user.setdefault(r.user_id, []).append(r)

        alerts: list[dict] = []
        late_counter: dict[int, int] = {}
        early_counter: dict[int, int] = {}
        absent_streak: dict[int, int] = {}

        # 1) 逐记录异常：未打下班卡 / 夜间打卡 / 外勤无审批单 / 迟到 / 早退
        for rec in records:
            name = users.get(rec.user_id, (f"#{rec.user_id}", f"用户#{rec.user_id}"))[1]
            past_day = rec.day < _attendance_now().date() or (
                rec.day == _attendance_now().date()
                and _attendance_now().time() > _parse_hhmm(settings.work_end, "18:00")
            )
            if rec.check_in and not rec.check_out and past_day:
                alerts.append({
                    "type": "missing_checkout", "level": "medium", "user_id": rec.user_id,
                    "user_name": name, "day": rec.day, "count": 1,
                    "message": f"{name} {rec.day} 只有上班卡、没有下班卡",
                })
            for point in (rec.check_in, rec.check_out):
                if point and (point.hour >= 22 or point.hour < 5):
                    alerts.append({
                        "type": "night_clock", "level": "low", "user_id": rec.user_id,
                        "user_name": name, "day": rec.day, "count": 1,
                        "message": f"{name} {rec.day} 在非工作时段打卡（{point:%H:%M}）",
                    })
                    break
            if rec.is_field_work and not rec.field_work_order_id:
                alerts.append({
                    "type": "field_no_order", "level": "medium", "user_id": rec.user_id,
                    "user_name": name, "day": rec.day, "count": 1,
                    "message": f"{name} {rec.day} 外勤打卡但没有关联的外勤审批单",
                })
            if rec.late_minutes > 0:
                late_counter[rec.user_id] = late_counter.get(rec.user_id, 0) + 1
            if rec.early_minutes > 0:
                early_counter[rec.user_id] = early_counter.get(rec.user_id, 0) + 1

        # 2) 应出勤未出勤（无记录且无请假/外勤）+ 连续缺勤
        for uid, (username, name) in users.items():
            days_with_record = {r.day for r in by_user.get(uid, [])}
            streak = 0
            for day in expected_days:
                if day > _attendance_now().date():
                    streak = 0
                    continue  # 未来工作日不判缺勤
                if day in days_with_record:
                    streak = 0
                    continue
                if (uid, day) in excused_days:
                    streak = 0
                    continue
                streak += 1
                alerts.append({
                    "type": "absent", "level": "high", "user_id": uid, "user_name": name,
                    "day": day, "count": 1,
                    "message": f"{name} {day} 应出勤但无打卡记录，且无请假/外勤单",
                })
                if streak == threshold:
                    alerts.append({
                        "type": "long_absent", "level": "high", "user_id": uid,
                        "user_name": name, "period": str(day), "count": streak,
                        "message": f"{name} 已连续 {streak} 个工作日无考勤记录",
                    })

        for uid, cnt in late_counter.items():
            if cnt >= threshold:
                name = users.get(uid, (f"#{uid}", f"用户#{uid}"))[1]
                alerts.append({
                    "type": "late_frequent", "level": "medium", "user_id": uid,
                    "user_name": name, "count": cnt,
                    "message": f"{name} 在 {start} ~ {end} 迟到 {cnt} 次（≥{threshold}）",
                })
        for uid, cnt in early_counter.items():
            if cnt >= threshold:
                name = users.get(uid, (f"#{uid}", f"用户#{uid}"))[1]
                alerts.append({
                    "type": "early_frequent", "level": "medium", "user_id": uid,
                    "user_name": name, "count": cnt,
                    "message": f"{name} 在 {start} ~ {end} 早退 {cnt} 次（≥{threshold}）",
                })

        level_rank = {"high": 0, "medium": 1, "low": 2}
        alerts.sort(key=lambda a: (level_rank.get(a["level"], 3), a["user_name"]))
        by_type: dict[str, int] = {}
        for a in alerts:
            by_type[a["type"]] = by_type.get(a["type"], 0) + 1
        return {
            "start": start,
            "end": end,
            "threshold": threshold,
            "checked_users": len(users),
            "total": len(alerts),
            "by_type": [{"type": t, "count": c} for t, c in sorted(by_type.items())],
            "alerts": alerts[:limit],
        }

    async def notify_alerts(
        self, *, start: date | None = None, end: date | None = None,
        threshold: int = 3, limit: int = 100,
    ) -> dict:
        """把当前预警汇总推送给具备 att:manage 的在岗用户（站内信 + SSE）。"""
        start = start or (_attendance_now().date() - timedelta(days=7))
        end = end or _attendance_now().date()
        data = await self.alerts(start=start, end=end, threshold=threshold, limit=limit)
        if not data["total"]:
            return {"alert_count": 0, "notified_users": 0}
        res = await self.session.execute(
            select(User.id)
            .join(Role, Role.id == User.role_id)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .where(Permission.code == "att:manage", User.is_active.is_(True))
            .distinct()
        )
        targets = [r[0] for r in res.all()]
        if not targets:
            return {"alert_count": data["total"], "notified_users": 0}
        top = "；".join(a["message"] for a in data["alerts"][:3])
        for uid in targets:
            await NotificationService(self.session, event_bus=self.bus).notify(
                uid,
                "attendance",
                f"考勤异常预警：{data['total']} 条",
                f"{start} ~ {end} 共 {data['total']} 条异常。{top}"
                + ("……" if data["total"] > 3 else ""),
                "/attendance",
            )
        return {"alert_count": data["total"], "notified_users": len(targets)}

    # ---- 加班 ----
    async def create_overtime(self, user_id: int, payload: dict) -> OvertimeRequest:
        day = payload.get("day")
        hours = float(payload.get("hours") or 0)
        if hours <= 0 or hours > 24:
            raise ValidationError("加班时长必须在 0-24 小时之间")
        if day and day > ( _attendance_now().date() + timedelta(days=1) ):
            raise ValidationError("不能为未来日期申请加班")
        pending = await self.overtime.list(user_id=user_id, status="pending", limit=50)
        if any(p.day == day for p in pending):
            raise ConflictError("该日期已有待审批的加班申请")
        return await self.overtime.create(
            OvertimeRequest(user_id=user_id, day=day, hours=hours, reason=payload.get("reason") or "")
        )

    async def list_overtime(
        self, *, user_id: int | None = None, status: str | None = None,
        offset: int = 0, limit: int = 50,
    ) -> tuple[list[OvertimeRequest], int]:
        items = await self.overtime.list(user_id=user_id, status=status, offset=offset, limit=limit)
        total = await self.overtime.count(user_id=user_id, status=status)
        return items, total

    async def review_overtime(
        self, ot_id: int, reviewer: User, payload: dict
    ) -> OvertimeRequest:
        item = await self.overtime.get(ot_id)
        if not item:
            raise NotFoundError("加班申请不存在")
        if item.status != "pending":
            raise ValidationError("该加班申请已处理")
        if item.user_id == reviewer.id and reviewer.role.name != "admin":
            raise ForbiddenError("不能审批自己的加班申请")
        item.status = "approved" if payload.get("approve") else "rejected"
        item.approver_id = reviewer.id
        item.review_comment = payload.get("comment") or ""
        item.reviewed_at = _now()
        # 复用 leave 的刷新语义
        await self.session.commit()
        await self.session.refresh(item)
        return item


# =========================================================================
# ---------- 审批委托（代审） ----------
# =========================================================================
def _to_utc_naive(dt: datetime) -> datetime:
    """入参统一成 naive UTC 存储（active_delegations 用 naive UTC 比较）。"""
    if dt.tzinfo is None:
        dt = dt.astimezone()  # 无时区 → 按本地时间解释
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _to_local_naive(dt: datetime) -> datetime:
    """库里的 naive UTC → 本地时间供展示。"""
    if dt is None:
        return dt
    return dt.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)


class DelegationService:
    """委托/代审：把某时段的审批权交给他人，工作流分派审批人时自动套用。"""

    def __init__(self, session: AsyncSession, *, event_bus: "EventBus | None" = None):
        self.session = session
        self.repo = DelegationRepository(session)
        self.users = UserRepository(session)
        self.bus = event_bus

    def _check_owner(self, item: WorkflowDelegation, actor: User) -> None:
        if item.from_user_id != actor.id and actor.role.name != "admin":
            raise ForbiddenError("只能管理自己的委托")

    async def _decorate(self, items: list) -> list[dict]:
        """批量补全委托人/受托人/流程名（一次查询，避免 N+1）。"""
        if not items:
            return []
        user_ids: set[int] = set()
        def_ids: set[int] = set()
        for d in items:
            user_ids.update({d.from_user_id, d.to_user_id})
            if d.definition_id:
                def_ids.add(d.definition_id)
        names: dict[int, str] = {}
        if user_ids:
            res = await self.session.execute(
                select(User.id, User.username, User.full_name).where(User.id.in_(user_ids))
            )
            names = {r[0]: (r[2] or r[1]) for r in res.all()}
        def_names: dict[int, str] = {}
        if def_ids:
            res = await self.session.execute(
                select(WorkflowDefinition.id, WorkflowDefinition.name).where(
                    WorkflowDefinition.id.in_(def_ids)
                )
            )
            def_names = {r[0]: r[1] for r in res.all()}
        return [
            {
                "id": d.id,
                "from_user_id": d.from_user_id,
                "from_user_name": names.get(d.from_user_id, f"#{d.from_user_id}"),
                "to_user_id": d.to_user_id,
                "to_user_name": names.get(d.to_user_id, f"#{d.to_user_id}"),
                "definition_id": d.definition_id,
                "definition_name": def_names.get(d.definition_id or 0, ""),
                "start_at": _to_local_naive(d.start_at),
                "end_at": _to_local_naive(d.end_at),
                "active": d.active,
                "created_at": d.created_at,
            }
            for d in items
        ]

    async def list(self, *, mine: User, show_all: bool = False) -> list[dict]:
        items = await self.repo.list(None if show_all else mine.id)
        return await self._decorate(items)

    async def get_dict(self, actor: User, did: int) -> dict:
        item = await self.repo.get(did)
        if not item:
            raise NotFoundError("委托不存在")
        self._check_owner(item, actor)
        rows = await self._decorate([item])
        return rows[0]

    async def _validate(self, from_user_id: int, to_user_id: int,
                        start_at: datetime, end_at: datetime, definition_id: int | None,
                        exclude_id: int | None = None) -> None:
        to_user = await self.users.get_by_id(to_user_id)
        if not to_user or not to_user.is_active:
            raise NotFoundError("受托人不存在或已停用")
        if to_user_id == from_user_id:
            raise ValidationError("不能把审批委托给自己")
        if end_at <= start_at:
            raise ValidationError("结束时间必须晚于开始时间")
        if definition_id:
            res = await self.session.execute(
                select(WorkflowDefinition.id).where(WorkflowDefinition.id == definition_id)
            )
            if res.scalar_one_or_none() is None:
                raise NotFoundError("流程定义不存在")
        # 冲突检测：同一委托人、时段重叠、流程范围相交的生效中委托只允许一条
        # （definition_id 为空=全部流程，与任何范围都相交）
        stmt = select(WorkflowDelegation).where(
            WorkflowDelegation.from_user_id == from_user_id,
            WorkflowDelegation.active.is_(True),
            WorkflowDelegation.start_at < end_at,
            WorkflowDelegation.end_at > start_at,
        )
        if exclude_id is not None:
            stmt = stmt.where(WorkflowDelegation.id != exclude_id)
        res = await self.session.execute(stmt)
        for dup in res.scalars().all():
            same_scope = (
                definition_id is None
                or dup.definition_id is None
                or dup.definition_id == definition_id
            )
            if same_scope:
                period = (
                    f"{_to_local_naive(dup.start_at):%m-%d %H:%M} ~ "
                    f"{_to_local_naive(dup.end_at):%m-%d %H:%M}"
                )
                raise ConflictError(f"该时段已有生效中的委托（{period}），请先停用或调整时间")

    async def check_conflicts(self, from_user_id: int, to_user_id: int,
                               start_at: datetime, end_at: datetime,
                               definition_id: int | None,
                               exclude_id: int | None = None) -> list[dict]:
        """预检冲突：返回所有冲突（重叠 + 循环），不抛异常——供前端 dry-run 使用。"""
        conflicts: list[dict] = []
        # 1) 时段重叠冲突（与 _validate 相同逻辑）
        stmt = select(WorkflowDelegation).where(
            WorkflowDelegation.from_user_id == from_user_id,
            WorkflowDelegation.active.is_(True),
            WorkflowDelegation.start_at < end_at,
            WorkflowDelegation.end_at > start_at,
        )
        if exclude_id is not None:
            stmt = stmt.where(WorkflowDelegation.id != exclude_id)
        res = await self.session.execute(stmt)
        for dup in res.scalars().all():
            same_scope = (
                definition_id is None
                or dup.definition_id is None
                or dup.definition_id == definition_id
            )
            if same_scope:
                conflicts.append({
                    "type": "overlap",
                    "message": f"该时段已有生效中的委托（{_to_local_naive(dup.start_at):%m-%d %H:%M} ~ {_to_local_naive(dup.end_at):%m-%d %H:%M}）",
                    "conflict_id": dup.id,
                })
        # 2) 循环检测：A→B 且 B→A 形成死循环
        chain = await self._detect_cycle(from_user_id, to_user_id, start_at, end_at)
        if chain:
            conflicts.append({
                "type": "cycle",
                "message": f"委托循环：{' → '.join(str(u) for u in chain)}",
                "chain": chain,
            })
        return conflicts

    async def _detect_cycle(self, from_user_id: int, to_user_id: int,
                             start_at: datetime, end_at: datetime) -> list[int] | None:
        """检测委托循环：从 to_user_id 出发，追踪委托链能否回到 from_user_id。"""
        visited = {from_user_id}
        current = to_user_id
        chain = [from_user_id, to_user_id]
        max_depth = 10  # 防止无限循环
        for _ in range(max_depth):
            if current == from_user_id:
                return chain  # 找到循环
            if current in visited:
                return None  # 已访问但未回到起点
            visited.add(current)
            # 查找当前用户作为委托人的下一条委托
            res = await self.session.execute(
                select(WorkflowDelegation).where(
                    WorkflowDelegation.from_user_id == current,
                    WorkflowDelegation.active.is_(True),
                    WorkflowDelegation.start_at < end_at,
                    WorkflowDelegation.end_at > start_at,
                )
            )
            next_delegations = res.scalars().all()
            if not next_delegations:
                return None
            # 取第一条（如果有多个分支，只检查第一条）
            current = next_delegations[0].to_user_id
            chain.append(current)
        return None

    async def _notify_delegate(self, *, to_user_id: int, title: str, body: str) -> None:
        """站内信通知受托人（SSE 只覆盖在线用户，站内信保证离线也能看到）。"""
        try:
            await NotificationService(self.session, event_bus=self.bus).notify(
                to_user_id, "workflow", title, body, "/workflows/delegations"
            )
        except Exception:  # noqa: BLE001
            logger.warning("delegation_notify_failed", to_user_id=to_user_id)

    async def create(self, actor: User, payload: dict) -> dict:
        to_user_id = int(payload.get("to_user_id") or 0)
        start_at = _to_utc_naive(payload["start_at"])
        end_at = _to_utc_naive(payload["end_at"])
        definition_id = payload.get("definition_id")
        await self._validate(actor.id, to_user_id, start_at, end_at, definition_id)
        # 循环检测：防止 A→B → B→C → C→A 死循环
        chain = await self._detect_cycle(actor.id, to_user_id, start_at, end_at)
        if chain:
            raise ConflictError(f"委托循环：{' → '.join(str(u) for u in chain)}")
        item = await self.repo.create(
            WorkflowDelegation(
                from_user_id=actor.id,
                to_user_id=to_user_id,
                definition_id=definition_id,
                start_at=start_at,
                end_at=end_at,
                active=bool(payload.get("active", True)),
            )
        )
        rows = await self._decorate([item])
        result = rows[0]
        # 实时通知：委托人和受托人
        if self.bus:
            await self.bus.publish(self.bus.make(
                EventType.WORKFLOW_TASK_ASSIGNED,
                {"delegation_id": item.id, "from_user_id": actor.id, "to_user_id": to_user_id,
                 "definition_id": definition_id, "start_at": _to_utc_naive(item.start_at).isoformat(),
                 "end_at": _to_utc_naive(item.end_at).isoformat()},
                user_ids=[to_user_id]
            ))
        # 站内信：SSE 只覆盖在线用户，站内信保证离线也能看到
        await self._notify_delegate(
            to_user_id=to_user_id,
            title="收到新的审批委托",
            body=f"{result['from_user_name']} 已将审批权委托给你"
                 f"（{_to_local_naive(item.start_at):%Y-%m-%d %H:%M} ~ "
                 f"{_to_local_naive(item.end_at):%Y-%m-%d %H:%M}）",
        )
        return rows[0]

    async def update(self, actor: User, did: int, payload: dict) -> dict:
        item = await self.repo.get(did)
        if not item:
            raise NotFoundError("委托不存在")
        self._check_owner(item, actor)
        old_to_user_id = item.to_user_id
        to_user_id = int(payload.get("to_user_id", item.to_user_id))
        start_at = _to_utc_naive(payload["start_at"]) if payload.get("start_at") else item.start_at
        end_at = _to_utc_naive(payload["end_at"]) if payload.get("end_at") else item.end_at
        definition_id = (
            payload["definition_id"] if "definition_id" in payload else item.definition_id
        )
        await self._validate(
            item.from_user_id, to_user_id, start_at, end_at, definition_id,
            exclude_id=item.id,
        )
        item.to_user_id = to_user_id
        item.start_at = start_at
        item.end_at = end_at
        item.definition_id = definition_id
        if payload.get("active") is not None:
            item.active = bool(payload["active"])
        item = await self.repo.update(item)
        rows = await self._decorate([item])
        result = rows[0]
        # 实时通知：旧受托人和新受托人（如果变更）
        if self.bus:
            notify_users = set()
            if to_user_id != old_to_user_id:
                notify_users.add(old_to_user_id)
            notify_users.add(to_user_id)
            if notify_users:
                await self.bus.publish(self.bus.make(
                    EventType.WORKFLOW_TASK_ASSIGNED,
                    {"delegation_id": item.id, "from_user_id": item.from_user_id, "to_user_id": to_user_id,
                     "definition_id": definition_id, "start_at": _to_utc_naive(item.start_at).isoformat(),
                     "end_at": _to_utc_naive(item.end_at).isoformat(), "updated": True},
                    user_ids=list(notify_users)
                ))
        if to_user_id != old_to_user_id:
            await self._notify_delegate(
                to_user_id=to_user_id,
                title="收到新的审批委托",
                body="该委托由本次修改转入你的名下，请及时处理相关审批。",
            )
        return rows[0]

    async def delete(self, actor: User, did: int) -> None:
        item = await self.repo.get(did)
        if not item:
            raise NotFoundError("委托不存在")
        self._check_owner(item, actor)
        to_user_id = item.to_user_id
        await self.repo.delete(item)
        # 站内信：受托人需要知道委托已取消
        await self._notify_delegate(
            to_user_id=to_user_id,
            title="审批委托已取消",
            body="一条你名下的委托已被删除，相关审批将回到委托人处理。",
        )
        # 实时通知：受托人
        if self.bus:
            await self.bus.publish(self.bus.make(
                EventType.WORKFLOW_TASK_ASSIGNED,
                {"delegation_id": did, "from_user_id": item.from_user_id, "to_user_id": to_user_id,
                 "definition_id": item.definition_id, "deleted": True},
                user_ids=[to_user_id]
            ))


# =========================================================================
# ---------- 报销单（接入工作流） ----------
# =========================================================================
EXPENSE_WF_CODE = "expense-claim"  # 种子里预置的报销审批流程编码


class ExpenseService:
    """报销：草稿 → 提交（发起审批流）→ 通过/驳回（由流程回写）→ 打款。"""

    def __init__(self, session: AsyncSession, *, event_bus: "EventBus | None" = None):
        self.session = session
        self.repo = ExpenseRepository(session)
        self.bus = event_bus

    @staticmethod
    def _user_name(claim: ExpenseClaim) -> str:
        user = getattr(claim, "user", None)
        return (user.full_name or user.username) if user else f"#{claim.user_id}"

    async def decorate(self, claim: ExpenseClaim) -> dict:
        data = {
            "id": claim.id,
            "code": claim.code,
            "user_id": claim.user_id,
            "user_name": self._user_name(claim),
            "claim_type": claim.claim_type,
            "amount": float(claim.amount or 0),
            "occur_date": claim.occur_date,
            "description": claim.description,
            "attachments": claim.attachments or [],
            "status": claim.status,
            "workflow_instance_id": claim.workflow_instance_id,
            "workflow_code": "",
            "approver_id": claim.approver_id,
            "approver_name": "",
            "review_comment": claim.review_comment or "",
            "reviewed_at": claim.reviewed_at,
            "paid_at": claim.paid_at,
            "created_at": claim.created_at,
            "updated_at": claim.updated_at,
        }
        if claim.workflow_instance_id:
            res = await self.session.execute(
                select(WorkflowInstance.code).where(WorkflowInstance.id == claim.workflow_instance_id)
            )
            data["workflow_code"] = res.scalar_one_or_none() or ""
        if claim.approver_id:
            res = await self.session.execute(
                select(User.username, User.full_name).where(User.id == claim.approver_id)
            )
            row = res.first()
            data["approver_name"] = (row[1] or row[0]) if row else f"#{claim.approver_id}"
        return data

    async def list(self, *, user_id: int | None, status: str | None, month: str | None,
                   q: str | None, offset: int = 0, limit: int = 50) -> dict:
        items = await self.repo.list(
            user_id=user_id, status=status, month=month, q=q, offset=offset, limit=limit
        )
        return {
            "items": [await self.decorate(c) for c in items],
            "total": await self.repo.count(user_id=user_id, status=status, month=month, q=q),
            "offset": offset,
            "limit": limit,
            "sum_amount": await self.repo.sum_amount(
                user_id=user_id, status=status, month=month, q=q
            ),
        }

    async def get(self, eid: int) -> ExpenseClaim:
        claim = await self.repo.get(eid)
        if not claim:
            raise NotFoundError("报销单不存在")
        return claim

    async def create(self, user_id: int, payload: dict) -> ExpenseClaim:
        amount = float(payload.get("amount") or 0)
        if amount <= 0:
            raise ValidationError("报销金额必须大于 0")
        if not payload.get("occur_date"):
            raise ValidationError("请选择费用发生日期")
        claim = ExpenseClaim(
            # 占位码保证唯一约束，flush 拿到 id 后回写正式单号
            code="TMP-" + uuid.uuid4().hex[:12],
            user_id=user_id,
            claim_type=payload.get("claim_type") or "daily",
            amount=amount,
            occur_date=payload["occur_date"],
            description=payload.get("description") or "",
            attachments=payload.get("attachments") or [],
        )
        self.session.add(claim)
        await self.session.flush()
        claim.code = f"BX{_attendance_now():%Y%m%d}{claim.id:04d}"
        await self.session.commit()
        await self.session.refresh(claim)
        # 按关系重新取回：响应要读 user 姓名，异步惰性加载会抛 MissingGreenlet
        return (await self.repo.get(claim.id)) or claim

    async def update(self, eid: int, actor: User, payload: dict) -> ExpenseClaim:
        claim = await self.get(eid)
        if claim.user_id != actor.id and actor.role.name != "admin":
            raise ForbiddenError("只能修改自己的报销单")
        if claim.status != "draft":
            raise ValidationError("仅草稿状态可编辑，请先撤回审批")
        if payload.get("amount") is not None:
            amount = float(payload["amount"])
            if amount <= 0:
                raise ValidationError("报销金额必须大于 0")
            claim.amount = amount
        for field in ("claim_type", "occur_date", "description", "attachments"):
            if payload.get(field) is not None:
                setattr(claim, field, payload[field])
        return await self.repo.update(claim)

    async def delete(self, eid: int, actor: User) -> None:
        claim = await self.get(eid)
        if claim.user_id != actor.id and actor.role.name != "admin":
            raise ForbiddenError("只能删除自己的报销单")
        if claim.status not in ("draft", "rejected"):
            raise ValidationError("仅草稿或已驳回的报销单可删除")
        await self.repo.delete(claim)

    async def submit(self, eid: int, actor: User) -> ExpenseClaim:
        """提交报销：以预置的 expense-claim 流程发起实例并回填关联。"""
        claim = await self.get(eid)
        if claim.user_id != actor.id and actor.role.name != "admin":
            raise ForbiddenError("只能提交自己的报销单")
        if claim.status != "draft":
            raise ValidationError("仅草稿状态可提交")
        if not claim.attachments:
            raise ValidationError("请先上传发票/凭证附件（文档中心）")
        res = await self.session.execute(
            select(WorkflowDefinition).where(WorkflowDefinition.code == EXPENSE_WF_CODE)
        )
        definition = res.scalar_one_or_none()
        if not definition or definition.status != "published":
            raise ValidationError("报销审批流程未发布，请联系管理员在流程设计中发布")
        # 额度控制：匹配预算 → 超额直接拒绝；未超额回写额度快照（发起流程前拦截，
        # 避免先建流程实例再回滚）。用量按已提交/已通过/已打款单据实时聚合。
        dept_res = await self.session.execute(
            select(User.department_id).where(User.id == claim.user_id)
        )
        quota = await BudgetService(self.session).check_quota(
            amount=float(claim.amount or 0),
            category=claim.claim_type,
            department_id=dept_res.scalar_one_or_none(),
            occur_date=claim.occur_date,
        )
        if quota.get("exceeded"):
            raise ValidationError(f"提交失败：{quota['message']}")
        if quota.get("has_budget"):
            # 快照语义：remaining = 本单提交后剩余额度（校验时本单仍是草稿、未计入用量）
            claim.budget_id = quota["budget_id"]
            claim.quota_amount = quota.get("quota_amount")
            claim.remaining_quota = round(
                float(quota.get("remaining") or 0) - float(claim.amount or 0), 2
            )
        wf = WorkflowService(self.session, event_bus=self.bus)
        instance = await wf.start_instance(
            claim.user_id,
            WorkflowInstanceCreate(
                definition_id=definition.id,
                title=f"报销审批 · {claim.code}",
                form_data={
                    "claim_code": claim.code,
                    "amount": float(claim.amount or 0),
                    "claim_type": claim.claim_type,
                    "occur_date": claim.occur_date.isoformat(),
                    "description": claim.description,
                },
            ),
        )
        claim.status = "submitted"
        claim.workflow_instance_id = instance.id
        return await self.repo.update(claim)

    async def mark_paid(self, eid: int, actor: User, payload: dict) -> ExpenseClaim:
        claim = await self.get(eid)
        paid = bool(payload.get("paid", True))
        if paid:
            if claim.status != "approved":
                raise ValidationError("仅审批通过的报销单可标记打款")
            claim.status = "paid"
            claim.paid_at = _now()
        else:
            if claim.status != "paid":
                raise ValidationError("该报销单未打款，无需撤销")
            claim.status = "approved"
            claim.paid_at = None
        return await self.repo.update(claim)

    async def stats(self, month: str | None = None) -> dict:
        by_status = await self.repo.group_by_status(month)
        by_type = await self.repo.group_by_type(month)
        total_count = sum(r["count"] for r in by_status)
        total_amount = round(sum(r["amount"] for r in by_status), 2)
        pending = next((r["count"] for r in by_status if r["status"] == "submitted"), 0)
        return {
            "month": month or _attendance_now().strftime("%Y-%m"),
            "total_count": total_count,
            "total_amount": total_amount,
            "pending_count": pending,
            "by_status": [
                {"status": r["status"], "count": r["count"], "amount": round(r["amount"], 2)}
                for r in by_status
            ],
            "by_type": [
                {"status": r["type"], "count": r["count"], "amount": round(r["amount"], 2)}
                for r in by_type
            ],
        }


# =========================================================================
# ---------- 公文（收发文 / 传阅 / 归档） ----------
# =========================================================================
class OfficialDocService:
    def __init__(self, session: AsyncSession, *, event_bus: "EventBus | None" = None):
        self.session = session
        self.repo = OfficialDocRepository(session)
        self.bus = event_bus

    async def list(self, *, direction: str | None, status: str | None, q: str | None,
                   offset: int = 0, limit: int = 50) -> dict:
        items = await self.repo.list(
            direction=direction, status=status, q=q, offset=offset, limit=limit
        )
        return {
            "items": items,
            "total": await self.repo.count(direction=direction, status=status, q=q),
            "offset": offset,
            "limit": limit,
        }

    async def get(self, did: int) -> OfficialDocument:
        doc = await self.repo.get(did)
        if not doc:
            raise NotFoundError("公文不存在")
        return doc

    async def create(self, owner: User, payload: dict) -> OfficialDocument:
        doc_no = (payload.get("doc_no") or "").strip()
        auto_generate = not doc_no
        if auto_generate:
            # 自动生成文号：{方向前缀}-{年份}-{序号:04d}
            direction = payload.get("direction") or "in"
            prefix = "SW" if direction == "in" else "FW"  # 收文SW，发文FW
            year = datetime.now().year
            # 查找当前年度最大序号
            last_seq = await self.repo.get_max_seq(year, prefix)
            seq = last_seq + 1
            doc_no = f"{prefix}-{year}-{seq:04d}"
        else:
            if await self.repo.get_by_doc_no(doc_no):
                raise ConflictError(f"文号 {doc_no} 已存在")
            seq = 0
        
        doc = OfficialDocument(
            doc_no=doc_no,
            seq=seq,
            title=payload["title"],
            direction=payload.get("direction") or "in",
            from_org=payload.get("from_org") or "",
            to_org=payload.get("to_org") or "",
            secrecy=payload.get("secrecy") or "internal",
            content=payload.get("content") or "",
            attachments=payload.get("attachments") or [],
            owner_id=owner.id,
            owner_name=owner.full_name or owner.username,
            status="draft",
        )
        result = await self.repo.create(doc)
        # 记录创建事件
        await self._add_event(result.id, "create", None, "draft", owner, "登记公文")
        return result

    async def update(self, did: int, actor: User, payload: dict) -> OfficialDocument:
        doc = await self.get(did)
        if doc.owner_id != actor.id and actor.role.name != "admin":
            raise ForbiddenError("只能编辑自己登记的公文")
        if doc.status == "archived":
            raise ValidationError("已归档公文不可编辑")
        if payload.get("doc_no") and payload["doc_no"] != doc.doc_no:
            if await self.repo.get_by_doc_no(payload["doc_no"]):
                raise ConflictError(f"文号 {payload['doc_no']} 已存在")
            doc.doc_no = payload["doc_no"]
        for field in ("title", "direction", "from_org", "to_org", "secrecy", "content"):
            if payload.get(field) is not None:
                setattr(doc, field, payload[field])
        if payload.get("attachments") is not None:
            doc.attachments = payload["attachments"]
        return await self.repo.update(doc)

    async def delete(self, did: int, actor: User) -> None:
        doc = await self.get(did)
        if doc.owner_id != actor.id and actor.role.name != "admin":
            raise ForbiddenError("只能删除自己登记的公文")
        if doc.status == "archived":
            raise ValidationError("已归档公文不可删除")
        await self.repo.delete(doc)

    async def circulate(self, actor: User, did: int, payload: dict) -> OfficialDocument:
        """传阅：广播给指定用户（为空则全体），置为 circulated 并记传阅人数。"""
        doc = await self.get(did)
        if doc.owner_id != actor.id and actor.role.name != "admin":
            raise ForbiddenError("只能传阅自己登记的公文")
        old_status = doc.status
        if doc.status == "draft":
            doc.published_at = _now()
        user_ids = [int(u) for u in (payload.get("user_ids") or [])]
        if user_ids:
            res = await self.session.execute(
                select(User.id).where(User.id.in_(user_ids), User.is_active.is_(True))
            )
            targets = [r[0] for r in res.all()]
        else:
            res = await self.session.execute(
                select(User.id).where(User.is_active.is_(True))
            )
            targets = [r[0] for r in res.all()]
        if not targets:
            raise ValidationError("没有可传阅的用户")
        remark = payload.get("remark") or ""
        for uid in targets:
            await NotificationService(self.session, event_bus=self.bus).add(
                uid, "system", f"公文传阅：{doc.doc_no} {doc.title}",
                remark or "请查阅该公文。", "/official-docs",
            )
        doc.status = "circulated"
        doc.read_count = len(targets)
        doc.published_at = doc.published_at or _now()
        # 记录流转事件
        await self._add_event(doc.id, "circulate", old_status, "circulated", actor,
                              remark, {"target_count": len(targets)})
        return await self.repo.update(doc)

    async def archive(self, actor: User, did: int) -> OfficialDocument:
        doc = await self.get(did)
        if doc.owner_id != actor.id and actor.role.name != "admin":
            raise ForbiddenError("只能归档自己登记的公文")
        if doc.status == "draft":
            raise ValidationError("草稿请先发布传阅后再归档")
        old_status = doc.status
        doc.status = "archived"
        doc.archived_at = _now()
        # 记录流转事件
        await self._add_event(doc.id, "archive", old_status, "archived", actor, "归档公文")
        return await self.repo.update(doc)

    async def _add_event(self, doc_id: int, action: str, from_status: str | None,
                         to_status: str | None, actor: User, remark: str = "",
                         meta: dict | None = None) -> None:
        """记录公文流转事件（内部方法）。"""
        from app.models import OfficialDocEvent as Event

        event = Event(
            doc_id=doc_id,
            action=action,
            from_status=from_status,
            to_status=to_status,
            actor_id=actor.id,
            actor_name=actor.full_name or actor.username,
            remark=remark,
            meta=meta or {},
        )
        await OfficialDocEventRepository(self.session).create(event)

    async def get_timeline(self, did: int) -> list[dict]:
        """获取公文流转时间线。"""
        events = await OfficialDocEventRepository(self.session).list_by_doc(did)
        return [
            {
                "id": e.id,
                "action": e.action,
                "from_status": e.from_status,
                "to_status": e.to_status,
                "actor_name": e.actor_name,
                "remark": e.remark,
                "created_at": e.created_at,
            }
            for e in events
        ]

    async def preview_doc_no(self, direction: str = "in") -> dict:
        """预览下一个文号（不创建，供前端实时显示）。"""
        direction = direction if direction in ("in", "out") else "in"
        prefix = "SW" if direction == "in" else "FW"
        year = datetime.now().year
        last_seq = await self.repo.get_max_seq(year, prefix)
        next_seq = last_seq + 1
        return {
            "doc_no": f"{prefix}-{year}-{next_seq:04d}",
            "prefix": prefix,
            "year": year,
            "seq": next_seq,
        }

    async def search(self, q: str, direction: str | None = None,
                     status: str | None = None, offset: int = 0, limit: int = 20) -> dict:
        """全文检索：跨标题/内容/文号/来源单位/目标单位搜索，返回匹配摘要。"""
        if not q or not q.strip():
            return {"items": [], "total": 0, "offset": offset, "limit": limit}
        q = q.strip()
        stmt = select(OfficialDocument).where(
            or_(
                OfficialDocument.doc_no.ilike(f"%{q}%"),
                OfficialDocument.title.ilike(f"%{q}%"),
                OfficialDocument.content.ilike(f"%{q}%"),
                OfficialDocument.from_org.ilike(f"%{q}%"),
                OfficialDocument.to_org.ilike(f"%{q}%"),
                OfficialDocument.owner_name.ilike(f"%{q}%"),
            )
        )
        if direction and direction in ("in", "out"):
            stmt = stmt.where(OfficialDocument.direction == direction)
        if status and status != "all":
            stmt = stmt.where(OfficialDocument.status == status)
        # 相关性排序：标题匹配 > 文号匹配 > 内容匹配
        stmt = stmt.order_by(
            case(
                (OfficialDocument.title.ilike(f"%{q}%"), 0),
                (OfficialDocument.doc_no.ilike(f"%{q}%"), 1),
                else_=2,
            ),
            OfficialDocument.created_at.desc(),
        )
        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(total_stmt)).scalar_one()
        res = await self.session.execute(stmt.offset(offset).limit(limit))
        items = res.scalars().all()
        results = []
        for doc in items:
            # 生成摘要：截取内容前200字符，高亮搜索词
            snippet = doc.content[:200] if doc.content else ""
            if len(doc.content) > 200:
                snippet += "..."
            results.append({
                "id": doc.id,
                "doc_no": doc.doc_no,
                "title": doc.title,
                "direction": doc.direction,
                "status": doc.status,
                "from_org": doc.from_org,
                "to_org": doc.to_org,
                "owner_name": doc.owner_name,
                "created_at": doc.created_at,
                "snippet": snippet,
            })
        return {"items": results, "total": total, "offset": offset, "limit": limit}


# =========================================================================
# ---------- 预算/额度管理 ----------
# =========================================================================
class BudgetService:
    """预算/额度：按「期间 + 部门 + 类别」控制报销可用额度。

    用量口径：不依赖 budgets.used_amount 缓存列（该列无人回写、会永远为 0），
    改为按「已提交 / 已通过 / 已打款」的报销实时聚合——单一可信来源，避免
    草稿/驳回单据污染额度，也无需在审批回调里做加减回滚。
    """

    # 计入额度占用的报销状态（草稿不占、驳回后释放）
    ACTIVE_CLAIM_STATUSES = ("submitted", "approved", "paid")

    def __init__(self, session: AsyncSession):
        self.session = session

    async def _usage_claims(self, start: date, end: date) -> list[tuple[date, str, int | None, float]]:
        """一次查询取窗口内占额度的报销（带申请人部门），供多预算复用，防 N+1。"""
        res = await self.session.execute(
            select(ExpenseClaim.occur_date, ExpenseClaim.claim_type,
                   User.department_id, ExpenseClaim.amount)
            .join(User, User.id == ExpenseClaim.user_id)
            .where(
                ExpenseClaim.status.in_(self.ACTIVE_CLAIM_STATUSES),
                ExpenseClaim.occur_date >= start,
                ExpenseClaim.occur_date <= end,
            )
        )
        return [(r[0], r[1], r[2], float(r[3] or 0)) for r in res.all()]

    @staticmethod
    def _matches(budget: Budget, occur_date: date, claim_type: str | None,
                 department_id: int | None) -> bool:
        """预算与单据是否匹配：日期在期间内，类别/部门（为空表示不限）一致。"""
        if not (budget.start_date <= occur_date <= budget.end_date):
            return False
        if budget.category and budget.category != (claim_type or ""):
            return False
        if budget.department_id and budget.department_id != department_id:
            return False
        return True

    @classmethod
    def _used(cls, budget: Budget, claims: list[tuple]) -> float:
        return round(sum(
            amount for day, ctype, dept, amount in claims
            if cls._matches(budget, day, ctype, dept)
        ), 2)

    def _out(self, budget: Budget, used: float) -> dict:
        return {
            "id": budget.id,
            "name": budget.name,
            "code": budget.code,
            "total_amount": float(budget.total_amount or 0),
            "used_amount": used,
            "remaining": round(float(budget.total_amount or 0) - used, 2),
            "start_date": budget.start_date,
            "end_date": budget.end_date,
            "department_id": budget.department_id,
            "category": budget.category,
            "status": budget.status,
            "created_at": budget.created_at,
            "updated_at": budget.updated_at,
        }

    async def list(self, *, status: str | None = None, department_id: int | None = None,
                   offset: int = 0, limit: int = 50) -> dict:
        stmt = select(Budget).order_by(Budget.created_at.desc())
        if status:
            stmt = stmt.where(Budget.status == status)
        if department_id:
            stmt = stmt.where(Budget.department_id == department_id)
        res = await self.session.execute(stmt.offset(offset).limit(limit))
        budgets = list(res.scalars().all())
        total_stmt = select(func.count()).select_from(Budget)
        if status:
            total_stmt = total_stmt.where(Budget.status == status)
        if department_id:
            total_stmt = total_stmt.where(Budget.department_id == department_id)
        total = (await self.session.execute(total_stmt)).scalar_one()
        # 一次取窗口内全部占额单据，再按预算逐个算用量（否则 50 条 = 50 次查询）
        claims: list[tuple] = []
        if budgets:
            claims = await self._usage_claims(
                min(b.start_date for b in budgets), max(b.end_date for b in budgets)
            )
        return {
            "items": [self._out(b, self._used(b, claims)) for b in budgets],
            "total": total,
            "offset": offset,
            "limit": limit,
        }

    async def create(self, payload: dict) -> Budget:
        if not payload.get("name"):
            raise ValidationError("预算名称不能为空")
        if not payload.get("code"):
            raise ValidationError("预算编码不能为空")
        res = await self.session.execute(select(Budget).where(Budget.code == payload["code"]))
        if res.scalar_one_or_none():
            raise ConflictError(f"预算编码 {payload['code']} 已存在")
        budget = Budget(
            name=payload["name"],
            code=payload["code"],
            total_amount=float(payload.get("total_amount", 0)),
            start_date=payload["start_date"],
            end_date=payload["end_date"],
            department_id=payload.get("department_id"),
            category=payload.get("category"),
            status=payload.get("status", "active"),
        )
        self.session.add(budget)
        await self.session.commit()
        await self.session.refresh(budget)
        return budget

    async def update(self, budget_id: int, payload: dict) -> Budget:
        res = await self.session.execute(select(Budget).where(Budget.id == budget_id))
        budget = res.scalar_one_or_none()
        if not budget:
            raise NotFoundError("预算不存在")
        for field in ("name", "total_amount", "start_date", "end_date", "department_id", "category", "status"):
            if field in payload:
                setattr(budget, field, payload[field])
        await self.session.commit()
        await self.session.refresh(budget)
        return budget

    async def check_quota(self, amount: float, category: str | None,
                          department_id: int | None, occur_date: date) -> dict:
        """检查报销金额是否超出预算额度（用量实时聚合，不读缓存列）。"""
        stmt = select(Budget).where(
            Budget.status == "active",
            Budget.start_date <= occur_date,
            Budget.end_date >= occur_date,
        )
        if department_id:
            stmt = stmt.where(
                (Budget.department_id == department_id) | (Budget.department_id.is_(None))
            )
        if category:
            stmt = stmt.where(
                (Budget.category == category) | (Budget.category.is_(None))
            )
        res = await self.session.execute(stmt)
        budgets = list(res.scalars().all())
        if not budgets:
            return {"has_budget": False, "remaining": None, "message": "无匹配预算"}
        claims = await self._usage_claims(
            min(b.start_date for b in budgets), max(b.end_date for b in budgets)
        )
        # 取最匹配的预算（部门+类别 > 部门 > 全部）
        best = min(budgets, key=lambda b: (
            0 if b.department_id and b.category else
            1 if b.department_id else
            2
        ))
        used = self._used(best, claims)
        remaining = round(float(best.total_amount or 0) - used, 2)
        result = {
            "has_budget": True,
            "budget_id": best.id,
            "quota_amount": float(best.total_amount or 0),
            "remaining": remaining,
            "exceeded": amount > remaining,
            "message": (
                f"超出预算额度 {amount - remaining:.2f} 元（剩余额度 {remaining:.2f}）"
                if amount > remaining else f"剩余额度 {remaining:.2f} 元"
            ),
        }
        return result


# =========================================================================
# ---------- 发票验真 ----------
# =========================================================================
class InvoiceService:
    """发票验真：格式校验 + 唯一性检测 + 统一社会信用代码校验位。"""

    # 统一社会信用代码校验字符集（GB 32100-2015）
    _USCC_CHARS = "0123456789ABCDEFGHJKLMNPQRTUWXY"
    _USCC_WEIGHTS = [1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28]

    def __init__(self, session: AsyncSession):
        self.session = session

    @classmethod
    def verify_uscc(cls, code: str) -> dict:
        """校验统一社会信用代码（18位）。返回校验结果。"""
        if len(code) != 18:
            return {"valid": False, "message": "长度应为18位"}
        if not all(c in cls._USCC_CHARS for c in code):
            return {"valid": False, "message": "包含非法字符"}
        total = sum(cls._USCC_CHARS.index(code[i]) * cls._USCC_WEIGHTS[i] for i in range(17))
        check = cls._USCC_CHARS[(total % 31 + 1) % 31]
        if check != code[17]:
            return {"valid": False, "message": f"校验位错误（应为 {check}）"}
        return {"valid": True, "message": "校验通过"}

    async def verify_invoice(self, invoice_no: str, invoice_code: str | None = None,
                             amount: float | None = None, buyer_tax_no: str | None = None) -> dict:
        """发票验真：格式 + 唯一性 + 买方税号校验。"""
        checks: list[dict] = []
        # 1) 格式校验
        if not invoice_no or len(invoice_no) < 8:
            checks.append({"name": "format", "passed": False, "message": "发票号码长度不足"})
        else:
            checks.append({"name": "format", "passed": True, "message": "格式正确"})
        # 2) 发票代码校验（可选）
        if invoice_code:
            if len(invoice_code) not in (10, 12):
                checks.append({"name": "code_format", "passed": False, "message": "发票代码长度应为10或12位"})
            else:
                checks.append({"name": "code_format", "passed": True, "message": "发票代码格式正确"})
        # 3) 买方税号校验（可选）
        if buyer_tax_no:
            uscc_result = self.verify_uscc(buyer_tax_no)
            checks.append({"name": "buyer_tax_no", **uscc_result})
        # 4) 唯一性检测
        res = await self.session.execute(
            select(ExpenseClaim.id).where(
                ExpenseClaim.description.contains(invoice_no)
            ).limit(1)
        )
        if res.scalar_one_or_none():
            checks.append({"name": "uniqueness", "passed": False, "message": "发票号码已关联其他报销单"})
        else:
            checks.append({"name": "uniqueness", "passed": True, "message": "唯一性检查通过"})
        # 5) 金额一致性（可选）
        if amount is not None and amount <= 0:
            checks.append({"name": "amount", "passed": False, "message": "金额必须大于0"})
        elif amount is not None:
            checks.append({"name": "amount", "passed": True, "message": "金额正确"})

        all_passed = all(c["passed"] for c in checks)
        return {
            "status": "verified" if all_passed else "failed",
            "checks": checks,
        }


# =========================================================================
# ---------- 批量打款 ----------
# =========================================================================
class BatchPaymentService:
    """批量打款：一次性处理多个已通过的报销单，逐条处理并汇总结果。"""

    def __init__(self, session: AsyncSession, *, event_bus: "EventBus | None" = None):
        self.session = session
        self.bus = event_bus

    async def batch_pay(self, expense_ids: list[int], actor: User) -> dict:
        """批量打款：逐条处理，记录成功/失败明细。"""
        results: list[dict] = []
        success_count = 0
        fail_count = 0
        for eid in expense_ids:
            try:
                res = await self.session.execute(
                    select(ExpenseClaim).where(ExpenseClaim.id == eid)
                )
                claim = res.scalar_one_or_none()
                if not claim:
                    results.append({"id": eid, "success": False, "error": "报销单不存在"})
                    fail_count += 1
                    continue
                if claim.status != "approved":
                    results.append({"id": eid, "success": False, "error": f"状态为 {claim.status}，非已通过"})
                    fail_count += 1
                    continue
                claim.status = "paid"
                claim.paid_at = _now()
                await self.session.commit()
                # 通知报销申请人
                await NotificationService(self.session, event_bus=self.bus).notify(
                    claim.user_id, "expense",
                    f"报销单 {claim.code} 已打款",
                    f"您的报销单 {claim.code}（{claim.amount}元）已完成打款。",
                    "/expenses",
                )
                results.append({"id": eid, "success": True, "code": claim.code})
                success_count += 1
            except Exception as exc:  # noqa: BLE001
                await self.session.rollback()
                results.append({"id": eid, "success": False, "error": str(exc)})
                fail_count += 1
        return {
            "total": len(expense_ids),
            "success": success_count,
            "failed": fail_count,
            "results": results,
        }
