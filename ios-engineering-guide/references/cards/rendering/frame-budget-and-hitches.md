---
id: frame-budget-and-hitches
tags: [UIKit, SwiftUI, Core Animation, 帧预算, 卡顿, Instruments]
status: verified
last_verified: 2026-09-10
---

# 帧预算与 Hitch

## 触发

- 滚动、拖拽、转场或动画不连贯。
- 修改主线程工作、布局、绘制或渲染代码。
- 讨论 60 Hz、120 Hz、FPS、掉帧或性能目标。

## 结论

- 60 Hz 和 120 Hz 的刷新间隔约为 16.7 ms 和 8.3 ms，但应用不能假定拥有完整间隔；系统和渲染服务器也要工作。
- 优化目标是让交互和运动按期交付，减少 hitch，而不是只追求某个平均 FPS。平均 FPS 可能掩盖少量但明显的长帧。
- Hitch 可能来自应用主线程提交阶段，也可能来自渲染阶段；先测量并分类，再改代码。

## 约束

- 主线程只承担 UI 状态提交和必须在主线程执行的框架调用；文件 I/O、图片解码和重计算移出关键交互路径。
- 连续交互期间避免排入“稍后再做”的非 UI 主线程任务；异步排队不代表不会撞上下一帧。
- 合并同一轮中的重复状态、布局和绘制失效，避免没有视觉变化的更新。
- 根据产品需要和设备能力选择刷新策略；高刷新率有更紧的预算，也可能增加耗电。

## 边界

- 一次刷新间隔只是理解问题的尺度，不是所有函数都必须满足的孤立 SLA。
- 没有屏幕更新触发时不存在“迟到的帧”；耗时后台工作应另用响应性、CPU、能耗等指标评价。
- 模拟器、Debug 构建和单一高端设备不能代表发布表现。

## 常见错误

- 只看平均 FPS，忽略 hitch 持续时间、发生位置和用户操作。
- 把所有 hitch 都归因于主线程，未区分 commit hitch 与 render hitch。
- 把任务包进 `Task {}` 或异步派发到主队列，就认为已经离开主线程。
- 为达到 120 FPS 无条件提高更新频率，增加无效绘制和耗电。

## 验证

- 在最低支持或性能较弱的真实设备上，以 Release/接近 Release 的配置复现真实手势和数据量。
- 用 Instruments 的 Hitches、Time Profiler 和 Core Animation 轨迹定位迟到帧；同时检查主线程是繁忙还是等待。
- 用 Xcode Organizer 的 Hitches 指标观察发布版本趋势；记录具体设备、系统、刷新率、操作和数据规模。
- 对比优化前后的 hitch rate、最差长帧和交互延迟；FPS 仅作为辅助证据。

## 来源

- [Understanding hitches in your app](https://developer.apple.com/documentation/xcode/understanding-hitches-in-your-app)
- [Improving app responsiveness](https://developer.apple.com/documentation/xcode/improving-app-responsiveness)
- [Understanding user interface responsiveness](https://developer.apple.com/documentation/xcode/understanding-user-interface-responsiveness)
- [Improving your app's rendering efficiency](https://developer.apple.com/documentation/xcode/improving-your-app-s-rendering-efficiency)
