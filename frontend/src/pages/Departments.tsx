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
  message,
} from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { deptApi, usersApi } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import type { DepartmentOut } from "../types";

export default function Departments() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const isAdmin = user?.role_name === "admin";

  const [createOpen, setCreateOpen] = useState(false);
  const [form] = Form.useForm();

  const deptsQ = useQuery({
    queryKey: ["departments"],
    queryFn: deptApi.list,
  });
  const usersQ = useQuery({ queryKey: ["users-all"], queryFn: () => usersApi.list() });

  const deptName = (id: number | null) =>
    id == null ? "-" : deptsQ.data?.find((d) => d.id === id)?.name ?? `#${id}`;
  const userName = (id: number | null) =>
    id == null ? "-" : usersQ.data?.find((u) => u.id === id)?.full_name ?? `#${id}`;

  const invalidate = () => qc.invalidateQueries({ queryKey: ["departments"] });

  const createM = useMutation({
    mutationFn: (v: any) => deptApi.create(v),
    onSuccess: () => {
      invalidate();
      setCreateOpen(false);
      form.resetFields();
      message.success("已创建部门");
    },
    onError: (e: any) => message.error(e?.message || "创建失败"),
  });

  const columns = [
    { title: "ID", dataIndex: "id", width: 70 },
    { title: "部门名称", dataIndex: "name" },
    {
      title: "上级部门",
      dataIndex: "parent_id",
      render: (v: number | null) => deptName(v),
    },
    {
      title: "负责人",
      dataIndex: "manager_id",
      render: (v: number | null) => userName(v),
    },
  ];

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
        <h2>部门管理</h2>
        {isAdmin && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
            新建部门
          </Button>
        )}
      </div>

      <Table
        rowKey="id"
        loading={deptsQ.isLoading}
        dataSource={deptsQ.data || []}
        columns={columns}
        pagination={false}
      />

      <Modal
        title="新建部门"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => form.submit()}
        okText="创建"
      >
        <Form form={form} layout="vertical" onFinish={(v) => createM.mutate(v)}>
          <Form.Item name="name" label="部门名称" rules={[{ required: true }]}>
            <Input placeholder="如：研发部" />
          </Form.Item>
          <Form.Item name="parent_id" label="上级部门">
            <Select
              allowClear
              placeholder="不选则表示顶级部门"
              options={deptsQ.data?.map((d: DepartmentOut) => ({ value: d.id, label: d.name }))}
              loading={deptsQ.isLoading}
            />
          </Form.Item>
          <Form.Item name="manager_id" label="部门负责人">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="选择负责人"
              options={usersQ.data?.map((u) => ({
                value: u.id,
                label: u.full_name || u.username,
              }))}
              loading={usersQ.isLoading}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
