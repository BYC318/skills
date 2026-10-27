---
name: fix-tapd-bugs
description: 修复 TAPD Bug，完成规范提交、远端分支 rebase 与推送、TAPD 已解决回写及 Debug Ad Hoc 交付；支持验收暂停、隔离 worktree 与断点续跑。
---

# TAPD Bug 无人值守交付

此技能把一次明确的“修复”调用视为该批次的交付授权：完成代码修复、规范 Git commit、将本批提交 rebase 到关联远端分支并普通 push、TAPD 开发角色回写到“已解决”、以及 Debug Ad Hoc 打包并上传。查询、审查、诊断、技能维护和用户明确要求“只修复不交付”的调用保持只读或只改对应文件，不推断外部写入授权。用户明确要求不推送时遵从该限制，并报告交付因同步门禁暂停，不能跳过门禁上传。

默认不等待逐 Bug 人工验收或逐单回写确认。用户明确说“需要验收”“先验收”或传入 `--require-acceptance` 时，在自动验证完成、创建 commit 前暂停；用户确认后继续同一批次。`--isolated-worktree` 或“隔离修复/干净 worktree”要求创建干净专用 worktree；`--resume <batch-id>` 只恢复已记录的未完成步骤；`--dry-run` 不作任何写入。

## 批次准入与状态

开始修复前阅读 [证据与清理规则](references/evidence-and-cleanup.md) 和 [批次记录协议](references/batch-protocol.md)，按其中的证据记录、状态命令与恢复流程执行。

除用户显式传入 `--resume <batch-id>` 外，每次调用都必须先实时查询 TAPD，再确定当前需要修复的 Bug。历史 `batch.json`、此前对话列出的 Bug、旧查询结果和旧批次名称只用于审计或显式续跑，不得作为新调用的候选范围，也不得据此跳过、隐藏或补选 TAPD 当前结果。

1. 先读取当前 Git 根目录、分支、worktree、状态、upstream、远端和目标目录规则；保留已有修改，不自动 stash、reset 或清理；push 仅在下述同步步骤执行。
2. 有链接时，实时读取这些链接对应的 Bug，并以链接集合为固定范围；无链接时，实时查询 TAPD 当前候选 Bug，列出后由用户选择一次。查询必须覆盖当前项目、端、状态和用户给出的其他范围条件，不能用“最近几条”、旧批次或本地缓存代替完整候选查询。
3. 用户选定范围后才创建本次批次记录；普通新调用即使发现未完成旧批次，也不得复用旧范围。逐 Bug 重读描述、环境、步骤、预期、评论和附件。影响判断的图片必须查看、视频必须完整播放；不可读取的关键附件仅阻塞该 Bug。
4. 记录批次 ID、Bug 链接、初始 TAPD 状态、当前 HEAD、工作树状态和源码指纹到用户级状态目录。状态和 manifest 不得进入仓库、提交或日志中的敏感字段。
5. 状态机为：`DISCOVERED → FIXING → VALIDATED → COMMITTED → SYNCING → PUSHED → FROZEN → TAPD_WRITING || PACKAGING → COMPLETE/PARTIAL`。`SYNCING/PUSHED` 是批次同步状态，Bug 保持 `COMMITTED`；验收模式在 `VALIDATED` 停止。无成功 Bug 或同步未确认时不进入 `FROZEN`。

“成功子集”是完成附件证据核对、修复、适用测试、规定构建、静态检查和独立审查的 Bug。描述歧义、关键附件不可读、验证失败、与已有本地改动无法安全拆分，或 TAPD 内容在回写前发生实质变化时，只阻塞该 Bug；其余成功 Bug 可交付。真机或完整 UI 证据无法获得时，如工程证据充分，记录残余风险而不把自动验证写成“人工验收”。

## 修复与提交

- 先找调用链和根因；测试优先覆盖实际操作链。UI 能稳定进入时生成结果截图；时序问题不能以单帧代替流程验证。
- 同根因且不可安全拆分的 Bug 使用一个 Conventional Commit；无关 Bug 分别提交。只暂存本批文件或可分离 hunk，提交正文关联 Bug ID 与链接；随后统一执行远端同步。不 autosquash，不擅自改写已发布历史。
- 默认在当前目录执行。若所选批次改动与已有改动无法分离，阻塞该 Bug，绝不把无关改动提交。提交后工作树仍有未提交改动时，保留现场并暂停同步和交付；不得自动 stash、使用 rebase autostash 或把这些改动混进 IPA。
- 需要隔离时，使用随技能分发的 `scripts/worktree.sh` 创建 worktree；基线、目录和分支必须来自本次检查。禁止 `--force`、`git branch -D` 或删除用户 worktree。

## 远端同步、推送与冻结

成功子集提交完成后、任何打包或上传之前，按 [远端同步规则](references/remote-sync.md) 串行完成以下步骤：

1. 确认当前分支关联的远端与分支，记录旧 HEAD、旧 Bug/commit 映射和待推送范围。
2. fetch 目标分支，将本地提交 rebase 到本次 fetch 的远端 tip。逐项理解并解决冲突，保留远端更新与本批修复意图，再完成 rebase。
3. 更新 Bug/commit SHA 映射，针对最终源码重新验证；确认工作树干净、无未解决冲突或进行中的 Git 操作。
4. 普通 push 到同一目标分支并回读远端确认。失败或结果未知时暂停交付；禁止 force push。
5. 记录 `PUSHED` 后才冻结成功子集，并用 `scripts/batch_manifest.rb` 创建 manifest。manifest 必须位于仓库外，包含最终 Bug/commit 映射、同步后的 HEAD、源码指纹和状态路径；同步与验证证据保存在同批 `batch.json`。冻结时实际 HEAD 必须等于已确认推送的 HEAD。

不能先打包再 rebase/push。蒲公英文案只取最终映射的本批提交，不混入 fetch 得到的其他业务提交。开始打包和上传前均校验冻结 HEAD 与源码指纹；源码变化时停止，不复用旧 IPA。

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

报告每个 Bug 的修复/阻塞原因、验证、最终 commit SHA、本地与远端分支、rebase 冲突处理、push 回读结果、TAPD 最终状态、截图、IPA SHA-256、蒲公英安装页和批次状态。只有 push、TAPD 与蒲公英都已回读确认，才标为 `COMPLETE`；任一步失败或未知时标为 `PARTIAL` 并给出同一 batch ID 的续跑命令。

rebase 合并后的 worktree 清理仍需用户明确说明已合并；先验证工作区干净、基线已包含或补丁等价，再使用 `scripts/worktree.sh` 无强制删除。
