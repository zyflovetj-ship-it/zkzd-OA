import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AutoComplete, Avatar, Badge, Button, Dropdown, Input, Tooltip } from "antd";
import {
  BellOutlined,
  LogoutOutlined,
  MenuOutlined,
  SearchOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { useAuth } from "../auth/AuthContext";
import { msgApi } from "../api/endpoints";
import { MENU_ICONS, type NavNode } from "./menuModel";

interface Props {
  tree: NavNode[];
  activeModuleKey: string | null;
  onSelectModule: (node: NavNode) => void;
  onOpenMobileMenu: () => void;
  isMobile: boolean;
}

/** 扁平化菜单，供全局搜索使用 */
function flatten(nodes: NavNode[], acc: NavNode[] = []): NavNode[] {
  for (const n of nodes) {
    if (n.path) acc.push(n);
    if (n.children.length) flatten(n.children, acc);
  }
  return acc;
}

export default function BrandHeader({
  tree,
  activeModuleKey,
  onSelectModule,
  onOpenMobileMenu,
  isMobile,
}: Props) {
  const navigate = useNavigate();
  const { user, logout } = useAuth();

  const unreadQ = useQuery({
    queryKey: ["notifications", "unread-count"],
    queryFn: () => msgApi.list({ unread_only: true, limit: 1 }),
    refetchInterval: 30_000,
  });
  const unread = unreadQ.data?.unread ?? 0;

  const searchOptions = useMemo(() => {
    const all = flatten(tree);
    return all.map((n) => {
      const Icon = n.icon ? MENU_ICONS[n.icon] : undefined;
      return {
        value: n.path,
        label: (
          <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {Icon ? <Icon style={{ color: "var(--zk-text-tertiary)" }} /> : null}
            <span>{n.name}</span>
            <span style={{ marginLeft: "auto", fontSize: 12, color: "var(--zk-text-tertiary)" }}>
              {n.path}
            </span>
          </span>
        ),
        // 供 AutoComplete 过滤的检索串
        search: n.name + " " + n.path,
      } as { value: string; label: React.ReactNode; search: string };
    });
  }, [tree]);

  const userMenu = {
    items: [
      { key: "name", label: <span style={{ fontWeight: 600 }}>{user?.full_name || user?.username}</span>, disabled: true },
      { type: "divider" as const },
      { key: "profile", icon: <UserOutlined />, label: "个人信息" },
      { key: "logout", icon: <LogoutOutlined />, label: "退出登录", danger: true },
    ],
    onClick: ({ key }: { key: string }) => {
      if (key === "logout") void logout();
    },
  };

  return (
    <header className="zk-header">
      {isMobile ? (
        <Button type="text" icon={<MenuOutlined />} onClick={onOpenMobileMenu} />
      ) : null}

      <div className="zk-header__brand" onClick={() => navigate("/")} title="返回工作台">
        <img className="zk-header__logo" src="/brand/logo-lockup.png" alt="中科智电" />
        <span className="zk-header__divider" />
        <span className="zk-header__product">协同办公平台</span>
      </div>

      {!isMobile ? (
        <nav className="zk-header__nav">
          {tree.map((node) => {
            const Icon = node.icon ? MENU_ICONS[node.icon] : undefined;
            const active = activeModuleKey === node.key;
            return (
              <span
                key={node.key}
                className={"zk-module" + (active ? " zk-module--active" : "")}
                onClick={() => onSelectModule(node)}
              >
                {Icon ? <Icon /> : null}
                {node.name}
              </span>
            );
          })}
        </nav>
      ) : (
        <div style={{ flex: 1, minWidth: 0 }} />
      )}

      <div className="zk-header__actions">
        {!isMobile ? (
          <AutoComplete
            options={searchOptions}
            style={{ width: 200 }}
            filterOption={(input, option) =>
              ((option as unknown as { search: string })?.search ?? "")
                .toLowerCase()
                .includes(input.toLowerCase())
            }
            onSelect={(value: string) => value && navigate(value)}
          >
            <Input
              allowClear
              prefix={<SearchOutlined style={{ color: "var(--zk-text-tertiary)" }} />}
              placeholder="搜索菜单 / 功能"
            />
          </AutoComplete>
        ) : null}

        <Tooltip title="消息中心">
          <Badge count={unread} size="small" offset={[-2, 2]}>
            <Button type="text" icon={<BellOutlined />} onClick={() => navigate("/messages")} />
          </Badge>
        </Tooltip>

        <Dropdown menu={userMenu} placement="bottomRight" trigger={["click"]}>
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              padding: "0 6px",
              height: 36,
              borderRadius: 6,
              cursor: "pointer",
            }}
          >
            <Avatar
              size={28}
              style={{ background: "linear-gradient(135deg, #2ba7d2, #033b88)" }}
            >
              {user?.full_name?.[0] || user?.username?.[0] || "?"}
            </Avatar>
            {!isMobile ? (
              <span style={{ fontSize: 13 }}>{user?.full_name || user?.username}</span>
            ) : null}
          </span>
        </Dropdown>
      </div>
    </header>
  );
}
