import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Form, Input, Modal, Popconfirm, Select, Space, Tag, message } from "antd";
import { PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import { deptApi, usersApi } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import {
  DataTable,
  FilterBar,
  FilterItem,
  PageContainer,
  StatusTag,
} from "../components/framework";

/** 角色标签配色（admin 高危、manager 管理、其余默认） */
const ROLE_COLOR: Record<string, string> = {
  admin: "volcano",
  manager: "geekblue",
};

export default function Employees() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const isAdmin = user?.role_name === "admin";

  const [keywordInput, setKeywordInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [pwdOpen, setPwdOpen] = useState(false);
  const [target, setTarget] = useState<any>(null);
  const [cform] = Form.useForm();
  const [eform] = Form.useForm();
  const [pform] = Form.useForm();

  const usersQ = useQuery({
    queryKey: ["users", keyword],
    queryFn: () => usersApi.list(keyword || undefined),
  });
  const rolesQ = useQuery({ queryKey: ["roles"], queryFn: usersApi.roles });
  const deptsQ = useQuery({ queryKey: ["departments"], queryFn: deptApi.list });

  const deptName = (id: number | null) =>
    id == null ? "-" : deptsQ.data?.find((d) => d.id === id)?.name ?? "#" + id;

  const invalidate = () => qc.invalidateQueries({ queryKey: ["users"] });

  const createM = useMutation({
    mutationFn: (v: any) => usersApi.create(v),
    onSuccess: () => {
      invalidate();
      setCreateOpen(false);
      cform.resetFields();
      message.success("已创建员工");
    },
    onError: (e: any) => message.error(e?.message || "创建失败"),
  });

  const updateM = useMutation({
    mutationFn: (v: { id: number; body: any }) => usersApi.update(v.id, v.body),
    onSuccess: (_, v) => {
      invalidate();
      message.success(v.body.password ? "密码已重置" : "已保存");
      setEditOpen(false);
      setPwdOpen(false);
    },
    onError: (e: any) => message.error(e?.message || "保存失败"),
  });

  const columns = [
    { title: "ID", dataIndex: "id", width: 70 },
    { title: "用户名", dataIndex: "username", width: 140 },
    { title: "姓名", dataIndex: "full_name", width: 120 },
    { title: "邮箱", dataIndex: "email", ellipsis: true },
    {
      title: "角色",
      dataIndex: "role_name",
      width: 110,
      render: (v: string) => <Tag color={ROLE_COLOR[v] || "default"}>{v || "-"}</Tag>,
    },
    {
      title: "部门",
      dataIndex: "department_id",
      width: 140,
      render: (v: number | null) => deptName(v),
    },
    {
      title: "状态",
      dataIndex: "is_active",
      width: 90,
      render: (v: boolean) => <StatusTag status={v ? "active" : "disabled"} />,
    },
    {
      title: "操作",
      key: "op",
      width: 230,
      fixed: "right" as const,
      render: (_: any, row: any) =>
        isAdmin ? (
          <Space size={4}>
            <Button
              type="link"
              size="small"
              onClick={() => {
                setTarget(row);
                eform.setFieldsValue({
                  full_name: row.full_name,
                  email: row.email,
                  role_id: row.role_id,
                  department_id: row.department_id,
                });
                setEditOpen(true);
              }}
            >
              编辑
            </Button>
            <Button
              type="link"
              size="small"
              onClick={() => {
                setTarget(row);
                pform.resetFields();
                setPwdOpen(true);
              }}
            >
              重置密码
            </Button>
            <Popconfirm
              title={"确定" + (row.is_active ? "停用" : "启用") + "「" + row.username + "」？"}
              onConfirm={() => updateM.mutate({ id: row.id, body: { is_active: !row.is_active } })}
            >
              <Button type="link" size="small" danger={row.is_active}>
                {row.is_active ? "停用" : "启用"}
              </Button>
            </Popconfirm>
          </Space>
        ) : (
          <span style={{ color: "var(--zk-text-tertiary)" }}>无权限</span>
        ),
    },
  ];

  return (
    <PageContainer
      title="账户管理"
      description="维护员工账号、角色与部门归属；停用后该账号将无法登录。"
    >
      <FilterBar
        onSearch={() => setKeyword(keywordInput)}
        onReset={() => {
          setKeywordInput("");
          setKeyword("");
        }}
      >
        <FilterItem label="关键字" width={240}>
          <Input
            allowClear
            placeholder="搜索用户名 / 姓名"
            value={keywordInput}
            onChange={(e) => setKeywordInput(e.target.value)}
          />
        </FilterItem>
      </FilterBar>

      <DataTable
        title="员工列表"
        rowKey="id"
        loading={usersQ.isLoading}
        dataSource={usersQ.data || []}
        columns={columns}
        scroll={{ x: "max-content" }}
        toolbar={
          <>
            {isAdmin ? (
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
                新建员工
              </Button>
            ) : null}
            <Button
              icon={<ReloadOutlined />}
              onClick={() => invalidate()}
              loading={usersQ.isFetching}
            >
              刷新
            </Button>
            <span style={{ marginLeft: "auto", fontSize: 13, color: "var(--zk-text-secondary)" }}>
              共 {usersQ.data?.length ?? 0} 人
            </span>
          </>
        }
      />

      {/* 新建 */}
      <Modal
        title="新建员工"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => cform.submit()}
        okText="创建"
        confirmLoading={createM.isPending}
        destroyOnHidden
      >
        <Form form={cform} layout="vertical" onFinish={(v) => createM.mutate(v)}>
          <Form.Item name="username" label="用户名" rules={[{ required: true, message: "请输入用户名" }]}>
            <Input placeholder="登录账号，创建后不可修改" />
          </Form.Item>
          <Form.Item
            name="password"
            label="初始密码"
            rules={[{ required: true, min: 6, message: "至少 6 位" }]}
          >
            <Input.Password placeholder="至少 6 位" />
          </Form.Item>
          <Form.Item name="full_name" label="姓名">
            <Input />
          </Form.Item>
          <Form.Item name="email" label="邮箱" rules={[{ type: "email", message: "邮箱格式不正确" }]}>
            <Input />
          </Form.Item>
          <Form.Item name="role_id" label="角色" rules={[{ required: true, message: "请选择角色" }]}>
            <Select
              placeholder="请选择角色"
              options={rolesQ.data?.map((r) => ({ value: r.id, label: r.name }))}
              loading={rolesQ.isLoading}
            />
          </Form.Item>
          <Form.Item name="department_id" label="部门">
            <Select
              allowClear
              placeholder="可不选"
              options={deptsQ.data?.map((d) => ({ value: d.id, label: d.name }))}
              loading={deptsQ.isLoading}
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑 */}
      <Modal
        title={"编辑账户 · " + (target?.username ?? "")}
        open={editOpen}
        onCancel={() => setEditOpen(false)}
        onOk={() => eform.submit()}
        okText="保存"
        confirmLoading={updateM.isPending}
        destroyOnHidden
      >
        <Form
          form={eform}
          layout="vertical"
          onFinish={(v) => updateM.mutate({ id: target.id, body: v })}
        >
          <Form.Item name="full_name" label="姓名">
            <Input />
          </Form.Item>
          <Form.Item name="email" label="邮箱" rules={[{ type: "email", message: "邮箱格式不正确" }]}>
            <Input />
          </Form.Item>
          <Form.Item name="role_id" label="角色">
            <Select options={rolesQ.data?.map((r) => ({ value: r.id, label: r.name }))} />
          </Form.Item>
          <Form.Item name="department_id" label="部门">
            <Select
              allowClear
              options={deptsQ.data?.map((d) => ({ value: d.id, label: d.name }))}
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* 重置密码 */}
      <Modal
        title={"重置密码 · " + (target?.username ?? "")}
        open={pwdOpen}
        onCancel={() => setPwdOpen(false)}
        onOk={() => pform.submit()}
        okText="重置"
        confirmLoading={updateM.isPending}
        destroyOnHidden
      >
        <Form
          form={pform}
          layout="vertical"
          onFinish={(v) => updateM.mutate({ id: target.id, body: { password: v.password } })}
        >
          <Form.Item
            name="password"
            label="新密码"
            rules={[{ required: true, min: 6, message: "至少 6 位" }]}
            extra="重置后请通知该用户；其已签发的刷新令牌在过期前仍然有效。"
          >
            <Input.Password />
          </Form.Item>
        </Form>
      </Modal>
    </PageContainer>
  );
}
