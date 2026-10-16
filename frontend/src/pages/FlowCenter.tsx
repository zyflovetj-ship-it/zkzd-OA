import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  Button,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  message,
  type TableProps,
} from "antd";
import { wfApi, usersApi } from "../api/endpoints";
import type {
  FormDefinitionOut,
  UserOut,
  WorkflowDefinitionOut,
  WorkflowInstanceOut,
  WorkflowTaskOut,
} from "../types";
import { INSTANCE_STATUS, TASK_STATUS } from "../wfMeta";

const instStatus = (s: string) => INSTANCE_STATUS[s] ?? { label: s, color: "default" };
const taskStatus = (s: string) => TASK_STATUS[s] ?? { label: s, color: "default" };

export default function FlowCenter() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [startOpen, setStartOpen] = useState(false);

  const pendingQ = useQuery({ queryKey: ["wf-pending"], queryFn: wfApi.pending });
  const doneQ = useQuery({ queryKey: ["wf-done"], queryFn: wfApi.done });
  const notifiedQ = useQuery({ queryKey: ["wf-notified"], queryFn: wfApi.notified });
  const mineQ = useQuery({ queryKey: ["wf-mine"], queryFn: wfApi.mine });
  const defsQ = useQuery({
    queryKey: ["wf-defs-published"],
    queryFn: () => wfApi.definitions("published"),
  });
  const usersQ = useQuery({ queryKey: ["users"], queryFn: () => usersApi.list() });

  const nameOf = (id: number | null) => {
    if (id == null) return "—";
    const u = usersQ.data?.find((x: UserOut) => x.id === id);
    return u ? u.full_name || u.username : `#${id}`;
  };

  const refreshAll = () => {
    qc.invalidateQueries({ queryKey: ["wf-pending"] });
    qc.invalidateQueries({ queryKey: ["wf-done"] });
    qc.invalidateQueries({ queryKey: ["wf-notified"] });
    qc.invalidateQueries({ queryKey: ["wf-mine"] });
  };

  const withdrawM = useMutation({
    mutationFn: (id: number) => wfApi.withdraw(id),
    onSuccess: () => {
      refreshAll();
      message.success("已撤回流程");
    },
    onError: (e: any) => message.error(e?.message || "撤回失败"),
  });
  const urgeM = useMutation({
    mutationFn: (id: number) => wfApi.urge(id),
    onSuccess: () => message.success("已催办当前审批人"),
    onError: (e: any) => message.error(e?.message || "催办失败"),
  });

  // ---------- 待办 ----------
  const pendingCols: TableProps<WorkflowTaskOut>["columns"] = [
    { title: "流程单号", dataIndex: "instance_id", render: (v) => `实例#${v}` },
    { title: "节点", dataIndex: "node_name" },
    {
      title: "状态",
      dataIndex: "status",
      render: (v: string) => <Tag color={taskStatus(v).color}>{taskStatus(v).label}</Tag>,
    },
    { title: "当前处理人", dataIndex: "approver_id", render: (v) => nameOf(v) },
    {
      title: "操作",
      render: (_, r) => (
        <Button size="small" type="primary" onClick={() => navigate(`/workflows/instance/${r.instance_id}`)}>
          去审批
        </Button>
      ),
    },
  ];

  // ---------- 我发起 ----------
  const mineCols: TableProps<WorkflowInstanceOut>["columns"] = [
    { title: "单号", dataIndex: "code" },
    { title: "标题", dataIndex: "title" },
    {
      title: "状态",
      dataIndex: "status",
      render: (v: string) => <Tag color={instStatus(v).color}>{instStatus(v).label}</Tag>,
    },
    {
      title: "操作",
      render: (_, r: WorkflowInstanceOut) => (
        <Space>
          <Button size="small" onClick={() => navigate(`/workflows/instance/${r.id}`)}>
            查看
          </Button>
          {r.status === "running" && (
            <>
              <Button size="small" onClick={() => urgeM.mutate(r.id)}>
                催办
              </Button>
              <Button size="small" danger onClick={() => withdrawM.mutate(r.id)}>
                撤回
              </Button>
            </>
          )}
        </Space>
      ),
    },
  ];

  const taskCols = (withView: boolean): TableProps<WorkflowTaskOut>["columns"] => [
    { title: "流程单号", dataIndex: "instance_id", render: (v) => `实例#${v}` },
    { title: "节点", dataIndex: "node_name" },
    {
      title: "状态",
      dataIndex: "status",
      render: (v: string) => <Tag color={taskStatus(v).color}>{taskStatus(v).label}</Tag>,
    },
    { title: "处理人", dataIndex: "approver_id", render: (v) => nameOf(v) },
    ...(withView
      ? [
          {
            title: "操作",
            render: (_: any, r: WorkflowTaskOut) => (
              <Button size="small" onClick={() => navigate(`/workflows/instance/${r.instance_id}`)}>
                查看
              </Button>
            ),
          },
        ]
      : []),
  ];

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
        <h2>流程中心</h2>
        <Button type="primary" onClick={() => setStartOpen(true)}>
          发起新流程
        </Button>
      </div>

      <Tabs
        items={[
          {
            key: "pending",
            label: `待办 (${pendingQ.data?.length || 0})`,
            children: (
              <Table
                rowKey="id"
                loading={pendingQ.isLoading}
                dataSource={pendingQ.data || []}
                columns={pendingCols}
                pagination={false}
              />
            ),
          },
          {
            key: "done",
            label: `已办 (${doneQ.data?.length || 0})`,
            children: (
              <Table
                rowKey="id"
                loading={doneQ.isLoading}
                dataSource={doneQ.data || []}
                columns={taskCols(true)}
                pagination={false}
              />
            ),
          },
          {
            key: "notified",
            label: `抄送我 (${notifiedQ.data?.length || 0})`,
            children: (
              <Table
                rowKey="id"
                loading={notifiedQ.isLoading}
                dataSource={notifiedQ.data || []}
                columns={taskCols(false)}
                pagination={false}
              />
            ),
          },
          {
            key: "mine",
            label: `我发起 (${mineQ.data?.length || 0})`,
            children: (
              <Table
                rowKey="id"
                loading={mineQ.isLoading}
                dataSource={mineQ.data || []}
                columns={mineCols}
                pagination={false}
              />
            ),
          },
        ]}
      />

      {startOpen && (
        <StartModal
          defs={defsQ.data || []}
          users={usersQ.data || []}
          onClose={() => setStartOpen(false)}
          onDone={() => {
            setStartOpen(false);
            refreshAll();
          }}
        />
      )}
    </div>
  );
}

// ---------- 发起新流程（动态表单） ----------
function StartModal({
  defs,
  users,
  onClose,
  onDone,
}: {
  defs: WorkflowDefinitionOut[];
  users: UserOut[];
  onClose: () => void;
  onDone: () => void;
}) {
  const [defId, setDefId] = useState<number | null>(null);
  const [form] = Form.useForm();
  const [formFields, setFormFields] = useState<any[]>([]);

  const versionsQ = useQuery({
    queryKey: ["wf-versions-for-start", defId],
    enabled: !!defId,
    queryFn: () => wfApi.listVersions(defId as number),
  });
  const formsQ = useQuery({ queryKey: ["wf-forms"], queryFn: wfApi.forms });

  const startM = useMutation({
    mutationFn: (v: { definition_id: number; title: string; form_data: Record<string, any> }) =>
      wfApi.start(v),
    onSuccess: () => {
      message.success("已发起审批");
      onDone();
    },
    onError: (e: any) => message.error(e?.message || "发起失败"),
  });

  // 选中流程后，定位其已发布版本的关联表单字段
  useEffect(() => {
    if (!defId) {
      setFormFields([]);
      return;
    }
    const pub = versionsQ.data?.find((v) => v.status === "published");
    const formId = pub?.form_id;
    const fd = formsQ.data?.find((f: FormDefinitionOut) => f.id === formId);
    setFormFields(fd?.fields || []);
  }, [defId, versionsQ.data, formsQ.data]);

  return (
    <Modal
      title="发起新流程"
      open
      onCancel={onClose}
      width={640}
      onOk={() => form.submit()}
      okText="提交"
      confirmLoading={startM.isPending}
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={(v) => {
          const data: Record<string, any> = {};
          formFields.forEach((f) => {
            if (v[f.key] !== undefined && v[f.key] !== "") data[f.key] = v[f.key];
          });
          startM.mutate({ definition_id: defId as number, title: v.title, form_data: data });
        }}
      >
        <Form.Item name="definition_id" label="选择流程" rules={[{ required: true }]}>
          <Select
            placeholder="请选择已发布流程"
            value={defId ?? undefined}
            onChange={(val) => {
              setDefId(val);
              form.resetFields(formFields.map((f) => f.key));
            }}
            options={defs.map((d) => ({ value: d.id, label: `${d.name}（${d.code}）` }))}
          />
        </Form.Item>
        <Form.Item name="title" label="标题" rules={[{ required: true }]}>
          <Input placeholder="如：差旅报销-张三-2026-09" />
        </Form.Item>

        {versionsQ.isLoading && <div>加载表单中…</div>}
        {formFields.length === 0 && defId && !versionsQ.isLoading && (
          <div style={{ color: "#999" }}>该流程未绑定表单，可直接提交。</div>
        )}
        {formFields.map((f) => (
          <Form.Item
            key={f.key}
            name={f.key}
            label={f.label}
            rules={f.required ? [{ required: true, message: `请填写${f.label}` }] : []}
          >
            {f.type === "number" ? (
              <Input type="number" />
            ) : f.type === "date" ? (
              <Input type="date" />
            ) : f.type === "select" ? (
              <Select
                options={(f.options || []).map((o: string) => ({ value: o, label: o }))}
                allowClear
              />
            ) : f.type === "textarea" ? (
              <Input.TextArea rows={3} />
            ) : (
              <Input />
            )}
          </Form.Item>
        ))}
      </Form>
    </Modal>
  );
}
