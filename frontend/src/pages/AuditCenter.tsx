import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Button,
  Card,
  Col,
  DatePicker,
  Drawer,
  Empty,
  Input,
  Modal,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  type TableProps,
} from "antd";
import { ExclamationCircleOutlined } from "@ant-design/icons";
import dayjs, { type Dayjs } from "dayjs";
import { auditApi } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import type { AuditLogOut, AuditStatsOut } from "../types";

const { RangePicker } = DatePicker;

const n = (v: number | undefined) => v || 0;

// 模块 / 动作 友好名映射
const MODULE_LABELS: Record<string, string> = {
  auth: "认证",
  workflow: "审批工作流",
  model: "建模引擎",
  org: "组织权限",
  user: "用户",
  leave: "请假",
  ann: "公告",
  sig: "电子签单",
  other: "其他",
};
const modLabel = (m: string) => MODULE_LABELS[m] || m;

const STATUS_COLOR: Record<string, string> = { success: "green", failed: "red" };

// 内联横条图（零依赖，tsc 安全）
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

// 内联趋势折线（近 14 天，零依赖 SVG）
function TrendSparkline({ data }: { data: { date: string; count: number }[] }) {
  const w = 320;
  const h = 96;
  const max = Math.max(1, ...data.map((d) => d.count));
  const step = data.length > 1 ? w / (data.length - 1) : w;
  const pts = data.map((d, i) => {
    const x = i * step;
    const y = h - (d.count / max) * (h - 12) - 6;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h}>
      <polyline fill="none" stroke="#1677ff" strokeWidth={2} points={pts.join(" ")} />
      {data.map((d, i) => {
        const x = i * step;
        const y = h - (d.count / max) * (h - 12) - 6;
        return <circle key={i} cx={x} cy={y} r={2.5} fill="#1677ff" />;
      })}
    </svg>
  );
}

export default function AuditCenter() {
  const { user } = useAuth();
  const canPurge = (user?.permissions || []).some((p) => p === "audit:manage" || p === "*");

  const [module, setModule] = useState<string | undefined>();
  const [status, setStatus] = useState<string | undefined>();
  const [q, setQ] = useState<string>("");
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null);
  const [drawerRow, setDrawerRow] = useState<AuditLogOut | null>(null);
  const [purgeOpen, setPurgeOpen] = useState(false);
  const [purgeDays, setPurgeDays] = useState(90);

  const statsQ = useQuery({ queryKey: ["audit-stats"], queryFn: auditApi.stats });

  const logsQ = useQuery({
    queryKey: ["audit-logs", module, status, q, range],
    queryFn: () =>
      auditApi.logs({
        module,
        status,
        q: q || undefined,
        start: range ? range[0].format("YYYY-MM-DD") + "T00:00:00" : undefined,
        end: range ? range[1].format("YYYY-MM-DD") + "T23:59:59" : undefined,
        limit: 100,
      }),
  });

  const stats = statsQ.data as AuditStatsOut | undefined;
  const moduleOptions = useMemo(
    () =>
      (stats?.by_module || []).map((m) => ({
        value: m.key,
        label: `${modLabel(m.key)} (${m.count})`,
      })),
    [stats]
  );

  const doPurge = async () => {
    try {
      const r = await auditApi.purge(purgeDays);
      setPurgeOpen(false);
      await Promise.all([statsQ.refetch(), logsQ.refetch()]);
      Modal.success({
        title: "清理完成",
        content: `已清理 ${r.deleted} 条 ${purgeDays} 天前的审计记录。`,
      });
    } catch (e: any) {
      Modal.error({ title: "清理失败", content: e?.response?.data?.error?.message || "操作失败" });
    }
  };

  const cols: TableProps<AuditLogOut>["columns"] = [
    {
      title: "时间",
      dataIndex: "created_at",
      width: 160,
      render: (v: string) => (v ? v.slice(0, 19).replace("T", " ") : "—"),
    },
    {
      title: "操作人",
      dataIndex: "actor_name",
      width: 100,
      render: (v: string, r) => v || (r.actor_id ? `#${r.actor_id}` : "匿名/系统"),
    },
    { title: "模块", dataIndex: "module", width: 92, render: (m: string) => <Tag>{modLabel(m)}</Tag> },
    { title: "动作", dataIndex: "action", width: 120, ellipsis: true },
    {
      title: "目标",
      width: 130,
      render: (_, r) => (r.target_type ? `${r.target_type}#${r.target_id}` : "—"),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 80,
      render: (s: string) => <Tag color={STATUS_COLOR[s] || "default"}>{s === "success" ? "成功" : "失败"}</Tag>,
    },
    { title: "路径", dataIndex: "path", ellipsis: true, render: (v: string) => <code style={{ fontSize: 12 }}>{v}</code> },
    {
      title: "详情",
      width: 72,
      render: (_, r) => (
        <Button size="small" onClick={() => setDrawerRow(r)}>
          查看
        </Button>
      ),
    },
  ];

  if (statsQ.isLoading) {
    return (
      <Card>
        <div style={{ padding: 40, textAlign: "center", color: "#999" }}>加载审计统计中…</div>
      </Card>
    );
  }
  if (statsQ.isError) {
    return (
      <Card>
        <div style={{ padding: 40, textAlign: "center", color: "#cf1322" }}>
          {(statsQ.error as any)?.message || "统计加载失败"}
          <div style={{ marginTop: 12 }}>
            <Button onClick={() => statsQ.refetch()}>重试</Button>
          </div>
        </div>
      </Card>
    );
  }

  const moduleData = (stats?.by_module || []).map((m) => ({ label: modLabel(m.key), value: m.count }));
  const statusData = (stats?.by_status || []).map((m) => ({
    label: m.key === "success" ? "成功" : m.key === "failed" ? "失败" : m.key,
    value: m.count,
    color: m.key === "success" ? "#52c41a" : m.key === "failed" ? "#ff4d4f" : "#999",
  }));

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
        <h2>日志中心</h2>
        <Space>
          <span style={{ color: "#999", fontSize: 12 }}>更新于 {stats?.generated_at?.slice(0, 19)?.replace("T", " ")}</span>
          {canPurge && (
            <Button danger icon={<ExclamationCircleOutlined />} onClick={() => setPurgeOpen(true)}>
              清理日志
            </Button>
          )}
          <Button onClick={() => Promise.all([statsQ.refetch(), logsQ.refetch()])}>刷新</Button>
        </Space>
      </div>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card>
            <Statistic title="审计总量" value={n(stats?.total)} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="成功" value={n(stats?.success)} valueStyle={{ color: "#52c41a" }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="失败" value={n(stats?.failed)} valueStyle={{ color: "#ff4d4f" }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="涉及模块" value={n(stats?.by_module?.length)} />
          </Card>
        </Col>
      </Row>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card title="按模块分布">
            {moduleData.length ? <HBarChart data={moduleData} /> : <Empty description="暂无数据" />}
          </Card>
        </Col>
        <Col span={8}>
          <Card title="按结果分布">
            {statusData.length ? <HBarChart data={statusData} /> : <Empty description="暂无数据" />}
          </Card>
        </Col>
        <Col span={8}>
          <Card title="近 14 天趋势">
            {(stats?.trend || []).length ? (
              <TrendSparkline data={stats!.trend} />
            ) : (
              <Empty description="暂无数据" />
            )}
          </Card>
        </Col>
      </Row>

      <Card title="审计日志">
        <Space wrap style={{ marginBottom: 12 }}>
          <Select
            allowClear
            placeholder="模块"
            style={{ width: 180 }}
            value={module}
            onChange={setModule}
            options={moduleOptions}
          />
          <Select
            allowClear
            placeholder="结果"
            style={{ width: 120 }}
            value={status}
            onChange={setStatus}
            options={[
              { value: "success", label: "成功" },
              { value: "failed", label: "失败" },
            ]}
          />
          <RangePicker value={range} onChange={(v) => setRange(v as [Dayjs, Dayjs] | null)} />
          <Input.Search
            placeholder="操作人 / 路径关键字"
            allowClear
            style={{ width: 240 }}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onSearch={() => logsQ.refetch()}
          />
        </Space>

        {logsQ.isError ? (
          <div style={{ padding: 40, textAlign: "center", color: "#cf1322" }}>
            {(logsQ.error as any)?.message || "日志加载失败"}
          </div>
        ) : (
          <Table
            rowKey="id"
            size="small"
            loading={logsQ.isLoading}
            dataSource={logsQ.data?.items || []}
            columns={cols}
            pagination={{
              pageSize: 20,
              total: logsQ.data?.total || 0,
              showTotal: (t) => `共 ${t} 条`,
            }}
          />
        )}
      </Card>

      <Drawer
        title="审计详情"
        width={480}
        open={!!drawerRow}
        onClose={() => setDrawerRow(null)}
      >
        {drawerRow && (
          <div style={{ fontSize: 13, lineHeight: 2 }}>
            <p><b>ID：</b>{drawerRow.id}</p>
            <p><b>时间：</b>{drawerRow.created_at?.slice(0, 19)?.replace("T", " ")}</p>
            <p><b>操作人：</b>{drawerRow.actor_name || `系统/匿名 (${drawerRow.actor_id ?? "—"})`}</p>
            <p><b>模块 / 动作：</b>{modLabel(drawerRow.module)} / {drawerRow.action}</p>
            <p><b>目标：</b>{drawerRow.target_type ? `${drawerRow.target_type}#${drawerRow.target_id}` : "—"}</p>
            <p><b>请求：</b>{drawerRow.method} {drawerRow.path}</p>
            <p><b>结果：</b>{drawerRow.status_code} ({drawerRow.status})</p>
            <p><b>IP：</b>{drawerRow.ip || "—"}</p>
            <p><b>请求 ID：</b>{drawerRow.request_id || "—"}</p>
            <p><b>上下文：</b></p>
            <pre
              style={{
                background: "#f5f5f5",
                padding: 12,
                borderRadius: 6,
                fontSize: 12,
                maxHeight: 240,
                overflow: "auto",
              }}
            >
              {JSON.stringify(drawerRow.detail || {}, null, 2)}
            </pre>
          </div>
        )}
      </Drawer>

      <Modal
        title="清理审计日志"
        open={purgeOpen}
        onOk={doPurge}
        onCancel={() => setPurgeOpen(false)}
        okText="确认清理"
        okButtonProps={{ danger: true }}
      >
        <p>将删除指定天数之前的全部审计记录，此操作不可恢复。</p>
        <Space>
          <span>保留最近</span>
          <Input
            type="number"
            min={1}
            max={3650}
            value={purgeDays}
            style={{ width: 120 }}
            onChange={(e) => setPurgeDays(Number(e.target.value) || 90)}
          />
          <span>天</span>
        </Space>
      </Modal>
    </div>
  );
}
