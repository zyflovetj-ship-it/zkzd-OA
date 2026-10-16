"""初始数据：默认角色（含数据范围）、管理员账号、权限点、角色授权与导航菜单。

可重复执行：已存在则跳过，保证本地重启 / 容器重建幂等。
"""
from datetime import datetime

from sqlalchemy import select

from app.core import security
from app.models import (
    Menu,
    Notification,
    Permission,
    Role,
    RolePermission,
    User,
    WorkflowDefinition,
    WorkflowVersion,
)

# 报销单提交时发起的内置流程编码（与 ExpenseService.EXPENSE_WF_CODE 保持一致）
EXPENSE_WF_CODE = "expense-claim"

# (name, description, data_scope)
DEFAULT_ROLES = [
    ("admin", "系统管理员", "all"),
    ("manager", "部门经理", "dept"),
    ("employee", "普通员工", "self"),
]

# (code, name, category, type, description)
DEFAULT_PERMISSIONS = [
    ("dashboard:view", "工作台", "通用", "menu", "查看工作台"),
    ("user:view", "员工管理", "人事管理", "menu", "查看员工列表"),
    ("user:create", "新增员工", "人事管理", "operation", "创建员工账号"),
    ("dept:view", "部门管理", "人事管理", "menu", "查看部门"),
    ("dept:manage", "部门维护", "人事管理", "operation", "维护部门"),
    ("leave:view", "请假审批", "考勤请假", "menu", "查看请假"),
    ("leave:review", "请假审批权", "考勤请假", "operation", "审核请假单"),
    ("ann:view", "公告文档", "公告文档", "menu", "查看公告"),
    ("ann:manage", "公告发布", "公告文档", "operation", "发布公告"),
    ("wf:view", "流程中心", "审批工作流", "menu", "查看流程"),
    ("wf:design", "流程设计", "审批工作流", "menu", "设计流程"),
    ("wf:form", "表单设计", "审批工作流", "menu", "设计表单"),
    ("wf:monitor", "流程监控", "审批工作流", "menu", "查看流程监控看板"),
    ("wf:manage", "流程定义", "审批工作流", "operation", "管理流程定义"),
    ("sig:view", "电子签单", "电子签单", "menu", "查看签单"),
    ("sig:sign", "电子签署", "电子签单", "operation", "执行签署"),
    ("org:role:view", "角色权限", "组织权限", "menu", "查看角色权限"),
    ("org:role:manage", "角色授权", "组织权限", "operation", "配置角色权限"),
    ("org:menu:view", "菜单管理", "组织权限", "menu", "查看菜单"),
    ("org:menu:manage", "菜单配置", "组织权限", "operation", "配置菜单"),
    ("org:ops:view", "运维中心", "组织权限", "menu", "查看运维中心"),
    ("audit:view", "日志中心", "组织权限", "menu", "查看审计日志"),
    ("audit:manage", "日志清理", "组织权限", "operation", "清理审计日志"),
    ("model:view", "建模引擎", "建模引擎", "menu", "查看建模引擎"),
    ("model:manage", "实体建模", "建模引擎", "operation", "维护自定义实体模型"),
    ("model:data:edit", "数据录入", "建模引擎", "operation", "维护实体数据"),
    ("doc:view", "文档中心", "内容引擎", "menu", "查看文档中心"),
    ("doc:upload", "文档上传", "内容引擎", "operation", "上传文档"),
    ("doc:manage", "文档管理", "内容引擎", "operation", "删除文档"),
    ("msg:view", "消息中心", "通用", "menu", "查看消息中心"),
    # 考勤管理：个人打卡用 att:view；全员记录/班次/统计/加班审批需 att:manage
    ("att:view", "考勤打卡", "考勤请假", "menu", "个人打卡与月度考勤"),
    ("att:manage", "考勤管理", "考勤请假", "operation", "全员考勤、班次设置、统计与加班审批"),
    # 报销：个人提交 expense:view；查看全部/打款/导出需 expense:manage
    ("expense:view", "报销管理", "费用报销", "menu", "提交与查看自己的报销单"),
    ("expense:manage", "报销打款", "费用报销", "operation", "查看全部报销、打款与导出"),
    # 公文：收发文登记与传阅
    ("doc:official:view", "公文管理", "公文", "menu", "查看公文"),
    ("doc:official:manage", "公文维护", "公文", "operation", "登记、传阅与归档公文"),
    # 报表中心：组织级聚合（全公司人数/审计总量等）敏感，仅授予 admin + manager，不给 employee
    ("report:view", "报表中心", "报表中心", "menu", "查看统一数据看板"),
]

# 角色 -> 权限码
ROLE_PERMISSIONS = {
    "admin": [p[0] for p in DEFAULT_PERMISSIONS],  # 管理员拥有全部权限
    "manager": [
        "dashboard:view", "user:view", "dept:view", "leave:view", "leave:review",
    "ann:view", "ann:manage", "wf:view", "wf:design", "wf:form", "wf:monitor",
    "sig:view", "sig:sign", "model:view", "model:manage", "model:data:edit",
    "audit:view", "msg:view", "report:view",
        "att:view", "att:manage", "expense:view", "expense:manage",
        "doc:official:view", "doc:official:manage",
    ],
    "employee": [
        "dashboard:view", "user:view", "leave:view", "ann:view",
        "wf:view", "sig:view", "model:view", "model:data:edit",
        "doc:view", "doc:upload", "msg:view",
        "att:view", "expense:view", "doc:official:view",
    ],
}

# (key, name, path, icon, order, permission_code, parent_key)
# path 为空表示分组节点；parent_key=None 表示顶级
DEFAULT_MENUS = [
    ("dashboard", "工作台", "/", "DashboardOutlined", 1, "dashboard:view", None),
    ("hr", "人事管理", "", "TeamOutlined", 2, "user:view", None),
    ("employees", "员工管理", "/employees", "TeamOutlined", 1, "user:view", "hr"),
    ("departments", "部门管理", "/departments", "ApartmentOutlined", 2, "dept:view", "hr"),
    ("attendance", "考勤请假", "", "CalendarOutlined", 3, "att:view", None),
    ("attendance_home", "考勤打卡", "/attendance", "ClockCircleOutlined", 0, "att:view", "attendance"),
    ("leave", "请假审批", "/leave", "CalendarOutlined", 1, "leave:view", "attendance"),
    ("ann", "公告文档", "", "NotificationOutlined", 4, "ann:view", None),
    ("announcements", "公告文档", "/announcements", "NotificationOutlined", 1, "ann:view", "ann"),
    ("docs", "文档中心", "/documents", "FileTextOutlined", 2, "doc:view", "ann"),
    ("official", "公文管理", "/official-docs", "ProfileOutlined", 3, "doc:official:view", "ann"),
    ("wf", "审批工作流", "", "ApartmentOutlined", 5, "wf:view", None),
    ("flow", "流程中心", "/workflows", "ApartmentOutlined", 1, "wf:view", "wf"),
    ("flow_design", "流程设计", "/workflows/designer", "BranchesOutlined", 2, "wf:design", "wf"),
    ("flow_form", "表单设计", "/workflows/forms", "FormOutlined", 3, "wf:form", "wf"),
    ("monitor", "流程监控", "/workflows/monitor", "DashboardOutlined", 4, "wf:monitor", "wf"),
    ("delegations", "审批委托", "/workflows/delegations", "SwapOutlined", 5, "wf:view", "wf"),
    ("sig", "电子签单", "", "FileProtectOutlined", 6, "sig:view", None),
    ("signatures", "电子签单", "/signatures", "FileProtectOutlined", 1, "sig:view", "sig"),
    ("expense", "报销管理", "", "AccountBookOutlined", 7, "expense:view", None),
    ("expenses", "报销单", "/expenses", "AccountBookOutlined", 1, "expense:view", "expense"),
    ("org", "组织权限中心", "", "SafetyOutlined", 8, "org:role:view", None),
    ("roles", "角色权限", "/settings/roles", "SafetyOutlined", 1, "org:role:view", "org"),
    ("menus", "菜单管理", "/settings/menus", "MenuOutlined", 2, "org:menu:view", "org"),
    ("ops", "运维中心", "/settings/ops", "DashboardOutlined", 3, "org:ops:view", "org"),
    ("audit", "日志中心", "/settings/audit", "FileSearchOutlined", 4, "audit:view", "org"),
    ("md", "建模引擎", "", "AppstoreOutlined", 9, "model:view", None),
    ("models", "模型与数据", "/models", "AppstoreOutlined", 1, "model:view", "md"),
    ("messages", "消息中心", "/messages", "BellOutlined", 10, "msg:view", None),
    ("reports", "报表中心", "/reports", "BarChartOutlined", 11, "report:view", None),
]


async def seed_initial_data(session) -> None:
    # ---- 角色 ----
    role_by_name: dict[str, Role] = {}
    for name, desc, scope in DEFAULT_ROLES:
        res = await session.execute(select(Role).where(Role.name == name))
        role = res.scalar_one_or_none()
        if not role:
            role = Role(name=name, description=desc, data_scope=scope)
            session.add(role)
            await session.commit()
        else:
            # 兼容旧库：补充 data_scope 默认值
            if not role.data_scope:
                role.data_scope = scope
                await session.commit()
        role_by_name[name] = role

    # ---- 权限点 ----
    perm_by_code: dict[str, Permission] = {}
    for code, pname, category, ptype, desc in DEFAULT_PERMISSIONS:
        res = await session.execute(select(Permission).where(Permission.code == code))
        perm = res.scalar_one_or_none()
        if not perm:
            perm = Permission(code=code, name=pname, category=category, type=ptype, description=desc)
            session.add(perm)
            await session.commit()
        perm_by_code[code] = perm

    # ---- 角色授权 ----
    for rname, codes in ROLE_PERMISSIONS.items():
        role = role_by_name[rname]
        for code in codes:
            perm = perm_by_code.get(code)
            if not perm:
                continue
            res = await session.execute(
                select(RolePermission).where(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == perm.id,
                )
            )
            if not res.scalar_one_or_none():
                session.add(RolePermission(role_id=role.id, permission_id=perm.id))
        await session.commit()

    # ---- 管理员账号 ----
    res = await session.execute(select(User).where(User.username == "admin"))
    if not res.scalar_one_or_none():
        admin_role = role_by_name["admin"]
        session.add(
            User(
                username="admin",
                full_name="系统管理员",
                email="admin@oa.local",
                hashed_password=security.hash_password("admin123"),
                role_id=admin_role.id,
                is_active=True,
            )
        )
        await session.commit()

    # ---- 导航菜单（按 name+parent 幂等 upsert，重跑 seed 可补齐新增菜单） ----
    existing_map = {
        (m.name, m.parent_id): m.id
        for m in (await session.execute(select(Menu))).scalars().all()
    }
    id_by_key: dict[str, int] = {}
    for key, name, path, icon, order, perm_code, parent_key in DEFAULT_MENUS:
        parent_id = id_by_key.get(parent_key) if parent_key else None
        match = existing_map.get((name, parent_id))
        if match is not None:
            # 已存在：同步 path/icon/order/permission_code，保证改版菜单在旧库上生效
            menu = (await session.execute(select(Menu).where(Menu.id == match))).scalar_one()
            changed = False
            for field, value in (
                ("path", path), ("icon", icon), ("order", order),
                ("permission_code", perm_code),
            ):
                if getattr(menu, field) != value:
                    setattr(menu, field, value)
                    changed = True
            if changed:
                await session.commit()
            id_by_key[key] = menu.id
            continue
        menu = Menu(
            parent_id=parent_id, name=name, path=path, icon=icon,
            order=order, permission_code=perm_code,
        )
        session.add(menu)
        await session.commit()
        await session.refresh(menu)
        id_by_key[key] = menu.id

    # ---- 预置「费用报销审批」流程（报销提交即发起，缺它报销无法提交） ----
    res = await session.execute(
        select(WorkflowDefinition).where(WorkflowDefinition.code == EXPENSE_WF_CODE)
    )
    if res.scalar_one_or_none() is None:
        definition = WorkflowDefinition(
            code=EXPENSE_WF_CODE,
            name="费用报销审批",
            category="expense",
            description="报销单提交后自动发起：审批人通过后单据变为已通过，可再标记打款。",
            icon="AccountBookOutlined",
            status="published",
            current_version=1,
        )
        session.add(definition)
        await session.commit()
        await session.refresh(definition)
        session.add(
            WorkflowVersion(
                definition_id=definition.id,
                version=1,
                graph={
                    "nodes": [
                        {"id": "start", "type": "start", "name": "发起"},
                        {
                            "id": "approve", "type": "approval", "name": "报销审批",
                            "assignee": {"type": "role", "value": "admin"},
                        },
                        {"id": "end", "type": "end", "name": "结束"},
                    ],
                    "edges": [
                        {"source": "start", "target": "approve"},
                        {"source": "approve", "target": "end"},
                    ],
                },
                status="published",
                published_at=datetime.utcnow(),
                remark="内置流程：报销审批（管理员）",
            )
        )
        await session.commit()

    # ---- 示例通知（仅首次无通知时灌入，便于演示；幂等） ----
    if not (await session.execute(select(Notification))).scalars().first():
        admin_user = (
            await session.execute(select(User).where(User.username == "admin"))
        ).scalar_one_or_none()
        if admin_user:
            samples = [
                ("system", "欢迎使用 zk-oa 消息中心", "您可以在此处集中查看待办、审批与系统通知。", ""),
                ("announcement", "新版请假流程已上线", "请假申请现已支持在线提交与审批。", "/announcements"),
                ("workflow", "您有一条待审批流程", "「报销审批」流程等待您的处理。", "/workflows?tab=pending"),
            ]
            for ntype, title, body, link in samples:
                session.add(
                    Notification(
                        user_id=admin_user.id, type=ntype,
                        title=title, body=body, link=link,
                    )
                )
            await session.commit()
