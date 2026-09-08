---
name: prefer-local-spm-cache
description: Use when Codex 即将在 iOS 项目中运行 xcodebuild、Simulator 测试或 SwiftPM 解析，需要优先复用本机已有 DerivedData 或 SourcePackages.zip，并在本地依赖不可用时自动联网兜底。
---

# 优先复用本地 SPM 缓存

## 核心原则

先复用当前设备已有缓存，避免每次验证都更新远端；本地缓存缺失、损坏或无法完成依赖解析时，自动执行正常联网解析，不把本地缓存问题当成任务失败，也不要求用户介入。

来源按以下顺序补充，始终保留目标已有内容：

1. 显式 `--cache-source` 或 `LOCAL_SPM_CACHE_SOURCES`。
2. 当前 Xcode 自定义 DerivedData、目标 DerivedData 的同级目录、系统默认 DerivedData，以及 `LOCAL_SPM_DERIVED_DATA_ROOTS` 中所有同名 workspace/project 缓存。
3. 显式 `--archive`、`LOCAL_SPM_CACHE_ARCHIVE`、`LOCAL_SPM_CACHE_SEARCH_ROOTS`，最后动态检查当前用户的 Desktop、Downloads 等常见位置中的 `SourcePackages.zip`。
4. 以上来源仍不足时由 SwiftPM 正常联网补齐。

任何路径都必须从当前命令、当前设备设置、环境变量或当前用户目录动态取得；不得写死用户名、卷名、项目绝对路径或 Xcode 的 DerivedData 哈希。

## 首选执行方式

计划好原始 `xcodebuild` 命令，并显式提供任务实际使用的 `-derivedDataPath`、`-clonedSourcePackagesDirPath`、`-packageCachePath`、`-resultBundlePath` 等项目规则要求的路径。随后用包装脚本执行完整原命令：

```bash
"$HOME/.codex/skills/prefer-local-spm-cache/scripts/run_xcodebuild.sh" -- \
  xcodebuild \
    -workspace /absolute/path/App.xcworkspace \
    -scheme App \
    -derivedDataPath /absolute/task/path/DerivedData \
    -clonedSourcePackagesDirPath /absolute/task/path/SourcePackages \
    build
```

包装脚本会：

1. 从原始命令提取 workspace/project 和实际缓存目标。
2. 遍历所有同项目 DerivedData，再尝试本地 zip，只补目标中缺失的顶层缓存目录。
3. 首次执行自动追加 `-onlyUsePackageVersionsFromResolvedFile` 与 `-skipPackageUpdates`，优先使用锁定版本和现有缓存；缺少的锁定依赖仍可由 SwiftPM 获取。
4. 如果首次失败属于 SwiftPM 解析、clone、fetch、checkout 或 `Package.resolved` 问题，隐藏该次内部错误并自动用原始命令重试；只有联网重试仍失败时才报告最终错误。
5. 如果首次失败是普通编译或测试错误，原样返回且不做无意义的第二次构建。

若原始命令没有显式缓存路径，包装脚本不会猜测 Xcode GUI 的哈希目录，而是直接执行原始命令并允许联网。

## 仅预热缓存

不希望包装构建命令时，可以只运行：

```bash
"$HOME/.codex/skills/prefer-local-spm-cache/scripts/seed_source_packages.sh" \
  --workspace /absolute/path/App.xcworkspace \
  --derived-data-path /absolute/task/path/DerivedData
```

然后继续执行原始构建。`LOCAL_CACHE_SKIPPED` 或 `LOCAL_CACHE_PARTIAL` 都是可恢复状态，不得停止任务。

## 行为边界

- 只复制目标中不存在的 `checkouts`、`repositories` 和 `artifacts` 子项；不删除、不覆盖同名 package。
- 不复制其他 DerivedData 或 zip 中的 `workspace-state.json`，避免旧项目绝对路径污染当前工作区。
- 不修改 `Package.swift`、`Package.resolved`、Xcode 工程或仓库源码。
- 不自动加入 `-disableAutomaticPackageResolution` 或网络沙箱；联网兜底始终可用。
- 不单独运行 `xcodebuild -resolvePackageDependencies`；缓存复用必须服务于本来就要执行的构建或测试。
- 用户显式给出的离线或包解析参数属于原始命令，包装脚本不得擅自删除。

## 自定义发现范围

跨设备共享配置时使用环境变量，不改技能脚本：

```bash
export LOCAL_SPM_DERIVED_DATA_ROOTS="/path/one:/path/two"
export LOCAL_SPM_CACHE_SOURCES="/path/a/SourcePackages:/path/b/SourcePackages"
export LOCAL_SPM_CACHE_SEARCH_ROOTS="/path/with/archive"
export LOCAL_SPM_CACHE_ARCHIVE="/path/to/SourcePackages.zip"
```

显式命令参数适合单次任务，环境变量适合某台设备的本地配置。技能本身保持无设备路径。
