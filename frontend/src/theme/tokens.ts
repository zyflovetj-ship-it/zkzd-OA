/**
 * 设计令牌（Design Tokens）
 *
 * 品牌色取自「中科智电」标识实测像素：
 *   - 深宝蓝 #033b88 —— 标识外环，用于品牌区/侧边栏/渐变
 *   - 亮青蓝 #2ba7d2 —— 标识闪电，用于强调、选中态、图表主色
 *   - 深灰蓝 #223a5d —— 字标，用于标题文字
 *
 * 交互主色单独取 primary[600] = #0d7fb8：它是品牌青蓝的加深版本，
 * 与白色文字对比度 4.54:1，满足 WCAG AA（而直接用 #2ba7d2 仅 2.79:1，不可用于按钮文字）。
 */

export const brand = {
  /** 标识外环深宝蓝 */
  deep: "#033b88",
  deepHover: "#044a9e",
  deepActive: "#022a63",
  /** 品牌区渐变（顶部/登录页/门户横幅） */
  deepGradient: "linear-gradient(135deg, #044a9e 0%, #033b88 48%, #022a63 100%)",
  /** 标识闪电亮青蓝 */
  cyan: "#2ba7d2",
  cyanHover: "#45b8e0",
  cyanActive: "#1c8bb4",
  /** 字标深灰蓝 */
  ink: "#223a5d",
} as const;

/** 主色阶（青蓝家族），供图表、标签、进度等按层级取用 */
export const primary = {
  50: "#e6f4fb",
  100: "#c2e4f4",
  200: "#9ad3ec",
  300: "#6fbfe2",
  400: "#4aaed9",
  500: "#2ba7d2",
  600: "#0d7fb8",
  700: "#0a6a9c",
  800: "#075581",
  900: "#044066",
} as const;

/** 中性色阶（带冷调，贴合品牌深蓝） */
export const neutral = {
  0: "#ffffff",
  50: "#f6f8fb",
  100: "#eef2f7",
  200: "#e3e9f0",
  300: "#cbd5e1",
  400: "#94a3b8",
  500: "#64748b",
  600: "#475569",
  700: "#334155",
  800: "#1e293b",
  900: "#0f172a",
} as const;

/** 语义色 */
export const semantic = {
  success: "#17a673",
  successBg: "#e8f7f1",
  warning: "#e8a33d",
  warningBg: "#fdf4e7",
  error: "#e05545",
  errorBg: "#fdeeec",
  info: "#0d7fb8",
  infoBg: "#e6f4fb",
} as const;

export const text = {
  primary: "#1f2d3d",
  secondary: "#5a6b7f",
  tertiary: "#8a99ab",
  disabled: "#b6c0cc",
  inverse: "#ffffff",
  link: "#0d7fb8",
  linkHover: "#2ba7d2",
} as const;

export const bg = {
  /** 页面底色：泛微式浅灰蓝 */
  page: "#f0f3f8",
  container: "#ffffff",
  elevated: "#ffffff",
  /** 侧边栏：品牌深蓝 */
  sider: "#033b88",
  siderSub: "#022a63",
  /** 交互态 */
  hover: "#f2f7fc",
  selected: "#e6f2fa",
  mask: "rgba(15, 30, 55, 0.45)",
} as const;

export const border = {
  color: "#e3e9f0",
  strong: "#cbd5e1",
  /** 侧边栏分隔线 */
  sider: "rgba(255, 255, 255, 0.12)",
} as const;

/** 圆角 */
export const radius = {
  xs: 2,
  sm: 4,
  md: 6,
  lg: 8,
  xl: 12,
  pill: 999,
} as const;

/** 间距（4 的倍数） */
export const space = {
  xxs: 4,
  xs: 8,
  sm: 12,
  md: 16,
  lg: 24,
  xl: 32,
  xxl: 48,
} as const;

/** 阴影（低饱和冷色投影，避免脏灰） */
export const shadow = {
  xs: "0 1px 2px rgba(16, 36, 64, 0.06)",
  sm: "0 1px 4px rgba(16, 36, 64, 0.08)",
  md: "0 4px 12px rgba(16, 36, 64, 0.10)",
  lg: "0 8px 24px rgba(16, 36, 64, 0.12)",
  focus: "0 0 0 3px rgba(13, 127, 184, 0.16)",
} as const;

/** 字体 */
export const font = {
  family:
    '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Helvetica Neue", Helvetica, Arial, sans-serif',
  familyNumber:
    '"DIN Alternate", "SF Mono", Menlo, Consolas, "PingFang SC", "Microsoft YaHei", monospace',
  size: {
    xs: 12,
    sm: 13,
    base: 14,
    lg: 16,
    xl: 18,
    xxl: 20,
    title: 24,
  },
  weight: {
    regular: 400,
    medium: 500,
    semibold: 600,
    bold: 700,
  },
  lineHeight: 1.5715,
} as const;

/** 布局尺寸（泛微式五段结构：品牌栏 / 一级导航 / 页签 / 二级菜单 / 内容） */
export const layout = {
  /** 顶部品牌栏高度（一级导航内嵌于其中，不单独占一行） */
  headerHeight: 56,
  /** 左侧二级菜单宽度 */
  siderWidth: 216,
  siderCollapsedWidth: 64,
  /** 多页签栏高度 */
  tabBarHeight: 40,
  /** 面包屑行高 */
  breadcrumbHeight: 36,
  /** 内容区内边距 */
  contentPadding: 16,
  /** 移动端断点 */
  mobileBreakpoint: 768,
  /** 窄屏断点（收起二级菜单） */
  compactBreakpoint: 1200,
} as const;

/** z-index 分层 */
export const zIndex = {
  sider: 90,
  header: 100,
  tabbar: 95,
  dropdown: 1050,
  modal: 1100,
  message: 1200,
} as const;

export const tokens = {
  brand,
  primary,
  neutral,
  semantic,
  text,
  bg,
  border,
  radius,
  space,
  shadow,
  font,
  layout,
  zIndex,
};

export type Tokens = typeof tokens;
export default tokens;
