import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  TimePicker,
  Upload,
  message,
} from "antd";
import {
  ClockCircleOutlined,
  DownloadOutlined,
  EditOutlined,
  SettingOutlined,
  UploadOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import dayjs, { type Dayjs } from "dayjs";
import {
  attendanceApi,
  type AttendanceRecord,
  type AttendanceSettingsUpdate,
  type Overtime,
  type FieldWorkOrder,
  type AttendanceAlert,
} from "../api/attendance";
import { useAuth } from "../auth/AuthContext";

const STATUS_META: Record<string, { label: string; color: string }> = {
  normal: { label: "正常", color: "green" },
  late: { label: "迟到", color: "red" },
  early: { label: "早退", color: "orange" },
  absent: { label: "缺勤", color: "magenta" },
  leave: { label: "请假", color: "blue" },
  travel: { label: "出差", color: "cyan" },
  remote: { label: "远程", color: "purple" },
};
const statusTag = (s: string) => {
  const m = STATUS_META[s] || { label: s, color: "default" };
  return <Tag color={m.color}>{m.label}</Tag>;
};
const OT_META: Record<string, { label: string; color: string }> = {
  pending: { label: "待审批", color: "orange" },
  approved: { label: "已通过", color: "green" },
  rejected: { label: "已驳回", color: "red" },
};
const otTag = (s: string) => {
  const m = OT_META[s] || { label: s, color: "default" };
  return <Tag color={m.color}>{m.label}</Tag>;
};

const hm = (v: string | null) => (v ? dayjs(v).format("HH:mm") : "—");
const hours = (min: number) => (min / 60).toFixed(1);

/** 月份最后一天（供全员记录区间默认值，避免硬编码 31 号） */
const lastDay = (m: Dayjs) => m.endOf("month");

export default function Attendance() {
  const qc = useQueryClient();
  const { hasPerm } = useAuth();
  const canManage = hasPerm("att:manage");

  const [month, setMonth] = useState<Dayjs>(dayjs());
  const monthStr = month.format("YYYY-MM");

  // ---- 查询 ----
  const settingsQ = useQuery({
    queryKey: ["att-settings"],
    queryFn: attendanceApi.settings,
  });
  const meQ = useQuery({
    queryKey: ["att-me", monthStr],
    queryFn: () => attendanceApi.me(monthStr),
  });
  const otQ = useQuery({
    queryKey: ["att-overtime"],
    queryFn: () => attendanceApi.overtime({}),
  });

  // 管理区
  const [range, setRange] = useState<[Dayjs, Dayjs]>([
    month.startOf("month"),
    lastDay(month),
  ]);
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [page, setPage] = useState(1);
  const pageSize = 20;
  const recordsQ = useQuery({
    queryKey: ["att-records", range[0].format("YYYY-MM-DD"), range[1].format("YYYY-MM-DD"), statusFilter, page],
    queryFn: () =>
      attendanceApi.records({
        start: range[0].format("YYYY-MM-DD"),
        end: range[1].format("YYYY-MM-DD"),
        ...(statusFilter ? { status: statusFilter } : {}),
        offset: (page - 1) * pageSize,
        limit: pageSize,
      }),
    enabled: canManage,
  });
  const statsQ = useQuery({
    queryKey: ["att-stats", monthStr],
    queryFn: () => attendanceApi.stats(monthStr),
    enabled: canManage,
  });
  const pendingOtQ = useQuery({
    queryKey: ["att-overtime-pending"],
    queryFn: () => attendanceApi.overtime({ all: true, status: "pending" }),
    enabled: canManage,
  });

  // ---- 外勤申请 ----
  const [fieldWorkPage, setFieldWorkPage] = useState(1);
  const fieldWorkQ = useQuery({
    queryKey: ["att-field-work", fieldWorkPage],
    queryFn: () => attendanceApi.fieldWork({ offset: (fieldWorkPage - 1) * 10, limit: 10 }),
    enabled: canManage,
  });

  // ---- 异常预警 ----
  const [alertRange, setAlertRange] = useState<[Dayjs, Dayjs]>([
    dayjs().startOf("month"),
    dayjs(),
  ]);
  const alertsQ = useQuery({
    queryKey: ["att-alerts", alertRange[0].format("YYYY-MM-DD"), alertRange[1].format("YYYY-MM-DD")],
    queryFn: () =>
      attendanceApi.alerts({
        start: alertRange[0].format("YYYY-MM-DD"),
        end: alertRange[1].format("YYYY-MM-DD"),
        threshold: 3,
      }),
    enabled: canManage,
  });

  // ---- 弹窗 ----
  const [otOpen, setOtOpen] = useState(false);
  const [settingOpen, setSettingOpen] = useState(false);
  const [fixTarget, setFixTarget] = useState<AttendanceRecord | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importPreview, setImportPreview] = useState<any>(null);
  const [fieldWorkOpen, setFieldWorkOpen] = useState(false);
  const [fieldWorkForm] = Form.useForm();
  const [otForm] = Form.useForm();
  const [settingForm] = Form.useForm();
  const [fixForm] = Form.useForm();

  const invalidate = (keys: string[][]) =>
    keys.forEach((k) => qc.invalidateQueries({ queryKey: k }));

  const clockM = useMutation({
    mutationFn: (params?: { lat?: number; lng?: number; address?: string; is_field_work?: boolean; field_work_address?: string; field_work_note?: string }) =>
      attendanceApi.clock(params),
    onSuccess: (res) => {
      message.success(res.message);
      invalidate([["att-me"], ["att-records"], ["att-stats"]]);
    },
    onError: (e: any) => message.error(e?.message || "打卡失败"),
  });

  const otM = useMutation({
    mutationFn: (v: { day: string; hours: number; reason: string }) =>
      attendanceApi.createOvertime(v),
    onSuccess: () => {
      message.success("加班申请已提交");
      setOtOpen(false);
      otForm.resetFields();
      invalidate([["att-overtime"], ["att-me"]]);
    },
    onError: (e: any) => message.error(e?.message || "提交失败"),
  });

  const reviewM = useMutation({
    mutationFn: (v: { id: number; approve: boolean; comment?: string }) =>
      attendanceApi.reviewOvertime(v.id, { approve: v.approve, comment: v.comment }),
    onSuccess: () => {
      message.success("已处理");
      invalidate([["att-overtime"], ["att-overtime-pending"], ["att-stats"]]);
    },
    onError: (e: any) => message.error(e?.message || "处理失败"),
  });

  const fixM = useMutation({
    mutationFn: (v: {
      id: number;
      body: { status?: string; note?: string; check_in?: string; check_out?: string };
    }) => attendanceApi.updateRecord(v.id, v.body),
    onSuccess: () => {
      message.success("已修正");
      setFixTarget(null);
      invalidate([["att-records"], ["att-stats"], ["att-me"]]);
    },
    onError: (e: any) => message.error(e?.message || "修正失败"),
  });

  const settingM = useMutation({
    mutationFn: (v: any) => {
      const body: AttendanceSettingsUpdate = {
        name: v.name,
        work_start: v.work_start ? v.work_start.format("HH:mm") : undefined,
        work_end: v.work_end ? v.work_end.format("HH:mm") : undefined,
        late_grace_minutes: v.late_grace_minutes,
        workdays: v.workdays,
      };
      return attendanceApi.updateSettings(body);
    },
    onSuccess: () => {
      message.success("班次设置已保存");
      setSettingOpen(false);
      invalidate([["att-settings"], ["att-me"], ["att-stats"]]);
    },
    onError: (e: any) => message.error(e?.message || "保存失败"),
  });

  const exportM = useMutation({
    mutationFn: () => attendanceApi.exportMonth(monthStr),
    onSuccess: () => message.success("导出成功"),
    onError: (e: any) => message.error(e?.message || "导出失败"),
  });

  // ---- 导入 ----
  const importPreviewM = useMutation({
    mutationFn: (file: File) => attendanceApi.importPreview(file),
    onSuccess: (data) => {
      setImportPreview(data);
    },
    onError: (e: any) => message.error(e?.message || "预检失败"),
  });

  const importM = useMutation({
    mutationFn: (file: File) => attendanceApi.importMonth(file),
    onSuccess: (data) => {
      message.success(`导入完成：新增 ${data.created} 条，更新 ${data.updated} 条`);
      setImportOpen(false);
      setImportFile(null);
      setImportPreview(null);
      invalidate([["att-records"], ["att-stats"]]);
    },
    onError: (e: any) => message.error(e?.message || "导入失败"),
  });

  // ---- 外勤申请 ----
  const fieldWorkM = useMutation({
    mutationFn: (body: any) => attendanceApi.createFieldWork(body),
    onSuccess: () => {
      message.success("外勤申请已提交");
      setFieldWorkOpen(false);
      fieldWorkForm.resetFields();
      invalidate([["att-field-work"]]);
    },
    onError: (e: any) => message.error(e?.message || "提交失败"),
  });

  const reviewFieldWorkM = useMutation({
    mutationFn: (v: { id: number; approve: boolean; comment?: string }) =>
      attendanceApi.reviewFieldWork(v.id, { approve: v.approve, comment: v.comment }),
    onSuccess: () => {
      message.success("已处理");
      invalidate([["att-field-work"]]);
    },
    onError: (e: any) => message.error(e?.message || "处理失败"),
  });

  const openSettings = () => {
    const s = settingsQ.data;
    settingForm.setFieldsValue({
      name: s?.name ?? "标准班次",
      work_start: dayjs(s?.work_start ?? "09:00", "HH:mm"),
      work_end: dayjs(s?.work_end ?? "18:00", "HH:mm"),
      late_grace_minutes: s?.late_grace_minutes ?? 0,
      workdays: s?.workdays ?? [1, 2, 3, 4, 5],
    });
    setSettingOpen(true);
  };

  const summary = meQ.data?.summary;
  const today = dayjs().format("YYYY-MM-DD");
  const todayRec = meQ.data?.records?.find((r) => r.day === today);

  // ---- 我的考勤列 ----
  const myColumns = [
    { title: "日期", dataIndex: "day" },
    { title: "上班", render: (_: unknown, r: AttendanceRecord) => hm(r.check_in) },
    { title: "下班", render: (_: unknown, r: AttendanceRecord) => hm(r.check_out) },
    { title: "状态", dataIndex: "status", render: (v: string) => statusTag(v) },
    { title: "迟到(分)", dataIndex: "late_minutes" },
    { title: "早退(分)", dataIndex: "early_minutes" },
    {
      title: "工时(h)",
      dataIndex: "work_minutes",
      render: (v: number) => (v ? hours(v) : "—"),
    },
    { title: "来源", dataIndex: "source", render: (v: string) => (v === "manual" ? "人工" : "打卡") },
    { title: "备注", dataIndex: "note", render: (v: string) => v || "—" },
  ];

  // ---- 全员考勤列 ----
  const allColumns = [
    { title: "日期", dataIndex: "day" },
    { title: "姓名", dataIndex: "user_name" },
    { title: "状态", dataIndex: "status", render: (v: string) => statusTag(v) },
    { title: "上班", render: (_: unknown, r: AttendanceRecord) => hm(r.check_in) },
    { title: "下班", render: (_: unknown, r: AttendanceRecord) => hm(r.check_out) },
    { title: "迟到(分)", dataIndex: "late_minutes" },
    { title: "早退(分)", dataIndex: "early_minutes" },
    { title: "备注", dataIndex: "note", render: (v: string) => v || "—" },
    { title: "打卡位置", render: (_: unknown, r: AttendanceRecord) => {
      if (r.check_in_address) return r.check_in_address;
      if (r.check_in_lat && r.check_in_lng) return `${r.check_in_lat.toFixed(4)}, ${r.check_in_lng.toFixed(4)}`;
      return "—";
    }},
    { title: "外勤", render: (_: unknown, r: AttendanceRecord) => r.is_field_work ? "是" : "否" },
    { title: "备注", dataIndex: "note", render: (v: string) => v || "—" },
    {
      title: "操作",
      render: (_: unknown, r: AttendanceRecord) => (
        <Button
          size="small"
          icon={<EditOutlined />}
          onClick={() => {
            fixForm.setFieldsValue({
              status: r.status,
              note: r.note,
              check_in: r.check_in ? dayjs(r.check_in) : undefined,
              check_out: r.check_out ? dayjs(r.check_out) : undefined,
            });
            setFixTarget(r);
          }}
        >
          修正
        </Button>
      ),
    },
  ];

  const statColumns = [
    { title: "姓名", dataIndex: "full_name" },
    { title: "用户名", dataIndex: "username" },
    { title: "出勤", dataIndex: "present_days" },
    { title: "迟到", dataIndex: "late_days" },
    { title: "早退", dataIndex: "early_days" },
    { title: "缺勤", dataIndex: "absent_days" },
    { title: "请假", dataIndex: "leave_days" },
    { title: "加班(h)", dataIndex: "overtime_hours" },
  ];

  const otColumns = [
    { title: "日期", dataIndex: "day" },
    { title: "时长(h)", dataIndex: "hours" },
    { title: "事由", dataIndex: "reason", render: (v: string) => v || "—" },
    { title: "状态", dataIndex: "status", render: (v: string) => otTag(v) },
    { title: "审批意见", dataIndex: "review_comment", render: (v: string) => v || "—" },
  ];

  const pendingColumns = [
    { title: "申请人", dataIndex: "user_name" },
    { title: "日期", dataIndex: "day" },
    { title: "时长(h)", dataIndex: "hours" },
    { title: "事由", dataIndex: "reason", render: (v: string) => v || "—" },
    {
      title: "操作",
      render: (_: unknown, r: Overtime) => (
        <Space>
          <Popconfirm title="通过该加班申请？" onConfirm={() => reviewM.mutate({ id: r.id, approve: true, comment: "同意" })}>
            <Button size="small" type="primary">通过</Button>
          </Popconfirm>
          <Popconfirm title="驳回该加班申请？" onConfirm={() => reviewM.mutate({ id: r.id, approve: false, comment: "未通过" })}>
            <Button size="small" danger>驳回</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const managePane = (
    <div>
      <Space style={{ marginBottom: 12 }} wrap>
        <DatePicker.RangePicker
          value={range}
          allowClear={false}
          onChange={(v) => {
            if (v && v[0] && v[1]) setRange([v[0], v[1]]);
          }}
        />
        <Select
          style={{ width: 140 }}
          allowClear
          placeholder="状态"
          value={statusFilter}
          onChange={(v) => {
            setStatusFilter(v);
            setPage(1);
          }}
          options={Object.entries(STATUS_META).map(([value, m]) => ({ value, label: m.label }))}
        />
        <Button
          onClick={() => {
            setRange([month.startOf("month"), lastDay(month)]);
            setStatusFilter(undefined);
            setPage(1);
          }}
        >
          重置
        </Button>
        <Button
          icon={<DownloadOutlined />}
          loading={exportM.isPending}
          onClick={() => exportM.mutate()}
        >
          导出 Excel
        </Button>
        <Button icon={<SettingOutlined />} onClick={openSettings}>
          班次设置
        </Button>
        <Button
          icon={<DownloadOutlined />}
          onClick={() => attendanceApi.downloadTemplate()}
        >
          导入模板
        </Button>
        <Button
          icon={<UploadOutlined />}
          onClick={() => setImportOpen(true)}
        >
          批量导入
        </Button>
        <Button
          icon={<WarningOutlined />}
          onClick={() => {
            const m = dayjs();
            setAlertRange([m.startOf("month"), m]);
          }}
        >
          异常预警
        </Button>
      </Space>

      <Tabs
        items={[
          {
            key: "records",
            label: "全员考勤",
            children: (
              <Table
                rowKey="id"
                size="small"
                loading={recordsQ.isLoading}
                dataSource={recordsQ.data?.items || []}
                columns={allColumns}
                pagination={{
                  current: page,
                  pageSize,
                  total: recordsQ.data?.total || 0,
                  onChange: (p) => setPage(p),
                  showSizeChanger: false,
                }}
              />
            ),
          },
          {
            key: "stats",
            label: `月度统计（待审批加班 ${statsQ.data?.pending_overtime ?? pendingOtQ.data?.length ?? 0}）`,
            children: (
              <Table
                rowKey="user_id"
                size="small"
                loading={statsQ.isLoading}
                dataSource={statsQ.data?.rows || []}
                columns={statColumns}
                pagination={false}
              />
            ),
          },
          {
            key: "overtime",
            label: `加班审批（${pendingOtQ.data?.length ?? 0}）`,
            children: (
              <Table
                rowKey="id"
                size="small"
                loading={pendingOtQ.isLoading}
                dataSource={pendingOtQ.data || []}
                columns={pendingColumns}
                pagination={false}
              />
            ),
          },
          {
            key: "field-work",
            label: `外勤申请（${fieldWorkQ.data?.total ?? 0}）`,
            children: (
              <div>
                <Space style={{ marginBottom: 12 }}>
                  <Button type="primary" onClick={() => setFieldWorkOpen(true)}>
                    新建外勤申请
                  </Button>
                </Space>
                <Table
                  rowKey="id"
                  size="small"
                  loading={fieldWorkQ.isLoading}
                  dataSource={fieldWorkQ.data?.items || []}
                  columns={[
                    { title: "申请人", dataIndex: "user_name" },
                    { title: "开始日期", dataIndex: "start_date" },
                    { title: "结束日期", dataIndex: "end_date" },
                    { title: "地点", dataIndex: "address" },
                    { title: "事由", dataIndex: "purpose", ellipsis: true },
                    {
                      title: "状态",
                      dataIndex: "status",
                      render: (v: string) => (
                        <Tag color={v === "approved" ? "green" : v === "rejected" ? "red" : "orange"}>
                          {v === "approved" ? "已通过" : v === "rejected" ? "已驳回" : "待审批"}
                        </Tag>
                      ),
                    },
                    {
                      title: "操作",
                      render: (_: unknown, r: FieldWorkOrder) =>
                        r.status === "pending" ? (
                          <Space>
                            <Popconfirm
                              title="通过该外勤申请？"
                              onConfirm={() =>
                                reviewFieldWorkM.mutate({ id: r.id, approve: true, comment: "同意" })
                              }
                            >
                              <Button size="small" type="primary">通过</Button>
                            </Popconfirm>
                            <Popconfirm
                              title="驳回该外勤申请？"
                              onConfirm={() =>
                                reviewFieldWorkM.mutate({ id: r.id, approve: false, comment: "未通过" })
                              }
                            >
                              <Button size="small" danger>驳回</Button>
                            </Popconfirm>
                          </Space>
                        ) : null,
                    },
                  ]}
                  pagination={{
                    current: fieldWorkPage,
                    pageSize: 10,
                    total: fieldWorkQ.data?.total || 0,
                    onChange: setFieldWorkPage,
                  }}
                />
              </div>
            ),
          },
          {
            key: "alerts",
            label: `异常预警（${alertsQ.data?.total ?? 0}）`,
            children: (
              <div>
                <Space style={{ marginBottom: 12 }}>
                  <DatePicker.RangePicker
                    value={alertRange}
                    onChange={(v) => {
                      if (v && v[0] && v[1]) setAlertRange([v[0], v[1]]);
                    }}
                  />
                </Space>
                <Table
                  rowKey={(r, i) => `${r.type}-${r.user_id}-${i}`}
                  size="small"
                  loading={alertsQ.isLoading}
                  dataSource={alertsQ.data?.alerts || []}
                  columns={[
                    {
                      title: "级别",
                      dataIndex: "level",
                      width: 80,
                      render: (v: string) => (
                        <Tag color={v === "high" ? "red" : v === "medium" ? "orange" : "blue"}>
                          {v === "high" ? "高" : v === "medium" ? "中" : "低"}
                        </Tag>
                      ),
                    },
                    { title: "员工", dataIndex: "user_name" },
                    { title: "类型", dataIndex: "type", width: 120 },
                    { title: "日期/周期", dataIndex: "day", render: (v: string, r: AttendanceAlert) => v || r.period || "—" },
                    { title: "次数", dataIndex: "count", width: 60 },
                    { title: "说明", dataIndex: "message", ellipsis: true },
                  ]}
                  pagination={false}
                />
              </div>
            ),
          },
        ]}
      />
    </div>
  );

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
        <Space>
          <h2 style={{ margin: 0 }}>考勤打卡</h2>
          <DatePicker
            picker="month"
            value={month}
            allowClear={false}
            onChange={(v) => {
              if (v) {
                setMonth(v);
                setRange([v.startOf("month"), lastDay(v)]);
                setPage(1);
              }
            }}
          />
        </Space>
        <Space>
          <Button
            type="primary"
            icon={<ClockCircleOutlined />}
            loading={clockM.isPending}
            onClick={() => {
              if (navigator.geolocation) {
                navigator.geolocation.getCurrentPosition(
                  (position) => {
                    clockM.mutate({
                      lat: position.coords.latitude,
                      lng: position.coords.longitude,
                    });
                  },
                  (error) => {
                    message.error(`获取定位失败: ${error.message}`);
                    // 降级到普通打卡
                    clockM.mutate();
                  },
                  { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
                );
              } else {
                message.error("浏览器不支持地理定位，降级为普通打卡");
                clockM.mutate();
              }
            }}
            >
              打卡
            </Button>
            <Button
              icon={<ClockCircleOutlined />}
              onClick={() => clockM.mutate()}
            >
              普通打卡
            </Button>
        </Space>
      </div>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message={
          todayRec
            ? `今日：上班 ${hm(todayRec.check_in)}　下班 ${hm(todayRec.check_out)}　状态 ${
                STATUS_META[todayRec.status]?.label || todayRec.status
              }`
            : "今日尚未打卡"
        }
        description={
          summary
            ? `班次 ${
                settingsQ.data ? `${settingsQ.data.work_start} - ${settingsQ.data.work_end}` : "加载中"
              }，迟到宽限 ${settingsQ.data?.late_grace_minutes ?? 0} 分钟`
            : undefined
        }
      />

      <Row gutter={12} style={{ marginBottom: 16 }}>
        {[
          { title: "应出勤(天)", value: summary?.expected_workdays ?? 0 },
          { title: "实出勤(天)", value: summary?.present_days ?? 0 },
          { title: "迟到(次)", value: summary?.late_days ?? 0 },
          { title: "早退(次)", value: summary?.early_days ?? 0 },
          { title: "缺勤(天)", value: summary?.absent_days ?? 0 },
          { title: "加班(小时)", value: summary?.overtime_hours ?? 0 },
        ].map((it) => (
          <Col span={4} key={it.title}>
            <Card size="small">
              <Statistic title={it.title} value={it.value} />
            </Card>
          </Col>
        ))}
      </Row>

      <Card
        title="我的考勤"
        size="small"
        style={{ marginBottom: 16 }}
        extra={
          <Button size="small" onClick={() => setOtOpen(true)}>
            申请加班
          </Button>
        }
      >
        <Table
          rowKey="id"
          size="small"
          loading={meQ.isLoading}
          dataSource={meQ.data?.records || []}
          columns={myColumns}
          pagination={false}
          locale={{ emptyText: "本月暂无考勤记录，点击右上角打卡" }}
        />
      </Card>

      <Card title="我的加班申请" size="small">
        <Table
          rowKey="id"
          size="small"
          loading={otQ.isLoading}
          dataSource={otQ.data || []}
          columns={otColumns}
          pagination={false}
        />
      </Card>

      {canManage && (
        <Card title="考勤管理" size="small" style={{ marginTop: 16 }}>
          {managePane}
        </Card>
      )}

      {/* 加班申请 */}
      <Modal
        title="申请加班"
        open={otOpen}
        onCancel={() => setOtOpen(false)}
        onOk={() => otForm.submit()}
        okText="提交"
        destroyOnHidden
      >
        <Form
          form={otForm}
          layout="vertical"
          onFinish={(v) =>
            otM.mutate({
              day: (v.day as Dayjs).format("YYYY-MM-DD"),
              hours: v.hours,
              reason: v.reason || "",
            })
          }
        >
          <Form.Item name="day" label="加班日期" rules={[{ required: true, message: "请选择日期" }]}>
            <DatePicker style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="hours" label="时长（小时）" rules={[{ required: true, message: "请填写时长" }]}>
            <InputNumber min={0.5} max={24} step={0.5} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="reason" label="事由">
            <Input.TextArea rows={3} maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 班次设置 */}
      <Modal
        title="班次设置"
        open={settingOpen}
        onCancel={() => setSettingOpen(false)}
        onOk={() => settingForm.submit()}
        okText="保存"
        destroyOnHidden
      >
        <Form form={settingForm} layout="vertical" onFinish={(v) => settingM.mutate(v)}>
          <Form.Item name="name" label="班次名称">
            <Input maxLength={60} />
          </Form.Item>
          <Row gutter={12}>
            <Col span={8}>
              <Form.Item name="work_start" label="上班时间" rules={[{ required: true }]}>
                <TimePicker format="HH:mm" style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="work_end" label="下班时间" rules={[{ required: true }]}>
                <TimePicker format="HH:mm" style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="late_grace_minutes" label="迟到宽限(分)">
                <InputNumber min={0} max={120} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="workdays"
            label="工作日"
            rules={[{ required: true, message: "至少选择一个工作日" }]}
          >
            <Checkbox.Group
              options={[1, 2, 3, 4, 5, 6, 7].map((d) => ({
                value: d,
                label: `周${["一", "二", "三", "四", "五", "六", "日"][d - 1]}`,
              }))}
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* 人工修正 */}
      <Modal
        title={`修正考勤 · ${fixTarget?.user_name || ""} ${fixTarget?.day || ""}`}
        open={!!fixTarget}
        onCancel={() => setFixTarget(null)}
        onOk={() => fixForm.submit()}
        okText="保存"
        destroyOnHidden
      >
        <Form
          form={fixForm}
          layout="vertical"
          onFinish={(v) =>
            fixTarget &&
            fixM.mutate({
              id: fixTarget.id,
              body: {
                status: v.status,
                note: v.note,
                check_in: v.check_in ? (v.check_in as Dayjs).format("YYYY-MM-DDTHH:mm:ss") : undefined,
                check_out: v.check_out ? (v.check_out as Dayjs).format("YYYY-MM-DDTHH:mm:ss") : undefined,
              },
            })
          }
        >
          <Form.Item name="status" label="状态" rules={[{ required: true }]}>
            <Select
              options={Object.entries(STATUS_META).map(([value, m]) => ({ value, label: m.label }))}
            />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="check_in" label="上班时间">
                <DatePicker showTime style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="check_out" label="下班时间">
                <DatePicker showTime style={{ width: "100%" }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="note" label="备注">
            <Input maxLength={200} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 批量导入 */}
      <Modal
        title="批量导入考勤"
        open={importOpen}
        onCancel={() => {
          setImportOpen(false);
          setImportFile(null);
          setImportPreview(null);
        }}
        footer={[
          <Button key="cancel" onClick={() => { setImportOpen(false); setImportFile(null); setImportPreview(null); }}>
            取消
          </Button>,
          importPreview ? (
            <Button
              key="confirm"
              type="primary"
              loading={importM.isPending}
              onClick={() => importFile && importM.mutate(importFile)}
            >
              确认导入（{importPreview.total} 行）
            </Button>
          ) : (
            <Button
              key="preview"
              type="primary"
              loading={importPreviewM.isPending}
              disabled={!importFile}
              onClick={() => importFile && importPreviewM.mutate(importFile)}
            >
              预检
            </Button>
          ),
        ]}
        width={640}
      >
        <Upload.Dragger
          accept=".xlsx,.xls"
          maxCount={1}
          beforeUpload={(file) => {
            setImportFile(file);
            setImportPreview(null);
            return false;
          }}
          onRemove={() => {
            setImportFile(null);
            setImportPreview(null);
          }}
        >
          <p className="ant-upload-drag-icon"><UploadOutlined /></p>
          <p className="ant-upload-text">点击或拖拽 Excel 文件到此处</p>
        </Upload.Dragger>
        {importPreview && (
          <div style={{ marginTop: 16 }}>
            <Alert
              type={importPreview.errors?.length ? "warning" : "success"}
              showIcon
              message={`预检结果：将导入 ${importPreview.total} 行，新增 ${importPreview.created} 条，更新 ${importPreview.updated} 条`}
              description={
                importPreview.errors?.length ? (
                  <ul style={{ margin: 0, paddingLeft: 16 }}>
                    {importPreview.errors.slice(0, 10).map((e: string, i: number) => (
                      <li key={i}>{e}</li>
                    ))}
                    {importPreview.errors.length > 10 && <li>...还有 {importPreview.errors.length - 10} 条错误</li>}
                  </ul>
                ) : null
              }
            />
          </div>
        )}
      </Modal>

      {/* 新建外勤申请 */}
      <Modal
        title="新建外勤申请"
        open={fieldWorkOpen}
        onCancel={() => { setFieldWorkOpen(false); fieldWorkForm.resetFields(); }}
        onOk={() => fieldWorkForm.submit()}
        okText="提交"
        destroyOnHidden
      >
        <Form
          form={fieldWorkForm}
          layout="vertical"
          onFinish={(v) => fieldWorkM.mutate({
            start_date: (v.start_date as Dayjs).format("YYYY-MM-DD"),
            end_date: (v.end_date as Dayjs).format("YYYY-MM-DD"),
            address: v.address,
            purpose: v.purpose || "",
            remark: v.remark || "",
          })}
        >
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="start_date" label="开始日期" rules={[{ required: true }]}>
                <DatePicker style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="end_date" label="结束日期" rules={[{ required: true }]}>
                <DatePicker style={{ width: "100%" }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="address" label="外勤地点" rules={[{ required: true, message: "请填写外勤地点" }]}>
            <Input maxLength={500} />
          </Form.Item>
          <Form.Item name="purpose" label="事由">
            <Input maxLength={300} />
          </Form.Item>
          <Form.Item name="remark" label="备注">
            <Input.TextArea rows={3} maxLength={1000} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
