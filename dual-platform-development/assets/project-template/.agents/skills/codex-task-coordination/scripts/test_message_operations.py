"""常用入口的可执行契约；全部产物和批次放在显式外部测试目录。"""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import coordination as co
import message_operations as ops


class MessageOperationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ["COORDINATION_TEST_ROOT"])
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name).resolve()
        self.root = self.folder / "含空格和'引号的批次"
        co.initialize(self.root, {"schema_version": 1, "batch_id": "OPERATIONS", "main": "main",
                                 "authorization": "只验证本地隔离操作，不通知真实聊天",
                                 "actors": {"main": {"role": "main", "thread_id": "coordinator"},
                                            "A": {"role": "worker", "thread_id": "worker-a"},
                                            "B": {"role": "worker", "thread_id": "worker-b"}}})
        self.context = {"root_task_ref": "原始目标", "objective": "验证当前分派责任链", "local_scope": "A模块",
                        "acceptance_refs": ["可核验产物"], "dependencies": [], "deliverable": "报告"}
        self.understanding = {"objective": "已核对原始目标", "assignment": "只处理本模块",
                              "acceptance": ["报告和真实验证"], "dependencies": "当前无前置", "next_step": "实际执行"}
        self.verification = {"status": "passed", "evidence": ["夹具实际验证记录"]}
        self.assignment = {"id": "ASSIGN", "recipient": "A", "entity_id": "MODULE", "revision": 1,
                           "payload": {"task_context": self.context}}
        ops.operate(self.root, "main", "assign", self.assignment)

    def event(self, identity, actor):
        return co.read_json(self.root / "events" / actor / (identity + ".json"))["message"]

    def deliver(self, **extra):
        return ops.operate(self.root, "A", "deliver", {
            "id": "DELIVERY", "reply_to": "ASSIGN", "payload": {"verification": self.verification}, **extra})

    def test_end_to_end_common_operations_keep_goal_and_explicit_review(self):
        ops.operate(self.root, "A", "accept", {"id": "ACCEPT", "reply_to": "ASSIGN", "payload": self.understanding})
        ops.operate(self.root, "A", "blocked", {"id": "BLOCK", "reply_to": "ASSIGN",
                                              "payload": {"description": "实际资料缺口", "next_step": "等协调者补齐"}})
        co.acknowledge(self.root, "main", "BLOCK")
        self.deliver()
        co.acknowledge(self.root, "main", "DELIVERY")
        ops.operate(self.root, "main", "ready", {"id": "READY", "reply_to": "DELIVERY",
                                                "payload": {"description": "协调者实际审核后可消费"}})
        co.acknowledge(self.root, "A", "READY")
        ops.operate(self.root, "A", "deliver", {"id": "CONSUMED", "reply_to": "READY", "kind": "CONSUMED",
                                               "payload": {"verification": self.verification}})
        co.acknowledge(self.root, "main", "CONSUMED")
        ops.operate(self.root, "main", "resolve", {"id": "CLOSE", "reply_to": "CONSUMED",
                                                 "request_ids": ["ASSIGN", "READY"], "reason": "已实核全部约定交付",
                                                 "payload": {"description": "本消费者业务关闭"}})
        co.acknowledge(self.root, "A", "CLOSE")
        report = co.recover(self.root, "main")
        self.assertEqual(report["open_requests"], [])
        self.assertEqual(report["awaiting_confirmation"], [])
        self.assertEqual(self.event("ASSIGN", "main")["payload"]["task_context"], self.context)

    def test_accept_derives_one_reference_and_requires_own_understanding(self):
        request = {"id": "ACCEPT", "reply_to": "ASSIGN", "payload": {**self.understanding, "dependencies": []}}
        with self.assertRaises(ValueError):
            ops.operate(self.root, "A", "accept", {**request, "refs": ["OTHER"]})
        with self.assertRaises(ValueError):
            ops.operate(self.root, "A", "accept", {**request, "payload": {"objective": "不完整"}})
        with self.assertRaises(ValueError):
            ops.operate(self.root, "B", "accept", request)
        ops.operate(self.root, "A", "accept", request)
        event = self.event("ACCEPT", "A")
        self.assertEqual((event["recipient"], event["entity_id"], event["revision"], event["refs"]),
                         ("main", "MODULE", 1, ["ASSIGN"]))

    def test_concurrent_same_request_has_one_immutable_event(self):
        request = {"id": "ACCEPT", "reply_to": "ASSIGN", "payload": self.understanding}
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: ops.operate(self.root, "A", "accept", request), range(8)))
        self.assertEqual(sum(not result["duplicate"] for result in results), 1)
        before = (self.root / "events/A/ACCEPT.json").read_bytes()
        ops.operate(self.root, "A", "accept", request)
        self.assertEqual(before, (self.root / "events/A/ACCEPT.json").read_bytes())
        with self.assertRaises(ValueError):
            ops.operate(self.root, "A", "accept", {**request, "payload": {**self.understanding, "objective": "改写"}})

    def test_artifacts_are_actual_hashes_and_do_not_rewrite_reports(self):
        file = self.folder / "报告.json"
        file.write_text('{"actual":1}')
        before = file.read_bytes()
        result = self.deliver(artifact_paths=[str(file)])
        artifact = self.event("DELIVERY", "A")["payload"]["artifacts"][0]
        self.assertEqual(artifact["file_sha256"], hashlib.sha256(before).hexdigest())
        self.assertFalse(result["notification_sent"])
        self.assertEqual(file.read_bytes(), before)
        file.write_text('{"actual":2}')
        with self.assertRaises(ValueError):
            self.deliver(artifact_paths=[str(file)])

    def test_bad_delivery_and_missing_artifacts_never_publish(self):
        for extra in ({"artifact_paths": [str(self.folder / "missing")]},
                      {"payload": {"verification": {"status": "passed", "evidence": [{}]}}},
                      {"payload": {"artifacts": [], "verification": self.verification}}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.deliver(**extra)
            self.assertFalse((self.root / "events/A/DELIVERY.json").exists())

    def test_stale_source_and_spoofed_envelope_are_rejected(self):
        ops.operate(self.root, "main", "assign", {**self.assignment, "id": "ASSIGN-2", "revision": 2})
        with self.assertRaises(ValueError):
            self.deliver()
        with self.assertRaises(ValueError):
            ops.operate(self.root, "main", "assign", {**self.assignment, "id": "SPOOF", "sender": "A"})
        with self.assertRaises(ValueError):
            ops.operate(self.root, "main", "assign", {**self.assignment, "id": "NO-GOAL", "payload": {}})

    def test_phase_wait_release_and_actual_receipt_use_same_core_guards(self):
        self.deliver()
        summary = self.folder / "summary.json"
        expected = [{"path": str(summary), "required_keys": list(ops.UNDERSTANDING)}]
        ops.operate(self.root, "main", "resolve", {
            "id": "WAIT", "reply_to": "DELIVERY", "request_ids": ["ASSIGN"], "reason": "业务已实核",
            "payload": {}, "phase": {"id": "RESUME", "state": "waiting", "expected_artifacts": expected}})
        co.acknowledge(self.root, "A", "WAIT")
        self.assertEqual(len(co.recover(self.root, "main")["phase_transitions_pending"]), 1)
        with self.assertRaises(ValueError):
            ops.operate(self.root, "A", "deliver", {"id": "TOO-EARLY", "reply_to": "WAIT", "complete_phase": True,
                                                   "payload": {"verification": self.verification}})
        ops.operate(self.root, "main", "ready", {"id": "REVIEW", "reply_to": "DELIVERY", "payload": {"description": "实际阶段审核"}})
        ops.operate(self.root, "main", "ready", {"id": "RELEASE", "reply_to": "WAIT", "payload": {},
                                                "phase": {"state": "released", "prerequisites": [{"message_id": "REVIEW"}]}})
        released = self.event("RELEASE", "main")
        self.assertEqual(released["payload"]["phase_transition"]["supersedes"], "WAIT")
        self.assertEqual(released["payload"]["phase_transition"]["expected_artifacts"], expected)
        with self.assertRaises(ValueError):
            ops.operate(self.root, "A", "deliver", {"id": "MISSING", "reply_to": "RELEASE", "complete_phase": True,
                                                   "payload": {"verification": self.verification}})
        summary.write_text(json.dumps(self.understanding))
        ops.operate(self.root, "A", "deliver", {"id": "PHASE-DONE", "reply_to": "RELEASE", "complete_phase": True,
                                               "payload": {"verification": self.verification}})
        done = co.recover(self.root, "main")["completed_phases"]
        self.assertEqual(done[0]["outcome"], "passed")
        self.assertEqual(done[0]["receipt_id"], "PHASE-DONE")

    def test_resolve_requires_explicit_requests_evidence_and_reason(self):
        self.deliver()
        request = {"id": "CLOSE", "reply_to": "DELIVERY", "payload": {}}
        for extra in ({}, {"request_ids": ["ASSIGN"]}, {"request_ids": ["NOT-PUBLISHED"], "reason": "已查"}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                ops.operate(self.root, "main", "resolve", {**request, **extra})
        self.assertFalse((self.root / "events/main/CLOSE.json").exists())

    def test_bound_parent_proof_is_read_from_actual_message_without_manual_hash(self):
        parent = self.folder / "parent"
        co.initialize(parent, {"schema_version": 1, "batch_id": "PARENT", "main": "parent",
                               "authorization": "隔离父组",
                               "actors": {"parent": {"role": "main", "thread_id": "parent-chat"},
                                          "main": {"role": "worker", "thread_id": "coordinator"}}})
        cfg = co.read_json(self.root / "batch.json")
        cfg["coordination_group"] = {"parent": {"coordination_root": str(parent), "batch_id": "PARENT", "actor_id": "main"}}
        (self.root / "batch.json").write_text(json.dumps(cfg))
        co.emit(parent, "parent", {"batch_id": "PARENT", "id": "PARENT-READY", "sender": "parent", "recipient": "main",
                                   "kind": "READY", "entity_id": "PARENT-REVIEW", "revision": 2,
                                   "created_at": "2000-01-01T00:00:00+00:00", "refs": [], "payload": {}})
        ops.operate(self.root, "main", "ready", {"id": "WAIT", "reply_to": "ASSIGN", "payload": {},
                                                "phase": {"id": "RESUME", "state": "waiting",
                                                          "expected_artifacts": [{"path": str(self.folder / "summary.json")}]}})
        request = {"id": "RELEASE", "reply_to": "WAIT", "payload": {}, "phase": {
            "state": "released", "prerequisites": [{"coordination_root": str(parent), "message_id": "PARENT-READY"}]}}
        ops.operate(self.root, "main", "ready", request)
        proof = self.event("RELEASE", "main")["payload"]["phase_transition"]["prerequisites"][0]
        self.assertEqual((proof["batch_id"], proof["revision"]), ("PARENT", 2))
        self.assertEqual(proof["message_sha256"], co.verify_message(parent, "PARENT-READY")["message_sha256"])

    def test_cli_publishes_derivable_envelope_and_rejects_unknown_fields(self):
        file = self.folder / "request.json"
        request = {"id": "ACCEPT", "reply_to": "ASSIGN", "payload": self.understanding}
        file.write_text(json.dumps(request))
        command = [sys.executable, "-B", str(Path(ops.__file__)), "accept", "--root", str(self.root),
                   "--actor", "A", "--input", str(file)]
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)["message_id"], "ACCEPT")
        file.write_text(json.dumps({**request, "created_at": "自行造时间"}))
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 2)


if __name__ == "__main__":
    unittest.main()
