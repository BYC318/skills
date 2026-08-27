# R.swift 集成与使用参考

## 目录

- [官方依据](#官方依据)
- [选择集成方式](#选择集成方式)
- [常用资源映射](#常用资源映射)
- [模块与 Bundle](#模块与-bundle)
- [常见故障](#常见故障)
- [审查清单](#审查清单)

## 官方依据

- 官方仓库：https://github.com/mac-cain13/R.swift
- 官方示例：https://github.com/mac-cain13/R.swift/blob/main/Documentation/Examples.md

官方 README 说明，从 Rswift 7 起推荐使用 Swift Package Manager。版本、产品名和插件名可能继续变化，执行集成前必须核对项目锁定版本对应的 README、Package manifest 与生成结果。

## 选择集成方式

### Xcode 项目使用 SPM

当前官方流程要求把 `RswiftLibrary` 加到使用资源的 target，并为该 target 添加 `RswiftGenerateInternalResources` Build Tool Plugin。不得因为其他 target 已配置插件就假设当前 target 可使用 `R`。

### `Package.swift` target

当前官方示例为 target 添加 `RswiftLibrary` product 和资源生成 plugin。根据目标模块的公开边界，在当前锁定版本实际提供的 internal/public plugin 中选择；不得为解决可见性问题盲目改成 public。

### CocoaPods

传统流程使用 `pod 'R.swift'`、生成脚本和声明的输出文件。严格遵循锁定版本文档，确认生成阶段顺序、输入输出和 `R.generated.swift` 的 target membership。生成文件通常应按仓库约定忽略，避免提交造成冲突。

除非用户明确要求集成或迁移依赖，不执行以上改动。

## 常用资源映射

以下仅用于识别资源类别，成员名称必须从实际生成结果读取：

```swift
let icon = R.image.settingsIcon()
let tint = R.color.indicatorHighlight()
let titleFont = R.font.acmeLight(size: 22)
let seedURL = R.file.seedDataJson()
let greeting = R.string.localizable.welcomeWithName("Alice")
let screen = R.storyboard.main.settingsController()
let view = R.nib.customView.firstView(owner: nil)
```

复用视图示意：

```swift
tableView.register(R.nib.textCell)
let cell = tableView.dequeueReusableCell(
    withIdentifier: R.reuseIdentifier.textCell,
    for: indexPath
)
```

不要照抄示例中的成员名或可选处理；以当前 target 生成签名为准。

## 模块与 Bundle

- App、Framework、Extension 和 Swift Package 的资源 bundle 可能不同。
- 每个 target 单独确认 R.swift 依赖、插件和资源归属。
- Swift Package 的非 R.swift 动态资源访问通常使用 `Bundle.module`，App 资源常见于 `Bundle.main`；不得互换猜测。
- 测试资源属于测试 bundle 时，使用测试 target 的正确访问方式，避免依赖宿主 App 的偶然加载行为。
- 同名资源跨模块存在时，优先保持模块边界清晰，不通过复制资源解决可见性。

## 常见故障

### 找不到 `R`

检查 target 是否链接 `RswiftLibrary`、是否添加生成 plugin 或脚本、生成步骤是否成功、源文件是否属于正确 target，以及模块 import 是否符合当前版本要求。

### `R` 中没有新资源

检查资源 target membership、asset namespace、文件扩展名、localization table、标识符、生成日志与构建缓存。先重新构建，再考虑清理派生数据。

### 生成成员不可访问

检查 internal/public 生成插件选择和模块边界。不要直接编辑生成访问级别，也不要把业务 API 无依据地扩大为 `public`。

### Nib 或复用标识未生成

检查 Nib、Storyboard 中的 custom class、module、Reuse Identifier、target membership，以及注册和出队是否指向同一资源。

### CI 拒绝执行插件

按照当前 Xcode、CI 服务和 R.swift 官方文档配置插件信任或验证策略。不要把本机全局绕过设置直接复制到所有 CI 环境。

## 审查清单

- [ ] 已确认受影响 target 的 R.swift 版本和集成方式。
- [ ] 没有手工编辑生成文件。
- [ ] 所有成员名和签名来自真实生成结果。
- [ ] 资源 target membership、namespace、table 与标识设置正确。
- [ ] 没有新增不必要的强制解包或强制类型转换。
- [ ] 动态字符串访问均有无法静态生成的理由。
- [ ] 构建、`R.validate()` 或相关资源测试已按风险执行。
- [ ] 未擅自新增、升级或切换依赖。
