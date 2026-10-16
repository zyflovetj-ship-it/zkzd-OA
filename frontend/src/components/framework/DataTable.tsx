import type { ReactNode } from "react";
import { Empty, Table, type TableProps } from "antd";
import SectionCard from "./SectionCard";

export interface DataTableProps<T extends object> {
  rowKey: TableProps<T>["rowKey"];
  columns: TableProps<T>["columns"];
  dataSource?: T[];
  loading?: boolean;
  /** 卡片标题 */
  title?: ReactNode;
  /** 卡片右上角操作 */
  extra?: ReactNode;
  /** 表格上方的工具栏（新增/批量删除/导出…），位于卡片内、表格外 */
  toolbar?: ReactNode;
  pagination?: TableProps<T>["pagination"];
  scroll?: TableProps<T>["scroll"];
  size?: TableProps<T>["size"];
  onRow?: TableProps<T>["onRow"];
  rowSelection?: TableProps<T>["rowSelection"];
  expandable?: TableProps<T>["expandable"];
  footer?: TableProps<T>["footer"];
  emptyText?: ReactNode;
  /** 是否包一层卡片，默认 true */
  card?: boolean;
}

/**
 * 列表页表格：统一分页、空态、紧凑密度与「工具栏 + 表格」的卡片组合。
 * 空态默认给出可读的中文提示，而不是 AntD 的默认英文插图。
 */
export default function DataTable<T extends object>({
  rowKey,
  columns,
  dataSource,
  loading,
  title,
  extra,
  toolbar,
  pagination,
  scroll,
  size = "middle",
  onRow,
  rowSelection,
  expandable,
  footer,
  emptyText = "暂无数据",
  card = true,
}: DataTableProps<T>) {
  const table = (
    <>
      {toolbar ? (
        <div
          className="zk-toolbar"
          style={{ padding: "12px 16px", borderBottom: "1px solid var(--zk-border)" }}
        >
          {toolbar}
        </div>
      ) : null}
      <Table<T>
        rowKey={rowKey}
        columns={columns}
        dataSource={dataSource}
        loading={loading}
        size={size}
        onRow={onRow}
        rowSelection={rowSelection}
        expandable={expandable}
        footer={footer}
        locale={{
          emptyText: (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyText} />
          ),
        }}
        scroll={scroll ?? { x: "max-content" }}
        pagination={
          pagination === undefined
            ? { showSizeChanger: true, showTotal: (t) => "共 " + t + " 条", defaultPageSize: 20 }
            : pagination
        }
      />
    </>
  );

  if (!card) return table;
  return (
    <SectionCard title={title} extra={extra} flush>
      {table}
    </SectionCard>
  );
}
