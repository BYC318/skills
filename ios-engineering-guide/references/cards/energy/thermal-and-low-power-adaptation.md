---
id: thermal-and-low-power-adaptation
tags: [iOS, energy, thermal, Low-Power-Mode, CPU, GPU, frame-rate]
triggers:
  - 持续 CPU、GPU、网络、定位或传感器工作
  - 游戏、视频、相机、实时渲染或高帧率页面
  - 设备发热、降频或低电量模式适配
  - 长时间任务需要动态降级质量
applies_to: [UIKit, SwiftUI, Swift, Objective-C]
status: verified
last_verified: 2026-09-10
---

# 热状态与低电量模式适配

## 触发条件

- 功能持续占用 CPU/GPU、频繁 I/O、网络、蓝牙、定位或传感器。
- 长时间使用后帧率下降、响应变慢、设备明显发热或电量消耗异常。
- 非关键工作可以降低频率、质量、精度或延后执行。

## 稳定结论

- 热状态升高时系统可能降低处理器性能；继续维持原工作量会同时恶化响应、帧稳定性与耗电。
- 低电量模式和热状态是不同信号。应分别读取 `isLowPowerModeEnabled` 与 `thermalState`，并监听对应变化通知。
- 在 `.serious` / `.critical` 等高热状态下，优先减少或暂停非必要 CPU/GPU、I/O、网络、蓝牙和高精度定位工作，并降低可降级渲染的复杂度或目标帧率。
- 降级策略必须可恢复。状态回落后重新评估，而不是永久维持低质量，也不要以恢复质量造成瞬时任务洪峰。

## 编码约束

- 由单一策略对象把电源、热状态、前后台和用户意图转换为能力档位，避免各组件独立降级产生矛盾。
- 把视觉特效、预取、索引、遥测上传和后台刷新等非关键工作设计成可暂停、合并或降频；用户明确发起的关键操作保持正确并提供进度。
- 实时渲染按产品体验选择分级帧率和细节，不机械固定为 60 或 120 FPS；不可见时停止 display link 和绘制。
- 处理通知时只更新策略并让任务在安全边界响应；取消观察、Timer 与资源采集应与所有者生命周期一致。
- 让系统通过合适 QoS 和 discretionary 能力调度可延迟工作，不用高优先级强行对抗节能策略。

## 不适用或边界

- 热状态是设备整体状态，不能单独证明当前 App 是根因；环境温度、充电和其他进程也会影响结果。
- 低电量模式不授权破坏用户已选择的核心功能或数据完整性；降级对象应是可选质量和非紧急工作。
- 模拟器不能提供可信的耗电、温升、降频或持续帧率证据。

## 常见错误

- 只在启动时读取一次热状态或低电量模式，运行期间不响应变化。
- 发热后仍增加线程或提高优先级，试图用更多资源维持吞吐。
- 一律把帧率降到 30 FPS，却未判断交互、视频、游戏和静态页面的不同需要。
- 状态恢复时同时重启全部下载、预取和计算，形成新的峰值。
- 看到 `.serious` 就宣称 App 耗电过高，未用真机工具定位实际子系统。

## 验证方法

- 在真机上长时间运行代表性场景，记录热状态、低电量模式、帧率/hitch、CPU/GPU、网络和电量趋势。
- 用 Xcode Energy Impact 与 Instruments 对比正常、低电量及降级档位；记录设备、系统、亮度、网络和测试时长。
- 通过可控策略输入测试各档位的暂停、降频、恢复和并发状态切换，确认不会丢数据或形成任务洪峰。
- 结合 MetricKit 的 CPU、GPU、网络、显示和定位指标观察真实用户趋势，不以一次本地运行代替长期证据。

## 官方来源

- [Apple: ProcessInfo](https://developer.apple.com/documentation/foundation/processinfo)
- [Apple: ProcessInfo.ThermalState.serious](https://developer.apple.com/documentation/foundation/processinfo/thermalstate-swift.enum/serious)
- [Apple: isLowPowerModeEnabled](https://developer.apple.com/documentation/foundation/processinfo/islowpowermodeenabled)
- [Apple: Analyzing your app's battery use](https://developer.apple.com/documentation/xcode/analyzing-your-app-s-battery-use)
- [Apple: Energy Efficiency Guide for iOS Apps](https://developer.apple.com/library/archive/documentation/Performance/Conceptual/EnergyGuide-iOS/)
