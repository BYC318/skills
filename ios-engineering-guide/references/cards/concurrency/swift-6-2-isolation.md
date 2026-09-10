---
id: swift-6-2-isolation
tags: [Swift, Swift-6.2, MainActor, nonisolated, concurrent, actor-isolation]
triggers:
  - Swift 6.2 迁移或默认 actor 隔离设置
  - async 函数意外占用主 actor
  - nonisolated、@concurrent 或协议隔离诊断
  - UI 模块调整并发构建配置
applies_to: [UIKit, SwiftUI, Swift]
status: verified
last_verified: 2026-09-10
---

# Swift 6.2 隔离与执行语义

## 触发条件

- 项目启用 Swift 6.2、`Default Actor Isolation` 或相关 upcoming feature。
- `async` 代码出现主线程卡顿，或迁移后执行位置与旧代码不同。
- `@MainActor` 类型实现同步协议时出现 isolation mismatch。

## 稳定结论

- `async` 只表示函数可以挂起，不表示它自动在后台执行。Swift 6.2 可让非隔离 `async` 函数保留调用者的隔离域；从主 actor 调用时，它仍可能占用主 actor。
- `@concurrent` 显式表达函数应离开调用者 actor 并允许并发执行；它不承诺创建新线程，也不替代工作量控制和取消。
- `-default-isolation MainActor` 与 SwiftPM 的 `defaultIsolation(MainActor.self)` 是逐模块选择。未显式启用时，默认仍为 `nonisolated`，依赖模块也不受当前模块设置影响。
- 全局 actor 隔离类型的协议一致性可以限制在同一隔离域内使用。隔离不匹配时应先明确一致性的使用域，不要常规化使用 `MainActor.assumeIsolated` 绕过静态检查。

## 编码约束

- 修改并发代码前先确认 Swift language mode、默认 actor 隔离和 upcoming feature 设置；不要只根据源码语法推断执行语义。
- UI 状态与其变更入口保持 `@MainActor` 隔离；CPU 密集工作只有在确实允许并发且输入输出满足隔离要求时才标记 `@concurrent`。
- 同步 I/O、锁等待或阻塞式第三方 API 不会因放进 `async` 函数而变成非阻塞；应在合适的异步边界处理。
- 协议一致性需要跨隔离域使用时，让实现真正 `nonisolated` 且只访问安全数据；只在 actor 内使用时，优先表达隔离一致性。

## 不适用或边界

- 这是 Swift 编译器与构建设置边界，不是 iOS 部署版本或运行时线程 API 的保证。
- `NonisolatedNonsendingByDefault` 与隔离一致性推断可能由 upcoming feature 控制；编码前以当前工具链和目标设置为准。
- 并发执行不等于更快。短工作、严格顺序依赖或频繁 actor hop 可能因调度成本变慢。

## 常见错误

- 用空的 `Task {}` 或新增 `async` 关键字声称已把重活移出主线程。
- 升级工具链后仍依赖旧版非隔离 `async` 自动切换到全局执行器的行为。
- 为消除协议隔离诊断，把所有成员标成 `nonisolated` 或使用运行时断言。
- 在未检查模块设置时批量增加或删除 `@MainActor`。

## 验证方法

- 在目标实际使用的 Swift language mode 和构建设置下编译，并解决而不是屏蔽严格并发诊断。
- 用 Main Thread Checker、Time Profiler 或 Swift Concurrency 轨迹确认 CPU/阻塞工作没有占用主 actor。
- 为协议一致性分别编译同隔离域与跨隔离域调用场景，确认边界与 API 意图一致。
- 比较迁移前后的交互响应、任务数量和 actor hop；构建成功不能证明主线程负载已经改善。

## 官方来源

- [Swift 6.2 Released](https://www.swift.org/blog/swift-6.2-released/)
- [SE-0461: Run nonisolated async functions on the caller's actor by default](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0461-async-function-isolation.md)
- [SE-0466: Control default actor isolation inference](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0466-control-default-actor-isolation.md)
- [SE-0470: Global-actor isolated conformances](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0470-isolated-conformances.md)
