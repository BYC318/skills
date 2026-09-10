---
id: hangs-and-priority-inversion
tags: [iOS, responsiveness, hang, main thread, QoS, Instruments]
triggers:
  - 点击、输入、页面切换或返回前台长时间无响应
  - 主线程同步 I/O、网络、锁、信号量或线程等待
  - dispatch_semaphore_wait、dispatch_group_wait 或 priority inversion
  - Hangs Instrument、Thread Performance Checker 或 Hang Diagnostic
applies_to: [UIKit, SwiftUI, Swift, Objective-C]
status: verified
last_verified: 2026-09-10
---

# Hang、主线程阻塞与优先级反转

## 触发条件

- 离散交互后界面冻结、按钮迟迟不反馈或系统报告 Hang。
- 主线程执行解析、图片处理、数据库、文件或同步网络工作。
- 主线程或高 QoS 工作等待锁、信号量、dispatch group、线程或低优先级任务。
- 异步化后仍卡顿，需要判断主线程是繁忙还是阻塞。

## 稳定结论

- Hang 是主 run loop 长时间无法处理交互的表现；主线程可能在执行过多工作，也可能阻塞等待资源，两者的修复方式不同。
- 离散交互的同步主线程工作应明显低于用户可感知延迟。Apple 以约 100 ms 作为粗略上界；滚动和手势等连续交互必须在单帧预算内完成，通常需要更短。
- 把工作派发到后台后再让主线程同步等待，并没有提升响应性。
- 高优先级线程等待低优先级工作会造成优先级反转；信号量和 group wait 等原语无法总是自动传播优先级。
- 先修复 Hang 往往也会减少一部分 commit hitch，但 render hitch 仍需单独分析。

## 编码约束

- 主线程只执行 UI、事件处理和必须在主线程调用的框架 API；文件、数据库、同步网络和已证实昂贵的计算移出交互关键路径。
- 优先使用结构化并发、Dispatch 或 OperationQueue 等系统管理的并发机制，不自行创建大量线程。
- 不使用 `dispatch_semaphore_wait` 或 `dispatch_group_wait` 将内部异步 API 包装成同步调用，尤其不能在主线程这样做。
- 必须存在等待关系时，让提供结果的工作具有不低于等待方需求的 QoS，并设置可失败或可取消的边界；不要无限等待。
- `Task {}` 和 `await` 不代表自动离开 MainActor；同步重活必须位于非主 actor 隔离的执行路径，并通过 Instruments 确认实际调度。
- 将长操作拆分或搬移时保持状态原子性、顺序与取消语义；不能用频繁切队列换取表面上的主线程空闲。

## 不适用或边界

- 100 ms 与连续交互约 5 ms 是开发和测试尺度，不是每个函数的固定 SLA；真实预算受设备、系统负载、刷新率和同一事件中的其他工作影响。
- 后台线程上的长任务不一定造成 Hang，但仍可能竞争 CPU、内存和 I/O，间接影响主线程或耗电。
- Thread Performance Checker 能发现部分优先级反转和主线程非 UI 工作，不是完整的正确性证明，也不替代性能测试。
- Hang 关注交互响应；没有屏幕更新时的后台耗时应使用 CPU、任务时限或能耗指标评价。

## 常见错误

- 在主线程读取文件、等待数据库、启动同步设备操作或等待后台任务完成。
- 用 semaphore 把 completion handler 包成同步返回，再从主线程调用。
- 把重活放入继承 MainActor 的 `Task`，误以为已经进入后台。
- 给所有队列设置 `.userInteractive`，制造 CPU 竞争并掩盖真实优先级关系。
- 看到低 CPU 就排除 Hang，忽略主线程可能正在锁或系统调用上等待。
- 只修复一次超过阈值的样本，没有覆盖真实数据量、较慢设备和竞争条件。

## 验证方法

1. 启用 Thread Performance Checker，检查优先级反转和主线程非 UI 工作；在测试计划中可将相关 runtime issue 配置为失败。
2. 用 Time Profiler、CPU Profiler 或 Hitches 模板中的 Hangs Instrument 复现问题，先判断主线程是 running 还是 blocked。
3. 对 blocked Hang 加入 Thread State Trace，沿等待链定位锁、信号量、I/O 或低 QoS 提供者。
4. 在开发签名或 TestFlight 真机上启用 on-device Hang Detection，并结合 Xcode Organizer 或 MetricKit 观察发布版本趋势。
5. 固定设备、系统、构建和数据，对比改动前后的主线程最长连续占用、Hang 次数和用户操作延迟。

## 官方来源

- Apple：[Improving app responsiveness](https://developer.apple.com/documentation/xcode/improving-app-responsiveness)
- Apple：[Understanding hangs in your app](https://developer.apple.com/documentation/xcode/understanding-hangs-in-your-app)
- Apple：[Diagnosing performance issues early](https://developer.apple.com/documentation/xcode/diagnosing-performance-issues-early)
- Apple：[Analyze hangs with Instruments](https://developer.apple.com/videos/play/wwdc2023/10248/)

