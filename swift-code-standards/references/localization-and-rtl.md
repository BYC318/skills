# 多语言与 RTL 适配规则

## 适用判定

改动用户可见文本、本地化参数、日期/数字格式、布局方向、对齐、边距、排列、方向图标、渐变、手势或运行时语言切换时必须执行本规则。纯 Model、网络、存储或无 UI 算法可判定为不适用，但必须说明依据。

## 实现前

1. 检索并复用项目已有的本地化访问器、语言状态源、切换通知/投影、root 重建或页面刷新机制，不得新增平行的语言单例。
2. 盘点本次改动中的可见文本、方向性几何、图标/图片、自定义绘制、手势和顺序语义；分清“视觉镜像”与“业务顺序”。

## 唯一语言与方向权威

- App 自有 UI 的文案、`Locale`、语义方向、文本对齐、方向资源和自定义绘制必须全部由项目现有的 App 内语言状态源决定，不得读取或混用 `Locale.preferredLanguages`、`Locale.current`、`Bundle.preferredLocalizations`、iOS Per-App Language、进程启动语言或未完成注入的继承方向。
- App 内语言状态源必须直接提供或投影 `Locale`、`UISemanticContentAttribute` 和 `UIUserInterfaceLayoutDirection`；调用方消费该投影，不得自行维护语言代码与 RTL 语言清单。
- `effectiveUserInterfaceLayoutDirection` 只允许在 View 已挂载且 App 方向已经注入后读取最终几何结果，例如计算渐变端点、自定义绘制或验证布局；不得把它反向用作 App 语言、文本对齐或方向资源的权威来源。
- App 自有页面不得因系统语言与 App 内语言暂时相同而省略显式方向配置，也不得为 `.natural`、系统自动镜像或进程语言保留回退分支。

## 文本与格式

- 用户可见文本必须经项目本地化系统读取；不得在视图、控制器或 ViewModel 中新增硬编码展示文案。
- 参数化文案、复数和语序变化使用完整本地化模板，不得通过字符串拼接假定语序。
- 日期、数字、货币和列表格式使用项目指定的 `Locale` 与 Foundation formatter，不得默认依赖设备当前语言或手工拼接。
- 容器必须允许文案伸缩或换行；不得仅以当前短文案固定宽度。
- App 自有文本控件必须同时显式设置 App 语言投影出的 `semanticContentAttribute` 和实际对齐。非居中正文、标题、说明、错误、占位与规则文案在 LTR 下使用 `.left`，在 RTL 下使用 `.right`；不得使用 `.natural`、`.unspecified` 或继承方向代替显式配置。设计明确要求物理居中的文本可以使用 `.center`，但仍必须设置 App 语言对应的 `semanticContentAttribute`。

```swift
let language = AppLanguageCenter.shared.current
let alignment: NSTextAlignment = language.userInterfaceLayoutDirection == .rightToLeft ? .right : .left

label.semanticContentAttribute = language.semanticContentAttribute
label.textAlignment = alignment
```

## RTL 布局与视觉

- 表达方向性几何时使用 `leading`/`trailing`、`NSDirectionalEdgeInsets` 和 directional layout margins；文本对齐遵循前述 App 语言显式规则，不得使用 `.natural`。只有物理坐标确实不随语义方向改变时才在约束或几何中使用 `left`/`right`，并说明原因。
- 从项目 App 内语言状态源读取其方向投影；不得根据语言代码、字符串内容、系统语言或手写语言清单推测 RTL。`UIView.userInterfaceLayoutDirection(for:)` 只用于把该状态源已有的语义投影转换为 UIKit 方向值。
- 箭头、chevron、方向渐变和前进/后退图标按语义镜像，优先复用 Asset Catalog 方向变体、`imageFlipsForRightToLeftLayoutDirection` 或项目既有解析器。Logo、头像、照片、文字图、媒体播放和无方向图标不得机械镜像。
- 当 App 内语言可能与进程或 iOS Per-App Language 不一致时，不得依赖 `chevron.backward`、系统返回项或图片容器的自动镜像来表达 App 自有方向；按 App 方向投影明确选择物理图形与物理栏位，并固定图片容器方向，避免 UIKit 二次翻转。
- 自定义绘制、渐变端点、转场和滑动手势必须根据当前布局方向计算；不得把 LTR 坐标常量直接复用到 RTL。
- RTL 只镜像展示与交互方向；不得自动反转 Tab 索引、服务端数组、领域枚举、时间顺序、数值区间或业务排序。

## UIKit 系统内容边界

- `window.semanticContentAttribute` 负责当前视图树，Appearance Proxy 只影响符合 UIKit Appearance 时机的实例；二者都不能保证改写 UIKit 已按进程语言生成的导航图形、Password AutoFill 提示或其他系统内容。
- 系统内容允许保持系统语言时，必须把它与 App 自有 UI 的语言责任明确分开。产品要求其严格跟随 App 内语言时，使用项目自有控件或明确的展示实现，不得声称设置 Window 方向即可改变系统进程语言。
- App 内切换语言不能修改 iOS Per-App Language 或当前进程语言；必须通过项目既有 root 重建或页面刷新，让全部 App 自有控件重新消费同一 App 语言快照。

## 运行时切换

- 语言切换后必须重新解析可见文本、layout direction、方向资源与自定义绘制。按项目已有机制重建 root 或刷新当前视图，不得要求重启 App 来掩盖未刷新状态。
- 异步回调或缓存不得在切换后重新发布旧语言文案或旧方向投影；必要时用代际、任务取消或当前状态校验拒绝迟到结果。

## 验证

- 至少验证 App LTR/系统 LTR、App RTL/系统 RTL、App LTR/系统 RTL、App RTL/系统 LTR 四种组合，并覆盖初始展示与运行时来回切换。系统维度可通过独立 Simulator、iOS Per-App Language 或等价的进程语言测试环境构造。
- 检查文本更新、截断/换行、safe area、边距、对齐、方向图标、渐变/绘制、手势与业务顺序。
- 测试必须直接断言关键文本控件的 `semanticContentAttribute` 与 `textAlignment`，并断言方向资源请求使用 App 语言投影；仅凭正常语言组合截图或 `window.effectiveUserInterfaceLayoutDirection` 不足以证明来源隔离。
- 交付时记录 `RTL：已适配`，或 `RTL：不适用（具体原因）`。
