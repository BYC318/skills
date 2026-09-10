---
id: layout-drawing-offscreen
tags: [UIKit, Auto Layout, Core Graphics, Core Animation, 绘制, 离屏渲染]
status: verified
last_verified: 2026-09-10
---

# 布局、绘制与离屏渲染

## 触发

- 修改 `layoutSubviews()`、约束、`draw(_:)`、`setNeedsLayout()` 或 `setNeedsDisplay()`。
- 使用圆角、阴影、遮罩、模糊、透明合成或自定义 Core Graphics 绘制。
- Instruments 显示 commit/render hitch、频繁视图更新或 GPU 压力。

## 结论

- 优先减少无意义的布局和绘制失效，并缩小实际更新范围；不是简单地“少用 Auto Layout”或“禁止离屏渲染”。
- `draw(_:)` 处在帧更新路径，应使用预先准备的数据，只绘制需要更新的区域，不做 I/O 或复杂计算。
- 离屏渲染是实现某些视觉效果的技术路径，不等于缺陷；只有测得它造成目标场景的 render hitch 或资源压力时才优化。

## 约束

- 仅在几何或内容确实变化时调用失效 API；避免在 `layoutSubviews()` 内无条件再次使布局失效。
- 自定义绘制尊重传入的脏矩形；可复用且不变的昂贵计算应在绘制前准备并有明确失效条件。
- 对约束或视图树做批量变更后再提交一次布局；同步 `layoutIfNeeded()` 必须有可解释的即时布局或动画需求。
- 保持视图层级和透明叠加满足实际设计即可；发现热点后再比较简化层级、预合成资源或调整效果的收益与画质成本。
- 动画期间避免每帧重建复杂路径、阴影或大量约束；可等价表达时评估使用已支持动画的属性，但以测量为准。

## 边界

- 圆角、阴影、遮罩、透明或 `shouldRasterize` 的成本随内容、尺寸、缩放和系统实现变化，不能仅凭属性组合判定性能问题。
- 栅格化可能减少重复绘制，也会增加缓存、缩放模糊与失效成本；动态内容通常更易抵消收益。
- Auto Layout 本身不是卡顿证据；需要由调用次数、耗时和具体约束更新路径证明。

## 常见错误

- 在 `draw(_:)` 中读取文件、解析数据、创建大图或执行重复文本布局。
- 每帧调用 `setNeedsDisplay()`，即使内容没有变化。
- 用“离屏渲染颜色提示”直接判定必须重写，而不看 hitch 和 GPU 时间。
- 为消除一次测量热点永久开启 `shouldRasterize`，却不设置正确 scale 或评估内容失效。
- 在布局回调里反复改约束，形成多轮 layout pass。

## 验证

- 使用 Xcode 的 Flash Updated Regions 检查无视觉变化的更新区域。
- 在真实设备上用 Instruments 的 Hitches、Time Profiler/Core Animation 相关轨迹区分 commit 与 render 阶段瓶颈。
- 对同一交互、数据和设备进行前后对比，记录布局/绘制调用次数、hitch 和画质；不要只凭 Debug 颜色判断。
- 覆盖动态内容、不同 scale、旋转/尺寸变化和长时间滚动，防止缓存失效或内存成本被短测试掩盖。

## 来源

- [Improving your app's rendering efficiency](https://developer.apple.com/documentation/xcode/improving-your-app-s-rendering-efficiency)
- [Improving app responsiveness](https://developer.apple.com/documentation/xcode/improving-app-responsiveness)
- [UIView](https://developer.apple.com/documentation/uikit/uiview)
- [setNeedsDisplay(_:)](https://developer.apple.com/documentation/uikit/uiview/setneedsdisplay%28_%3A%29)
- [Understanding hitches in your app](https://developer.apple.com/documentation/xcode/understanding-hitches-in-your-app)
