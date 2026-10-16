import type { CSSProperties, ReactNode } from "react";

export interface PageContainerProps {
  /** 页面标题；通常与页签标题一致 */
  title?: ReactNode;
  /** 标题下方的说明文字 */
  description?: ReactNode;
  /** 右上角操作区（按钮组） */
  extra?: ReactNode;
  children?: ReactNode;
  className?: string;
  style?: CSSProperties;
}

/**
 * 页面容器：统一「标题 + 说明 + 操作区 + 内容」的页面骨架。
 * 泛微式页面都遵循这一结构，避免每个页面各写一套页头。
 */
export default function PageContainer({
  title,
  description,
  extra,
  children,
  className,
  style,
}: PageContainerProps) {
  const hasHead = Boolean(title || description || extra);
  return (
    <div className={"zk-page" + (className ? " " + className : "")} style={style}>
      {hasHead ? (
        <div className="zk-page__head">
          <div className="zk-page__heading">
            {title ? <h1 className="zk-page__title">{title}</h1> : null}
            {description ? <p className="zk-page__desc">{description}</p> : null}
          </div>
          {extra ? <div className="zk-page__extra">{extra}</div> : null}
        </div>
      ) : null}
      {children}
    </div>
  );
}
