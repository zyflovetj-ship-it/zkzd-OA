import { Suspense, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useRoutes } from "react-router-dom";
import { Breadcrumb, Drawer, Spin, Tooltip } from "antd";
import { HomeOutlined, ReloadOutlined } from "@ant-design/icons";
import { Button } from "antd";
import { useAuth } from "../auth/AuthContext";
import { useIsMobile } from "../hooks/useIsMobile";
import { appRouteObjects } from "../routes";
import RealtimeBridge from "../components/RealtimeBridge";
import BrandHeader from "./BrandHeader";
import SideNav from "./SideNav";
import WorkspaceTabs from "./WorkspaceTabs";
import { buildMenuTree, firstNavigablePath, resolveNav, type NavNode } from "./menuModel";
import { HOME_PATH, WorkspaceProvider, useWorkspace } from "./workspace";

/** 单个页签的内容：用 useRoutes 在指定 path 上求值，从而实现「多实例并存」的页签保活 */
function PaneRoutes({ path }: { path: string }) {
  const element = useRoutes(appRouteObjects, path);
  return (
    <Suspense
      fallback={
        <div style={{ padding: 64, textAlign: "center" }}>
          <Spin tip="页面加载中…" />
        </div>
      }
    >
      {element}
    </Suspense>
  );
}

function ShellInner() {
  const location = useLocation();
  const navigate = useNavigate();
  const { menus } = useAuth();
  const isMobile = useIsMobile();
  const [collapsed, setCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const { tabs, activeKey, openTab, activate, closeTab, closeOthers, closeAll, refresh } =
    useWorkspace();

  const tree = useMemo(() => buildMenuTree(menus || []), [menus]);
  const pathname = location.pathname;
  const nav = useMemo(() => resolveNav(tree, pathname), [tree, pathname]);

  // 路由变化 → 打开/激活对应页签（openTab 幂等，StrictMode 双调用安全）
  useEffect(() => {
    openTab(pathname, nav.title);
  }, [pathname, nav.title, openTab]);

  const go = (path: string) => {
    if (!path) return;
    navigate(path);
    if (isMobile) setDrawerOpen(false);
  };

  const onSelectModule = (node: NavNode) => go(firstNavigablePath(node));

  const onCloseTab = (key: string) => {
    const next = closeTab(key);
    if (next !== pathname) navigate(next);
  };
  const onCloseOthers = (key: string) => {
    closeOthers(key);
    if (key !== pathname) navigate(key);
  };
  const onCloseAll = () => {
    closeAll();
    if (pathname !== HOME_PATH) navigate(HOME_PATH);
  };

  const breadcrumbItems = useMemo(() => {
    const items: { title: React.ReactNode }[] = [
      {
        title: (
          <span className="zk-link" onClick={() => go(HOME_PATH)}>
            <HomeOutlined /> 首页
          </span>
        ),
      },
    ];
    for (const node of nav.chain) {
      const isLast = node === nav.chain[nav.chain.length - 1];
      items.push({
        title: isLast ? (
          <span>{nav.title !== node.name ? nav.title : node.name}</span>
        ) : (
          <span className="zk-link" onClick={() => go(node.path)}>
            {node.name}
          </span>
        ),
      });
    }
    return items;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nav, pathname, isMobile]);

  const sideNav = (
    <SideNav
      module={nav.module}
      selectedPath={pathname}
      collapsed={collapsed}
      onToggleCollapse={() => setCollapsed((v) => !v)}
      onNavigate={go}
      showCollapse={!isMobile}
    />
  );

  return (
    <div className="zk-shell">
      <BrandHeader
        tree={tree}
        activeModuleKey={nav.module?.key ?? null}
        onSelectModule={onSelectModule}
        onOpenMobileMenu={() => setDrawerOpen(true)}
        isMobile={isMobile}
      />

      <WorkspaceTabs
        tabs={tabs}
        activeKey={activeKey}
        onActivate={(key) => {
          activate(key);
          if (key !== pathname) navigate(key);
        }}
        onClose={onCloseTab}
        onCloseOthers={onCloseOthers}
        onCloseAll={onCloseAll}
        onRefresh={refresh}
      />

      <div className="zk-body">
        {!isMobile ? sideNav : null}

        <div className="zk-main">
          <div className="zk-breadcrumb">
            <Breadcrumb items={breadcrumbItems} style={{ flex: 1, minWidth: 0 }} />
            <Tooltip title="刷新当前页">
              <Button
                type="text"
                size="small"
                icon={<ReloadOutlined />}
                onClick={() => refresh(activeKey)}
              />
            </Tooltip>
          </div>

          <div className="zk-content zk-scroll">
            {tabs.map((t) => (
              <div
                key={t.key + "#" + t.nonce}
                className="zk-pane"
                style={{ display: t.key === activeKey ? "block" : "none" }}
              >
                <PaneRoutes path={t.key} />
              </div>
            ))}
          </div>
        </div>
      </div>

      {isMobile ? (
        <Drawer
          placement="left"
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          width={240}
          closable={false}
          styles={{ body: { padding: 0, background: "#033b88" }, header: { display: "none" } }}
        >
          {sideNav}
        </Drawer>
      ) : null}

      <RealtimeBridge />
    </div>
  );
}

export default function AppShell() {
  return (
    <WorkspaceProvider>
      <ShellInner />
    </WorkspaceProvider>
  );
}
