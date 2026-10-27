# 提交后的远端同步

本流程在成功子集提交完成后、冻结和打包之前执行。同步与推送属于修复交付授权，无需另问一次；技能维护不执行真实仓库的 rebase、push 或上传。

## 确定目标与保护现场

- 默认目标来自当前分支的 `branch.<name>.remote` 和 `branch.<name>.merge`（完整 `refs/heads/...`），同时核对 upstream。用户明确指定的目标优先；不猜 `origin`、`main` 或同名远端分支。
- detached HEAD、无 upstream、目标不是远端分支、远端分支已删除，或 fetch/push 指向不同仓库且无法确认时，记录阻塞并询问缺少的目标信息。不自动设置或更换 upstream。
- 隔离 worktree 创建前记录来源分支的 upstream；临时分支没有 upstream 时只能使用这个已确认目标。push 显式指定该目标，不能意外发布 `codex/tapd-*` 分支。
- 检查工作树、索引、未跟踪文件以及 rebase/merge/cherry-pick/revert 状态。存在未提交改动时暂停，不自动 stash、reset、clean 或 autostash；已有 Git 操作先核对是否属于本批。
- 记录旧 HEAD、目标 remote/ref、本批旧 SHA 和源码指纹，然后使用 `sync-start` 保存意图。检查相对目标的全部待推送提交；若包含用户已有的无关未发布提交，不把本批授权扩展到它们，先确认是否一并推送。

## fetch、rebase 与验证

1. 显式 fetch 已确认的远端分支，例如 `git fetch --no-tags <remote> <refs/heads/branch>`；记录本次 `FETCH_HEAD` 的完整 SHA，立即 rebase 到这个固定 SHA，不能仅依据可能过期的 remote-tracking ref。
2. rebase 前保留旧 tip 与提交范围供恢复和映射；默认仅重放尚未发布的提交。远端历史改写或需要重写已发布提交时暂停，不能改用 merge 绕过本流程。禁用 autostash，例如 `git -c rebase.autoStash=false rebase <fetched-sha>`。
3. 有冲突时先读取冲突目录规则和三方版本，理解调用关系与双方业务意图，逐文件解决后 `git rebase --continue`。rebase 中 ours 是新的远端基线，theirs 是正在重放的本地提交；不得整批选择任一侧。不能确定业务含义时保留可恢复现场，记录冲突和原因，暂停交付。
4. 对比前后提交范围（如 `git range-diff`），逐项建立旧 SHA → 最终 SHA 映射，不能按提交顺序或标题盲配。被跳过的等价修复须映射到实际承载修复的可达提交并记录证据；无法唯一定位时停止冻结，不伪造 SHA 或空提交。
5. 检查目标 tip 是最终 HEAD 的祖先、本批最终 SHA 均可从 HEAD 到达、索引无未合并项、无残留冲突标记、无进行中 Git 操作且工作树干净。对合并后的源码重新执行受影响测试、规定构建、静态检查和审查；无源码变化的检查可引用同一源码的既有证据并说明理由。失败不能沿用 rebase 前的通过结论。

## 推送与确认

- 用显式 refspec 普通推送：`git push <remote> HEAD:<refs/heads/branch>`。不依赖 `push.default`、`pushRemote` 或同名推断，禁止 `--force` 和 `--force-with-lease`。
- push 后直接查询该远端目标 ref（如 `git ls-remote --exit-code <remote> <refs/heads/branch>`），确认 tip 等于本地 HEAD，并记录时间和完整 SHA；只看到本地 tracking ref 或 push 命令成功不足以完成回读。
- 非 fast-forward 拒绝时，重新 fetch → rebase → 验证 → push，更新映射；单次执行最多进行 3 轮。持续竞争、权限/网络失败或不明确的拒绝原因均记录 `PARTIAL` 并暂停，不强推、不继续打包。
- push 响应丢失时先回读对账；远端等于最终 HEAD 可确认成功，远端已继续前进则重新 fetch 并同步，无法读取则保留 `SYNCING`，不猜测成功或盲目重试。
- `sync-complete` 仅在最终 HEAD 已通过验证且远端回读一致时记录，写入映射、目标 tip、最终 HEAD、验证摘要和回读时间。随后 freeze 和 manifest 均使用最终 SHA。

## 中断恢复与冻结边界

- `SYNCING` 续跑先核对记录、实际 HEAD、Git 操作状态和远端目标；本批 rebase 未完则继续已记录操作，不再启动一次 rebase。完成 rebase 但未记回执时，依据旧 tip、range-diff 和远端事实恢复映射，不再创建修复 commit。
- 未冻结且已 `PUSHED` 时复核 HEAD 和远端，仍一致即可冻结；若远端前进，需要 `sync-start` 开新一轮同步并重新验证。旧回执保留在同步历史中，不能继续当作当前成功证据。
- 已冻结的 manifest 不原地改写。若 HEAD/源码仍符合冻结记录，且远端仍包含已推送 HEAD，可续跑该固定快照的未完成交付；后来产生的远端提交属于快照之后的变化。用户要求纳入这些更新或源码发生变化时，停止旧批交付，建立新批次重新同步、验证、冻结和打包。
- 旧版冻结批次没有 push 回执时，不能直接续传或补写“已推送”；保留旧 manifest、buildKey 和回执，建立关联新批次执行同步流程。已有上传先对账，不能以升级协议为理由重复上传。
