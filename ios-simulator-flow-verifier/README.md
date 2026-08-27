# iOS 模拟器流程验证 Skill 使用教程

`ios-simulator-flow-verifier` 用于在一组 iOS 改动达到可验收节点后，通过真实 Simulator、XCTest/XCUITest 和 xcresult 证据验证业务流程。它不会把“编译成功”或“能够截图”当成功能正确，也不会在每次小改动后自动运行模拟器。

这是通用型 Skill。验证范围由当前代码改动、验收条件和项目现有测试体系决定，不预设具体业务页面、第三方 SDK 或专项容器。项目出现特殊能力时，在当前任务中按实际实现补充测试，不修改通用 Skill 的默认验收范围。

## 适用范围

- Swift、SwiftUI、UIKit 或混合项目
- `.xcworkspace` 和 `.xcodeproj`
- 页面跳转、按钮、表单、列表、弹窗和状态切换
- 网络请求、数据解码、权限、角色和持久化
- “编译成功但运行不起来”或“自动化能操作但看不到模拟器”的诊断

## 文件说明

```text
ios-simulator-flow-verifier/
├── SKILL.md                         Skill 执行规范
├── README.md                        使用教程
├── agents/openai.yaml               Codex 展示、默认提示词和显式调用策略
├── scripts/verify_ios_flow.sh       模拟器测试执行器
├── scripts/test_verify_ios_flow.sh  执行器无模拟器自测
├── references/xcuitest-patterns.md  XCUITest 和契约测试通用范式
└── references/accessibility-audit.md 可选无障碍专项，默认不读取
```

## 前置条件

使用前确认：

1. 已安装 Xcode 和目标 iOS Simulator Runtime。
2. `xcode-select -p` 指向要使用的 Xcode。
3. 项目存在可共享 Scheme。
4. 项目已经配置 Unit Test 或 UI Test Target；没有时可让 Codex 创建。
5. UI 流程中的关键控件具有稳定的 `accessibilityIdentifier`，仅用于 UI 测试定位。
6. 需要账号或固定数据的流程具备测试账号、Mock、Fixture 或依赖注入边界。

## 最简单的使用方式

`agents/openai.yaml` 已设置 `policy.allow_implicit_invocation: false`。Skill 不会被隐式触发，必须由用户通过 `$ios-simulator-flow-verifier` 显式调用；下文规则描述的是调用后如何选择验证时机和范围。

在 Codex 中直接输入：

```text
使用 $ios-simulator-flow-verifier 验证我刚修改的功能。
请先读取项目规则和代码改动，整理验收条件，补充必要测试，
然后以可视模式在模拟器点击完整业务流程，最后报告 xcresult 和剩余风险。
```

验证指定业务流程：

```text
使用 $ios-simulator-flow-verifier 验证个人资料保存。
在模拟器进入个人中心，修改昵称并保存，退出后重新进入，
确认新昵称仍然存在。必须让我看到点击过程。
```

## 什么时候运行

推荐在以下节点调用：

- 用户明确要求立即观看或验证模拟器流程；
- 一组关联修改已完成、准备交付且影响用户可观察行为；
- 当前任务明确诊断运行时问题，需要在模拟器重现；
- 唯一验证代理上次运行失败，修复后重跑失败旅程。

以下情况先不运行：

- 仍在连续修改同一个功能；
- 当前只是未完成的中间代码；
- 普通实现代理刚提交一次补丁；
- UI、架构、代码质量或安全 Review 子代理正在审核；
- 只改了注释、文档、格式或无行为影响的名称；
- 单元测试已经足以覆盖纯逻辑修改；
- 相同代码状态和测试旅程已经通过，没有相关文件继续变化。

## 推荐工作节奏

```text
连续实现多个关联改动
→ 记录待验证旅程
→ 使用静态检查或定向单元测试快速反馈
→ 完成整批改动并进入交付检查点
→ 委派唯一验证代理运行一次定向模拟器旅程
→ 其他 Review 代理复用同一 xcresult
→ 仅在高风险或里程碑运行全量测试
```

例如连续完成页面布局、按钮事件、状态更新和持久化时，不要分四次启动模拟器。四项形成完整流程后，一次验证“进入页面 → 操作 → 状态变化 → 重新进入后保持”即可。

## 验证层级

| 层级 | 验证方式 | 适用节点 |
| --- | --- | --- |
| L0 | Diff、类型、配置和资源静态检查 | 实现过程中的小改动 |
| L1 | 定向单元、解码或契约测试 | 纯逻辑或数据层修改 |
| L2 | 一条或少量定向模拟器旅程 | 完成一个可验收业务片段 |
| L3 | 直接相关的 UI 回归 | 修复缺陷或准备交付 |
| L4 | Scheme 全量测试 | 共享基础设施、里程碑或发布前 |

默认从最低层级开始。L1 能证明正确时，不升级到 L2；L2 已覆盖当前风险时，不运行 L4。

## 唯一验证代理

父代理在实现阶段累计待验证清单，不启动模拟器。准备交付时，如果改动影响用户可观察行为，只指定一个子代理为模拟器验证代理：

- 唯一验证代理负责模拟器、xcresult 和运行证据；
- 其他 UI、架构、代码质量和安全 Review 子代理只做静态审核；
- 所有 Review 代理复用同一个 xcresult；
- 唯一验证运行期间暂停同一工作区的实现修改；开始和结束指纹不同则结果无效；
- 没有可用子代理时，父代理在交付检查点临时承担验证角色；
- 失败修复后仍由同一验证角色只重跑失败测试。

委派内容必须包含触发原因、代码状态指纹、受影响功能、验证层级、目标测试、验收条件和已有 xcresult。默认使用 L2；共享导航、状态容器或跨功能基础设施变化才升级 L3；L4 只用于明确要求、里程碑或发布前。

## 避免重复运行

执行器会自动计算代码状态和测试范围指纹。每次通过后记录：

- 当前代码状态或 diff 摘要；
- 已运行测试标识符；
- 模拟器型号和系统；
- xcresult 绝对路径；
- 通过、失败和跳过数量。

如果相关生产代码、测试、Fixture、配置和资源均未变化，执行器直接复用上次 xcresult，不启动模拟器。只有相关行为继续变化、旧结果失败或验收范围扩大时才重新验证。只有用户明确要求、缓存损坏或确认偶发问题时使用 `--force`。

测试范围指纹还包含 Scheme、目标测试、模拟器、可视/无头模式、页面观察时长、启动参数和 Xcode 版本；例如从无头切换到可视观察时不会错误复用。非 Git 项目无法可靠计算代码状态，执行器会显示 `unavailable` 并关闭成功缓存，避免误用旧结果。

Git 忽略的外部配置、凭据、测试服务器或后端数据不会进入代码指纹；这些外部条件变化时必须使用 `--force`。

每个仓库同时只允许一个验证进程。另一个代理遇到锁冲突会收到状态码 `75`，应退出并等待唯一验证代理的 xcresult，不能再次启动。

验证期间工作区发生变化时返回状态码 `74`，不写成功缓存；应等实现改动稳定后再由唯一验证代理运行。`--force` 会使当前成功缓存失效，如果强制重跑失败，后续不会回退复用旧的成功结果。

## 验证流程

Skill 会按下面的证据链工作：

```text
读取仓库规则和代码改动
→ 明确可观察的验收条件
→ 检查或补充测试边界
→ 构建项目
→ 启动并显示指定模拟器
→ 安装、启动应用
→ 点击真实业务流程
→ 验证中间状态和最终结果
→ 必要时验证刷新、重启和持久化
→ 按需运行契约测试
→ 输出 xcresult、测试数量和未覆盖风险
```

## 可视模式

可视模式是本地执行的默认模式。它会：

- 优先选择 Simulator 当前窗口设备；
- 启动同一个动态 UUID 对应的设备；
- 打开并置前 Simulator；
- 检查屏幕上是否存在 Simulator 窗口；
- 测试开始前检查基础窗口设备 UUID 是否与测试 Destination 一致；
- 在页面断言成功后提供可配置的人工观察停留；
- 测试结束后保持 Simulator 打开。

命令示例：

```bash
~/.codex/skills/ios-simulator-flow-verifier/scripts/verify_ios_flow.sh \
  --workspace /绝对路径/App.xcworkspace \
  --scheme App \
  --verification-reason delivery-checkpoint \
  --visible \
  --only-testing AppUITests/AppJourneyTests/testChangedFlow
```

`--visible` 可以省略，因为它是默认模式。

如果检测到 Simulator 进程存在但没有屏幕窗口，或者当前窗口设备与测试 UUID 不一致，脚本会在测试开始前停止，避免自动化静默操作另一台设备。

## 并行 Clone 与页面停留

Xcode 开启并行测试时，可能创建多个 `Clone N of iPhone` 窗口。每个 Clone 是独立的测试 Worker，并拥有临时 UUID，这属于正常行为；Skill 不会禁止并行 Clone。基础设备一致性只在并行测试开始前校验，测试结果从 xcresult 分别报告各 Clone Worker。

为了让测试过程可观察，UI Test Target 需要复用 `references/xcuitest-patterns.md` 中的 `FlowObservation`：

```swift
let page = app.otherElements["feature.root"]
XCTAssertTrue(page.waitForExistence(timeout: 8))
XCTAssertTrue(app.staticTexts["feature.title"].exists)
FlowObservation.checkpoint("功能页面", in: self)

app.buttons["feature.submit"].tap()
let result = app.otherElements["result.success"]
XCTAssertTrue(result.waitForExistence(timeout: 8))
FlowObservation.finalCheckpoint("成功结果页", in: self)
```

默认停留时间：

- 每个主要中间页面：2 秒；
- 最终结果页面：5 秒。

调整时长：

```bash
verify_ios_flow.sh \
  --workspace App.xcworkspace \
  --scheme App \
  --verification-reason delivery-checkpoint \
  --observe-seconds 3 \
  --final-observe-seconds 8 \
  --full
```

停留只发生在页面断言成功后，用于人工查看，不参与加载等待和正确性判定。测试失败时不会为了展示而继续停留；最终停留必须放在 `tearDown` 或 `app.terminate()` 之前。

## 无头模式

无头模式用于 CI，或者用户明确不需要观看过程的场景：

```bash
~/.codex/skills/ios-simulator-flow-verifier/scripts/verify_ios_flow.sh \
  --project /绝对路径/App.xcodeproj \
  --scheme App \
  --verification-reason delivery-checkpoint \
  --headless \
  --full
```

无头模式下，XCUITest、`simctl` 截图和 xcresult 仍然能够工作，但不会主动打开 Simulator 窗口。

## 指定测试

下面使用 `verify_ios_flow.sh` 作为命令简称；如果没有把脚本目录加入 `PATH`，请替换成完整路径：

```text
~/.codex/skills/ios-simulator-flow-verifier/scripts/verify_ios_flow.sh
```

运行一个测试：

```bash
verify_ios_flow.sh \
  --workspace App.xcworkspace \
  --scheme App \
  --verification-reason delivery-checkpoint \
  --only-testing AppUITests/ProfileJourneyTests/testSaveProfile
```

运行多个测试时重复传入 `--only-testing`：

```bash
verify_ios_flow.sh \
  --workspace App.xcworkspace \
  --scheme App \
  --verification-reason user-request \
  --only-testing AppTests/ProfileStoreTests/testSave \
  --only-testing AppUITests/ProfileJourneyTests/testSaveProfile
```

运行 Scheme 中的全部测试：

```bash
verify_ios_flow.sh \
  --workspace App.xcworkspace \
  --scheme App \
  --verification-reason user-request \
  --full
```

## 其他常用参数

```text
--workspace PATH      Xcode Workspace 路径
--project PATH        Xcode Project 路径
--scheme NAME         要测试的共享 Scheme
--device-id UUID      指定可用模拟器
--device-name NAME    优先选择指定模拟器型号
--only-testing ID     指定测试，可重复传入
--full                运行完整 Scheme 测试
--derived-data PATH   指定 DerivedData 路径
--result PATH         指定 xcresult 路径
--verification-reason VALUE 实际执行原因，必填；dry-run 除外
--force               忽略相同代码和测试范围的成功缓存
--launch-arg VALUE    记录测试需要的启动参数，可重复传入
--visible             可视模式，默认值
--headless            无头模式
--observe-seconds N   中间页面人工观察秒数，默认 2
--final-observe-seconds N 最终页面人工观察秒数，默认 5
--no-observation      关闭人工观察停留
--verbose             显示完整 xcodebuild 日志
--dry-run             只解析设备和命令，不执行测试
```

`--verification-reason` 只接受：

```text
user-request
delivery-checkpoint
runtime-diagnosis
failure-rerun
```

`--force` 只绕过成功缓存，不绕过仓库级唯一验证锁。

查看最新参数：

```bash
~/.codex/skills/ios-simulator-flow-verifier/scripts/verify_ios_flow.sh --help
```

## 先用 dry-run 检查

首次接入项目时，建议先解析命令：

```bash
verify_ios_flow.sh \
  --workspace /绝对路径/App.xcworkspace \
  --scheme App \
  --only-testing AppUITests/AppJourneyTests/testChangedFlow \
  --dry-run
```

重点确认：

- Workspace 或 Project 路径正确；
- Scheme 正确；
- 模拟器型号和 UUID 符合预期；
- `-only-testing` 标识符正确；
- xcresult 和 DerivedData 路径可写。

## 为 UI 增加稳定标识符

SwiftUI：

```swift
Button("保存") {
    save()
}
.accessibilityIdentifier("profile.save")
```

这里使用 `accessibilityIdentifier` 是为了让 XCUITest 稳定定位控件，不代表要求应用支持无障碍功能，也不会自动触发无障碍审计。

UIKit：

```swift
saveButton.accessibilityIdentifier = "profile.save"
```

XCUITest：

```swift
let saveButton = app.buttons["profile.save"]
XCTAssertTrue(saveButton.waitForExistence(timeout: 5))
XCTAssertTrue(saveButton.isHittable)
saveButton.tap()
```

建议使用带业务命名空间的稳定标识符，例如：

```text
welcome.enter
profile.save
profile.nickname
order.submit
content.ready
content.retry
```

不要把绝对屏幕坐标作为主要选择器，也不要只依赖会变化或本地化的标题。

## 测试数据设计

UI 测试应使用确定性测试环境：

- 启动参数进入 UI 测试模式；
- 使用 Fixture、Mock Gateway 或测试服务器提供固定数据；
- 只替换网络、支付、认证等外部边界；
- 保留生产页面、路由、Store 和业务用例；
- Fixture 必须支持保存、关注、切换等真实状态修改；
- 需要验证持久化时，退出页面或重启应用后重新检查。

示例启动方式：

```swift
let app = XCUIApplication()
app.launchArguments = ["--ui-testing", "--demo"]
app.launchEnvironment["ANIMATIONS_DISABLED"] = "1"
app.launch()
```

脚本的 `--launch-arg` 会记录参数并提醒测试代码配置 `XCUIApplication.launchArguments`，不会绕过测试代码直接注入参数。

## xcresult 结果检查

默认结果目录：

```text
/tmp/ios-simulator-flow-verifier/results/
```

查看摘要：

```bash
xcrun xcresulttool get test-results summary --path Test.xcresult
```

查看指定测试活动：

```bash
xcrun xcresulttool get test-results activities \
  --path Test.xcresult \
  --test-id 'Target/Suite/testName()'
```

导出失败附件：

```bash
xcrun xcresulttool export attachments \
  --path Test.xcresult \
  --output-path /tmp/test-failures \
  --only-failures
```

失败时同时检查：

- `Complete Issue Description.txt`
- 应用截图
- 元素截图
- 测试活动和控制台日志
- 崩溃日志或启动失败原因

## 如何判断验证完成

最终报告至少应包含：

- 验证原因、代码状态指纹和测试范围指纹；
- 本次实际运行还是复用已有成功 xcresult；
- 模拟器型号、系统版本和动态 UUID；
- 可视模式或无头模式；
- 基础 Destination UUID、并行 Clone 数量、各 Worker 临时 UUID 以及页面观察停留时长；
- 验证过的用户旅程和中间检查点；
- 通过、失败和跳过测试数量；
- xcresult 绝对路径；
- 应用安装、启动及 PID；
- 网络契约或真实后端覆盖情况；
- 仍需真机或人工验证的能力。

只有编译成功、App 启动、自动化截图或单一成功流程通过时，不能宣称业务逻辑已经完整正确。

## 可选无障碍审计（默认关闭）

无障碍审计不属于普通模拟器流程的默认范围。没有用户明确要求、需求文档规定或项目规则要求时：

- 不运行 `XCUIAccessibilityAuditType`；
- 不新增无障碍专项测试；
- 不把无障碍结果列为交付门槛；
- 不为此扩大模拟器回归范围。

只有任务明确要求时，才读取 [references/accessibility-audit.md](references/accessibility-audit.md) 并按指定范围执行。

## 常见问题

### 自动化可以点击和截图，但肉眼看不到模拟器

原因通常是 CoreSimulator 已经无头启动，但 Simulator 没有设备窗口，或者窗口设备与测试设备不同。

处理方式：

```text
使用默认 --visible 模式；
不要只执行 simctl boot；
确认输出中的窗口 UUID 与测试 UUID 一致；
检查窗口是否被最小化或位于其他桌面空间。
```

### 编译成功但 App 没有启动

依次检查：

1. Scheme 是否包含正确 App Target；
2. Bundle Identifier 是否与启动命令一致；
3. 构建产品是否安装成功；
4. App 是否启动后立即崩溃；
5. 是否缺少运行时密钥、配置或动态 Framework；
6. xcresult 和模拟器日志是否记录了退出原因。

### 找不到按钮

检查：

- 是否配置了正确的 `accessibilityIdentifier`；
- 元素是否尚未加载；
- 元素是否在屏幕外；
- 是否被弹窗、键盘或 Sheet 覆盖；
- 控件是否处于不同的 UI 测试元素容器；
- 是否错误依赖了本地化标题。

### 测试偶发失败

不要首先增加固定 `sleep`。优先使用：

- `waitForExistence`
- `NSPredicate` 状态等待
- 有限次数滚动
- 明确的加载完成标识
- 确定性测试数据
- 禁用非必要动画

## 在项目中规定批量验收

可以在项目 `AGENTS.md` 增加：

```markdown
## iOS 模拟器验收

修改 Swift、SwiftUI、UIKit、导航、状态、网络、持久化、权限
或其他用户可观察行为时，父代理先累计待验证清单。实现阶段不启动模拟器；
整批改动完成、准备交付时，只委派一个子代理作为模拟器验证代理。

不得每修改少量代码就启动模拟器。实现过程中优先使用静态检查和定向单元测试；
普通 UI、架构、代码质量和安全 Review 子代理不得各自运行模拟器，必须复用唯一验证代理的 xcresult。

唯一验证代理默认执行 L2 定向旅程；共享导航、状态容器或跨功能基础设施变化时升级 L3；
L4 全量测试只用于用户明确要求、里程碑或发布前。

实际执行必须传入 --verification-reason。相同代码状态和测试范围已有成功结果时直接复用；
锁冲突返回 75 后等待现有验证代理，不得重新启动。只有明确要求重新运行时使用 --force。

本地默认使用可视模式，让用户看到模拟器点击和跳转过程。
只有 CI 或用户明确要求时才能使用无头模式。

不得只以编译成功、截图或单一成功流程作为完成依据。
最终必须报告测试范围、结果数量、模拟器 UUID、xcresult 路径和未覆盖风险。
```

## 能力边界

以下能力可能仍需真机或外部环境：

- 相机和部分媒体采集能力
- 蓝牙、NFC 和特定硬件
- APNs 生产推送
- 真实 StoreKit 支付链路
- 第三方登录真实回调
- 多设备实时通信
- 生产证书、账号和服务端权限

Skill 会把这些内容列为未覆盖风险，不会虚假报告已经完成。
