import type { CSSProperties, ReactNode } from "react";

export interface SectionCardProps {
  title?: ReactNode;
  extra?: ReactNode;
  children?: ReactNode;
  /** 内容区去掉内边距，供表格/列表铺满卡片 */
  flush?: boolean;
  /** 卡片主体内边距覆盖 */
  bodyStyle?: CSSProperties;
  className?: string;
  style?: CSSProperties;
  id?: string;
}

/** 卡片容器：带品牌色标题条的白色卡片，是页面内容的基本承载单元 */
export default function SectionCard({
  title,
  extra,
  children,
  flush = false,
  bodyStyle,
  className,
  style,
  id,
}: SectionCardProps) {
  const hasHead = Boolean(title || extra);
  return (
    <section id={id} className={"zk-card" + (className ? " " + className : "")} style={style}>
      {hasHead ? (
        <header className="zk-card__head">
          <div className="zk-card__title">{title}</div>
          {extra ? <div className="zk-card__extra">{extra}</div> : null}
        </header>
      ) : null}
      <div
        className={"zk-card__body" + (flush ? " zk-card__body--tight" : "")}
        style={bodyStyle}
      >
        {children}
      </div>
    </section>
  );
}
