import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  Button,
  Card,
  Col,
  Progress,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
} from "antd";
import type { TableProps } from "antd/es/table";
import { wfApi } from "../api/endpoints";
import type { WorkflowStatsOut } from "../types";
import { INSTANCE_STATUS, NODE_META } from "../wfMeta";

type RunningNode = { node_id: string; name: string; type: string };

const n = (v: number | undefined) => v || 0;
const nodeColor = (t: string) => NODE_META[(t as keyof typeof NODE_META)]?.color || "#999";
const instStatus = (s: string) => INSTANCE_STATUS[s] ?? { label: s, color: "default" };
const daysLate = (createdAt: string | null) =>
  createdAt ? Math.floor((Date.now() - new Date(createdAt).getTime()) / 86400000) : 0;

// ---------- 内联 SVG 图表（零依赖，随环境可 tsc 校验、无构建风险） ----------

function DonutChart({
  data,
  size = 160,
}: {
  data: { label: string; value: number; color: string }[];
  size?: number;
}) {
  const total = data.reduce((s, d) => s + d.value, 0);
  const stroke = 16;
  const r = size / 2 - stroke / 2;
  const c = 2 * Math.PI * r;
  let offset = 0;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
      <div style={{ position: "relative", width: size, height: size }}>
        <svg width={size} height={size}>
          <g transform={`rotate(-90 ${size / 2} ${size / 2})`}>
            <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#f0f0f0" strokeWidth={stroke} />
            {total > 0 &&
              data.map((d, i) => {
                const len = (d.value / total) * c;
                const seg = (
                  <circle
                    key={i}
                    cx={size / 2}
                    cy={size / 2}
                    r={r}
                    fill="none"
                    stroke={d.color}
                    strokeWidth={stroke}
                    strokeDasharray={`${len} ${c - len}`}
                    strokeDashoffset={-offset}
                  />
                );
                offset += len;
                return seg;
              })}
          </g>
        </svg>
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <span style={{ fontSize: 22, fontWeight: 700 }}>{total}</span>
          <span style={{ color: "#999", fontSize: 12 }}>实例总数</span>
        </div>
      </div>
      <div>
        {data.map((d, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            <span style={{ width: 10, height: 10, borderRadius: 2, background: d.color, display: "inline-block" }} />
            <span style={{ fontSize: 13 }}>{d.label}</span>
            <span style={{ fontSize: 13, fontWeight: 600 }}>{d.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function HBarChart({ data }: { data: { label: string; value: number; color?: string }[] }) {
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <div>
      {data.map((d, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", marginBottom: 8, gap: 8 }}>
          <div
            style={{
              width: 110,
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

function TrendChart({ data }: { data: { date: string; started: number; finished: number }[] }) {
  const w = 540;
  const h = 200;
  const pad = 32;
  const max = Math.max(1, ...data.map((d) => Math.max(d.started, d.finished)));
  const cnt = data.length;
  const x = (i: number) => pad + (cnt > 1 ? (i / (cnt - 1)) * (w - pad * 2) : 0);
  const y = (v: number) => h - pad - (v / max) * (h - pad * 2);
  const line = (key: "started" | "finished") =>
    data.map((d, i) => `${x(i)},${y(d[key])}`).join(" ");
  const area = (key: "started" | "finished") =>
    `${pad},${h - pad} ${data.map((d, i) => `${x(i)},${y(d[key])}`).join(" ")} ${w - pad},${h - pad}`;
  return (
    <div>
      <svg width="100%" viewBox={`0 0 ${w} ${h}`} style={{ maxWidth: w }}>
        <line x1={pad} y1={h - pad} x2={w - pad} y2={h - pad} stroke="#eee" />
        {data.map((d, i) =>
          i % 2 === 0 ? (
            <text key={i} x={x(i)} y={h - pad + 16} fontSize={10} fill="#999" textAnchor="middle">
              {d.date.slice(5)}
            </text>
          ) : null
        )}
        <polygon points={area("started")} fill="rgba(22,119,255,0.08)" />
        <polyline points={line("started")} fill="none" stroke="#1677ff" strokeWidth={2} />
        <polyline points={line("finished")} fill="none" stroke="#52c41a" strokeWidth={2} />
      </svg>
      <Space size={16} style={{ marginTop: 4 }}>
        <span style={{ fontSize: 12, color: "#666" }}>
          <span style={{ display: "inline-block", width: 10, height: 10, background: "#1677ff", marginRight: 4 }} />
          发起
        </span>
        <span style={{ fontSize: 12, color: "#666" }}>
          <span style={{ display: "inline-block", width: 10, height: 10, background: "#52c41a", marginRight: 4 }} />
          办结
        </span>
      </Space>
    </div>
  );
}

// ---------- 页面 ----------

export default function WorkflowMonitor() {
  const navigate = useNavigate();
  const statsQ = useQuery({ queryKey: ["wf-stats"], queryFn: wfApi.stats });

  if (statsQ.isLoading) {
    return (
      <Card>
        <div style={{ padding: 40, textAlign: "center", color: "#999" }}>加载监控数据中…</div>
      </Card>
    );
  }
  if (statsQ.isError) {
    const msg = (statsQ.error as any)?.message || "监控数据加载失败";
    return (
      <Card>
        <div style={{ padding: 40, textAlign: "center", color: "#cf1322" }}>
          {msg}
          <div style={{ marginTop: 12 }}>
            <Button onClick={() => statsQ.refetch()}>重试</Button>
          </div>
        </div>
      </Card>
    );
  }

  const s = statsQ.data as WorkflowStatsOut;
  const defStat = s.definitions;
  const instStat = s.instances;
  const taskStat = s.tasks;

  const donutData = [
    { label: "进行中", value: n(instStat.running), color: "#1677ff" },
    { label: "已通过", value: n(instStat.approved), color: "#52c41a" },
    { label: "已驳回", value: n(instStat.rejected), color: "#cf1322" },
    { label: "已撤回", value: n(instStat.canceled), color: "#bfbfbf" },
  ];
  const byDefData = s.by_definition.map((d) => ({ label: d.name, value: d.total, color: "#1677ff" }));

  const overdueCols: TableProps<WorkflowStatsOut["overdue_tasks"][number]>["columns"] = [
    { title: "单号", dataIndex: "instance_code" },
    { title: "标题", dataIndex: "instance_title", ellipsis: true },
    { title: "节点", dataIndex: "node_name" },
    { title: "处理人", dataIndex: "approver_name" },
    {
      title: "停留(天)",
      dataIndex: "created_at",
      render: (v: string | null) => {
        const d = daysLate(v);
        return d > s.sla_days ? <span style={{ color: "#cf1322", fontWeight: 600 }}>{d}</span> : d;
      },
    },
    {
      title: "操作",
      render: (_, r) => (
        <Button size="small" onClick={() => navigate(`/workflows/instance/${r.instance_id}`)}>
          查看
        </Button>
      ),
    },
  ];

  const runningCols: TableProps<WorkflowStatsOut["running_instances"][number]>["columns"] = [
    { title: "单号", dataIndex: "code" },
    { title: "标题", dataIndex: "title", ellipsis: true },
    { title: "流程", dataIndex: "definition_name" },
    { title: "发起人", dataIndex: "initiator" },
    {
      title: "当前节点",
      dataIndex: "current_nodes",
      render: (nodes: RunningNode[]) => (
        <Space size={4} wrap>
          {nodes.map((nd) => (
            <Tag key={nd.node_id} color={nodeColor(nd.type)}>
              {nd.name}
            </Tag>
          ))}
        </Space>
      ),
    },
    { title: "进度", dataIndex: "progress", render: (v: number) => <Progress percent={v} size="small" /> },
    {
      title: "操作",
      render: (_, r) => (
        <Button size="small" onClick={() => navigate(`/workflows/instance/${r.id}`)}>
          查看
        </Button>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <h2>流程监控看板</h2>
        <Space>
          <span style={{ color: "#999", fontSize: 12 }}>
            超时阈值 {s.sla_days} 天 · 更新于 {s.generated_at?.slice(0, 19)?.replace("T", " ")}
          </span>
          <Button onClick={() => statsQ.refetch()}>刷新</Button>
        </Space>
      </div>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card>
            <Statistic title="流程定义" value={n(defStat.draft) + n(defStat.published) + n(defStat.locked)} />
            <div style={{ marginTop: 8, fontSize: 12, color: "#666" }}>
              <Tag color="blue">已发布 {n(defStat.published)}</Tag>
              <Tag>草稿 {n(defStat.draft)}</Tag>
              <Tag color="red">锁定 {n(defStat.locked)}</Tag>
            </div>
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="流程实例"
              value={n(instStat.running) + n(instStat.approved) + n(instStat.rejected) + n(instStat.canceled)}
            />
            <div style={{ marginTop: 8, fontSize: 12, color: "#666" }}>
              <Tag color="blue">进行中 {n(instStat.running)}</Tag>
              <Tag color="green">通过 {n(instStat.approved)}</Tag>
              <Tag color="red">驳回 {n(instStat.rejected)}</Tag>
            </div>
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="待办任务" value={n(taskStat.pending)} />
            <div style={{ marginTop: 8, fontSize: 12, color: "#666" }}>
              {n(taskStat.overdue) ? (
                <Tag color="red">已超时 {n(taskStat.overdue)}</Tag>
              ) : (
                <Tag color="green">无超时</Tag>
              )}
            </div>
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="生效委托" value={s.delegations_active} />
            <div style={{ marginTop: 8, fontSize: 12, color: "#666" }}>当前生效中的审批委托</div>
          </Card>
        </Col>
      </Row>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card title="实例状态分布">
            <DonutChart data={donutData} />
          </Card>
        </Col>
        <Col span={8}>
          <Card title="各流程发起量">
            <HBarChart data={byDefData} />
          </Card>
        </Col>
        <Col span={8}>
          <Card title="近 14 天趋势（发起/办结）">
            <TrendChart data={s.trend} />
          </Card>
        </Col>
      </Row>

      <Row gutter={16}>
        <Col span={12}>
          <Card title={`超时待办 (${s.overdue_tasks.length})`}>
            <Table
              rowKey="task_id"
              size="small"
              dataSource={s.overdue_tasks}
              columns={overdueCols}
              pagination={{ pageSize: 5 }}
            />
          </Card>
        </Col>
        <Col span={12}>
          <Card title={`进行中实例 (${s.running_instances.length})`}>
            <Table
              rowKey="id"
              size="small"
              dataSource={s.running_instances}
              columns={runningCols}
              pagination={{ pageSize: 5 }}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
