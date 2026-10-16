import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Col,
  Divider,
  Empty,
  Row,
  Segmented,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  type TableProps,
} from "antd";
import * as echarts from "echarts";
import { reportApi } from "../api/endpoints";
import type { ActivityItem, DashboardOut } from "../types";
import { INSTANCE_STATUS } from "../wfMeta";

const instStatus = (s: string) => INSTANCE_STATUS[s] ?? { label: s, color: "default" };

const PIE_COLORS = ["#1677ff", "#52c41a", "#faad14", "#ff4d4f", "#722ed1", "#13c2c2", "#999"];

// 趋势窗口选项（与后端 Query(ge=7, le=365) 约束一致）
const RANGE_OPTIONS = [
  { label: "近 7 天", value: 7 },
  { label: "近 30 天", value: 30 },
  { label: "近 90 天", value: 90 },
];

/** 轻量 ECharts 容器：挂载初始化、随窗口 resize 自适应、卸载 dispose 防内存泄漏。 */
function Chart({ option, height = 260 }: { option: echarts.EChartsOption; height?: number }) {
  const boxRef = useRef<HTMLDivElement>(null);
  const instRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!boxRef.current) return;
    instRef.current = echarts.init(boxRef.current);
    const onResize = () => instRef.current?.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      instRef.current?.dispose();
      instRef.current = null;
    };
  }, []);

  useEffect(() => {
    instRef.current?.setOption(option, true);
  }, [option]);

  return <div ref={boxRef} style={{ width: "100%", height }} />;
}

export default function Reports() {
  const [days, setDays] = useState<number>(30);
  const [exporting, setExporting] = useState(false);
  const [exportErr, setExportErr] = useState<string | null>(null);

  // 组织级视图：用于切换 cube / trends
  const [cubeMetrics, setCubeMetrics] = useState<string>("attendance,expense,workflow,official_doc");
  const [cubeDim, setCubeDim] = useState<string>("month");
  const [trendsMetrics, setTrendsMetrics] = useState<string | undefined>(undefined);
  const [cubeData, setCubeData] = useState<any>(null);
  const [trendsData, setTrendsData] = useState<any>(null);

  const q = useQuery({
    queryKey: ["dashboard-overview", days],
    queryFn: () => reportApi.overview(days),
  });

  const d = q.data as DashboardOut | undefined;
  const org = d?.org ?? null;

  const statusOption = useMemo<echarts.EChartsOption>(() => {
    const data = (org?.workflow_status ?? []).map((s) => ({
      name: instStatus(s.status).label,
      value: s.count,
    }));
    return {
      tooltip: { trigger: "item" },
      legend: { bottom: 0 },
      color: PIE_COLORS,
      series: [
        {
          type: "pie",
          radius: ["45%", "70%"],
          avoidLabelOverlap: true,
          label: { show: true, formatter: "{b}: {c}" },
          data,
        },
      ],
    };
  }, [org]);

  const trendOption = useMemo<echarts.EChartsOption>(() => {
    const rows = org?.workflow_trend ?? [];
    return {
      tooltip: { trigger: "axis" },
      legend: { data: ["发起", "完成"], bottom: 0 },
      grid: { left: 40, right: 16, top: 16, bottom: 40 },
      xAxis: {
        type: "category",
        data: rows.map((r) => r.date.slice(5)),
        boundaryGap: false,
      },
      yAxis: { type: "value", minInterval: 1 },
      series: [
        {
          name: "发起",
          type: "line",
          smooth: true,
          areaStyle: { opacity: 0.15 },
          data: rows.map((r) => r.started),
          itemStyle: { color: "#1677ff" },
        },
        {
          name: "完成",
          type: "line",
          smooth: true,
          data: rows.map((r) => r.finished),
          itemStyle: { color: "#52c41a" },
        },
      ],
    };
  }, [org]);

  const onExport = async () => {
    setExporting(true);
    setExportErr(null);
    try {
      await reportApi.exportCsv(days);
    } catch (e: any) {
      setExportErr((e as Error)?.message || "导出失败，请稍后重试");
    } finally {
      setExporting(false);
    }
  };

  const deptOption = useMemo<echarts.EChartsOption>(() => {
    const rows = org?.department_headcount ?? [];
    return {
      tooltip: { trigger: "axis" },
      grid: { left: 40, right: 16, top: 16, bottom: 40 },
      xAxis: { type: "category", data: rows.map((r) => r.department) },
      yAxis: { type: "value", minInterval: 1 },
      series: [
        {
          type: "bar",
          barMaxWidth: 28,
          data: rows.map((r) => r.count),
          itemStyle: { color: "#1677ff", borderRadius: [4, 4, 0, 0] },
        },
      ],
    };
  }, [org]);

  const actCols: TableProps<ActivityItem>["columns"] = [
    { title: "#", dataIndex: "id", width: 70 },
    { title: "摘要", dataIndex: "title", ellipsis: true },
    { title: "模块", dataIndex: "type", width: 110, render: (v: string) => <Tag>{v}</Tag> },
    {
      title: "结果",
      dataIndex: "status",
      width: 90,
      render: (v: string | null) =>
        v ? <Tag color={v === "success" ? "green" : "red"}>{v}</Tag> : "—",
    },
    { title: "操作人", dataIndex: "actor", width: 120 },
    {
      title: "时间",
      dataIndex: "at",
      width: 170,
      render: (v: string | null) => (v ? v.slice(0, 19).replace("T", " ") : "—"),
    },
  ];

  if (q.isLoading) {
    return (
      <Card>
        <div style={{ padding: 40, textAlign: "center", color: "#999" }}>加载报表数据中…</div>
      </Card>
    );
  }
  if (q.isError || !d) {
    const msg = (q.error as any)?.message || "报表数据加载失败";
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

  const p = d.personal;
  const k = org?.kpi;

  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 12,
          flexWrap: "wrap",
          gap: 12,
        }}
      >
        <h2 style={{ margin: 0 }}>报表中心</h2>
        <Space wrap>
          <Segmented
            options={RANGE_OPTIONS}
            value={days}
            onChange={(v) => setDays(v as number)}
          />
          <span style={{ color: "#999", fontSize: 12 }}>
            更新于 {d.generated_at?.slice(0, 19)?.replace("T", " ")}
          </span>
          {d.has_org_scope && org ? (
            <Button
              type="primary"
              loading={exporting}
              onClick={onExport}
              disabled={exporting}
            >
              导出 CSV
            </Button>
          ) : null}
          <Button onClick={() => q.refetch()} disabled={exporting}>
            刷新
          </Button>
        </Space>
      </div>

      {exportErr ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          message="导出失败"
          description={exportErr}
          closable
          onClose={() => setExportErr(null)}
        />
      ) : null}

      <Card title="我的概览" size="small" style={{ marginBottom: 16 }}>
        <Row gutter={16}>
          <Col span={6}>
            <Statistic title="未读消息" value={p.my_unread} />
          </Col>
          <Col span={6}>
            <Statistic title="待我审批" value={p.my_pending_approvals} />
          </Col>
          <Col span={6}>
            <Statistic title="我的请假" value={p.my_leaves} />
          </Col>
          <Col span={6}>
            <Statistic title="我在途流程" value={p.my_running} />
          </Col>
        </Row>
      </Card>

      {!d.has_org_scope || !org ? (
        <Alert
          type="info"
          showIcon
          message="组织级数据看板需要 report:view 权限"
          description="当前账号仅可查看个人概览；如需查看全公司 KPI 与图表，请联系管理员授权。"
        />
      ) : (
        <>
          <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
            {[
              { t: "用户总数", v: k?.users_total },
              { t: "部门总数", v: k?.departments_total },
              { t: "流程实例", v: k?.workflow_instances },
              { t: "在途流程", v: k?.workflow_active },
              { t: "已办结", v: k?.workflow_done },
              { t: "本月请假", v: k?.leaves_this_month },
              { t: "公告总数", v: k?.announcements_total },
              { t: "审计记录", v: k?.audit_total },
            ].map((it) => (
              <Col span={6} key={it.t}>
                <Card size="small">
                  <Statistic title={it.t} value={it.v || 0} />
                </Card>
              </Col>
            ))}
          </Row>

          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={8}>
              <Card title="流程状态分布" size="small">
                {org.workflow_status.length ? (
                  <Chart option={statusOption} height={240} />
                ) : (
                  <Empty description="暂无实例" />
                )}
              </Card>
            </Col>
            <Col span={16}>
              <Card title={`近 ${days} 天发起 / 完成趋势`} size="small">
                <Chart option={trendOption} height={240} />
              </Card>
            </Col>
          </Row>

          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={24}>
              <Card title="部门人数分布" size="small">
                {org.department_headcount.length ? (
                  <Chart option={deptOption} height={220} />
                ) : (
                  <Empty description="暂无部门数据" />
                )}
              </Card>
            </Col>
          </Row>

          <Divider style={{ margin: "8px 0 16px" }} />
          <Card title={`最近动态 (${org.recent_activities.length})`} size="small">
            <Table
              rowKey="id"
              size="small"
              dataSource={org.recent_activities}
              columns={actCols}
              pagination={{ pageSize: 8 }}
              locale={{ emptyText: <Empty description="暂无动态" /> }}
            />
          </Card>
        </>
      )}
    </div>
  );
}
