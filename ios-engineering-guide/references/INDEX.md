# iOS 工程知识索引

任何 iOS 编码任务都先根据目标代码、计划采用的 API、数据流、生命周期和交互路径选择卡片，用于编码前预防问题；不要求用户提供下方术语，也不等待故障出现。默认最多 3 张，复杂任务最多 5 张，不遍历全部卡片。下方组合命中时优先采用组合，不机械追加相邻主题。

## 快速路由

| 实现信号（由 AI 从任务与代码推导） | 优先读取 | 相关检查清单 |
|---|---|---|
| 新增通用组件、准备自行封装、改动范围可能膨胀 | [复用与最小改动](cards/engineering/reuse-and-scope.md) | [编码前检查](../checklists/before-coding.md) |
| 远程图片、大图、头像、相册、图片列表、图片解码或缓存；内存峰值同样适用 | [图片与缓存](cards/memory/image-and-cache.md) | [内存检查](../checklists/memory-review.md) |
| 闭包、Timer、Delegate、观察者、异步所有权与页面生命周期；不能释放时同样适用 | [生命周期与泄漏](cards/memory/lifecycle-and-leaks.md) | [内存检查](../checklists/memory-review.md) |
| 主线程计算、频繁 UI 更新、滚动、逐帧或动画关键路径；掉帧卡顿时同样适用 | [帧预算与 Hitch](cards/rendering/frame-budget-and-hitches.md) | [性能证据](../checklists/performance-verification.md) |
| 同步 I/O、锁、信号量、group wait、QoS 依赖；点击冻结时同样适用 | [Hang 与优先级反转](cards/responsiveness/hangs-and-priority-inversion.md) | [性能证据](../checklists/performance-verification.md) |
| UITableView、UICollectionView、复杂 Cell、预取 | [列表滚动](cards/rendering/list-scrolling.md) | [滚动检查](../checklists/scrolling-review.md) |
| layoutSubviews、draw、CALayer、阴影、圆角、离屏渲染 | [布局绘制与合成](cards/rendering/layout-drawing-offscreen.md) | [性能证据](../checklists/performance-verification.md) |
| 转场、手势、弹簧、动画中断、连续点击 | [自然且可中断的动画](cards/animation/natural-interruptible.md) | [动画检查](../checklists/animation-review.md) |
| Timer、轮询、定位、传感器、后台任务、频繁网络 | [耗电与唤醒](cards/energy/timers-network-background.md) | [耗电检查](../checklists/energy-review.md) |
| 相机、定位、传感器、持续 CPU/GPU 或高帧率负载；发热、降频和 Low Power Mode 同样适用 | [热状态与低电量降级](cards/energy/thermal-and-low-power-adaptation.md) | [耗电检查](../checklists/energy-review.md) |
| async/await、Task、actor、MainActor、Sendable | [结构化并发](cards/concurrency/structured-concurrency.md) | [编码前检查](../checklists/before-coding.md) |
| Swift 6.2、默认隔离、@concurrent、nonisolated、隔离协议报错 | [Swift 6.2 隔离语义](cards/concurrency/swift-6-2-isolation.md) | [编码前检查](../checklists/before-coding.md) |
| AsyncStream、通知/Delegate 流、Socket、传感器流、缓冲增长 | [AsyncStream 缓冲与生命周期](cards/concurrency/async-stream-buffer-and-lifecycle.md) | [内存检查](../checklists/memory-review.md) |
| 页面退出、Cell 复用、搜索联想、请求覆盖、旧回调 | [任务取消与结果时效](cards/concurrency/task-cancellation.md) | [编码前检查](../checklists/before-coding.md) |
| HTTP 状态、响应验证、错误分层、幂等重试、指数退避 | [请求正确性与重试](cards/networking/request-correctness-and-retry.md) | [编码前检查](../checklists/before-coding.md) |
| URLCache、Cache-Control、ETag、Low Data Mode、弱网、请求指标 | [缓存、连接与网络指标](cards/networking/cache-connectivity-and-metrics.md) | [耗电检查](../checklists/energy-review.md) |
| JSON/plist 保存、日志文件、缓存目录、数据库批量写入与文件生命周期 | [磁盘写入与文件生命周期](cards/storage/disk-writes-and-file-lifecycle.md) | [性能证据](../checklists/performance-verification.md) |
| 冷启动、首屏、初始化、pre-main/post-main | [启动性能](cards/startup/launch-performance.md) | [性能证据](../checklists/performance-verification.md) |
| 状态归属、模块边界、依赖方向、重复请求 | [状态与依赖边界](cards/architecture/state-and-dependencies.md) | [编码前检查](../checklists/before-coding.md) |
| @Observable、Observation、SwiftUI/UIKit 状态追踪与更新范围；无效刷新时同样适用 | [Observation 更新范围与隔离](cards/observation/update-scope-and-isolation.md) | [性能证据](../checklists/performance-verification.md) |
| Keychain、token、密码、私钥、文件保护、ATS | [秘密与数据保护](cards/security/secrets-and-data-protection.md) | [编码前检查](../checklists/before-coding.md) |
| OSLog、日志隐私、signpost、MetricKit、Organizer、线上性能回归 | [日志、Signpost 与 MetricKit](cards/observability/logging-signposts-and-metrickit.md) | [编码前检查](../checklists/before-coding.md)；只有性能测量/回归再读[性能证据](../checklists/performance-verification.md) |
| 准备改变缓存、并发度、算法、线程或渲染策略；性能验收与回归同样适用 | [性能证据边界](cards/validation/performance-evidence.md) | [性能证据](../checklists/performance-verification.md) |

## 编码前组合建议

- 图片列表：图片与缓存 + 列表滚动 + 任务取消。列表卡已包含 hitch 测量；只有任务直接修改渲染循环/主线程调度，或需要诊断列表之外的未知 hitch 时，才替换或追加帧预算卡。
- 远程动画页面：帧预算 + 自然动画 + 任务取消；远程状态另交 `remote-page-development`。
- 批量图片或媒体处理：图片与缓存 + 生命周期与泄漏 + 性能证据。
- 高频轮询页面：耗电与唤醒 + 结构化并发 + 任务取消。
- 启动优化：启动性能 + 性能证据；只有确认涉及图片时才加图片卡。
- 带自动重试、缓存或弱网策略的远程请求：请求正确性与重试 + 缓存、连接与网络指标 + 任务取消。
- 包含同步 I/O、锁等待或重计算的交互路径：Hang 与优先级反转 + 帧预算与 Hitch + 性能证据。
- 高频事件流：AsyncStream 缓冲与生命周期 + 结构化并发 + 生命周期与泄漏。
- Swift 6.2 并发迁移：Swift 6.2 隔离语义 + 结构化并发；只有涉及页面或请求生命周期时才追加任务取消。
- 状态驱动 UI：Observation 更新范围与隔离；只有存在高频变化或昂贵更新路径时再加帧预算与性能证据。
- 新增线上性能观测：日志、Signpost 与 MetricKit + 性能证据 + 命中的具体领域卡。

## 不适用示例

- 修改 Codable 字段映射：本库加载 0 张卡并退出；继续按仓库规则执行编译、解码兼容性和相关测试。
- 调整用户可见颜色或普通约束：优先使用现有 Swift/UIKit 专项技能；只有目标代码还涉及本索引中的实现信号时才加载对应卡片。
- 单纯修正文案：不加载本库。
- 没有卡片能改变当前实现或验证决策：保持 0 张，不为“预防”泛读相邻主题。
