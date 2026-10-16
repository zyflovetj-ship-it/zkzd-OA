import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  message,
} from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { leaveApi } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";

const statusColor = (s: string) =>
  s === "approved" ? "green" : s === "rejected" ? "red" : "orange";

export default function Leave() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();

  const listQ = useQuery({ queryKey: ["leave"], queryFn: leaveApi.list });
  const canReview = ["admin", "manager"].includes(user?.role_name ?? ""); // 管理员/经理可审批

  const createM = useMutation({
    mutationFn: (v: any) => leaveApi.create(v),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["leave"] });
      setOpen(false);
      form.resetFields();
      message.success("已提交请假申请");
    },
    onError: (e: any) => message.error(e?.message || "提交失败"),
  });

  const reviewM = useMutation({
    mutationFn: (v: { id: number; body: any }) => leaveApi.review(v.id, v.body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["leave"] });
      message.success("已处理");
    },
    onError: (e: any) => message.error(e?.message || "处理失败"),
  });

  const columns = [
    { title: "ID", dataIndex: "id" },
    { title: "申请人", dataIndex: "user_id" },
    { title: "类型", dataIndex: "leave_type" },
    { title: "开始", dataIndex: "start_date" },
    { title: "结束", dataIndex: "end_date" },
    {
      title: "状态",
      dataIndex: "status",
      render: (v: string) => <Tag color={statusColor(v)}>{v}</Tag>,
    },
    {
      title: "操作",
      render: (_: any, r: any) =>
        canReview && r.status === "pending" ? (
          <Space>
            <Button
              size="small"
              type="primary"
              onClick={() => reviewM.mutate({ id: r.id, body: { approve: true } })}
            >
              通过
            </Button>
            <Button
              size="small"
              danger
              onClick={() =>
                reviewM.mutate({ id: r.id, body: { approve: false, rejection_reason: "未通过" } })
              }
            >
              驳回
            </Button>
          </Space>
        ) : null,
    },
  ];

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
        <h2>请假审批</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
          申请请假
        </Button>
      </div>
      <Table
        rowKey="id"
        loading={listQ.isLoading}
        dataSource={listQ.data || []}
        columns={columns}
      />
      <Modal
        title="申请请假"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => form.submit()}
        okText="提交"
      >
        <Form form={form} layout="vertical" onFinish={(v) => createM.mutate(v)}>
          <Form.Item name="leave_type" label="类型" rules={[{ required: true }]}>
            <Select
              options={[
                { value: "annual", label: "年假" },
                { value: "sick", label: "病假" },
                { value: "personal", label: "事假" },
                { value: "other", label: "其他" },
              ]}
            />
          </Form.Item>
          <Form.Item name="start_date" label="开始日期" rules={[{ required: true }]}>
            <Input type="date" />
          </Form.Item>
          <Form.Item name="end_date" label="结束日期" rules={[{ required: true }]}>
            <Input type="date" />
          </Form.Item>
          <Form.Item name="reason" label="事由">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
