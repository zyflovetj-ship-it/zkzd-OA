import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Form, Input, InputNumber, Select, Space, Table, message } from "antd";
import { sigApi } from "../api/endpoints";

function SignaturePad({ onChange }: { onChange: (data: string) => void }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const drawing = useRef(false);

  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, c.width, c.height);
    ctx.strokeStyle = "#000";
    ctx.lineWidth = 2;
  }, []);

  const pos = (e: any) => {
    const c = ref.current!;
    const rect = c.getBoundingClientRect();
    const t = e.touches?.[0] || e;
    return {
      x: (t.clientX - rect.left) * (c.width / rect.width),
      y: (t.clientY - rect.top) * (c.height / rect.height),
    };
  };
  const start = (e: any) => {
    drawing.current = true;
    const p = pos(e);
    ref.current!.getContext("2d")!.beginPath();
    ref.current!.getContext("2d")!.moveTo(p.x, p.y);
  };
  const move = (e: any) => {
    if (!drawing.current) return;
    e.preventDefault();
    const p = pos(e);
    const ctx = ref.current!.getContext("2d")!;
    ctx.lineTo(p.x, p.y);
    ctx.stroke();
  };
  const end = () => {
    if (!drawing.current) return;
    drawing.current = false;
    onChange(ref.current!.toDataURL());
  };

  return (
    <canvas
      ref={ref}
      width={400}
      height={150}
      style={{ border: "1px solid #ccc", touchAction: "none", background: "#fff" }}
      onMouseDown={start}
      onMouseMove={move}
      onMouseUp={end}
      onMouseLeave={end}
      onTouchStart={start}
      onTouchMove={move}
      onTouchEnd={end}
    />
  );
}

export default function Signatures() {
  const qc = useQueryClient();
  const [form] = Form.useForm();
  const [dataUrl, setDataUrl] = useState("");
  const [refType, setRefType] = useState("leave_request");
  const [refId, setRefId] = useState(1);

  const listQ = useQuery({
    queryKey: ["sigs", refType, refId],
    queryFn: () => sigApi.list(refType, refId),
  });

  const createM = useMutation({
    mutationFn: (v: any) => sigApi.create(v),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sigs"] });
      message.success("已签署");
      setDataUrl("");
    },
    onError: (e: any) => message.error(e?.message || "签署失败"),
  });

  return (
    <div>
      <h2>电子签单</h2>
      <Space style={{ marginBottom: 12 }}>
        <Select
          value={refType}
          onChange={setRefType}
          style={{ width: 140 }}
          options={[
            { value: "leave_request", label: "请假单" },
            { value: "document", label: "文档" },
            { value: "workflow", label: "工作流" },
          ]}
        />
        <InputNumber value={refId} onChange={(v) => setRefId(v || 1)} min={1} />
        <Button onClick={() => listQ.refetch()}>查询</Button>
      </Space>

      <SignaturePad onChange={setDataUrl} />

      <div style={{ marginTop: 12 }}>
        <Button
          type="primary"
          disabled={!dataUrl}
          onClick={() =>
            createM.mutate({
              ref_type: refType,
              ref_id: refId,
              signature_data: dataUrl,
              comment: form.getFieldValue("comment"),
            })
          }
        >
          提交签署
        </Button>
        <Form form={form} layout="inline" style={{ marginLeft: 12 }}>
          <Form.Item name="comment" label="备注">
            <Input />
          </Form.Item>
        </Form>
      </div>

      <Table
        rowKey="id"
        style={{ marginTop: 16 }}
        loading={listQ.isLoading}
        dataSource={listQ.data || []}
        columns={[
          { title: "ID", dataIndex: "id" },
          { title: "签署人", dataIndex: "signer_id" },
          {
            title: "内容哈希",
            dataIndex: "content_hash",
            render: (v: string) => <code style={{ fontSize: 10 }}>{v.slice(0, 16)}…</code>,
          },
          { title: "时间", dataIndex: "signed_at" },
        ]}
      />
    </div>
  );
}
