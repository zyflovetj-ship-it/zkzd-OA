import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Divider,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Switch,
  Table,
  Tag,
  Upload,
  message,
  type TableColumnsType,
} from "antd";
import {
  AuditOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  EyeOutlined,
  FileOutlined,
  PlusOutlined,
  SafetyCertificateOutlined,
  SearchOutlined,
  SendOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import dayjs, { type Dayjs } from "dayjs";
import { useNavigate } from "react-router-dom";
import {
  expensesApi,
  type Budget,
  type Expense,
  type ExpenseAttachment,
  type ExpenseClaimType,
  type ExpenseInput,
  type ExpenseStatus,
  type InvoiceVerifyResult,
} from "../api/expenses";
import { useAuth } from "../auth/AuthContext";

// ---------- 展示字典 ----------
const STATUS_META: Record<string, { label: string; color: string }> = {
  draft: { label: "草稿", color: "default" },
  submitted: { label: "审批中", color: "processing" },
  approved: { label: "已通过", color: "success" },
  rejected: { label: "已驳回", color: "error" },
  paid: { label: "已打款", color: "purple" },
};

const TYPE_LABELS: Record<string, string> = {
  travel: "差旅",
  daily: "日常",
  entertain: "招待",
  other: "其他",
};

const STATUS_OPTIONS: { value: ExpenseStatus | "all"; label: string }[] = [
  { value: "all", label: "全部状态" },
  { value: "draft", label: "草稿" },
  { value: "submitted", label: "审批中" },
  { value: "approved", label: "已通过" },
  { value: "rejected", label: "已驳回" },
  { value: "paid", label: "已打款" },
];

const TYPE_OPTIONS: { value: ExpenseClaimType; label: string }[] = [
  { value: "travel", label: "差旅" },
  { value: "daily", label: "日常" },
  { value: "entertain", label: "招待" },
  { value: "other", label: "其他" },
];

interface FilterState {
  status: ExpenseStatus | "all";
  month: string; // YYYY-MM，空串表示不限
  q: string;
  mine: boolean;
}

const DEFAULT_FILTERS: FilterState = { status: "all", month: "", q: "", mine: true };

interface ExpenseFormValues {
  claim_type: ExpenseClaimType;
  amount: number;
  occur_date: Dayjs;
  description?: string;
  attachments?: number[];
}

// 预算表单值
interface BudgetFormValues {
  name: string;
  code: string;
  total_amount: number;
  range: [Dayjs, Dayjs];
  category?: ExpenseClaimType | null;
  status?: "active" | "inactive" | "expired";
}

// 发票验真表单值
interface VerifyFormValues {
  invoice_no: string;
  invoice_code?: string;
  amount?: number;
  buyer_tax_no?: string;
}

// 验真检查项中文名
const CHECK_LABELS: Record<string, string> = {
  format: "发票号码格式",
  code_format: "发票代码格式",
  buyer_tax_no: "买方税号校验位",
  uniqueness: "唯一性（未被占用）",
  amount: "金额",
};

// 千分位金额
const money = (n: number) =>
  Number(n || 0).toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

const fmtTime = (v: string) => (v ? v.replace("T", " ").slice(0, 16) : "-");

// ApiError 是 Error 子类，message 为中文提示
const errText = (e: unknown, fallback: string): string =>
  e instanceof Error && e.message ? e.message : fallback;

const statusTag = (s: string) => {
  const m = STATUS_META[s] ?? { label: s, color: "default" };
  return <Tag color={m.color}>{m.label}</Tag>;
};

export default function Expenses() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { hasPerm } = useAuth();
  const canManage = hasPerm("expense:manage");

  // 筛选：draft 供控件编辑，点「查询」后写入 filters（驱动查询）
  const [draft, setDraft] = useState<FilterState>(DEFAULT_FILTERS);
  const [filters, setFilters] = useState<FilterState>(DEFAULT_FILTERS);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Expense | null>(null);
  const [viewing, setViewing] = useState<Expense | null>(null);
  const [exporting, setExporting] = useState(false);
  const [form] = Form.useForm<ExpenseFormValues>();

  // 额度 / 验真 / 批量打款
  const [budgetOpen, setBudgetOpen] = useState(false);
  const [budgetModalOpen, setBudgetModalOpen] = useState(false);
  const [editingBudget, setEditingBudget] = useState<Budget | null>(null);
  const [verifyOpen, setVerifyOpen] = useState(false);
  const [verifyResult, setVerifyResult] = useState<InvoiceVerifyResult | null>(null);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [budgetForm] = Form.useForm<BudgetFormValues>();
  const [verifyForm] = Form.useForm<VerifyFormValues>();

  // 无 expense:manage 权限：后端固定只返回本人数据
  const mine = canManage ? filters.mine : true;

  const listQ = useQuery({
    queryKey: ["expenses", filters, page, pageSize],
    queryFn: () =>
      expensesApi.list({
        status: filters.status === "all" ? undefined : filters.status,
        month: filters.month || undefined,
        q: filters.q || undefined,
        mine,
        offset: (page - 1) * pageSize,
        limit: pageSize,
      }),
  });

  const statsQ = useQuery({
    queryKey: ["expenses-stats", filters.month],
    queryFn: () => expensesApi.stats(filters.month || undefined),
    enabled: canManage,
  });

  const docsQ = useQuery({
    queryKey: ["expense-doc-options"],
    queryFn: () => expensesApi.docOptions(),
    enabled: modalOpen,
  });

  // 预算列表：打开额度抽屉时才拉取（仅 expense:manage）
  const budgetsQ = useQuery({
    queryKey: ["expense-budgets"],
    queryFn: () => expensesApi.budgets({ limit: 100 }),
    enabled: budgetOpen && canManage,
  });

  // 报销单填写过程中的额度预检（金额/类型/日期齐了才查）
  const watchAmount = Form.useWatch("amount", form);
  const watchDate = Form.useWatch("occur_date", form);
  const watchType = Form.useWatch("claim_type", form);
  const quotaQ = useQuery({
    queryKey: ["expense-quota", watchAmount, watchDate?.toISOString?.(), watchType],
    queryFn: () =>
      expensesApi.quotaCheck({
        amount: Number(watchAmount || 0),
        occur_date: (watchDate as Dayjs).format("YYYY-MM-DD"),
        category: watchType,
      }),
    enabled:
      modalOpen &&
      Number(watchAmount || 0) > 0 &&
      !!watchDate &&
      !editing, // 编辑的是草稿，额度以提交时为准
    staleTime: 5_000,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["expenses"] });
    qc.invalidateQueries({ queryKey: ["expenses-stats"] });
  };

  const saveM = useMutation({
    mutationFn: (vars: { id: number | null; body: ExpenseInput }) =>
      vars.id === null ? expensesApi.create(vars.body) : expensesApi.update(vars.id, vars.body),
    onSuccess: (_data, vars) => {
      invalidate();
      setModalOpen(false);
      setEditing(null);
      form.resetFields();
      message.success(vars.id === null ? "报销单已创建" : "报销单已保存");
    },
    onError: (e) => message.error(errText(e, "保存失败")),
  });

  const submitM = useMutation({
    mutationFn: (id: number) => expensesApi.submit(id),
    onSuccess: () => {
      invalidate();
      message.success("已提交，进入审批流程");
    },
    onError: (e) => message.error(errText(e, "提交失败")),
  });

  const removeM = useMutation({
    mutationFn: (id: number) => expensesApi.remove(id),
    onSuccess: () => {
      invalidate();
      message.success("报销单已删除");
    },
    onError: (e) => message.error(errText(e, "删除失败")),
  });

  const payM = useMutation({
    mutationFn: (vars: { id: number; paid: boolean }) =>
      expensesApi.markPaid(vars.id, { paid: vars.paid }),
    onSuccess: (_data, vars) => {
      invalidate();
      message.success(vars.paid ? "已标记打款" : "已撤销打款");
    },
    onError: (e) => message.error(errText(e, "打款处理失败")),
  });

  const importM = useMutation({
    mutationFn: (file: File) => expensesApi.importExcel(file),
    onSuccess: (res) => {
      invalidate();
      if (res.created > 0) message.success(`成功导入 ${res.created} 条报销草稿`);
      else message.warning("未导入任何数据，请检查表头是否包含：金额、日期、类型、说明");
      if (res.errors.length > 0) {
        message.warning(`部分行导入失败（${res.errors.length} 条）：${res.errors[0]}`);
      }
    },
    onError: (e) => message.error(errText(e, "导入失败")),
  });

  // ---- 批量打款：逐条处理，返回明细 ----
  const batchPayM = useMutation({
    mutationFn: (ids: number[]) => expensesApi.batchPay(ids),
    onSuccess: (res) => {
      invalidate();
      setSelectedIds([]);
      if (res.failed === 0) {
        message.success(`批量打款完成：${res.success} 笔已打款`);
      } else {
        const firstErr = res.results.find((r) => !r.success);
        message.warning(
          `成功 ${res.success} 笔 / 失败 ${res.failed} 笔` +
            (firstErr ? `，如：${firstErr.error}` : "")
        );
      }
    },
    onError: (e) => message.error(errText(e, "批量打款失败")),
  });

  // ---- 预算新建 / 编辑 ----
  const saveBudgetM = useMutation({
    mutationFn: (vars: { id: number | null; body: Parameters<typeof expensesApi.createBudget>[0] }) =>
      vars.id === null
        ? expensesApi.createBudget(vars.body)
        : expensesApi.updateBudget(vars.id, vars.body),
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({ queryKey: ["expense-budgets"] });
      qc.invalidateQueries({ queryKey: ["expense-quota"] });
      setBudgetModalOpen(false);
      setEditingBudget(null);
      budgetForm.resetFields();
      message.success(vars.id === null ? "预算已创建" : "预算已更新");
    },
    onError: (e) => message.error(errText(e, "保存预算失败")),
  });

  // ---- 发票验真（本地校验，不做税务库核验）----
  const verifyM = useMutation({
    mutationFn: (body: Parameters<typeof expensesApi.verifyInvoice>[0]) =>
      expensesApi.verifyInvoice(body),
    onSuccess: (res) => setVerifyResult(res),
    onError: (e) => message.error(errText(e, "验真失败")),
  });

  const applyFilters = () => {
    setFilters(draft);
    setPage(1);
  };

  const resetFilters = () => {
    setDraft(DEFAULT_FILTERS);
    setFilters(DEFAULT_FILTERS);
    setPage(1);
  };

  const toggleMine = (checked: boolean) => {
    setDraft((d) => ({ ...d, mine: checked }));
    setFilters((f) => ({ ...f, mine: checked }));
    setPage(1);
  };

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (r: Expense) => {
    setEditing(r);
    form.setFieldsValue({
      claim_type: r.claim_type,
      amount: r.amount,
      occur_date: dayjs(r.occur_date),
      description: r.description,
      attachments: r.attachments.map((a) => a.document_id),
    });
    setModalOpen(true);
  };

  const onFinish = (v: ExpenseFormValues) => {
    if (!v.occur_date) {
      message.warning("请选择费用发生日期");
      return;
    }
    if (!v.amount || v.amount <= 0) {
      message.warning("报销金额必须大于 0");
      return;
    }
    // 文档中心选项 → {document_id,title,file_url}；不在候选项内的沿用原附件快照
    const docs = docsQ.data?.items ?? [];
    const prev = editing?.attachments ?? [];
    const attachments: ExpenseAttachment[] = [];
    for (const id of v.attachments ?? []) {
      const doc = docs.find((d) => d.id === id);
      if (doc) {
        attachments.push({ document_id: doc.id, title: doc.title, file_url: doc.file_url });
        continue;
      }
      const old = prev.find((a) => a.document_id === id);
      if (old) attachments.push(old);
    }
    const body: ExpenseInput = {
      claim_type: v.claim_type,
      amount: v.amount,
      occur_date: v.occur_date.format("YYYY-MM-DD"),
      description: v.description ?? "",
      attachments,
    };
    saveM.mutate({ id: editing?.id ?? null, body });
  };

  const handleExport = async () => {
    setExporting(true);
    try {
      await expensesApi.exportExcel(filters.month || undefined);
      message.success("导出成功，已开始下载");
    } catch (e) {
      message.error(errText(e, "导出失败"));
    } finally {
      setExporting(false);
    }
  };

  const downloadAtt = async (att: ExpenseAttachment) => {
    try {
      await expensesApi.downloadAttachment(att);
    } catch (e) {
      message.error(errText(e, "附件下载失败"));
    }
  };

  // 审批中的单子跳流程详情；流程未关联时退回抽屉
  const openWorkflow = (r: Expense) => {
    if (r.workflow_instance_id) navigate(`/workflows/instance/${r.workflow_instance_id}`);
    else setViewing(r);
  };

  const renderActions = (r: Expense) => (
    <Space wrap size={4}>
      {(r.status === "draft" || r.status === "rejected") && (
        <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)}>
          编辑
        </Button>
      )}
      {r.status === "draft" && (
        <Popconfirm
          title="提交该报销单并发起审批？"
          description={
            r.attachments.length === 0 ? "当前没有发票附件，提交将被拒绝" : undefined
          }
          onConfirm={() => submitM.mutate(r.id)}
        >
          <Button
            size="small"
            icon={<SendOutlined />}
            loading={submitM.isPending && submitM.variables === r.id}
          >
            提交
          </Button>
        </Popconfirm>
      )}
      {(r.status === "draft" || r.status === "rejected") && (
        <Popconfirm title="确认删除该报销单？" onConfirm={() => removeM.mutate(r.id)}>
          <Button
            size="small"
            danger
            icon={<DeleteOutlined />}
            loading={removeM.isPending && removeM.variables === r.id}
          >
            删除
          </Button>
        </Popconfirm>
      )}
      {r.status === "submitted" && (
        <Button size="small" icon={<EyeOutlined />} onClick={() => openWorkflow(r)}>
          查看
        </Button>
      )}
      {r.status === "approved" && canManage && (
        <Popconfirm title="确认该报销单已打款？" onConfirm={() => payM.mutate({ id: r.id, paid: true })}>
          <Button
            size="small"
            type="primary"
            loading={payM.isPending && payM.variables?.id === r.id}
          >
            打款
          </Button>
        </Popconfirm>
      )}
      {r.status === "paid" && (
        <Button size="small" icon={<EyeOutlined />} onClick={() => setViewing(r)}>
          查看
        </Button>
      )}
    </Space>
  );

  const columns: TableColumnsType<Expense> = [
    {
      title: "单号",
      dataIndex: "code",
      width: 130,
      render: (v: string) => <span style={{ fontFamily: "monospace" }}>{v}</span>,
    },
    { title: "申请人", dataIndex: "user_name", width: 90 },
    {
      title: "类型",
      dataIndex: "claim_type",
      width: 80,
      render: (v: string) => <Tag color="blue">{TYPE_LABELS[v] || v}</Tag>,
    },
    {
      title: "金额",
      dataIndex: "amount",
      width: 120,
      align: "right",
      render: (v: number) => `¥${money(v)}`,
    },
    { title: "发生日期", dataIndex: "occur_date", width: 110 },
    { title: "状态", dataIndex: "status", width: 96, render: (v: string) => statusTag(v) },
    {
      title: "审批人 / 意见",
      width: 180,
      render: (_: unknown, r: Expense) =>
        r.approver_name || r.review_comment ? (
          <span title={r.review_comment || undefined}>
            {r.approver_name || "-"}
            {r.review_comment ? ` · ${r.review_comment}` : ""}
          </span>
        ) : (
          "-"
        ),
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      width: 150,
      render: (v: string) => fmtTime(v),
    },
    {
      title: "操作",
      key: "action",
      width: 230,
      fixed: "right",
      render: (_: unknown, r: Expense) => renderActions(r),
    },
  ];

  const totalAmount = statsQ.data?.total_amount ?? 0;

  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 8,
          marginBottom: 12,
        }}
      >
        <h2 style={{ margin: 0 }}>报销单</h2>
        <Space wrap>
          <Upload
            accept=".xlsx,.xls"
            showUploadList={false}
            maxCount={1}
            customRequest={({ file }) => {
              if (file instanceof File) {
                importM.mutate(file);
              } else {
                message.error("文件格式不支持，请选择 xlsx/xls 文件");
              }
            }}
          >
            <Button icon={<UploadOutlined />} loading={importM.isPending}>
              导入 Excel
            </Button>
          </Upload>
          <Button
            icon={<FileOutlined />}
            onClick={() => expensesApi.downloadTemplate()}
            style={{ marginLeft: 8 }}
          >
            下载模板
          </Button>
          {canManage && (
            <Button icon={<DownloadOutlined />} loading={exporting} onClick={handleExport}>
              导出 Excel
            </Button>
          )}
          {canManage && (
            <Button icon={<SafetyCertificateOutlined />} onClick={() => setBudgetOpen(true)}>
              额度预算
            </Button>
          )}
          <Button
            icon={<AuditOutlined />}
            onClick={() => {
              setVerifyResult(null);
              verifyForm.resetFields();
              setVerifyOpen(true);
            }}
          >
            发票验真
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建报销单
          </Button>
        </Space>
      </div>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="提交前请先在「文档中心」上传发票/凭证，并在报销单的附件中选择该文档；没有附件的报销单无法提交审批。"
      />

      {canManage && (
        <Card size="small" loading={statsQ.isLoading} style={{ marginBottom: 12 }}>
          <Row gutter={16}>
            <Col xs={24} md={8}>
              <Statistic title="总笔数" value={statsQ.data?.total_count ?? 0} suffix="笔" />
            </Col>
            <Col xs={24} md={8}>
              <Statistic title="总金额（元）" value={money(statsQ.data?.total_amount ?? 0)} />
            </Col>
            <Col xs={24} md={8}>
              <Statistic
                title="待审批"
                value={statsQ.data?.pending_count ?? 0}
                suffix="笔"
                valueStyle={{ color: "#faad14" }}
              />
            </Col>
          </Row>
          <Divider style={{ margin: "12px 0 8px" }} />
          <div style={{ color: "#888", fontSize: 12, marginBottom: 6 }}>
            类型分布（{statsQ.data?.month || filters.month || "本月"}）
          </div>
          {(statsQ.data?.by_type ?? []).length === 0 ? (
            <div style={{ color: "#bbb", fontSize: 12 }}>暂无数据</div>
          ) : (
            (statsQ.data?.by_type ?? []).map((b) => {
              const pct = totalAmount > 0 ? Math.round((b.amount / totalAmount) * 1000) / 10 : 0;
              return (
                <div
                  key={b.status}
                  style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}
                >
                  <span style={{ width: 48, flexShrink: 0 }}>
                    {TYPE_LABELS[b.status] || b.status}
                  </span>
                  <Progress size="small" style={{ flex: 1, margin: 0 }} percent={pct} />
                  <span
                    style={{
                      width: 150,
                      flexShrink: 0,
                      textAlign: "right",
                      color: "#888",
                      fontSize: 12,
                    }}
                  >
                    {b.count} 笔 · ¥{money(b.amount)}
                  </span>
                </div>
              );
            })
          )}
        </Card>
      )}

      {/* 筛选行 */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          gap: 8,
          marginBottom: 12,
        }}
      >
        <Select<ExpenseStatus | "all">
          value={draft.status}
          style={{ width: 132 }}
          options={STATUS_OPTIONS}
          onChange={(v) => setDraft((d) => ({ ...d, status: v }))}
        />
        <DatePicker
          picker="month"
          format="YYYY-MM"
          placeholder="选择月份"
          allowClear
          value={draft.month ? dayjs(draft.month) : null}
          onChange={(v) => setDraft((d) => ({ ...d, month: v ? v.format("YYYY-MM") : "" }))}
        />
        <Input.Search
          allowClear
          placeholder="单号 / 说明 / 申请人"
          style={{ width: 220 }}
          value={draft.q}
          onChange={(e) => setDraft((d) => ({ ...d, q: e.target.value }))}
          onSearch={applyFilters}
        />
        <Button type="primary" icon={<SearchOutlined />} onClick={applyFilters}>
          查询
        </Button>
        <Button onClick={resetFilters}>重置</Button>
        <Space size={6}>
          <span style={{ color: canManage ? undefined : "#999" }}>只看我的</span>
          <Switch
            size="small"
            checked={canManage ? draft.mine : true}
            disabled={!canManage}
            onChange={toggleMine}
          />
        </Space>
        {!canManage && (
          <span style={{ color: "#999", fontSize: 12 }}>无管理权限，仅显示本人报销单</span>
        )}
      </div>

      <div style={{ marginBottom: 8, color: "#666", fontSize: 13 }}>
        当前筛选合计：<b>¥{money(listQ.data?.sum_amount ?? 0)}</b>
        <span style={{ color: "#999" }}>（共 {listQ.data?.total ?? 0} 条记录）</span>
        {canManage && selectedIds.length > 0 && (
          <Space style={{ marginLeft: 16 }}>
            <span>已选 <b>{selectedIds.length}</b> 笔（仅「已通过」可打款）</span>
            <Popconfirm
              title={`确认对 ${selectedIds.length} 笔报销单批量打款？`}
              onConfirm={() => batchPayM.mutate(selectedIds)}
              okText="确认打款"
              cancelText="取消"
            >
              <Button
                type="primary"
                size="small"
                icon={<SendOutlined />}
                loading={batchPayM.isPending}
              >
                批量打款
              </Button>
            </Popconfirm>
            <Button size="small" onClick={() => setSelectedIds([])}>
              取消选择
            </Button>
          </Space>
        )}
      </div>

      <Table<Expense>
        rowKey="id"
        loading={listQ.isLoading}
        dataSource={listQ.data?.items ?? []}
        columns={columns}
        scroll={{ x: 1200 }}
        rowSelection={
          canManage
            ? {
                selectedRowKeys: selectedIds,
                onChange: (keys) => setSelectedIds(keys as number[]),
                getCheckboxProps: (r) => ({
                  disabled: r.status !== "approved",
                }),
              }
            : undefined
        }
        pagination={{
          current: page,
          pageSize,
          total: listQ.data?.total ?? 0,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条`,
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
      />

      {/* 新建 / 编辑 */}
      <Modal
        title={editing ? `编辑报销单 · ${editing.code}` : "新建报销单"}
        open={modalOpen}
        forceRender
        okText={editing ? "保存" : "创建"}
        confirmLoading={saveM.isPending}
        onCancel={() => {
          setModalOpen(false);
          setEditing(null);
        }}
        onOk={() => form.submit()}
      >
        <Form<ExpenseFormValues>
          form={form}
          layout="vertical"
          initialValues={{ claim_type: "daily", attachments: [] }}
          onFinish={onFinish}
        >
          <Form.Item
            name="claim_type"
            label="报销类型"
            rules={[{ required: true, message: "请选择报销类型" }]}
          >
            <Select options={TYPE_OPTIONS} placeholder="请选择类型" />
          </Form.Item>
          <Form.Item
            name="amount"
            label="金额（元）"
            rules={[{ required: true, message: "请输入金额" }]}
          >
            <InputNumber
              style={{ width: "100%" }}
              min={0.01}
              precision={2}
              step={1}
              placeholder="0.00"
            />
          </Form.Item>
          {/* 额度预检：匹配到预算时实时提示剩余额度；超额直接标红（提交时后端同样会拦截） */}
          {!editing && quotaQ.data?.has_budget && (
            <Alert
              type={quotaQ.data.exceeded ? "error" : "info"}
              showIcon
              style={{ marginBottom: 16 }}
              message={
                quotaQ.data.exceeded
                  ? `超出预算：${quotaQ.data.message}`
                  : `预算额度：${quotaQ.data.message}（总额度 ¥${money(quotaQ.data.quota_amount ?? 0)}）`
              }
            />
          )}
          <Form.Item
            name="occur_date"
            label="费用发生日期"
            rules={[{ required: true, message: "请选择费用发生日期" }]}
          >
            <DatePicker
              style={{ width: "100%" }}
              format="YYYY-MM-DD"
              allowClear={false}
              placeholder="选择日期"
            />
          </Form.Item>
          <Form.Item
            name="description"
            label="说明"
            rules={[{ max: 1000, message: "说明最多 1000 字" }]}
          >
            <Input.TextArea rows={3} maxLength={1000} showCount placeholder="费用事由、明细等" />
          </Form.Item>
          <Form.Item
            name="attachments"
            label="附件（发票 / 凭证）"
            extra="来自文档中心，提交审批前至少需要选择一个附件"
          >
            <Select
              mode="multiple"
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="从文档中心选择附件"
              loading={docsQ.isLoading}
              options={(docsQ.data?.items ?? []).map((d) => ({ value: d.id, label: d.title }))}
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* 详情抽屉 */}
      <Drawer
        title={viewing ? `报销单详情 · ${viewing.code}` : "报销单详情"}
        open={!!viewing}
        onClose={() => setViewing(null)}
        width={560}
      >
        {viewing && (
          <>
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="申请人">{viewing.user_name || "-"}</Descriptions.Item>
              <Descriptions.Item label="类型">
                {TYPE_LABELS[viewing.claim_type] || viewing.claim_type}
              </Descriptions.Item>
              <Descriptions.Item label="金额">¥{money(viewing.amount)}</Descriptions.Item>
              <Descriptions.Item label="发生日期">{viewing.occur_date}</Descriptions.Item>
              <Descriptions.Item label="状态">{statusTag(viewing.status)}</Descriptions.Item>
              <Descriptions.Item label="审批人">
                {viewing.approver_name || "-"}
              </Descriptions.Item>
              <Descriptions.Item label="审批意见" span={2}>
                {viewing.review_comment || "-"}
              </Descriptions.Item>
              <Descriptions.Item label="流程编号">
                {viewing.workflow_code || "-"}
              </Descriptions.Item>
              <Descriptions.Item label="打款时间">
                {viewing.paid_at ? fmtTime(viewing.paid_at) : "-"}
              </Descriptions.Item>
              <Descriptions.Item label="创建时间" span={2}>
                {fmtTime(viewing.created_at)}
              </Descriptions.Item>
              <Descriptions.Item label="说明" span={2}>
                {viewing.description || "-"}
              </Descriptions.Item>
            </Descriptions>

            <div style={{ marginTop: 16, fontWeight: 600, marginBottom: 8 }}>
              附件（发票 / 凭证）
            </div>
            {viewing.attachments.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无附件" />
            ) : (
              viewing.attachments.map((a) => (
                <div
                  key={a.document_id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 8,
                    padding: "6px 0",
                    borderBottom: "1px solid #f0f0f0",
                  }}
                >
                  <span
                    style={{
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                    title={a.title}
                  >
                    {a.title}
                  </span>
                  <Button
                    size="small"
                    type="link"
                    icon={<DownloadOutlined />}
                    onClick={() => downloadAtt(a)}
                  >
                    下载
                  </Button>
                </div>
              ))
            )}

            {viewing.workflow_instance_id != null && (
              <Button
                style={{ marginTop: 16 }}
                onClick={() => navigate(`/workflows/instance/${viewing.workflow_instance_id}`)}
              >
                查看审批流程
              </Button>
            )}
          </>
        )}
      </Drawer>

      {/* ===== 额度预算抽屉（expense:manage） ===== */}
      <Drawer
        title="额度预算"
        width={760}
        open={budgetOpen}
        onClose={() => setBudgetOpen(false)}
        extra={
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              setEditingBudget(null);
              budgetForm.resetFields();
              budgetForm.setFieldsValue({ status: "active" });
              setBudgetModalOpen(true);
            }}
          >
            新建预算
          </Button>
        }
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="额度按「期间 + 部门 + 类别」匹配；用量按已提交/已通过/已打款单据实时聚合，草稿不占用、驳回后自动释放。"
        />
        <Table<Budget>
          rowKey="id"
          size="small"
          loading={budgetsQ.isLoading}
          dataSource={budgetsQ.data?.items ?? []}
          columns={[
            { title: "名称", dataIndex: "name" },
            { title: "编码", dataIndex: "code", width: 120 },
            {
              title: "类别",
              dataIndex: "category",
              width: 80,
              render: (v: ExpenseClaimType | null) => (v ? TYPE_LABELS[v] ?? v : "全部"),
            },
            {
              title: "期间",
              width: 190,
              render: (_: unknown, r: Budget) => `${r.start_date} ~ ${r.end_date}`,
            },
            {
              title: "状态",
              dataIndex: "status",
              width: 80,
              render: (v: string) => (
                <Tag color={v === "active" ? "green" : v === "expired" ? "red" : "default"}>
                  {v === "active" ? "生效中" : v === "expired" ? "已过期" : "停用"}
                </Tag>
              ),
            },
            {
              title: "额度使用",
              width: 200,
              render: (_: unknown, r: Budget) => {
                const pct =
                  r.total_amount > 0
                    ? Math.min(100, Math.round((r.used_amount / r.total_amount) * 100))
                    : 0;
                return (
                  <div>
                    <Progress
                      size="small"
                      percent={pct}
                      status={r.remaining <= 0 ? "exception" : undefined}
                    />
                    <span style={{ fontSize: 12, color: "#888" }}>
                      已用 ¥{money(r.used_amount)} / 剩余 ¥{money(r.remaining)}
                    </span>
                  </div>
                );
              },
            },
            {
              title: "操作",
              width: 80,
              render: (_: unknown, r: Budget) => (
                <Button
                  size="small"
                  type="link"
                  icon={<EditOutlined />}
                  onClick={() => {
                    setEditingBudget(r);
                    budgetForm.setFieldsValue({
                      name: r.name,
                      code: r.code,
                      total_amount: r.total_amount,
                      range: [dayjs(r.start_date), dayjs(r.end_date)],
                      category: r.category,
                      status: r.status,
                    });
                    setBudgetModalOpen(true);
                  }}
                >
                  编辑
                </Button>
              ),
            },
          ]}
          pagination={false}
        />
      </Drawer>

      {/* ===== 预算新建 / 编辑 ===== */}
      <Modal
        title={editingBudget ? `编辑预算 · ${editingBudget.code}` : "新建预算"}
        open={budgetModalOpen}
        onCancel={() => {
          setBudgetModalOpen(false);
          setEditingBudget(null);
        }}
        onOk={() => budgetForm.submit()}
        okText="保存"
        confirmLoading={saveBudgetM.isPending}
        forceRender
      >
        <Form<BudgetFormValues>
          form={budgetForm}
          layout="vertical"
          initialValues={{ status: "active" }}
          onFinish={(v) => {
            const body = {
              name: v.name,
              code: v.code,
              total_amount: Number(v.total_amount || 0),
              start_date: v.range[0].format("YYYY-MM-DD"),
              end_date: v.range[1].format("YYYY-MM-DD"),
              category: v.category ?? null,
              status: v.status ?? "active",
            };
            saveBudgetM.mutate({ id: editingBudget?.id ?? null, body });
          }}
        >
          <Form.Item name="name" label="预算名称" rules={[{ required: true, message: "请输入名称" }]}>
            <Input maxLength={100} placeholder="如：2026 年度差旅预算" />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="code" label="编码" rules={[{ required: true, message: "请输入编码" }]}>
                <Input maxLength={40} placeholder="唯一，如 BG-2026-001" disabled={!!editingBudget} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="total_amount"
                label="总额度（元）"
                rules={[{ required: true, message: "请输入总额度" }]}
              >
                <InputNumber style={{ width: "100%" }} min={0} precision={2} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="range" label="生效期间" rules={[{ required: true, message: "请选择期间" }]}>
            <DatePicker.RangePicker style={{ width: "100%" }} />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="category" label="适用类别">
                <Select allowClear placeholder="不限类别" options={TYPE_OPTIONS} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="status" label="状态">
                <Select
                  options={[
                    { value: "active", label: "生效中" },
                    { value: "inactive", label: "停用" },
                    { value: "expired", label: "已过期" },
                  ]}
                />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>

      {/* ===== 发票验真（本地校验） ===== */}
      <Modal
        title="发票验真"
        open={verifyOpen}
        onCancel={() => setVerifyOpen(false)}
        footer={null}
        width={560}
        forceRender
      >
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="本地校验：格式 / 唯一性 / 买方税号校验位；不接入税务发票库，真伪请以官方渠道查验为准。"
        />
        <Form<VerifyFormValues>
          form={verifyForm}
          layout="vertical"
          onFinish={(v) => {
            setVerifyResult(null);
            verifyM.mutate(v);
          }}
        >
          <Row gutter={12}>
            <Col span={14}>
              <Form.Item
                name="invoice_no"
                label="发票号码"
                rules={[{ required: true, message: "请输入发票号码" }]}
              >
                <Input maxLength={50} placeholder="8 位以上" />
              </Form.Item>
            </Col>
            <Col span={10}>
              <Form.Item name="invoice_code" label="发票代码（选填）">
                <Input maxLength={20} placeholder="10 / 12 位" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="amount" label="金额（选填）">
                <InputNumber style={{ width: "100%" }} min={0} precision={2} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="buyer_tax_no" label="买方税号（选填）">
                <Input maxLength={18} placeholder="18 位统一社会信用代码" />
              </Form.Item>
            </Col>
          </Row>
          <Space>
            <Button
              type="primary"
              htmlType="submit"
              icon={<AuditOutlined />}
              loading={verifyM.isPending}
            >
              开始验真
            </Button>
            <Button
              onClick={() => {
                verifyForm.resetFields();
                setVerifyResult(null);
              }}
            >
              重置
            </Button>
          </Space>
        </Form>

        {verifyResult && (
          <div style={{ marginTop: 16 }}>
            <Alert
              type={verifyResult.status === "verified" ? "success" : "error"}
              showIcon
              style={{ marginBottom: 12 }}
              message={verifyResult.status === "verified" ? "验真通过" : "验真未通过"}
            />
            <Table
              rowKey="name"
              size="small"
              pagination={false}
              dataSource={verifyResult.checks}
              columns={[
                {
                  title: "检查项",
                  dataIndex: "name",
                  render: (v: string) => CHECK_LABELS[v] ?? v,
                },
                {
                  title: "结果",
                  dataIndex: "passed",
                  width: 100,
                  render: (ok: boolean) =>
                    ok ? (
                      <Tag color="green" icon={<CheckCircleOutlined />}>
                        通过
                      </Tag>
                    ) : (
                      <Tag color="red" icon={<CloseCircleOutlined />}>
                        不通过
                      </Tag>
                    ),
                },
                { title: "说明", dataIndex: "message" },
              ]}
            />
          </div>
        )}
      </Modal>
    </div>
  );
}
