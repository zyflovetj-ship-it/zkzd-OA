import { useMemo } from "react";
import { Menu, type MenuProps } from "antd";
import { MenuFoldOutlined, MenuUnfoldOutlined } from "@ant-design/icons";
import { Button } from "antd";
import { MENU_ICONS, type NavNode } from "./menuModel";

interface Props {
  /** 当前一级模块（决定二级菜单内容） */
  module: NavNode | null;
  selectedPath: string;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onNavigate: (path: string) => void;
  /** 移动端抽屉里不显示折叠按钮 */
  showCollapse?: boolean;
}

function toItems(nodes: NavNode[]): MenuProps["items"] {
  return nodes.map((n) => {
    const Icon = n.icon ? MENU_ICONS[n.icon] : undefined;
    const children = n.children.length ? toItems(n.children) : undefined;
    return {
      key: n.key,
      icon: Icon ? <Icon /> : undefined,
      label: n.name,
      children,
    };
  });
}

export default function SideNav({
  module,
  selectedPath,
  collapsed,
  onToggleCollapse,
  onNavigate,
  showCollapse = true,
}: Props) {
  // 模块有子菜单则展示子菜单；纯页面型模块（工作台/消息中心/报表中心）展示自身
  const nodes = useMemo<NavNode[]>(() => {
    if (!module) return [];
    return module.children.length ? module.children : [module];
  }, [module]);

  return (
    <aside className={"zk-sider" + (collapsed ? " zk-sider--collapsed" : "")}>
      <div className="zk-sider__title">
        {!collapsed ? <span>{module?.name ?? "功能菜单"}</span> : null}
        {collapsed && module?.icon && MENU_ICONS[module.icon]
          ? (() => {
              const Icon = MENU_ICONS[module.icon];
              return <Icon />;
            })()
          : null}
      </div>

      <Menu
        className="zk-sider__menu zk-scroll"
        theme="dark"
        mode="inline"
        inlineCollapsed={collapsed}
        selectedKeys={[selectedPath]}
        defaultOpenKeys={nodes.map((n) => n.key)}
        items={toItems(nodes)}
        onClick={({ key }) => {
          if (typeof key === "string" && key.startsWith("/")) onNavigate(key);
        }}
      />

      {showCollapse ? (
        <div className="zk-sider__foot">
          <Button
            type="text"
            block
            style={{ color: "rgba(255,255,255,.72)" }}
            icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            onClick={onToggleCollapse}
          />
        </div>
      ) : null}
    </aside>
  );
}
