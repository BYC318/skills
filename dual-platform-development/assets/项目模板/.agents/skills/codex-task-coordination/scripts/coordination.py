#!/usr/bin/env python3
"""独立任务的本机持久信箱；不执行通知、Git 或消息正文中的动作。"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
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


def absolute_path(value):
    """CLI不依赖启动目录解析资料；在读取或建立锁之前拒绝相对路径。"""
    path = Path(value)
    if not path.is_absolute() or "\0" in str(path):
        raise argparse.ArgumentTypeError("须使用绝对路径：" + str(value))
    return path


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


def publish_event(root, event):
    wrapper = {"message": event, "sha256": hashlib.sha256(canonical(event)).hexdigest()}
    path = root / "events" / event["sender"] / (event["id"] + ".json")
    publish(path, wrapper)
    require(read_json(path) == wrapper, "落盘读回不符")


def validate_verification(value, require_passed=False):
    require(isinstance(value, dict) and value.get("status") in ("passed", "failed", "not_run"), "verification.status 须为 passed、failed 或 not_run")
    evidence = value.get("evidence")
    require(isinstance(evidence, list) and evidence and all(isinstance(item, str) and item.strip() for item in evidence), "verification.evidence 须为非空字符串数组；结构化路径与哈希放入 artifacts")
    require(not require_passed or value["status"] == "passed", "核验通过后才能关闭依赖或完成阶段")


def phase_key(event):
    phase = event["payload"].get("phase_transition")
    return (event["entity_id"], event["recipient"], phase["id"]) if phase is not None else None


def phase_successors(event, events):
    return [item for item in events.values() if item["payload"].get("phase_transition", {}).get("supersedes") == event["id"]]


def validate_phase_definition(event, events, config):
    phase = event["payload"].get("phase_transition")
    if phase is None:
        return
    require(event["sender"] == config["main"] and event["kind"] in ("ASSIGN", "READY", "RESOLVED", "INTEGRATED", "INVALIDATED"), "阶段状态须由本组协调者发布")
    require(isinstance(phase, dict), "phase_transition 须为对象")
    identifier(phase.get("id"))
    require(phase.get("state") in ("waiting", "released", "cancelled"), "阶段状态须为 waiting、released 或 cancelled")
    require((event["kind"] == "INVALIDATED") == (phase["state"] == "cancelled"), "取消阶段须使用INVALIDATED，不能伪装成放行")
    expected = phase.get("expected_artifacts")
    require(isinstance(expected, list) and expected, "阶段须登记下层实际应交付的产物")
    paths = []
    for item in expected:
        require(isinstance(item, dict) and isinstance(item.get("path"), str) and Path(item["path"]).is_absolute(), "阶段产物须登记绝对路径")
        require(str(Path(item["path"]).resolve()) == item["path"], "阶段产物路径须规范化且不能经过软链接")
        keys = item.get("required_keys", [])
        require(isinstance(keys, list) and all(isinstance(key, str) and key.strip() for key in keys), "required_keys 须为JSON顶层字段名数组")
        paths.append(item["path"])
    require(len(set(paths)) == len(paths), "阶段产物路径不得重复")
    prerequisites = phase.get("prerequisites", [])
    require(isinstance(prerequisites, list) and (phase["state"] != "released" or prerequisites), "放行阶段须携带已核验的前置决策引用")
    previous = phase.get("supersedes")
    if phase["state"] == "cancelled":
        require(previous is not None and isinstance(phase.get("reason"), str) and phase["reason"].strip(), "取消阶段须明确承接原阶段并记录授权或决策依据")
    if previous is not None:
        require(previous in event["refs"] and previous in events, "阶段后继须引用本组原阶段消息")
        require(phase_key(events[previous]) == phase_key(event) and events[previous]["revision"] <= event["revision"], "阶段后继须保持同一实体、接收者及阶段身份")
        if events[previous]["revision"] == event["revision"]:
            require(expected == events[previous]["payload"]["phase_transition"]["expected_artifacts"], "同修订阶段不能静默缩减或替换产物要求")
    peers = [item for item in events.values() if item["id"] != event["id"] and phase_key(item) == phase_key(event)]
    heads = [item for item in peers if not phase_successors(item, {key: value for key, value in events.items() if key != event["id"]})]
    require(not heads or (len(heads) == 1 and previous == heads[0]["id"]), "阶段变化须显式承接唯一当前消息，不能分叉或仅改变旧消息的通知时机")


def verify_phase_prerequisites(root, event, events, config):
    phase = event["payload"]["phase_transition"]
    require(phase["state"] == "released", "阶段仍在等待，不能执行后续动作")
    observed = []
    parent = config.get("coordination_group", {}).get("parent") or {}
    for proof in phase["prerequisites"]:
        require(isinstance(proof, dict) and isinstance(proof.get("coordination_root"), str), "阶段前置引用须为结构化批次消息")
        source_root = Path(proof["coordination_root"])
        require(source_root.is_absolute() and str(source_root.resolve()) == str(source_root), "前置批次须为规范绝对路径")
        if source_root == root:
            source_config, source_events = config, events
        else:
            # 只查已绑定的直接父组，不沿消息任意读取另一个项目，也不跨组持锁。
            require(str(source_root) == parent.get("coordination_root") and proof.get("batch_id") == parent.get("batch_id"), "前置引用不属于本组或已绑定直接父组")
            source_config = validate_config(read_json(source_root / "batch.json"))
            source_events = load_events(source_root, source_config)
            parent_actor = parent.get("actor_id")
            require(parent_actor in source_config["actors"], "父组协调身份未绑定")
            local_thread = config["actors"][config["main"]].get("thread_id")
            require(local_thread and source_config["actors"][parent_actor].get("thread_id") == local_thread, "父子协调者真实聊天绑定不一致")
        require(proof.get("batch_id") == source_config["batch_id"] and proof.get("message_id") in source_events, "前置决策尚未发布或批次不符")
        source = source_events[proof["message_id"]]
        require(source["sender"] == source_config["main"] and source["kind"] in ("ASSIGN", "READY", "RESOLVED", "INTEGRATED"), "ACK、结果报告或普通文字不能作为阶段放行决策")
        if source_root != root:
            require(source["recipient"] == parent["actor_id"], "父组决策不是发给本协调聊天")
        require((proof.get("entity_id"), proof.get("revision")) == (source["entity_id"], source["revision"]), "前置实体或修订不符")
        require(source["revision"] == current_revision(source_events, source["entity_id"]) and not phase_successors(source, source_events), "前置决策已被后续修订或阶段取代")
        require(source["payload"].get("phase_transition", {}).get("state") != "waiting", "仍在等待的上层消息不是放行依据")
        require(proof.get("message_sha256") == hashlib.sha256(canonical(source)).hexdigest(), "前置决策内容哈希不符")
        observed.append({**proof, "current_revision": source["revision"]})
    return observed


def validate_phase_receipt(root, event, events, config):
    receipt = event["payload"].get("phase_receipt")
    if receipt is None:
        return None
    require(event["kind"] in ("RESULT", "CONSUMED") and isinstance(receipt, dict), "阶段完成回执须由RESULT或CONSUMED携带")
    identity = receipt.get("transition_id")
    require(identity in event["refs"] and identity in events, "阶段回执须引用本组放行消息")
    transition = events[identity]
    require(phase_key(transition) is not None and not phase_successors(transition, events), "阶段回执引用的不是当前阶段消息")
    require((event["sender"], event["recipient"], event["entity_id"], event["revision"]) == (transition["recipient"], transition["sender"], transition["entity_id"], transition["revision"]), "阶段回执的归属、实体或修订不符")
    verify_phase_prerequisites(root, transition, events, config)
    validate_verification(event["payload"].get("verification"), require_passed=True)
    artifacts = receipt.get("artifacts")
    require(isinstance(artifacts, list) and all(isinstance(item, dict) and isinstance(item.get("path"), str) for item in artifacts), "阶段回执须提供实际产物及file_sha256")
    expected = transition["payload"]["phase_transition"]["expected_artifacts"]
    require(len(artifacts) == len(expected) and {item["path"] for item in artifacts} == {item["path"] for item in expected}, "阶段回执没有完整覆盖本次要求的产物")
    checked = []
    for item in expected:
        path = Path(item["path"])
        require(path.is_file() and not path.is_symlink() and str(path.resolve()) == str(path), "阶段产物不存在或路径已改变：" + str(path))
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        declared = next(value for value in artifacts if value["path"] == str(path))
        require(declared.get("file_sha256") == actual, "阶段产物文件字节哈希不符：" + str(path))
        if item.get("required_keys"):
            data = read_json(path)
            require(isinstance(data, dict) and all(key in data for key in item["required_keys"]), "阶段JSON产物缺少约定字段：" + str(path))
        checked.append({"path": str(path), "file_sha256": actual})
    return checked


def phase_statuses(root, events, config, actor):
    statuses = []
    for event in events.values():
        # 只有显式后继能承接阶段；新修订没再提它，不等于旧待办已取消。
        if phase_key(event) is None or phase_successors(event, events):
            continue
        if actor not in (config["main"], event["recipient"]):
            continue
        phase = event["payload"]["phase_transition"]
        item = {"message_id": event["id"], "entity_id": event["entity_id"], "revision": event["revision"], "phase_id": phase["id"], "recipient": event["recipient"], "state": phase["state"], "expected_artifacts": phase["expected_artifacts"], "stale": event["revision"] < current_revision(events, event["entity_id"]), "completed": False}
        if phase["state"] == "cancelled":
            # 处理已结束，但取消绝不冒充产物核验通过。
            item.update(completed=True, outcome="cancelled", reason=phase["reason"])
            statuses.append(item)
            continue
        try:
            item["prerequisites"] = verify_phase_prerequisites(root, event, events, config)
            receipts = [value for value in events.values() if value["payload"].get("phase_receipt", {}).get("transition_id") == event["id"]]
            errors = []
            for receipt in sorted(receipts, key=lambda value: value["id"]):
                try:
                    item.update(artifacts=validate_phase_receipt(root, receipt, events, config), receipt_id=receipt["id"], completed=True, outcome="passed")
                    break
                except (ValueError, OSError, KeyError, TypeError) as error:
                    errors.append(str(error))
            if not item["completed"]:
                item["reason"] = errors[-1] if errors else "已放行，尚缺接收方的实际产物回执；ACK不代表阶段完成"
        except (ValueError, OSError, KeyError, TypeError) as error:
            item["reason"] = str(error)
        if not item["completed"]:
            item["next_step"] = "核对承接或取消依据并发布新阶段消息" if item["stale"] or phase["state"] == "waiting" or "prerequisites" not in item else "由接收方核对实际产物并补阶段完成回执；不要重做已完成业务动作"
        statuses.append(item)
    return sorted(statuses, key=lambda value: value["message_id"])


def emit(root, sender, event):
    with locked(root):
        config = validate_config(read_json(root / "batch.json"))
        events = load_events(root, config)
        return _emit_locked(root, sender, event, config, events)


def _emit_locked(root, sender, event, config, events):
    """调用方已持有本批锁；消息封装入口与底层emit共用同一发布门槛。"""
    validate_envelope(event, config)
    require(sender == event["sender"], "发送方声明与消息不符")
    existing = events.get(event["id"])
    if existing:
        # 旧消息重发仍然幂等；不能因已发生新修订而再次执行旧动作。
        require(existing == event, "同消息 ID 的内容已变化，拒绝覆盖")
        return {"id": event["id"], "duplicate": True, "stale": event["revision"] < current_revision(events, event["entity_id"])}
    validate_references(event, events)
    # 新交付提前校验；读历史及同ID重放仍兼容旧格式，修正须另发新ID。
    if event["kind"] in ("RESULT", "CONSUMED"):
        validate_verification(event["payload"].get("verification"))
    validate_phase_definition(event, events, config)
    if event["payload"].get("phase_transition", {}).get("state") == "released":
        verify_phase_prerequisites(root, event, events, config)
    validate_phase_receipt(root, event, events, config)
    recovery_resolution(event, {**events, event["id"]: event}, config, check_scope=True)
    if event["kind"] not in ("ACK", "ACCEPTED"):
        revision = current_revision(events, event["entity_id"])
        if sender == config["main"]:
            require(event["revision"] >= revision, "不能新写旧修订动作；先核对主任务决策")
            if event["kind"] == "RESOLVED":
                require(event["revision"] == revision, "关闭依赖不能自行升级需求修订")
        else:
            require(event["revision"] == revision, "执行方修订须等于主任务当前修订，不能自行升级或使用旧版")
    publish_event(root, event)
    return {"id": event["id"], "duplicate": False, "stale": False}


def acknowledge(root, actor, identity):
    """确认类消息无需再确认；在同一锁内查重并保存接收回执。"""
    with locked(root):
        config = validate_config(read_json(root / "batch.json"))
        events = load_events(root, config)
        require(identity in events and events[identity]["recipient"] == actor, "原消息不存在或不属于本接收方")
        original = events[identity]
        if original["kind"] in ("ACK", "ACCEPTED"):
            return {"created": False, "reason": "确认消息不再确认"}
        existing = [event["id"] for event in events.values() if event["kind"] in ("ACK", "ACCEPTED") and event["sender"] == actor and event["refs"] == [identity]]
        if existing:
            return {"created": False, "reason": "已有接收或理解回执", "receipt_ids": sorted(existing)}
        receipt = {**original, "id": "ACK-" + hashlib.sha256(canonical([actor, identity])).hexdigest(),
                   "sender": actor, "recipient": original["sender"], "kind": "ACK",
                   "created_at": datetime.now(timezone.utc).isoformat(), "refs": [identity],
                   "payload": {"description": "已收到；不代表已理解分派或完成执行"}}
        validate_envelope(receipt, config)
        validate_references(receipt, events)
        publish_event(root, receipt)
        return {"created": True, "receipt_ids": [receipt["id"]]}


def message_metadata(root, event):
    path = root / "events" / event["sender"] / (event["id"] + ".json")
    return {"message_id": event["id"], "entity_id": event["entity_id"], "revision": event["revision"], "event_path": str(path),
            "message_sha256": hashlib.sha256(canonical(event)).hexdigest(),
            "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def verify_message(root, identity, expected_message=None, expected_file=None):
    with locked(root):
        config = validate_config(read_json(root / "batch.json"))
        events = load_events(root, config)
        require(identity in events, "消息不存在")
        event = events[identity]
        result = message_metadata(root, event)
        require(expected_message is None or expected_message == result["message_sha256"], "消息内容哈希不符")
        require(expected_file is None or expected_file == result["file_sha256"], "消息文件字节哈希不符")
        successors = phase_successors(event, events)
        return {**result, "valid": True, "revision": event["revision"], "current_revision": current_revision(events, event["entity_id"]), "superseded_by_phase": [item["id"] for item in successors]}


def load_notifications(root, config, events):
    records = []
    folder = root / "notifications"
    require(not folder.is_symlink(), "通知目录不能是软链接")
    for path in sorted(folder.glob("*/*.intent.json")):
        require(not path.parent.is_symlink(), "通知记录目录不能是软链接")
        intent = read_sealed(path)
        key = intent["identity"]
        identity = hashlib.sha256(canonical(key)).hexdigest()
        require(path.parent.name == identity and path.name == str(intent["attempt"]) + ".intent.json", "通知意图身份不符")
        require(key["batch_id"] == config["batch_id"] and key["sender"] in config["actors"] and key["recipient"] in config["actors"], "通知批次或角色不符")
        require(all(item["message_id"] in events and events[item["message_id"]]["sender"] == key["sender"] and events[item["message_id"]]["recipient"] == key["recipient"] and hashlib.sha256(canonical(events[item["message_id"]])).hexdigest() == item["message_sha256"] for item in key["messages"]), "通知来源消息已缺失或改变")
        done = path.with_name(str(intent["attempt"]) + ".done.json")
        result = read_sealed(done) if done.exists() else None
        if result is not None:
            validate_notification_result(result)
        verified = path.with_name(str(intent["attempt"]) + ".verified.json")
        observation = read_sealed(verified) if verified.exists() else None
        if observation is not None:
            validate_notification_result(observation)
            require(observation["status"] != "unknown", "恢复核验不能仍为未知")
        claim_path = path.with_name(str(intent["attempt"]) + ".dispatch.json")
        claim = read_sealed(claim_path) if claim_path.exists() else None
        if claim is not None:
            require(set(claim) == {"notification_id", "attempt", "claimed_at"} and claim["notification_id"] == identity and claim["attempt"] == intent["attempt"], "通知领取记录身份不符")
        records.append({"notification_id": identity, "intent": intent, "result": result, "observation": observation, **({"dispatch_claim": claim} if claim is not None else {})})
    for suffix in ("done", "verified", "dispatch"):
        for path in folder.glob("*/*." + suffix + ".json"):
            require(path.with_name(path.name.replace("." + suffix + ".json", ".intent.json")).is_file(), "通知回执缺少意图")
    return records


def validate_notification_result(result):
    require(isinstance(result, dict) and set(result) == {"status", "evidence"}, "通知回执字段不符")
    require(result["status"] in ("sent", "not_sent", "unknown"), "通知回执状态无效")
    require(isinstance(result["evidence"], list) and result["evidence"] and all(isinstance(item, str) and item.strip() for item in result["evidence"]), "通知回执须保存实际调用或核验依据")


def notification_status(record, events):
    key = record["intent"]["identity"]
    messages = [events[item["message_id"]] for item in key["messages"]]
    confirmed = {event["refs"][0] for event in events.values() if event["kind"] in ("ACK", "ACCEPTED")}
    actionable = [event for event in messages if event["kind"] not in ("ACK", "ACCEPTED")]
    if actionable and all(event["id"] in confirmed for event in actionable):
        return "acknowledged"
    known = record["observation"] or record["result"]
    return known["status"] if known else "unknown"


def prepare_notification(root, sender, identities, verification=None):
    """只有已发布读回的当前消息能取得通知计划；意图先落盘，未知结果不放行重试。"""
    with locked(root):
        config = validate_config(read_json(root / "batch.json"))
        events = load_events(root, config)
        require(identities and len(set(identities)) == len(identities), "通知消息须非空且不重复")
        require(all(identity in events and events[identity]["sender"] == sender for identity in identities), "消息未发布读回或不属于本发送方")
        messages = [events[identity] for identity in sorted(identities)]
        require(len({event["recipient"] for event in messages}) == 1, "合并通知只能发给同一接收者")
        require(all(event["revision"] == current_revision(events, event["entity_id"]) for event in messages), "禁止通知旧修订；先核对最新决策")
        for event in messages:
            require(not phase_successors(event, events), "禁止通知已被后续阶段消息取代的旧指令")
            if event["kind"] in ("RESULT", "CONSUMED"):
                validate_verification(event["payload"].get("verification"))
            if event["payload"].get("phase_transition", {}).get("state") == "released":
                verify_phase_prerequisites(root, event, events, config)
            validate_phase_receipt(root, event, events, config)
        actionable = [event for event in messages if event["kind"] not in ("ACK", "ACCEPTED")]
        confirmed = {event["refs"][0] for event in events.values() if event["kind"] in ("ACK", "ACCEPTED")}
        if not actionable or all(event["id"] in confirmed for event in actionable):
            return {"can_notify": False, "reason": "仅确认消息或实际接收方已确认，无需另行唤醒"}
        recipient = messages[0]["recipient"]
        target = config["actors"][recipient]
        require(isinstance(target.get("thread_id"), str) and target["thread_id"].strip(), "接收方未绑定真实聊天ID")
        metadata = [message_metadata(root, event) for event in messages]
        key = {"batch_id": config["batch_id"], "sender": sender, "recipient": recipient,
               "thread_id": target["thread_id"], "host_id": target.get("host_id"),
               "messages": [{name: item[name] for name in ("message_id", "message_sha256")} for item in metadata]}
        identity = hashlib.sha256(canonical(key)).hexdigest()
        records = load_notifications(root, config, events)
        # 不同消息组合也可能重复唤醒同一消息，按重叠的实际消息核对在途通知。
        previous = [record for record in records if record["intent"]["identity"]["sender"] == sender and set(identities) & {item["message_id"] for item in record["intent"]["identity"]["messages"]} and notification_status(record, events) != "acknowledged"]
        now = datetime.now(timezone.utc)
        policy = config.get("notification_policy", {})
        if previous:
            if verification is None:
                return {"can_notify": False, "reason": "已有通知意图或已发送待确认；先核对实际结果", "notification_ids": sorted({record["notification_id"] for record in previous})}
            require(isinstance(verification, dict), "重试核验须为对象")
            latest = max(previous, key=lambda record: record["intent"]["created_at"])
            require(verification.get("notification_id") == latest["notification_id"] and verification.get("attempt") == latest["intent"]["attempt"], "重试核验不属于最近一次通知")
            require(all(record["intent"]["identity"] == key for record in previous), "消息组合或聊天绑定已变化，先逐项核对原通知，不能借新组合重试")
            validate_notification_result({"status": verification.get("status"), "evidence": verification.get("evidence")})
            require(verification["status"] in ("sent", "not_sent"), "结果仍未知，禁止直接重试")
            checked = datetime.fromisoformat(verification.get("checked_at", "").replace("Z", "+00:00"))
            created = datetime.fromisoformat(latest["intent"]["created_at"])
            require(checked.utcoffset() is not None and created <= checked <= now, "重试核验时间须在上次意图之后且不晚于当前时间")
            require(len(previous) <= policy.get("max_notification_retries", 2), "通知重试次数已耗尽")
            require((now - created).total_seconds() >= policy.get("check_after_seconds", 120), "尚未到约定核对窗口")
        else:
            require(verification is None, "没有对应旧通知，不接受重试核验")
        attempts = [record["intent"]["attempt"] for record in records if record["notification_id"] == identity]
        attempt = max(attempts, default=0) + 1
        args = {"threadId": target["thread_id"], "prompt": "批次 " + config["batch_id"] + " 的持久消息已发布并读回：\n" + "\n".join(item["event_path"] + " / " + item["entity_id"] + " / 修订 " + str(item["revision"]) for item in metadata) + "\n请先核对原始授权、批次、有效修订与消息，再按本层职责处理；回执不等于完成。"}
        if target.get("host_id"):
            args["hostId"] = target["host_id"]
        intent = {"identity": key, "attempt": attempt, "created_at": now.isoformat(), "tool_args": args, "retry_verification": verification}
        path = root / "notifications" / identity / (str(attempt) + ".intent.json")
        publish(path, sealed(intent))
        require(read_sealed(path) == intent, "通知意图读回不符")
        return {"can_notify": True, "root": str(root), "sender": sender, "notification_id": identity, "attempt": attempt, "tool_args": args, "messages": metadata}


def claim_notification(root, sender, identity, attempt):
    """发送前仅领取一次；领取后中断仍属未知，不能靠重放异步接续再次发送。"""
    with locked(root):
        config = validate_config(read_json(root / "batch.json"))
        events = load_events(root, config)
        records = load_notifications(root, config, events)
        matches = [row for row in records if row["notification_id"] == identity and row["intent"]["attempt"] == attempt]
        require(len(matches) == 1, "通知意图不存在")
        record = matches[0]
        key = record["intent"]["identity"]
        require(key["sender"] == sender, "通知意图不属于本发送方")
        if notification_status(record, events) == "acknowledged":
            return {"can_send": False, "reason": "实际接收方已确认，无需再次发送"}
        if record.get("dispatch_claim") is not None or record["result"] is not None or record["observation"] is not None:
            return {"can_send": False, "reason": "本次通知已经领取或有实际结果；先恢复对账，不重复发送"}
        # 只有最新尝试能领取；旧会话迟到不能越过已经核验后启动的新尝试。
        require(attempt == max(row["intent"]["attempt"] for row in records if row["notification_id"] == identity), "旧通知尝试不能领取发送")
        target = config["actors"][key["recipient"]]
        require((target.get("thread_id"), target.get("host_id")) == (key["thread_id"], key["host_id"]), "通知聊天绑定已变化")
        for item in key["messages"]:
            event = events[item["message_id"]]
            require(event["revision"] == current_revision(events, event["entity_id"]), "禁止发送旧修订通知")
            require(not phase_successors(event, events), "禁止发送已被取代的旧阶段通知")
            if event["kind"] in ("RESULT", "CONSUMED"):
                validate_verification(event["payload"].get("verification"))
            if event["payload"].get("phase_transition", {}).get("state") == "released":
                verify_phase_prerequisites(root, event, events, config)
            validate_phase_receipt(root, event, events, config)
        claim = {"notification_id": identity, "attempt": attempt, "claimed_at": datetime.now(timezone.utc).isoformat()}
        path = root / "notifications" / identity / (str(attempt) + ".dispatch.json")
        publish(path, sealed(claim))
        require(read_sealed(path) == claim, "通知领取记录读回不符")
        return {"can_send": True, "root": str(root), "sender": sender, "notification_id": identity,
                "attempt": attempt, "tool_args": record["intent"]["tool_args"]}


def finish_notification(root, sender, identity, attempt, result, reconcile=False):
    with locked(root):
        config = validate_config(read_json(root / "batch.json"))
        events = load_events(root, config)
        records = load_notifications(root, config, events)
        matches = [record for record in records if record["notification_id"] == identity and record["intent"]["attempt"] == attempt]
        require(len(matches) == 1 and matches[0]["intent"]["identity"]["sender"] == sender, "通知意图不存在或不属于本发送方")
        validate_notification_result(result)
        record = matches[0]
        if reconcile:
            require(result["status"] != "unknown", "恢复核验须已查明实际结果")
        previous = record["observation"] if reconcile else record["result"]
        if previous is not None:
            require(previous == result, "通知回执不可改写；新的事实需另行核对")
            return {"duplicate": True, "status": result["status"]}
        suffix = ".verified.json" if reconcile else ".done.json"
        publish(root / "notifications" / identity / (str(attempt) + suffix), sealed(result))
        return {"duplicate": False, "status": result["status"], "task_completion_verified": False}


def inbox(root, recipient):
    with locked(root):
        config = validate_config(read_json(root / "batch.json"))
        require(recipient in config["actors"], "接收方未登记")
        events = load_events(root, config)
        acknowledged = {event["refs"][0] for event in events.values() if event["kind"] in ("ACK", "ACCEPTED")}
        rows = []
        for event in sorted(events.values(), key=lambda item: (item["created_at"], item["id"])):
            if event["recipient"] != recipient:
                continue
            stale = event["revision"] < current_revision(events, event["entity_id"])
            status = "旧修订" if stale else "旧阶段" if phase_successors(event, events) else "回执" if event["kind"] in ("ACK", "ACCEPTED") else "已确认收到" if event["id"] in acknowledged else "待确认"
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


def consumer_requests(original, consumer, config):
    """分派按接收者/显式消费者归属；页面 REQUEST 保留既有公共需求语义。"""
    if original and original[0]["kind"] == "REQUEST":
        return [item for item in original if item["sender"] == consumer] or original
    direct = [item for item in original if item["recipient"] == consumer or
              consumer in item["payload"].get("consumers", [])]
    # 旧共享分派可能尚未列消费者，后来才用 READY 下发；保留该公共来源。
    # 不把其他 worker 的分派当作兜底，否则同实体的多个模块会互相背负请求。
    return direct or [item for item in original if config["actors"][item["recipient"]]["role"] == "shared"
                      and not item["payload"].get("consumers")]


def recovery_resolution(event, events, config, check_scope=False):
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
    if check_scope:
        history = [item for item in events.values() if item["entity_id"] == event["entity_id"]]
        for kind in {events[item]["kind"] for item in requests}:
            allowed = {item["id"] for item in consumer_requests([item for item in history if item["kind"] == kind], consumer, config)}
            require(all(item in allowed for item in requests if events[item]["kind"] == kind), "关闭请求不属于对应消费者；按恢复报告逐消费者的request_ids核对")
    # 只收紧新发布；旧版曾记录全组 request_ids，读取及同 ID 重放仍保留原事实。
    require(isinstance(claim.get("reason"), str) and claim["reason"].strip(), "恢复结论须说明依据")
    if claim["resolution"] == "completed":
        require(event["kind"] in ("RESOLVED", "INTEGRATED"), "完成依赖使用RESOLVED或已核验的INTEGRATED")
        evidence = claim.get("evidence_refs")
        require(isinstance(evidence, list) and evidence and all(item in event["refs"] for item in evidence), "完成结论须关联实际消费或验证回执")
        for identity in evidence:
            receipt = events[identity]
            require(receipt["kind"] in ("RESULT", "CONSUMED") and receipt["sender"] == consumer and receipt["entity_id"] == event["entity_id"] and receipt["revision"] == event["revision"], "完成结论关联的消费回执不符")
            validate_verification(receipt["payload"].get("verification"), require_passed=True)
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
        notifications = load_notifications(root, config, events)
        from execution_guards import integration_status
        freeze = integration_status(root, config, events)
        pending_integration = ([{"owner": config["main"], "reasons": freeze["reasons"],
                                "next_step": "先核对冻结输入和状态，按执行防护入口恢复；不重跑Git"}]
                               if freeze["registered"] and not freeze["can_integrate"] else [])
        phases = phase_statuses(root, events, config, actor)
        pending_phases = [item for item in phases if not item["completed"]]
        main = config["main"]
        acknowledgements = {event["refs"][0] for event in events.values() if event["kind"] in ("ACK", "ACCEPTED")}
        resolutions = {identity: recovery_resolution(event, events, config) for identity, event in events.items()}
        incoming, outgoing, superseded = [], [], []
        for identity, event in sorted(events.items()):
            if event["kind"] in ("ACK", "ACCEPTED") or identity in acknowledgements:
                continue
            summary = {key: event[key] for key in ("id", "entity_id", "revision", "kind", "sender", "recipient")}
            if event["revision"] < current_revision(events, event["entity_id"]) or phase_successors(event, events):
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
                relevant = consumer_requests(original, consumer, config)
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
                progress.append({"consumer": consumer, "status": status, "closed": closed,
                                 "request_ids": sorted(event["id"] for event in relevant),
                                 "unresolved_request_ids": unresolved, "next_step": next_step})
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
        latest_notifications = {}
        for record in notifications:
            key = record["notification_id"]
            if key not in latest_notifications or record["intent"]["attempt"] > latest_notifications[key]["intent"]["attempt"]:
                latest_notifications[key] = record
        pending_notifications = []
        for record in latest_notifications.values():
            key = record["intent"]["identity"]
            if (actor == main or actor == key["sender"]) and notification_status(record, events) == "unknown":
                pending_notifications.append({"notification_id": record["notification_id"], "attempt": record["intent"]["attempt"], "sender": key["sender"], "recipient": key["recipient"], "message_ids": [item["message_id"] for item in key["messages"]], "status": "通知调用结果待核对", "next_step": "先核对真实聊天及回执，再reconcile-notification；禁止直接重发或宣布送达"})
        next_steps = [{"owner": item["sender"], "entity_id": "notification", "action": item["next_step"], "notification_id": item["notification_id"]} for item in pending_notifications]
        next_steps.extend({"owner": item["owner"], "entity_id": "integration", "action": item["next_step"] + "：" + ";".join(item["reasons"])} for item in pending_integration)
        next_steps.extend({"owner": main if item["stale"] or item["state"] == "waiting" or "prerequisites" not in item else item["recipient"], "entity_id": item["entity_id"], "action": item["next_step"], "message_id": item["message_id"]} for item in pending_phases)
        next_steps.extend({"owner": item["plan"]["actor"], "entity_id": item["plan"]["entity_id"], "action": item["next_step"], "action_id": item["action_id"]} for item in pending_actions)
        next_steps.extend({"owner": main, "entity_id": item["entity_id"], "action": "记录缺少原始请求/分派，核对历史并补录，不能据此判定没有待办", "message_id": item["id"]} for item in unlinked)
        next_steps.extend({"owner": actor, "entity_id": item["entity_id"], "action": "核对并确认收到消息", "message_id": item["id"]} for item in incoming)
        next_steps.extend({"owner": item["recipient"], "entity_id": item["entity_id"], "action": "核对送达及通知账本，按受控调用器和重试核验处理，不重做业务动作", "message_id": item["id"]} for item in outgoing)
        for request in requests:
            if request["open"] and request["blocked_message_ids"]:
                next_steps.append({"owner": main, "entity_id": request["entity_id"], "action": "核对阻塞记录与后续处理结果，再决定是否继续", "message_ids": request["blocked_message_ids"]})
            next_steps.extend({"owner": sorted(request["owners"]) if consumer["status"] == "已分派，待交付" else consumer["consumer"], "entity_id": request["entity_id"], "action": consumer["next_step"]} for consumer in request["consumers"] if not consumer["closed"] and (actor == main or actor == consumer["consumer"] or actor in request["owners"]))
        return {"batch_id": config["batch_id"], "actor": actor, "snapshot_sha256": hashlib.sha256(canonical({"config": config, "events": events, "actions": actions, "notifications": notifications, "phases": phases, **({"integration_guard": freeze} if freeze["registered"] else {})})).hexdigest(), "open_requests": [item for item in requests if item["open"]], "closed_requests": [item for item in requests if not item["open"]], "unlinked_events": unlinked, "pending_messages": incoming, "awaiting_confirmation": outgoing, "superseded_messages": superseded, "actions_pending_verification": pending_actions, "completed_actions": completed_actions, "notifications_pending_verification": pending_notifications, "integration_pending_verification": pending_integration, "phase_transitions_pending": pending_phases, "completed_phases": [item for item in phases if item["completed"]], "next_steps": next_steps, "limitations": ["仅扫描本批已落盘资料；未落盘用户纠正须从原聊天补录", "不会发送消息、运行Git或自动执行下一步；完成记录不证明业务或UI验收通过", "跨批依赖仍须按长期任务目录核对；旧格式无明确关闭依据时保留未完成", "阶段核对仅覆盖已登记phase_transition及产物字节/约定字段，不理解自然语言或代验业务"]}


def task_map(path):
    """只读导出已核实登记，供汇总复用；不查询聊天、不读 Git，也不判断任务完成。"""
    registry = read_json(path)
    raw = path.read_bytes()
    require(json.loads(raw) == registry, "导出期间长期目录已变化，请重读")
    require(isinstance(registry, dict) and registry.get("schema_version") == 1, "长期任务目录格式无效")
    tasks, main = registry.get("tasks"), registry.get("main_task_id")
    require(isinstance(tasks, dict) and tasks and main in tasks, "长期目录须明确本组main_task_id及tasks")
    rows, identities = {}, set()
    for actor, info in sorted(tasks.items()):
        identifier(actor)
        require(isinstance(info, dict) and info.get("role") in ("main", "worker", "shared"), "登记角色无效：" + actor)
        thread, title = info.get("thread_id"), info.get("title")
        require(isinstance(thread, str) and thread.strip() and isinstance(title, str) and title.strip(),
                "尚未登记真实聊天ID或标题：" + actor + "；先核对创建回执，不从创建计划生成汇总")
        require(thread not in identities, "本组多个角色绑定了同一聊天，请核对登记")
        identities.add(thread)
        workspaces = info.get("workspaces", [])
        require(isinstance(workspaces, list) and all(isinstance(item, dict) for item in workspaces), "workspaces须为登记对象数组")
        rows[actor] = {"actor": actor, "role": info["role"], "thread_id": thread, "host_id": info.get("host_id"),
                       "title": title, "task_directory": info.get("task_directory"), "workspaces": workspaces,
                       "recorded_status": info.get("status", info.get("state"))}
    require(rows[main]["role"] == "main" and sum(item["role"] == "main" for item in rows.values()) == 1, "本组协调角色登记不一致")
    require(path.read_bytes() == raw, "导出期间长期目录已变化，请重读")
    return {"registry": str(path), "registry_file_sha256": hashlib.sha256(raw).hexdigest(),
            "main_task_id": main, "tasks": rows, "live_state_verified": False}


def recover_registry(path, actor):
    require(path.is_absolute(), "长期任务目录须为绝对路径")
    registry = read_json(path)
    require(isinstance(registry, dict) and registry.get("schema_version") == 1 and actor in registry.get("tasks", {}), "长期任务目录或执行者无效")
    batches = registry.get("batches")
    require(isinstance(batches, list) and batches, "长期任务目录尚未登记批次，不能据此判定无待办")
    reports, unavailable, identities, roots = [], [], set(), set()
    aggregate = {key: [] for key in ("open_requests", "closed_requests", "unlinked_events", "pending_messages", "awaiting_confirmation", "superseded_messages", "actions_pending_verification", "completed_actions", "notifications_pending_verification", "integration_pending_verification", "phase_transitions_pending", "completed_phases", "next_steps")}
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
    lines += ["", "## 通知调用结果待核对", ""]
    lines += [f"- {item['sender']} → {item['recipient']} / {item['notification_id']} / 尝试 {item['attempt']}：{item['next_step']}" for item in report["notifications_pending_verification"]] or ["无。"]
    lines += ["", "## 集成冻结待核对", ""]
    lines += ["- " + ";".join(item["reasons"]) + "；" + item["next_step"] for item in report["integration_pending_verification"]] or ["无。"]
    lines += ["", "## 阶段放行与产物待核对", ""]
    lines += [f"- {item['recipient']} / {item['phase_id']} / {item['message_id']}：{item['reason']}；{item['next_step']}" for item in report["phase_transitions_pending"]] or ["无。"]
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
    require(root.resolve() == root and not root.is_symlink(), "初始化目录须为规范绝对路径，不能是软链接")
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise FileExistsError("初始化目录非空或已有批次；保留原资料，先恢复或另选目录：" + str(root))
    root.mkdir(parents=True, exist_ok=True)
    with locked(root):
        # 两个初始化者可能同时看到空目录；加锁后再次核对，不能覆盖先完成者或未知资料。
        if any(path.name != ".message.lock" for path in root.iterdir()):
            raise FileExistsError("初始化目录已有资料，未覆盖：" + str(root))
        publish(root / "batch.json", config)
        for actor in config["actors"]:
            (root / "events" / actor).mkdir(parents=True)
        (root / "deliveries").mkdir()


def main():
    parser = argparse.ArgumentParser(description="独立任务持久消息：落盘、去重、确认及恢复扫描")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "emit", "inbox", "check", "recover", "task-map", "begin-action", "finish-action", "ack", "verify-message", "prepare-notification", "claim-notification", "finish-notification", "reconcile-notification"):
        command = sub.add_parser(name)
        if name == "task-map":
            command.add_argument("--registry", type=absolute_path, required=True)
        elif name == "recover":
            scope = command.add_mutually_exclusive_group(required=True)
            scope.add_argument("--root", type=absolute_path)
            scope.add_argument("--registry", type=absolute_path)
        else:
            command.add_argument("--root", type=absolute_path, required=True)
        if name == "init":
            command.add_argument("--config", type=absolute_path, required=True)
        elif name == "emit":
            command.add_argument("--sender", required=True)
            command.add_argument("--event", type=absolute_path, required=True)
        elif name == "inbox":
            recipient = command.add_mutually_exclusive_group(required=True)
            recipient.add_argument("--recipient", help="收件执行者逻辑ID")
            recipient.add_argument("--actor", dest="recipient", help="--recipient的兼容别名；二者只传一个")
        elif name == "ack":
            command.add_argument("--actor", required=True)
            command.add_argument("--message-id", required=True)
        elif name == "verify-message":
            command.add_argument("--message-id", required=True)
            command.add_argument("--expected-message-sha256")
            command.add_argument("--expected-file-sha256")
        elif name == "prepare-notification":
            command.add_argument("--sender", required=True)
            command.add_argument("--message-id", nargs="+", required=True)
            command.add_argument("--retry-verification", type=absolute_path)
        elif name == "claim-notification":
            command.add_argument("--sender", required=True)
            command.add_argument("--notification-id", required=True)
            command.add_argument("--attempt", type=int, required=True)
        elif name in ("finish-notification", "reconcile-notification"):
            command.add_argument("--sender", required=True)
            command.add_argument("--notification-id", required=True)
            command.add_argument("--attempt", type=int, required=True)
            command.add_argument("--status", choices=("sent", "not_sent", "unknown"), required=True)
            command.add_argument("--evidence", action="append", required=True)
        elif name in ("recover", "begin-action", "finish-action"):
            command.add_argument("--actor", required=True)
            if name == "recover":
                command.add_argument("--format", choices=("json", "markdown"), default="json")
            elif name == "begin-action":
                command.add_argument("--plan", type=absolute_path, required=True)
            elif name == "finish-action":
                command.add_argument("--action-id", required=True)
                command.add_argument("--result", type=absolute_path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "init":
            initialize(args.root, read_json(args.config))
            result = {"created": str(args.root), "tasks_started": 0}
        elif args.command == "emit":
            result = emit(args.root, args.sender, read_json(args.event))
        elif args.command == "inbox":
            result = inbox(args.root, args.recipient)
        elif args.command == "ack":
            result = acknowledge(args.root, args.actor, args.message_id)
        elif args.command == "verify-message":
            result = verify_message(args.root, args.message_id, args.expected_message_sha256, args.expected_file_sha256)
        elif args.command == "prepare-notification":
            result = prepare_notification(args.root, args.sender, args.message_id, read_json(args.retry_verification) if args.retry_verification else None)
        elif args.command == "claim-notification":
            result = claim_notification(args.root, args.sender, args.notification_id, args.attempt)
        elif args.command in ("finish-notification", "reconcile-notification"):
            result = finish_notification(args.root, args.sender, args.notification_id, args.attempt, {"status": args.status, "evidence": args.evidence}, args.command == "reconcile-notification")
        elif args.command == "task-map":
            result = task_map(args.registry)
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
                notifications = load_notifications(args.root, config, events)
                for event in events.values():
                    recovery_resolution(event, events, config)
                from execution_guards import integration_status
                freeze = integration_status(args.root, config, events)
                result = {"integration_guard": freeze, "valid": True, "messages": len(events), "actions": len(actions), "notification_attempts": len(notifications), "task_completion_verified": False}
        print(recovery_markdown(result) if args.command == "recover" and args.format == "markdown" else json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print("协作消息失败：" + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
