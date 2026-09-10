---
id: request-correctness-and-retry
tags: [iOS, URLSession, HTTP, retry, idempotency, timeout, cancellation]
triggers:
  - 新增或修改 API 请求、上传、提交、重试或超时
  - 弱网、连接中断、重复提交或响应乱序
  - POST、PUT、DELETE 或具有业务副作用的操作
  - HTTP 状态码、MIME 类型或响应模型校验
applies_to: [UIKit, SwiftUI, Swift, Objective-C]
status: verified
last_verified: 2026-09-10
---

# 网络请求正确性与有界重试

## 触发条件

- 实现请求封装、自动重试、上传提交、分页刷新或认证后的业务操作。
- 需要处理超时、连接丢失、服务器错误、取消或旧响应覆盖新状态。
- 同一用户动作可能因连点、恢复、重试或调用方重复订阅而发出多次。

## 稳定结论

- 传输成功不等于业务成功：先区分传输错误，再校验 HTTP 状态、预期内容类型和响应体语义。
- 自动重试必须以请求的实际幂等性为前提。HTTP 的安全方法以及 PUT、DELETE 在协议语义上是幂等的；非幂等请求只有在业务协议能保证重复执行安全，或能确认原请求未生效时才可自动重试。
- 超时与连接中断通常无法证明服务器没有执行请求；对支付、发布、创建等副作用操作，客户端重试需要服务端幂等键、资源版本或结果查询契约。
- 重试是一个有生命周期的操作：必须有尝试上限、总时间边界、取消传播和最终错误；不能无限递归或固定频率持续请求。
- 取消、过期结果、传输故障、HTTP 失败和解码失败是不同状态，不应统一映射成“网络错误”。

## 编码约束

- 请求完成后按顺序检查传输错误、`HTTPURLResponse` 状态、MIME/内容约束，再解码业务数据；保留服务器可诊断信息但不泄露敏感内容。
- 为副作用请求显式记录幂等依据；若服务端没有幂等契约，不因“连接断开得早”就猜测可以重试。
- 仅对策略明确的暂时性失败重试，并遵守服务器提供的 `Retry-After`；限制尝试次数和总体资源时间，任务取消后立即停止后续尝试。
- 每次重试创建新的任务，但保留同一业务请求身份；提交 UI 或状态前同时校验取消状态与当前请求身份。
- `timeoutIntervalForRequest` 与 `timeoutIntervalForResource` 按交互语义设置；不要用一个很短的全局值覆盖上传、下载和前台查询等不同操作。
- 相同读取请求需要合并时，缓存键或合并键必须包含会影响结果的认证、参数和表示信息，并保证单个订阅者取消不会错误取消其他仍需结果的调用方。

## 不适用或边界

- HTTP 方法的协议幂等性描述“预期服务端效果”，不表示每个具体后端实现都正确；异常接口仍需按服务端契约处理。
- 4xx 或 5xx 是否可重试取决于具体状态和业务语义，不能按状态码首位建立无条件规则。
- `Retry-After` 可以是日期或秒数，且只是何时再次尝试的服务器指示，不是客户端无限等待或必然成功的承诺。
- 用户主动点击“重试”不等于自动重试安全；副作用操作仍需避免重复执行。

## 常见错误

- 只检查 `error == nil` 就把任意 HTTP 响应当作成功。
- 对所有错误统一重试三次，包括取消、鉴权失败、参数错误和非幂等提交。
- 连接超时后重新 POST，导致重复下单、重复发布或重复写入。
- 每次尝试生成新的业务幂等键，使服务端无法识别同一操作。
- 页面离开后重试链继续运行，最终把旧结果写回新页面或新账号。
- 多层网络封装各自重试，造成尝试次数相乘和请求风暴。

## 验证方法

1. 分别模拟 DNS/断网、建连失败、连接中途断开、超时、HTTP 错误、畸形响应、取消和正常成功。
2. 对副作用请求让服务器已执行但客户端未收到响应，再触发恢复流程，验证不会重复产生业务结果。
3. 记录一次用户动作对应的业务请求身份、实际网络任务数、重试原因和最终状态，确认上限与取消有效。
4. 使用 URLSession task metrics 或 HTTP Traffic Instrument 检查重定向、连接复用、每次尝试的时序和实际请求数量。

## 官方来源

- Apple：[Fetching website data into memory](https://developer.apple.com/documentation/foundation/fetching-website-data-into-memory)
- Apple：[URLSessionConfiguration](https://developer.apple.com/documentation/foundation/urlsessionconfiguration)
- Apple：[URLSessionTaskMetrics](https://developer.apple.com/documentation/foundation/urlsessiontaskmetrics)
- IETF：[RFC 9110 — HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110.html)

