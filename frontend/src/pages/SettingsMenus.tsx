import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Table,
  message,
} from "antd";
import { EditOutlined, PlusOutlined } from "@ant-design/icons";
import { menuApi } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import type { MenuOut } from "../types";

export default function SettingsMenus() {
  const qc = useQueryClient();
  const { hasPerm } = useAuth();
  const canManage = hasPerm("org:menu:manage");

  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState<MenuOut | null>(null);
  const [form] = Form.useForm();

  const menusQ = useQuery({ queryKey: ["menus"], queryFn: menuApi.list });

  // 按 parent_id 规整成带层级的扁平列表
  const rows = useMemo(() => {
    const byParent = new Map<number | null, MenuOut[]>();
    for (const m of menusQ.data || []) {
      const key = m.parent_id ?? null;
      if (!byParent.has(key)) byParent.set(key, []);
      byParent.get(key)!.push(m);
    }
    const out: Array<MenuOut & { level: number }> = [];
    const walk = (pid: number | null, level: number) => {
      for (const m of (byParent.get(pid) || []).sort((a, b) => a.order - b.order)) {
        out.push({ ...m, level });
        walk(m.id, level + 1);
      }
    };
    walk(null, 0);
    return out;
  }, [menusQ.data]);

  const invalidate = () => qc.invalidateQueries({ queryKey: ["menus"] });

  const saveM = useMutation({
    mutationFn: (v: any) => {
      if (target) return menuApi.update(target.id, v);
      return menuApi.create(v);
    },
    onSuccess: () => {
      invalidate();
      setOpen(false);
      form.resetFields();
      message.success("已保存菜单");
    },
    onError: (e: any) => message.error(e?.message || "保存失败"),
  });

  const openCreate = () => {
    setTarget(null);
    form.resetFields();
    form.setFieldsValue({ order: rows.length + 1 });
    setOpen(true);
  };
  const openEdit = (m: MenuOut) => {
    setTarget(m);
    form.setFieldsValue({
      name: m.name,
      parent_id: m.parent_id,
      path: m.path,
      icon: m.icon,
      order: m.order,
      permission_code: m.permission_code,
    });
    setOpen(true);
  };

  const columns = [
    {
      title: "菜单名称",
      dataIndex: "name",
      render: (v: string, row: MenuOut & { level: number }) => (
        <span style={{ paddingLeft: row.level * 20 }}>{v}</span>
      ),
    },
    { title: "路径", dataIndex: "path", render: (v: string) => v || <span style={{ color: "#999" }}>分组</span> },
    { title: "权限码", dataIndex: "permission_code", render: (v: string) => v || "-" },
    { title: "排序", dataIndex: "order", width: 70 },
    {
      title: "操作",
      width: 90,
      render: (_: any, row: MenuOut) =>
        canManage ? (
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>
            编辑
          </Button>
        ) : null,
    },
  ];

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
        <h2>菜单管理</h2>
        {canManage && (
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建菜单
          </Button>
        )}
      </div>

      {!canManage && (
        <Alert style={{ marginBottom: 12 }} type="info" showIcon message="当前账号仅可查看菜单配置" />
      )}

      <Table
        rowKey="id"
        loading={menusQ.isLoading}
        dataSource={rows}
        columns={columns}
        pagination={false}
      />

      <Modal
        title={target ? `编辑菜单 · ${target.name}` : "新建菜单"}
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => form.submit()}
        okText="保存"
      >
        <Form form={form} layout="vertical" onFinish={(v) => saveM.mutate(v)}>
          <Form.Item name="name" label="菜单名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="parent_id" label="上级菜单">
            <Select
              allowClear
              placeholder="顶级菜单"
              options={menusQ.data?.map((m) => ({ value: m.id, label: m.name }))}
            />
          </Form.Item>
          <Form.Item name="path" label="路由路径" extra="分组节点留空；页面节点填写前端路由，如 /employees">
            <Input placeholder="/path" />
          </Form.Item>
          <Form.Item name="permission_code" label="权限码" extra="留空表示所有登录用户可见">
            <Input placeholder="如 user:view" />
          </Form.Item>
          <Form.Item name="icon" label="图标名" extra="对应前端图标注册表，如 TeamOutlined">
            <Input />
          </Form.Item>
          <Form.Item name="order" label="排序" rules={[{ required: true }]}>
            <InputNumber min={0} style={{ width: "100%" }} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
