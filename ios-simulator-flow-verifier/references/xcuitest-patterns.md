# XCUITest 验证范式

## 目录

- 稳定启动
- 可视模拟器预检
- 页面观察检查点
- 语义定位与等待
- 有限滚动
- 数据修改与持久化
- 角色与权限检查
- 网络契约边界
- xcresult 证据

## 稳定启动

```swift
let app = XCUIApplication()
app.launchArguments = ["--ui-testing", "--demo"]
app.launchEnvironment["ANIMATIONS_DISABLED"] = "1"
app.launch()

let root = app.otherElements["home.root"]
XCTAssertTrue(root.waitForExistence(timeout: 8))
```

只重置测试环境拥有的状态。未经授权，不得删除开发者在模拟器中的其他数据。

## 可视模拟器预检

CoreSimulator 设备可以在 Simulator 没有可见窗口时保持 Booted。XCUITest 仍能注入事件，`simctl io` 和 xcresult 也仍能截图。需要让用户观看过程时，明确执行：

```bash
xcrun simctl boot "$DEVICE_ID" 2>/dev/null || true
xcrun simctl bootstatus "$DEVICE_ID" -b
open -a Simulator --args -CurrentDeviceUDID "$DEVICE_ID"
osascript -e 'tell application "Simulator" to activate'
```

测试 Destination 必须使用相同的 `$DEVICE_ID`。不要把 UUID 写进项目源码；每次从可用设备列表动态选择。默认优先使用 Simulator 当前窗口设备，避免自动化在另一台无头设备上运行。可视验证完成后保持 Simulator 打开，除非用户要求关闭。

只检查 `Simulator` 进程不够，因为进程存在时也可能没有设备窗口。可视模式还要检查屏幕上的 Simulator 窗口数量，并在当前窗口设备 UUID 与测试 UUID 不一致时中止测试和报告原因。

如果用户仍看不到画面，按顺序检查：

1. Simulator 进程是否存在；
2. 设备是否仍是 Booted；
3. 窗口是否在其他桌面空间或被最小化；
4. 窗口设备 UUID 是否与测试 Destination 一致；
5. Simulator 图形窗口是否与 CoreSimulator Framebuffer 失去同步。

## 页面观察检查点

将下面的辅助类型放在 UI Test Target 的共享测试工具中。它只在执行器注入可视观察环境变量时停留；无头运行和普通 Xcode 测试默认不等待。

```swift
import XCTest

enum FlowObservation {
    private static var isEnabled: Bool {
        ProcessInfo.processInfo.environment["IOS_FLOW_OBSERVATION_ENABLED"] == "1"
    }

    private static func duration(for key: String, fallback: TimeInterval) -> TimeInterval {
        guard let raw = ProcessInfo.processInfo.environment[key],
              let value = TimeInterval(raw) else { return fallback }
        return value
    }

    static func checkpoint(
        _ name: String,
        in testCase: XCTestCase,
        seconds: TimeInterval? = nil
    ) {
        hold(
            name,
            in: testCase,
            seconds: seconds ?? duration(
                for: "IOS_FLOW_STEP_OBSERVE_SECONDS",
                fallback: 2
            )
        )
    }

    static func finalCheckpoint(
        _ name: String,
        in testCase: XCTestCase,
        seconds: TimeInterval? = nil
    ) {
        hold(
            name,
            in: testCase,
            seconds: seconds ?? duration(
                for: "IOS_FLOW_FINAL_OBSERVE_SECONDS",
                fallback: 5
            )
        )
    }

    private static func hold(
        _ name: String,
        in testCase: XCTestCase,
        seconds: TimeInterval
    ) {
        guard isEnabled, seconds > 0 else { return }

        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = "人工观察：\(name)"
        attachment.lifetime = .keepAlways
        testCase.add(attachment)
        RunLoop.current.run(until: Date().addingTimeInterval(seconds))
    }
}
```

必须先断言页面稳定，再调用观察检查点：

```swift
let details = app.otherElements["details.root"]
XCTAssertTrue(details.waitForExistence(timeout: 8))
XCTAssertTrue(app.staticTexts["details.title"].exists)
FlowObservation.checkpoint("详情页完整展示", in: self)

app.buttons["details.confirm"].tap()
let completed = app.otherElements["result.success"]
XCTAssertTrue(completed.waitForExistence(timeout: 8))
FlowObservation.finalCheckpoint("成功结果页", in: self)
```

不要把观察停留写在断言之前，不要用它等待网络或动画，也不要在 `tearDown` 中补停留。并行测试时每个 Clone 会独立执行这些检查点，并在 xcresult 中留下各自的截图附件和临时设备 UUID。

## 语义定位与等待

```swift
let save = app.buttons["profile.save"]
XCTAssertTrue(save.waitForExistence(timeout: 5))
XCTAssertTrue(save.isHittable)
save.tap()

let completed = NSPredicate(format: "label CONTAINS %@", "Saved")
expectation(for: completed, evaluatedWith: app.staticTexts["profile.notice"])
waitForExpectations(timeout: 5)
```

优先使用标识符。只有在验证可见文案本身时，才优先使用本地化标题。

## 有限滚动

```swift
func reveal(_ element: XCUIElement, in app: XCUIApplication, attempts: Int = 5) {
    for _ in 0..<attempts where !element.isHittable { app.swipeUp() }
}
```

达到较小的次数上限后必须失败。无限循环会挂起 CI，并掩盖分页缺陷。

## 数据修改与持久化

```swift
app.switches["preferences.sync.toggle"].tap()
XCTAssertTrue(app.staticTexts["preferences.sync.enabled"].waitForExistence(timeout: 5))

app.navigationBars.buttons.firstMatch.tap()
app.buttons["settings.preferences"].tap()
XCTAssertTrue(app.staticTexts["preferences.sync.enabled"].exists)
```

测试 Gateway 应修改当前用户拥有的状态：

```swift
actor PreferenceFixture {
    private var values: [String: Bool] = [:]

    func set(_ value: Bool, for key: String) {
        values[key] = value
    }
}
```

## 角色与权限检查

必须验证权限两侧：

```swift
XCTAssertTrue(ownerApp.buttons["resource.manage"].exists)
XCTAssertFalse(visitorApp.buttons["resource.manage"].exists)
```

如果产品要求禁止操作完全不可见，就不能只把它设置成禁用状态。

## 网络契约边界

```swift
final class ContractURLProtocol: URLProtocol {
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let object = request.httpBody
            .flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] } ?? [:]
        let valid = request.url?.path.hasSuffix("/feature/set") == true
            && (object["id"] as? NSNumber)?.intValue == 42
            && object["legacyField"] == nil

        let body = valid
            ? #"{"code":0,"data":{}}"#
            : #"{"code":422,"msg":"contract mismatch","data":{}}"#
        let response = HTTPURLResponse(
            url: request.url!, statusCode: valid ? 200 : 422,
            httpVersion: "HTTP/1.1", headerFields: ["Content-Type": "application/json"]
        )!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(body.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}
```

当应用传输层使用流式请求体时，还要处理 `httpBodyStream`。

## xcresult 证据

```bash
xcrun xcresulttool get test-results summary --path Test.xcresult
xcrun xcresulttool get test-results activities \
  --path Test.xcresult --test-id 'Target/Suite/testName()'
xcrun xcresulttool export attachments \
  --path Test.xcresult --output-path /tmp/test-failures --only-failures
```

同时检查 `Complete Issue Description.txt`、应用截图和元素截图。
