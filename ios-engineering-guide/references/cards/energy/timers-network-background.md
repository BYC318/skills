---
id: timers-network-background
tags: [iOS, energy, Timer, URLSession, BackgroundTasks, network]
status: verified
last_verified: 2026-09-10
---

# 减少定时器、网络与后台工作的无效唤醒

## 触发条件

- 新增轮询、心跳、倒计时、自动刷新、重试或周期任务。
- 发起多个零散请求、大文件传输，或处理弱网与受限网络。
- 需要在 App 退到后台后继续传输、刷新或维护数据。
- 出现后台耗电、发热、网络唤醒频繁或电量指标回归。

## 稳定结论

- 降低耗电首先是减少不必要的工作和唤醒，再优化剩余工作的执行方式。
- 事件驱动通常比固定频率轮询更节能；零散网络活动会延长通信硬件活跃时间，适合合并的请求应批处理。
- 后台执行时间和调度时机由系统管理。`BGTaskScheduler`、后台 `URLSession` 或后台推送都不是精确定时器。
- “少请求”不能单独证明省电：数据量、重试、连接条件、CPU 处理和用户可感知延迟都必须一起测量。

## 编码约束

- 只有产品语义确实要求周期触发时才使用重复 Timer；离开有效生命周期立即停止，并在允许延迟时设置合理 tolerance。
- 倒计时以目标时间或单调时钟计算剩余量，不累计 Timer 触发次数，避免系统延迟后漂移。
- 复用合理粒度的 `URLSession`，避免为每个请求创建会阻断连接复用的独立会话。
- 合并可延迟请求、压缩有效载荷；对非必要任务按业务容忍度配置昂贵/受限网络访问，不能擅自影响用户要求的即时操作。
- 连接暂不可用时，根据交互语义选择等待或快速失败；`waitsForConnectivity` 只作用于建连阶段，后台 session 本就等待连接。
- 大型、可延后的后台传输使用后台 `URLSession`，并在合适时允许系统 discretionary 调度；短刷新和维护任务按用途选择 BackgroundTasks API。
- 所有后台工作处理到期与取消，尽快报告完成；任务必须可重入、可重复调度，不能假设系统一定执行。

## 后台机制选择

- 前台发起且只需短时间完成关键收尾：使用 `beginBackgroundTask`，处理 expiration 并保证成对结束。
- 长文件上传或下载：使用后台 `URLSession`，让传输在 App 未运行时由系统继续管理。
- 系统择机执行的短时内容刷新：使用 `BGAppRefreshTask`；延后且较重的维护或计算：使用 `BGProcessingTask`。
- 服务端不定期通知内容变化：使用 background push，但仍按系统裁量设计，不能依赖每次送达。
- iOS/iPadOS 26 及以后，用户明确发起、需要持续可见进度的长任务可评估 `BGContinuedProcessingTask`；它不用于普通自动同步、备份或维护。

## 不适用或边界

- 实时通话、导航、媒体播放、外设通信等有专门后台模式与体验要求，应遵循对应框架规则，不能套用“全部延后”。
- `BGContinuedProcessingTask` 是版本绑定能力；旧系统应按任务语义选择已有机制，不能伪造一个等价的通用 fallback。
- 用户主动点击后的关键请求通常应及时执行；批处理不得破坏正确性、交易时效或明确的刷新承诺。
- 动画逐帧更新使用显示同步机制，不用普通 Timer 猜测刷新频率。
- Timer tolerance 的大小取决于体验和业务精度；不要把固定百分比当成跨场景硬规则。

## 常见错误

- 用短间隔 Timer 观察状态变化，页面隐藏或 App 进入后台后仍持续触发。
- 为“保活”滥用后台模式、静音音频或无限后台任务。
- 固定间隔失败重试且没有退避、上限、去重与取消，弱网下形成唤醒风暴。
- 把 `earliestBeginDate` 当成准点执行承诺，或依赖一次后台任务完成关键数据一致性。
- 仅在模拟器或充电连接状态下观察耗电，并据此宣称真机改善。

## 验证方法

1. 固定前台/后台时长、网络条件、设备、电量和温度区间，对同一用户流程记录改动前基线。
2. 用 Instruments Power Profiler 定位 CPU、网络和唤醒相关活动；结合 Network 模板核对请求数量、时间分布、重试和字节量。
3. 在非充电真机上验证锁屏、前后台切换、弱网、受限网络和 Low Power Mode；同时确认延迟与数据新鲜度仍符合产品要求。
4. 发布后用 Xcode Organizer 的 Battery Usage/energy diagnostics 或 MetricKit 趋势确认改善，避免以单次本地采样外推全量用户。

## 官方来源

- Apple：[Reducing your app's battery use](https://developer.apple.com/documentation/xcode/reducing-your-app-s-battery-use)
- Apple：[Reducing networking and Bluetooth power usage](https://developer.apple.com/documentation/xcode/reducing-networking-and-bluetooth-power-usage)
- Apple：[Choosing background strategies for your app](https://developer.apple.com/documentation/backgroundtasks/choosing-background-strategies-for-your-app)
- Apple：[Extending your app's background execution time](https://developer.apple.com/documentation/uikit/extending-your-app-s-background-execution-time)
- Apple：[BGContinuedProcessingTask](https://developer.apple.com/documentation/backgroundtasks/bgcontinuedprocessingtask)
- Apple：[URLSessionConfiguration.waitsForConnectivity](https://developer.apple.com/documentation/foundation/urlsessionconfiguration/waitsforconnectivity)
- Apple：[Timer.tolerance](https://developer.apple.com/documentation/foundation/timer/tolerance)
- Apple：[Analyzing your app's battery use](https://developer.apple.com/documentation/xcode/analyzing-your-app-s-battery-use)
