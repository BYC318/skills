---
id: natural-interruptible-animation
tags: [UIKit, UIViewPropertyAnimator, 交互式动画, 弹簧, Reduce Motion]
status: verified
last_verified: 2026-09-10
---

# 自然、可中断与交互式动画

## 触发

- 创建页面转场、展开收起、拖拽跟随、手势返回或状态切换动画。
- 用户连续操作时动画跳变、抢操作、突然反向或结束状态错误。
- 调整动画时长、曲线、弹簧参数或无障碍动效。

## 结论

- 自然感来自输入与画面及时对应、位置和速度连续、结果可预测；不等于统一使用某个时长或弹簧参数。
- 用户可以在动画中再次操作时，应设计中断、反向、续播和结束状态，而不是堆叠新的 fire-and-forget 动画。
- `UIViewPropertyAnimator` 支持暂停、反向、修改进度和带新 timing parameters 继续，适合可中断与交互式 UIKit 动画。

## 约束

- 明确模型状态、视觉状态和动画状态的单一所有者；中断后从当前呈现位置继续，并最终收敛到合法模型状态。
- 手势进度应有边界，结束时根据进度与手势速度共同决定完成或取消；转场取消后恢复交互和层级。
- 对可重复触发的动作，复用/接管现有 animator 或先规范化旧状态，避免多个 animator 同时写同一属性。
- 动画块中只提交可动画属性变化；昂贵计算、I/O 和资源准备应在开始前完成。
- 读取 `UIAccessibility.isReduceMotionEnabled`，为大幅位移、缩放和模拟纵深的运动提供减弱或交叉淡化方案，并响应设置变化。
- 高刷新率缩短每帧预算；动画参数保持以时间和状态为中心，不按“帧数”硬编码进度。

## 边界

- 非交互、不可重复触发且很短的装饰动画不一定需要完整的中断状态机。
- 弹簧不是天然更自然；业务语义、位移、输入速度和终点约束不同，参数应通过原型与真机体验确定。
- 可中断只解决控制流，不会自动解决主线程阻塞、布局热点或 GPU 渲染压力。

## 常见错误

- 用户再次点击时重新从固定起点开启动画，造成位置或速度跳变。
- 只改 `fractionComplete`，却未定义取消、反向、完成回调和最终状态。
- 在完成回调前就假定动画一定到达 `.end`，忽略中止和反向。
- 动画时禁用整个页面交互，却没有产品或一致性上的必要性。
- 固定按 60 帧更新，或把 120 FPS 当作自然动画的充分条件。
- 忽略 Reduce Motion，或简单删除反馈导致状态变化难以理解。

## 验证

- 在真实设备上连续快速触发、动画中反向、拖到临界点释放、取消转场并切换前后台。
- 检查每种中断路径的模型状态、presentation 位置、命中测试、焦点和完成回调均一致。
- 分别在 60 Hz 与支持 120 Hz 的设备上用 Hitches/Time Profiler 检查长帧和主线程工作；FPS 只作辅助。
- 开启 Reduce Motion，验证替代效果仍能表达层级、方向或完成状态。
- 用慢速动画辅助观察连续性，但以正常速度和真实手势的体验为准。

## 来源

- [UIViewPropertyAnimator](https://developer.apple.com/documentation/uikit/uiviewpropertyanimator)
- [isInterruptible](https://developer.apple.com/documentation/uikit/uiviewpropertyanimator/isinterruptible)
- [UIViewAnimating](https://developer.apple.com/documentation/uikit/uiviewanimating)
- [UIAccessibility.isReduceMotionEnabled](https://developer.apple.com/documentation/uikit/uiaccessibility/isreducemotionenabled)
- [Understanding hitches in your app](https://developer.apple.com/documentation/xcode/understanding-hitches-in-your-app)
