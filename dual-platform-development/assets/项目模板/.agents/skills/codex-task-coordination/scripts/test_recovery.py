"""恢复对账的请求保留、关闭证据、执行去重与进程重启验证。"""

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("coordination", Path(__file__).with_name("coordination.py"))
co = importlib.util.module_from_spec(spec)
spec.loader.exec_module(co)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=os.environ["COORDINATION_TEST_ROOT"])
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()
        self.root = self.directory / "coordination"
        self.config = {"schema_version": 1, "batch_id": "RECOVERY-TEST", "main": "main", "authorization": "仅本机合成验证", "actors": {"main": {"role": "main"}, "shared": {"role": "shared"}, "A": {"role": "worker"}, "B": {"role": "worker"}}}
        co.initialize(self.root, self.config)

    def send(self, identity, sender="A", recipient="main", kind="REQUEST", revision=1, refs=None, payload=None, entity="CAPABILITY"):
        event = {"batch_id": self.config["batch_id"], "id": identity, "sender": sender, "recipient": recipient, "kind": kind, "entity_id": entity, "revision": revision, "created_at": "2000-01-01T00:00:00+00:00", "refs": refs or [], "payload": payload or {"description": "共享能力"}}
        co.emit(self.root, sender, event)
        return event

    def request(self):
        self.send("REQ-1")
        self.send("ASSIGN-1", "main", "shared", "ASSIGN", refs=["REQ-1"], payload={"consumers": ["A"]})

    def closure(self, consumer="A", outcome="completed", request_ids=None, evidence=None):
        request_ids = request_ids or ["REQ-1"]
        claim = {"resolution": outcome, "consumer": consumer, "request_ids": request_ids, "reason": "合成验证依据"}
        refs = list(request_ids)
        if evidence:
            claim["evidence_refs"] = evidence
            refs += evidence
        return self.send("CLOSE-" + consumer, "main", consumer, "RESOLVED" if outcome == "completed" else "INVALIDATED", refs=refs, payload={"recovery": claim})

    def plan(self):
        return {"actor": "A", "entity_id": "CAPABILITY", "revision": 1, "operation": "cherry_pick", "repo_id": "example-repo", "worktree": str(self.directory / "source-a"), "source_sha": "a" * 40}

    def result(self):
        return {"local_sha": "b" * 40, "verification": {"status": "passed", "evidence": ["合成Git核验"]}}

    def test_request_survives_ack_and_unrelated_repeated_corrections(self):
        self.request()
        self.send("ACK-REQ", "main", "A", "ACK", refs=["REQ-1"])
        for revision in (1, 2, 3):
            self.send("PAGE-" + str(revision), "main", "A", "ASSIGN", revision=revision, entity="MODULE-CHANGE")
        report = co.recover(self.root, "A")
        self.assertEqual([item["entity_id"] for item in report["open_requests"]], ["CAPABILITY", "MODULE-CHANGE"])
        self.assertEqual(report["open_requests"][0]["consumers"][0]["status"], "已分派，待交付")
        self.assertIn("PAGE-3", [item["id"] for item in report["pending_messages"]])

    def test_request_remains_once_after_multiple_revisions(self):
        self.request()
        for revision in (2, 3):
            self.send("CHANGE-" + str(revision), revision=revision - 1, payload={"description": "调整共享能力", "proposed_revision": revision})
            self.send("ASSIGN-" + str(revision), "main", "shared", "ASSIGN", revision=revision, refs=["CHANGE-" + str(revision)], payload={"consumers": ["A"]})
        report = co.recover(self.root, "main")
        self.assertEqual(len(report["open_requests"]), 1)
        request = report["open_requests"][0]
        self.assertEqual(request["revision"], 3)
        self.assertEqual(set(request["request_ids"]), {"REQ-1", "CHANGE-2", "CHANGE-3"})
        self.assertEqual(request["owners"], ["shared"])
        self.assertTrue(any(item["entity_id"] == "CAPABILITY" for item in report["next_steps"]))

    def test_delivery_and_legacy_success_text_do_not_close_dependency(self):
        self.request()
        self.send("RELEASE", "shared", "main", "RELEASE")
        # 模拟升级前已落盘的旧交付，不通过现在的新交付发布门槛补造历史。
        legacy = co.read_json(self.root / "events/A/REQ-1.json")["message"]
        co.publish_event(self.root, {**legacy, "id": "RESULT", "kind": "RESULT", "payload": {"description": "已完成，一切正常"}})
        report = co.recover(self.root, "main")
        self.assertEqual(len(report["closed_requests"]), 0)
        self.assertEqual(report["open_requests"][0]["consumers"][0]["status"], "已有结果，待主任务核验关闭")
        with self.assertRaises(ValueError):
            self.closure(evidence=["RESULT"])
        self.assertEqual(len(co.recover(self.root, "main")["open_requests"]), 1)

    def test_cancel_one_consumer_does_not_drop_another(self):
        self.request()
        self.send("REQ-B", "B")
        self.closure(outcome="cancelled")
        report = co.recover(self.root, "main")
        consumers = {item["consumer"]: item for item in report["open_requests"][0]["consumers"]}
        self.assertTrue(consumers["A"]["closed"])
        self.assertFalse(consumers["B"]["closed"])
        self.assertEqual(consumers["B"]["unresolved_request_ids"], ["REQ-B"])

    def test_explicit_verified_receipt_closes_but_does_not_erase_history(self):
        self.request()
        self.send("CONSUMED", kind="CONSUMED", payload={"verification": {"status": "passed", "evidence": ["合成验证日志"]}})
        self.assertEqual(len(co.recover(self.root, "main")["open_requests"]), 1)
        self.closure(evidence=["CONSUMED"])
        before = {str(path): path.read_bytes() for path in self.root.rglob("*.json")}
        report = co.recover(self.root, "main")
        self.assertEqual(report["open_requests"], [])
        self.assertEqual(report["closed_requests"][0]["request_ids"], ["REQ-1"])
        self.assertEqual(before, {str(path): path.read_bytes() for path in self.root.rglob("*.json")})
        self.assertEqual(report, co.recover(self.root, "main"))

    def test_unhandled_change_is_not_hidden_by_old_request_closure(self):
        self.request()
        self.send("CHANGE", payload={"description": "刚追加的新要求", "proposed_revision": 2})
        self.send("CONSUMED", kind="CONSUMED", payload={"verification": {"status": "passed", "evidence": ["旧要求的核验"]}})
        self.closure(evidence=["CONSUMED"])
        report = co.recover(self.root, "main")
        self.assertEqual(report["open_requests"][0]["consumers"][0]["unresolved_request_ids"], ["CHANGE"])

    def test_conflicting_closure_is_reported_instead_of_picking_by_clock(self):
        self.request()
        self.closure(outcome="cancelled")
        self.send("CONSUMED", kind="CONSUMED", payload={"verification": {"status": "passed", "evidence": ["验证记录"]}})
        self.send("OTHER-CLOSE", "main", "A", "INTEGRATED", refs=["REQ-1", "CONSUMED"], payload={"recovery": {"resolution": "completed", "consumer": "A", "request_ids": ["REQ-1"], "evidence_refs": ["CONSUMED"], "reason": "不同结论"}})
        self.assertEqual(co.recover(self.root, "main")["open_requests"][0]["consumers"][0]["status"], "关闭结论冲突，待核对")

    def test_action_gate_is_atomic_and_survives_revision_change(self):
        self.request()
        plan = self.plan()
        with ThreadPoolExecutor(max_workers=6) as pool:
            attempts = list(pool.map(lambda _: co.begin_action(self.root, "A", plan), range(12)))
        self.assertEqual(sum(item["can_execute"] for item in attempts), 1)
        identity = attempts[0]["action_id"]
        report = co.recover(self.root, "A")
        self.assertEqual(len(report["actions_pending_verification"]), 1)
        self.assertFalse(report["actions_pending_verification"][0]["can_execute"])
        self.send("ASSIGN-2", "main", "shared", "ASSIGN", revision=2)
        changed = {**plan, "revision": 2}
        self.assertFalse(co.begin_action(self.root, "A", changed)["can_execute"])
        with self.assertRaises(ValueError):
            co.finish_action(self.root, "B", identity, self.result())
        co.finish_action(self.root, "A", identity, self.result())
        self.assertTrue(co.finish_action(self.root, "A", identity, self.result())["duplicate"])
        self.assertFalse(co.begin_action(self.root, "A", changed)["can_execute"])
        self.assertEqual(co.recover(self.root, "A")["actions_pending_verification"], [])
        self.assertTrue(co.recover(self.root, "A")["completed_actions"][0]["stale"])

    def test_corrupt_action_receipt_is_rejected_and_pending_temp_is_ignored(self):
        self.request()
        start = co.begin_action(self.root, "A", self.plan())
        (self.root / "actions/.pending-interrupted").write_text("半份尚未发布的记录")
        self.assertEqual(len(co.recover(self.root, "A")["actions_pending_verification"]), 1)
        path = self.root / "actions" / (start["action_id"] + ".intent.json")
        record = json.loads(path.read_text())
        record["data"]["source_sha"] = "c" * 40
        path.write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            co.recover(self.root, "A")

    def test_restart_reads_disk_and_pending_ack_is_not_pending_business_execution(self):
        self.request()
        self.send("ACK-ASSIGN", "shared", "main", "ACCEPTED", refs=["ASSIGN-1"])
        program = Path(__file__).with_name("coordination.py")
        result = subprocess.run([sys.executable, str(program), "recover", "--root", str(self.root), "--actor", "shared"], check=True, capture_output=True, text=True)
        report = json.loads(result.stdout)
        self.assertEqual(report["pending_messages"], [])
        self.assertEqual(len(report["open_requests"]), 1)
        self.assertEqual(report["open_requests"][0]["owners"], ["shared"])
        self.assertEqual(report, co.recover(self.root, "shared"))

    def test_project_scan_preserves_old_pending_work_and_distinguishes_batches(self):
        self.request()
        second = self.directory / "second"
        config = {**self.config, "batch_id": "NEXT-BATCH"}
        co.initialize(second, config)
        registry = {"schema_version": 1, "tasks": self.config["actors"], "batches": [{"batch_id": self.config["batch_id"], "coordination_root": str(self.root), "status": "已完成"}, {"batch_id": "NEXT-BATCH", "coordination_root": str(second)}]}
        path = self.directory / "registry.json"
        path.write_text(json.dumps(registry))
        report = co.recover_registry(path, "main")
        self.assertTrue(report["scan_complete"])
        self.assertEqual(report["open_requests"][0]["batch_id"], self.config["batch_id"])
        self.assertIn(self.config["batch_id"], co.recovery_markdown(report))
        registry["batches"].append({"batch_id": "MISSING-BATCH", "coordination_root": str(self.directory / "missing")})
        path.write_text(json.dumps(registry))
        incomplete = co.recover_registry(path, "main")
        self.assertFalse(incomplete["scan_complete"])
        self.assertEqual(len(incomplete["unavailable_batches"]), 1)
        self.assertEqual(len(incomplete["open_requests"]), 1)
        self.assertIn("未能扫描", incomplete["next_steps"][0]["action"])

    def test_empty_registry_cannot_mean_no_pending_work(self):
        path = self.directory / "empty.json"
        path.write_text(json.dumps({"schema_version": 1, "tasks": self.config["actors"], "batches": []}))
        with self.assertRaises(ValueError):
            co.recover_registry(path, "main")

    def test_deferred_request_stays_open_with_explicit_destination(self):
        self.request()
        with self.assertRaises(ValueError):
            self.closure(outcome="deferred")
        self.send("DEFER", "main", "A", "INVALIDATED", refs=["REQ-1"], payload={"recovery": {"resolution": "deferred", "consumer": "A", "request_ids": ["REQ-1"], "reason": "本轮暂缓", "next_batch": "NEXT-BATCH"}})
        report = co.recover(self.root, "main")
        self.assertEqual(report["open_requests"][0]["consumers"][0]["status"], "已延后，仍未完成")

    def test_actor_cannot_publish_completion_and_failed_verification_cannot_finish_action(self):
        self.request()
        with self.assertRaises(ValueError):
            self.send("FAKE-CLOSE", payload={"recovery": {"resolution": "completed"}})
        start = co.begin_action(self.root, "A", self.plan())
        with self.assertRaises(ValueError):
            co.finish_action(self.root, "A", start["action_id"], {"local_sha": "b" * 40, "verification": {"status": "failed", "evidence": ["失败"]}})
        self.assertEqual(len(co.recover(self.root, "A")["actions_pending_verification"]), 1)

    def test_shared_assignment_without_page_request_is_not_lost_after_ack(self):
        assignment = self.send("DIRECT-SHARED", "main", "shared", "ASSIGN")
        self.send("ACK-DIRECT", "shared", "main", "ACK", refs=[assignment["id"]])
        report = co.recover(self.root, "shared")
        self.assertEqual(report["pending_messages"], [])
        self.assertEqual(report["open_requests"][0]["request_ids"], ["DIRECT-SHARED"])
        self.assertEqual(report["open_requests"][0]["consumers"][0]["consumer"], "shared")
        self.assertTrue(report["next_steps"])

    def test_orphan_blocked_event_is_retained_even_after_ack(self):
        blocked = self.send("ORPHAN-BLOCK", kind="BLOCKED")
        self.send("ACK-ORPHAN", "main", "A", "ACK", refs=[blocked["id"]])
        report = co.recover(self.root, "main")
        self.assertEqual(report["pending_messages"], [])
        self.assertEqual(report["unlinked_events"][0]["id"], blocked["id"])
        self.assertIn("缺少原始请求", report["next_steps"][0]["action"])

    def test_unknown_action_blocks_another_commit_in_the_same_worktree(self):
        self.request()
        plan = self.plan()
        co.begin_action(self.root, "A", plan)
        with self.assertRaises(ValueError):
            co.begin_action(self.root, "A", {**plan, "source_sha": "c" * 40})

    def test_blocked_dependency_has_explicit_followup_instead_of_only_ack(self):
        self.request()
        self.send("BLOCKED", "shared", "main", "BLOCKED")
        report = co.recover(self.root, "main")
        self.assertTrue(any(item.get("message_ids") == ["BLOCKED"] for item in report["next_steps"]))


if __name__ == "__main__":
    unittest.main()
