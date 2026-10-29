"""通知门槛、真实进程恢复和受控工具编排；只使用隔离夹具及模拟聊天工具。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("coordination", Path(__file__).with_name("coordination.py"))
co = importlib.util.module_from_spec(spec)
spec.loader.exec_module(co)


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=os.environ["COORDINATION_TEST_ROOT"])
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()
        self.root = self.directory / "带空格和'引号的批次"
        self.config = {"schema_version": 1, "batch_id": "NOTICE-TEST", "main": "main",
                       "authorization": "仅隔离合成测试，不通知真实聊天",
                       "notification_policy": {"check_after_seconds": 0, "max_notification_retries": 2},
                       "actors": {"main": {"role": "main", "thread_id": "fixture-main"},
                                  "A": {"role": "worker", "thread_id": "fixture-a", "host_id": "local"},
                                  "B": {"role": "worker", "thread_id": "fixture-b"}}}
        co.initialize(self.root, self.config)
        self.event = {"batch_id": "NOTICE-TEST", "id": "ASSIGN-1", "sender": "main", "recipient": "A",
                      "kind": "ASSIGN", "entity_id": "MODULE", "revision": 1, "refs": [],
                      "created_at": "2000-01-01T00:00:00+00:00", "payload": {"description": "合成分派"}}
        co.emit(self.root, "main", self.event)

    def prepare(self, verification=None, ids=None):
        return co.prepare_notification(self.root, "main", ids or ["ASSIGN-1"], verification)

    def finish(self, plan, status="sent"):
        return co.finish_notification(self.root, "main", plan["notification_id"], plan["attempt"],
                                      {"status": status, "evidence": ["模拟聊天工具回执"]})

    def retry(self, plan, status="not_sent"):
        return {"notification_id": plan["notification_id"], "attempt": plan["attempt"], "status": status,
                "evidence": ["已核对模拟工具记录及目标聊天"], "checked_at": datetime.now(timezone.utc).isoformat()}

    def test_ack_is_atomic_idempotent_and_acceptance_does_not_request_ack(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: co.acknowledge(self.root, "A", "ASSIGN-1"), range(8)))
        self.assertEqual(sum(result["created"] for result in results), 1)
        receipt = next(self.root.glob("events/A/*.json"))
        identity = co.read_json(receipt)["message"]["id"]
        self.assertFalse(co.acknowledge(self.root, "main", identity)["created"])
        accepted = {**self.event, "id": "ACCEPTED-1", "sender": "A", "recipient": "main", "kind": "ACCEPTED", "refs": ["ASSIGN-1"]}
        co.emit(self.root, "A", accepted)
        self.assertFalse(co.acknowledge(self.root, "main", "ACCEPTED-1")["created"])
        self.assertEqual(next(row for row in co.inbox(self.root, "main") if row["message"]["id"] == "ACCEPTED-1")["status"], "回执")
        self.assertFalse(co.prepare_notification(self.root, "A", ["ACCEPTED-1"])["can_notify"])
        co.emit(self.root, "main", {**self.event, "id": "ASSIGN-ACCEPTED-ONLY"})
        co.emit(self.root, "A", {**accepted, "id": "ACCEPTED-ONLY", "refs": ["ASSIGN-ACCEPTED-ONLY"]})
        self.assertEqual(next(row for row in co.inbox(self.root, "A") if row["message"]["id"] == "ASSIGN-ACCEPTED-ONLY")["status"], "已确认收到")
        self.assertFalse(co.acknowledge(self.root, "A", "ASSIGN-ACCEPTED-ONLY")["created"])
        self.assertEqual(co.recover(self.root, "main")["pending_messages"], [])
        self.assertEqual(len(co.recover(self.root, "main")["open_requests"]), 1)

    def test_explicit_hash_types_reject_file_message_confusion(self):
        meta = co.verify_message(self.root, "ASSIGN-1")
        self.assertNotEqual(meta["file_sha256"], meta["message_sha256"])
        self.assertTrue(co.verify_message(self.root, "ASSIGN-1", meta["message_sha256"], meta["file_sha256"])["valid"])
        with self.assertRaisesRegex(ValueError, "消息内容哈希"):
            co.verify_message(self.root, "ASSIGN-1", meta["file_sha256"])

    def test_missing_stale_unbound_and_wrong_sender_never_create_intent(self):
        with self.assertRaises(ValueError):
            self.prepare(ids=["NOT-PUBLISHED"])
        with self.assertRaises(ValueError):
            co.prepare_notification(self.root, "A", ["ASSIGN-1"])
        cfg = co.read_json(self.root / "batch.json")
        cfg["actors"]["A"].pop("thread_id")
        (self.root / "batch.json").write_text(json.dumps(cfg))
        with self.assertRaises(ValueError):
            self.prepare()
        (self.root / "batch.json").write_text(json.dumps(self.config))
        co.emit(self.root, "main", {**self.event, "id": "ASSIGN-2", "revision": 2})
        with self.assertRaisesRegex(ValueError, "旧修订"):
            self.prepare()
        self.assertFalse((self.root / "notifications").exists())

    def test_failed_intent_publish_or_readback_does_not_return_permission(self):
        with patch.object(co, "publish", side_effect=OSError("模拟发布失败")), self.assertRaises(OSError):
            self.prepare()
        original = co.read_sealed
        with patch.object(co, "read_sealed", side_effect=lambda path: {} if path.name.endswith("intent.json") else original(path)), self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse(self.prepare()["can_notify"])
        self.assertEqual(len(co.recover(self.root, "main")["notifications_pending_verification"]), 1)

    def test_only_one_concurrent_dispatch_and_restart_preserves_unknown(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            plans = list(pool.map(lambda _: self.prepare(), range(8)))
        self.assertEqual(sum(plan["can_notify"] for plan in plans), 1)
        command = [sys.executable, "-B", str(Path(__file__).with_name("coordination.py")), "recover", "--root", str(self.root), "--actor", "main"]
        recovered = json.loads(subprocess.run(command, check=True, capture_output=True, text=True).stdout)
        self.assertEqual(len(recovered["notifications_pending_verification"]), 1)
        self.assertFalse(self.prepare()["can_notify"])

    def test_sent_unknown_retries_require_evidence_and_have_a_limit(self):
        first = self.prepare()
        self.finish(first, "unknown")
        self.assertFalse(self.prepare()["can_notify"])
        with self.assertRaisesRegex(ValueError, "仍未知"):
            self.prepare(self.retry(first, "unknown"))
        second = self.prepare(self.retry(first))
        self.finish(second)
        self.assertFalse(self.prepare()["can_notify"])
        third = self.prepare(self.retry(second, "sent"))
        self.finish(third)
        with self.assertRaisesRegex(ValueError, "耗尽"):
            self.prepare(self.retry(third, "sent"))
        co.acknowledge(self.root, "A", "ASSIGN-1")
        self.assertFalse(self.prepare()["can_notify"])
        self.assertEqual(co.recover(self.root, "main")["notifications_pending_verification"], [])

    def test_reconcile_settles_unknown_without_resending_obsolete_message(self):
        plan = self.prepare()
        self.finish(plan, "unknown")
        co.emit(self.root, "main", {**self.event, "id": "ASSIGN-2", "revision": 2})
        result = {"status": "not_sent", "evidence": ["恢复时查明工具未调用，旧修订不重发"]}
        co.finish_notification(self.root, "main", plan["notification_id"], 1, result, reconcile=True)
        self.assertEqual(co.recover(self.root, "main")["notifications_pending_verification"], [])
        with self.assertRaises(ValueError):
            self.prepare()
        with self.assertRaises(ValueError):
            self.finish(plan, "sent")

    def test_retry_window_and_cross_batch_recovery_include_notification_intents(self):
        plan = self.prepare()
        cfg = co.read_json(self.root / "batch.json")
        cfg["notification_policy"]["check_after_seconds"] = 3600
        (self.root / "batch.json").write_text(json.dumps(cfg))
        with self.assertRaisesRegex(ValueError, "核对窗口"):
            self.prepare(self.retry(plan))
        registry = self.directory / "registry.json"
        registry.write_text(json.dumps({"schema_version": 1, "tasks": self.config["actors"],
                                        "batches": [{"batch_id": "NOTICE-TEST", "coordination_root": str(self.root)}]}))
        report = co.recover_registry(registry, "main")
        self.assertTrue(report["scan_complete"])
        self.assertEqual(report["notifications_pending_verification"][0]["batch_id"], "NOTICE-TEST")
        self.assertIn("通知调用结果待核对", co.recovery_markdown(report))

    def test_rebundle_does_not_bypass_inflight_intent_and_tampering_fails(self):
        plan = self.prepare()
        co.emit(self.root, "main", {**self.event, "id": "EXTRA"})
        self.assertFalse(self.prepare(ids=["ASSIGN-1", "EXTRA"])["can_notify"])
        with self.assertRaisesRegex(ValueError, "组合或聊天绑定"):
            self.prepare(self.retry(plan), ["ASSIGN-1", "EXTRA"])
        path = next(self.root.glob("notifications/*/*.intent.json"))
        record = co.read_json(path)
        record["data"]["tool_args"]["threadId"] = "wrong-target"
        path.write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            co.recover(self.root, "main")

    @unittest.skipUnless(shutil.which("node"), "本地工具编排回归需要Node；Python信箱不依赖Node")
    def test_actual_dispatch_adapter_stops_failures_and_records_unknown_without_retry(self):
        runner = r'''
const {dispatchNotification} = require(process.argv[1]);
const {spawnSync} = require('child_process');
const options = JSON.parse(process.argv[2]);
const mode = process.argv[3];
let sends = 0;
const io = {
  exec: async args => {
    if (mode === 'prepare-failure') return {exit_code:2,output:'publication failed'};
    if (mode === 'bad-json') return {exit_code:0,output:'not json'};
    if (mode === 'record-failure' && args.cmd.includes('finish-notification')) return {exit_code:2,output:'record failed'};
    const p = spawnSync('/bin/sh',['-c',args.cmd],{encoding:'utf8'});
    return {exit_code:p.status,output:p.stdout,stderr:p.stderr};
  },
  send: async args => {
    sends++;
    if (args.threadId !== 'fixture-a') throw new Error('wrong target');
    if (mode === 'timeout') throw new Error('simulated timeout after dispatch');
    if (mode === 'wrong-receipt') return {threadId:'another-fixture'};
    if (mode === 'tool-error') return {isError:true,threadId:args.threadId};
    if (mode === 'unstructured') return {content:[{type:'text',text:'unknown'}]};
    return {content:[{type:'text',text:JSON.stringify({threadId:args.threadId})}]};
  }
};
(async()=>{const result=await dispatchNotification(io,options);process.stdout.write(JSON.stringify({sends,result}));})();
'''
        options = {"root": str(self.root), "sender": "main", "messageIds": ["ASSIGN-1"],
                   "scriptPath": str(Path(__file__).with_name("coordination.py")), "python": sys.executable}
        def dispatch(mode):
            command = ["node", "-e", runner, str(Path(__file__).with_name("notification_dispatch.js")), json.dumps(options), mode]
            return json.loads(subprocess.run(command, check=True, capture_output=True, text=True).stdout)
        for mode in ["prepare-failure", "bad-json"]:
            self.assertEqual(dispatch(mode)["sends"], 0)
        for mode, expected in [("success", "notified_waiting_ack"), ("timeout", "result_unknown"), ("record-failure", "result_unknown"), ("wrong-receipt", "result_unknown"), ("tool-error", "result_unknown"), ("unstructured", "result_unknown")]:
            root = self.directory / ("adapter-'" + mode)
            co.initialize(root, self.config)
            co.emit(root, "main", self.event)
            options["root"] = str(root)
            first = dispatch(mode)
            self.assertEqual(first["sends"], 1)
            self.assertEqual(first["result"]["status"], expected)
            self.assertEqual(dispatch("success")["sends"], 0)
            unknown = co.recover(root, "main")["notifications_pending_verification"]
            self.assertEqual(len(unknown), 0 if mode == "success" else 1)
        options["root"] = str(self.root)
        options["messageIds"] = ["MISSING"]
        self.assertEqual(dispatch("success")["sends"], 0)
        options["messageIds"] = ["ASSIGN-1"]
        co.emit(self.root, "main", {**self.event, "id": "ASSIGN-2", "revision": 2})
        self.assertEqual(dispatch("success")["sends"], 0)


if __name__ == "__main__":
    unittest.main()
