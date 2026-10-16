import { useMemo, useState } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import {
  Button,
  Card,
  Descriptions,
  Divider,
  Input,
  Modal,
  Select,
  Space,
  Tag,
  Timeline,
  message,
} from "antd";
import { ArrowLeftOutlined } from "@ant-design/icons";
import { wfApi, usersApi } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import type { FormDefinitionOut, UserOut, WorkflowInstanceOut } from "../types";
import { INSTANCE_STATUS, LOG_ACTION, TASK_STATUS } from "../wfMeta";

export default function InstanceDetail() {
  const { id } = useParams();
  const instId = Number(id);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { user } = useAuth();
  const meId = user?.id;

  const instQ = useQuery({
    queryKey: ["wf-instance", instId],
    queryFn: () => wfApi.getInstance(instId),
  });
  const logsQ = useQuery({
    queryKey: ["wf-instance-logs", instId],
    queryFn: () => wfApi.instanceLogs(instId),
  });
  const usersQ = useQuery({ queryKey: ["users"], queryFn: () => usersApi.list() });
  const formsQ = useQuery({ queryKey: ["wf-forms"], queryFn: wfApi.forms });
  const versionQ = useQuery({
    queryKey: ["wf-versions-for-detail", instQ.data?.definition_id],
    enabled: !!instQ.data?.definition_id,
    queryFn: () => wfApi.listVersions(instQ.data!.definition_id),
  });

  const [transferOpen, setTransferOpen] = useState(false);
  const [addsignOpen, setAddsignOpen] = useState(false);
  const [transferTo, setTransferTo] = useState<number | undefined>();
  const [addsignUsers, setAddsignUsers] = useState<number[]>([]);
  const [comment, setComment] = useState("");

  const nameOf = (id: number | null) => {
    if (id == null) return "—";
    const u = usersQ.data?.find((x: UserOut) => x.id === id);
    return u ? u.full_name || u.username : `#${id}`;
  };

  const instance: WorkflowInstanceOut | undefined = instQ.data;
  const formId = useMemo(() => {
    if (!instance || !versionQ.data) return null;
    return versionQ.data.find((v) => v.id === instance.version_id)?.form_id ?? null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [instance, versionQ.data]);
  const form: FormDefinitionOut | undefined = formsQ.data?.find((f) => f.id === formId);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["wf-instance", instId] });
    qc.invalidateQueries({ queryKey: ["wf-instance-logs", instId] });
    qc.invalidateQueries({ queryKey: ["wf-pending"] });
    qc.invalidateQueries({ queryKey: ["wf-done"] });
    qc.invalidateQueries({ queryKey: ["wf-mine"] });
  };

  const decideM = useMutation({
    mutationFn: (p: { taskId: number; approve: boolean; comment?: string }) =>
      wfApi.decide(p.taskId, { approve: p.approve, comment: p.comment }),
    onSuccess: () => {
      message.success("已处理");
      setComment("");
      refresh();
    },
    onError: (e: any) => message.error(e?.message || "处理失败"),
  });
  const transferM = useMutation({
    mutationFn: (p: { taskId: number; to_user_id: number; comment?: string }) =>
      wfApi.transfer(p.taskId, { to_user_id: p.to_user_id, comment: p.comment }),
    onSuccess: () => {
      message.success("已转办");
      setTransferOpen(false);
      refresh();
    },
    onError: (e: any) => message.error(e?.message || "转办失败"),
  });
  const addsignM = useMutation({
    mutationFn: (p: { nodeId: string; user_ids: number[]; before?: boolean }) =>
      wfApi.addsign(instId, p.nodeId, { user_ids: p.user_ids, before: p.before ?? false }),
    onSuccess: () => {
      message.success("已加签");
      setAddsignOpen(false);
      refresh();
    },
    onError: (e: any) => message.error(e?.message || "加签失败"),
  });
  const withdrawM = useMutation({
    mutationFn: () => wfApi.withdraw(instId),
    onSuccess: () => {
      message.success("已撤回");
      refresh();
    },
    onError: (e: any) => message.error(e?.message || "撤回失败"),
  });
  const urgeM = useMutation({
    mutationFn: (c?: string) => wfApi.urge(instId, { comment: c }),
    onSuccess: () => message.success("已催办"),
    onError: (e: any) => message.error(e?.message || "催办失败"),
  });

  if (instQ.isLoading) return <div>加载中…</div>;
  if (!instance) return <div>流程不存在</div>;

  const st = INSTANCE_STATUS[instance.status] ?? { label: instance.status, color: "default" };
  const myPending = (instance.tasks || []).filter(
    (t) => t.approver_id === meId && t.status === "pending"
  );
  const isInitiator = instance.initiator_id === meId;

  const formRows = Object.entries(instance.form_data || {}).map(([k, v]) => {
    const f = form?.fields?.find((x) => x.key === k);
    return { key: k, label: f?.label || k, value: v };
  });

  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate("/workflows")}>
          返回流程中心
        </Button>
      </Space>

      <Card style={{ marginBottom: 16 }}>
        <Descriptions title={`${instance.title}（${instance.code}）`} column={3} size="small">
          <Descriptions.Item label="状态">
            <Tag color={st.color}>{st.label}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="发起人">{nameOf(instance.initiator_id)}</Descriptions.Item>
          <Descriptions.Item label="发起时间">{instance.created_at}</Descriptions.Item>
        </Descriptions>

        {formRows.length > 0 && (
          <>
            <Divider orientation="left" plain>
              表单内容
            </Divider>
            <Descriptions column={2} size="small">
              {formRows.map((r) => (
                <Descriptions.Item key={r.key} label={r.label}>
                  {String(r.value ?? "")}
                </Descriptions.Item>
              ))}
            </Descriptions>
          </>
        )}
      </Card>

      {/* 我的审批动作 */}
      {myPending.length > 0 && (
        <Card title="待我处理" style={{ marginBottom: 16 }} styles={{ body: { background: "#fffbe6" } }}>
          {myPending.map((t) => (
            <Card key={t.id} size="small" style={{ marginBottom: 8 }}>
              <div style={{ marginBottom: 8 }}>
                节点：<b>{t.node_name}</b> · 类型：{t.node_type}
              </div>
              <Space>
                <Input.TextArea
                  style={{ width: 320 }}
                  rows={1}
                  placeholder="审批意见（可选）"
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                />
                <Button
                  type="primary"
                  loading={decideM.isPending}
                  onClick={() => decideM.mutate({ taskId: t.id, approve: true, comment })}
                >
                  通过
                </Button>
                <Button
                  danger
                  loading={decideM.isPending}
                  onClick={() => decideM.mutate({ taskId: t.id, approve: false, comment })}
                >
                  驳回
                </Button>
                <Button onClick={() => setTransferOpen(true)}>转办</Button>
                <Button onClick={() => setAddsignOpen(true)}>加签</Button>
              </Space>
            </Card>
          ))}
        </Card>
      )}

      {/* 发起人操作 */}
      {isInitiator && instance.status === "running" && (
        <Space style={{ marginBottom: 16 }}>
          <Button onClick={() => urgeM.mutate()}>催办</Button>
          <Button danger onClick={() => withdrawM.mutate()}>
            撤回流程
          </Button>
        </Space>
      )}

      {/* 流转时间线 */}
      <Card title="流转记录">
        <Timeline
          items={(logsQ.data || [])
            .slice()
            .sort((a, b) => (a.created_at < b.created_at ? -1 : 1))
            .map((l) => ({
              color:
                l.action === "approve"
                  ? "green"
                  : l.action === "reject"
                    ? "red"
                    : l.action === "urge"
                      ? "orange"
                      : "blue",
              children: (
                <div>
                  <Space>
                    <Tag>{LOG_ACTION[l.action] || l.action}</Tag>
                    <span style={{ color: "#888" }}>{l.node_name}</span>
                  </Space>
                  <div style={{ fontSize: 12, color: "#555" }}>
                    {l.operator_id != null ? `操作人：${nameOf(l.operator_id)}` : "系统"} · {l.created_at}
                  </div>
                  {l.comment && <div style={{ fontSize: 13 }}>意见：{l.comment}</div>}
                </div>
              ),
            }))}
        />
      </Card>

      {/* 转办弹窗 */}
      <Modal
        title="转办"
        open={transferOpen}
        onCancel={() => setTransferOpen(false)}
        onOk={() => {
          if (!myPending[0]) return;
          if (!transferTo) return message.warning("请选择转办人");
          transferM.mutate({ taskId: myPending[0].id, to_user_id: transferTo, comment });
        }}
        okText="确认转办"
      >
        <div style={{ marginBottom: 8 }}>转给：</div>
        <Select
          style={{ width: "100%" }}
          showSearch
          placeholder="选择用户"
          value={transferTo}
          onChange={setTransferTo}
          options={(usersQ.data || []).map((u: UserOut) => ({
            value: u.id,
            label: u.full_name || u.username,
          }))}
        />
      </Modal>

      {/* 加签弹窗 */}
      <Modal
        title="加签"
        open={addsignOpen}
        onCancel={() => setAddsignOpen(false)}
        onOk={() => {
          if (!addsignUsers.length) return message.warning("请选择加签人");
          addsignM.mutate({ nodeId: myPending[0]?.node_id || "", user_ids: addsignUsers });
        }}
        okText="确认加签"
      >
        <div style={{ marginBottom: 8 }}>加签人（可多选）：</div>
        <Select
          mode="multiple"
          style={{ width: "100%" }}
          placeholder="选择用户"
          value={addsignUsers}
          onChange={setAddsignUsers}
          options={(usersQ.data || []).map((u: UserOut) => ({
            value: u.id,
            label: u.full_name || u.username,
          }))}
        />
        <div style={{ fontSize: 12, color: "#999", marginTop: 8 }}>
          加签将在当前节点追加审批人，参与会签结论。
        </div>
      </Modal>
    </div>
  );
}
