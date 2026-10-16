/**
 * 导航解析单元测试（项目首个前端测试）。
 *
 * 为什么需要它：menuModel 的路径解析是「多页签标题 + 面包屑 + 侧边栏高亮」的共同依据，
 * 但它的正确性 tsc 完全查不出来。本次开发中它确实出过两处缺陷：
 *   1) /workflows/designer 被前缀更短的 /workflows 抢先命中，页签标题与面包屑显示成「流程中心」；
 *   2) /workflows/instance/123 无任何菜单精确匹配，导致一级模块解析为 null，侧边栏与面包屑整个空掉。
 * 第 9 节保留了修复前逻辑的对照，防止后续重构再次退化。
 *
 * 运行：npm run test:nav
 * 原理：menuModel.ts 是纯逻辑（唯一运行时依赖是图标注册表），先用 tsc 编译到 .test-build/，
 *       再用 Node 直接执行，无需浏览器或测试框架。
 */
import { buildMenuTree, resolveNav, firstNavigablePath, MENU_ICONS } from "../.test-build/layouts/menuModel.js";

// 与 backend/app/seed.py 的 DEFAULT_MENUS 保持一致（取关键分支）
const M = (id, parent_id, name, path, icon, order, permission_code) => ({
  id, parent_id, name, path, icon, order, permission_code,
});

const MENUS = [
  M(1, null, "工作台", "/", "DashboardOutlined", 1, "dashboard:view"),
  M(2, null, "人事管理", "", "TeamOutlined", 2, "user:view"),
  M(3, 2, "员工管理", "/employees", "TeamOutlined", 1, "user:view"),
  M(4, 2, "部门管理", "/departments", "ApartmentOutlined", 2, "dept:view"),
  M(5, null, "考勤请假", "", "CalendarOutlined", 3, "att:view"),
  M(6, 5, "考勤打卡", "/attendance", "ClockCircleOutlined", 0, "att:view"),
  M(7, 5, "请假审批", "/leave", "CalendarOutlined", 1, "leave:view"),
  M(12, null, "审批工作流", "", "ApartmentOutlined", 5, "wf:view"),
  M(13, 12, "流程中心", "/workflows", "ApartmentOutlined", 1, "wf:view"),
  M(14, 12, "流程设计", "/workflows/designer", "BranchesOutlined", 2, "wf:design"),
  M(15, 12, "表单设计", "/workflows/forms", "FormOutlined", 3, "wf:form"),
  M(16, 12, "流程监控", "/workflows/monitor", "DashboardOutlined", 4, "wf:monitor"),
  M(17, 12, "审批委托", "/workflows/delegations", "SwapOutlined", 5, "wf:view"),
  M(29, null, "消息中心", "/messages", "BellOutlined", 10, "msg:view"),
  M(30, null, "报表中心", "/reports", "BarChartOutlined", 11, "report:view"),
];

const tree = buildMenuTree(MENUS);
let pass = 0, fail = 0;

function eq(actual, expected, label) {
  const a = JSON.stringify(actual), e = JSON.stringify(expected);
  if (a === e) { pass++; console.log("  PASS  " + label); }
  else { fail++; console.log("  FAIL  " + label + "\n        期望 " + e + "\n        实际 " + a); }
}

function nav(path) {
  const r = resolveNav(tree, path);
  return {
    module: r.module?.name ?? null,
    chain: r.chain.map((n) => n.name),
    node: r.node?.name ?? null,
    title: r.title,
  };
}

console.log("=== 1. 菜单树结构 ===");
eq(tree.length, 6, "一级模块 6 个");
eq(tree.map((n) => n.name), ["工作台", "人事管理", "考勤请假", "审批工作流", "消息中心", "报表中心"], "一级模块按 order 排序");
eq(tree.find((n) => n.name === "人事管理").children.map((c) => c.name), ["员工管理", "部门管理"], "人事管理下 2 个子菜单");
eq(tree.find((n) => n.name === "考勤请假").children.map((c) => c.name), ["考勤打卡", "请假审批"], "考勤打卡 order=0 排在前面");
const keys = tree.flatMap((n) => [n.key, ...n.children.map((c) => c.key)]);
eq(keys.length, new Set(keys).size, "Menu key 无重复");
eq(tree.find((n) => n.name === "工作台").key, "/", "有 path 的节点 key 用 path");
eq(tree.find((n) => n.name === "人事管理").key, "group-2", "纯分组节点 key 用 group-<id>");

console.log("=== 2. 精确优先：/workflows/designer 必须命中「流程设计」而非前缀更短的「流程中心」 ===");
eq(nav("/workflows/designer"), { module: "审批工作流", chain: ["审批工作流", "流程设计"], node: "流程设计", title: "流程设计" }, "/workflows/designer");
eq(nav("/workflows/forms"), { module: "审批工作流", chain: ["审批工作流", "表单设计"], node: "表单设计", title: "表单设计" }, "/workflows/forms");
eq(nav("/workflows/monitor"), { module: "审批工作流", chain: ["审批工作流", "流程监控"], node: "流程监控", title: "流程监控" }, "/workflows/monitor");
eq(nav("/workflows/delegations"), { module: "审批工作流", chain: ["审批工作流", "审批委托"], node: "审批委托", title: "审批委托" }, "/workflows/delegations");

console.log("=== 3. 最长前缀回退：/workflows/instance/123 无菜单精确匹配 ===");
eq(nav("/workflows/instance/123"), { module: "审批工作流", chain: ["审批工作流", "流程中心"], node: "流程中心", title: "流程详情" }, "/workflows/instance/123");

console.log("=== 4. 普通二级页 ===");
eq(nav("/workflows"), { module: "审批工作流", chain: ["审批工作流", "流程中心"], node: "流程中心", title: "流程中心" }, "/workflows");
eq(nav("/employees"), { module: "人事管理", chain: ["人事管理", "员工管理"], node: "员工管理", title: "员工管理" }, "/employees");
eq(nav("/attendance"), { module: "考勤请假", chain: ["考勤请假", "考勤打卡"], node: "考勤打卡", title: "考勤打卡" }, "/attendance");

console.log("=== 5. 无子菜单的页面型模块 ===");
eq(nav("/"), { module: "工作台", chain: ["工作台"], node: "工作台", title: "工作台" }, "/ 工作台");
eq(nav("/messages"), { module: "消息中心", chain: ["消息中心"], node: "消息中心", title: "消息中心" }, "/messages");
eq(nav("/reports"), { module: "报表中心", chain: ["报表中心"], node: "报表中心", title: "报表中心" }, "/reports");

console.log("=== 6. 未知路径不崩且给出兜底 ===");
eq(nav("/no-such-page"), { module: null, chain: [], node: null, title: "/no-such-page" }, "/no-such-page");

console.log("=== 7. 点击纯分组模块时进入其第一个可跳转页面 ===");
eq(firstNavigablePath(tree.find((n) => n.name === "人事管理")), "/employees", "人事管理 -> /employees");
eq(firstNavigablePath(tree.find((n) => n.name === "审批工作流")), "/workflows", "审批工作流 -> /workflows");
eq(firstNavigablePath(tree.find((n) => n.name === "消息中心")), "/messages", "消息中心 -> /messages");

console.log("=== 8. 图标注册表覆盖 seed 中用到的全部图标名 ===");
const iconNames = [...new Set(MENUS.map((m) => m.icon).filter(Boolean))];
const missing = iconNames.filter((n) => !MENU_ICONS[n]);
eq(missing, [], "seed 图标全部已注册（缺失: " + JSON.stringify(missing) + "）");

console.log("=== 9. 回归对照：用修复前的旧逻辑跑同样的路径，确认缺陷真实存在 ===");
const oldContains = (node, p) => {
  if (node.path && node.path === p) return true;
  return node.children.some((c) => oldContains(c, p));
};
const oldFindNode = (node, p) => {
  if (node.path && node.path === p) return node;
  for (const c of node.children) { const h = oldFindNode(c, p); if (h) return h; }
  if (node.path && p.startsWith(node.path + "/")) return node;
  return null;
};
const oldChainTo = (node, p, acc) => {
  const next = [...acc, node];
  if (node.path && node.path === p) return next;
  for (const c of node.children) { const h = oldChainTo(c, p, next); if (h) return h; }
  if (node.path && p.startsWith(node.path + "/")) return next;
  return null;
};
function oldNav(p) {
  const mod = tree.find((n) => oldContains(n, p)) ?? null;
  const node = mod ? oldFindNode(mod, p) : null;
  const chain = mod ? (node ? oldChainTo(mod, node.path, []) ?? [mod] : [mod]) : [];
  return { module: mod?.name ?? null, chain: chain.map((n) => n.name), node: node?.name ?? null };
}
const oldDesigner = oldNav("/workflows/designer");
const oldInstance = oldNav("/workflows/instance/123");
console.log("  旧逻辑 /workflows/designer      -> " + JSON.stringify(oldDesigner));
console.log("  新逻辑 /workflows/designer      -> " + JSON.stringify({ module: "审批工作流", chain: ["审批工作流", "流程设计"], node: "流程设计" }));
console.log("  旧逻辑 /workflows/instance/123  -> " + JSON.stringify(oldInstance));
console.log("  新逻辑 /workflows/instance/123  -> " + JSON.stringify({ module: "审批工作流", chain: ["审批工作流", "流程中心"], node: "流程中心" }));
eq(oldDesigner.node, "流程中心", "确认旧逻辑把 /workflows/designer 误判为「流程中心」");
eq(oldInstance.module, null, "确认旧逻辑对 /workflows/instance/123 完全解析不出模块（侧栏/面包屑会空）");

console.log("");
console.log("结果: " + pass + " 通过 / " + fail + " 失败");
process.exit(fail === 0 ? 0 : 1);
