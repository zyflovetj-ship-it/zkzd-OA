/**
 * 多页签工作区（泛微 e-cology 的核心交互特征之一）。
 *
 * 设计要点：
 * - 页签以路由 path 为唯一键，首页（/）固定不可关闭；
 * - 每个页签带 nonce，刷新页签时递增以强制重挂载（等价于泛微的「刷新本页」）；
 * - 页签数量设上限，超出时自动关闭最早的、可关闭的页签，避免无限增长；
 * - 真正的「保持状态」由 AppShell 侧的多实例渲染实现（见 AppShell 的 pane 渲染），
 *   本模块只负责页签集合与激活态。
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

export const HOME_PATH = "/";
/** 同时打开的页签上限 */
const MAX_TABS = 12;

export interface WorkspaceTab {
  /** 路由 path，作为唯一键 */
  key: string;
  /** 页签标题 */
  title: string;
  /** 是否可关闭（首页固定） */
  closable: boolean;
  /** 刷新计数：变化即重挂载该页签内容 */
  nonce: number;
}

interface WorkspaceContextValue {
  tabs: WorkspaceTab[];
  activeKey: string;
  openTab: (key: string, title: string) => void;
  activate: (key: string) => void;
  closeTab: (key: string) => string;
  closeOthers: (key: string) => void;
  closeAll: () => void;
  refresh: (key: string) => void;
  setTitle: (key: string, title: string) => void;
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [tabs, setTabs] = useState<WorkspaceTab[]>([
    { key: HOME_PATH, title: "工作台", closable: false, nonce: 0 },
  ]);
  const [activeKey, setActiveKey] = useState<string>(HOME_PATH);
  // 用 ref 读取最新页签集合，避免把 tabs 塞进 useCallback 依赖导致频繁重建
  const tabsRef = useRef(tabs);
  tabsRef.current = tabs;

  const openTab = useCallback((key: string, title: string) => {
    setActiveKey(key);
    setTabs((prev) => {
      const idx = prev.findIndex((t) => t.key === key);
      if (idx >= 0) {
        // 已存在：仅在标题变化时更新（避免无意义的 setState 触发重渲染）
        if (prev[idx].title === title) return prev;
        const next = [...prev];
        next[idx] = { ...next[idx], title };
        return next;
      }
      const tab: WorkspaceTab = {
        key,
        title,
        closable: key !== HOME_PATH,
        nonce: 0,
      };
      const next = [...prev, tab];
      // 超限：从最早的可关闭页签开始淘汰，且不动当前激活页签
      while (next.length > MAX_TABS) {
        const victim = next.findIndex((t) => t.closable && t.key !== key);
        if (victim < 0) break;
        next.splice(victim, 1);
      }
      return next;
    });
  }, []);

  const activate = useCallback((key: string) => setActiveKey(key), []);

  /** 关闭页签并返回下一个应当激活的 key（调用方据此导航） */
  const closeTab = useCallback((key: string) => {
    const current = tabsRef.current;
    const idx = current.findIndex((t) => t.key === key);
    if (idx < 0 || !current[idx].closable) return key;
    const next = current.filter((t) => t.key !== key);
    setTabs(next);
    if (activeKey === key) {
      const fallback = next[Math.min(idx, next.length - 1)]?.key ?? HOME_PATH;
      setActiveKey(fallback);
      return fallback;
    }
    return activeKey;
  }, [activeKey]);

  const closeOthers = useCallback((key: string) => {
    setTabs((prev) => prev.filter((t) => t.key === key || !t.closable));
    setActiveKey(key);
  }, []);

  const closeAll = useCallback(() => {
    setTabs((prev) => prev.filter((t) => !t.closable));
    setActiveKey(HOME_PATH);
  }, []);

  const refresh = useCallback((key: string) => {
    setTabs((prev) =>
      prev.map((t) => (t.key === key ? { ...t, nonce: t.nonce + 1 } : t))
    );
  }, []);

  const setTitle = useCallback((key: string, title: string) => {
    setTabs((prev) => {
      const idx = prev.findIndex((t) => t.key === key);
      if (idx < 0 || prev[idx].title === title) return prev;
      const next = [...prev];
      next[idx] = { ...next[idx], title };
      return next;
    });
  }, []);

  const value = useMemo(
    () => ({ tabs, activeKey, openTab, activate, closeTab, closeOthers, closeAll, refresh, setTitle }),
    [tabs, activeKey, openTab, activate, closeTab, closeOthers, closeAll, refresh, setTitle]
  );

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspace 必须在 WorkspaceProvider 内使用");
  return ctx;
}

/** 页面可用它把动态标题（如「报销单 EXP-001」）写回所属页签 */
export function useTabTitle(title: string | undefined) {
  const { activeKey, setTitle } = useWorkspace();
  useEffect(() => {
    if (title) setTitle(activeKey, title);
  }, [title, activeKey, setTitle]);
}
