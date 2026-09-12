---
name: fix-tapd-bugs
description: 修复 TAPD Bug 并在修复模式下完成规范提交、TAPD 已解决回写和 Debug Ad Hoc 交付；支持验收暂停、隔离 worktree 与断点续跑。
---

# TAPD Bug 无人值守交付

此技能把一次明确的“修复”调用视为该批次的交付授权：完成代码修复、规范 Git commit、TAPD 开发角色回写到“已解决”、以及 Debug Ad Hoc 打包并上传。查询、审查、诊断和用户明确要求“只修复不交付”的调用保持只读或只改代码，不推断外部写入授权。

默认不等待逐 Bug 人工验收或逐单回写确认。用户明确说“需要验收”“先验收”或传入 `--require-acceptance` 时，在自动验证完成、创建 commit 前暂停；用户确认后继续同一批次。`--isolated-worktree` 或“隔离修复/干净 worktree”要求创建干净专用 worktree；`--resume <batch-id>` 只恢复已记录的未完成步骤；`--dry-run` 不作任何写入。

## 批次准入与状态

开始修复前阅读 [证据与清理规则](references/evidence-and-cleanup.md) 和 [批次记录协议](references/batch-protocol.md)，按其中的证据记录、状态命令与恢复流程执行。

1. 先读取当前 Git 根目录、分支、worktree、状态、远端和目标目录规则；保留已有修改，不自动 stash、reset、清理或 push。
2. 有链接时，链接集合就是固定范围；无链接时只列出并由用户选择一次。逐 Bug 重读描述、环境、步骤、预期、评论和附件。影响判断的图片必须查看、视频必须完整播放；不可读取的关键附件仅阻塞该 Bug。
3. 记录批次 ID、Bug 链接、初始 TAPD 状态、当前 HEAD、工作树状态和源码指纹到用户级状态目录。状态和 manifest 不得进入仓库、提交或日志中的敏感字段。
4. 状态机为：`DISCOVERED → FIXING → VALIDATED → COMMITTED → FROZEN → TAPD_WRITING || PACKAGING → COMPLETE/PARTIAL`。验收模式在 `VALIDATED` 停止；无成功 Bug 时不进入 `FROZEN`。

“成功子集”是完成附件证据核对、修复、适用测试、规定构建、静态检查和独立审查的 Bug。描述歧义、关键附件不可读、验证失败、与已有本地改动无法安全拆分，或 TAPD 内容在回写前发生实质变化时，只阻塞该 Bug；其余成功 Bug 可交付。真机或完整 UI 证据无法获得时，如工程证据充分，记录残余风险而不把自动验证写成“人工验收”。

## 修复、提交与冻结

- 先找调用链和根因；测试优先覆盖实际操作链。UI 能稳定进入时生成结果截图；时序问题不能以单帧代替流程验证。
- 同根因且不可安全拆分的 Bug 使用一个 Conventional Commit；无关 Bug 分别提交。只暂存本批文件或可分离 hunk，提交正文关联 Bug ID 与链接；不 push、不 autosquash、不重写历史。
- 默认在当前目录执行。打包前重新计算源码指纹；IPA 允许包含用户已有的本地未提交改动，但蒲公英描述只来自冻结的本批 commit。若所选批次改动与已有改动无法分离，阻塞该 Bug，绝不把无关改动提交。
- 需要隔离时，使用随技能分发的 `scripts/worktree.sh` 创建 worktree；基线、目录和分支必须来自本次检查。禁止 `--force`、`git branch -D` 或删除用户 worktree。
- 成功子集提交完成后，使用 `scripts/batch_manifest.rb` 创建冻结 manifest。manifest 必须位于仓库外，包含 `batch_id`、Bug/commit 映射、HEAD、源码指纹和状态路径；验证摘要保存在同批 `batch.json`。

## TAPD 回写

冻结后，TAPD 回写与打包可以并行；同一批内 TAPD 仍逐 Bug 串行，以便准确恢复。

每个成功 Bug 按以下顺序执行：重新读取并比较关键字段/附件/状态 → 上传可靠的修复截图（若有） → 添加 `已修复：实际行为变化。` → 按当前可用流转动作到开发职责的“已解决” → 重新读取核验。

- 不写 Commit SHA，不写“已验证/已关闭”，不改标签。
- 每步先记录意图，执行后立即回读并保存回执。中断或异常后先对账已存在的评论、附件和状态，不能唯一判断时不重复写入。
- 某一 Bug 写回失败、状态已变化或远端结果不确定时，将该 Bug 标为 `PARTIAL` 并继续可独立处理的其他 Bug；不回滚已成功的远端操作。

## Debug Ad Hoc 交付

新批次先检查构建目录的 `ios-delivery.json`：若已安装其中 `tool_version` 锁定的独立工具，优先调用该版本的 `bin/ios-delivery`。默认安装位置为 `~/.local/share/ios-delivery/<tool_version>/`；不能仅凭 PATH 中同名命令推断版本一致。未安装时，若项目存在旧 `fastlane/adhoc_debug_delivery`，继续用旧入口，不要求同事改变现有 Fastlane 打包方式，不自动安装工具或改 Gemfile。

两种入口的 manifest 模式均接收精确 commit SHA 集合，不直接用“最近 N 条提交”调用 Fastlane。沿用文案规则：跳过 merge、清洗 Conventional Commit 前缀、精确去重；多条优先归纳为编号中文说明，归纳失败退回原标题。

```bash
ruby "$PROJECT_DIR/fastlane/adhoc_debug_delivery" --project-dir "$PROJECT_DIR" --manifest "$MANIFEST_PATH"
```

`--resume <batch-id>` 只恢复用户级状态目录中的同一 manifest。记录本批实际使用的入口及工具版本，续跑必须用原入口；缺少新工具项目/配置身份的旧回执仍由旧 CLI 对账，不自动迁移或新建批次重传。CLI 必须校验冻结 HEAD/源码指纹、IPA SHA-256 和既有 buildKey；发布超时或上传响应异常均为非成功状态，先查询既有 buildKey，禁止盲目重建或重传。Debug 包不得上传 Crashlytics dSYM。

项目未提供该 CLI 时，不伪造共享交付能力：报告该批次仅完成代码/TAPD 部分，或等待用户指定打包方式。

## 收尾报告

报告每个 Bug 的修复/阻塞原因、验证、commit SHA、本地分支、TAPD 最终状态、截图、IPA SHA-256、蒲公英安装页和批次状态。明确说明本批未 push。只有 TAPD 与蒲公英都已回读确认，才标为 `COMPLETE`；任一分支失败或未知时标为 `PARTIAL` 并给出同一 batch ID 的续跑命令。

rebase 合并后的 worktree 清理仍需用户明确说明已合并；先验证工作区干净、基线已包含或补丁等价，再使用 `scripts/worktree.sh` 无强制删除。
