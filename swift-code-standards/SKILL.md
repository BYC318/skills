---
name: swift-code-standards
description: 统一 Swift 代码的声明、初始化、成员 API、调用链换行与 Combine 订阅风格，优先使用 Then 配置变量和属性、在 Then 闭包中使用 `$0`，将仅返回值的无参数方法声明为只读计算属性，在行长限制内保持表达式紧凑，并使用 `sink(with:)` 访问订阅所属对象。创建、修改、格式化、重构或审查 Swift 文件中的变量、属性、UIKit/SwiftUI 界面、用户可见文本、方向性布局、颜色、图片、图层、协议成员、无参数方法、链式调用或 Combine 订阅时使用此技能。
---

# Swift 代码规范

## UI 环境适配门禁

用户未显式提及多语言、RTL 或夜间模式时，也必须根据实际改动内容主动判定，不得根据文件名或当前设计稿单一状态省略适配。

- 改动涉及用户可见文本、本地化参数、布局、对齐、边距、排列、方向图标、渐变、手势或运行时语言切换时，实现前必须完整阅读 [多语言与 RTL 适配规则](references/localization-and-rtl.md)。
- 改动涉及颜色、图片、渐变、边框、阴影、模糊、`CALayer`/`CGColor`、自定义绘制、视觉缓存或运行时主题切换时，实现前必须完整阅读 [主题与夜间模式适配规则](references/theme-and-dark-mode.md)。
- 同一改动同时命中两类条件时，两份规则都必须阅读并联合验证。纯 Model、网络、存储或无 UI 算法改动可判定为不适用，但交付时必须给出不适用的具体依据。

## 核心规则

声明变量或属性时，只要当前类型支持 Then 且需要在初始化阶段配置实例，就使用 `.then { ... }`。

在 Then 闭包内部始终使用简写参数 `$0` 访问被配置实例，不得为该参数声明 `view`、`label`、`button` 等名称。

```swift
private let titleLabel = UILabel().then {
    $0.textColor = .label
    $0.numberOfLines = 0
}
```

不得写成：

```swift
private let titleLabel: UILabel = {
    let label = UILabel()
    label.textColor = .label
    label.numberOfLines = 0
    return label
}()

private let titleLabel = UILabel().then { label in
    label.textColor = .label
    label.numberOfLines = 0
}
```

`lazy` 属性同样遵循该规则：

```swift
private lazy var actionButton = UIButton(type: .system).then {
    $0.setTitle(title, for: .normal)
    $0.addTarget(self, action: #selector(handleAction), for: .touchUpInside)
}
```

## 返回值成员

成员只读取当前状态或派生值、没有参数且没有副作用时，优先声明为只读计算属性，不得声明为无参数方法。

```swift
protocol UserPresenting {
    var displayName: String { get }
}

var displayName: String {
    profile.nickname.trimmingCharacters(in: .whitespacesAndNewlines)
}
```

不得写成：

```swift
func displayName() -> String {
    profile.nickname.trimmingCharacters(in: .whitespacesAndNewlines)
}
```

仅当调用表示动作或过程、存在副作用、需要显式传达较高计算成本，或者受 `async`、`throws` 等方法语义约束时，保留无参数 `func`。

## Combine 订阅

当前 target 提供 `Publisher.sink(with:)`，并且订阅闭包需要访问所属对象时，始终使用 `sink(with: self)`。将闭包接收的所属对象命名为 `this`，直接调用其成员；不得手写 `[weak self]`、`guard let self` 或 `self?`。

```swift
baseViewModel.loadingPublisher.removeDuplicates().sink(with: self) { this, isLoading in
    this.renderLoading(isLoading)
}.store(in: &cancellables)

baseViewModel.toastPublisher.sink(with: self) { this, message in
    this.showToast(message)
}.store(in: &cancellables)
```

不得写成：

```swift
baseViewModel.toastPublisher.sink { [weak self] message in
    self?.showToast(message)
}.store(in: &cancellables)
```

需要同时处理完成事件和输出值时，使用项目提供的对应重载，并在两个闭包中都将所属对象命名为 `this`：

```swift
publisher.sink(with: self) { this, completion in
    this.handle(completion)
} receiveValue: { this, value in
    this.handle(value)
}.store(in: &cancellables)
```

## 换行与调用链

以当前仓库的 formatter 或 linter 行长限制为准。表达式、函数调用和链式调用能够在限制内清晰放入一行时，保持在同一行；不得仅为视觉对齐而将 receiver、每个点调用或结尾的 `.store(...)` 机械拆成多行。

闭包包含执行语句时，保持闭包体正常缩进和换行，但尽量将闭包前的调用链放在同一行，并将闭包后的短链式调用接在右花括号之后：

```swift
publisher.removeDuplicates().sink(with: self) { this, value in
    this.render(value)
}.store(in: &cancellables)
```

只有整行会超过限制、表达式结构复杂或紧凑写法明显降低可读性时才换行。需要换行时按语义边界进行最少量拆分，不得默认采用每个链式操作各占一行的格式。

## 适用边界

- 先检查受影响 target 是否已链接 Then，以及当前类型是否支持 `.then`。
- target 已链接 Then 但当前文件尚未导入时，按项目现有方式添加 `import Then`。
- 除非用户明确要求修改依赖，否则不得为了套用写法而新增 Then 依赖。
- 实例无需任何初始化配置时，直接声明，不得添加空的 `.then {}`。
- 常量值、依赖注入结果、工厂方法返回值、闭包属性和计算属性不适合使用 Then 时，保留语义最直接的写法。
- Then 闭包中的 `$0` 仅代表被配置实例；确需访问所属对象时可以使用 `self`，不得用命名闭包参数替代 `$0`。
- 不得仅为改成 Then 而改变初始化顺序、懒加载时机、可见性、可变性或其他运行时语义。
- 不得将执行动作、改变状态、触发 I/O、生成一次性结果或计算成本明显较高的方法伪装成属性访问。
- 先确认受影响 target 已提供语义等价的 `sink(with:)`，并核实其内部不会强持有传入对象；不得根据其他项目的同名 API 猜测捕获语义。
- 订阅闭包不访问所属对象时，使用普通 `sink`，不得为套用规范而传入无用的 `self`。
- 当前 target 不具备 `sink(with:)` 时，遵循该 target 的现有生命周期约定；除非用户明确要求，不得仅为统一写法而新增或复制扩展。
- `sink(with:)` 规则仅适用于对应 Combine 扩展，不得机械套用到 `Task`、GCD、代理回调或其他闭包 API。
- 改写订阅时保持 publisher 链、调度器、完成处理、取消存储和生命周期语义不变。
- 紧凑排版不得违反当前仓库的行长、缩进、formatter 或 lint 规则，也不得将复杂控制流强行压缩成难以阅读的单行代码。

## 修改与审查

1. 阅读相邻 Swift 代码并确认当前 target 的 Then 集成方式。
2. 先执行 UI 环境适配门禁，按改动内容阅读必需的多语言/RTL 或主题规则；不适用时记录依据。
3. 新增声明直接采用 `.then { $0... }` 风格。
4. 修改现有声明时，在不改变行为的前提下，将可等价转换的立即执行初始化闭包改为 Then。
5. 将仅返回值且无参数、无副作用的成员声明为只读计算属性；同步更新协议要求、调用点和测试。
6. 将访问所属对象的 Combine `sink` 订阅改为 `sink(with: self)`，并在闭包中通过 `this` 访问该对象。
7. 合并在行长限制内被过度拆分的表达式和调用链，保留闭包体、复杂参数和必要语义边界的可读换行。
8. 审查时指出可使用 Then 却仍采用临时变量、立即执行闭包或命名 Then 参数的声明，应为只读计算属性的无参数方法，可用 `sink(with:)` 却手写 `[weak self]` 的 Combine 订阅，以及不必要的链式换行。
9. UI 改动交付时明确记录 `RTL：已适配/不适用（原因）` 和 `夜间模式：已适配/不适用（原因）`，并按规则覆盖适用的 LTR/RTL 与 Light/Dark 组合。
10. 完成后检查闭包捕获、初始化时机、对象配置顺序、订阅取消、行长和 API 语义是否保持不变，并按改动风险执行构建或相关测试。
