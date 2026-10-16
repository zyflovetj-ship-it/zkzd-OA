import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  DatePicker,
  Form,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  message,
  type TableColumnsType,
} from "antd";
import { PlusOutlined } from "@ant-design/icons";
import dayjs, { type Dayjs } from "dayjs";
import {
  delegationsApi,
  type Delegation,
  type DelegationCreate,
} from "../api/delegations";
import { usersApi, wfApi } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";

// 表单值：时间用 Dayjs，提交前再格式化为 "YYYY-MM-DDTHH:mm:ss"
interface DelegationFormValues {
  to_user_id: number;
  start_at: Dayjs;
  end_at: Dayjs;
  definition_id?: number;
  active: boolean;
}

const fmtMinute = (s: string) => dayjs(s).format("YYYY-MM-DD HH:mm");

// 状态：不在时段内 → 灰色「未到时段 / 已过期」；否则 active ? 生效中 : 已停用
function statusOf(d: Delegation): { color?: string; text: string } {
  const now = Date.now();
  const start = new Date(d.start_at).getTime();
  const end = new Date(d.end_at).getTime();
  if (!Number.isNaN(start) && now < start) return { color: "default", text: "未到时段" };
  if (!Number.isNaN(end) && now > end) return { color: "default", text: "已过期" };
  return d.active ? { color: "green", text: "生效中" } : { text: "已停用" };
}

export default function Delegations() {
  const qc = useQueryClient();
  const { user, hasPerm } = useAuth();
  const isAdmin = user?.role_name === "admin";

  const [all, setAll] = useState(false); // 管理员「查看全部」
  const [modalOpen, setModalOpen] = useState(false);
  const [target, setTarget] = useState<Delegation | null>(null); // null=新建
  const [form] = Form.useForm<DelegationFormValues>();
  const startAt = Form.useWatch("start_at", form) as Dayjs | undefined;

  const listQ = useQuery({
    queryKey: ["delegations", all],
    queryFn: () => delegationsApi.list(all),
  });

  // 受托人下拉：仅启用用户，且过滤掉委托人自己
  const usersQ = useQuery({
    queryKey: ["users", "delegation-options"],
    queryFn: () => usersApi.list(),
  });

  // 流程下拉：仅已发布流程（编辑时把当前值也带上，避免下拉展示成裸 id）
  const defsQ = useQuery({
    queryKey: ["workflow-definitions"],
    queryFn: () => wfApi.definitions(),
  });

  const ownerUserId = target?.from_user_id ?? user?.id;
  const candidateUsers = (usersQ.data ?? []).filter(
    (u) => u.id !== ownerUserId && (u.is_active || u.id === target?.to_user_id)
  );
  const definitionOptions = (defsQ.data ?? [])
    .filter((d) => d.status === "published" || d.id === target?.definition_id)
    .map((d) => ({ value: d.id, label: d.name }));

  const invalidate = () => qc.invalidateQueries({ queryKey: ["delegations"] });

  const close = () => {
    setModalOpen(false);
    setTarget(null);
    form.resetFields();
  };

  const saveM = useMutation({
    mutationFn: (v: { id: number | null; body: DelegationCreate }) =>
      v.id === null ? delegationsApi.create(v.body) : delegationsApi.update(v.id, v.body),
    onSuccess: (_data, v) => {
      invalidate();
      close();
      message.success(v.id === null ? "已创建委托" : "已保存修改");
    },
    onError: (e) => message.error(e?.message || "保存失败"),
  });

  const toggleM = useMutation({
    mutationFn: (v: { id: number; active: boolean }) =>
      delegationsApi.update(v.id, { active: v.active }),
    onSuccess: () => {
      invalidate();
      message.success("已更新委托状态");
    },
    onError: (e) => message.error(e?.message || "状态更新失败"),
  });

  const deleteM = useMutation({
    mutationFn: (id: number) => delegationsApi.remove(id),
    onSuccess: () => {
      invalidate();
      message.success("已删除委托");
    },
    onError: (e) => message.error(e?.message || "删除失败"),
  });

  const openCreate = () => {
    setTarget(null);
    form.resetFields();
    form.setFieldsValue({ active: true });
    setModalOpen(true);
  };

  const openEdit = (row: Delegation) => {
    setTarget(row);
    form.resetFields();
    form.setFieldsValue({
      to_user_id: row.to_user_id,
      start_at: dayjs(row.start_at),
      end_at: dayjs(row.end_at),
      definition_id: row.definition_id ?? undefined,
      active: row.active,
    });
    setModalOpen(true);
  };

  const onFinish = (v: DelegationFormValues) => {
    const { start_at, end_at } = v;
    if (!start_at || !end_at || !end_at.isAfter(start_at)) {
      message.warning("结束时间必须晚于开始时间");
      return;
    }
    const body: DelegationCreate = {
      to_user_id: v.to_user_id,
      start_at: start_at.format("YYYY-MM-DDTHH:mm:ss"),
      end_at: end_at.format("YYYY-MM-DDTHH:mm:ss"),
      definition_id: v.definition_id ?? null,
      active: v.active,
    };
    saveM.mutate({ id: target?.id ?? null, body });
  };

  const columns: TableColumnsType<Delegation> = [
    { title: "委托人", dataIndex: "from_user_name", width: 120 },
    { title: "受托人", dataIndex: "to_user_name", width: 140 },
    {
      title: "流程",
      dataIndex: "definition_name",
      render: (v: string) => v || "全部流程",
    },
    {
      title: "委托时段",
      key: "period",
      render: (_v, r) => `${fmtMinute(r.start_at)} ~ ${fmtMinute(r.end_at)}`,
    },
    {
      title: "状态",
      key: "status",
      render: (_v, r) => {
        const s = statusOf(r);
        return <Tag color={s.color}>{s.text}</Tag>;
      },
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      render: (v: string) => fmtMinute(v),
    },
    {
      title: "操作",
      key: "action",
      render: (_v, r) => (
        <Space>
          <Button size="small" onClick={() => openEdit(r)}>
            编辑
          </Button>
          <Switch
            size="small"
            checked={r.active}
            checkedChildren="启用"
            unCheckedChildren="停用"
            loading={toggleM.isPending && toggleM.variables?.id === r.id}
            onChange={(checked) => toggleM.mutate({ id: r.id, active: checked })}
          />
          <Popconfirm
            title="确定删除该委托？"
            okText="删除"
            cancelText="取消"
            onConfirm={() => deleteM.mutate(r.id)}
          >
            <Button
              size="small"
              danger
              loading={deleteM.isPending && deleteM.variables === r.id}
            >
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="委托生效后，时段内你名下的审批任务会自动派给受托人；受托人无需额外操作。"
        description="不选择流程即对全部流程生效；不在委托时段内的审批仍由你自己处理。"
      />

      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
        <h2>审批委托</h2>
        <Space>
          {isAdmin && (
            <Space size={8}>
              <span style={{ color: "#666" }}>查看全部</span>
              <Switch
                checked={all}
                checkedChildren="全部"
                unCheckedChildren="我的"
                onChange={setAll}
              />
            </Space>
          )}
          {hasPerm("wf:view") && (
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              新建委托
            </Button>
          )}
        </Space>
      </div>

      <Table
        rowKey="id"
        loading={listQ.isLoading}
        dataSource={listQ.data ?? []}
        columns={columns}
        locale={{ emptyText: "暂无委托记录" }}
      />

      <Modal
        title={target ? `编辑委托 · ${target.from_user_name}` : "新建委托"}
        open={modalOpen}
        onCancel={close}
        onOk={() => form.submit()}
        okText={target ? "保存" : "创建"}
        confirmLoading={saveM.isPending}
      >
        <Form form={form} layout="vertical" onFinish={onFinish}>
          <Form.Item
            name="to_user_id"
            label="受托人"
            rules={[{ required: true, message: "请选择受托人" }]}
          >
            <Select
              placeholder="选择受托人"
              showSearch
              optionFilterProp="label"
              loading={usersQ.isLoading}
              options={candidateUsers.map((u) => ({
                value: u.id,
                label: u.full_name ? `${u.full_name}(${u.username})` : u.username,
              }))}
            />
          </Form.Item>

          <Form.Item
            name="start_at"
            label="开始时间"
            rules={[{ required: true, message: "请选择开始时间" }]}
          >
            <DatePicker showTime style={{ width: "100%" }} placeholder="选择开始时间" />
          </Form.Item>

          <Form.Item
            name="end_at"
            label="结束时间"
            dependencies={["start_at"]}
            rules={[
              { required: true, message: "请选择结束时间" },
              {
                validator: (_rule, value?: Dayjs) => {
                  if (!value || !startAt || value.isAfter(startAt)) {
                    return Promise.resolve();
                  }
                  return Promise.reject(new Error("结束时间必须晚于开始时间"));
                },
              },
            ]}
          >
            <DatePicker showTime style={{ width: "100%" }} placeholder="选择结束时间" />
          </Form.Item>

          <Form.Item name="definition_id" label="适用流程">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="不选 = 全部流程"
              loading={defsQ.isLoading}
              options={definitionOptions}
            />
          </Form.Item>

          <Form.Item
            name="active"
            label="启用"
            valuePropName="checked"
            style={{ marginBottom: 0 }}
          >
            <Switch checkedChildren="启用" unCheckedChildren="停用" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
