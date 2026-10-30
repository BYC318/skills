# 常用消息操作

分派、接单、交付、阻塞、就绪与关闭优先使用 `scripts/message_operations.py`；普通收到确认仍用 `coordination.py ack`。未覆盖的 REQUEST、RELEASE、INVALIDATED、INTEGRATED 或历史封装修正继续按原协议用 `emit`。两者共用原批次锁、不可变事件和校验，不建立另一套消息目录，不发送聊天通知。

```bash
python3 '实际技能目录/scripts/message_operations.py' accept --root '本批实际绝对路径' --actor '本逻辑身份' --input '本人实际请求.json'
```

输入均有唯一 `id` 和本人编写的 `payload`。工具从批次及原消息推导 envelope，不接受手填批次、sender、时间；类型仅deliver可选择RESULT／CONSUMED。同请求同ID重跑沿用首次时间并返回duplicate；不同内容不覆盖。旧修订／被取代阶段不经常用入口重新发布，历史消息仍可由底层协议读取。

| 操作 | 除id、payload外的输入 | 自动处理与边界 |
| --- | --- | --- |
| `assign` | recipient、entity_id、revision | 发布ASSIGN；payload.task_context提供root_task_ref、objective、local_scope、acceptance_refs、dependencies、deliverable，不代拆目标 |
| `accept` | 单个reply_to | 回复原发送方，refs只有这一条；本人填写objective、assignment、acceptance、dependencies、next_step，不自动宣称理解 |
| `deliver` | reply_to；可选kind=RESULT/CONSUMED、refs、artifact_paths、complete_phase | verification由执行者提供；计算实际文件哈希。complete_phase=true只从当前released读取全部约定产物生成phase_receipt，缺文件／字段／验证不通过则不发布 |
| `blocked` | reply_to；可选refs | payload写实际description、next_step；不自动重新分派 |
| `ready` | reply_to；可选refs、artifact_paths、phase | 仅协调者READY；引用本人原分派或发给本人的当前交付，审核判断仍归协调者 |
| `resolve` | 真实交付的reply_to、明确request_ids、本人核验reason；可选refs、phase | 从当前消费者RESULT/CONSUMED生成completed依据并关联原请求，不猜测应关闭哪些工作 |

附产物使用顶层 `artifact_paths` 非重复路径数组，须为已存在的规范绝对文件路径。工具只读并计算文件SHA256，不生成／改写产物，也不授予路径访问或源码权限。不要在payload手填artifacts、phase_transition、phase_receipt、recovery；其他业务字段保留。没有依赖时接单明确写“当前无前置”或显式空数组，不能遗漏字段或编造等待对象。

接单示例：

```json
{
  "id": "ACCEPT-MODULE-R2",
  "reply_to": "本组当前ASSIGN消息ID",
  "payload": {
    "objective": "本人理解的原始需求及来源",
    "assignment": "本层范围与排除项",
    "acceptance": ["本层实际验收项"],
    "dependencies": "等待谁；没有时明确说明",
    "next_step": "实际动作及交付对象"
  }
}
```

交付示例：

```json
{
  "id": "RESULT-MODULE-R2",
  "reply_to": "本组当前ASSIGN或READY消息ID",
  "artifact_paths": ["本人已生成报告的规范绝对路径"],
  "payload": {
    "description": "真实结果及尚未覆盖范围",
    "verification": {"status": "passed", "evidence": ["实际检查依据，结构化路径不放此数组"]}
  }
}
```

verification没有默认通过值；失败／未执行如实写failed／not_run。成功发布不等于聊天收到或协调者验收。

## 显式阶段

ready、resolve可附顶层 `phase`，遵守[阶段协议](delivery-and-phases.md)。新等待提供id、state=waiting、expected_artifacts。承接已有阶段时reply_to指当前阶段消息，工具沿用其ID及完整产物约定并生成supersedes和refs，不自动缩减或取消。

```json
{
  "id": "READY-MODULE-RESUME-R2",
  "reply_to": "本组当前waiting消息ID",
  "phase": {
    "state": "released",
    "prerequisites": [{"coordination_root": "实际本组或绑定直接父批次绝对路径", "message_id": "已实核当前决策ID"}]
  },
  "payload": {"description": "前置已实际满足，本层继续的动作"}
}
```

前置只提供实际组路径和消息ID，工具读回生成批次、实体、修订与内容哈希；发布及通知继续核对权限、绑定、有效修订。接收者仍须核对当前依据。跨组引用只放payload，不能混入本组refs。阶段交付使用deliver、reply_to=当前released ID、complete_phase=true；只生成回执，不代写本人摘要。

## 发布之后

命令未结束或失败不通知。成功后用返回的实际message_id经[受控通知](notification-gate.md)发送；确认与必要交付可合并，不为ACK／ACCEPTED单独唤醒。返回 `notification_sent: false` 明确表示这里只落盘，不能称作发送成功。
