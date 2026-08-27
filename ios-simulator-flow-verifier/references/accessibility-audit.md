# 可选无障碍审计

## 默认策略

本专项默认关闭。只有满足以下任一条件时才读取和执行：

- 用户明确要求无障碍功能或无障碍审计；
- 需求文档把无障碍列为验收标准；
- 项目 `AGENTS.md` 或团队规范明确要求；
- 当前任务专门修复 VoiceOver、动态字体、点击区域、文字裁切、对比度或其他无障碍问题。

普通功能开发、普通 UI 修改和常规模拟器回归不运行无障碍审计，也不把无障碍结果列为交付门槛。

## 审计范式

```swift
let types: XCUIAccessibilityAuditType = [
    .dynamicType,
    .textClipped,
    .hitRegion,
    .sufficientElementDescription
]

try app.performAccessibilityAudit(for: types) { issue in
    false // 默认不屏蔽问题
}
```

只有明确要求时，才按任务范围补充 VoiceOver 阅读顺序、颜色对比度、减少动态效果、粗体文本或超大辅助字号等专项测试。

## 结果处理

- 从 xcresult 导出完整问题说明、应用截图和元素截图；
- 修复真实布局或语义问题，不得大范围屏蔽；
- 只有专用测试能够证明属于 Xcode 误报时，才添加范围严格的过滤规则；
- 最终报告列出审计类型、通过和失败数量、过滤项及 xcresult 路径。
