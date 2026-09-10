---
id: reuse-and-scope
tags: [效率, 复用, 改动范围, 依赖]
status: verified
last_verified: 2026-09-10
---

# 复用与最小改动

## 触发条件

- 准备新增组件、缓存、调度器、扩展、工具或第三方依赖。
- 一个小需求开始扩大为跨模块重构。

## 稳定结论

编码效率主要来自复用已验证的边界、减少无关改动和缩短反馈周期，不来自提前建立更多抽象。

## 编码约束

- 先定位现有公共入口、相邻实现、平台 API 和已安装依赖。
- 明确当前调用方、输入输出、线程、取消、错误和生命周期边界。
- 能直接复用就不再封装；仅有轻微差异时做最小适配。
- 新抽象至少应解决两个真实调用方的共同问题，或隔离明确的安全/供应商边界。
- 保留业务行为，避免把性能猜测与功能改动混在一个补丁中。

## 不适用或边界

- “两个真实调用方”是抑制过早抽象的工程启发式，不是 Apple API 契约；单一调用方若需要隔离安全边界、系统差异或可替换供应商，也可以合理抽象。
- 是否复用必须以当前仓库的行为、测试、维护状态和依赖版本为准；名字相似不能证明语义兼容。
- 拆分模块有时能提高增量构建并行度，有时也会增加依赖和链接成本，必须先测量构建时间再调整结构。

## 常见错误

- 因为已有半成品就继续补完重复实现。
- 为可能永远不会出现的调用方设计配置项。
- 未测量就加入多级缓存、并发队列或复杂预加载。

## 验证方法

- 搜索仓库和依赖，记录实际复用点。
- 用最小测试覆盖新边界；检查 diff 是否包含无关格式化或重命名。
- 性能动机必须转到性能证据卡验证。

## 参考来源

- Apple：[Improving the speed of incremental builds](https://developer.apple.com/documentation/xcode/improving-the-speed-of-incremental-builds)
- Apple：[Improving build efficiency with good coding practices](https://developer.apple.com/documentation/xcode/improving-build-efficiency-with-good-coding-practices)
- Swift：[API Design Guidelines](https://www.swift.org/documentation/api-design-guidelines/)
