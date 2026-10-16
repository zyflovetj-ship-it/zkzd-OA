import type { ReactNode } from "react";
import { Button, Space } from "antd";
import SectionCard from "./SectionCard";

export interface FormSectionProps {
  title?: ReactNode;
  extra?: ReactNode;
  children: ReactNode;
  /** 分组说明文字 */
  description?: ReactNode;
}

/** 表单分组：把长表单按业务语义切成多张卡片（基本信息 / 附件 / 审批设置…） */
export function FormSection({ title, extra, children, description }: FormSectionProps) {
  return (
    <SectionCard title={title} extra={extra}>
      {description ? (
        <p style={{ margin: "0 0 16px", fontSize: 13, color: "var(--zk-text-secondary)" }}>
          {description}
        </p>
      ) : null}
      {children}
    </SectionCard>
  );
}

export interface FormFooterBarProps {
  children: ReactNode;
  /** 左侧补充说明（如「提交后将进入审批流」） */
  hint?: ReactNode;
}

/** 表单底部操作条：泛微式表单在卡片底部右对齐放置 提交/取消 */
export function FormFooterBar({ children, hint }: FormFooterBarProps) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "12px 16px",
        background: "#fff",
        border: "1px solid var(--zk-border)",
        borderRadius: "var(--zk-radius-lg)",
        boxShadow: "var(--zk-shadow-xs)",
      }}
    >
      {hint ? (
        <span style={{ fontSize: 13, color: "var(--zk-text-secondary)" }}>{hint}</span>
      ) : null}
      <Space size={8} style={{ marginLeft: "auto" }}>
        {children}
      </Space>
    </div>
  );
}

export interface DescriptionsCardProps {
  title?: ReactNode;
  extra?: ReactNode;
  children: ReactNode;
}

/** 详情分组：卡片包裹的 Descriptions，用于详情页的「基本信息」等分区 */
export function DescriptionsCard({ title, extra, children }: DescriptionsCardProps) {
  return (
    <SectionCard title={title} extra={extra}>
      {children}
    </SectionCard>
  );
}

export interface ActionBarProps {
  children: ReactNode;
  extra?: ReactNode;
}

/** 卡片内工具栏（新增/批量/导出…） */
export function ActionBar({ children, extra }: ActionBarProps) {
  return (
    <div className="zk-toolbar">
      {children}
      {extra ? <div className="zk-toolbar__spacer" /> : null}
      {extra}
    </div>
  );
}

export { Button };
