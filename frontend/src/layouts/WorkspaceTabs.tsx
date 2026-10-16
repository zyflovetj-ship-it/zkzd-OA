import { useEffect, useRef } from "react";
import { Button, Dropdown, Tooltip } from "antd";
import {
  CloseCircleOutlined,
  CloseOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import type { WorkspaceTab } from "./workspace";

interface Props {
  tabs: WorkspaceTab[];
  activeKey: string;
  onActivate: (key: string) => void;
  onClose: (key: string) => void;
  onCloseOthers: (key: string) => void;
  onCloseAll: () => void;
  onRefresh: (key: string) => void;
}

export default function WorkspaceTabs({
  tabs,
  activeKey,
  onActivate,
  onClose,
  onCloseOthers,
  onCloseAll,
  onRefresh,
}: Props) {
  const refs = useRef<Record<string, HTMLSpanElement | null>>({});

  // 激活页签滚动进可视区（页签较多时）
  useEffect(() => {
    refs.current[activeKey]?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [activeKey]);

  return (
    <div className="zk-tabbar">
      {tabs.map((t) => {
        const active = t.key === activeKey;
        return (
          <Dropdown
            key={t.key}
            trigger={["contextMenu"]}
            menu={{
              items: [
                { key: "refresh", label: "刷新本页", icon: <ReloadOutlined /> },
                { key: "close", label: "关闭本页", icon: <CloseOutlined />, disabled: !t.closable },
                { type: "divider" },
                { key: "others", label: "关闭其他页签" },
                { key: "all", label: "关闭全部页签" },
              ],
              onClick: ({ key, domEvent }) => {
                domEvent.stopPropagation();
                if (key === "refresh") onRefresh(t.key);
                else if (key === "close") onClose(t.key);
                else if (key === "others") onCloseOthers(t.key);
                else if (key === "all") onCloseAll();
              },
            }}
          >
            <span
              ref={(el) => {
                refs.current[t.key] = el;
              }}
              className={"zk-tab" + (active ? " zk-tab--active" : "")}
              onClick={() => onActivate(t.key)}
              title={t.title}
            >
              <i className="zk-tab__dot" />
              <span style={{ maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis" }}>
                {t.title}
              </span>
              {t.closable ? (
                <span
                  className="zk-tab__close"
                  onClick={(e) => {
                    e.stopPropagation();
                    onClose(t.key);
                  }}
                >
                  <CloseOutlined />
                </span>
              ) : null}
            </span>
          </Dropdown>
        );
      })}

      <div className="zk-tabbar__tools">
        <Tooltip title="刷新当前页">
          <Button
            type="text"
            size="small"
            icon={<ReloadOutlined />}
            onClick={() => onRefresh(activeKey)}
          />
        </Tooltip>
        <Tooltip title="关闭全部页签">
          <Button
            type="text"
            size="small"
            icon={<CloseCircleOutlined />}
            onClick={onCloseAll}
          />
        </Tooltip>
      </div>
    </div>
  );
}
