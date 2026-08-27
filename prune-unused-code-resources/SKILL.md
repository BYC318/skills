---
name: prune-unused-code-resources
description: 审计并安全清理 iOS、Swift 和 Objective-C 项目中的死代码、不可达分支、无调用类型与成员、废弃 API、过期兼容实现，以及未引用的图片、颜色、字体、本地化、音频、视频、Lottie、SVGA、PAG、JSON 动效、Nib、Storyboard 和其他 bundle 资源。用于用户要求删除垃圾代码、无效代码、过时代码、重复实现、未使用文件或瘦身安装包时；必须先排除动态加载、Objective-C runtime、Selector、Interface Builder、远程配置、脚本、测试、反射与字符串资源引用，禁止仅凭一次文本搜索批量删除。
---

# 清理无用代码与资源

## 核心规则

- 把扫描结果视为候选项，不把“未搜索到引用”直接视为可删除证据。
- 至少结合符号调用关系、工程配置与资源引用、动态运行入口三类证据判断；证据不足时保留并列为待确认项。
- 先建立可工作的构建与测试基线，再小批量删除并逐批验证。
- 保护用户已有改动。先检查工作区状态，不覆盖、回滚或顺带删除不属于当前清理范围的内容。
- 不使用 `git clean`、`find -delete`、宽泛 `rm -rf` 或按扩展名全量删除等破坏性方式。
- 不直接修改生成代码、Pods、第三方 Vendor、DerivedData 或构建产物；应修改生成源或依赖配置。
- 删除是最后一步。对废弃 API 先完成等价迁移并验证，再移除旧实现。

## 工作流

### 1. 确定范围与基线

1. 阅读仓库指令；若仓库存在 `.codegraph/`，在读取或搜索代码前先使用 CodeGraph。
2. 记录 `git status`，识别用户已有修改、生成文件、Vendored code 与目标外目录。
3. 确认要清理的 target、构建配置、平台、语言和资源类型。
4. 构建受影响 target 并运行已有相关测试，记录清理前已存在的失败和警告。
5. 未经用户要求，不把局部清理扩大为全仓库重构、依赖升级或公共 API 破坏。

### 2. 盘点代码候选项

- 使用 CodeGraph 调用路径、编译器诊断、IDE 索引和 `rg` 交叉检查类型、方法、属性、协议实现与文件引用。
- 区分真正不可达代码、仅当前 target 未引用的代码、测试辅助代码、示例代码和外部模块公开 API。
- 检查 `@objc`、`dynamic`、Selector、通知、KVC/KVO、`NSClassFromString`、反射、依赖注入注册、路由表、序列化、脚本和测试发现机制。
- 对 `@available`、兼容分支和 feature flag，确认最低系统版本、灰度配置与回滚需求后再删除。
- 对 deprecated API，先替换调用方并保持行为、错误、线程和生命周期语义，再删除旧适配层。

### 3. 盘点资源候选项

检查图片、Asset Catalog、颜色、字体、本地化、音频、视频、Lottie/SVGA/PAG/JSON 动效、Nib、Storyboard、模型和任意 bundle 文件。

- 检查 Swift/Objective-C 源码、Storyboard/Nib、`Info.plist`、entitlements、Build Phases、Package resources、Copy Bundle Resources 和测试代码。
- 检查 `UIImage(named:)`、`UIColor(named:)`、`Bundle` 查询、文件路径拼接、播放器或动效库按字符串加载、远程配置下发名称与服务端协议。
- 检查 App Icon、Launch Screen、On-Demand Resources、Asset tags、设备变体、深浅色变体、本地化变体和辅助功能资源。
- 项目已集成 R.swift 时，同时加载 `$rswift-resource-references`，用实际生成引用辅助审计；不得仅依据生成文件缺少成员就删除资源。
- 哈希相同或视觉相同只表示“可能重复”，不表示名称、bundle、尺寸、压缩或业务语义可互换。

### 4. 建立删除证据

为每个候选项记录：

- 路径或符号、所属 target、类型和用途推断。
- 静态调用与文本引用结果。
- 工程配置、Interface Builder、脚本和生成器结果。
- 动态入口与运行时检查结果。
- 置信度、删除影响、验证方式和回滚办法。

只有在所有相关入口均已排除、行为有测试或可复现流程覆盖时标记为“可删除”。读取 [references/deletion-evidence-checklist.md](references/deletion-evidence-checklist.md) 获取动态入口和资源类别检查表。

### 5. 小批量清理

- 优先删除叶子节点：无调用私有成员、已替代适配层、完全未引用的独立资源。
- 同步移除 Xcode 文件引用、target membership、Build Phase 条目、Package resource 声明和对应测试夹具。
- Asset Catalog 中删除完整且确认无用的 `.imageset` / `.colorset`，不要破坏仍使用的变体或 namespace。
- 删除本地化 key 时检查所有语言和 `.stringsdict`；删除媒体时检查封面、字幕、配置和预加载清单。
- 一批只处理一个紧密相关的功能或资源组，便于定位回归和恢复。
- 若清理导致 UIKit 层级或布局调整，同时加载并遵循 `$uikit-layout-standards`。

### 6. 验证

1. 重新生成 R.swift 或其他派生资源索引，但不手改生成文件。
2. 构建所有受影响 target、Extension、Test Bundle 与必要的 Debug/Release 配置。
3. 运行单元测试、UI 测试、快照测试和资源验证测试。
4. 对音频、视频和动效执行真实播放、暂停、循环、后台恢复、弱网或本地缺失等定向流程。
5. 对本地化、深浅色、设备规格、RTL 和辅助功能资源做抽查。
6. 再次扫描悬空工程引用、残留生成成员、空目录、失效配置和新增编译警告。
7. 无法获得充分运行证据时，不删除高风险候选项，并明确列出剩余风险。

### 7. 交付

报告已删除的代码与资源、每类删除依据、构建和测试结果、包体变化（若已测量）、保留的可疑项及原因。不要把工具零引用报告等同于已证明安全。

## 完成标准

- 旧行为和必要兼容性保持不变。
- 不存在由清理引入的编译错误、运行时资源缺失或 Interface Builder 崩溃。
- 没有误删动态、远程配置、反射、测试或跨模块入口。
- 工程文件、生成引用、Bundle 配置和文件系统保持一致。
- 所有删除均有可复核证据和验证结果。
