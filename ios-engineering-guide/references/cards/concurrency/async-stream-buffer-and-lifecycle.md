---
id: async-stream-buffer-and-lifecycle
tags: [Swift, AsyncStream, AsyncSequence, buffering, cancellation, lifecycle]
triggers:
  - 用 AsyncStream 桥接 Delegate、通知或多次回调
  - 高频事件流、消费者变慢或内存持续增长
  - Stream 结束后生产者仍在运行
  - 需要设计事件丢弃或背压策略
applies_to: [UIKit, SwiftUI, Swift]
status: verified
last_verified: 2026-09-10
---

# AsyncStream 缓冲与生命周期

## 触发条件

- 将 Timer、Notification、Delegate、Socket、传感器或订阅包装成 `AsyncSequence`。
- 事件生产速度可能高于消费速度，或事件可合并、可丢弃。
- 消费任务取消后仍有回调、资源占用或内存增长。

## 稳定结论

- `AsyncStream` 的默认缓冲策略是 `.unbounded`。当生产者持续快于消费者时，未消费元素可能无界增长。
- `yield` 会立即返回，不会等待消费者，因此 continuation 版本的 `AsyncStream` 不会自动给无背压生产者施加真正背压。
- `.bufferingNewest(n)` 丢弃最旧元素，适合只关心最新状态；`.bufferingOldest(n)` 丢弃新元素，适合保留先到事件。策略必须来自业务语义。
- `finish()` 只结束 Stream；底层生产者、观察者或系统资源仍需显式停止。消费取消时用 `onTermination` 转发清理。

## 编码约束

- 创建 continuation Stream 时显式选择缓冲策略；只有元素总量有明确上限且峰值可接受时才使用 `.unbounded`。
- 处理 `yield` 返回的 `.dropped` 与 `.terminated`，用于停止无效生产、记录丢弃或触发领域允许的合并策略。
- 所有正常完成和失败路径都结束 Stream；`AsyncThrowingStream` 的错误终止与主动取消保持不同语义。
- `onTermination` 中只执行快速、线程安全的取消动作。通知、Delegate、Timer 和底层任务由明确的生命周期所有者持有并清理。
- 需要不能丢数据的高速流时，在上游设计限速、批处理或需求驱动接口，不靠扩大缓冲掩盖吞吐不匹配。

## 不适用或边界

- 状态快照、遥测和 UI 事件通常允许合并或丢弃；交易、持久化写入等可靠事件不能未经约定直接丢弃。
- `onTermination` 表示消费端结束，不保证任何第三方生产者天然支持取消。
- `AsyncStream` 自 Swift 5.5 提供；部署兼容性仍应以当前 SDK 和项目目标为准。

## 常见错误

- 省略缓冲策略后假定系统只保留一个最新值。
- 消费 Task 被取消，却未移除通知、Delegate 或停止硬件采集。
- 调用 `finish()` 后继续生产，且忽略 `.terminated`。
- 为“绝不丢事件”使用无限缓冲，却没有容量、速率或故障恢复边界。

## 验证方法

- 用快生产、慢消费压力测试记录缓冲峰值、丢弃数量和内存曲线。
- 覆盖正常完成、生产失败、消费取消、重复结束与无人消费场景。
- 用生命周期断言或 signpost 确认终止后 Timer、观察者、Delegate 与底层任务及时释放。
- 在真机上观察长时间事件流的内存、CPU 和耗电；短单元测试不能证明缓冲稳定。

## 官方来源

- [Apple: AsyncStream](https://developer.apple.com/documentation/swift/asyncstream)
- [Apple: AsyncStream.BufferingPolicy](https://developer.apple.com/documentation/swift/asyncstream/continuation/bufferingpolicy)
- [Apple: AsyncStream.Continuation.onTermination](https://developer.apple.com/documentation/swift/asyncstream/continuation/ontermination)
- [SE-0314: AsyncStream and AsyncThrowingStream](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0314-async-stream.md)
