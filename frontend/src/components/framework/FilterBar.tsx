import type { ReactNode } from "react";
import { Button, Space } from "antd";
import { ReloadOutlined, SearchOutlined } from "@ant-design/icons";

export interface FilterItemProps {
  label?: ReactNode;
  children: ReactNode;
  /** 控件宽度，默认 180 */
  width?: number | string;
}

/** 单个筛选条件：左标签右控件，标签宽度统一保证多条件对齐 */
export function FilterItem({ label, children, width = 180 }: FilterItemProps) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
      {label ? (
        <span style={{ fontSize: 13, color: "var(--zk-text-secondary)", whiteSpace: "nowrap" }}>
          {label}
        </span>
      ) : null}
      <span style={{ display: "inline-block", width }}>{children}</span>
    </span>
  );
}

export interface FilterBarProps {
  children?: ReactNode;
  onSearch?: () => void;
  onReset?: () => void;
  /** 右侧附加内容（如「高级筛选」开关、导出按钮） */
  extra?: ReactNode;
  loading?: boolean;
}

/**
 * 筛选条：列表页顶部的查询条件区。
 * 约定「回车即查询」，并把查询/重置按钮统一放在最右。
 */
export default function FilterBar({
  children,
  onSearch,
  onReset,
  extra,
  loading,
}: FilterBarProps) {
  return (
    <div
      className="zk-filterbar"
      onKeyDown={(e) => {
        if (e.key === "Enter" && onSearch) onSearch();
      }}
    >
      {children}
      {onSearch || onReset ? (
        <Space size={8} style={{ marginLeft: "auto" }}>
          {extra}
          {onSearch ? (
            <Button type="primary" icon={<SearchOutlined />} loading={loading} onClick={onSearch}>
              查询
            </Button>
          ) : null}
          {onReset ? (
            <Button icon={<ReloadOutlined />} onClick={onReset}>
              重置
            </Button>
          ) : null}
        </Space>
      ) : (
        extra
      )}
    </div>
  );
}
