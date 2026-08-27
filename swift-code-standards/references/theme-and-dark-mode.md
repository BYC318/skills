# 主题与夜间模式适配规则

## 适用判定

改动颜色、图片、渐变、边框、阴影、模糊、`CALayer`/`CGColor`、自定义绘制、视觉缓存、bar 外观或运行时主题切换时必须执行本规则。纯 Model、网络、存储或无 UI 算法可判定为不适用，但必须说明依据。

## 实现前

1. 检索并复用项目已有设计 token、动态语义色、Asset Catalog appearance、主题状态源与刷新机制；不得新增平行主题单例或页面私有色板。
2. 区分系统 `userInterfaceStyle` 与 App 自定义主题。后者不一定触发 `traitCollectionDidChange`，必须跟随项目真实主题状态源刷新。

## 颜色与资源

- 优先使用项目设计系统语义 token，其次使用 UIKit/SwiftUI 动态语义色或 Asset Catalog Any/Dark 变体。不得把 `.white`、`.black` 或固定 RGB 当作默认界面颜色；品牌不变色必须有明确语义且在 Light/Dark 中验证对比度。
- 图标优先使用 template 渲染与动态 `tintColor`，需要不同视觉时使用 Any/Dark 资源。照片、头像、商品图、内容图和已完成色彩管理的媒体不得机械染色。
- 材质、模糊、状态栏、导航栏和 Tab Bar 外观使用系统或项目动态配置，不得在可复用子视图中强制 `overrideUserInterfaceStyle`。只有经产品确认的组合根可统一覆盖外观。

## `CGColor`、图层与绘制

- 动态 `UIColor` 转成 `CGColor` 后不会随外观自动更新。`borderColor`、`shadowColor`、`CAGradientLayer.colors`、shape/text layer 颜色必须使用当前 `traitCollection` 重新解析并设置。
- 系统外观变化时，在 `traitCollectionDidChange(_:)` 中使用 `hasDifferentColorAppearance(comparedTo:)` 判断后刷新图层；项目自定义主题则同时订阅已有主题状态源。
- 自定义绘制、生成图片、属性文本、阴影路径与视觉快照必须按主题失效并重建；不得跨主题长期缓存已解析的静态颜色或渲染结果。

## 运行时切换

- 主题切换后，当前可见视图必须同步刷新背景、文本、图标、分割线、边框、阴影、渐变、自定义绘制和 bar appearance，不得仅保证下次重建页面正确。
- 异步图片、绘制任务或缓存回调必须核对当前主题代际，防止迟到的旧主题结果覆盖新主题。

## 验证

- 至少验证 Light、Dark 与运行时来回切换；页面同时涉及方向性时，覆盖 LTR Light、RTL Light、LTR Dark 和 RTL Dark。
- 检查背景、文本可读性、图标、分割线、边框、阴影、渐变、自定义绘制、bar appearance 和切换前后已存在视图。
- 交付时记录 `夜间模式：已适配`，或 `夜间模式：不适用（具体原因）`。
