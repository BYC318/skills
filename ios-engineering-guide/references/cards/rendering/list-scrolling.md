---
id: list-scrolling
tags: [UIKit, UITableView, UICollectionView, 复用, 预取, 滚动]
status: verified
last_verified: 2026-09-10
---

# 列表滚动性能

## 触发

- 创建或修改 `UITableView`、`UICollectionView`、Cell、Supplementary View。
- 列表包含网络图片、富文本、动态高度或复杂布局。
- 快速滚动时出现白块、错图、闪烁、卡顿或内存持续增长。

## 结论

- Cell 配置路径应只组合已经准备好的展示数据；I/O、图片解码和昂贵计算不应占用滚动关键路径。
- 复用、异步加载、预取和取消必须成套设计。预取只是提前通知，不保证每个 Cell 都会收到。
- 流畅度用真实操作下的 hitch 和响应性判断，不能由复用标识存在或平均 FPS 推断。

## 约束

- 使用复用 API；`prepareForReuse()` 只重置可复用状态，不启动新的业务请求。
- Cell 配置应幂等，并以稳定内容身份绑定结果；异步回调前再次确认 Cell/模型身份，防止旧结果覆盖新内容。
- `cellFor...` 必须能处理“已预取、正在预取、未预取”三种状态，不依赖预取一定发生。
- 实现预取时同步实现取消；页面离开、数据失效和 Cell 不再需要内容时，停止不再有价值的工作。
- 后台准备纯数据，最终 UIKit 视图更新回到主线程；避免每个 Cell 生成无界并发任务。
- 更新列表时保持数据源与 UI 一致，合并可合并的变更，避免滚动期间反复全量 reload。

## 边界

- 预取适合可预测且有成本的数据准备；廉价数据或高速变化的数据不一定受益。
- 预计算高度、缓存布局或栅格化是否有效取决于内容变化和测量结果，不能作为默认规则。
- SwiftUI 列表的身份、更新频率和 `body` 成本也会导致 hitch，但其诊断应结合 SwiftUI Instrument。

## 常见错误

- 在 `cellForRowAt` / `cellForItemAt` 同步读磁盘、解码大图或格式化大量内容。
- 仅按 `IndexPath` 绑定请求；插入、删除或复用后将结果写到错误 Cell。
- 开启预取却不取消，导致快速滚动制造更多 CPU、网络和内存压力。
- 无差别调用 `reloadData()`，或在滚动回调中持续触发布局与图片请求。
- 为“优化”增加永久高度/图片缓存，却没有容量上限和失效规则。

## 验证

- 在真实设备上用接近生产的数据量连续快速滚动、反向滚动并频繁进入退出页面。
- 使用 Hitches 和 Time Profiler 定位主线程长任务；需要时结合 Allocations 检查对象和图片是否持续累积。
- 通过限速/延迟网络验证复用正确性、占位状态和取消；检查错图、闪烁及过期回调。
- 分别记录 60 Hz 与支持 120 Hz 设备的 hitch，而不是只记录平均 FPS。

## 来源

- [UICollectionView — Data prefetching](https://developer.apple.com/documentation/uikit/uicollectionview)
- [UITableViewDataSourcePrefetching](https://developer.apple.com/documentation/uikit/uitableviewdatasourceprefetching)
- [Improving app responsiveness](https://developer.apple.com/documentation/xcode/improving-app-responsiveness)
- [Understanding and improving SwiftUI performance](https://developer.apple.com/documentation/xcode/understanding-and-improving-swiftui-performance)
