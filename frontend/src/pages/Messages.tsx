import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Badge, Button, Empty, Segmented, Space, Table, Tag, message } from "antd";
import { CheckOutlined, NotificationOutlined } from "@ant-design/icons";
import { msgApi } from "../api/endpoints";
import type { NotificationOut } from "../types";

const TYPE_META: Record<string, { color: string; label: string }> = {
  system: { color: "default", label: "系统" },
  leave: { color: "blue", label: "请假" },
  workflow: { color: "green", label: "审批" },
  announcement: { color: "orange", label: "公告" },
};

function fmtTime(s: string): string {
  const d = new Date(s);
  if (isNaN(d.getTime())) return s;
  return d.toLocaleString("zh-CN", { hour12: false });
}

export default function Messages() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [onlyUnread, setOnlyUnread] = useState(false);

  const listQ = useQuery({
    queryKey: ["notifications", onlyUnread],
    queryFn: () => msgApi.list({ unread_only: onlyUnread, limit: 100 }),
  });

  const markReadM = useMutation({
    mutationFn: (id: number) => msgApi.markRead(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
    onError: (e: any) => message.error(e?.message || "标记失败"),
  });

  const markAllM = useMutation({
    mutationFn: () => msgApi.markAllRead(),
    onSuccess: () => {
      message.success("已全部标记为已读");
      qc.invalidateQueries({ queryKey: ["notifications"] });
    },
    onError: (e: any) => message.error(e?.message || "操作失败"),
  });

  const open = (n: NotificationOut) => {
    if (!n.is_read) markReadM.mutate(n.id);
    if (n.link) navigate(n.link);
  };

  const data = listQ.data?.items ?? [];

  const columns = [
    {
      title: "类型",
      dataIndex: "type",
      width: 90,
      render: (t: string) => {
        const m = TYPE_META[t] ?? { color: "default", label: t };
        return <Tag color={m.color}>{m.label}</Tag>;
      },
    },
    {
      title: "标题",
      dataIndex: "title",
      render: (v: string, r: NotificationOut) => (
        <span style={{ fontWeight: r.is_read ? 400 : 600 }}>{v}</span>
      ),
    },
    {
      title: "内容",
      dataIndex: "body",
      ellipsis: true,
    },
    {
      title: "时间",
      dataIndex: "created_at",
      width: 170,
      render: (v: string) => fmtTime(v),
    },
    {
      title: "操作",
      width: 140,
      render: (_: any, r: NotificationOut) => (
        <Space>
          <Button size="small" icon={<NotificationOutlined />} onClick={() => open(r)}>
            查看
          </Button>
          {!r.is_read && (
            <Button
              size="small"
              type="text"
              icon={<CheckOutlined />}
              onClick={() => markReadM.mutate(r.id)}
            />
          )}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Space style={{ marginBottom: 16, justifyContent: "space-between", width: "100%" }}>
        <Segmented
          value={onlyUnread ? "unread" : "all"}
          onChange={(v) => setOnlyUnread(v === "unread")}
          options={[
            { label: "全部", value: "all" },
            {
              label: (
                <span>
                  未读
                  {listQ.data?.unread ? (
                    <Badge count={listQ.data.unread} size="small" offset={[4, -2]} />
                  ) : null}
                </span>
              ),
              value: "unread",
            },
          ]}
        />
        <Button
          type="primary"
          onClick={() => markAllM.mutate()}
          loading={markAllM.isPending}
          disabled={!listQ.data?.unread}
        >
          全部标记为已读
        </Button>
      </Space>

      <Table<NotificationOut>
        rowKey="id"
        loading={listQ.isLoading}
        columns={columns}
        dataSource={data}
        pagination={{ pageSize: 10, showTotal: (t) => `共 ${t} 条` }}
        locale={{ emptyText: <Empty description="暂无通知" /> }}
      />
    </div>
  );
}
