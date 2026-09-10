---
id: structured-concurrency
tags: [Swift, async-await, TaskGroup, MainActor, Sendable, actor]
triggers:
  - 新增或重构 async/await 代码
  - 并行请求、批量处理或 TaskGroup
  - Swift 6 并发安全告警
  - UI 状态跨并发域更新
applies_to: [UIKit, SwiftUI, Swift]
status: verified
last_verified: 2026-09-10
---

# 结构化并发与隔离边界

## 稳定结论

- 优先用 `async let` 和任务组表达有明确作用域的并发工作。结构化子任务不会越过父作用域，并继承优先级、任务局部值与取消信号。
- `await` 表示潜在挂起点，不代表工作离开主线程，也不保证并行；CPU 密集或同步阻塞工作仍可能占住当前执行器。
- `@MainActor` 用来声明 UI 与其状态的隔离要求，不只是一次线程切换。优先标注类型或 API 的隔离边界，而不是到处调用 `MainActor.run`。
- `Sendable` 是值可以安全跨隔离域传递的契约。优先使用由 `Sendable` 成员组成的不可变值类型；`@unchecked Sendable` 是人工安全承诺，不是消除编译错误的快捷方式。
- actor 防止数据竞争，但 `await` 之后 actor 状态可能已经变化；跨挂起点的“读取—等待—写回”不具备原子性。

## 编码约束

- 固定数量且彼此独立的操作用 `async let`；动态数量用 `withThrowingTaskGroup` / `withTaskGroup`，并明确结果顺序与失败策略。
- UI 可观察状态及其变更入口通常隔离到 `@MainActor`；耗时解析、图像处理和同步 I/O 不放在该隔离域内执行。
- 跨 actor 传递 DTO 时优先 `struct`、不可变属性和显式 `Sendable` 公共契约。
- 共享可变状态集中到一个清晰的隔离域；不要同时由锁、队列和 actor 分散管理同一状态。
- 仅在任务确实不应继承当前 actor、优先级和任务局部值时使用 `Task.detached`，并在代码中说明生命周期所有者。
- 每个 `await` 后重新验证依赖的可变前置条件；需要原子性的状态转换应放进 actor 的同步隔离方法中一次完成。

## 边界

- 顺序存在数据依赖时不要为了“并发化”创建子任务。
- 任务组退出前会等待所有子任务结束；只取到首个结果并不会自动停止其余工作，需要显式取消且子任务配合响应。
- 旧 Objective-C 回调、未标注并发语义的第三方库和受锁保护的引用类型可能需要迁移适配；使用 `@preconcurrency` 或 `@unchecked Sendable` 时应记录无法由编译器验证的安全依据。

## 常见错误

- 用 `Task {}` 包裹同步重活，误以为一定移到了后台。
- 把整个业务层标成 `@MainActor`，导致解析、磁盘和数据库工作阻塞 UI。
- 为消除 Swift 6 告警直接添加 `@unchecked Sendable`。
- 假设任务组结果按创建顺序返回，或假设 actor 方法跨多个 `await` 仍是一个临界区。
- 用大量无界子任务处理大集合，造成内存、连接数或调度压力峰值。

## 验证

- 开启目标支持的严格并发检查，解决而非屏蔽 actor isolation 和 `Sendable` 诊断。
- 用 Thread Sanitizer 检查仍通过锁、回调或 Objective-C 暴露的共享状态；它不能替代编译期隔离检查。
- 用 Instruments 的 Time Profiler / Swift Concurrency 轨迹确认主线程没有同步阻塞，并检查任务数量与生命周期是否符合预期。
- 对并行聚合编写成功、部分失败、取消、乱序完成和重复调用测试。

## 官方来源

- [The Swift Programming Language: Concurrency](https://docs.swift.org/swift-book/documentation/the-swift-programming-language/concurrency/)
- [Swift 6 Migration Guide: Data Race Safety](https://www.swift.org/migration/documentation/swift-6-concurrency-migration-guide/dataracesafety/)
- [Apple: MainActor](https://developer.apple.com/documentation/swift/mainactor)
- [Apple: TaskGroup](https://developer.apple.com/documentation/swift/taskgroup)
