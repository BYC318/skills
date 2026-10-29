"""重现同实体多模块串单，并保护旧关闭记录与共享消费者语义。"""

import os
from pathlib import Path
import tempfile
import unittest

import coordination as co
import message_operations as ops


class RecoveryScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ["COORDINATION_TEST_ROOT"])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "batch"
        self.config = {"schema_version": 1, "batch_id": "SCOPE", "main": "main", "authorization": "仅隔离回归",
                       "actors": {"main": {"role": "main"}, "A": {"role": "worker"},
                                  "B": {"role": "worker"}, "shared": {"role": "shared"}}}
        co.initialize(self.root, self.config)

    def event(self, identity, sender, recipient, kind, payload=None, refs=(), revision=1):
        return {"batch_id": "SCOPE", "id": identity, "sender": sender, "recipient": recipient, "kind": kind,
                "entity_id": "SAME-REQUIREMENT", "revision": revision, "created_at": "2000-01-01T00:00:00+00:00",
                "refs": list(refs), "payload": payload or {"description": "本层实际工作"}}

    def send(self, identity, sender, recipient, kind, **kwargs):
        event = self.event(identity, sender, recipient, kind, **kwargs)
        co.emit(self.root, sender, event)
        return event

    def result(self, actor):
        self.send("RESULT-" + actor, actor, "main", "RESULT",
                  payload={"verification": {"status": "passed", "evidence": ["隔离夹具实际核验"]}})

    def close(self, actor, requests, identity=None):
        return ops.operate(self.root, "main", "resolve", {
            "id": identity or "CLOSE-" + actor, "reply_to": "RESULT-" + actor,
            "request_ids": requests, "reason": "已审核本人分派及结果", "payload": {}})

    def consumers(self):
        report = co.recover(self.root, "main")
        request = (report["open_requests"] + report["closed_requests"])[0]
        return {item["consumer"]: item for item in request["consumers"]}

    def test_same_entity_modules_close_only_their_own_assignments(self):
        for actor in ("A", "B"):
            self.send("ASSIGN-" + actor, "main", actor, "ASSIGN")
            self.result(actor)
        self.close("A", ["ASSIGN-A"])
        rows = self.consumers()
        self.assertTrue(rows["A"]["closed"])
        self.assertEqual(rows["A"]["request_ids"], ["ASSIGN-A"])
        self.assertEqual(rows["B"]["unresolved_request_ids"], ["ASSIGN-B"])
        self.close("B", ["ASSIGN-B"])
        self.assertEqual(co.recover(self.root, "main")["open_requests"], [])

    def test_new_cross_consumer_closure_is_rejected_without_publishing(self):
        for actor in ("A", "B"):
            self.send("ASSIGN-" + actor, "main", actor, "ASSIGN")
        self.result("A")
        with self.assertRaisesRegex(ValueError, "不属于对应消费者"):
            self.close("A", ["ASSIGN-B"])
        self.assertFalse((self.root / "events/main/CLOSE-A.json").exists())

    def test_second_assignment_for_same_actor_is_not_hidden(self):
        for identity in ("ASSIGN-A1", "ASSIGN-A2"):
            self.send(identity, "main", "A", "ASSIGN")
        self.send("ASSIGN-B", "main", "B", "ASSIGN")
        self.result("A")
        self.close("A", ["ASSIGN-A1"])
        self.assertEqual(self.consumers()["A"]["unresolved_request_ids"], ["ASSIGN-A2"])

    def test_shared_assignment_remains_required_for_both_declared_consumers(self):
        self.send("COMMON", "main", "shared", "ASSIGN", payload={"consumers": ["A", "B"]})
        self.result("A")
        self.close("A", ["COMMON"])
        rows = self.consumers()
        self.assertTrue(rows["A"]["closed"])
        self.assertFalse(rows["B"]["closed"])
        self.assertEqual(rows["B"]["request_ids"], ["COMMON"])

    def test_old_shared_assignment_can_supply_a_later_ready(self):
        self.send("COMMON", "main", "shared", "ASSIGN")
        self.send("READY-A", "main", "A", "READY", refs=["COMMON"])
        self.result("A")
        self.close("A", ["COMMON", "READY-A"])
        self.assertTrue(self.consumers()["A"]["closed"])

    def test_legacy_broad_closure_remains_readable_but_cannot_close_another_actor(self):
        for actor in ("A", "B"):
            self.send("ASSIGN-" + actor, "main", actor, "ASSIGN")
        self.result("A")
        legacy = self.event("LEGACY", "main", "A", "RESOLVED", refs=["ASSIGN-A", "ASSIGN-B", "RESULT-A"],
                            payload={"recovery": {"resolution": "completed", "consumer": "A",
                                     "request_ids": ["ASSIGN-A", "ASSIGN-B"], "evidence_refs": ["RESULT-A"], "reason": "旧版全组归并"}})
        co.publish_event(self.root, legacy)
        before = (self.root / "events/main/LEGACY.json").read_bytes()
        rows = self.consumers()
        self.assertTrue(rows["A"]["closed"])
        self.assertFalse(rows["B"]["closed"])
        self.assertTrue(co.emit(self.root, "main", legacy)["duplicate"])
        self.assertEqual(before, (self.root / "events/main/LEGACY.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
