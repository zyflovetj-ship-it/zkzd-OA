import { useState, useEffect } from "react";

/**
 * 移动端适配Hook：检测屏幕宽度是否为移动端（<768px）。
 * 用于响应式布局切换：表格→卡片、侧边栏→抽屉等。
 */
export function useIsMobile(breakpoint: number = 768): boolean {
  const [isMobile, setIsMobile] = useState(
    typeof window !== "undefined" ? window.innerWidth < breakpoint : false
  );

  useEffect(() => {
    const handleResize = () => {
      setIsMobile(window.innerWidth < breakpoint);
    };

    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [breakpoint]);

  return isMobile;
}

export default useIsMobile;