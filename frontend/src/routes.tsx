/**
 * 路由表：抽成 RouteObject[] 以便「多页签工作区」用 useRoutes(routes, path)
 * 为每个页签独立渲染匹配结果（这是页签保持状态的关键）。
 *
 * 所有页面按路由懒加载：首屏只下载工作台，其余页面在打开对应页签时才拉取，
 * 避免 echarts / 流程设计器这类重依赖进入首屏包。
 */
import { lazy } from "react";
import type { RouteObject } from "react-router-dom";

const Dashboard = lazy(() => import("./pages/Dashboard"));
const Employees = lazy(() => import("./pages/Employees"));
const Departments = lazy(() => import("./pages/Departments"));
const Leave = lazy(() => import("./pages/Leave"));
const Announcements = lazy(() => import("./pages/Announcements"));
const Workflows = lazy(() => import("./pages/Workflows"));
const FlowCenter = lazy(() => import("./pages/FlowCenter"));
const ProcessDesigner = lazy(() => import("./pages/ProcessDesigner"));
const FormDesigner = lazy(() => import("./pages/FormDesigner"));
const InstanceDetail = lazy(() => import("./pages/InstanceDetail"));
const WorkflowMonitor = lazy(() => import("./pages/WorkflowMonitor"));
const Signatures = lazy(() => import("./pages/Signatures"));
const SettingsRoles = lazy(() => import("./pages/SettingsRoles"));
const SettingsMenus = lazy(() => import("./pages/SettingsMenus"));
const OpsCenter = lazy(() => import("./pages/OpsCenter"));
const ModelStudio = lazy(() => import("./pages/ModelStudio"));
const AuditCenter = lazy(() => import("./pages/AuditCenter"));
const Documents = lazy(() => import("./pages/Documents"));
const Messages = lazy(() => import("./pages/Messages"));
const Reports = lazy(() => import("./pages/Reports"));
const Attendance = lazy(() => import("./pages/Attendance"));
const Delegations = lazy(() => import("./pages/Delegations"));
const Expenses = lazy(() => import("./pages/Expenses"));
const OfficialDocs = lazy(() => import("./pages/OfficialDocs"));

export const appRouteObjects: RouteObject[] = [
  { path: "/", element: <Dashboard /> },
  { path: "/employees", element: <Employees /> },
  { path: "/departments", element: <Departments /> },
  { path: "/leave", element: <Leave /> },
  { path: "/announcements", element: <Announcements /> },
  { path: "/workflows", element: <Workflows /> },
  { path: "/workflows/designer", element: <ProcessDesigner /> },
  { path: "/workflows/forms", element: <FormDesigner /> },
  { path: "/workflows/instance/:id", element: <InstanceDetail /> },
  { path: "/workflows/monitor", element: <WorkflowMonitor /> },
  { path: "/workflows/delegations", element: <Delegations /> },
  { path: "/attendance", element: <Attendance /> },
  { path: "/expenses", element: <Expenses /> },
  { path: "/official-docs", element: <OfficialDocs /> },
  { path: "/signatures", element: <Signatures /> },
  { path: "/settings/roles", element: <SettingsRoles /> },
  { path: "/settings/menus", element: <SettingsMenus /> },
  { path: "/settings/ops", element: <OpsCenter /> },
  { path: "/settings/audit", element: <AuditCenter /> },
  { path: "/documents", element: <Documents /> },
  { path: "/messages", element: <Messages /> },
  { path: "/models", element: <ModelStudio /> },
  { path: "/reports", element: <Reports /> },
];

export default appRouteObjects;
