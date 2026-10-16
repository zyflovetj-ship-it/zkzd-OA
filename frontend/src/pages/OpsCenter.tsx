import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  Button,
  Card,
  Col,
  Empty,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  type TableProps,
} from "antd";
import { opsApi } from "../api/endpoints";
import type { OpsInstance, OpsOverviewOut } from "../types";
import { INSTANCE_STATUS } from "../wfMeta";

const n = (v: number | undefined) => v || 0;
const instStatus = (s: string) => INSTANCE_STATUS[s] ?? { label: s, color: "default" };

// 内联横条图（零依赖，随环境可 tsc 校验、无构建风险）
function HBarChart({
  data,
}: {
  data: { label: string; value: number; color?: string }[];
}) {
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <div>
      {data.map((d, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", marginBottom: 8, gap: 8 }}>
          <div
            style={{
              width: 96,
              fontSize: 13,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
            title={d.label}
          >
            {d.label}
          </div>
          <div style={{ flex: 1, background: "#f5f5f5", borderRadius: 4, height: 16 }}>
            <div
              style={{
                width: `${(d.value / max) * 100}%`,
                background: d.color || "#1677ff",
                height: "100%",
                borderRadius: 4,
                transition: "width .3s",
              }}
            />
          </div>
          <div style={{ width: 36, textAlign: "right", fontSize: 13 }}>{d.value}</div>
        </div>
      ))}
      {data.length === 0 && <div style={{ color: "#999", fontSize: 13 }}>暂无数据</div>}
    </div>
  );
}

const COUNT_LABELS: Record<string, string> = {
  用户: "用户",
  部门: "部门",
  角色: "角色",
  权限点: "权限点",
  菜单: "菜单",
  请假单: "请假单",
  公告: "公告",
  流程定义: "流程定义",
  流程实例: "流程实例",
};

export default function OpsCenter() {
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ["ops-overview"], queryFn: opsApi.overview });

  if (q.isLoading) {
    return (
      <Card>
        <div style={{ padding: 40, textAlign: "center", color: "#999" }}>加载运维数据中…</div>
      </Card>
    );
  }
  if (q.isError) {
    const msg = (q.error as any)?.message || "运维数据加载失败";
    return (
      <Card>
        <div style={{ padding: 40, textAlign: "center", color: "#cf1322" }}>
          {msg}
          <div style={{ marginTop: 12 }}>
            <Button onClick={() => q.refetch()}>重试</Button>
          </div>
        </div>
      </Card>
    );
  }

  const d = q.data as OpsOverviewOut;
  const countEntries = Object.entries(d.counts);
  const statusData = Object.entries(d.instances_by_status).map(([k, v]) => ({
    label: instStatus(k).label,
    value: v,
    color: instStatus(k).color === "default" ? "#999" : instStatus(k).color,
  }));
  const roleData = d.users_by_role.map((r) => ({ label: r.role, value: r.count }));

  const instCols: TableProps<OpsInstance>["columns"] = [
    { title: "单号", dataIndex: "code" },
    { title: "标题", dataIndex: "title", ellipsis: true },
    { title: "发起人", dataIndex: "initiator" },
    {
      title: "状态",
      dataIndex: "status",
      render: (s: string) => <Tag color={instStatus(s).color}>{instStatus(s).label}</Tag>,
    },
    {
      title: "发起时间",
      dataIndex: "started_at",
      render: (v: string | null) => (v ? v.slice(0, 19).replace("T", " ") : "—"),
    },
    {
      title: "操作",
      render: (_, r) => (
        <Button size="small" onClick={() => navigate(`/workflows/instance/${r.id}`)}>
          查看
        </Button>
      ),
    },
  ];

  const statCards = countEntries.map(([k, v]) => (
    <Col span={8} key={k}>
      <Card>
        <Statistic title={COUNT_LABELS[k] || k} value={n(v)} />
        <div style={{ marginTop: 8, fontSize: 12, color: "#666" }}>{k}总数</div>
      </Card>
    </Col>
  ));

  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 12,
        }}
      >
        <h2>运维中心</h2>
        <Space>
          <span style={{ color: "#999", fontSize: 12 }}>
            数据库：{d.db_backend} · 更新于 {d.generated_at?.slice(0, 19)?.replace("T", " ")}
          </span>
          <Button onClick={() => q.refetch()}>刷新</Button>
        </Space>
      </div>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        {statCards}
      </Row>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={12}>
          <Card title="流程实例状态分布">
            {statusData.length ? <HBarChart data={statusData} /> : <Empty description="暂无实例" />}
          </Card>
        </Col>
        <Col span={12}>
          <Card title="角色人数矩阵">
            {roleData.length ? <HBarChart data={roleData} /> : <Empty description="暂无角色" />}
          </Card>
        </Col>
      </Row>

      <Card title={`最近流程实例 (${d.recent_instances.length})`}>
        <Table
          rowKey="id"
          size="small"
          dataSource={d.recent_instances}
          columns={instCols}
          pagination={{ pageSize: 8 }}
        />
      </Card>
    </div>
  );
}
