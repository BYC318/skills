---
id: logging-signposts-and-metrickit
tags: [iOS, Logger, OSSignposter, MetricKit, Instruments, privacy]
triggers:
  - 新增日志、埋点、性能区间或线上诊断
  - 需要定位启动、网络、数据库、图片处理或动画耗时
  - Xcode Organizer、MetricKit、hang 或 disk write diagnostic
  - 声称发布版本性能已改善或出现回归
applies_to: [UIKit, SwiftUI, Swift, Objective-C]
status: verified
last_verified: 2026-09-10
---

# 日志、Signpost 与 MetricKit 可观测性

## 触发条件

- 为关键流程增加可诊断日志或测量区间。
- 本地难以复现线上内存、耗电、启动、Hang、Hitch 或磁盘写入问题。
- 并发任务重叠，单靠函数耗时无法还原用户操作与资源活动的关系。
- 需要把 Instruments 本地证据与真实设备发布指标分开。

## 稳定结论

- `Logger` 用于记录离散状态和错误；`OSSignposter` 用于测量具有开始与结束的操作。日志行数量不能代替时长和资源指标。
- signpost 的名称、subsystem 和 category 应稳定且低基数；同时发生的同名区间需要不同 ID，并保证 begin/end 成对。
- MetricKit 提供真实设备的聚合性能指标与诊断，适合发现发布版本趋势；它不替代 Instruments 的可复现调用栈和时间线分析。
- MetricKit 指标是采样和聚合结果，必须结合报告时间区间、应用版本、设备与系统环境解释，不能由单个 payload 推断全部用户。
- 动态日志内容默认按隐私处理；账户、令牌、完整请求数据和用户内容不得为了诊断而公开。

## 编码约束

- 用稳定 subsystem 表示应用或进程，用 category 表示功能域；日志级别表达严重程度，不为普通控制流滥用 error/fault。
- 对网络请求、数据库事务、图片管线、启动准备和交互等关键区间使用静态名称；动态身份只作为受隐私保护的元数据。
- 可能重叠的区间用唯一 signpost ID，并持有返回的 interval state 直到所有成功、失败和取消路径均结束区间。
- 在正式构建中控制热路径日志量；逐帧、紧密循环和高频回调只记录能改变诊断结论的事件。
- iOS 13–26 目标使用 `MXMetricManager` 与 subscriber 接收报告；由一个明确的进程级所有者注册和管理 subscriber，并将上传、去重和保留策略置于独立后台管线。
- 保存 MetricKit 诊断时保留原始时间与环境元数据，符号化调用栈后再聚合；日志与指标后端不得用高基数用户标识拆分性能数据。

## 不适用或边界

- signpost 会提供相关性和时长边界，但不会自动说明 CPU、锁、I/O 或 GPU 根因；仍需结合对应 Instruments 轨迹。
- MetricKit 日常指标最多按系统节奏交付，不能用于实时监控或单次操作的即时 UI 决策。
- iOS 15 起诊断可更及时交付，但系统不保证每个问题或设备都产生报告。
- Apple 已为 iOS 27 beta 提供基于 AsyncSequence 的 `MetricManager`；在 iOS 27 成为目标且 SDK 稳定前，不把 beta API 当作通用默认，也不提前删除 iOS 13–26 的 `MXMetricManager` 路径。

## 常见错误

- 在循环中打印每个元素，既制造开销又淹没真正的异常事件。
- signpost 名称包含 URL、对象 ID 或用户 ID，导致高基数且泄露数据。
- 同名并发区间共用 `.exclusive` ID，或异常返回时漏掉 end。
- 将动态字符串标成 `.public`，无意暴露账户、请求参数或用户内容。
- 只上传平均值，不保留分布、版本和设备环境，导致回归无法归因。
- 看到线上 Hang 指标后直接猜测代码根因，没有在 Instruments 中复现和检查调用栈。

## 验证方法

1. 在 Instruments 的 Points of Interest 或 os_signposts 轨迹中确认区间配对、并发 ID 和任务边界正确。
2. 覆盖成功、错误、取消和提前返回路径，确认没有未结束区间，日志也不会包含敏感明文。
3. 在物理设备上验证 MetricKit 订阅、payload 序列化和诊断处理；开发环境不能要求即时收到日常报告。
4. 将同一发布版本的 MetricKit/Organizer 趋势与可复现的 Instruments 证据关联，分别报告线上分布和本地根因。

## 官方来源

- Apple：[Generating log messages from your code](https://developer.apple.com/documentation/os/generating-log-messages-from-your-code)
- Apple：[OSLogPrivacy](https://developer.apple.com/documentation/os/oslogprivacy)
- Apple：[Recording performance data](https://developer.apple.com/documentation/os/recording-performance-data)
- Apple：[OSSignposter](https://developer.apple.com/documentation/os/ossignposter)
- Apple：[MetricKit](https://developer.apple.com/documentation/metrickit)
- Apple：[MXMetricManager](https://developer.apple.com/documentation/metrickit/mxmetricmanager)
