import type { ReactNode } from "react";

export interface StatCardProps {
  label: ReactNode;
  value: ReactNode;
  suffix?: ReactNode;
  icon?: ReactNode;
  onClick?: () => void;
}

/** 指标卡：工作台/看板上的数字概览，左侧带品牌渐变图标块 */
export default function StatCard({ label, value, suffix, icon, onClick }: StatCardProps) {
  return (
    <div
      className="zk-stat"
      onClick={onClick}
      style={onClick ? { cursor: "pointer" } : undefined}
    >
      {icon ? <div className="zk-stat__icon">{icon}</div> : null}
      <div style={{ minWidth: 0 }}>
        <div className="zk-stat__label">{label}</div>
        <div className="zk-stat__value">
          {value}
          {suffix ? <span className="zk-stat__suffix">{suffix}</span> : null}
        </div>
      </div>
    </div>
  );
}
