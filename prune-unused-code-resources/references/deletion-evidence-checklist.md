# 删除证据检查清单

## 目录

- [置信度分级](#置信度分级)
- [代码动态入口](#代码动态入口)
- [资源动态入口](#资源动态入口)
- [媒体与动效](#媒体与动效)
- [工程与模块](#工程与模块)
- [删除记录模板](#删除记录模板)

## 置信度分级

### 高置信度，可进入删除批次

- CodeGraph、编译器或索引均无调用方。
- `rg` 未发现源码、配置、脚本、测试或 Interface Builder 引用。
- 不属于公开 API、协议要求、运行时注册或动态字符串入口。
- 所属 target 和资源 bundle 已确认。
- 有构建、测试或可复现流程覆盖删除影响。

### 中置信度，需要定向验证

- 仅由 feature flag、兼容分支、深链路或罕见错误路径使用。
- 可能由远程配置、路由、通知、序列化或运行时字符串引用。
- 资源存在同名、别名、namespace、设备或主题变体。
- 只有 Debug、Release、Extension、Widget、测试或特定地区使用。

### 低置信度，默认保留

- 公共框架 API 或可能由外部仓库调用。
- `@objc` / `dynamic` / Selector / KVC / KVO / 反射入口未排除。
- 服务端、运营后台或脚本可能下发资源名。
- 无法构建相关 target 或运行关键流程。
- 无法确定许可证、生成来源、资源所有权或业务用途。

## 代码动态入口

- [ ] `@objc`、`dynamic`、`perform(_:)`、Selector 与 Objective-C runtime。
- [ ] `NSClassFromString`、反射、依赖注入容器和插件注册。
- [ ] Notification name、URL route、deeplink、App Intent 和快捷指令。
- [ ] Codable key、数据库映射、迁移、归档和缓存恢复。
- [ ] 协议默认实现、泛型约束、继承 override 和 framework public/open API。
- [ ] XCTest 自动发现、UI 测试 launch argument 和快照注册。
- [ ] Shell、Ruby、Python、CI、代码生成和 Build Phase 脚本。
- [ ] feature flag、A/B 实验、远程配置与回滚开关。

## 资源动态入口

- [ ] `UIImage(named:)`、`UIColor(named:)`、`UINib`、Storyboard identifier。
- [ ] `Bundle.url/path`、路径拼接、文件扩展名替换和目录枚举。
- [ ] `AVPlayer`、`AVAudioPlayer`、视频预加载或播放列表配置。
- [ ] Lottie、SVGA、PAG 或自研动效框架按名称加载。
- [ ] Storyboard/Nib XML、`Info.plist`、entitlements 和 Copy Bundle Resources。
- [ ] R.swift 或其他资源生成器的源配置与生成成员。
- [ ] 远程 JSON、运营配置、服务端协议、下载缓存和 fallback 名称。
- [ ] 本地化 key、`.stringsdict`、Accessibility、RTL 与语言变体。

## 媒体与动效

- [ ] 音频的提示音、背景音、震动协同、后台与静音模式用途。
- [ ] 视频的封面、字幕、多码率、横竖屏和离线 fallback。
- [ ] 动效 JSON 引用的内嵌图片、字体、合成层和外部子资源。
- [ ] Asset Catalog 中的深浅色、分辨率、设备、gamut 和 appearance 变体。
- [ ] App Icon、Launch Screen、品牌审核素材和商店截图不按普通资源处理。
- [ ] 同内容不同压缩、尺寸、色彩空间或 alpha 的文件未被误判为重复。

## 工程与模块

- [ ] App、Framework、Extension、Widget、Test 与 Swift Package target 均已检查。
- [ ] Xcode 文件引用、target membership 和 Build Phase 与磁盘一致。
- [ ] `Package.swift` resources、`Bundle.module` 和测试 fixtures 已检查。
- [ ] Pods、Vendor、Generated、DerivedData 和外部子模块未被直接修改。
- [ ] Debug/Release、不同 scheme 与最低系统版本兼容分支已检查。

## 删除记录模板

| 项目 | 内容 |
|---|---|
| 符号或路径 | 待删除对象 |
| 所属 target | App / Extension / Package / Test |
| 静态证据 | CodeGraph、编译器、索引、`rg` 结果 |
| 动态证据 | runtime、配置、脚本、IB、服务端入口检查 |
| 风险 | 可能受影响的功能与环境 |
| 验证 | 构建、测试、播放或交互流程 |
| 结论 | 删除 / 保留 / 待确认 |
