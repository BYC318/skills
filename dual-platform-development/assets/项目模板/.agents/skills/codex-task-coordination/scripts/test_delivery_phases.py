"""交付提前校验、阶段放行及真实产物回执；全部使用外部隔离夹具。"""

from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("coordination", Path(__file__).with_name("coordination.py"))
co = importlib.util.module_from_spec(spec)
spec.loader.exec_module(co)


class DeliveryPhaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ["COORDINATION_TEST_ROOT"])
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name).resolve()
        self.root, self.parent = self.folder / "child", self.folder / "parent"
        actors = {"main": {"role": "main", "thread_id": "fixture-coordinator"},
                  "A": {"role": "worker", "thread_id": "fixture-a"},
                  "B": {"role": "worker", "thread_id": "fixture-b"}}
        self.config = {"schema_version": 1, "batch_id": "CHILD", "main": "main", "actors": actors,
                       "authorization": "仅隔离夹具，禁止真实通知",
                       "coordination_group": {"parent": {"coordination_root": str(self.parent), "batch_id": "PARENT", "actor_id": "main"}}}
        parent_config = {"schema_version": 1, "batch_id": "PARENT", "main": "parent", "authorization": "仅隔离夹具",
                         "actors": {"parent": {"role": "main", "thread_id": "fixture-parent"},
                                    "main": {"role": "worker", "thread_id": "fixture-coordinator"}}}
        co.initialize(self.root, self.config)
        co.initialize(self.parent, parent_config)
        self.output = self.folder / "A-summary.json"
        self.expected = [{"path": str(self.output), "required_keys": ["objective", "assignment", "acceptance", "dependencies", "next_step"]}]
        self.verification = {"status": "passed", "evidence": ["夹具实际核验"]}
        self.send("ASSIGN")
        self.send("DELIVERY", sender="A", recipient="main", kind="RESULT", refs=["ASSIGN"], payload={"verification": self.verification})
        self.waiting = self.event("WAIT", kind="RESOLVED", refs=["ASSIGN", "DELIVERY"], payload={
            "recovery": {"resolution": "completed", "consumer": "A", "request_ids": ["ASSIGN"], "evidence_refs": ["DELIVERY"], "reason": "只关闭前一交付，后续恢复阶段尚待放行"},
            "phase_transition": {"id": "RESUME", "state": "waiting", "expected_artifacts": self.expected}})
        co.emit(self.root, "main", self.waiting)
        source = self.event("PARENT-READY", sender="parent", recipient="main", kind="READY", entity="PARENT-REVIEW")
        source["batch_id"] = "PARENT"
        co.emit(self.parent, "parent", source)

    def event(self, identity, sender="main", recipient="A", kind="ASSIGN", refs=None, payload=None, revision=1, entity="MODULE"):
        return {"batch_id": "CHILD", "id": identity, "sender": sender, "recipient": recipient, "kind": kind,
                "entity_id": entity, "revision": revision, "created_at": "2000-01-01T00:00:00+00:00", "refs": refs or [], "payload": payload or {}}

    def send(self, identity, **kwargs):
        event = self.event(identity, **kwargs)
        co.emit(self.root, event["sender"], event)
        return event

    def proof(self):
        meta = co.verify_message(self.parent, "PARENT-READY")
        return {"coordination_root": str(self.parent), "batch_id": "PARENT", "message_id": "PARENT-READY",
                "entity_id": meta["entity_id"], "revision": meta["revision"], "message_sha256": meta["message_sha256"]}

    def release(self, identity="RELEASE"):
        return self.event(identity, kind="READY", refs=["WAIT"], payload={"phase_transition": {
            "id": "RESUME", "state": "released", "supersedes": "WAIT", "prerequisites": [self.proof()], "expected_artifacts": self.expected}})

    def receipt(self, identity="PHASE-DONE"):
        return self.event(identity, sender="A", recipient="main", kind="RESULT", refs=["RELEASE"], payload={
            "verification": self.verification, "phase_receipt": {"transition_id": "RELEASE", "artifacts": [
                {"path": str(self.output), "file_sha256": hashlib.sha256(self.output.read_bytes()).hexdigest()}]}})

    def write_summary(self):
        self.output.write_text(json.dumps({"objective": "找回原始目标", "assignment": "MODULE R1", "acceptance": ["恢复实际上下文"], "dependencies": [], "next_step": "等待下一轮"}, ensure_ascii=False))

    def test_new_deliveries_fail_before_publish_for_invalid_verification(self):
        for kind in ("RESULT", "CONSUMED"):
            for value in (None, {}, {"status": "passed", "evidence": []}, {"status": "passed", "evidence": [{"path": "x"}]},
                          {"status": "passed", "evidence": [" "]}, {"status": "unknown", "evidence": ["依据"]}):
                with self.subTest(kind=kind, value=value), self.assertRaises(ValueError):
                    self.send("INVALID-DELIVERY", sender="A", recipient="main", kind=kind, payload={"verification": value})
                self.assertFalse((self.root / "events/A/INVALID-DELIVERY.json").exists())
        self.send("FAILED", sender="A", recipient="main", kind="RESULT", payload={"verification": {"status": "failed", "evidence": ["实际失败日志"]}})
        close = copy.deepcopy(self.waiting)
        close.update(id="CANNOT-CLOSE-FAILED", refs=["ASSIGN", "FAILED"])
        close["payload"]["recovery"]["evidence_refs"] = ["FAILED"]
        with self.assertRaises(ValueError):
            co.emit(self.root, "main", close)

    def test_legacy_delivery_stays_readable_but_cannot_be_renotified(self):
        old = self.event("OLD-RESULT", sender="A", recipient="main", kind="RESULT", payload={"verification": {"status": "passed", "evidence": [{"path": "旧格式"}]}})
        co.publish_event(self.root, old)
        before = (self.root / "events/A/OLD-RESULT.json").read_bytes()
        self.assertTrue(co.emit(self.root, "A", old)["duplicate"])
        self.assertTrue(co.recover(self.root, "main")["phase_transitions_pending"])
        with self.assertRaises(ValueError):
            co.prepare_notification(self.root, "A", ["OLD-RESULT"])
        self.send("CORRECTED", sender="A", recipient="main", kind="RESULT", refs=["OLD-RESULT"], payload={"verification": self.verification, "supersedes_result": "OLD-RESULT"})
        self.assertEqual(before, (self.root / "events/A/OLD-RESULT.json").read_bytes())

    def test_ack_and_closed_delivery_do_not_hide_waiting_phase_after_restart(self):
        co.acknowledge(self.root, "A", "ASSIGN")
        co.acknowledge(self.root, "main", "DELIVERY")
        co.acknowledge(self.root, "A", "WAIT")
        report = co.recover(self.root, "main")
        self.assertEqual(report["open_requests"], [])
        self.assertEqual(report["pending_messages"], [])
        self.assertEqual(report["awaiting_confirmation"], [])
        self.assertEqual(report["phase_transitions_pending"][0]["state"], "waiting")
        command = [sys.executable, "-B", str(Path(__file__).with_name("coordination.py")), "recover", "--root", str(self.root), "--actor", "main"]
        fresh = json.loads(subprocess.run(command, check=True, capture_output=True, text=True).stdout)
        self.assertEqual(report, fresh)

    def test_release_needs_current_authority_hash_and_bound_parent(self):
        release = self.release()
        for name in ("message_sha256", "batch_id", "revision", "coordination_root"):
            broken = copy.deepcopy(release)
            broken["payload"]["phase_transition"]["prerequisites"][0][name] = 9 if name == "revision" else "wrong"
            with self.subTest(name=name), self.assertRaises(ValueError):
                co.emit(self.root, "main", broken)
        missing = copy.deepcopy(release)
        missing["payload"]["phase_transition"]["prerequisites"] = []
        with self.assertRaises(ValueError):
            co.emit(self.root, "main", missing)
        co.emit(self.root, "main", release)
        self.assertEqual(next(row for row in co.inbox(self.root, "A") if row["message"]["id"] == "WAIT")["status"], "旧阶段")
        with self.assertRaises(ValueError):
            co.prepare_notification(self.root, "main", ["WAIT"])
        self.assertTrue(co.prepare_notification(self.root, "main", ["RELEASE"])["can_notify"])

    def test_ack_is_not_a_prerequisite_decision(self):
        ack = co.acknowledge(self.parent, "main", "PARENT-READY")["receipt_ids"][0]
        meta = co.verify_message(self.parent, ack)
        release = self.release()
        release["payload"]["phase_transition"]["prerequisites"][0].update(message_id=ack, message_sha256=meta["message_sha256"])
        with self.assertRaises(ValueError):
            co.emit(self.root, "main", release)

    def test_parent_revision_change_between_publish_and_notice_blocks_dispatch(self):
        co.emit(self.root, "main", self.release())
        source = self.event("PARENT-NEW", sender="parent", recipient="main", kind="READY", entity="PARENT-REVIEW", revision=2)
        source["batch_id"] = "PARENT"
        co.emit(self.parent, "parent", source)
        with self.assertRaises(ValueError):
            co.prepare_notification(self.root, "main", ["RELEASE"])
        pending = co.recover(self.root, "main")["phase_transitions_pending"]
        self.assertEqual(len(pending), 1)
        self.assertIn("取代", pending[0]["reason"])
        self.assertFalse((self.root / "notifications").exists())

    def test_missing_wrong_or_incomplete_artifact_cannot_complete_phase(self):
        co.emit(self.root, "main", self.release())
        co.acknowledge(self.root, "A", "RELEASE")
        self.assertEqual(len(co.recover(self.root, "A")["phase_transitions_pending"]), 1)
        self.write_summary()
        valid = self.receipt()
        for artifacts in ([], [{"path": str(self.output), "file_sha256": "0" * 64}], [{"path": str(self.folder / "other"), "file_sha256": "0" * 64}]):
            broken = copy.deepcopy(valid)
            broken["payload"]["phase_receipt"]["artifacts"] = artifacts
            with self.subTest(artifacts=artifacts), self.assertRaises(ValueError):
                co.emit(self.root, "A", broken)
        self.output.write_text('{}')
        with self.assertRaises(ValueError):
            co.emit(self.root, "A", self.receipt())
        self.write_summary()
        self.output.unlink()
        with self.assertRaises(ValueError):
            co.emit(self.root, "A", valid)

    def test_actual_receipt_completes_and_changed_file_reopens_phase(self):
        co.emit(self.root, "main", self.release())
        self.write_summary()
        co.emit(self.root, "A", self.receipt())
        before = {str(p): p.read_bytes() for p in self.root.rglob('*.json')}
        report = co.recover(self.root, "main")
        self.assertEqual(report["phase_transitions_pending"], [])
        self.assertEqual(report["completed_phases"][0]["receipt_id"], "PHASE-DONE")
        self.output.write_text('{"objective":"changed"}')
        changed = co.recover(self.root, "main")
        self.assertNotEqual(report["snapshot_sha256"], changed["snapshot_sha256"])
        self.assertIn("哈希", changed["phase_transitions_pending"][0]["reason"])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*.json')})

    def test_wrong_recipient_and_stale_phase_receipts_are_rejected(self):
        co.emit(self.root, "main", self.release())
        self.write_summary()
        wrong = self.receipt()
        wrong["sender"] = "B"
        with self.assertRaises(ValueError):
            co.emit(self.root, "B", wrong)
        new = self.release("RELEASE-NEW")
        new["refs"] = ["RELEASE"]
        new["payload"]["phase_transition"]["supersedes"] = "RELEASE"
        co.emit(self.root, "main", new)
        with self.assertRaises(ValueError):
            co.emit(self.root, "A", self.receipt())

    def test_phase_cannot_fork_or_silently_drop_expected_outputs(self):
        bad = self.release()
        bad["payload"]["phase_transition"]["expected_artifacts"] = [{"path": str(self.output)}]
        with self.assertRaises(ValueError):
            co.emit(self.root, "main", bad)
        def publish(index):
            try:
                co.emit(self.root, "main", self.release("RELEASE-" + str(index)))
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(publish, range(2))), 1)

    def test_registry_and_markdown_keep_phase_pending_even_when_messages_acked(self):
        co.acknowledge(self.root, "A", "WAIT")
        registry = self.folder / "registry.json"
        registry.write_text(json.dumps({"schema_version": 1, "tasks": self.config["actors"], "batches": [{"batch_id": "CHILD", "coordination_root": str(self.root)}]}))
        report = co.recover_registry(registry, "main")
        self.assertTrue(report["scan_complete"])
        self.assertEqual(report["phase_transitions_pending"][0]["batch_id"], "CHILD")
        self.assertIn("阶段放行与产物待核对", co.recovery_markdown(report))

    def test_parent_unavailable_or_rebound_stays_pending_without_false_completion(self):
        co.emit(self.root, "main", self.release())
        parent_config = self.parent / "batch.json"
        original = parent_config.read_bytes()
        parent_config.unlink()
        self.assertEqual(len(co.recover(self.root, "main")["phase_transitions_pending"]), 1)
        parent_config.write_bytes(original)
        config = json.loads(original)
        config["actors"]["main"]["thread_id"] = "replaced-coordinator"
        parent_config.write_text(json.dumps(config))
        with self.assertRaises(ValueError):
            co.prepare_notification(self.root, "main", ["RELEASE"])
        self.assertIn("绑定", co.recover(self.root, "main")["phase_transitions_pending"][0]["reason"])

    def test_new_revision_cannot_silently_drop_unfinished_phase(self):
        self.send("ASSIGN-NEXT", revision=2)
        pending = co.recover(self.root, "main")["phase_transitions_pending"]
        self.assertEqual(len(pending), 1)
        self.assertTrue(pending[0]["stale"])
        self.assertEqual(pending[0]["message_id"], "WAIT")

    def test_explicit_phase_cancellation_keeps_reason_without_faking_artifacts(self):
        cancelled = self.event("CANCEL-PHASE", kind="INVALIDATED", refs=["WAIT"], payload={"phase_transition": {
            "id": "RESUME", "state": "cancelled", "supersedes": "WAIT", "expected_artifacts": self.expected,
            "reason": "本合成场景的已授权决策明确取消后续恢复产物"}})
        co.emit(self.root, "main", cancelled)
        report = co.recover(self.root, "main")
        self.assertEqual(report["phase_transitions_pending"], [])
        self.assertEqual(report["completed_phases"][0]["outcome"], "cancelled")
        self.assertFalse(self.output.exists())

    @unittest.skipUnless(shutil.which("node"), "工具编排回归需要Node")
    def test_actual_dispatch_adapter_never_sends_invalid_delivery_or_obsolete_phase(self):
        runner = r'''
const {dispatchNotification}=require(process.argv[1]);
const {spawnSync}=require('child_process');
const options=JSON.parse(process.argv[2]); let sends=0;
const io={exec:async args=>{const p=spawnSync('/bin/sh',['-c',args.cmd],{encoding:'utf8'});return {exit_code:p.status,output:p.stdout,stderr:p.stderr};},
send:async args=>{sends++;return {threadId:args.threadId};}};
(async()=>process.stdout.write(JSON.stringify({result:await dispatchNotification(io,options),sends})))();
'''
        def dispatch(identity, sender="main"):
            options = {"root": str(self.root), "sender": sender, "messageIds": [identity], "scriptPath": str(Path(__file__).with_name("coordination.py")), "python": sys.executable}
            command = ["node", "-e", runner, str(Path(__file__).with_name("notification_dispatch.js")), json.dumps(options)]
            return json.loads(subprocess.run(command, check=True, capture_output=True, text=True).stdout)
        bad = self.event("LEGACY-BAD", sender="A", recipient="main", kind="RESULT", payload={"verification": {"status": "passed", "evidence": [{}]}})
        co.publish_event(self.root, bad)
        self.assertEqual(dispatch("LEGACY-BAD", "A")["sends"], 0)
        co.emit(self.root, "main", self.release())
        self.assertEqual(dispatch("WAIT")["sends"], 0)
        self.assertEqual(dispatch("RELEASE")["sends"], 1)
        newer = self.event("PARENT-NEXT", sender="parent", recipient="main", kind="READY", entity="PARENT-REVIEW", revision=2)
        newer["batch_id"] = "PARENT"
        co.emit(self.parent, "parent", newer)
        self.assertEqual(dispatch("RELEASE")["sends"], 0)


if __name__ == "__main__":
    unittest.main()
