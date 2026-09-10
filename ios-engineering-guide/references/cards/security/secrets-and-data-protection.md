---
id: secrets-and-data-protection
tags: [iOS, security, Keychain, Data-Protection, ATS, credentials, secrets]
triggers:
  - 保存密码、访问令牌、私钥或敏感用户数据
  - 新增 UserDefaults、文件缓存或数据库持久化
  - 配置 ATS、证书校验或网络安全例外
  - 日志、埋点、崩溃报告可能包含敏感字段
applies_to: [UIKit, SwiftUI, Swift, Objective-C]
status: verified
last_verified: 2026-09-10
---

# 凭据与本地数据保护

## 触发条件

- App 接收、缓存、更新或删除认证凭据、令牌和密码学密钥。
- 将个人或敏感数据写入 UserDefaults、文件、数据库、日志或共享容器。
- 为网络连接添加 ATS 例外、自定义服务端信任或证书固定。

## 稳定结论

- `UserDefaults` 用于非敏感偏好，不提供秘密存储所需的访问控制契约；小型密码、令牌和密钥应使用 Keychain。
- Keychain 的 `kSecAttrAccessible` 应选择满足功能的最严格级别。只有锁屏后台访问确有必要时，才放宽到首次解锁后可用；不需迁移或同步的高敏感项优先考虑 `ThisDeviceOnly` 级别。
- 大块敏感文件使用 iOS Data Protection，并依据锁屏、重启和后台访问需求选择文件保护等级；Keychain 不应被当作大对象数据库。
- ATS 默认保护 URL Loading System 的网络连接。优先修复服务端；确需例外时只放宽到最小域和最小能力，不全局启用任意加载。
- 客户端随包分发的字符串、资源或配置不能被当作服务器秘密。需要保密的长期凭据留在服务端，App 只持有范围受限、可撤销且生命周期合适的用户或设备凭据。

## 编码约束

- 按数据分类确定存储、备份/同步、访问时机、注销删除和失效更新策略，再选择 Keychain 或文件保护等级。
- Keychain 查询明确 `service`、`account`、access group 和 accessibility，区分“未找到”与真实系统错误；凭据变化后更新，注销时删除。
- 敏感值不写源码、Info.plist、UserDefaults、普通缓存、日志、埋点、剪贴板或错误描述；调试输出也使用脱敏值。
- 网络优先使用 `URLSession` 和系统信任评估。自定义 challenge 处理只能收紧或满足明确威胁模型，不能接受任意证书。
- 数据离开内存、设备或进程边界前重新判断是否必要，并最小化收集、保留时间和共享范围。

## 不适用或边界

- Keychain 和 Data Protection 降低静态数据暴露风险，不能防止已解锁设备上正在运行的受控进程读取其自身可访问数据。
- Secure Enclave 适合受支持的密钥操作，不是任意秘密或业务数据的通用存储空间。
- 证书固定会增加轮换和可用性风险；没有明确威胁模型、备份密钥与轮换方案时不默认加入。
- 具体 accessibility、access group、备份与后台行为必须按目标系统和 entitlement 验证。

## 常见错误

- 把 token、密码或私钥存入 UserDefaults，或只做 Base64/字符串混淆。
- 把第三方服务的长期管理密钥硬编码进 App，认为代码混淆即可保密。
- 为解决一次连接失败设置 `NSAllowsArbitraryLoads = true`，或跳过系统服务端信任验证。
- 所有 Keychain 项都使用宽松可访问级别，未考虑设备锁定、迁移和 iCloud 同步。
- 登出只清 UI 状态，未删除 Keychain、敏感缓存和仍持有凭据的后台任务。

## 验证方法

- 审计源码、构建产物、Info.plist、UserDefaults、日志和分析事件，确认不包含真实凭据或敏感明文。
- 在锁屏、重启后首次解锁前、后台执行、升级和重装等场景验证 Keychain 与文件访问行为。
- 测试凭据新增、读取、更新、过期、注销删除以及账号切换，确认不会复用旧账号秘密。
- 使用 ATS 诊断定位连接失败，检查例外是否限定到目标域；用无效、过期和主机名不匹配证书验证连接会失败。
- 对客户端无法保密的配置进行服务端权限与撤销测试，不以二进制中“难以搜索”作为安全证据。

## 官方来源

- [Apple: UserDefaults](https://developer.apple.com/documentation/foundation/userdefaults)
- [Apple: Using the keychain to manage user secrets](https://developer.apple.com/documentation/security/using-the-keychain-to-manage-user-secrets)
- [Apple: Restricting keychain item accessibility](https://developer.apple.com/documentation/security/restricting-keychain-item-accessibility)
- [Apple: Encrypting your app's files](https://developer.apple.com/documentation/uikit/encrypting-your-app-s-files)
- [Apple: Preventing insecure network connections](https://developer.apple.com/documentation/security/preventing-insecure-network-connections)
