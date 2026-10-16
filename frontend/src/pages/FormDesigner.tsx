import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  message,
  type TableProps,
} from "antd";
import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import { wfApi } from "../api/endpoints";
import type { FormDefinitionOut, FormField } from "../types";

type FieldRow = FormField;

export default function FormDesigner() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();
  const [rows, setRows] = useState<FieldRow[]>([]);

  const formsQ = useQuery({ queryKey: ["wf-forms"], queryFn: wfApi.forms });

  const createM = useMutation({
    mutationFn: (body: { code: string; name: string; fields: FormField[] }) =>
      wfApi.createForm(body),
    onSuccess: () => {
      message.success("表单已创建");
      setOpen(false);
      form.resetFields();
      setRows([]);
      qc.invalidateQueries({ queryKey: ["wf-forms"] });
    },
    onError: (e: any) => message.error(e?.message || "创建失败"),
  });

  const updateRow = (i: number, patch: Partial<FieldRow>) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  const columns: TableProps<FieldRow>["columns"] = [
    {
      title: "字段标识(key)",
      dataIndex: "key",
      render: (v, r, i) => (
        <Input value={v} onChange={(e) => updateRow(i, { key: e.target.value })} />
      ),
    },
    {
      title: "字段名称(label)",
      dataIndex: "label",
      render: (v, r, i) => (
        <Input value={v} onChange={(e) => updateRow(i, { label: e.target.value })} />
      ),
    },
    {
      title: "类型",
      dataIndex: "type",
      render: (v, r, i) => (
        <Select
          style={{ width: 120 }}
          value={v}
          onChange={(val) => updateRow(i, { type: val })}
          options={[
            { value: "text", label: "文本" },
            { value: "number", label: "数字" },
            { value: "date", label: "日期" },
            { value: "select", label: "下拉" },
            { value: "textarea", label: "多行文本" },
          ]}
        />
      ),
    },
    {
      title: "必填",
      dataIndex: "required",
      width: 70,
      render: (v, r, i) => (
        <Switch checked={!!v} onChange={(c) => updateRow(i, { required: c })} />
      ),
    },
    {
      title: "选项(下拉用,逗号分隔)",
      dataIndex: "options",
      render: (v, r, i) => (
        <Input
          value={(v || []).join(",")}
          placeholder="选项A,选项B"
          onChange={(e) =>
            updateRow(i, {
              options: e.target.value
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean),
            })
          }
        />
      ),
    },
    {
      title: "操作",
      width: 70,
      render: (_, r, i) => (
        <Button danger size="small" icon={<DeleteOutlined />} onClick={() => setRows(rows.filter((_, j) => j !== i))} />
      ),
    },
  ];

  const formsCols: TableProps<FormDefinitionOut>["columns"] = [
    { title: "编码", dataIndex: "code" },
    { title: "名称", dataIndex: "name" },
    {
      title: "字段数",
      dataIndex: "fields",
      render: (f: FormField[]) => <Tag>{f?.length || 0}</Tag>,
    },
    {
      title: "字段概览",
      dataIndex: "fields",
      render: (f: FormField[]) => (f || []).map((x) => x.label).join("、") || "—",
    },
  ];

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
        <h2>表单设计</h2>
        <Button
          type="primary"
          onClick={() => {
            setRows([]);
            setOpen(true);
          }}
        >
          新建表单
        </Button>
      </div>

      <Table
        rowKey="id"
        loading={formsQ.isLoading}
        dataSource={formsQ.data || []}
        columns={formsCols}
        pagination={false}
      />

      <Modal
        title="新建表单"
        open={open}
        width={860}
        onCancel={() => setOpen(false)}
        onOk={() => form.submit()}
        okText="创建"
        confirmLoading={createM.isPending}
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={(v) => {
            if (!rows.length) return message.warning("请至少添加一个字段");
            if (rows.some((r) => !r.key || !r.label))
              return message.warning("字段标识与名称必填");
            createM.mutate({ code: v.code, name: v.name, fields: rows });
          }}
        >
          <Space>
            <Form.Item name="code" label="表单编码" rules={[{ required: true }]}>
              <Input placeholder="如 expense-form" style={{ width: 240 }} />
            </Form.Item>
            <Form.Item name="name" label="表单名称" rules={[{ required: true }]}>
              <Input placeholder="如 报销单" style={{ width: 240 }} />
            </Form.Item>
          </Space>
        </Form>

        <Table rowKey={(_, i) => String(i)} dataSource={rows} columns={columns} pagination={false} />

        <Button
          type="dashed"
          icon={<PlusOutlined />}
          style={{ marginTop: 12 }}
          onClick={() =>
            setRows((rs) => [...rs, { key: "", label: "", type: "text", required: false, options: [] }])
          }
        >
          添加字段
        </Button>
      </Modal>
    </div>
  );
}
