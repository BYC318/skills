# 恢复对账工具

## 恢复时先运行

工具是本技能的 `scripts/coordination.py`，仅依赖 Python 3 标准库。以下资料路径替换为实际绝对路径；输出为 stdout，不覆盖历史报告。

```bash
python3 .agents/skills/codex-task-coordination/scripts/coordination.py recover --registry '长期任务目录的绝对路径' --actor main --format markdown
python3 .agents/skills/codex-task-coordination/scripts/coordination.py recover --root '本批协调目录的绝对路径' --actor A
```

`--registry` 与 `--root` 二选一。长期目录每个 `batches` 条目至少包含 `batch_id` 和实际绝对 `coordination_root`；工具扫描全部已登记批次，不因状态写为“已完成”而跳过。`tasks` 中须有当前逻辑执行者 ID。批次缺失、损坏或执行者不匹配会列入 `unavailable_batches`，令 `scan_complete=false`，不能因此宣布没有剩余工作；目录为空也不能解释为待办为零。扫描不是跨批原子事务，目录变化时须重跑。

本组主任务使用 `--actor` 加本批 `main` 字段的实际逻辑 ID 核对本组全部参与者（模板为 `main`，子组也可为 `ios` 等稳定 ID）；模块和共享任务使用实际逻辑 ID，列出与自己有关的请求及分派。首次没有长期目录时可按单批扫描，恢复后补齐索引；跨批工作优先扫描长期目录。JSON 为默认格式供 Agent 读取，`--format markdown` 供人查看，跨批项目携带批次及来源路径。

多级目录的 `children`、跨组转述和修订映射不由脚本递归处理。按 [分层恢复](hierarchical-coordination.md#分层接续与结构调整) 分别扫描父组与各实际子组目录；兼任端内协调聊天分别使用父组中的自身 actor 和子组中的 main ID。各组目录只索引本组批次，未扫描的子组仍属待核对，不能把本组 `scan_complete=true` 报为全局完成。

## 自动列出的事实

- `open_requests`：未完成请求或直接分派，保留原请求及各次调整的消息 ID、当前修订、负责方、逐消费者状态与下一步。只有 ASSIGN/READY 而没有页面侧 REQUEST 的工作也会列出。
- `pending_messages`：发给当前执行者、尚无 ACK/ACCEPTED 的当前修订消息。
- `awaiting_confirmation`：当前执行者发出的、尚无接收确认的当前修订消息。尚未通知和已通知未确认都在其中，工具不猜测真实聊天工具的送达结果。
- `superseded_messages`：旧修订或已被明确后继取代的阶段消息，保留历史但不作为当前执行指令；旧请求仍与当前需求关联。
- `actions_pending_verification` / `completed_actions`：已登记但结果未知的接入意图，以及已有完成回执的接入。
- `notifications_pending_verification`：已登记意图但调用结果缺失或未知的通知；先核对真实聊天/接收回执，经[通知恢复](notification-gate.md#重试与中断恢复)保存独立核验结论，不直接重发。旧批没有账本时不补造历史发送事实。
- 通知尝试的 `.dispatch.json` 仅表示已原子领取本次发送，不表示送达；已有领取或异步会话不构成重发依据。带continuation的调用按[原命令接续](notification-gate.md#原命令的异步接续)处理，原会话不可用时保留未知。发送成功但回执前中断也先查实际结果，不重新调用send。
- `phase_transitions_pending` / `completed_phases`：按[阶段协议](delivery-and-phases.md)显式登记的等待／放行及实际产物状态。只ACK、前置决策不可读或被取代、缺阶段回执或文件哈希/约定字段不符都保留待办；阶段待办未清不能报告完整闭环。旧批未登记阶段时不反推自然语言，也不能把该字段为空当作所有阶段已验证。
- `integration_pending_verification`：已出现冻结快照或集成信号，但冻结状态遗漏、指针/文件哈希不符、终版过期或存在未承接快照；按[执行资料防护](execution-guards.md)核对恢复，不能漏记后直接宣布闭环。没有登记集成的旧批次不反推冻结，也不自动改写旧资料。
- `next_steps`：先核对执行及通知结果未知项，再确认消息、跟进依赖或核验关闭。这里只生成建议，不发送消息或执行命令。
- `unlinked_events`：已有 BLOCKED/RESULT/CONSUMED 却找不到请求或分派来源的记录，即使已 ACK 仍提示补查，不当作没有待办。

报告是从磁盘重算的快照，含 `snapshot_sha256`。反复运行不会确认消息、关闭请求或改写事件。旧格式消息只有“完成”文字、ACK、共享 RELEASE 或页面 RESULT 时，保守保留待核验，不能从描述猜测完成。

## 明确关闭依赖

主任务核验消费结果后，发布 `RESOLVED` 关闭本项依赖；这不代表整个源码批次已集成或 UI 已通过。外层 `entity_id`、`revision` 使用当前需求，`refs` 包含被关闭的原请求及核验回执。参考 [关闭依赖消息模板](../assets/关闭依赖消息模板.json)，在 `payload` 中填写：

```json
{
  "recovery": {
    "resolution": "completed",
    "consumer": "A",
    "request_ids": ["REQ-001", "REQ-CHANGE-2", "REQ-CHANGE-3"],
    "evidence_refs": ["CONSUMED-3"],
    "reason": "已核对当前修订的接入与验证记录"
  }
}
```

`evidence_refs` 指向同实体、同修订、同消费者的 CONSUMED/RESULT，其 `payload.verification` 包含 `status: passed` 和非空字符串数组 `evidence`；该格式也在新交付发布与通知时检查，结构化证据放 artifacts。工具校验关联和声明，真实 Git、业务结果与截图身份仍须核实。

取消或延后使用主任务的 INVALIDATED，填写 `resolution: cancelled` 或 `deferred`，列明原请求、消费者及原因；延后另有 `next_batch`，仍计为未完成。直接分派可在 `request_ids` 中引用原 ASSIGN/READY。A 的关闭不替 B 关闭；未覆盖的新调整保留。同修订有矛盾关闭结论时报告待核对，不按时间戳或文件顺序任选一个。

同实体下的直接 ASSIGN/READY 按接收者及显式 `payload.consumers` 区分归属，使用报告中 `consumers` 各项的 `request_ids` 核对关闭范围，不照抄顶层聚合列表；同一消费者的多条分派仍须逐条处理。REQUEST 的既有公共需求语义及未声明消费者的旧共享分派继续兼容。新发布的关闭消息拒绝引用其他消费者的分派；旧版全组归并消息可读且同 ID 重放仍幂等，仅影响原记录的消费者，不改写历史或替其他任务关闭。

## 接入前后登记

实际执行接入的任务填写 [执行意图模板](../assets/执行意图模板.json) 后运行：

```bash
python3 .agents/skills/codex-task-coordination/scripts/coordination.py begin-action --root '本批协调目录的绝对路径' --actor A --plan '实际执行意图的绝对路径.json'
```

单批次内，以操作、仓库 ID、规范 worktree 路径及完整源 SHA 为动作身份；需求修订或通知变化不会重新放行同一工作区的同一源提交。并发申请仅一次返回 `can_execute=true`，已有意图或完成回执均返回 false。这是执行防重检查，不是新增源码权限授权。

首次放行后仍须核对真实 Git、当前修订与授权，再按源码规则执行。实际核验完成后填写 [执行完成回执模板](../assets/执行完成回执模板.json)：

```bash
python3 .agents/skills/codex-task-coordination/scripts/coordination.py finish-action --root '本批协调目录的绝对路径' --actor A --action-id 'begin-action返回的动作ID' --result '实际完成回执的绝对路径.json'
```

回执记录真实本地 SHA、`verification.status: passed` 及核验依据，原子保存且不可改写为不同结果。随后发布 CONSUMED；主任务核验并发布 RESOLVED 后关闭对应依赖，不能直接标为业务或 UI 验收通过。

Git 已执行但回执未写就被强制中断时，报告要求先查真实 Git，禁止直接重做；核实已接入则补回执。核实尚未发生时，由主任务协调继续原意图；工具不自动重试、删除意图或解除未知状态。故意回退后重新接入也须明确协调，不清空历史骗取首次放行。

执行去重限定在本批登记记录内。新批次先运行跨批恢复并检查真实 Git 和基线，不能凭新批首次放行重复接入上一批代码。绕过工具直接执行 Git 不受此登记约束；工具不提供“Git 与回执同时提交”的事务。

## 可重复的中断模拟

```bash
python3 .agents/skills/codex-task-coordination/scripts/simulate_recovery.py --output '不存在的外部验证目录绝对路径'
```

模拟创建独立 Git 夹具与合成消息，保留六次新进程恢复快照，并在 cherry-pick 成功但完成回执未写时向合成子进程发送 SIGKILL。核验原始依赖请求、两次需求修改、独立需求取消、跨批旧请求保留、重复通知、执行去重、实际 Git 接入次数与最终明确关闭，生成验证报告及原始记录。不创建真实 Codex 任务，不修改应用源码，不把合成记录当作 UI 证据。

## 迁移后的协议回归

修改或迁移消息工具后，可在显式指定的外部测试目录运行包内回归；先建立符合本机产物规则的目录，并用其实际绝对路径替换占位内容：

```bash
COORDINATION_TEST_ROOT='已存在的外部测试目录绝对路径' python3 -B -m unittest discover -s .agents/skills/codex-task-coordination/scripts -p 'test_*.py'
```

回归只使用合成消息与独立 Git 夹具，验证通知幂等、修订、恢复、消费者隔离及去重；不创建真实聊天。`simulate_recovery.py` 另外验证接入成功而回执未落盘时的恢复。测试案例中的模块和共享能力可替换，不代表项目需求。

`test_message_operations.py` 验证常用操作的责任链、并发幂等、真实文件哈希及阶段约束；`test_dispatch_recovery.py` 验证prepare／claim／finish的分块会话接续和不重跑命令，并在本地测试收件箱fsync后、完成回执尚未写入前对真实Node子进程发送SIGKILL。新进程须恢复通知未知，普通再次调用发送0，核验实际测试收件箱后补独立sent核验再收ACK。传输为隔离持久夹具，不冒充真实桌面聊天送达或应用验收。

`test_execution_guards.py` 验证收件箱参数别名与冲突拒绝、中文及含空白/换行的原始Git路径、索引不变、冻结齐备/哈希/修订检查、并发幂等和真实子进程在快照落盘后状态写入前SIGKILL的恢复；合成夹具不创建聊天，不操作应用源码。

`test_candidate_safety.py` 使用真实隔离Git验证完整ref切换仍附着本地分支、重现detached后拒绝放行、候选前序提交累积、脏索引/忽略文件/在途操作/其他worktree占用保护；另核对相对路径零命令/零通知、空目录与并发初始化、脚本失败即停及运行进程SIGKILL后的未知意图不重放。初始化与脚本入口见[执行资料防护](execution-guards.md)。
