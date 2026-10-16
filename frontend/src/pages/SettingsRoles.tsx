import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  type TableProps,
  message,
} from "antd";
import { permApi, rolesApi } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import type { PermissionOut, Role } from "../types";

const SCOPE_OPTIONS = [
  { value: "all", label: "全部数据（本部门及全公司）" },
  { value: "dept", label: "仅本部门数据" },
  { value: "self", label: "仅本人数据" },
];

const SCOPE_LABEL: Record<string, string> = {
  all: "全部数据",
  dept: "仅本部门",
  self: "仅本人",
};
const SCOPE_COLOR: Record<string, string> = {
  all: "blue",
  dept: "green",
  self: "default",
};

export default function SettingsRoles() {
  const { hasPerm } = useAuth();
  const canView = hasPerm("org:role:view");
  const canManage = hasPerm("org:role:manage");

  const [roleId, setRoleId] = useState<number | undefined>(undefined);
  const [scopeSaving, setScopeSaving] = useState(false);

  // 角色管理弹窗状态
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Role | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();

  const rolesQ = useQuery({ queryKey: ["roles"], queryFn: rolesApi.list });
  const permsQ = useQuery({ queryKey: ["permissions"], queryFn: () => permApi.list() });
  const rolePermsQ = useQuery({
    queryKey: ["role-permissions", roleId],
    queryFn: () => permApi.rolePermissions(roleId as number),
    enabled: roleId != null,
  });

  const activeRole = rolesQ.data?.find((r) => r.id === roleId);
  const assignedCodes = useMemo(
    () => new Set((rolePermsQ.data || []).map((p) => p.code)),
    [rolePermsQ.data]
  );

  // 按分类分组权限
  const grouped = useMemo(() => {
    const map = new Map<string, PermissionOut[]>();
    for (const p of permsQ.data || []) {
      if (!map.has(p.category)) map.set(p.category, []);
      map.get(p.category)!.push(p);
    }
    return Array.from(map.entries());
  }, [permsQ.data]);

  if (!canView) {
    return <Alert type="warning" showIcon message="无角色权限查看权限（需 org:role:view）" />;
  }

  const openCreate = () => {
    setEditing(null);
    setModalOpen(true);
  };
  const openEdit = (role: Role) => {
    setEditing(role);
    setModalOpen(true);
  };
  const onSubmit = async (values: {
    name?: string;
    description?: string;
    data_scope?: string;
  }) => {
    setSaving(true);
    try {
      if (editing) {
        await rolesApi.update(editing.id, {
          description: values.description ?? "",
          data_scope: values.data_scope || "all",
        });
      } else {
        await rolesApi.create({
          name: values.name!,
          description: values.description ?? "",
          data_scope: ((values.data_scope as Role["data_scope"]) || "all") as
            | "all"
            | "dept"
            | "self",
        });
      }
      message.success("已保存");
      setModalOpen(false);
      rolesQ.refetch();
    } catch (e: any) {
      message.error(e?.message || "保存失败");
    } finally {
      setSaving(false);
    }
  };
  const onDelete = async (role: Role) => {
    try {
      await rolesApi.remove(role.id);
      message.success("角色已删除");
      if (roleId === role.id) setRoleId(undefined);
      rolesQ.refetch();
    } catch (e: any) {
      message.error(e?.message || "删除失败");
    }
  };

  const onGroupChange = async (checked: string[], categoryCodes: string[]) => {
    if (roleId == null) return;
    const added = checked.filter((c) => !assignedCodes.has(c));
    const removed = categoryCodes.filter((c) => !checked.includes(c));
    const all = permsQ.data || [];
    try {
      await Promise.all([
        ...added.map((code) =>
          permApi.assign(roleId, all.find((p) => p.code === code)!.id)
        ),
        ...removed.map((code) =>
          permApi.revoke(roleId, all.find((p) => p.code === code)!.id)
        ),
      ]);
      message.success("权限已更新");
      rolePermsQ.refetch();
    } catch (e: any) {
      message.error(e?.message || "更新失败");
    }
  };

  const onScopeChange = async (value: string) => {
    if (roleId == null) return;
    setScopeSaving(true);
    try {
      await rolesApi.update(roleId, { data_scope: value });
      message.success("数据范围已更新");
      rolesQ.refetch();
    } catch (e: any) {
      message.error(e?.message || "更新失败");
    } finally {
      setScopeSaving(false);
    }
  };

  const columns: TableProps<Role>["columns"] = [
    {
      title: "角色标识",
      dataIndex: "name",
      render: (name: string) => (
        <Space>
          <Typography.Text strong>{name}</Typography.Text>
          {name === "admin" && <Tag color="red">内置</Tag>}
        </Space>
      ),
    },
    { title: "描述", dataIndex: "description" },
    {
      title: "数据范围",
      dataIndex: "data_scope",
      render: (scope?: string) => (
        <Tag color={SCOPE_COLOR[scope || "all"]}>{SCOPE_LABEL[scope || "all"]}</Tag>
      ),
    },
    {
      title: "操作",
      key: "op",
      render: (_: unknown, role: Role) => (
        <Space>
          {canManage && (
            <Button type="link" size="small" onClick={(e) => { e.stopPropagation(); openEdit(role); }}>
              编辑
            </Button>
          )}
          {canManage && role.name !== "admin" && (
            <Popconfirm
              title="确认删除该角色？"
              description="删除后该角色与权限的关联将一并清除，且不可恢复。"
              okText="删除"
              okButtonProps={{ danger: true }}
              cancelText="取消"
              onConfirm={() => onDelete(role)}
            >
              <Button type="link" size="small" danger onClick={(e) => e.stopPropagation()}>
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
      <h2>角色权限管理</h2>

      {/* 角色管理：列表 + 新建 / 编辑 / 删除 */}
      <Card
        title="角色管理"
        style={{ marginBottom: 16 }}
        extra={
          canManage ? (
            <Button type="primary" size="small" onClick={openCreate}>
              新建角色
            </Button>
          ) : null
        }
      >
        <Table<Role>
          rowKey="id"
          size="small"
          loading={rolesQ.isLoading}
          dataSource={rolesQ.data || []}
          columns={columns}
          pagination={false}
          rowSelection={{
            type: "radio",
            selectedRowKeys: roleId != null ? [roleId] : [],
            onChange: (keys) => setRoleId(keys[0] as number),
          }}
          onRow={(record) => ({
            onClick: () => setRoleId(record.id),
            style: { cursor: "pointer" },
          })}
        />
      </Card>

      {/* 选中角色的权限配置 */}
      <Card style={{ marginBottom: 16 }}>
        <Form layout="inline">
          <Form.Item label="数据范围">
            <Select
              style={{ width: 260 }}
              value={activeRole?.data_scope || "all"}
              options={SCOPE_OPTIONS}
              disabled={!canManage || roleId == null}
              loading={scopeSaving}
              onChange={onScopeChange}
            />
          </Form.Item>
        </Form>
        {activeRole?.name === "admin" && (
          <Alert
            style={{ marginTop: 12 }}
            type="info"
            showIcon
            message="管理员（admin）为超级角色，服务端恒以通配权限处理，下方勾选仅作展示。"
          />
        )}
      </Card>

      {roleId == null ? (
        <Empty description="请选择上方角色以配置权限" />
      ) : rolePermsQ.isLoading ? (
        <Spin />
      ) : (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 16 }}>
          {grouped.map(([category, list]) => {
            const codes = list.map((p) => p.code);
            const value = list.filter((p) => assignedCodes.has(p.code)).map((p) => p.code);
            return (
              <Card key={category} title={category} style={{ width: 320 }}>
                <Checkbox.Group
                  disabled={!canManage}
                  value={value}
                  onChange={(v) => onGroupChange(v as string[], codes)}
                >
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {list.map((p) => (
                      <Checkbox key={p.code} value={p.code}>
                        <Typography.Text>{p.name}</Typography.Text>
                        <Typography.Text type="secondary" style={{ marginLeft: 6, fontSize: 12 }}>
                          {p.code}
                        </Typography.Text>
                      </Checkbox>
                    ))}
                  </div>
                </Checkbox.Group>
              </Card>
            );
          })}
        </div>
      )}

      {/* 新建 / 编辑角色弹窗 */}
      <Modal
        open={modalOpen}
        title={editing ? "编辑角色" : "新建角色"}
        okText="保存"
        confirmLoading={saving}
        onOk={() => form.submit()}
        onCancel={() => setModalOpen(false)}
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={onSubmit}
          initialValues={
            editing
              ? { name: editing.name, description: editing.description, data_scope: editing.data_scope || "all" }
              : { data_scope: "all" }
          }
        >
          <Form.Item
            name="name"
            label="角色标识（英文）"
            rules={[
              { required: true, message: "请输入角色标识" },
              {
                pattern: /^[a-z][a-z0-9_]*$/,
                message: "小写字母开头，仅含小写字母 / 数字 / 下划线",
              },
            ]}
          >
            <Input disabled={!!editing} placeholder="如 finance_officer" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input placeholder="角色说明" maxLength={200} />
          </Form.Item>
          <Form.Item name="data_scope" label="数据范围" rules={[{ required: true }]}>
            <Select options={SCOPE_OPTIONS} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
