# 批次记录与续跑

修复模式必须使用本协议。以下参数是技能调用约定，不是 TAPD CLI；远端读取/写入仍使用可用的 TAPD 工具或浏览器。

## 文件与启动

每批在 `~/.codex/state/fix-tapd-bugs/<repo-key>/<batch-id>/` 建立 0700 目录。`batch.json` 为修复/TAPD 日志，`manifest.json` 为技能冻结的成功子集输入，`delivery-manifest.json` 为打包 CLI 校验、补全描述和仓库身份后的规范化冻结副本，`delivery.json` 为打包回执；分开写入避免并行覆盖。文件 0600；不得保存凭据、原始附件或敏感业务数据。

`scripts/batch_state.rb COMMAND --state <batch.json> --input <json-file>` 接收结构化 JSON；输入文件用 apply_patch 创建或通过工具 stdin 传入，避免把评论拼入 shell 命令。

- `init`：`{repo,batch_id,source_head,source_fingerprint,initial_changes,require_acceptance,bugs:[{id,url,snapshot}]}`。snapshot 是影响判断的字段/附件版本的摘要；将本批自己新增的评论和合法中间状态排除，并单独记录实际远端状态。
- `update`：`{bug_id,status:"FIXING"}` 开始修复。通过验证时传 `status:"VALIDATED",verification:{tests,build,static,review,residual_risks}`，四类证据必须有本次结果或明确不适用理由。阻塞时传 `status:"BLOCKED",reason`。
- `check-commit`：提交前以 `{bug_id}` 检查；非零禁止提交。仅验收模式需要 `accepted {bug_id,user_confirmed:true}`，此字段只在用户实际确认后记录。默认模式无需此步骤。
- 实际 Git commit 完成后记录 `committed {bug_id,commit_shas:[完整SHA]}`；同根因 Bug 分别映射到同一 SHA。
- 尝试完所有 Bug 后 `freeze` 固定成功子集。阻塞 Bug 不写 TAPD；没有成功项则停止交付。

冻结源码使用 `scripts/batch_manifest.rb --repo <root> --batch-id <id> --out <manifest.json> --state-path <delivery.json> --bug <id=url> --commit <sha> --bug-commit <id=sha>`。重复这些参数覆盖全部成功 Bug 和提交，不使用最近 N 条。它解析 SHA、记录 staged/unstaged/untracked 指纹并拒绝覆盖已有 manifest。验证摘要与原始工作树清单留在 batch.json。

## 并行交付

以项目 `fastlane/adhoc_debug_delivery --project-dir <Gemfile目录> --manifest <manifest.json>` 启动打包，保留执行会话并等待结果；同时执行 TAPD 链路。不要通过创建用户新任务来实现内部并行。

TAPD 每 Bug 重读后执行 `check-snapshot {bug_id,snapshot}`。若 `remote_changed` 为 true 则跳过该 Bug。每个操作先写 `intent {bug_id,operation,payload_sha256,snapshot}`，operation 为 `comment`、`attachment`、`resolve:<action>` 或 `resolve`；出现 already done / inflight 时不再次调用外部写接口。

随后调用实际 TAPD 接口并回读，保存 `receipt {bug_id,operation,observed:"present",payload_sha256,receipt_id}`。多步开发流转使用 `resolve:<action>` 逐步记录意图和回执，action 使用实际动作 ID（字母、数字、下划线或连字符）；最终进入“已解决”的操作使用 `resolve`。中断后重新读取当前状态和动作，只执行未完成步骤；最终到“已解决”才为 resolve 写 present。截图多张时以一组附件内容hash记录，恢复时逐张核对已存在附件。

写操作响应丢失时保留 inflight。重读远端后 `reconcile` 使用同一结构：确认已存在为 present；无法确认是 unknown；只有明确证明未发生才允许 `observed:"absent",definitive:true`，之后可重新 intent。不确定操作跳过并继续其他独立 Bug，不重复评论或附件。

## 恢复与报告

用户 `--resume <id>` 后先 show 同一 batch.json，对照本次授权范围、冻结 manifest 与远端实际状态；保留已完成 commit、评论和上传。CLI 的 `--resume <id>` 读取同批 `delivery-manifest.json`，只处理打包分支，不代替 TAPD 恢复。新需求或重开 Bug 建立新的修复批次。

读取 delivery.json，只有 `pgyer.state == published` 且回执有安装页时，调用 `report {delivery_status:"published"}`；其他状态传实际值。原批有阻塞项或任何交付步骤未确认，最终仍是 PARTIAL。报告包含成功子集、阻塞项、本地 commit（未push）、实际验证限制和安装链接。

`--dry-run` 只读取和输出候选范围、分组与命令，不 init、freeze、commit、上传或流转。验收/隔离为自然语言或调用标记，由技能解释；这些不是打包 CLI 参数。
