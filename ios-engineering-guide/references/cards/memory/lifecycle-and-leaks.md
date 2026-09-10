---
id: lifecycle-and-leaks
tags: [iOS, Swift, ARC, closure, Task, lifecycle, memory]
status: verified
last_verified: 2026-09-10
---

# 用所有权和生命周期消除泄漏与无效存活

## 触发条件

- 新增或修改 delegate、闭包回调、Timer、通知、Combine 订阅或异步 `Task`。
- 页面退出后对象没有释放、任务仍执行、回调仍更新 UI，或内存随重复操作持续增长。
- 需要在 `weak`、`unowned` 和强引用之间选择。

## 稳定结论

- ARC 管理引用类型的生命周期，但不会自动打破强引用环。
- 泄漏不只包括不可达内存；对象仍被引用但业务已不再需要的“遗留内存”同样会推高占用。
- 是否弱引用由所有权和生命周期决定，不由“闭包里出现 `self`”这一表面形式决定。
- Swift Task 的取消是协作式的；丢弃 task handle 不会停止任务，调用 `cancel()` 也不保证任意工作立即退出。

## 编码约束

- 先写清谁拥有谁：父对象通常强持有子对象；反向 delegate/reference 在不拥有对方时使用 `weak`。
- 闭包被对象长期持有且又捕获该对象时，显式打破环；短生命周期、非逃逸或不形成环的闭包不机械添加 `[weak self]`。
- 只有被引用对象确定比引用方活得更久时才用 `unowned`；无法证明该不变量时使用 `weak` 并处理 `nil`。
- 对可取消的长任务保留 handle，在功能生命周期结束时取消，并在耗时阶段或回写前响应取消。
- 观察者、Timer、订阅和回调令牌的注册者与注销者应有可追踪、对称的生命周期；不要假设页面不可见等于对象已释放。
- 异步回写除对象仍存在外，还要校验请求、账户、页面代次或资源身份，避免“没有泄漏但结果已过期”。

## 不适用或边界

- 单纯看到强引用不能证明泄漏；所有权树本来就需要强引用维持对象生存。
- `deinit` 日志只能证明某个测试路径上的释放，不能定位全部持有链，也不能替代 Memory Graph。
- 系统或框架缓存导致对象暂时存活不等于泄漏；要结合重复操作后的增长趋势和引用路径判断。

## 常见错误

- 所有逃逸闭包一律 `[weak self]`，导致必要工作静默消失或状态更新不完整。
- 为避免可选处理滥用 `unowned`，把生命周期错误变成运行时崩溃。
- 只在 `deinit` 中取消一个实际被任务闭包强持有的长期任务，形成无法到达 `deinit` 的等待关系。
- 取消任务后不检查取消状态，仍完成昂贵计算或回写过期结果。
- 只运行 Leaks，忽略仍然可达但已无业务用途的对象。

## 验证方法

1. 用接近真实使用的路径重复进入、操作、退出页面，建立预期实例数和任务数。
2. 在 Xcode Memory Graph 中检查目标对象的强引用路径和循环；不要只看“是否有紫色告警”。
3. 用 Instruments Allocations 的 Generations 比较每轮操作后存活对象是否回落；必要时再用 Leaks 辅助排查不可达分配。
4. 为生命周期边界增加可观察测试：退出/复用后旧任务停止，旧结果不能覆盖当前状态；将释放断言与功能正确性分别验证。

## 官方来源

- Swift：[Automatic Reference Counting](https://docs.swift.org/swift-book/documentation/the-swift-programming-language/automaticreferencecounting/)
- Apple：[Task and task cancellation](https://developer.apple.com/documentation/swift/task)
- Apple：[Gathering information about memory use](https://developer.apple.com/documentation/xcode/gathering-information-about-memory-use)
- Apple：[Diagnosing and resolving bugs in your running app](https://developer.apple.com/documentation/xcode/diagnosing-and-resolving-bugs-in-your-running-app)
