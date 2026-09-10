---
id: image-and-cache
tags: [iOS, UIKit, SwiftUI, ImageIO, NSCache, memory]
status: verified
last_verified: 2026-09-10
---

# 控制图片解码与缓存的内存占用

## 触发条件

- 加载相册、相机、文件或网络中的大尺寸位图。
- 列表、瀑布流、头像墙等场景同时展示或预取多张图片。
- 使用 `UIImage`、`CGImageSource`、`NSCache` 或第三方图片缓存。
- 内存峰值、滚动卡顿、内存警告或 Jetsam 与图片路径相关。

## 稳定结论

- 压缩后的文件大小不等于解码后的内存占用；应按输入像素、目标显示像素和实际测量判断成本。
- 当源图明显大于展示尺寸时，优先从图片源生成目标像素附近的缩略图，避免先完整解码再缩放。
- 内存风险不仅来自缓存总量，也来自单个响应、解码后像素规模，以及同时进行的下载、解码和变换数量。
- 相同资源的并发请求可以合并底层下载或解码工作，但每个使用者仍需独立管理取消和结果身份。
- 内存缓存是可丢弃的加速层，不是数据真相。命中、淘汰和重建都必须保持业务正确。
- `NSCache.totalCostLimit` 和 `countLimit` 是淘汰提示，不是严格内存上限；不能据此宣称峰值已受硬限制。

## 编码约束

- 目标像素尺寸由最终布局尺寸与显示 `scale` 共同决定；布局尚未确定时不要盲目生成超大图。
- 大文件读取、缩略图生成和已证实昂贵的解码工作不阻塞主线程；UI 状态更新仍回到正确的隔离域。
- 在进入完整解码前限制不可信或异常大的响应体、像素尺寸与并发任务数；具体阈值由产品输入范围和真机基线决定。
- Cell/视图复用、请求换源或页面退出时，取消不再需要的工作，并在回写前校验资源身份。
- 合并请求时按订阅者计数：一个 Cell 取消不能误停仍被其他视图需要的共享任务，最后一个订阅者离开后才释放底层工作。
- 给内存缓存设置与设备和业务场景匹配的成本策略；传入成本时优先使用可获得的真实字节信息（如 `bytesPerRow * height`），不要恒定假设每像素 4 字节。
- 原图、降采样图、变换后图片使用能区分尺寸、scale、内容模式和变换参数的缓存键。
- 收到内存压力时可以丢弃可重建内容，但关键数据必须由持久层或网络层负责恢复。

## 不适用或边界

- Asset Catalog 中尺寸受控的小型静态资源，不需要额外建立复杂降采样管线。
- 需要像素级查看、裁剪或导出的页面，目标尺寸可能就是原图尺寸；应按交互阶段切换资源，而非永久降质。
- 缓存越大并不必然更快，缓存越小也不必然更省电；以真实访问模式、重解码成本和内存峰值权衡。
- 渐进式解码和积极预取会增加 CPU、内存与网络占用；只有真实滚动或感知延迟证据支持时才采用，并设置节流、窗口和取消边界。

## 常见错误

- 用文件 KB 数估算位图驻留内存。
- `UIImage(data:)` 得到完整图片后再绘制成缩略图，并把两份对象同时缓存。
- 让无限制字典长期持有图片，或把 `NSCache` 的淘汰顺序当成业务契约。
- 异步结果未校验复用身份，旧图片覆盖新内容。
- 对相同 URL 重复下载和解码，或反过来用一个全局任务把所有订阅者的取消生命周期绑在一起。
- 只比较平均内存，没有复现峰值、连续滚动和反复进入退出页面。

## 验证方法

1. 固定同一批代表性图片、设备、构建配置和操作脚本，记录改动前基线。
2. 用 Xcode Memory Report 观察当前值与峰值；用 Instruments Allocations 的 Generations 比较一次完整操作后仍存活的分配。
3. 对图片路径同时记录源像素、生成像素、同时下载/解码数量、缓存命中率和峰值内存，确认优化没有用画质下降或重复网络请求换取指标。
4. 在支持范围内内存较小的真机上反复滚动、切后台并触发页面销毁；模拟器结果不能证明真机不会 Jetsam。

## 官方来源

- Apple：[CGImageSourceCreateThumbnailAtIndex](https://developer.apple.com/documentation/imageio/cgimagesourcecreatethumbnailatindex%28_%3A_%3A_%3A%29)
- Apple：[NSCache.totalCostLimit](https://developer.apple.com/documentation/foundation/nscache/totalcostlimit)
- Apple：[Gathering information about memory use](https://developer.apple.com/documentation/xcode/gathering-information-about-memory-use)
- Apple：[Reducing your app's memory use](https://developer.apple.com/documentation/xcode/reducing-your-app-s-memory-use)
