import type { ThemeConfig } from "antd";
import { bg, border, brand, font, neutral, primary, radius, semantic, shadow, text } from "./tokens";

/**
 * AntD 5 主题：把品牌令牌注入 AntD 的 design token 体系。
 * 这样既有页面无需逐个改造，即可整体切换到「中科智电」视觉。
 */
export const antdTheme: ThemeConfig = {
  token: {
    // 主色：品牌青蓝的可访问加深版本
    colorPrimary: primary[600],
    colorInfo: primary[600],
    colorSuccess: semantic.success,
    colorWarning: semantic.warning,
    colorError: semantic.error,
    colorLink: text.link,
    colorLinkHover: primary[500],

    // 文字与背景
    colorTextBase: text.primary,
    colorText: text.primary,
    colorTextSecondary: text.secondary,
    colorTextTertiary: text.tertiary,
    colorTextQuaternary: text.disabled,
    colorBgBase: "#ffffff",
    colorBgLayout: bg.page,
    colorBgContainer: bg.container,
    colorBorder: border.color,
    colorBorderSecondary: border.color,
    colorSplit: border.color,

    // 圆角与字体
    borderRadius: radius.md,
    borderRadiusLG: radius.lg,
    borderRadiusSM: radius.sm,
    borderRadiusXS: radius.xs,
    fontFamily: font.family,
    fontSize: font.size.base,
    fontSizeLG: font.size.lg,
    fontSizeSM: font.size.sm,
    fontSizeHeading1: 30,
    fontSizeHeading2: 24,
    fontSizeHeading3: 18,
    fontSizeHeading4: 16,
    fontSizeHeading5: 14,
    lineHeight: font.lineHeight,

    // 控件尺寸（OA 高密度信息场景，默认 32 更紧凑）
    controlHeight: 32,
    controlHeightLG: 38,
    controlHeightSM: 26,
    controlHeightXS: 22,

    // 阴影
    boxShadow: shadow.sm,
    boxShadowSecondary: shadow.md,
    boxShadowTertiary: shadow.xs,
  },

  components: {
    Layout: {
      headerBg: "#ffffff",
      headerHeight: 56,
      headerPadding: "0 16px",
      bodyBg: bg.page,
      siderBg: bg.sider,
      triggerBg: brand.deepActive,
      triggerColor: "#ffffff",
    },

    Menu: {
      // 侧边栏深色菜单
      darkItemBg: "transparent",
      darkSubMenuItemBg: "transparent",
      darkItemColor: "rgba(255, 255, 255, 0.78)",
      darkItemHoverBg: "rgba(255, 255, 255, 0.10)",
      darkItemHoverColor: "#ffffff",
      darkItemSelectedBg: "rgba(43, 167, 210, 0.22)",
      darkItemSelectedColor: "#ffffff",
      // 亮色菜单（顶栏下拉、内容区导航）
      itemBg: "transparent",
      itemColor: text.secondary,
      itemHoverBg: bg.hover,
      itemHoverColor: primary[600],
      itemSelectedBg: bg.selected,
      itemSelectedColor: primary[600],
      itemHeight: 38,
      itemMarginInline: 8,
      itemMarginBlock: 2,
      itemBorderRadius: radius.md,
      subMenuItemBg: "transparent",
      iconMarginInlineEnd: 10,
      activeBarWidth: 3,
      activeBarBorderWidth: 0,
    },

    Card: {
      headerBg: "#ffffff",
      headerFontSize: font.size.base,
      headerHeight: 48,
      paddingLG: 20,
      colorBorderSecondary: border.color,
    },

    Table: {
      headerBg: "#f5f8fc",
      headerColor: text.primary,
      headerSplitColor: "transparent",
      rowHoverBg: bg.hover,
      borderColor: border.color,
      cellPaddingBlock: 10,
      cellPaddingInline: 12,
      cellPaddingBlockSM: 8,
      cellPaddingInlineSM: 10,
      headerBorderRadius: radius.sm,
    },

    Button: {
      controlHeight: 32,
      fontWeight: font.weight.medium,
      primaryShadow: "none",
      defaultShadow: "none",
      dangerShadow: "none",
      borderRadius: radius.md,
    },

    Tabs: {
      titleFontSize: font.size.base,
      horizontalItemPadding: "10px 16px",
      horizontalItemGutter: 0,
      itemColor: text.secondary,
      itemSelectedColor: primary[600],
      itemHoverColor: primary[500],
      inkBarColor: primary[600],
      cardBg: "#f5f8fc",
      cardGutter: 4,
    },

    Breadcrumb: {
      itemColor: text.secondary,
      lastItemColor: text.primary,
      linkColor: text.secondary,
      linkHoverColor: primary[600],
      separatorColor: text.disabled,
      fontSize: font.size.sm,
    },

    Descriptions: {
      labelBg: "#f7fafd",
      titleMarginBottom: 12,
      itemPaddingBottom: 12,
    },

    Input: { paddingBlock: 5, activeShadow: shadow.focus },
    InputNumber: { activeShadow: shadow.focus },
    Select: { optionSelectedBg: bg.selected, optionSelectedColor: primary[600] },
    DatePicker: { activeShadow: shadow.focus },
    Modal: { titleFontSize: font.size.lg, headerBg: "#ffffff", contentBg: "#ffffff" },
    Drawer: { paddingLG: 20 },
    Tag: { defaultBg: neutral[100], defaultColor: text.secondary, borderRadiusSM: radius.sm },
    Statistic: { titleFontSize: font.size.sm, contentFontSize: 26 },
    Progress: { defaultColor: primary[600] },
    Pagination: { itemActiveBg: primary[600], itemSize: 30 },
    Tooltip: { colorBgSpotlight: "rgba(15, 30, 55, 0.92)" },
    Notification: { width: 340 },
    Form: { labelColor: text.primary, verticalLabelPadding: "0 0 6px" },
  },
};

export default antdTheme;
