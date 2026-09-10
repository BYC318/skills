---
id: performance-evidence
tags: [Instruments, MetricKit, 性能, 验证, 真机]
status: verified
last_verified: 2026-09-10
---

# 性能证据边界

## 触发条件

- 任务目标包含更省内存、更省电、更快、更流畅、更高帧率或更自然。
- 准备声称性能问题已修复或优化完成。

## 稳定结论

性能是特定场景下的可观察结果。代码看起来更轻、构建通过或模拟器可运行都不是性能改善证据。

## 验证设计

1. 固定用户路径、测试数据、设备、系统版本、构建配置和网络条件。
2. 记录优化前基线；选择与问题直接对应的指标。
3. 一次只改变少量可归因因素，并检查功能和资源权衡。
4. 在支持范围内的较低性能真机复测；模拟器只作功能诊断。
5. 同时报告结果、方差、未验证项和回归风险。
6. 对稳定、可重复的关键路径建立 XCTest 性能基线；本地测试用于阻止已知回归，不能替代真机 Instruments 和发布后的分布数据。

## 证据匹配

- 内存：Memory Graph、Allocations、Leaks、VM Tracker、Organizer/MetricKit、Jetsam 报告。
- CPU/卡顿：Time Profiler、CPU Profiler、Hangs、Hitches、Organizer/MetricKit。
- 渲染：Core Animation/Hitches、真实交互录制和帧截止时间。
- 启动：App Launch 模板、Organizer/MetricKit、首帧/可交互时间。
- 耗电：Energy Log、Power Profiler、后台与网络行为记录。
- 自动回归：按风险选择 `XCTClockMetric`、`XCTMemoryMetric`、`XCTHitchMetric`、`XCTOSSignpostMetric`、`XCTStorageMetric` 或 `XCTApplicationLaunchMetric`，并固定测试输入与测量区间。
- 线上趋势：MetricKit/Organizer 按 App 版本、系统和设备族观察分布与变化；单个 payload 或少量设备样本不能代表全部用户。

## 常见错误

- 只给优化后数据，没有基线。
- 只测一次或只测高性能新设备。
- 用平均 FPS 掩盖短时 hitch。
- 把内存下降但 CPU、I/O 或耗电明显上升称为无条件优化。
- 把静态审计、测试、构建、模拟器和真机证据混成同一结论。
- 用 XCTest 的一次通过宣称线上性能已改善，或用 MetricKit 聚合数据替代可复现的本地根因分析。

## 官方来源

- [Improving app responsiveness](https://developer.apple.com/documentation/xcode/improving-app-responsiveness)
- [Understanding hitches in your app](https://developer.apple.com/documentation/xcode/understanding-hitches-in-your-app)
- [Reducing your app's memory use](https://developer.apple.com/documentation/xcode/reducing-your-app-s-memory-use)
- [Performance Tests](https://developer.apple.com/documentation/xctest/performance-tests)
- [Monitoring app performance with MetricKit](https://developer.apple.com/documentation/metrickit/monitoring-app-performance-with-metrickit)
- [Recording performance data](https://developer.apple.com/documentation/os/recording-performance-data)
