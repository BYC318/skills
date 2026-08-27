---
name: commenting-business-intent
description: Use when creating, modifying, refactoring, or reviewing code whose business behavior, constraints, edge cases, side effects, lifecycle, compatibility, or non-obvious design decisions must remain understandable, especially around comments, documentation comments, TODOs, magic values, status gates, pagination, ordering, retries, permissions, and error handling.
---

# 业务意图注释

## 核心原则

先理解业务，再决定是否注释。注释必须来自可追溯证据，并解释代码无法自行表达的原因、约束或影响；不得用猜测填补上下文。

## 每次代码改动的门禁

1. 先阅读需求、相关实现、调用方、类型/接口契约、测试和项目约定，确认改动的输入、状态变化、输出、副作用及失败行为。
2. 将认知在内部区分为“已证实事实 / 待验证推断 / 未知”。只有事实可以写成业务结论。
3. 检查改动是否包含非显然的业务规则、边界、顺序、生命周期、并发、安全、兼容、外部协议或保留旧行为的原因。
4. 未命中这些语义热点时，不强行增加注释；优先用命名和结构让代码自解释。
5. 命中时，必须完整阅读 [注释质量规则](references/comment-quality.md)，再同步编写或更新代码与注释。

## 证据边界

- 优先使用用户确认的需求、正式契约、测试、调用链、参考实现和相邻代码共同证明业务含义。
- 字段名、魔法值、常见行业做法、单次运行结果和个人经验都不是充分业务证据。
- 证据不足时继续调查；仍无法确认时，优先不写注释。只有局部技术约束非显然且会影响维护决策时，才精确描述可观察行为及其作用范围。不得把 `state == 3` 写成“封禁”，也不得把布尔表达式逐句翻译成中文，或把“当前函数未使用 source”扩大为“来源不影响业务”。
- 将未确认项和调查缺口写入交付说明或 review 结论，不得用“含义未知、未找到文档”充当源码注释。只有用户授权且具备明确跟踪依据、风险或退出条件时才留下 TODO。

## 完成检查

- 注释与最新实现同步，reviewer 能看懂“为什么、何时、有什么影响”。
- 注释不逐行翻译语法，不重复名称，不承诺未经证实的产品规则。
- 修改行为时同步修改相关注释；注释已失真时删除或重写。
- 遵循目标仓库的注释语言、文档注释格式、lint 和敏感信息规则。
