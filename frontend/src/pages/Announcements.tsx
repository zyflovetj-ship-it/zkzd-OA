import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Form,
  Input,
  Modal,
  Switch,
  Table,
  Tag,
  message,
} from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { annApi } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";

export default function Announcements() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();

  const listQ = useQuery({ queryKey: ["announcements"], queryFn: annApi.list });
  const createM = useMutation({
    mutationFn: (v: any) => annApi.create(v),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["announcements"] });
      setOpen(false);
      form.resetFields();
      message.success("已发布公告");
    },
    onError: (e: any) => message.error(e?.message || "发布失败"),
  });

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
        <h2>公告文档</h2>
        {["admin", "manager"].includes(user?.role_name ?? "") && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
            发布公告
          </Button>
        )}
      </div>
      <Table
        rowKey="id"
        loading={listQ.isLoading}
        dataSource={listQ.data || []}
        columns={[
          { title: "ID", dataIndex: "id" },
          { title: "标题", dataIndex: "title" },
          {
            title: "置顶",
            dataIndex: "pinned",
            render: (v: boolean) => <Tag color={v ? "gold" : "default"}>{v ? "置顶" : "普通"}</Tag>,
          },
          {
            title: "发布",
            dataIndex: "published",
            render: (v: boolean) => <Tag color={v ? "green" : "red"}>{v ? "已发布" : "草稿"}</Tag>,
          },
          { title: "更新时间", dataIndex: "updated_at" },
        ]}
      />
      <Modal
        title="发布公告"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => form.submit()}
        okText="发布"
      >
        <Form form={form} layout="vertical" onFinish={(v) => createM.mutate(v)}>
          <Form.Item name="title" label="标题" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="content" label="内容">
            <Input.TextArea rows={4} />
          </Form.Item>
          <Form.Item name="pinned" label="置顶" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="published" label="立即发布" valuePropName="checked" initialValue={true}>
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
