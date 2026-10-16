import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Descriptions,
  Drawer,
  Form,
  Input,
  Modal,
  Popconfirm,
  Segmented,
  Select,
  Space,
  Spin,
  Table,
  Timeline,
  Tag,
  message,
  type TableProps,
} from "antd";
import {
  InboxOutlined,
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  EyeOutlined,
  PlusOutlined,
  SendOutlined,
} from "@ant-design/icons";
import {
  officialDocsApi,
  type AttachmentCandidate,
  type OfficialDoc,
  type OfficialDocAttachment,
  type OfficialDocDirection,
  type OfficialDocPayload,
  type OfficialDocSearchHit,
  type OfficialDocSecrecy,
  type OfficialDocStatus,
} from "../api/officialDocs";
import { useAuth } from "../auth/AuthContext";

// ---- 流转事件文案 ----
const TIMELINE_META: Record<string, { label: string; color: string }> = {
  create: { label: "登记", color: "green" },
  circulate: { label: "传阅", color: "blue" },
  archive: { label: "归档", color: "gold" },
  status_change: { label: "状态变更", color: "orange" },
};

// ---- 中文文案映射 ----
const DIRECTION_LABELS: Record<OfficialDocDirection, string> = { in: "收文", out: "发文" };

const STATUS_META: Record<OfficialDocStatus, { label: string; color: string }> = {
  draft: { label: "草稿", color: "default" },
  pending: { label: "待发布", color: "orange" },
  circulated: { label: "已传阅", color: "blue" },
  archived: { label: "已归档", color: "green" },
};

const SECRECY_META: Record<OfficialDocSecrecy, { label: string; color: string }> = {
  public: { label: "公开", color: "green" },
  internal: { label: "内部", color: "blue" },
  secret: { label: "秘密", color: "red" },
};

type DirectionFilter = "all" | OfficialDocDirection;
type StatusFilter = "all" | OfficialDocStatus;

const DIRECTION_OPTIONS: { value: DirectionFilter; label: string }[] = [
  { value: "all", label: "全部方向" },
  { value: "in", label: "收文" },
  { value: "out", label: "发文" },
];

const STATUS_OPTIONS: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "全部状态" },
  { value: "draft", label: "草稿" },
  { value: "pending", label: "待发布" },
  { value: "circulated", label: "已传阅" },
  { value: "archived", label: "已归档" },
];

const SECRECY_OPTIONS: { value: OfficialDocSecrecy; label: string }[] = [
  { value: "public", label: "公开" },
  { value: "internal", label: "内部" },
  { value: "secret", label: "秘密" },
];

const DIRECTION_SEGMENTS: { label: string; value: OfficialDocDirection }[] = [
  { label: "收文", value: "in" },
  { label: "发文", value: "out" },
];

// 新建/编辑表单值（attachments 存文档中心的 document_id）
interface DocFormValues {
  doc_no: string;
  title: string;
  direction: OfficialDocDirection;
  from_org?: string;
  to_org?: string;
  secrecy?: OfficialDocSecrecy;
  content?: string;
  attachments?: number[];
}

// 传阅表单值（user_ids 为空 = 广播全体）
interface CirculateFormValues {
  user_ids?: number[];
  remark?: string;
}

function errMsg(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback;
}

type DocColumns = NonNullable<TableProps<OfficialDoc>["columns"]>;

export default function OfficialDocs() {
  const qc = useQueryClient();
  const { hasPerm } = useAuth();
  const canManage = hasPerm("doc:official:manage");

  // ---- 筛选与分页状态 ----
  const [direction, setDirection] = useState<DirectionFilter>("all");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  // ---- 弹层状态 ----
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<OfficialDoc | null>(null);
  const [circulateRow, setCirculateRow] = useState<OfficialDoc | null>(null);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [detailRow, setDetailRow] = useState<OfficialDoc | null>(null);
  const [form] = Form.useForm<DocFormValues>();
  const [circForm] = Form.useForm<CirculateFormValues>();

  const offset = (page - 1) * pageSize;

  // ---- 查询 ----
  const listQ = useQuery({
    queryKey: ["official-docs", "list", { direction, status, q, offset, limit: pageSize }],
    queryFn: () =>
      officialDocsApi.list({
        direction: direction === "all" ? undefined : direction,
        status,
        q: q || undefined,
        offset,
        limit: pageSize,
      }),
  });

  const detailQ = useQuery({
    queryKey: ["official-docs", "detail", detailId],
    queryFn: () => officialDocsApi.get(detailId!),
    enabled: detailId !== null,
  });

  // 全文检索：关键词非空时切换到 /search（跨标题/正文/文号/来往单位/登记人，带摘要）
  const isSearching = q.trim().length > 0;
  const searchQ = useQuery({
    queryKey: ["official-docs", "search", { q, direction, status, offset, limit: pageSize }],
    queryFn: () =>
      officialDocsApi.search(q.trim(), {
        direction: direction === "all" ? undefined : direction,
        status,
        offset,
        limit: pageSize,
      }),
    enabled: isSearching,
  });

  // 流转时间线：详情抽屉打开时拉取
  const timelineQ = useQuery({
    queryKey: ["official-docs", "timeline", detailId],
    queryFn: () => officialDocsApi.timeline(detailId!),
    enabled: detailId !== null,
  });

  // 文号预览：登记弹窗内按当前方向预取「下一个可用文号」，自动填入空文号
  const watchDirection = Form.useWatch("direction", form) ?? "in";
  const docNoQ = useQuery({
    queryKey: ["official-docs", "next-doc-no", watchDirection],
    queryFn: () =>
      officialDocsApi.nextDocNo(watchDirection === "out" ? "out" : "in"),
    enabled: formOpen && !editing,
    staleTime: 0,
  });
  useEffect(() => {
    if (formOpen && !editing && docNoQ.data) {
      const cur = form.getFieldValue("doc_no");
      if (!cur) form.setFieldsValue({ doc_no: docNoQ.data.doc_no });
    }
  }, [docNoQ.data, formOpen, editing, form]);

  // 附件候选：打开登记/编辑弹窗时才拉取
  const attachQ = useQuery({
    queryKey: ["official-docs", "attachment-candidates"],
    queryFn: officialDocsApi.attachmentCandidates,
    enabled: formOpen,
    staleTime: 60_000,
  });

  // 传阅人员候选：打开传阅弹窗时才拉取
  const usersQ = useQuery({
    queryKey: ["official-docs", "user-candidates"],
    queryFn: officialDocsApi.userCandidates,
    enabled: circulateRow !== null,
    staleTime: 60_000,
  });

  // ---- 附件候选合并（含当前编辑公文已有附件，保证回显可选） ----
  const attachSourceMap = new Map<number, OfficialDocAttachment>();
  (attachQ.data?.items ?? []).forEach((c: AttachmentCandidate) =>
    attachSourceMap.set(c.id, { document_id: c.id, title: c.title, file_url: c.file_url })
  );
  (editing?.attachments ?? []).forEach((a) => {
    if (!attachSourceMap.has(a.document_id)) attachSourceMap.set(a.document_id, a);
  });
  const attachmentOptions = Array.from(attachSourceMap.values()).map((a) => ({
    value: a.document_id,
    label: a.title,
  }));

  // ---- 变更后统一刷新 ----
  const invalidate = () => qc.invalidateQueries({ queryKey: ["official-docs"] });

  const createM = useMutation({
    mutationFn: (body: OfficialDocPayload) => officialDocsApi.create(body),
    onSuccess: () => {
      invalidate();
      closeForm();
      message.success("公文已登记");
    },
    onError: (e: unknown) => message.error(errMsg(e, "登记失败")),
  });

  const updateM = useMutation({
    mutationFn: (v: { id: number; body: OfficialDocPayload }) =>
      officialDocsApi.update(v.id, v.body),
    onSuccess: () => {
      invalidate();
      closeForm();
      message.success("公文已更新");
    },
    onError: (e: unknown) => message.error(errMsg(e, "保存失败")),
  });

  const removeM = useMutation({
    mutationFn: (id: number) => officialDocsApi.remove(id),
    onSuccess: () => {
      invalidate();
      message.success("公文已删除");
    },
    onError: (e: unknown) => message.error(errMsg(e, "删除失败")),
  });

  const archiveM = useMutation({
    mutationFn: (id: number) => officialDocsApi.archive(id),
    onSuccess: () => {
      invalidate();
      message.success("公文已归档");
    },
    onError: (e: unknown) => message.error(errMsg(e, "归档失败")),
  });

  const circulateM = useMutation({
    mutationFn: (v: { id: number; body: { user_ids: number[]; remark: string } }) =>
      officialDocsApi.circulate(v.id, v.body),
    onSuccess: () => {
      invalidate();
      setCirculateRow(null);
      circForm.resetFields();
      message.success("传阅已发送");
    },
    onError: (e: unknown) => message.error(errMsg(e, "传阅失败")),
  });

  // ---- 打开/关闭 ----
  function closeForm() {
    setFormOpen(false);
    setEditing(null);
    form.resetFields();
  }

  function openCreate() {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({
      direction: "in",
      secrecy: "public",
      attachments: [],
      content: "",
      from_org: "",
      to_org: "",
    });
    setFormOpen(true);
  }

  function openEdit(row: OfficialDoc) {
    setEditing(row);
    form.resetFields();
    form.setFieldsValue({
      doc_no: row.doc_no,
      title: row.title,
      direction: row.direction,
      from_org: row.from_org,
      to_org: row.to_org,
      secrecy: row.secrecy,
      content: row.content,
      attachments: row.attachments.map((a) => a.document_id),
    });
    setFormOpen(true);
  }

  function openCirculate(row: OfficialDoc) {
    circForm.resetFields();
    circForm.setFieldsValue({ user_ids: [], remark: "" });
    setCirculateRow(row);
  }

  function openDetail(row: OfficialDoc) {
    setDetailRow(row);
    setDetailId(row.id);
  }

  function buildPayload(v: DocFormValues): OfficialDocPayload {
    const attachments = (v.attachments ?? [])
      .map((id) => attachSourceMap.get(id))
      .filter((a): a is OfficialDocAttachment => a !== undefined);
    return {
      doc_no: v.doc_no.trim(),
      title: v.title.trim(),
      direction: v.direction,
      from_org: (v.from_org ?? "").trim(),
      to_org: (v.to_org ?? "").trim(),
      secrecy: v.secrecy ?? "public",
      content: v.content ?? "",
      attachments,
    };
  }

  async function handleDownload(att: OfficialDocAttachment) {
    try {
      await officialDocsApi.downloadAttachment(att);
    } catch (e) {
      message.error(errMsg(e, "附件下载失败"));
    }
  }

  // ---- 表格列 ----
  const columns: DocColumns = [
    { title: "文号", dataIndex: "doc_no", width: 170 },
    { title: "标题", dataIndex: "title", ellipsis: true },
    {
      title: "方向",
      dataIndex: "direction",
      width: 80,
      render: (v: OfficialDocDirection) => (
        <Tag color={v === "in" ? "geekblue" : "purple"}>{DIRECTION_LABELS[v] ?? v}</Tag>
      ),
    },
    {
      title: "来文/去文单位",
      width: 170,
      ellipsis: true,
      render: (_: unknown, row: OfficialDoc) => {
        const org = row.direction === "in" ? row.from_org : row.to_org;
        return org || "-";
      },
    },
    {
      title: "密级",
      dataIndex: "secrecy",
      width: 90,
      render: (v: OfficialDocSecrecy) => (
        <Tag color={SECRECY_META[v]?.color ?? "default"}>{SECRECY_META[v]?.label ?? v}</Tag>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 100,
      render: (v: OfficialDocStatus) => (
        <Tag color={STATUS_META[v]?.color ?? "default"}>{STATUS_META[v]?.label ?? v}</Tag>
      ),
    },
    { title: "传阅人数", dataIndex: "read_count", width: 90, align: "right" },
    { title: "登记人", dataIndex: "owner_name", width: 110 },
    { title: "登记时间", dataIndex: "created_at", width: 170 },
    {
      title: "操作",
      width: canManage ? 340 : 90,
      render: (_: unknown, row: OfficialDoc) => (
        <Space wrap>
          <Button size="small" icon={<EyeOutlined />} onClick={() => openDetail(row)}>
            查看
          </Button>
          {canManage && row.status !== "archived" && (
            <>
              <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>
                编辑
              </Button>
              <Button size="small" icon={<SendOutlined />} onClick={() => openCirculate(row)}>
                传阅
              </Button>
              <Popconfirm
                title="确认归档该公文？"
                description="归档后不可再编辑与删除"
                onConfirm={() => archiveM.mutate(row.id)}
              >
                <Button size="small" icon={<InboxOutlined />} loading={archiveM.isPending}>
                  归档
                </Button>
              </Popconfirm>
              <Popconfirm
                title="确认删除该公文？"
                onConfirm={() => removeM.mutate(row.id)}
              >
                <Button size="small" danger icon={<DeleteOutlined />} loading={removeM.isPending}>
                  删除
                </Button>
              </Popconfirm>
            </>
          )}
        </Space>
      ),
    },
  ];

  const detailDoc = detailQ.data ?? detailRow;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
        <h2>公文管理</h2>
        <Space>
          <Button onClick={() => listQ.refetch()}>刷新</Button>
          {canManage && (
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              登记公文
            </Button>
          )}
        </Space>
      </div>

      {/* 筛选行 */}
      <Space style={{ marginBottom: 12 }} wrap>
        <Select
          value={direction}
          style={{ width: 140 }}
          options={DIRECTION_OPTIONS}
          onChange={(v: DirectionFilter) => {
            setDirection(v);
            setPage(1);
          }}
        />
        <Select
          value={status}
          style={{ width: 140 }}
          options={STATUS_OPTIONS}
          onChange={(v: StatusFilter) => {
            setStatus(v);
            setPage(1);
          }}
        />
        <Input.Search
          allowClear
          placeholder="全文检索：文号/标题/正文/单位"
          style={{ width: 260 }}
          onSearch={(v) => {
            setQ(v.trim());
            setPage(1);
          }}
          onChange={(e) => {
            if (!e.target.value) {
              setQ("");
              setPage(1);
            }
          }}
        />
        {isSearching && (
          <Tag color="blue" closable onClose={() => { setQ(""); setPage(1); }}>
            全文检索：{q}
          </Tag>
        )}
      </Space>

      {isSearching ? (
        <Table
          rowKey="id"
          loading={searchQ.isLoading}
          dataSource={searchQ.data?.items || []}
          scroll={{ x: 1000 }}
          columns={[
            {
              title: "文号",
              dataIndex: "doc_no",
              width: 160,
              render: (v: string) => <Tag>{v}</Tag>,
            },
            {
              title: "标题 / 摘要",
              render: (_: unknown, r: OfficialDocSearchHit) => (
                <div>
                  <div style={{ fontWeight: 600 }}>{r.title}</div>
                  <div style={{ color: "#888", fontSize: 12 }}>{r.snippet || "（无正文）"}</div>
                </div>
              ),
            },
            {
              title: "方向",
              dataIndex: "direction",
              width: 80,
              render: (v: OfficialDocDirection) => DIRECTION_LABELS[v],
            },
            {
              title: "状态",
              dataIndex: "status",
              width: 100,
              render: (v: OfficialDocStatus) => (
                <Tag color={STATUS_META[v]?.color ?? "default"}>{STATUS_META[v]?.label ?? v}</Tag>
              ),
            },
            { title: "登记人", dataIndex: "owner_name", width: 120 },
            { title: "登记时间", dataIndex: "created_at", width: 170 },
          ]}
          pagination={{
            current: page,
            pageSize,
            total: searchQ.data?.total ?? 0,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条命中`,
            onChange: (p, ps) => {
              setPage(p);
              setPageSize(ps);
            },
          }}
        />
      ) : (
      <Table
        rowKey="id"
        loading={listQ.isLoading}
        dataSource={listQ.data?.items || []}
        columns={columns}
        scroll={{ x: 1100 }}
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
      )}

      {/* 详情抽屉 */}
      <Drawer
        title="公文详情"
        width={680}
        open={detailId !== null}
        onClose={() => {
          setDetailId(null);
          setDetailRow(null);
        }}
      >
        {!detailDoc ? (
          <div style={{ textAlign: "center", padding: 48 }}>
            <Spin />
          </div>
        ) : (
          <div>
            <Descriptions column={2} bordered size="small" style={{ marginBottom: 16 }}>
              <Descriptions.Item label="文号">{detailDoc.doc_no}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={STATUS_META[detailDoc.status]?.color ?? "default"}>
                  {STATUS_META[detailDoc.status]?.label ?? detailDoc.status}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="标题" span={2}>
                {detailDoc.title}
              </Descriptions.Item>
              <Descriptions.Item label="方向">
                <Tag color={detailDoc.direction === "in" ? "geekblue" : "purple"}>
                  {DIRECTION_LABELS[detailDoc.direction]}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="密级">
                <Tag color={SECRECY_META[detailDoc.secrecy]?.color ?? "default"}>
                  {SECRECY_META[detailDoc.secrecy]?.label ?? detailDoc.secrecy}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="来文单位">{detailDoc.from_org || "-"}</Descriptions.Item>
              <Descriptions.Item label="去文单位">{detailDoc.to_org || "-"}</Descriptions.Item>
              <Descriptions.Item label="登记人">{detailDoc.owner_name || "-"}</Descriptions.Item>
              <Descriptions.Item label="传阅人数">{detailDoc.read_count}</Descriptions.Item>
              <Descriptions.Item label="发布时间">
                {detailDoc.published_at || "-"}
              </Descriptions.Item>
              <Descriptions.Item label="归档时间">
                {detailDoc.archived_at || "-"}
              </Descriptions.Item>
              <Descriptions.Item label="登记时间">{detailDoc.created_at}</Descriptions.Item>
              <Descriptions.Item label="更新时间">{detailDoc.updated_at}</Descriptions.Item>
            </Descriptions>

            <div style={{ fontWeight: 600, marginBottom: 8 }}>正文</div>
            <div
              style={{
                whiteSpace: "pre-wrap",
                background: "#fafafa",
                border: "1px solid #f0f0f0",
                borderRadius: 6,
                padding: 12,
                marginBottom: 16,
                lineHeight: 1.7,
              }}
            >
              {detailDoc.content ? detailDoc.content : "（无正文）"}
            </div>

            <div style={{ fontWeight: 600, marginBottom: 8 }}>
              附件（{detailDoc.attachments.length}）
            </div>
            {detailDoc.attachments.length === 0 ? (
              <div style={{ color: "#999", marginBottom: 16 }}>暂无附件</div>
            ) : (
              <div style={{ marginBottom: 16 }}>
                {detailDoc.attachments.map((att) => (
                  <div
                    key={att.document_id}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      padding: "6px 0",
                      borderBottom: "1px solid #f0f0f0",
                    }}
                  >
                    <Button
                      type="link"
                      style={{ padding: 0 }}
                      icon={<DownloadOutlined />}
                      onClick={() => handleDownload(att)}
                    >
                      {att.title}
                    </Button>
                  </div>
                ))}
              </div>
            )}

            {/* 流转时间线：登记 → 传阅 → 归档 */}
            <div style={{ fontWeight: 600, marginBottom: 8 }}>流转记录</div>
            {timelineQ.isLoading ? (
              <Spin size="small" />
            ) : (timelineQ.data ?? []).length === 0 ? (
              <div style={{ color: "#999", marginBottom: 16 }}>暂无流转记录</div>
            ) : (
              <Timeline
                style={{ marginBottom: 16 }}
                items={(timelineQ.data ?? []).map((ev) => {
                  const meta = TIMELINE_META[ev.action] ?? { label: ev.action, color: "default" };
                  return {
                    color: meta.color,
                    children: (
                      <div>
                        <div>
                          <b>{meta.label}</b> · {ev.actor_name || "系统"}
                          <span style={{ color: "#999", marginLeft: 8, fontSize: 12 }}>
                            {ev.created_at}
                          </span>
                        </div>
                        {ev.from_status || ev.to_status ? (
                          <div style={{ fontSize: 12, color: "#666" }}>
                            {ev.from_status || "-"} → {ev.to_status || "-"}
                          </div>
                        ) : null}
                        {ev.remark ? (
                          <div style={{ fontSize: 12, color: "#666" }}>{ev.remark}</div>
                        ) : null}
                      </div>
                    ),
                  };
                })}
              />
            )}
          </div>
        )}
      </Drawer>

      {/* 登记 / 编辑弹窗 */}
      <Modal
        title={editing ? "编辑公文" : "登记公文"}
        open={formOpen}
        onCancel={closeForm}
        onOk={() => form.submit()}
        okText={editing ? "保存" : "登记"}
        confirmLoading={createM.isPending || updateM.isPending}
        forceRender
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={(v) => {
            const payload = buildPayload(v);
            if (editing) updateM.mutate({ id: editing.id, body: payload });
            else createM.mutate(payload);
          }}
        >
          <Form.Item
            name="doc_no"
            label="文号"
            rules={[
              { required: true, message: "请输入文号" },
              { whitespace: true, message: "文号不能为空" },
            ]}
            extra={
              !editing && docNoQ.data
                ? `按 ${DIRECTION_LABELS[watchDirection === "out" ? "out" : "in"]}序列，下一个可用文号：${docNoQ.data.doc_no}`
                : undefined
            }
          >
            <Input
              placeholder={
                !editing && docNoQ.data ? docNoQ.data.doc_no : "如：中科发〔2024〕1号（唯一，重复会报错）"
              }
              maxLength={64}
              addonAfter={
                !editing && docNoQ.data ? (
                  <Button
                    type="link"
                    size="small"
                    style={{ padding: 0, height: "auto" }}
                    onClick={() => form.setFieldsValue({ doc_no: docNoQ.data!.doc_no })}
                  >
                    填入
                  </Button>
                ) : null
              }
            />
          </Form.Item>
          <Form.Item
            name="title"
            label="标题"
            rules={[
              { required: true, message: "请输入标题" },
              { whitespace: true, message: "标题不能为空" },
            ]}
          >
            <Input placeholder="公文标题" maxLength={200} />
          </Form.Item>
          <Form.Item name="direction" label="方向">
            <Segmented options={DIRECTION_SEGMENTS} />
          </Form.Item>
          <Space style={{ display: "flex" }} align="start">
            <Form.Item name="from_org" label="来文单位" style={{ width: 250 }}>
              <Input placeholder="收文时填写" maxLength={100} />
            </Form.Item>
            <Form.Item name="to_org" label="去文单位" style={{ width: 250 }}>
              <Input placeholder="发文时填写" maxLength={100} />
            </Form.Item>
          </Space>
          <Form.Item name="secrecy" label="密级">
            <Select options={SECRECY_OPTIONS} />
          </Form.Item>
          <Form.Item name="content" label="正文">
            <Input.TextArea rows={8} placeholder="公文正文内容" />
          </Form.Item>
          <Form.Item name="attachments" label="附件（来自文档中心，可多选）">
            <Select
              mode="multiple"
              allowClear
              placeholder="选择文档作为附件"
              optionFilterProp="label"
              options={attachmentOptions}
              loading={attachQ.isFetching}
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* 传阅弹窗 */}
      <Modal
        title={circulateRow ? `传阅公文：${circulateRow.doc_no}` : "传阅公文"}
        open={circulateRow !== null}
        onCancel={() => setCirculateRow(null)}
        onOk={() => circForm.submit()}
        okText="发送传阅"
        confirmLoading={circulateM.isPending}
        forceRender
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="未选择人员时，将把该公文传阅给全体用户（广播）"
        />
        <Form
          form={circForm}
          layout="vertical"
          onFinish={(v: CirculateFormValues) => {
            if (!circulateRow) return;
            circulateM.mutate({
              id: circulateRow.id,
              body: { user_ids: v.user_ids ?? [], remark: (v.remark ?? "").trim() },
            });
          }}
        >
          <Form.Item name="user_ids" label="传阅人员">
            <Select
              mode="multiple"
              allowClear
              placeholder="不选 = 传阅给全体用户"
              optionFilterProp="label"
              loading={usersQ.isFetching}
              options={(usersQ.data ?? [])
                .filter((u) => u.is_active)
                .map((u) => ({
                  value: u.id,
                  label: u.full_name ? `${u.full_name}（${u.username}）` : u.username,
                }))}
            />
          </Form.Item>
          <Form.Item name="remark" label="传阅备注">
            <Input placeholder="如：请各科室阅知（选填）" maxLength={200} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
