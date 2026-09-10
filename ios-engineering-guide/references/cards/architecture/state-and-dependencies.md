---
id: state-and-dependencies
tags: [architecture, state, dependency-injection, UIKit, SwiftUI, testability]
triggers:
  - 新页面、Feature 或业务模块
  - ViewModel、Store、Coordinator 或 Service 重构
  - 状态不同步、重复请求或难以测试
  - 新增全局单例或跨层依赖
applies_to: [UIKit, SwiftUI, Swift]
status: verified
last_verified: 2026-09-10
---

# 状态所有权与依赖边界

## 稳定结论

- 每份可变业务状态应有一个权威所有者；其他层读取快照、派生值或观察变化，不维护可独立漂移的副本。
- 视图负责呈现状态和发送用户意图；业务规则、持久化与网络生命周期不应依赖具体 View/ViewController 实例。
- 依赖从组合根显式注入能暴露模块需求、替换测试实现并控制生命周期；全局可变单例会隐藏依赖和共享状态。
- Observation、Combine 或通知只是变化传播机制，不决定状态归属、线程隔离或业务边界。
- 架构边界服务于变化与验证成本；不要为了模式本身增加无业务意义的协议、层级和转发对象。

## 编码约束

- 先写清状态所有者、合法状态与事件，再选择 UIKit/SwiftUI 的绑定机制；派生状态尽量由源状态计算。
- 必需依赖使用初始化注入；可选能力明确为可选；短生命周期对象使用工厂或闭包注入。
- 在 App/Scene/Feature composition root 组装具体实现，业务对象依赖最小能力接口，不在深层代码中查找容器。
- 状态变更集中到有限入口，保持“检查前置条件—更新状态—发出副作用”顺序可推理；UI 状态通常隔离到 `@MainActor`。
- 网络 DTO、持久化模型、领域状态和显示模型仅在职责确有差异时分离，并把转换放在边界处。
- 明确依赖生命周期：应用级、会话级、页面级或单次操作级；退出/切换时释放观察、任务和缓存。

## 边界

- 系统提供的稳定单例与无状态纯工具不必机械包装；只有替换、控制生命周期或隔离副作用有实际价值时才建立抽象。
- 简单局部 UI 状态可以由视图拥有；跨页面、需持久化或驱动业务副作用的状态应提升到合适作用域。
- 单向数据流、MVC、MVVM 等名称不是验收标准；以所有权清晰、依赖可见、状态一致和可测试为准。
- SwiftUI `@State`、`@Environment` 等具体所有权语义应按目标系统版本的官方文档选择，不能混用包装器解决生命周期问题。

## 常见错误

- ViewController、ViewModel、缓存和单例都保存并修改同一份业务状态。
- 用 Service Locator 或全局容器在任意位置取依赖，导致测试与生命周期不可见。
- 为每个类型创建协议和仓库层，却只有一个实现且没有边界价值。
- 网络回调直接修改已离开的页面，或依赖对象比所属账号/会话活得更久。
- 把加载、空内容、错误和已有内容混成多个互相矛盾的布尔值。

## 验证

- 画出关键状态的唯一写入者、读取者和副作用，确认没有未同步副本或反向依赖。
- 使用内存实现替换网络/存储依赖，测试成功、空结果、错误、取消、重试和乱序返回，不启动真实 UI 或网络。
- 运行页面进入—退出—重进、账号切换和多次刷新场景，确认旧任务与观察不会写入新作用域。
- 用 Memory Graph/生命周期断言确认 Feature 释放；用主线程与并发检查验证 UI 状态隔离。

## 官方来源

- [Apple: Managing model data in your app](https://developer.apple.com/documentation/swiftui/managing-model-data-in-your-app)
- [Apple: UIKit and AppKit apps](https://developer.apple.com/documentation/technologyoverviews/uikit-appkit)
- [The Swift Programming Language: Concurrency](https://docs.swift.org/swift-book/documentation/the-swift-programming-language/concurrency/)
- [Swift API Design Guidelines](https://www.swift.org/documentation/api-design-guidelines/)
