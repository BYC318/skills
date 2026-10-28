#!/usr/bin/env python3
"""独立任务的本机持久信箱；不执行通知、Git 或消息正文中的动作。"""

import argparse
from contextlib import contextmanager
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile


KINDS = {"REQUEST", "ASSIGN", "RELEASE", "READY", "ACK", "ACCEPTED", "CONSUMED", "RESULT", "BLOCKED", "RESOLVED", "INTEGRATED", "INVALIDATED"}
MAIN_ONLY = {"ASSIGN", "READY", "RESOLVED", "INTEGRATED", "INVALIDATED"}
DECISIONS = {"ASSIGN", "READY", "INVALIDATED"}
FIELDS = {"batch_id", "id", "sender", "recipient", "kind", "entity_id", "revision", "created_at", "refs", "payload"}
ACTION_FIELDS = {"actor", "entity_id", "revision", "operation", "repo_id", "worktree", "source_sha"}


def sealed(value):
    return {"data": value, "sha256": hashlib.sha256(canonical(value)).hexdigest()}


def read_sealed(path):
    record = read_json(path)
    require(isinstance(record, dict) and set(record) == {"data", "sha256"}, "执行记录封装损坏")
    require(record["sha256"] == hashlib.sha256(canonical(record["data"])).hexdigest(), "执行记录哈希不符")
    return record["data"]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", value), "标识须为 ASCII 字母数字、横线或下划线")
    return value


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def read_json(path):
    require(not path.is_symlink() and path.is_file(), "资料缺失或不能是软链接：" + str(path))
    return json.loads(path.read_text(encoding="utf-8"))


def validate_config(config):
    require(isinstance(config, dict) and config.get("schema_version") == 1, "不支持的批次格式")
    identifier(config.get("batch_id"))
    actors = config.get("actors")
    require(isinstance(actors, dict) and actors, "批次须登记参与者")
    main = identifier(config.get("main"))
    for actor, info in actors.items():
        identifier(actor)
        require(isinstance(info, dict) and info.get("role") in ("main", "shared", "worker"), "参与者角色无效")
    require(main in actors and actors[main]["role"] == "main", "主任务未登记")
    require(sum(info["role"] == "main" for info in actors.values()) == 1, "同一批只能有一个主任务")
    require(isinstance(config.get("authorization"), str) and config["authorization"].strip(), "须记录实际用户授权")
    return config


@contextmanager
def locked(root):
    require(root.is_absolute() and root.is_dir(), "须传入已存在的绝对协调目录")
    lock = root / ".message.lock"
    require(not lock.is_symlink(), "锁文件不能是软链接")
    with lock.open("a+b") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def publish(path, value):
    """先完整写入并同步，再以硬链接原子发布；读者不会读到半份 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def validate_envelope(event, config):
    require(isinstance(event, dict) and set(event) == FIELDS, "消息字段须完整且不得增加未知字段")
    require(event["batch_id"] == config["batch_id"], "消息批次不符")
    for key in ("id", "sender", "recipient", "entity_id"):
        identifier(event[key])
    actors, main = config["actors"], config["main"]
    require(event["sender"] in actors and event["recipient"] in actors and event["sender"] != event["recipient"], "收发方未登记或相同")
    require(main in (event["sender"], event["recipient"]), "执行任务之间经主任务路由")
    require(event["kind"] in KINDS, "消息类型无效")
    if event["kind"] in MAIN_ONLY:
        require(event["sender"] == main, "此类决策仅由主任务发布")
    if event["kind"] == "RELEASE":
        require(actors[event["sender"]]["role"] == "shared", "公共交付仅由共享任务发布")
    require(type(event["revision"]) is int and event["revision"] > 0, "修订须为正整数")
    require(isinstance(event["created_at"], str), "时间须为带时区 ISO 字符串")
    moment = datetime.fromisoformat(event["created_at"].replace("Z", "+00:00"))
    require(moment.utcoffset() is not None, "时间须包含时区")
    require(isinstance(event["refs"], list) and all(isinstance(value, str) for value in event["refs"]), "refs 须为消息 ID 数组")
    require(len(set(event["refs"])) == len(event["refs"]), "引用不得重复")
    require(isinstance(event["payload"], dict), "payload 须为对象")


def validate_references(event, events):
    require(all(reference in events for reference in event["refs"]), "引用的消息尚未落盘")
    if event["kind"] in ("ACK", "ACCEPTED"):
        require(len(event["refs"]) == 1, "确认须恰好引用一条消息")
        original = events[event["refs"][0]]
        require(original["kind"] not in ("ACK", "ACCEPTED"), "不对确认消息重复确认")
        require(event["sender"] == original["recipient"] and event["recipient"] == original["sender"], "确认只能由原接收方回复原发送方")
        require((event["entity_id"], event["revision"]) == (original["entity_id"], original["revision"]), "确认的实体或修订不符")


def load_events(root, config):
    events = {}
    for path in sorted((root / "events").glob("*/*.json")):
        require(not path.parent.is_symlink(), "发送方目录不能是软链接")
        record = read_json(path)
        require(isinstance(record, dict) and set(record) == {"message", "sha256"}, "消息封装损坏")
        event = record["message"]
        require(hashlib.sha256(canonical(event)).hexdigest() == record["sha256"], "消息哈希不符")
        validate_envelope(event, config)
        require(path.stem == event["id"] and path.parent.name == event["sender"], "消息位置与身份不符")
        require(event["id"] not in events, "整批消息 ID 重复")
        events[event["id"]] = event
    for event in events.values():
        validate_references(event, events)
        recovery_resolution(event, events, config)
    return events


def current_revision(events, entity):
    return max((event["revision"] for event in events.values() if event["entity_id"] == entity and event["kind"] in DECISIONS), default=1)


def emit(root, sender, event):
    with locked(root):
        config = validate_config(read_json(root / "batch.json"))
        events = load_events(root, config)
        validate_envelope(event, config)
        require(sender == event["sender"], "发送方声明与消息不符")
        existing = events.get(event["id"])
        if existing:
            # 旧消息重发仍然幂等；不能因已发生新修订而再次执行旧动作。
            require(existing == event, "同消息 ID 的内容已变化，拒绝覆盖")
            return {"id": event["id"], "duplicate": True, "stale": event["revision"] < current_revision(events, event["entity_id"])}
        validate_references(event, events)
        recovery_resolution(event, {**events, event["id"]: event}, config)
        if event["kind"] not in ("ACK", "ACCEPTED"):
            revision = current_revision(events, event["entity_id"])
            if sender == config["main"]:
                require(event["revision"] >= revision, "不能新写旧修订动作；先核对主任务决策")
                if event["kind"] == "RESOLVED":
                    require(event["revision"] == revision, "关闭依赖不能自行升级需求修订")
            else:
                require(event["revision"] == revision, "执行方修订须等于主任务当前修订，不能自行升级或使用旧版")
        wrapper = {"message": event, "sha256": hashlib.sha256(canonical(event)).hexdigest()}
        publish(root / "events" / sender / (event["id"] + ".json"), wrapper)
        require(read_json(root / "events" / sender / (event["id"] + ".json")) == wrapper, "落盘读回不符")
        return {"id": event["id"], "duplicate": False, "stale": False}


def inbox(root, recipient):
    with locked(root):
        config = validate_config(read_json(root / "batch.json"))
        require(recipient in config["actors"], "接收方未登记")
        events = load_events(root, config)
        acknowledged = {event["refs"][0] for event in events.values() if event["kind"] == "ACK"}
        rows = []
        for event in sorted(events.values(), key=lambda item: (item["created_at"], item["id"])):
            if event["recipient"] != recipient:
                continue
            stale = event["revision"] < current_revision(events, event["entity_id"])
            status = "旧修订" if stale else "回执" if event["kind"] == "ACK" else "已确认收到" if event["id"] in acknowledged else "待确认"
            rows.append({"status": status, "message": event})
        return rows


def action_identity(plan, config):
    require(isinstance(plan, dict) and set(plan) == ACTION_FIELDS, "执行意图字段不符")
    require(plan["actor"] in config["actors"], "执行者未登记")
    identifier(plan["entity_id"])
    identifier(plan["repo_id"])
    require(type(plan["revision"]) is int and plan["revision"] > 0, "执行意图修订无效")
    require(plan["operation"] == "cherry_pick", "目前仅支持提交接入的执行意图")
    require(isinstance(plan["source_sha"], str) and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", plan["source_sha"]), "须使用小写完整源提交 SHA")
    require(isinstance(plan["worktree"], str) and Path(plan["worktree"]).is_absolute(), "源码 worktree 须为绝对路径")
    require(str(Path(plan["worktree"]).resolve()) == plan["worktree"], "须使用源码 worktree 的规范绝对路径")
    # 需求修订或执行者变化不会让同一工作区中的同一源提交变成一次新接入。
    key = {field: plan[field] for field in ("operation", "repo_id", "worktree", "source_sha")}
    return hashlib.sha256(canonical(key)).hexdigest()


def validate_action_result(result):
    require(isinstance(result, dict) and set(result) == {"local_sha", "verification"}, "完成回执字段不符")
    require(isinstance(result["local_sha"], str) and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", result["local_sha"]), "完成回执须记录实际本地 SHA")
    verification = result["verification"]
    require(isinstance(verification, dict) and verification.get("status") == "passed", "核验成功后才能完成执行意图")
    require(isinstance(verification.get("evidence"), list) and verification["evidence"] and all(isinstance(item, str) and item.strip() for item in verification["evidence"]), "完成回执须记录实际核验依据")


def load_actions(root, config):
    actions = []
    folder = root / "actions"
    require(not folder.is_symlink(), "执行记录目录不能是软链接")
    if not folder.exists():
        return actions
    for path in sorted(folder.glob("*.intent.json")):
        plan = read_sealed(path)
        identity = action_identity(plan, config)
        require(path.name == identity + ".intent.json", "执行意图身份不符")
        done = folder / (identity + ".done.json")
        result = read_sealed(done) if done.exists() else None
        if result is not None:
            validate_action_result(result)
        actions.append({"action_id": identity, "plan": plan, "result": result})
    for done in folder.glob("*.done.json"):
        require((folder / done.name.replace(".done.json", ".intent.json")).is_file(), "完成回执缺少执行意图")
    return actions


def begin_action(root, actor, plan):
    with locked(root):
        config = validate_config(read_json(root / "batch.json"))
        identity = action_identity(plan, config)
        require(actor == plan["actor"], "执行者声明与意图不符")
        actions = {item["action_id"]: item for item in load_actions(root, config)}
        if identity in actions:
            return {"action_id": identity, "can_execute": False, "duplicate": True, "status": "已记录完成，禁止重复接入" if actions[identity]["result"] else "执行结果待核对，禁止直接重做"}
        require(not any(item["result"] is None and item["plan"]["worktree"] == plan["worktree"] for item in actions.values()), "同一worktree仍有结果未知的接入，先核验并处理原意图")
        events = load_events(root, config)
        require(plan["revision"] == current_revision(events, plan["entity_id"]), "执行意图必须采用当前有效修订")
        publish(root / "actions" / (identity + ".intent.json"), sealed(plan))
        return {"action_id": identity, "can_execute": True, "duplicate": False, "status": "意图已落盘；执行前仍须核对真实Git"}


def finish_action(root, actor, identity, result):
    with locked(root):
        config = validate_config(read_json(root / "batch.json"))
        actions = {item["action_id"]: item for item in load_actions(root, config)}
        require(identity in actions and actions[identity]["plan"]["actor"] == actor, "执行意图不存在或不属于本执行者")
        validate_action_result(result)
        if actions[identity]["result"] is not None:
            require(actions[identity]["result"] == result, "完成回执不能覆盖为不同结果")
            return {"action_id": identity, "duplicate": True, "can_execute": False}
        # 旧修订的真实执行结果也必须保留；补回执不等于批准旧代码继续使用。
        publish(root / "actions" / (identity + ".done.json"), sealed(result))
        return {"action_id": identity, "duplicate": False, "can_execute": False}


def recovery_resolution(event, events, config):
    claim = event["payload"].get("recovery")
    if claim is None:
        return None
    require(isinstance(claim, dict), "recovery 须为对象")
    # 归档结论由主任务明确发布；普通 RESULT 文本或 ACK 不会关闭依赖。
    require(event["sender"] == config["main"] and event["kind"] in ("RESOLVED", "INTEGRATED", "INVALIDATED"), "恢复关闭结论仅由主任务发布")
    require(claim.get("resolution") in ("completed", "cancelled", "deferred"), "恢复关闭结论无效")
    consumer = claim.get("consumer")
    require(consumer in config["actors"] and consumer != config["main"], "恢复结论的消费者无效")
    require(event["recipient"] == consumer, "关闭结论须发给对应消费者")
    requests = claim.get("request_ids")
    require(isinstance(requests, list) and requests and all(isinstance(item, str) and item in event["refs"] for item in requests), "恢复结论须引用被处理的原请求")
    require(all(events[item]["kind"] in ("REQUEST", "ASSIGN", "READY") and events[item]["entity_id"] == event["entity_id"] for item in requests), "恢复结论与原请求或分派实体不符")
    require(all(events[item]["revision"] <= event["revision"] for item in requests), "旧修订不能关闭较新要求")
    require(isinstance(claim.get("reason"), str) and claim["reason"].strip(), "恢复结论须说明依据")
    if claim["resolution"] == "completed":
        require(event["kind"] in ("RESOLVED", "INTEGRATED"), "完成依赖使用RESOLVED或已核验的INTEGRATED")
        evidence = claim.get("evidence_refs")
        require(isinstance(evidence, list) and evidence and all(item in event["refs"] for item in evidence), "完成结论须关联实际消费或验证回执")
        for identity in evidence:
            receipt = events[identity]
            require(receipt["kind"] in ("RESULT", "CONSUMED") and receipt["sender"] == consumer and receipt["entity_id"] == event["entity_id"] and receipt["revision"] == event["revision"], "完成结论关联的消费回执不符")
            verification = receipt["payload"].get("verification", {})
            require(isinstance(verification, dict) and verification.get("status") == "passed" and isinstance(verification.get("evidence"), list) and verification["evidence"] and all(isinstance(item, str) and item.strip() for item in verification["evidence"]), "消费回执缺少验证结果与依据")
    if claim["resolution"] == "deferred":
        require(isinstance(claim.get("next_batch"), str) and claim["next_batch"].strip(), "延后必须登记后续批次或待安排位置")
    if claim["resolution"] in ("cancelled", "deferred"):
        require(event["kind"] == "INVALIDATED", "取消或延后须明确发布INVALIDATED")
    return claim


def recover(root, actor):
    """重扫本批事实；不依据自然语言、文件名顺序或 ACK 推断业务已经完成。"""
    with locked(root):
        config = validate_config(read_json(root / "batch.json"))
        require(actor in config["actors"], "恢复执行者未登记")
        events = load_events(root, config)
        actions = load_actions(root, config)
        main = config["main"]
        acknowledgements = {event["refs"][0] for event in events.values() if event["kind"] in ("ACK", "ACCEPTED")}
        resolutions = {identity: recovery_resolution(event, events, config) for identity, event in events.items()}
        incoming, outgoing, superseded = [], [], []
        for identity, event in sorted(events.items()):
            if event["kind"] in ("ACK", "ACCEPTED") or identity in acknowledgements:
                continue
            summary = {key: event[key] for key in ("id", "entity_id", "revision", "kind", "sender", "recipient")}
            if event["revision"] < current_revision(events, event["entity_id"]):
                if actor in (event["sender"], event["recipient"]) or actor == main:
                    superseded.append(summary)
            else:
                if event["recipient"] == actor:
                    incoming.append(summary)
                if event["sender"] == actor:
                    outgoing.append(summary)
        requests, unlinked = [], []
        for entity in sorted({event["entity_id"] for event in events.values()}):
            history = [event for event in events.values() if event["entity_id"] == entity]
            original = [event for event in history if event["kind"] == "REQUEST"]
            if not original:
                # 用户直接向主任务下达的工作可能只有 ASSIGN，没有页面侧 REQUEST。
                original = [event for event in history if event["kind"] == "ASSIGN"] or [event for event in history if event["kind"] == "READY"]
            if not original:
                unlinked.extend({"id": event["id"], "entity_id": entity, "kind": event["kind"], "sender": event["sender"]} for event in history if event["kind"] in ("BLOCKED", "RESULT", "CONSUMED") and (actor == main or actor in (event["sender"], event["recipient"])))
                continue
            revision = current_revision(events, entity)
            current = [event for event in history if event["revision"] == revision]
            consumers = {event["sender"] for event in original if event["sender"] != main}
            owners = {event["recipient"] for event in current if event["kind"] == "ASSIGN"}
            consumers.update(event["recipient"] for event in history if event["kind"] in ("ASSIGN", "READY") and config["actors"][event["recipient"]]["role"] == "worker")
            for event in history:
                declared = event["payload"].get("consumers", []) if event["sender"] == main else []
                require(isinstance(declared, list) and all(item in config["actors"] and item != main for item in declared), "消费者列表无效")
                consumers.update(declared)
            if not consumers:
                consumers.update(owners or {event["recipient"] for event in original if event["recipient"] != main})
            if actor != main and actor not in consumers | owners:
                continue
            progress = []
            for consumer in sorted(consumers):
                claims = [(event, resolutions[event["id"]]) for event in current if resolutions[event["id"]] and resolutions[event["id"]]["consumer"] == consumer]
                outcomes = {claim["resolution"] for _, claim in claims}
                covered = {identity for _, claim in claims for identity in claim["request_ids"]}
                relevant = [event for event in original if event["sender"] == consumer] or original
                unresolved = sorted(event["id"] for event in relevant if event["id"] not in covered)
                closed = len(outcomes) == 1 and outcomes <= {"completed", "cancelled"} and not unresolved
                if len(outcomes) > 1:
                    status, next_step = "关闭结论冲突，待核对", "核对同修订矛盾结论，主任务发布明确的新修订"
                    closed = False
                elif closed:
                    status = "已记录完成" if outcomes == {"completed"} else "已明确取消"
                    next_step = "保留来源与证据，不重复执行"
                elif outcomes == {"deferred"}:
                    status, next_step = "已延后，仍未完成", "按已登记的后续批次继续跟踪"
                elif any(event["kind"] in ("CONSUMED", "RESULT") and event["sender"] == consumer for event in current):
                    status, next_step = "已有结果，待主任务核验关闭", "核验消费、验证依据及全部请求，主任务发布结构化结论"
                elif any(event["kind"] == "READY" and event["recipient"] == consumer for event in current):
                    status, next_step = "已通知可接入，待消费回执", "先查执行意图、完成回执及真实Git，再决定接入或补回执"
                elif any(event["kind"] == "RELEASE" for event in current):
                    status, next_step = "已交付，待审核下发", "主任务核对当前修订交付，再向消费者发布READY"
                elif any(event["kind"] == "ASSIGN" for event in current):
                    status, next_step = "已分派，待交付", "核对负责方进度与当前契约，继续未完成交付"
                else:
                    status, next_step = "待主任务处理", "主任务查重并核对用户要求，明确保留、修订或取消"
                progress.append({"consumer": consumer, "status": status, "closed": closed, "unresolved_request_ids": unresolved, "next_step": next_step})
            requests.append({"entity_id": entity, "revision": revision, "description": original[0]["payload"].get("description", "未填写说明"), "request_ids": sorted(event["id"] for event in original), "request_details": [{"id": event["id"], "description": event["payload"].get("description", "未填写说明")} for event in original], "owners": sorted(owners), "consumers": progress, "open": not progress or any(not item["closed"] for item in progress), "blocked_message_ids": sorted(event["id"] for event in current if event["kind"] == "BLOCKED")})
        pending_actions = []
        completed_actions = []
        for action in actions:
            if actor != main and action["plan"]["actor"] != actor:
                continue
            item = {**action, "can_execute": False, "stale": action["plan"]["revision"] < current_revision(events, action["plan"]["entity_id"])}
            if action["result"] is None:
                item.update(status="执行结果待核对", next_step="先核对真实Git，已接入则补完成回执；核实前禁止直接重做")
                pending_actions.append(item)
            else:
                completed_actions.append(item)
        next_steps = [{"owner": item["plan"]["actor"], "entity_id": item["plan"]["entity_id"], "action": item["next_step"], "action_id": item["action_id"]} for item in pending_actions]
        next_steps.extend({"owner": main, "entity_id": item["entity_id"], "action": "记录缺少原始请求/分派，核对历史并补录，不能据此判定没有待办", "message_id": item["id"]} for item in unlinked)
        next_steps.extend({"owner": actor, "entity_id": item["entity_id"], "action": "核对并确认收到消息", "message_id": item["id"]} for item in incoming)
        next_steps.extend({"owner": item["recipient"], "entity_id": item["entity_id"], "action": "核对送达情况；必要时重发原通知，不重做业务动作", "message_id": item["id"]} for item in outgoing)
        for request in requests:
            if request["open"] and request["blocked_message_ids"]:
                next_steps.append({"owner": main, "entity_id": request["entity_id"], "action": "核对阻塞记录与后续处理结果，再决定是否继续", "message_ids": request["blocked_message_ids"]})
            next_steps.extend({"owner": sorted(request["owners"]) if consumer["status"] == "已分派，待交付" else consumer["consumer"], "entity_id": request["entity_id"], "action": consumer["next_step"]} for consumer in request["consumers"] if not consumer["closed"] and (actor == main or actor == consumer["consumer"] or actor in request["owners"]))
        return {"batch_id": config["batch_id"], "actor": actor, "snapshot_sha256": hashlib.sha256(canonical({"config": config, "events": events, "actions": actions})).hexdigest(), "open_requests": [item for item in requests if item["open"]], "closed_requests": [item for item in requests if not item["open"]], "unlinked_events": unlinked, "pending_messages": incoming, "awaiting_confirmation": outgoing, "superseded_messages": superseded, "actions_pending_verification": pending_actions, "completed_actions": completed_actions, "next_steps": next_steps, "limitations": ["仅扫描本批已落盘资料；未落盘用户纠正须从原聊天补录", "不会发送消息、运行Git或自动执行下一步；完成记录不证明业务或UI验收通过", "跨批依赖仍须按长期任务目录核对；旧格式无明确关闭依据时保留未完成"]}


def recover_registry(path, actor):
    require(path.is_absolute(), "长期任务目录须为绝对路径")
    registry = read_json(path)
    require(isinstance(registry, dict) and registry.get("schema_version") == 1 and actor in registry.get("tasks", {}), "长期任务目录或执行者无效")
    batches = registry.get("batches")
    require(isinstance(batches, list) and batches, "长期任务目录尚未登记批次，不能据此判定无待办")
    reports, unavailable, identities, roots = [], [], set(), set()
    aggregate = {key: [] for key in ("open_requests", "closed_requests", "unlinked_events", "pending_messages", "awaiting_confirmation", "superseded_messages", "actions_pending_verification", "completed_actions", "next_steps")}
    for batch in batches:
        require(isinstance(batch, dict), "批次索引格式无效")
        identity = identifier(batch.get("batch_id"))
        root = batch.get("coordination_root")
        require(isinstance(root, str) and Path(root).is_absolute(), "批次索引须登记绝对 coordination_root")
        require(identity not in identities and root not in roots, "长期目录的批次或协调路径重复")
        identities.add(identity)
        roots.add(root)
        try:
            report = recover(Path(root), actor)
            require(report["batch_id"] == identity, "批次索引与真实批次身份不符")
            reports.append({"batch_id": identity, "coordination_root": root, "snapshot_sha256": report["snapshot_sha256"]})
            for key in aggregate:
                aggregate[key].extend({**item, "batch_id": identity, "coordination_root": root} for item in report[key])
        except (ValueError, OSError, KeyError, TypeError) as error:
            # 即使目录曾写“已完成”，也不能因旧批缺失/损坏而把未知待办当作零。
            unavailable.append({"batch_id": identity, "coordination_root": root, "reason": str(error)})
    require(read_json(path) == registry, "扫描期间长期目录已变化，请重新恢复对账")
    aggregate["next_steps"] = [{"owner": actor, "entity_id": item["batch_id"], "action": "批次未能扫描：" + item["reason"]} for item in unavailable] + aggregate["next_steps"]
    return {"batch_id": "全部登记批次", "actor": actor, "registry": str(path), "scan_complete": not unavailable, "batches": reports, "unavailable_batches": unavailable, "snapshot_sha256": hashlib.sha256(canonical({"registry": registry, "reports": reports, "unavailable": unavailable})).hexdigest(), **aggregate, "limitations": ["扫描全部登记批次，不依据目录中的完成标记省略旧请求；索引未登记的批次无法自动发现", "逐批加锁读取，不提供跨批原子事务；未落盘用户纠正仍须从原聊天补录", "不会发送消息或执行Git；执行意图去重以单批次为范围，新批次仍需核对历史与真实Git"]}


def recovery_markdown(report):
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")

    lines = ["# 恢复对账", "", f"批次：{report['batch_id']}；任务：{report['actor']}", "", f"未完成请求：{len(report['open_requests'])}；待确认收到：{len(report['pending_messages'])}；发出后待确认：{len(report['awaiting_confirmation'])}；执行结果待核对：{len(report['actions_pending_verification'])}", "", "## 未完成请求", "", "| 批次 / 请求 | 有效修订 | 消费者 | 当前状态 | 下一步 |", "| --- | --- | --- | --- | --- |"]
    if "scan_complete" in report:
        lines[4:4] = ["扫描完整：" + ("是" if report["scan_complete"] else "否，存在无法读取的批次，不能判定待办已清零"), ""]
    for item in report["open_requests"]:
        for consumer in item["consumers"]:
            if not consumer["closed"]:
                label = item.get("batch_id", report["batch_id"]) + " / " + item["entity_id"] + " · " + str(item["description"])
                lines.append("| " + " | ".join(cell(value) for value in (label, item["revision"], consumer["consumer"], consumer["status"], consumer["next_step"])) + " |")
    lines += ["", "## 执行结果待核对", ""]
    lines += [f"- {item['plan']['actor']} / {item['plan']['worktree']} / 源提交 {item['plan']['source_sha']}：先核验 Git，禁止直接重做；动作 ID {item['action_id']}" for item in report["actions_pending_verification"]] or ["无。"]
    for label, key in (("待确认收到的消息", "pending_messages"), ("发出后等待确认的消息", "awaiting_confirmation")):
        lines += ["", "## " + label, ""]
        lines += [f"- {item.get('batch_id', report['batch_id'])} / {item['id']}：{item['sender']} → {item['recipient']}，{item['entity_id']} / 修订 {item['revision']}，{item['kind']}" for item in report[key]] or ["无。"]
    lines += ["", "## 下一步", ""]
    for item in report["next_steps"]:
        owner = "、".join(item["owner"]) if isinstance(item["owner"], list) else item["owner"]
        lines.append(f"- {item.get('batch_id', report['batch_id'])} / {owner} / {item['entity_id']}：{cell(item['action'])}")
    lines += ["", "## 范围说明", ""] + ["- " + item for item in report["limitations"]]
    return "\n".join(lines) + "\n"


def initialize(root, config):
    validate_config(config)
    require(root.is_absolute(), "协调目录须为绝对路径")
    root.mkdir(parents=True, exist_ok=False)
    publish(root / "batch.json", config)
    for actor in config["actors"]:
        (root / "events" / actor).mkdir(parents=True)
    (root / "deliveries").mkdir()


def main():
    parser = argparse.ArgumentParser(description="独立任务持久消息：落盘、去重、确认及恢复扫描")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "emit", "inbox", "check", "recover", "begin-action", "finish-action"):
        command = sub.add_parser(name)
        if name == "recover":
            scope = command.add_mutually_exclusive_group(required=True)
            scope.add_argument("--root", type=Path)
            scope.add_argument("--registry", type=Path)
        else:
            command.add_argument("--root", type=Path, required=True)
        if name == "init":
            command.add_argument("--config", type=Path, required=True)
        elif name == "emit":
            command.add_argument("--sender", required=True)
            command.add_argument("--event", type=Path, required=True)
        elif name == "inbox":
            command.add_argument("--recipient", required=True)
        elif name in ("recover", "begin-action", "finish-action"):
            command.add_argument("--actor", required=True)
            if name == "recover":
                command.add_argument("--format", choices=("json", "markdown"), default="json")
            elif name == "begin-action":
                command.add_argument("--plan", type=Path, required=True)
            elif name == "finish-action":
                command.add_argument("--action-id", required=True)
                command.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "init":
            initialize(args.root, read_json(args.config))
            result = {"created": str(args.root), "tasks_started": 0}
        elif args.command == "emit":
            result = emit(args.root, args.sender, read_json(args.event))
        elif args.command == "inbox":
            result = inbox(args.root, args.recipient)
        elif args.command == "recover":
            result = recover_registry(args.registry, args.actor) if args.registry else recover(args.root, args.actor)
        elif args.command == "begin-action":
            result = begin_action(args.root, args.actor, read_json(args.plan))
        elif args.command == "finish-action":
            result = finish_action(args.root, args.actor, args.action_id, read_json(args.result))
        else:
            with locked(args.root):
                config = validate_config(read_json(args.root / "batch.json"))
                events = load_events(args.root, config)
                actions = load_actions(args.root, config)
                for event in events.values():
                    recovery_resolution(event, events, config)
                result = {"valid": True, "messages": len(events), "actions": len(actions), "task_completion_verified": False}
        print(recovery_markdown(result) if args.command == "recover" and args.format == "markdown" else json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print("协作消息失败：" + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
