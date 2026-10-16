import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  addEdge,
  useNodesState,
  useEdgesState,
  useReactFlow,
  type Node,
  type Edge,
  type Connection,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  Button,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Switch,
  Tag,
  Tooltip,
  message,
} from "antd";
import {
  ApartmentOutlined,
  BellOutlined,
  BranchesOutlined,
  CheckSquareOutlined,
  PlayCircleOutlined,
  StopOutlined,
  UsergroupAddOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { wfApi, usersApi } from "../api/endpoints";
import type {
  AssigneeSpec,
  ConditionGroup,
  ConditionOp,
  WFGraph,
  WFGraphEdge,
  WFGraphNode,
  WFNodeType,
  WorkflowDefinitionOut,
  WorkflowVersionOut,
} from "../types";
import { NODE_META, assigneeLabel } from "../wfMeta";

// ---------- 类型与图转换 ----------
type WFNodeData = {
  nodeType: WFNodeType;
  name: string;
  assignee?: AssigneeSpec;
  assignees?: AssigneeSpec[];
  strategy?: "all" | "any" | "ratio";
  ratio?: number | null;
  parallel?: boolean;
};
type WFNode = Node<WFNodeData, "wf">;

const NODE_ICON: Record<WFNodeType, React.ReactNode> = {
  start: <PlayCircleOutlined />,
  approval: <CheckSquareOutlined />,
  countersign: <UsergroupAddOutlined />,
  condition: <BranchesOutlined />,
  join: <ApartmentOutlined />,
  notify: <BellOutlined />,
  end: <StopOutlined />,
};

function defaultData(t: WFNodeType): Partial<WFNodeData> {
  switch (t) {
    case "approval":
      return { assignee: { type: "role", value: "manager" } };
    case "countersign":
      return {
        assignees: [{ type: "role", value: "manager" }],
        strategy: "all",
        ratio: null,
      };
    case "notify":
      return { assignees: [{ type: "role", value: "manager" }] };
    case "condition":
      return { parallel: false };
    default:
      return {};
  }
}

function conditionText(c?: ConditionGroup | null): string {
  if (!c || !c.rules?.length) return "默认分支";
  return c.rules
    .map((r) => `${r.field} ${r.op} ${Array.isArray(r.value) ? r.value.join("/") : r.value}`)
    .join(c.op === "and" ? " 且 " : " 或 ");
}

function graphToFlow(graph: WFGraph): { nodes: WFNode[]; edges: Edge[] } {
  const layout = layoutGraph(graph);
  const nodes: WFNode[] = (graph.nodes || []).map((n) => ({
    id: n.id,
    type: "wf",
    position: { x: n.x ?? layout[n.id]?.x ?? 0, y: n.y ?? layout[n.id]?.y ?? 0 },
    data: {
      nodeType: n.type,
      name: n.name || NODE_META[n.type].label,
      assignee: n.assignee,
      assignees: n.assignees,
      strategy: n.strategy,
      ratio: n.ratio,
      parallel: n.parallel,
    },
  }));
  const edges: Edge[] = (graph.edges || []).map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    data: { condition: e.condition ?? null },
    label: conditionText(e.condition),
    animated: !!e.condition,
  }));
  return { nodes, edges };
}

function flowToGraph(nodes: WFNode[], edges: Edge[]): WFGraph {
  return {
    nodes: nodes.map((n) => {
      const d = n.data;
      const base: WFGraphNode = { id: n.id, type: d.nodeType, name: d.name };
      if (d.nodeType === "approval") base.assignee = d.assignee;
      if (d.nodeType === "countersign") {
        base.assignees = d.assignees;
        base.strategy = d.strategy;
        base.ratio = d.ratio;
      }
      if (d.nodeType === "notify") base.assignees = d.assignees;
      if (d.nodeType === "condition") base.parallel = d.parallel;
      base.x = Math.round(n.position.x);
      base.y = Math.round(n.position.y);
      return base;
    }),
    edges: edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      condition: (e.data as any)?.condition ?? null,
    })),
  };
}

// 简易分层布局：未存坐标时给个能看的排布
function layoutGraph(graph: WFGraph): Record<string, { x: number; y: number }> {
  const pos: Record<string, { x: number; y: number }> = {};
  const nodes = graph.nodes || [];
  const out: Record<string, WFGraphEdge[]> = {};
  (graph.edges || []).forEach((e) => (out[e.source] ||= []).push(e));
  const layer: Record<string, number> = {};
  const start = nodes.find((n) => n.type === "start") || nodes[0];
  if (start) {
    const queue = [start.id];
    layer[start.id] = 0;
    while (queue.length) {
      const id = queue.shift()!;
      const depth = layer[id];
      (out[id] || []).forEach((e) => {
        if (layer[e.target] === undefined) {
          layer[e.target] = depth + 1;
          queue.push(e.target);
        }
      });
    }
  }
  const maxLayer = Object.values(layer).length ? Math.max(...Object.values(layer)) : 0;
  nodes.forEach((n) => {
    if (layer[n.id] === undefined) layer[n.id] = maxLayer + 1;
  });
  const col: Record<number, number> = {};
  nodes.forEach((n) => {
    const l = layer[n.id];
    const idx = col[l] || 0;
    col[l] = idx + 1;
    pos[n.id] = { x: 80 + l * 260, y: 80 + idx * 140 };
  });
  return pos;
}

// ---------- 自定义节点 ----------
function WFNodeComp({ data, selected }: NodeProps<WFNode>) {
  const meta = NODE_META[data.nodeType];
  const hasTarget = data.nodeType !== "start";
  const hasSource = data.nodeType !== "end";
  const sub =
    data.nodeType === "approval"
      ? assigneeLabel(data.assignee)
      : data.nodeType === "countersign" || data.nodeType === "notify"
        ? (data.assignees || []).map(assigneeLabel).join("、") || "（无）"
        : data.nodeType === "condition"
          ? data.parallel
            ? "并行分支（全部命中）"
            : "互斥分支（首个命中）"
          : "";
  return (
    <div
      style={{
        minWidth: 160,
        background: "#fff",
        border: `2px solid ${selected ? meta.color : "#e0e0e0"}`,
        borderRadius: 8,
        boxShadow: "0 2px 6px rgba(0,0,0,0.08)",
        overflow: "hidden",
      }}
    >
      {hasTarget && <Handle type="target" position={Position.Top} style={{ background: "#888" }} />}
      <div
        style={{
          background: meta.color,
          color: "#fff",
          padding: "4px 8px",
          fontSize: 12,
          display: "flex",
          alignItems: "center",
          gap: 4,
        }}
      >
        {NODE_ICON[data.nodeType]} {meta.label}
      </div>
      <div style={{ padding: "8px 10px", fontWeight: 600 }}>{data.name}</div>
      {sub && <div style={{ padding: "0 10px 8px", fontSize: 12, color: "#888" }}>{sub}</div>}
      {hasSource && <Handle type="source" position={Position.Bottom} style={{ background: "#888" }} />}
    </div>
  );
}

const nodeTypes = { wf: WFNodeComp };
const PALETTE: WFNodeType[] = [
  "start",
  "approval",
  "countersign",
  "condition",
  "join",
  "notify",
  "end",
];

// ---------- 审批人编辑器 ----------
function SpecEditor({
  value,
  onChange,
  roles,
  users,
}: {
  value: AssigneeSpec;
  onChange: (s: AssigneeSpec) => void;
  roles: { id: number; name: string }[];
  users: { id: number; full_name: string; username: string }[];
}) {
  return (
    <Space style={{ display: "flex", marginBottom: 8 }} align="start">
      <Select
        style={{ width: 120 }}
        value={value.type}
        onChange={(t) => onChange({ type: t, value: t === "user" ? value.value : undefined })}
        options={[
          { value: "role", label: "角色" },
          { value: "user", label: "指定用户" },
          { value: "dept_manager", label: "部门主管" },
          { value: "initiator", label: "发起人" },
        ]}
      />
      {value.type === "role" && (
        <Select
          style={{ width: 140 }}
          value={value.value as string}
          onChange={(v) => onChange({ type: "role", value: v })}
          options={roles.map((r) => ({ value: r.name, label: r.name }))}
        />
      )}
      {value.type === "user" && (
        <Select
          style={{ width: 160 }}
          showSearch
          value={value.value as number}
          onChange={(v) => onChange({ type: "user", value: v })}
          options={users.map((u) => ({
            value: u.id,
            label: u.full_name || u.username,
          }))}
        />
      )}
    </Space>
  );
}

// ---------- 设计器主体 ----------
export default function ProcessDesigner() {
  return (
    <ReactFlowProvider>
      <DesignerInner />
    </ReactFlowProvider>
  );
}

function DesignerInner() {
  const qc = useQueryClient();
  const rf = useReactFlow();
  const [nodes, setNodes, onNodesChange] = useNodesState<WFNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selNode, setSelNode] = useState<WFNode | null>(null);
  const [selEdge, setSelEdge] = useState<Edge | null>(null);
  const [defId, setDefId] = useState<number | null>(null);
  const [curVersionId, setCurVersionId] = useState<number | null>(null);
  const [linkFormId, setLinkFormId] = useState<number | null>(null);
  const [newDefOpen, setNewDefOpen] = useState(false);
  const [defForm] = Form.useForm();

  const defsQ = useQuery({ queryKey: ["wf-defs-all"], queryFn: () => wfApi.definitions() });
  const formsQ = useQuery({ queryKey: ["wf-forms"], queryFn: wfApi.forms });
  const rolesQ = useQuery({ queryKey: ["roles"], queryFn: () => usersApi.roles() });
  const usersQ = useQuery({ queryKey: ["users"], queryFn: () => usersApi.list() });
  const versionsQ = useQuery({
    queryKey: ["wf-versions", defId],
    enabled: !!defId,
    queryFn: () => wfApi.listVersions(defId as number),
  });

  // 选中定义后载入最新版本
  useEffect(() => {
    if (!versionsQ.data?.length) {
      setNodes([]);
      setEdges([]);
      setCurVersionId(null);
      setLinkFormId(null);
      return;
    }
    const latest = [...versionsQ.data].sort((a, b) => b.version - a.version)[0];
    const g = graphToFlow((latest.graph as WFGraph) || { nodes: [], edges: [] });
    setNodes(g.nodes);
    setEdges(g.edges);
    setCurVersionId(latest.id);
    setLinkFormId(latest.form_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [versionsQ.data]);

  const roles = rolesQ.data || [];
  const users = usersQ.data || [];

  const onConnect = useCallback(
    (c: Connection) =>
      setEdges((eds) =>
        addEdge({ ...c, data: { condition: null }, label: "默认分支", type: "smoothstep" }, eds)
      ),
    [setEdges]
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const t = e.dataTransfer.getData("application/wf-node") as WFNodeType;
      if (!t) return;
      const position = rf.screenToFlowPosition({ x: e.clientX, y: e.clientY });
      const id = `${t}_${Date.now().toString(36)}`;
      const newNode: WFNode = {
        id,
        type: "wf",
        position,
        data: { nodeType: t, name: NODE_META[t].label, ...defaultData(t) },
      };
      setNodes((nds) => [...nds, newNode]);
    },
    [rf, setNodes]
  );

  const updateNodeData = (id: string, patch: Partial<WFNodeData>) =>
    setNodes((nds) =>
      nds.map((n) => (n.id === id ? { ...n, data: { ...n.data, ...patch } } : n))
    );

  const deleteNode = (id: string) => {
    setNodes((nds) => nds.filter((n) => n.id !== id));
    setEdges((eds) => eds.filter((e) => e.source !== id && e.target !== id));
    setSelNode(null);
  };

  const updateEdge = (id: string, condition: ConditionGroup | null) =>
    setEdges((eds) =>
      eds.map((e) =>
        e.id === id ? { ...e, data: { condition }, label: conditionText(condition) } : e
      )
    );

  const saveM = useMutation({
    mutationFn: () =>
      wfApi.saveVersion(defId as number, {
        graph: flowToGraph(nodes, edges),
        form_id: linkFormId,
        remark: "可视化设计器保存",
      }),
    onSuccess: (ver: WorkflowVersionOut) => {
      setCurVersionId(ver.id);
      message.success(`草稿已保存（v${ver.version}）`);
      qc.invalidateQueries({ queryKey: ["wf-versions", defId] });
    },
    onError: (e: any) => message.error(e?.message || "保存失败"),
  });

  const publishM = useMutation({
    mutationFn: async () => {
      if (!curVersionId) throw new Error("请先保存草稿");
      return wfApi.publishVersion(curVersionId);
    },
    onSuccess: () => {
      message.success("流程已发布，可发起");
      qc.invalidateQueries({ queryKey: ["wf-defs-published"] });
    },
    onError: (e: any) => message.error(e?.message || "发布失败"),
  });

  const createDefM = useMutation({
    mutationFn: (v: any) => wfApi.createDef(v),
    onSuccess: (d: WorkflowDefinitionOut) => {
      setNewDefOpen(false);
      defForm.resetFields();
      qc.invalidateQueries({ queryKey: ["wf-defs-all"] });
      setDefId(d.id);
      message.success("已创建流程，开始绘制流程图");
    },
    onError: (e: any) => message.error(e?.message || "创建失败"),
  });

  const hasStart = nodes.some((n) => n.data.nodeType === "start");
  const hasEnd = nodes.some((n) => n.data.nodeType === "end");

  const defOptions = (defsQ.data || []).map((d) => ({
    value: d.id,
    label: `${d.name}（${d.code}·${d.status}）`,
  }));

  return (
    <div>
      <h2>流程设计</h2>

      <Space wrap style={{ marginBottom: 12 }}>
        <Select
          style={{ width: 280 }}
          placeholder="选择流程定义"
          value={defId ?? undefined}
          onChange={setDefId}
          options={defOptions}
        />
        <Button onClick={() => setNewDefOpen(true)}>新建流程</Button>
        <Tooltip title={!defId ? "请先选择或新建流程" : ""}>
          <Button
            type="primary"
            disabled={!defId}
            loading={saveM.isPending}
            onClick={() => {
              if (!hasStart || !hasEnd)
                message.warning("建议包含『开始』与『结束』节点，仍会保存");
              saveM.mutate();
            }}
          >
            保存草稿
          </Button>
        </Tooltip>
        <Button
          disabled={!defId}
          loading={publishM.isPending}
          onClick={() => publishM.mutate()}
        >
          发布版本
        </Button>
        <Select
          style={{ width: 220 }}
          allowClear
          placeholder="关联表单（可选）"
          value={linkFormId ?? undefined}
          onChange={setLinkFormId}
          options={(formsQ.data || []).map((f) => ({ value: f.id, label: f.name }))}
        />
      </Space>

      <div style={{ display: "flex", height: 620, border: "1px solid #eee", borderRadius: 8 }}>
        {/* 节点面板 */}
        <div style={{ width: 150, borderRight: "1px solid #eee", padding: 12, background: "#fafafa" }}>
          <div style={{ fontSize: 12, color: "#888", marginBottom: 8 }}>拖拽节点到画布</div>
          {PALETTE.map((t) => (
            <div
              key={t}
              draggable
              onDragStart={(e) => e.dataTransfer.setData("application/wf-node", t)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                padding: "8px 10px",
                marginBottom: 8,
                background: "#fff",
                border: "1px solid #e0e0e0",
                borderRadius: 6,
                cursor: "grab",
                color: NODE_META[t].color,
                fontWeight: 600,
              }}
            >
              {NODE_ICON[t]} {NODE_META[t].label}
            </div>
          ))}
        </div>

        {/* 画布 */}
        <div style={{ flex: 1, position: "relative" }} onDrop={onDrop} onDragOver={(e) => e.preventDefault()}>
          {!defId ? (
            <Empty
              style={{ marginTop: 200 }}
              description="请选择或新建流程定义，然后拖拽左侧节点开始设计"
            />
          ) : (
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onNodeClick={(_, n) => setSelNode(n as WFNode)}
              onEdgeClick={(_, e) => setSelEdge(e as Edge)}
              onPaneClick={() => {
                setSelNode(null);
                setSelEdge(null);
              }}
              fitView
              deleteKeyCode={["Backspace", "Delete"]}
            >
              <Background />
              <Controls />
              <MiniMap pannable zoomable />
            </ReactFlow>
          )}
        </div>
      </div>

      {/* 节点配置抽屉 */}
      <Drawer
        title={selNode ? `节点配置：${NODE_META[selNode.data.nodeType].label}` : ""}
        open={!!selNode}
        onClose={() => setSelNode(null)}
        width={420}
      >
        {selNode && (
          <Space direction="vertical" style={{ width: "100%" }}>
            <div>
              <div style={{ fontSize: 12, color: "#888" }}>节点名称</div>
              <Input
                value={selNode.data.name}
                onChange={(e) => updateNodeData(selNode.id, { name: e.target.value })}
              />
            </div>

            {selNode.data.nodeType === "approval" && (
              <div>
                <div style={{ fontSize: 12, color: "#888", marginBottom: 4 }}>审批人</div>
                <SpecEditor
                  value={selNode.data.assignee || { type: "role", value: "manager" }}
                  onChange={(s) => updateNodeData(selNode.id, { assignee: s })}
                  roles={roles}
                  users={users}
                />
              </div>
            )}

            {(selNode.data.nodeType === "countersign" || selNode.data.nodeType === "notify") && (
              <div>
                <div style={{ fontSize: 12, color: "#888", marginBottom: 4 }}>
                  {selNode.data.nodeType === "countersign" ? "会签/抄送人" : "抄送人"}
                </div>
                {(selNode.data.assignees || []).map((spec, i) => (
                  <div key={i}>
                    <Space>
                      <SpecEditor
                        value={spec}
                        onChange={(s) => {
                          const arr = [...(selNode.data.assignees || [])];
                          arr[i] = s;
                          updateNodeData(selNode.id, { assignees: arr });
                        }}
                        roles={roles}
                        users={users}
                      />
                      <Button
                        danger
                        size="small"
                        onClick={() => {
                          const arr = (selNode.data.assignees || []).filter((_, j) => j !== i);
                          updateNodeData(selNode.id, { assignees: arr });
                        }}
                      >
                        删
                      </Button>
                    </Space>
                  </div>
                ))}
                <Button
                  size="small"
                  onClick={() =>
                    updateNodeData(selNode.id, {
                      assignees: [...(selNode.data.assignees || []), { type: "role", value: "manager" }],
                    })
                  }
                >
                  + 添加审批人
                </Button>

                {selNode.data.nodeType === "countersign" && (
                  <div style={{ marginTop: 12 }}>
                    <div style={{ fontSize: 12, color: "#888" }}>会签策略</div>
                    <Select
                      style={{ width: "100%" }}
                      value={selNode.data.strategy || "all"}
                      onChange={(v) => updateNodeData(selNode.id, { strategy: v })}
                      options={[
                        { value: "all", label: "全员通过（一票否决）" },
                        { value: "any", label: "一人通过即可" },
                        { value: "ratio", label: "按比例通过" },
                      ]}
                    />
                    {selNode.data.strategy === "ratio" && (
                      <InputNumber
                        style={{ width: "100%", marginTop: 8 }}
                        min={0}
                        max={1}
                        step={0.1}
                        placeholder="通过比例阈值（如 0.5）"
                        value={selNode.data.ratio ?? undefined}
                        onChange={(v) => updateNodeData(selNode.id, { ratio: v })}
                      />
                    )}
                  </div>
                )}
              </div>
            )}

            {selNode.data.nodeType === "condition" && (
              <div>
                <div style={{ fontSize: 12, color: "#888", marginBottom: 4 }}>分支模式</div>
                <Switch
                  checked={!!selNode.data.parallel}
                  onChange={(v) => updateNodeData(selNode.id, { parallel: v })}
                  checkedChildren="并行（命中分支全部走）"
                  unCheckedChildren="互斥（仅首个命中）"
                />
                <div style={{ fontSize: 12, color: "#999", marginTop: 6 }}>
                  在画布连线上点击可设置条件（按表单字段路由）
                </div>
              </div>
            )}

            <Button danger onClick={() => deleteNode(selNode.id)}>
              删除该节点
            </Button>
          </Space>
        )}
      </Drawer>

      {/* 连线条件抽屉 */}
      <Drawer
        title="分支条件"
        open={!!selEdge}
        onClose={() => setSelEdge(null)}
        width={420}
      >
        {selEdge && (
          <EdgeConditionEditor
            edge={selEdge}
            onChange={(c) => updateEdge(selEdge.id, c)}
            fields={(formsQ.data || []).find((f) => f.id === linkFormId)?.fields || []}
          />
        )}
      </Drawer>

      {/* 新建流程弹窗 */}
      <Modal
        title="新建流程定义"
        open={newDefOpen}
        onCancel={() => setNewDefOpen(false)}
        onOk={() => defForm.submit()}
        okText="创建"
        confirmLoading={createDefM.isPending}
      >
        <Form
          form={defForm}
          layout="vertical"
          onFinish={(v) => createDefM.mutate(v)}
        >
          <Form.Item name="code" label="流程编码" rules={[{ required: true }]}>
            <Input placeholder="如 leave-request" />
          </Form.Item>
          <Form.Item name="name" label="流程名称" rules={[{ required: true }]}>
            <Input placeholder="如 请假审批" />
          </Form.Item>
          <Form.Item name="category" label="分类" initialValue="general">
            <Input placeholder="如 hr / finance" />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

// 连线条件编辑器
function EdgeConditionEditor({
  edge,
  onChange,
  fields,
}: {
  edge: Edge;
  onChange: (c: ConditionGroup | null) => void;
  fields: { key: string; label: string }[];
}) {
  const cond = (edge.data as any)?.condition as ConditionGroup | null;
  const op = cond?.op || "and";
  const rules = cond?.rules || [];
  const fieldOptions = useMemo(
    () =>
      fields.length
        ? fields.map((f) => ({ value: f.key, label: `${f.label}（${f.key}）` }))
        : undefined,
    [fields]
  );

  const setRules = (rs: ConditionGroup["rules"]) => onChange({ op, rules: rs });
  const setOp = (o: "and" | "or") => onChange({ op: o, rules });

  return (
    <Space direction="vertical" style={{ width: "100%" }}>
      <Tag color="blue">从 {edge.source} → {edge.target}</Tag>
      <div style={{ fontSize: 12, color: "#888" }}>
        留空表示「默认分支」（其它条件都不命中时走此路）
      </div>
      <Select
        value={op}
        onChange={(v) => (v === "and" ? setOp("and") : setOp("or"))}
        options={[
          { value: "and", label: "同时满足（AND）" },
          { value: "or", label: "任一满足（OR）" },
        ]}
      />
      {rules.map((r, i) => (
        <Space key={i} align="start">
          <Select
            style={{ width: 150 }}
            placeholder="字段"
            value={r.field || undefined}
            onChange={(v) => {
              const rs = [...rules];
              rs[i] = { ...r, field: v };
              setRules(rs);
            }}
            options={fieldOptions || []}
            showSearch
            notFoundContent={fieldOptions ? "无可用字段" : "请先关联表单"}
          />
          <Select
            style={{ width: 90 }}
            value={r.op}
            onChange={(v) => {
              const rs = [...rules];
              rs[i] = { ...r, op: v as ConditionOp };
              setRules(rs);
            }}
            options={[
              { value: ">", label: ">" },
              { value: "<", label: "<" },
              { value: ">=", label: ">=" },
              { value: "<=", label: "<=" },
              { value: "==", label: "==" },
              { value: "!=", label: "!=" },
              { value: "in", label: "属于" },
              { value: "not_in", label: "不属于" },
              { value: "contains", label: "包含" },
            ]}
          />
          <Input
            style={{ width: 100 }}
            placeholder="值"
            value={r.value as string}
            onChange={(e) => {
              const rs = [...rules];
              rs[i] = { ...r, value: e.target.value };
              setRules(rs);
            }}
          />
          <Button danger size="small" onClick={() => setRules(rules.filter((_, j) => j !== i))}>
            删
          </Button>
        </Space>
      ))}
      <Button
        size="small"
        onClick={() =>
          setRules([...rules, { field: fieldOptions?.[0]?.value || "", op: ">", value: "" }])
        }
      >
        + 添加条件
      </Button>
      {rules.length > 0 && (
        <Button onClick={() => onChange(null)}>清空为默认分支</Button>
      )}
    </Space>
  );
}
