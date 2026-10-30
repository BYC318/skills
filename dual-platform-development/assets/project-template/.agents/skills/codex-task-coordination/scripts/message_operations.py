#!/usr/bin/env python3
"""常用消息封装；只发布持久事件，不通知聊天，也不替调用方判断业务完成。"""

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import coordination as co


OPERATIONS = {"assign", "accept", "deliver", "blocked", "ready", "resolve"}
COMMON_FIELDS = {"id", "payload", "artifact_paths"}
REPLY_FIELDS = {"reply_to", "refs"}
UNDERSTANDING = ("objective", "assignment", "acceptance", "dependencies", "next_step")


def supplied_context(payload, fields):
    # 显式空数组表示本人已判断无依赖，区别于遗漏字段；不为通过校验编造等待对象。
    return (all(payload.get(key) for key in fields if key != "dependencies") and
            "dependencies" in payload and (payload["dependencies"] == [] or bool(payload["dependencies"])))


def artifact(path):
    co.require(isinstance(path, str), "产物路径须为字符串")
    file = Path(path)
    co.require(file.is_absolute() and str(file.resolve()) == path and file.is_file() and not file.is_symlink(), "产物须为已存在的规范绝对文件路径")
    return {"path": path, "file_sha256": hashlib.sha256(file.read_bytes()).hexdigest()}


def phase_definition(root, request, source, events, config):
    phase = copy.deepcopy(request["phase"])
    co.require(isinstance(phase, dict) and set(phase) <= {"id", "state", "expected_artifacts", "prerequisites"}, "阶段封装字段无效")
    co.require(phase.get("state") in ("waiting", "released"), "常用入口只登记等待或放行；取消继续使用明确INVALIDATED")
    previous = source["payload"].get("phase_transition")
    if previous is not None:
        # 同修订沿用原产物约定，避免修消息时意外缩减验收；底层再校验唯一后继。
        for key in ("id", "expected_artifacts"):
            co.require(key not in phase or phase[key] == previous[key], "阶段接续不能修改原ID或产物约定")
            phase[key] = copy.deepcopy(previous[key])
        phase["supersedes"] = source["id"]
    proofs = []
    prerequisites = phase.get("prerequisites", [])
    co.require(isinstance(prerequisites, list), "prerequisites须为前置引用数组")
    for item in prerequisites:
        co.require(isinstance(item, dict) and set(item) <= {"coordination_root", "message_id"} and "message_id" in item, "前置依据只提供实际组路径和消息ID")
        group = Path(item.get("coordination_root", str(root)))
        parent = config.get("coordination_group", {}).get("parent") or {}
        co.require(group.is_absolute() and str(group.resolve()) == str(group), "前置批次须为规范绝对路径")
        co.require(group == root or str(group) == parent.get("coordination_root"), "只能读取本组或已绑定直接父组的前置依据")
        cfg = config if group == root else co.validate_config(co.read_json(group / "batch.json"))
        # 不同时持有父子组锁；发布与通知入口还会重核权威来源及当前修订。
        messages = events if group == root else co.load_events(group, cfg)
        co.require(item["message_id"] in messages, "阶段前置消息不存在")
        event = messages[item["message_id"]]
        meta = co.message_metadata(group, event)
        proofs.append({"coordination_root": str(group), "batch_id": cfg["batch_id"],
                       **{key: meta[key] for key in ("message_id", "entity_id", "revision", "message_sha256")}})
    if "prerequisites" in phase:
        phase["prerequisites"] = proofs
    return phase


def operate(root, actor, operation, request):
    co.require(operation in OPERATIONS and isinstance(request, dict), "常用操作或请求格式无效")
    extra = {"recipient", "entity_id", "revision"} if operation == "assign" else REPLY_FIELDS
    if operation == "accept":
        extra = {"reply_to"}
    if operation == "deliver":
        extra |= {"kind", "complete_phase"}
    if operation in ("ready", "resolve"):
        extra |= {"phase"}
    if operation == "resolve":
        extra |= {"request_ids", "reason"}
    co.require(set(request) <= COMMON_FIELDS | extra, "常用操作包含不支持的字段；接单只引用reply_to，其他确认使用ack")
    co.identifier(request.get("id"))
    payload = copy.deepcopy(request.get("payload"))
    co.require(isinstance(payload, dict), "payload须为调用方实际编写的对象")
    co.require(not {"artifacts", "phase_transition", "phase_receipt", "recovery"} & set(payload), "产物、阶段和关闭元数据由封装生成，不在payload手填")
    paths = request.get("artifact_paths", [])
    co.require(isinstance(paths, list) and all(isinstance(path, str) for path in paths) and
               len(paths) == len(set(paths)), "artifact_paths须为不重复的路径数组")
    with co.locked(root):
        config = co.validate_config(co.read_json(root / "batch.json"))
        events = co.load_events(root, config)
        co.require(actor in config["actors"], "执行者未登记")
        existing = events.get(request["id"])
        source = None
        if operation == "assign":
            kind, recipient = "ASSIGN", request.get("recipient")
            entity, revision, refs = request.get("entity_id"), request.get("revision"), []
            context = payload.get("task_context")
            co.require(isinstance(context, dict) and supplied_context(context, ("root_task_ref", "objective", "local_scope", "acceptance_refs", "dependencies", "deliverable")), "分派须提供原始目标、本层范围、验收、依赖和交付上下文")
        else:
            identity = request.get("reply_to")
            co.require(isinstance(identity, str) and identity in events, "reply_to须为实际已发布消息ID")
            source = events[identity]
            co.require(actor in (source["sender"], source["recipient"]) and source["kind"] not in ("ACK", "ACCEPTED"), "不能从其他参与者或确认消息派生工作")
            entity, revision = source["entity_id"], source["revision"]
            co.require(revision == co.current_revision(events, entity) and not co.phase_successors(source, events), "引用已过期；先恢复当前分派或阶段")
            recipient = source["recipient"] if source["sender"] == actor else source["sender"]
            more = request.get("refs", [])
            co.require(isinstance(more, list) and all(isinstance(item, str) for item in more), "refs须为消息ID数组")
            refs = list(dict.fromkeys([identity, *more]))
            kind = {"accept": "ACCEPTED", "deliver": request.get("kind", "RESULT"),
                    "blocked": "BLOCKED", "ready": "READY", "resolve": "RESOLVED"}[operation]
            if operation in ("accept", "deliver", "blocked"):
                co.require(source["recipient"] == actor, "接单、交付或阻塞须来自发给本人的工作")
            if operation == "accept":
                co.require(supplied_context(payload, UNDERSTANDING), "接单理解须由本人填写目标、分派、验收、依赖及下一步")
            if operation == "deliver":
                co.require(kind in ("RESULT", "CONSUMED"), "交付只使用RESULT或CONSUMED")
                co.validate_verification(payload.get("verification"))
                co.require(type(request.get("complete_phase", False)) is bool, "complete_phase须为布尔值")
                if request.get("complete_phase"):
                    phase = source["payload"].get("phase_transition", {})
                    co.require(phase.get("state") == "released", "阶段交付须引用当前明确放行消息")
                    payload["phase_receipt"] = {"transition_id": identity, "artifacts": [artifact(item["path"]) for item in phase["expected_artifacts"]]}
            if operation == "blocked":
                co.require(payload.get("description") and payload.get("next_step"), "阻塞须说明实际原因及下一步")
            if operation == "resolve":
                co.require(source["recipient"] == actor and source["kind"] in ("RESULT", "CONSUMED"), "关闭须引用本消费者当前真实交付")
                ids = request.get("request_ids")
                co.require(isinstance(ids, list) and ids and all(isinstance(item, str) for item in ids), "关闭须明确列出本人已审核的原请求")
                reason = request.get("reason")
                co.require(isinstance(reason, str) and reason.strip(), "关闭须由协调者说明实际核验依据")
                refs = list(dict.fromkeys([*refs, *ids]))
                payload["recovery"] = {"resolution": "completed", "consumer": recipient,
                                       "request_ids": ids, "evidence_refs": [identity], "reason": reason}
            if "phase" in request:
                payload["phase_transition"] = phase_definition(root, request, source, events, config)
        if paths:
            payload["artifacts"] = [artifact(path) for path in paths]
        event = {"batch_id": config["batch_id"], "id": request["id"], "sender": actor, "recipient": recipient,
                 "kind": kind, "entity_id": entity, "revision": revision, "refs": refs, "payload": payload,
                 "created_at": existing["created_at"] if existing else datetime.now(timezone.utc).isoformat()}
        # 构建和发布共用一把批次锁；重复运行沿用首次时间，不能覆盖旧内容或重复生成事件。
        result = co._emit_locked(root, actor, event, config, events)
        return {**result, **co.message_metadata(root, event), "notification_sent": False}


def main():
    parser = argparse.ArgumentParser(description="分派、理解接单、交付、阻塞、就绪和关闭的常用消息入口")
    parser.add_argument("operation", choices=sorted(OPERATIONS))
    parser.add_argument("--root", type=co.absolute_path, required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--input", type=co.absolute_path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(operate(args.root, args.actor, args.operation, co.read_json(args.input)), ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print("消息封装失败：" + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
