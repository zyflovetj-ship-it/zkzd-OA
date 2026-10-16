import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Button, Col, List, Row, Space, Tag } from "antd";
import {
  ApartmentOutlined,
  AuditOutlined,
  BranchesOutlined,
  CalendarOutlined,
  DashboardOutlined,
  FileTextOutlined,
  NotificationOutlined,
  TeamOutlined,
} from "@ant-design/icons";
import { useAuth } from "../auth/AuthContext";
import { portalApi } from "../api/endpoints";
import {
  DataTable,
  EmptyState,
  PageContainer,
  SectionCard,
  StatCard,
  StatusTag,
} from "../components/framework";
import type {
  PortalAnnouncementOut,
  PortalInstanceOut,
  PortalLeaveOut,
  PortalOverviewOut,
  PortalTaskOut,
} from "../types";

const LEAVE_LABEL: Record<string, string> = {
  annual: "年假",
  sick: "病假",
  personal: "事假",
  other: "其他",
};

const fmtDate = (s?: string | null) => (s ? s.slice(0, 10) : "-");
const fmtTime = (s?: string | null) => (s ? s.slice(0, 16).replace("T", " ") : "-");

/** 按当前时段生成问候语 */
function greeting(): string {
  const h = new Date().getHours();
  if (h < 6) return "夜深了";
  if (h < 9) return "早上好";
  if (h < 12) return "上午好";
  if (h < 14) return "中午好";
  if (h < 18) return "下午好";
  return "晚上好";
}

function todayLabel(): string {
  const d = new Date();
  const week = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"][d.getDay()];
  return d.getFullYear() + " 年 " + (d.getMonth() + 1) + " 月 " + d.getDate() + " 日 " + week;
}

/** 指标卡图标按中文标签关键字匹配，避免后端新增指标时前端硬编码 */
function iconFor(label: string) {
  if (label.includes("待办") || label.includes("审批")) return <AuditOutlined />;
  if (label.includes("请假")) return <CalendarOutlined />;
  if (label.includes("公告")) return <NotificationOutlined />;
  if (label.includes("流程")) return <BranchesOutlined />;
  if (label.includes("部门")) return <ApartmentOutlined />;
  if (label.includes("员工")) return <TeamOutlined />;
  if (label.includes("公告单")) return <FileTextOutlined />;
  return <DashboardOutlined />;
}

export default function Dashboard() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ["portal"], queryFn: portalApi.overview });

  if (q.isLoading) {
    return (
      <PageContainer>
        <SectionCard>
          <EmptyState description="正在加载工作台…" compact />
        </SectionCard>
      </PageContainer>
    );
  }
  if (q.isError || !q.data) {
    return (
      <PageContainer>
        <SectionCard>
          <EmptyState description="工作台加载失败，请稍后重试" compact />
        </SectionCard>
      </PageContainer>
    );
  }

  const d: PortalOverviewOut = q.data;
  const statEntries = Object.entries(d.stats);
  const pendingCount = d.pending_tasks.length;

  return (
    <PageContainer>
      {/* 门户横幅：品牌渐变 + 问候语 + 快捷入口 */}
      <div className="zk-banner">
        <h1 className="zk-banner__title">
          {greeting()}，{user?.full_name || user?.username}
        </h1>
        <p className="zk-banner__sub">
          {todayLabel()}
          <span style={{ margin: "0 8px", opacity: 0.5 }}>|</span>
          当前角色 <Tag color="rgba(255,255,255,.22)" style={{ color: "#fff", border: 0 }}>{d.role}</Tag>
          {pendingCount > 0 ? (
            <>
              <span style={{ margin: "0 8px", opacity: 0.5 }}>|</span>
              您有 <b>{pendingCount}</b> 项待办审批
            </>
          ) : (
            <>
              <span style={{ margin: "0 8px", opacity: 0.5 }}>|</span>暂无待办事项
            </>
          )}
        </p>
        <div className="zk-banner__actions">
          <Button
            style={{ background: "#fff", borderColor: "#fff", color: "#033b88", fontWeight: 600 }}
            onClick={() => navigate("/workflows")}
          >
            发起流程
          </Button>
          <Button ghost onClick={() => navigate("/leave")}>
            请假申请
          </Button>
          <Button ghost onClick={() => navigate("/expenses")}>
            费用报销
          </Button>
          <Button ghost onClick={() => navigate("/announcements")}>
            发布公告
          </Button>
        </div>
      </div>

      {/* 指标概览 */}
      <Row gutter={[12, 12]}>
        {statEntries.map(([k, v]) => (
          <Col key={k} xs={12} sm={12} md={8} xl={statEntries.length > 4 ? 4 : 6}>
            <StatCard label={k} value={v} icon={iconFor(k)} />
          </Col>
        ))}
      </Row>

      {/* 待办与在途 */}
      <Row gutter={[12, 12]}>
        <Col xs={24} xl={12}>
          <SectionCard
            title={"待我审批" + (pendingCount ? "（" + pendingCount + "）" : "")}
            extra={<a onClick={() => navigate("/workflows")}>进入流程中心</a>}
            flush
          >
            {pendingCount === 0 ? (
              <EmptyState description="暂无待办，一切顺利" compact />
            ) : (
              <DataTable<PortalTaskOut>
                card={false}
                rowKey="task_id"
                size="small"
                pagination={false}
                dataSource={d.pending_tasks}
                columns={[
                  {
                    title: "流程单号",
                    dataIndex: "instance_code",
                    width: 150,
                    render: (v: string) => (
                      <span style={{ fontFamily: "var(--zk-font-mono, monospace)", fontSize: 12 }}>{v}</span>
                    ),
                  },
                  { title: "标题", dataIndex: "instance_title", ellipsis: true },
                  { title: "当前节点", dataIndex: "node_name", width: 110 },
                  {
                    title: "提交时间",
                    dataIndex: "created_at",
                    width: 130,
                    render: (v: string) => fmtTime(v),
                  },
                  {
                    title: "操作",
                    key: "op",
                    width: 70,
                    fixed: "right",
                    render: (_: unknown, r: PortalTaskOut) => (
                      <a onClick={() => navigate("/workflows/instance/" + r.instance_id)}>处理</a>
                    ),
                  },
                ]}
              />
            )}
          </SectionCard>
        </Col>

        <Col xs={24} xl={12}>
          <SectionCard
            title="我发起的在途流程"
            extra={<a onClick={() => navigate("/workflows")}>全部</a>}
            flush
          >
            {d.my_instances_running.length === 0 ? (
              <EmptyState description="暂无在途流程" compact />
            ) : (
              <DataTable<PortalInstanceOut>
                card={false}
                rowKey="id"
                size="small"
                pagination={false}
                dataSource={d.my_instances_running}
                columns={[
                  {
                    title: "单号",
                    dataIndex: "code",
                    width: 150,
                    render: (v: string) => (
                      <span style={{ fontFamily: "var(--zk-font-mono, monospace)", fontSize: 12 }}>{v}</span>
                    ),
                  },
                  { title: "标题", dataIndex: "title", ellipsis: true },
                  {
                    title: "状态",
                    dataIndex: "status",
                    width: 90,
                    render: (s: string) => <StatusTag status={s} />,
                  },
                  {
                    title: "操作",
                    key: "op",
                    width: 70,
                    fixed: "right",
                    render: (_: unknown, r: PortalInstanceOut) => (
                      <a onClick={() => navigate("/workflows/instance/" + r.id)}>查看</a>
                    ),
                  },
                ]}
              />
            )}
          </SectionCard>
        </Col>

        <Col xs={24} xl={12}>
          <SectionCard
            title="我的请假"
            extra={<a onClick={() => navigate("/leave")}>请假申请</a>}
            flush
          >
            {d.recent_leave.length === 0 ? (
              <EmptyState description="暂无请假记录" compact />
            ) : (
              <DataTable<PortalLeaveOut>
                card={false}
                rowKey="id"
                size="small"
                pagination={false}
                dataSource={d.recent_leave}
                columns={[
                  {
                    title: "类型",
                    dataIndex: "leave_type",
                    width: 90,
                    render: (t: string) => LEAVE_LABEL[t] || t,
                  },
                  {
                    title: "状态",
                    dataIndex: "status",
                    width: 100,
                    render: (s: string) => <StatusTag status={s} />,
                  },
                  { title: "开始", dataIndex: "start_date", width: 110, render: (v: string) => fmtDate(v) },
                  { title: "结束", dataIndex: "end_date", width: 110, render: (v: string) => fmtDate(v) },
                ]}
              />
            )}
          </SectionCard>
        </Col>

        <Col xs={24} xl={12}>
          <SectionCard
            title="最新公告"
            extra={<a onClick={() => navigate("/announcements")}>查看全部</a>}
            flush
          >
            {d.announcements.length === 0 ? (
              <EmptyState description="暂无公告" compact />
            ) : (
              <List<PortalAnnouncementOut>
                dataSource={d.announcements}
                rowKey="id"
                style={{ padding: "0 4px" }}
                renderItem={(a) => (
                  <List.Item
                    actions={[
                      <a key="view" onClick={() => navigate("/announcements")}>
                        查看
                      </a>,
                    ]}
                  >
                    <List.Item.Meta
                      title={
                        <Space size={6}>
                          {a.pinned ? <Tag color="error">置顶</Tag> : null}
                          <span>{a.title}</span>
                        </Space>
                      }
                      description={fmtTime(a.created_at)}
                    />
                  </List.Item>
                )}
              />
            )}
          </SectionCard>
        </Col>
      </Row>
    </PageContainer>
  );
}
