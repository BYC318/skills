---
name: rswift-resource-references
description: 使用 R.swift 为 iOS、UIKit、SwiftUI、App target 和 Swift Package target 生成、迁移、维护并审查类型安全的资源引用。添加或修改图片、颜色、字体、本地化字符串、文件、Storyboard、Segue、Nib、UITableView/UICollectionView 复用标识时，以及诊断 R.generated.swift、R 类型不可见、Build Tool Plugin、Build Phase、target membership、Bundle 或 CI 生成失败时使用。必须先确认目标 target 实际采用的 R.swift 版本与集成方式，不得猜测生成 API、手改生成文件或擅自添加依赖。
---

# R.swift 资源引用

## 核心规则

- 先确认受影响 target 已集成的 R.swift 版本、依赖管理方式和生成插件，再编写 `R.*` 调用。
- 以实际生成的符号和类型为准。通过构建、IDE 自动补全或只读检查生成结果确认名称，不得凭资源文件名猜测 camelCase 结果。
- 不得编辑 `R.generated.swift` 或 Build Tool Plugin 的派生输出；修改源资源或生成配置后重新构建。
- 除非用户明确要求修改依赖，不得新增、移除、升级或切换 R.swift 的集成方式。
- 仅引用当前 target 或模块真实拥有的资源；不得用错误的 `Bundle.main` 掩盖 target membership 或 package resource 问题。
- 对运行时动态资源名保留受控的 `Bundle` / UIKit 查询，并说明 R.swift 无法生成静态引用的原因。

## 工作流

### 1. 检查项目与 target

1. 阅读仓库指令；若仓库存在 `.codegraph/`，先用 CodeGraph 定位资源调用和受影响符号。
2. 检查 `Package.swift`、`Package.resolved`、Xcode `project.pbxproj`、`Podfile`、`Podfile.lock`、Build Phases、Build Tool Plug-ins 和 import。
3. 确认资源属于 App、Framework、Extension、Test Bundle 还是 Swift Package target。
4. 查找现有 `R.image`、`R.color`、`R.string` 等调用及生成文件，遵循同一 target 的既有写法。
5. 如果 target 未集成 R.swift，不得直接写无法编译的 `R.*`；说明需要集成，或在用户未授权依赖改动时沿用项目现有资源访问规范。

### 2. 添加或调整资源

- 使用表达业务语义、稳定且易搜索的资源名称，避免无意义缩写和重复类型后缀。
- 正确设置 asset catalog namespace、localization table、Nib/Storyboard 标识、reuse identifier 和 target membership。
- 重命名资源时同步处理所有调用方、本地化变体、测试和 Interface Builder 引用。
- 不把敏感信息或环境密钥放入可打包资源。

### 3. 使用生成引用

仅在生成结果确实提供对应成员时使用以下类别：

- 图片：`R.image.<name>()`
- 颜色：`R.color.<name>()`
- 字体：`R.font.<name>(size:)`
- 本地化：`R.string.<table>.<key>(...)`
- 文件：`R.file.<name>()`
- Storyboard、Segue、Nib：`R.storyboard`、`R.segue`、`R.nib`
- 复用视图：`R.reuseIdentifier`

具体成员名、参数标签、返回可选性和可见性必须以当前版本的生成代码为准。不要为了消除编译错误添加强制解包或 `as!`；先修正资源、标识、target membership 或生成配置。

### 4. 处理 UIKit 复用资源

- 只在 R.swift 已生成对应 Nib 或复用标识时调用 `register(R.nib...)` 和 `dequeueReusableCell(withIdentifier: R.reuseIdentifier...)`。
- 确保 Interface Builder Identifier 与注册、出队使用的标识一致。
- 纯代码 cell 若没有可生成的资源条目，遵循项目既有类型安全复用方案，不伪造 `R.reuseIdentifier` 成员。
- 涉及视图布局时同时加载并遵循 `$uikit-layout-standards`。

### 5. 验证

1. 重新构建受影响 target，确认生成步骤在 Compile Sources 前或由正确的 Build Tool Plugin 执行。
2. 验证新增、删除、重命名的资源均反映到生成 API。
3. 在测试 target 可访问且当前版本支持时，添加或运行 `XCTAssertNoThrow(try R.validate())`；不要在 Release 启动路径无条件执行完整验证。
4. 运行相关单元测试、UI 测试或快照测试，检查本地化参数、资源 bundle、暗色模式和设备变体。
5. 搜索受影响范围内遗留的字符串资源访问；仅迁移能被静态生成且属于本次任务的调用。
6. 交付时说明 target、R.swift 集成方式、生成与测试结果，以及保留动态字符串访问的原因。

## 集成与排错参考

需要新增集成、区分 SPM 与 CocoaPods、处理模块可见性或排查生成失败时，读取 [references/integration-and-usage.md](references/integration-and-usage.md)。
