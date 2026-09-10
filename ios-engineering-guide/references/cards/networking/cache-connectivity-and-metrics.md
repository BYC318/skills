---
id: cache-connectivity-and-metrics
tags: [iOS, URLSession, URLCache, HTTP cache, Low Data Mode, Instruments]
triggers:
  - URLCache、Cache-Control、ETag 或缓存策略
  - 重复请求、网络流量、连接复用或请求变慢
  - Low Data Mode、蜂窝网络、热点、无网或网络切换
  - URLSessionConfiguration、waitsForConnectivity 或 task metrics
applies_to: [UIKit, SwiftUI, Swift, Objective-C]
status: verified
last_verified: 2026-09-10
---

# HTTP 缓存、连接策略与任务度量

## 触发条件

- 创建或修改 `URLSession`、`URLCache`、请求缓存策略或离线读取。
- 应用重复下载相同资源、弱网体验差、流量或网络耗电异常。
- 后台预取、批量同步等可延迟工作需要服从 Low Data Mode 或昂贵网络限制。
- 需要判断耗时来自 DNS、连接、TLS、服务器响应、重定向还是本地缓存。

## 稳定结论

- HTTP 缓存通过复用新鲜响应或验证已有响应降低延迟与流量；默认的 `useProtocolCachePolicy` 会依据协议缓存语义工作。
- `URLCache` 同时支持内存和磁盘缓存，但缓存可被清理，不能承担业务数据真相或离线正确性的唯一来源。
- 网络“可用”、是否昂贵和是否受 Low Data Mode 约束是不同属性；可延迟流量应尊重用户选择，用户主动请求则按产品承诺决定是否允许。
- `waitsForConnectivity` 只处理建连阶段的等待；已建立连接随后中断仍会返回错误。后台 session 本身会等待连接。
- `URLSessionTaskMetrics` 和 HTTP Traffic Instrument 能区分本地缓存、连接复用、协议、重定向以及各阶段耗时，优先用证据定位网络慢点。

## 编码约束

- 除非有明确的新鲜度或安全要求，保留 `useProtocolCachePolicy` 并让服务端通过 Cache-Control、验证器和状态码表达缓存语义；不要习惯性忽略本地缓存。
- 按资源敏感性决定是否允许磁盘缓存。HTTPS 响应也可能被协议缓存写入磁盘；敏感内容需要明确存储策略或禁用对应缓存。
- 在创建 `URLSession` 前配置缓存、连接、超时和 constrained/expensive 网络策略；session 会复制 configuration，之后修改原对象不会改变已有 session。
- 非必要预取或维护任务可禁止 constrained/expensive 网络并配合 `waitsForConnectivity`；关键用户请求不可被全局策略静默挂起。
- 复用职责和策略相同的 session；为 session 与重要 task 设置稳定、无敏感数据的描述，便于 Instruments 归因。
- 采集 task metrics 时记录请求类别与结果，不记录凭据、完整 URL 查询、响应正文或其他用户敏感内容。

## 不适用或边界

- 离线业务状态、用户草稿和必须可靠保存的数据需要独立持久层，不能只依赖 `URLCache`。
- `returnCacheDataElseLoad` 和 `returnCacheDataDontLoad` 会改变新鲜度行为，只能在产品明确接受旧数据或纯离线读取时使用。
- background session 默认不使用 `URLCache`；ephemeral session 使用随 session 销毁的私有内存缓存。不同 session 类型不能假定具有相同缓存行为。
- 网络路径状态不能保证后续请求成功；连接、服务器和协议错误仍须由请求结果处理。

## 常见错误

- 所有 GET 都使用 `reloadIgnoringLocalCacheData`，造成重复传输和更慢首屏。
- 自建对象缓存、磁盘缓存和 `URLCache` 三层保存同一响应，却没有统一的新鲜度和失效规则。
- 将含账户或隐私数据的 HTTPS 响应无意写入磁盘缓存。
- 用网络监视器先判断“有网”再发请求，随后把真实连接失败当作不可能状态。
- 修改已经用于创建 session 的 configuration，误以为新策略立即生效。
- 只看总请求耗时，未区分 DNS、TLS、服务端等待、重定向、缓存命中和连接复用。

## 验证方法

1. 使用 HTTP Traffic Instrument 检查请求数量、缓存命中、连接复用、重定向、协议和响应头；trace 可能包含未加密的敏感内容，需受控保存。
2. 通过 `URLSessionTaskMetrics` 对同类请求比较 DNS、连接、TLS、请求与响应阶段，并记录 `resourceFetchType`。
3. 在设备开发者设置中覆盖 constrained/expensive 网络条件，验证可延迟工作、关键用户请求和错误提示均符合产品语义。
4. 测试缓存为空、响应新鲜、需要验证、缓存被系统清理、无网和连接中途丢失，确认状态与数据来源可解释。

## 官方来源

- Apple：[Accessing cached data](https://developer.apple.com/documentation/foundation/accessing-cached-data)
- Apple：[URLCache](https://developer.apple.com/documentation/foundation/urlcache)
- Apple：[URLSessionConfiguration](https://developer.apple.com/documentation/foundation/urlsessionconfiguration)
- Apple：[Analyzing HTTP traffic with Instruments](https://developer.apple.com/documentation/foundation/analyzing-http-traffic-with-instruments)
- Apple：[URLSessionTaskTransactionMetrics](https://developer.apple.com/documentation/foundation/urlsessiontasktransactionmetrics)
- IETF：[RFC 9111 — HTTP Caching](https://www.rfc-editor.org/rfc/rfc9111.html)

