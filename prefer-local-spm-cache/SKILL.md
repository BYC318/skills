---
name: prefer-local-spm-cache
description: Use when Codex 即将在 iOS 项目中运行 xcodebuild、Simulator 测试、SwiftPM 解析或其他依赖远程 Swift Package 的验证，且远端拉取影响执行速度。
---

# 优先复用本地 SPM 缓存

## 核心原则

在执行 iOS CLI 构建或测试前，先用 `/Users/byc/Desktop/SourcePackages.zip` 补充本次命令实际使用的 `SourcePackages`。这只是缓存预热；本地缓存缺失、不完整或版本不匹配时，继续执行原命令并允许 SwiftPM 正常联网补齐。

## 执行流程

1. 从计划执行的 `xcodebuild` 命令确定目标缓存：

   | 命令参数 | 脚本参数 |
   | --- | --- |
   | `-clonedSourcePackagesDirPath <路径>` | `--source-packages-path <路径>` |
   | `-derivedDataPath <路径>` | `--derived-data-path <路径>` |

2. 如果两个参数都没有，为本次验证指定明确、任务专用的 `-derivedDataPath`，再把同一路径传给脚本。不要猜测 Xcode GUI 的哈希 DerivedData 目录。
3. 在 `xcodebuild` 前运行：

   ```bash
   /Users/byc/.codex/skills/prefer-local-spm-cache/scripts/seed_source_packages.sh \
     --derived-data-path /tmp/ZecoDerivedData
   ```

4. 随后原样执行构建或测试。脚本输出 `LOCAL_CACHE_SKIPPED` 或 `LOCAL_CACHE_PARTIAL` 也不要中止验证；让 SwiftPM 从远端补齐。脚本已将这些回退情况处理为成功退出，不要追加 `|| true` 掩盖真正的参数错误。

## 行为边界

- 只复制目标中不存在的顶层 `checkout`、`repository` 和 `artifact`。
- 保留目标已有内容，不删除、不整体替换、不覆盖同名 package。
- 不复制 zip 内的 `workspace-state.json`，避免旧 checkout 的绝对路径污染当前项目。
- 不修改 `Package.swift`、`Package.resolved`、Xcode 工程或仓库源码。
- 不主动添加离线沙箱、`-disableAutomaticPackageResolution`、`-skipPackageUpdates` 或其他禁止联网参数。
- 不为检查缓存而单独运行 `xcodebuild -resolvePackageDependencies`；缓存预热后直接执行任务原本需要的验证。

## 自定义缓存路径

命令使用独立 cloned packages 目录时执行：

```bash
/Users/byc/.codex/skills/prefer-local-spm-cache/scripts/seed_source_packages.sh \
  --source-packages-path /tmp/ZecoSourcePackages
```

目标目录可以使用 `xcodebuild` 指定的任意名称。需要临时测试其他 zip 时可追加 `--archive <路径>`。

## 常见错误

- 把 zip 解压到一个未被当前 `xcodebuild` 使用的 DerivedData：必须以命令参数为准。
- 整体覆盖 `SourcePackages`：会丢失目标独有依赖，并可能带入旧 `workspace-state.json`。
- 本地缓存不完整就停止任务：本技能的目标是提速，远程回退是正常路径。
