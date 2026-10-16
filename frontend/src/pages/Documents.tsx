import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Upload,
  message,
  type UploadFile,
} from "antd";
import {
  DeleteOutlined,
  DownloadOutlined,
  PlusOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import { docApi } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import { DOC_CATEGORY_LABELS, type DocumentOut } from "../types";

function formatSize(bytes: number): string {
  if (!bytes || bytes < 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  return `${(bytes / Math.pow(1024, i)).toFixed(i ? 1 : 0)} ${units[i]}`;
}

const CATEGORY_OPTIONS = [
  { value: "all", label: "全部分类" },
  ...Object.entries(DOC_CATEGORY_LABELS).map(([value, label]) => ({ value, label })),
];

export default function Documents() {
  const qc = useQueryClient();
  const { hasPerm } = useAuth();
  const canUpload = hasPerm("doc:upload");
  const canManage = hasPerm("doc:manage");

  const [category, setCategory] = useState<string>("all");
  const [q, setQ] = useState<string>("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();
  const [file, setFile] = useState<File | null>(null);

  const listQ = useQuery({
    queryKey: ["documents", category, q, page, pageSize],
    queryFn: () =>
      docApi.list({
        category: category === "all" ? undefined : category,
        q: q || undefined,
        offset: (page - 1) * pageSize,
        limit: pageSize,
      }),
  });

  const uploadM = useMutation({
    mutationFn: (v: { title: string; category: string; description: string; file: File }) =>
      docApi.upload(v),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["documents"] });
      setOpen(false);
      form.resetFields();
      setFile(null);
      message.success("文档已上传");
    },
    onError: (e: any) => message.error(e?.message || "上传失败"),
  });

  const removeM = useMutation({
    mutationFn: (id: number) => docApi.remove(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["documents"] });
      message.success("文档已删除");
    },
    onError: (e: any) => message.error(e?.message || "删除失败"),
  });

  const handleDownload = async (doc: DocumentOut) => {
    try {
      await docApi.download(doc);
    } catch (e: any) {
      message.error(e?.message || "下载失败");
    }
  };

  // 阻止自动上传，等表单提交统一上传
  const beforeUpload = (f: File) => {
    setFile(f);
    return false;
  };

  const columns = [
    { title: "标题", dataIndex: "title" },
    {
      title: "分类",
      dataIndex: "category",
      render: (c: string) => <Tag color="blue">{DOC_CATEGORY_LABELS[c] || c}</Tag>,
    },
    {
      title: "类型",
      dataIndex: "file_type",
      render: (t: string) => <Tag>{t ? t.toUpperCase() : "-"}</Tag>,
    },
    { title: "大小", dataIndex: "file_size", render: (s: number) => formatSize(s) },
    { title: "上传人", dataIndex: "owner_name" },
    { title: "更新时间", dataIndex: "updated_at" },
    {
      title: "操作",
      render: (_: any, doc: DocumentOut) => (
        <Space>
          <Button size="small" icon={<DownloadOutlined />} onClick={() => handleDownload(doc)}>
            下载
          </Button>
          {canManage && (
            <Popconfirm title="确认删除该文档？" onConfirm={() => removeM.mutate(doc.id)}>
              <Button size="small" danger icon={<DeleteOutlined />} loading={removeM.isPending}>
                删除
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
        <h2>文档中心</h2>
        {canUpload && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
            上传文档
          </Button>
        )}
      </div>

      <Space style={{ marginBottom: 12 }} wrap>
        <Select
          value={category}
          style={{ width: 160 }}
          options={CATEGORY_OPTIONS}
          onChange={(v) => {
            setCategory(v);
            setPage(1);
          }}
        />
        <Input.Search
          allowClear
          placeholder="搜索标题"
          style={{ width: 240 }}
          onSearch={(v) => {
            setQ(v);
            setPage(1);
          }}
          onChange={(e) => {
            if (!e.target.value) {
              setQ("");
              setPage(1);
            }
          }}
        />
        <Button onClick={() => listQ.refetch()}>刷新</Button>
      </Space>

      <Table
        rowKey="id"
        loading={listQ.isLoading}
        dataSource={listQ.data?.items || []}
        columns={columns}
        pagination={{
          current: page,
          pageSize,
          total: listQ.data?.total || 0,
          showSizeChanger: true,
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
      />

      <Modal
        title="上传文档"
        open={open}
        onCancel={() => {
          setOpen(false);
          form.resetFields();
          setFile(null);
        }}
        onOk={() => form.submit()}
        okText="上传"
        confirmLoading={uploadM.isPending}
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ category: "general" }}
          onFinish={(v) => {
            if (!file) {
              message.warning("请先选择文件");
              return;
            }
            uploadM.mutate({ ...v, file });
          }}
        >
          <Form.Item
            name="title"
            label="标题"
            rules={[{ required: true, message: "请输入标题" }]}
          >
            <Input />
          </Form.Item>
          <Form.Item name="category" label="分类">
            <Select
              options={Object.entries(DOC_CATEGORY_LABELS).map(([value, label]) => ({
                value,
                label,
              }))}
            />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} maxLength={500} />
          </Form.Item>
          <Form.Item label="文件" required>
            <Upload
              beforeUpload={beforeUpload}
              maxCount={1}
              onRemove={() => setFile(null)}
              fileList={
                file ? ([{ uid: "-1", name: file.name, status: "done" }] as UploadFile[]) : []
              }
            >
              <Button icon={<UploadOutlined />}>选择文件</Button>
            </Upload>
            <div style={{ color: "#999", fontSize: 12, marginTop: 4 }}>
              支持 pdf/doc/xls/ppt/图片/压缩包等，单文件 ≤ 20MB
            </div>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
