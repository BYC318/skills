# 交付校验与阶段放行

发布 RESULT／CONSUMED、关闭依赖，或有后续动作等待本组／上层决策时读取本页。复用现有消息类型和 schema 1，不引入固定层数、平台、任务事件或后台调度。

## 新交付在发布时校验

新 RESULT／CONSUMED 必须提供统一的 `payload.verification`：

```json
{"status":"passed","evidence":["已实际核对的日志、文件路径或事实；没有执行的验证不要写成通过"]}
```

`status` 允许 `passed`、`failed`、`not_run`；`evidence` 始终为非空字符串数组。失败／未执行时写实际原因或依据。结构化路径和文件哈希放在 `payload.artifacts`，不能把对象直接塞入 evidence。参考 [交付结果模板](../assets/交付结果消息模板.json)。

`emit` 在新交付落盘前检查，`prepare-notification` 在通知前再检查；依赖关闭复用同一契约并另外要求 `passed`。格式正确只说明可核验，不证明业务或截图真实。`RELEASE` 的共享交付清单仍按原交付协议处理。

历史缺失／格式错误的 RESULT 继续可读取和恢复，同 ID 同内容的重放仍幂等；它们不能作为通过证据关闭依赖，也不能直接重新通知。由原交付者用新消息 ID 补交更正，标明 `supersedes_result` 并引用旧消息；只修封装时不重跑已完成作业、不改写旧报告。

## 将等待与放行明确记成消息

只在确有后续动作等待另一决策、且需要跨轮／跨层接续时登记 `payload.phase_transition`；普通交付不附空阶段。阶段 ID 描述实际工作，例如 `FINAL-REVIEW`，不固定为某次演练的阶段号。

| 字段 | 约定 |
| --- | --- |
| `id` | 在同一实体和接收者下稳定的 ASCII 阶段 ID |
| `state` | `waiting` 表示尚未放行；`released` 表示本消息明确放行；`cancelled` 表示有依据地取消该阶段 |
| `supersedes` | 阶段变化时指向唯一当前阶段消息，且放入本批 `refs`；新建阶段可省略 |
| `prerequisites` | 放行时必填非空数组，逐项引用已实际核验的前置决策 |
| `expected_artifacts` | 本阶段实际应交付的绝对文件路径；JSON产物可另列 `required_keys` 顶层字段 |

协调者用 ASSIGN、READY、RESOLVED 或 INTEGRATED 发布等待／放行状态；取消阶段须用 INVALIDATED，显式承接原阶段并在 `reason` 写实际授权或决策依据。旧关闭消息可以同时表示“此前交付已关闭，后续阶段仍在等待”，但它的 ACK 不放行后续动作。条件满足后，必须新增带当前依据的放行消息，显式承接原阶段；仅改变旧消息的发送时机、增加旁边的说明文件或口头称“已关闭”都不代替这一步。业务范围没有变化时可保持原修订；同修订不能静默缩减产物要求。需求增版也不会静默删除旧阶段待办，须明确承接或取消。

每个前置引用包含 `coordination_root`、`batch_id`、`message_id`、`entity_id`、`revision`、`message_sha256`。来源限本组或 `batch.json.coordination_group.parent` 已绑定的直接父组；父组绑定须有实际批次路径、批次ID及 actor_id，并与子组协调者的真实聊天ID一致。父决策必须发给该协调者，不凭路径建立新权限。

放行依据须为来源组 main 的 ASSIGN／READY／RESOLVED／INTEGRATED；ACK、普通报告和仍在等待的阶段不能放行。发布时及通知前均重读来源，核对批次、内容哈希、当前修订与阶段是否已被取代。未知、不可读或过期时保留待核对，不通知执行。跨批引用只放 payload，`refs` 仍限本批。

参考 [阶段放行模板](../assets/阶段放行消息模板.json)。接收方先核对消息及前置依据，再按原任务责任链接单；不得因旧摘要写了“等待”忽略当前明确后继，也不得仅从通知到达的时机推断已放行。`inbox` 标出被后继取代的旧阶段；通知入口拒绝再次通知它。

## 按真实产物确认阶段完成

接收方执行阶段动作后，在正常 RESULT／CONSUMED 中合并 `payload.phase_receipt`，不单独再造一轮普通进度通知：

```json
{
  "transition_id":"本组实际放行消息ID",
  "artifacts":[{"path":"实际产物的绝对路径","file_sha256":"实际文件字节SHA256"}]
}
```

该回执须引用放行消息，收发方、实体和修订匹配，verification 为 passed。工具检查要求的产物全部存在、路径及文件哈希一致；约定 required_keys 时再读取 JSON 检查顶层字段。阶段回执不授予新文件写入权限，产物路径仍遵守原分派范围。恢复摘要可约定 `objective`、`assignment`、`acceptance`、`dependencies`、`next_step`；字段齐备不代替协调者实际读懂并核对内容。

`recover`／`recover --registry` 的 `phase_transitions_pending` 独立于原依赖和 ACK：仍在等待、只收到 ACK、缺产物回执、前置决策过期、文件缺失／变动均保持待办。阶段处理结束列入 `completed_phases`，`outcome: passed` 表示产物核验通过，`outcome: cancelled` 仅表示明确取消，不能说成业务完成。即使 open_requests、pending_messages、awaiting_confirmation 都为0，只要阶段待办仍存在，就不能宣布本轮完整闭环。阶段产物改变会使恢复状态及快照哈希变化；先核对实际结果，再补新回执，不盲目重做业务。

多级接续仍分别扫描父组与子组；协调者核对直接下层的真实轮次、当前阶段回执和产物内容，再向上汇总。不将下层自然结束、ACK齐全或本组清零代替整体验收。

## 兼容与能力边界

旧批次没有结构化阶段元数据时照常读取，不从旧自然语言或某个特定布尔字段反推阶段状态。遇到实际等待／放行歧义，在新消息补明确上下文及元数据，保留旧消息和运行目录；不能把“未登记阶段”说成“所有阶段已验证”。

这是显式登记后的消息与产物门槛，不是自动理解全文的全局状态机；不会递归追踪所有祖先、自动通知、自动完成语义验收或阻止绕过工具。前置批次的读取与本组发布不是跨组原子事务，接收执行前还须核对当前来源。维护或测试技能不创建真实聊天、不沿用历史通信授权。
