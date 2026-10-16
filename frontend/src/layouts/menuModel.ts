/**
 * 导航模型：把后端下发的扁平菜单列表整理成泛微式「一级模块 + 二级菜单」两层结构，
 * 并提供 path → 标题/面包屑 的解析能力（页签标题与面包屑共用同一份索引）。
 *
 * 路径匹配必须遵循「精确优先、其次最长前缀」：
 *   - /workflows/designer 必须命中「流程设计」，而不是前缀更短的「流程中心」(/workflows)；
 *   - /workflows/instance/123 没有任何菜单精确匹配，必须回退到最长前缀「流程中心」，
 *     否则侧边栏与面包屑会整个空掉。
 */
import type { ComponentType, CSSProperties } from "react";
import {
  AccountBookOutlined,
  ApartmentOutlined,
  AppstoreOutlined,
  BarChartOutlined,
  BellOutlined,
  BranchesOutlined,
  CalendarOutlined,
  ClockCircleOutlined,
  DashboardOutlined,
  FileProtectOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  FormOutlined,
  MenuOutlined,
  NotificationOutlined,
  ProfileOutlined,
  SafetyOutlined,
  SwapOutlined,
  TeamOutlined,
} from "@ant-design/icons";
import type { MenuOut } from "../types";

/** 图标组件可接受的属性（antd 图标支持 style/className） */
export type MenuIconComponent = ComponentType<{ style?: CSSProperties; className?: string }>;

/** 后端只下发图标名字符串，前端按注册表映射为组件 */
export const MENU_ICONS: Record<string, MenuIconComponent> = {
  AccountBookOutlined,
  ApartmentOutlined,
  AppstoreOutlined,
  BarChartOutlined,
  BellOutlined,
  BranchesOutlined,
  CalendarOutlined,
  ClockCircleOutlined,
  DashboardOutlined,
  FileProtectOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  FormOutlined,
  MenuOutlined,
  NotificationOutlined,
  ProfileOutlined,
  SafetyOutlined,
  SwapOutlined,
  TeamOutlined,
};

export interface NavNode {
  id: number;
  /** 有 path 用 path，纯分组用 group-<id>，保证 Menu 的 key 唯一 */
  key: string;
  name: string;
  path: string;
  icon: string;
  permissionCode: string;
  children: NavNode[];
}

/** 动态路由（菜单里没有对应条目）的标题兜底 */
const DYNAMIC_TITLES: Array<[RegExp, string]> = [
  [/^\/workflows\/instance\//, "流程详情"],
];

export function buildMenuTree(menus: MenuOut[]): NavNode[] {
  const childrenOf = (parentId: number | null): NavNode[] =>
    menus
      .filter((m) => (m.parent_id ?? null) === parentId)
      .sort((a, b) => a.order - b.order)
      .map((m) => ({
        id: m.id,
        key: m.path || "group-" + m.id,
        name: m.name,
        path: m.path || "",
        icon: m.icon || "",
        permissionCode: m.permission_code || "",
        children: childrenOf(m.id),
      }));
  return childrenOf(null);
}

/** 精确命中：path 与 pathname 完全相等 */
function findExact(node: NavNode, pathname: string): NavNode | null {
  if (node.path && node.path === pathname) return node;
  for (const child of node.children) {
    const hit = findExact(child, pathname);
    if (hit) return hit;
  }
  return null;
}

/** 最长前缀命中：node.path 是 pathname 的父路径，取 path 最长者 */
function findLongestPrefix(node: NavNode, pathname: string): NavNode | null {
  let best: NavNode | null = null;
  const visit = (n: NavNode) => {
    if (n.path && pathname.startsWith(n.path + "/")) {
      if (!best || n.path.length > best.path.length) best = n;
    }
    for (const c of n.children) visit(c);
  };
  visit(node);
  return best;
}

/** 子树内解析路径：精确优先，其次最长前缀 */
function findNode(module: NavNode, pathname: string): NavNode | null {
  return findExact(module, pathname) ?? findLongestPrefix(module, pathname);
}

/** 某节点子树是否覆盖该路径（含动态子路径） */
function contains(node: NavNode, pathname: string): boolean {
  return findNode(node, pathname) !== null;
}

/** 到「精确路径」的节点链路 */
function chainExact(node: NavNode, pathname: string, acc: NavNode[]): NavNode[] | null {
  const next = [...acc, node];
  if (node.path && node.path === pathname) return next;
  for (const child of node.children) {
    const hit = chainExact(child, pathname, next);
    if (hit) return hit;
  }
  return null;
}

export interface NavResolution {
  /** 当前所属一级模块 */
  module: NavNode | null;
  /** 从一级模块到当前节点的链路，用于面包屑 */
  chain: NavNode[];
  /** 命中的菜单节点 */
  node: NavNode | null;
  /** 页签/面包屑展示的标题 */
  title: string;
}

export function resolveNav(tree: NavNode[], pathname: string): NavResolution {
  const module = tree.find((n) => contains(n, pathname)) ?? null;

  let node: NavNode | null = null;
  let chain: NavNode[] = [];
  if (module) {
    node = findNode(module, pathname);
    // 先按目标节点的 path 求精确链路，再退化为「模块自身」
    chain =
      (node ? chainExact(module, node.path, []) : null) ?? [module];
  }

  // 标题：精确命中的菜单名优先；动态路由（如 /workflows/instance/123）走兜底字典
  let title = node?.name ?? "";
  if (!node || node.path !== pathname) {
    for (const [re, t] of DYNAMIC_TITLES) {
      if (re.test(pathname)) {
        title = t;
        break;
      }
    }
  }
  if (!title) title = module?.name ?? pathname;

  return { module, chain, node, title };
}

/** 一级模块的第一个可跳转页面（用于点击纯分组模块时自动进入其首页） */
export function firstNavigablePath(node: NavNode): string {
  if (node.path) return node.path;
  for (const child of node.children) {
    const p = firstNavigablePath(child);
    if (p) return p;
  }
  return "";
}
