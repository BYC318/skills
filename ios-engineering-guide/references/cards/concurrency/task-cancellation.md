---
id: task-cancellation
tags: [Swift, Task, cancellation, lifecycle, stale-response]
triggers:
  - 页面退出或 Cell 复用后仍有异步回调
  - 搜索联想、分页、图片请求或连续刷新
  - 长循环、任务组或桥接回调 API
  - 数据被旧请求结果覆盖
applies_to: [UIKit, SwiftUI, Swift]
status: verified
last_verified: 2026-09-10
---

# 任务取消与过期结果防护

## 稳定结论

- Swift 任务取消是协作式、幂等的信号：`cancel()` 会设置取消状态、触发取消处理器并向结构化子任务传播，但不会强制停止任意代码。
- “请求已取消”和“结果仍适用于当前界面”是两件事。底层工作可能忽略取消或恰好完成，因此提交状态前仍要判断结果是否过期。
- 生命周期所有者应持有非结构化任务句柄，并在任务被替换、视图离开或对象结束时取消；结构化工作则让作用域管理子任务。
- `[weak self]` 只影响引用生命周期，不能证明结果对应当前页面、查询、账号或 Cell。

## 编码约束

- 在长循环、批处理边界和关键 `await` 后调用 `Task.checkCancellation()`，或读取 `Task.isCancelled` 后清理并尽快返回。
- 用 `withTaskCancellationHandler` 转发取消到回调式或自定义底层操作；处理器可能与 operation 并发执行，只做线程安全且快速的取消动作。
- 新请求替代旧请求时，先取消旧句柄；提交结果前同时检查取消状态和当前请求身份。
- 用单调递增 generation、不可变 request ID、查询快照或模型 identity 识别过期结果；在 `@MainActor` 隔离内完成“校验并提交”。
- `CancellationError` 通常不展示成用户故障；真实错误、空结果和主动取消保持不同状态。
- 对 Cell/可复用视图，复用时取消任务，回填前核对模型 identity；不要只核对 `IndexPath`。

## 边界

- 不能仅因 `URLSession`、第三方 SDK 或 continuation 支持 `async` 就假定它会及时响应取消；查阅该 API 契约并实测。
- 必须完成的持久化或交易操作不能随页面消失盲目取消；应把所有权提升到业务作用域，并把 UI 观察与工作生命周期分离。
- generation 防止旧结果落地，但不会释放网络、CPU 或内存资源；仍应传播取消。

## 常见错误

- 调用 `task.cancel()` 后立即认为闭包不会再执行。
- 只在任务开始时检查一次取消，长循环继续耗电和占用 CPU。
- 页面反复刷新时覆盖任务句柄，却未先取消旧任务。
- 在取消处理器和 operation 中无同步地读写同一个变量。
- 将取消映射为错误页或弹窗，造成离开页面时的伪失败。

## 验证

- 测试慢请求 A 后快速发起 B，令 A 最后返回，断言最终状态只来自 B。
- 测试页面退出、Cell 复用、账号切换和连续点击后，不再产生旧 UI 写入或副作用。
- 为底层操作记录开始、取消、结束 signpost，确认取消后资源在可接受时间内释放。
- 对循环和任务组注入取消，断言不会继续创建无用子任务，且已完成部分结果符合 API 约定。

## 官方来源

- [The Swift Programming Language: Task Cancellation](https://docs.swift.org/swift-book/documentation/the-swift-programming-language/concurrency/#Task-Cancellation)
- [Apple: Task.cancel()](https://developer.apple.com/documentation/swift/task/cancel%28%29)
- [Apple: TaskGroup](https://developer.apple.com/documentation/swift/taskgroup)
- [Apple: withTaskCancellationHandler](https://developer.apple.com/documentation/swift/withtaskcancellationhandler%28operation%3Aoncancel%3Aisolation%3A%29)
