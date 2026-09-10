---
id: launch-performance
tags: [launch, startup, time-to-first-frame, Instruments, MetricKit]
triggers:
  - 修改 AppDelegate、SceneDelegate 或应用入口
  - 首屏、初始化器、SDK 注册或数据库迁移
  - 冷启动慢、白屏、启动 watchdog 或首屏不可交互
applies_to: [UIKit, SwiftUI, iOS]
status: verified
last_verified: 2026-09-10
---

# 启动与首屏性能

## 稳定结论

- Xcode Organizer 与系统指标以 time to first frame/draw 衡量启动：从用户启动应用到启动画面后的首帧绘制完成，包括首屏视图绘制成本。
- 首帧不等于可用。首帧之后到内容可读、控件可交互的准备工作会影响体感，应使用自定义 signpost 单独测量。
- 启动优化的核心是缩短主线程关键路径、简化首屏并延后非必要工作；异步化本身不能减少总工作量，也不能保证不占主线程。
- 启动数据分布受设备、系统、应用状态和预热影响，不能用一次模拟器结果代表真实用户。

## 编码约束

- 启动路径只完成首帧必需的依赖装配与最小状态恢复；分析、预取、非首屏 SDK 和维护任务延后到首帧后或实际需要时。
- 禁止在应用入口和首屏主线程执行同步网络、磁盘 I/O、大型解码、全库扫描或可延后的迁移。
- 首屏视图层级保持必要且简单；避免在首帧创建屏外页面、全量 Cell 或昂贵自定义绘制。
- 必需数据尚未就绪时展示明确且可替换的初始状态；不要用同步等待换取“首帧即完整”。
- 为应用自身的关键阶段设置稳定的 `os_signpost` 区间，并区分进程启动、首帧、首屏内容就绪和首次可交互。
- 延后工作应有调度与取消策略，避免首帧后同时爆发造成紧接着的卡顿和耗电峰值。

## 边界

- 启动模式与测量术语会随系统工具演进；使用当前 Xcode Instruments、Organizer 和 MetricKit/系统指标提供的定义。
- 冷启动、温启动、恢复和系统预热不是同一种场景，应分别观察，不能混成单一平均值。
- 不为追求首帧数字隐藏真实等待。若用户必须等核心内容才能操作，仍需优化并报告“可交互时间”。

## 常见错误

- 只测 Debug 模拟器的一次启动，或只比较平均值。
- 在 `didFinishLaunching` 中顺序初始化所有 SDK。
- 把工作放进 `Task {}` 后就认定不会阻塞主 actor。
- 首帧展示空壳，随后在主线程集中布局、解码和刷新，指标好看但体验仍卡。
- 优化前后测试设备、构建配置、数据集或启动状态不一致。

## 验证

- 用 Release/接近发布配置在最低支持档真机重复测量，分别记录典型值与尾部值（例如 p50、p90）。
- 使用 Instruments 的 App Launch / Time Profiler 检查首帧前主线程关键路径、动态库加载和初始化热点。
- 用 Xcode Organizer 查看发布版本与设备分布；需要自有采集时采用当前系统提供的启动指标 API。
- 用 Points of Interest/signpost 测量首帧后的内容就绪和首次可交互阶段，并对比优化前后的同条件样本。

## 官方来源

- [Apple: Reducing your app’s launch time](https://developer.apple.com/documentation/xcode/reducing-your-app-s-launch-time)
- [Apple: Improving app responsiveness](https://developer.apple.com/documentation/xcode/improving-app-responsiveness)
- [Apple: TimeToFirstDrawMetric](https://developer.apple.com/documentation/metrickit/timetofirstdrawmetric)
- [Apple: Diagnosing performance issues early](https://developer.apple.com/documentation/xcode/diagnosing-performance-issues-early)
