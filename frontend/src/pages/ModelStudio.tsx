import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Radio,
  Row,
  Select,
  Space,
  Statistic,
  Switch,
  Table,
  Tag,
  message,
  type TableProps,
} from "antd";
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  DeleteOutlined,
  PlusOutlined,
} from "@ant-design/icons";
import { modelApi } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import {
  FIELD_TYPE_LABELS,
  type ModelEntityOut,
  type ModelField,
  type ModelFieldType,
  type ModelRecordOut,
  type ModelRecordsPage,
} from "../types";

const PAGE_SIZE = 10;
const KEY_RE = /^[a-z][a-z0-9_]{0,39}$/;
const OPTION_TYPES: ModelFieldType[] = ["select", "radio", "multiselect"];

interface FieldDraft {
  key: string;
  label: string;
  type: ModelFieldType;
  required: boolean;
  unique: boolean;
  optionsText: string;
  defaultText: string;
}

const emptyDraft = (): FieldDraft => ({
  key: "",
  label: "",
  type: "text",
  required: false,
  unique: false,
  optionsText: "",
  defaultText: "",
});

const splitOptions = (text: string): string[] =>
  text
    .split(/[,，;；、]/)
    .map((s) => s.trim())
    .filter(Boolean);

function draftToFields(rows: FieldDraft[]) {
  return rows.map((r) => ({
    key: r.key.trim(),
    label: r.label.trim(),
    type: r.type,
    required: r.required,
    unique: r.unique,
    options: OPTION_TYPES.includes(r.type) ? splitOptions(r.optionsText) : [],
    default: r.defaultText.trim() === "" ? null : r.defaultText.trim(),
  }));
}

function validateRows(rows: FieldDraft[]): string | null {
  if (rows.length === 0) return "请至少添加一个字段";
  const seen = new Set<string>();
  for (const r of rows) {
    const key = r.key.trim();
    if (!KEY_RE.test(key)) return `字段标识「${key || "空"}」不合法：小写字母开头，可含数字与下划线`;
    if (seen.has(key)) return `字段标识重复：${key}`;
    seen.add(key);
    if (!r.label.trim()) return `字段 ${key} 缺少名称`;
    if (OPTION_TYPES.includes(r.type) && splitOptions(r.optionsText).length === 0) {
      return `字段 ${key} 为${FIELD_TYPE_LABELS[r.type]}，必须配置选项`;
    }
  }
  return null;
}

// ---------- 动态控件：由字段 schema 决定表单控件 ----------
function FieldControl({ field }: { field: ModelField }) {
  const opts = (field.options || []).map((o) => ({ value: o, label: o }));
  switch (field.type) {
    case "select":
      return <Select allowClear options={opts} placeholder={`请选择${field.label}`} />;
    case "radio":
      return <Radio.Group options={opts} />;
    case "multiselect":
      return <Select mode="multiple" allowClear options={opts} placeholder={`可多选`} />;
    case "bool":
      return <Switch />;
    case "number":
    case "money":
      return <InputNumber style={{ width: "100%" }} placeholder={`请输入${field.label}`} />;
    case "textarea":
      return <Input.TextArea rows={3} placeholder={`请输入${field.label}`} />;
    case "date":
      return <Input type="date" style={{ width: "100%" }} />;
    case "datetime":
      return <Input type="datetime-local" style={{ width: "100%" }} />;
    default:
      return <Input placeholder={`请输入${field.label}`} />;
  }
}

function renderCell(field: ModelField, v: any) {
  if (v === null || v === undefined || v === "") return <span style={{ color: "#bbb" }}>—</span>;
  if (field.type === "bool") return <Tag color={v ? "green" : "default"}>{v ? "是" : "否"}</Tag>;
  if (field.type === "multiselect" && Array.isArray(v))
    return (
      <Space size={4} wrap>
        {v.map((x: string) => (
          <Tag key={x}>{x}</Tag>
        ))}
      </Space>
    );
  if (field.type === "money") return `¥${Number(v).toLocaleString()}`;
  if (field.type === "date") return String(v).slice(0, 10);
  if (field.type === "datetime") return String(v).slice(0, 16).replace("T", " ");
  return String(v);
}

// ---------- 数据行表单 ----------
function DataFormModal({
  entity,
  record,
  onClose,
}: {
  entity: ModelEntityOut;
  record: ModelRecordOut | null;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [form] = Form.useForm();

  const save = useMutation({
    mutationFn: (data: Record<string, any>) =>
      record
        ? modelApi.updateRecord(record.id, data)
        : modelApi.createRecord(entity.id, data),
    onSuccess: () => {
      message.success(record ? "数据已更新" : "数据已保存");
      qc.invalidateQueries({ queryKey: ["model-records", entity.id] });
      qc.invalidateQueries({ queryKey: ["model-entities"] });
      qc.invalidateQueries({ queryKey: ["model-stats"] });
      onClose();
    },
    onError: (e: any) => message.error(e?.message || "保存失败"),
  });

  const initial = entity.fields.reduce<Record<string, any>>((acc, f) => {
    acc[f.key] = record ? record.data?.[f.key] ?? undefined : undefined;
    return acc;
  }, {});

  return (
    <Modal
      open
      width={640}
      title={`${record ? "编辑" : "新增"} · ${entity.name}`}
      okText="保存"
      cancelText="取消"
      confirmLoading={save.isPending}
      onCancel={onClose}
      onOk={() => form.submit()}
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={initial}
        onFinish={(values) => save.mutate(values)}
      >
        {entity.fields.map((f) => (
          <Form.Item
            key={f.key}
            name={f.key}
            label={`${f.label}${f.required ? " *" : ""}`}
            valuePropName={f.type === "bool" ? "checked" : undefined}
            rules={f.required ? [{ required: true, message: `${f.label}为必填项` }] : []}
            extra={f.unique ? "该字段不允许重复" : undefined}
          >
            <FieldControl field={f} />
          </Form.Item>
        ))}
      </Form>
    </Modal>
  );
}

// ---------- 实体设计器 ----------
function EntityModal({
  entity,
  onClose,
}: {
  entity: ModelEntityOut | null;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [form] = Form.useForm();
  const [rows, setRows] = useState<FieldDraft[]>(
    entity
      ? entity.fields.map((f) => ({
          key: f.key,
          label: f.label,
          type: f.type,
          required: !!f.required,
          unique: !!f.unique,
          optionsText: (f.options || []).join(","),
          defaultText: f.default === null || f.default === undefined ? "" : String(f.default),
        }))
      : [emptyDraft()]
  );

  const save = useMutation({
    mutationFn: (body: any) =>
      entity ? modelApi.updateEntity(entity.id, body) : modelApi.createEntity(body),
    onSuccess: () => {
      message.success(entity ? "实体已更新" : "实体已创建");
      qc.invalidateQueries({ queryKey: ["model-entities"] });
      qc.invalidateQueries({ queryKey: ["model-stats"] });
      onClose();
    },
    onError: (e: any) => message.error(e?.message || "保存失败"),
  });

  useEffect(() => {
    if (!entity) return;
    form.setFieldsValue({
      code: entity.code,
      name: entity.name,
      category: entity.category,
      description: entity.description,
      display_field: entity.display_field,
      status: entity.status,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const patch = (i: number, p: Partial<FieldDraft>) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...p } : r)));
  const move = (i: number, delta: number) =>
    setRows((rs) => {
      const target = i + delta;
      if (target < 0 || target >= rs.length) return rs;
      const next = [...rs];
      [next[i], next[target]] = [next[target], next[i]];
      return next;
    });

  const onSubmit = (values: any) => {
    const err = validateRows(rows);
    if (err) {
      message.error(err);
      return;
    }
    if (values.display_field && !rows.some((r) => r.key.trim() === values.display_field)) {
      message.error("主展示字段不在字段列表中");
      return;
    }
    save.mutate({
      code: entity ? undefined : values.code,
      name: values.name,
      category: values.category || "general",
      description: values.description || "",
      display_field: values.display_field || rows[0]?.key.trim() || "",
      status: values.status || "draft",
      fields: draftToFields(rows),
    });
  };

  const fieldCols: TableProps<FieldDraft>["columns"] = [
    {
      title: "标识 key",
      width: 150,
      render: (_, r, i) => (
        <Input
          value={r.key}
          placeholder="customer_no"
          onChange={(e) => patch(i, { key: e.target.value })}
        />
      ),
    },
    {
      title: "名称",
      width: 140,
      render: (_, r, i) => (
        <Input
          value={r.label}
          placeholder="客户编号"
          onChange={(e) => patch(i, { label: e.target.value })}
        />
      ),
    },
    {
      title: "类型",
      width: 130,
      render: (_, r, i) => (
        <Select
          value={r.type}
          style={{ width: "100%" }}
          options={Object.entries(FIELD_TYPE_LABELS).map(([v, l]) => ({ value: v, label: l }))}
          onChange={(v: ModelFieldType) => patch(i, { type: v })}
        />
      ),
    },
    {
      title: "选项（逗号分隔）",
      render: (_, r, i) =>
        OPTION_TYPES.includes(r.type) ? (
          <Input
            value={r.optionsText}
            placeholder="启用,停用"
            onChange={(e) => patch(i, { optionsText: e.target.value })}
          />
        ) : (
          <span style={{ color: "#bbb" }}>—</span>
        ),
    },
    {
      title: "必填",
      width: 60,
      align: "center",
      render: (_, r, i) => (
        <Switch size="small" checked={r.required} onChange={(v) => patch(i, { required: v })} />
      ),
    },
    {
      title: "唯一",
      width: 60,
      align: "center",
      render: (_, r, i) => (
        <Switch size="small" checked={r.unique} onChange={(v) => patch(i, { unique: v })} />
      ),
    },
    {
      title: "操作",
      width: 100,
      render: (_, __, i) => (
        <Space size={4}>
          <Button size="small" icon={<ArrowUpOutlined />} onClick={() => move(i, -1)} />
          <Button size="small" icon={<ArrowDownOutlined />} onClick={() => move(i, 1)} />
          <Button
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}
          />
        </Space>
      ),
    },
  ];

  return (
    <Modal
      open
      width={1080}
      title={entity ? `编辑实体 · ${entity.name}` : "新建实体"}
      okText="保存"
      cancelText="取消"
      confirmLoading={save.isPending}
      onCancel={onClose}
      onOk={() => form.submit()}
    >
      <Form form={form} layout="vertical" onFinish={onSubmit}>
        <Row gutter={12}>
          <Col span={8}>
            <Form.Item
              name="code"
              label="实体标识"
              rules={[{ pattern: KEY_RE, message: "小写字母开头，可含数字与下划线" }]}
              required={!entity}
              extra={entity ? "标识创建后不可修改" : undefined}
            >
              <Input placeholder="customer" disabled={!!entity} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="name" label="实体名称" rules={[{ required: true, message: "必填" }]}>
              <Input placeholder="客户档案" />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="category" label="分类">
              <Input placeholder="general" />
            </Form.Item>
          </Col>
        </Row>
        <Row gutter={12}>
          <Col span={8}>
            <Form.Item name="display_field" label="主展示字段">
              <Select
                allowClear
                placeholder="默认取第一个字段"
                options={rows
                  .filter((r) => r.key.trim())
                  .map((r) => ({ value: r.key.trim(), label: r.label || r.key }))}
              />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="status" label="状态">
              <Select
                options={[
                  { value: "draft", label: "草稿（不可录入数据）" },
                  { value: "published", label: "已发布（可录入数据）" },
                ]}
              />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="description" label="说明">
              <Input placeholder="一句话描述用途" />
            </Form.Item>
          </Col>
        </Row>
      </Form>

      <div style={{ display: "flex", justifyContent: "space-between", margin: "8px 0" }}>
        <span style={{ fontWeight: 600 }}>字段定义</span>
        <Button
          size="small"
          icon={<PlusOutlined />}
          onClick={() => setRows((rs) => [...rs, emptyDraft()])}
        >
          添加字段
        </Button>
      </div>
      <Table
        rowKey={(_, i) => String(i)}
        size="small"
        dataSource={rows}
        columns={fieldCols}
        pagination={false}
        scroll={{ y: 260 }}
      />
    </Modal>
  );
}

// ---------- 主页面 ----------
export default function ModelStudio() {
  const { hasPerm } = useAuth();
  const qc = useQueryClient();
  const canManage = hasPerm("model:manage");
  const canEditData = hasPerm("model:data:edit");

  const [entityId, setEntityId] = useState<number | undefined>(undefined);
  const [search, setSearch] = useState("");
  const [submittedSearch, setSubmittedSearch] = useState("");
  const [filterValue, setFilterValue] = useState<string | undefined>(undefined);
  const [page, setPage] = useState(1);
  const [entityModal, setEntityModal] = useState<{ open: boolean; entity: ModelEntityOut | null }>({
    open: false,
    entity: null,
  });
  const [dataModal, setDataModal] = useState<{
    open: boolean;
    record: ModelRecordOut | null;
  }>({ open: false, record: null });

  const entitiesQ = useQuery({
    queryKey: ["model-entities"],
    queryFn: () => modelApi.entities(),
  });
  const statsQ = useQuery({ queryKey: ["model-stats"], queryFn: modelApi.stats });
  const recordsQ = useQuery({
    queryKey: ["model-records", entityId, submittedSearch, filterValue, page],
    queryFn: () =>
      modelApi.records(entityId!, {
        q: submittedSearch || undefined,
        filters: filterValue ? { [filterField!]: filterValue } : undefined,
        offset: (page - 1) * PAGE_SIZE,
        limit: PAGE_SIZE,
      }),
    enabled: !!entityId,
  });

  const entities = entitiesQ.data || [];
  const entity = entities.find((e) => e.id === entityId);
  const optionFields = (entity?.fields || []).filter((f) => OPTION_TYPES.includes(f.type));
  const filterField = optionFields[0]?.key;

  useEffect(() => {
    if (!entityId && entities.length) setEntityId(entities[0].id);
  }, [entities, entityId]);

  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ["model-entities"] });
    qc.invalidateQueries({ queryKey: ["model-records", entityId] });
    qc.invalidateQueries({ queryKey: ["model-stats"] });
  };

  const publishM = useMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) =>
      modelApi.updateEntity(id, { status }),
    onSuccess: (_, v) => {
      message.success(v.status === "published" ? "实体已发布，可录入数据" : "实体已转为草稿");
      invalidateAll();
    },
    onError: (e: any) => message.error(e?.message || "操作失败"),
  });

  const delEntityM = useMutation({
    mutationFn: (id: number) => modelApi.removeEntity(id),
    onSuccess: () => {
      message.success("实体已删除");
      setEntityId(undefined);
      invalidateAll();
    },
    onError: (e: any) => message.error(e?.message || "删除失败"),
  });

  const delRecordM = useMutation({
    mutationFn: (id: number) => modelApi.removeRecord(id),
    onSuccess: () => {
      message.success("数据已删除");
      invalidateAll();
    },
    onError: (e: any) => message.error(e?.message || "删除失败"),
  });

  const columns: TableProps<ModelRecordOut>["columns"] = [
    { title: "编号", dataIndex: "serial_no", width: 130 },
    ...(entity?.fields || []).map((f) => ({
      title: f.label,
      key: f.key,
      dataIndex: ["data", f.key] as [string, string],
      width: f.type === "textarea" ? 240 : undefined,
      ellipsis: true,
      render: (v: any) => renderCell(f, v),
    })),
    {
      title: "更新时间",
      dataIndex: "updated_at",
      width: 170,
      render: (v: string) => (v ? v.slice(0, 19).replace("T", " ") : "—"),
    },
    {
      title: "操作",
      width: 130,
      fixed: "right" as const,
      render: (_, r) => (
        <Space size={4}>
          <Button
            size="small"
            disabled={!canEditData}
            onClick={() => setDataModal({ open: true, record: r })}
          >
            编辑
          </Button>
          <Popconfirm title="确认删除这条数据？" onConfirm={() => delRecordM.mutate(r.id)}>
            <Button size="small" danger disabled={!canEditData}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  if (entitiesQ.isLoading) {
    return (
      <Card>
        <div style={{ padding: 40, textAlign: "center", color: "#999" }}>加载建模数据中…</div>
      </Card>
    );
  }
  if (entitiesQ.isError) {
    return (
      <Card>
        <div style={{ padding: 40, textAlign: "center", color: "#cf1322" }}>
          {(entitiesQ.error as any)?.message || "建模数据加载失败"}
          <div style={{ marginTop: 12 }}>
            <Button onClick={() => entitiesQ.refetch()}>重试</Button>
          </div>
        </div>
      </Card>
    );
  }

  const stats = statsQ.data;
  const rows = (recordsQ.data as ModelRecordsPage | undefined)?.items || [];

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
        <h2 style={{ margin: 0 }}>建模引擎</h2>
        <Space>
          <span style={{ color: "#999", fontSize: 12 }}>
            {stats ? `更新于 ${stats.generated_at?.slice(0, 19).replace("T", " ")}` : ""}
          </span>
          <Button onClick={() => qc.invalidateQueries()}>刷新</Button>
          <Button
            type="primary"
            disabled={!canManage}
            onClick={() => setEntityModal({ open: true, entity: null })}
          >
            新建实体
          </Button>
        </Space>
      </div>

      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={6}>
          <Card>
            <Statistic title="实体模型" value={stats?.entities || 0} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="已发布"
              value={stats?.entities_published || 0}
              suffix={`/ ${stats?.entities || 0}`}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="数据总量" value={stats?.records || 0} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="今日新增" value={stats?.records_today || 0} />
          </Card>
        </Col>
      </Row>

      <Row gutter={12}>
        <Col span={6}>
          <Card title={`实体列表 (${entities.length})`} size="small">
            {entities.length === 0 && <Empty description="暂无实体，点击右上角新建" />}
            {entities.map((e) => (
              <div
                key={e.id}
                onClick={() => {
                  setEntityId(e.id);
                  setPage(1);
                  setFilterValue(undefined);
                }}
                style={{
                  padding: "8px 10px",
                  marginBottom: 6,
                  borderRadius: 6,
                  cursor: "pointer",
                  background: e.id === entityId ? "#e6f4ff" : "#fafafa",
                  border: `1px solid ${e.id === entityId ? "#91caff" : "#f0f0f0"}`,
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <b>{e.name}</b>
                  <Tag color={e.status === "published" ? "green" : "orange"}>
                    {e.status === "published" ? "已发布" : "草稿"}
                  </Tag>
                </div>
                <div style={{ fontSize: 12, color: "#888" }}>
                  {e.code} · {e.fields.length} 字段 · {e.record_count} 条数据
                </div>
              </div>
            ))}
          </Card>
        </Col>

        <Col span={18}>
          {!entity ? (
            <Card>
              <Empty description="请选择左侧实体，或新建一个" />
            </Card>
          ) : (
            <Card
              size="small"
              title={
                <Space wrap>
                  <span>
                    {entity.name} · 数据 ({recordsQ.data?.total ?? 0})
                  </span>
                  <Tag>{entity.code}</Tag>
                </Space>
              }
              extra={
                <Space wrap>
                  <Input.Search
                    placeholder="全字段搜索"
                    allowClear
                    style={{ width: 180 }}
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    onSearch={(v) => {
                      setSubmittedSearch(v.trim());
                      setPage(1);
                    }}
                  />
                  {filterField && (
                    <Select
                      allowClear
                      style={{ width: 140 }}
                      placeholder={optionFields[0]?.label}
                      value={filterValue}
                      onChange={(v) => {
                        setFilterValue(v);
                        setPage(1);
                      }}
                      options={(optionFields[0]?.options || []).map((o) => ({
                        value: o,
                        label: o,
                      }))}
                    />
                  )}
                  <Button
                    disabled={!canManage}
                    onClick={() => publishM.mutate({
                      id: entity.id,
                      status: entity.status === "published" ? "draft" : "published",
                    })}
                  >
                    {entity.status === "published" ? "转为草稿" : "发布"}
                  </Button>
                  <Button
                    disabled={!canManage}
                    onClick={() => setEntityModal({ open: true, entity })}
                  >
                    设计字段
                  </Button>
                  <Popconfirm
                    title="删除实体？"
                    description="实体下必须没有数据才能删除"
                    onConfirm={() => delEntityM.mutate(entity.id)}
                  >
                    <Button danger disabled={!canManage}>
                      删除
                    </Button>
                  </Popconfirm>
                  <Button
                    type="primary"
                    disabled={!canEditData || entity.status !== "published"}
                    onClick={() => setDataModal({ open: true, record: null })}
                  >
                    新增数据
                  </Button>
                </Space>
              }
            >
              {entity.status !== "published" && (
                <div style={{ marginBottom: 8, color: "#d46b08", fontSize: 13 }}>
                  该实体处于草稿状态，发布后即可录入数据。
                </div>
              )}
              {recordsQ.isLoading ? (
                <div style={{ padding: 30, textAlign: "center", color: "#999" }}>加载数据中…</div>
              ) : (
                <Table
                  rowKey="id"
                  size="small"
                  dataSource={rows}
                  columns={columns}
                  scroll={{ x: "max-content" }}
                  pagination={{
                    current: page,
                    pageSize: PAGE_SIZE,
                    total: recordsQ.data?.total || 0,
                    onChange: (p) => setPage(p),
                    showSizeChanger: false,
                  }}
                />
              )}
            </Card>
          )}
        </Col>
      </Row>

      {entityModal.open && (
        <EntityModal entity={entityModal.entity} onClose={() => setEntityModal({ open: false, entity: null })} />
      )}
      {dataModal.open && entity && (
        <DataFormModal
          entity={entity}
          record={dataModal.record}
          onClose={() => setDataModal({ open: false, record: null })}
        />
      )}
    </div>
  );
}
