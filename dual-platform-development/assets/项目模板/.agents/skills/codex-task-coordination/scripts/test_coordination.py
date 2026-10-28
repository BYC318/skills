"""本机信箱与选择性集成验证，产物仅写显式指定的测试目录。"""

from concurrent.futures import ThreadPoolExecutor
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("coordination", Path(__file__).with_name("coordination.py"))
co = importlib.util.module_from_spec(spec)
spec.loader.exec_module(co)


class CoordinationTests(unittest.TestCase):
    def setUp(self):
        destination = Path(os.environ["COORDINATION_TEST_ROOT"])
        self.temporary = tempfile.TemporaryDirectory(dir=destination)
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.root = self.directory / "coordination"
        self.config = {
            "schema_version": 1, "batch_id": "TEST-001", "main": "main",
            "authorization": "仅合成测试，不创建真实任务，不操作实际工程",
            "actors": {"main": {"role": "main"}, "shared": {"role": "shared"}, "A": {"role": "worker"}, "B": {"role": "worker"}}
        }
        co.initialize(self.root, self.config)

    def event(self, identity="MSG-A-1", sender="A", recipient="main", kind="REQUEST", revision=1, refs=None):
        return {"batch_id": "TEST-001", "id": identity, "sender": sender, "recipient": recipient,
                "kind": kind, "entity_id": "CR-001", "revision": revision,
                "created_at": "2000-01-01T00:00:00+00:00", "refs": refs or [], "payload": {"description": "合成测试"}}

    def test_retry_is_idempotent_and_rejects_changed_body(self):
        event = self.event()
        self.assertFalse(co.emit(self.root, "A", event)["duplicate"])
        self.assertTrue(co.emit(self.root, "A", event)["duplicate"])
        changed = copy.deepcopy(event)
        changed["payload"]["description"] = "不能覆盖"
        with self.assertRaises(ValueError):
            co.emit(self.root, "A", changed)
        self.assertEqual(len(co.inbox(self.root, "main")), 1)

    def test_ack_checks_identity_and_is_not_completion(self):
        co.emit(self.root, "A", self.event())
        self.assertEqual(co.inbox(self.root, "main")[0]["status"], "待确认")
        ack = self.event("MSG-main-ack", "main", "A", "ACK", refs=["MSG-A-1"])
        co.emit(self.root, "main", ack)
        self.assertEqual(co.inbox(self.root, "main")[0]["status"], "已确认收到")
        self.assertEqual(co.inbox(self.root, "A")[0]["status"], "回执")
        wrong = self.event("MSG-B-ack", "B", "main", "ACK", refs=["MSG-A-1"])
        with self.assertRaises(ValueError):
            co.emit(self.root, "B", wrong)
        self.assertNotIn("completion", co.inbox(self.root, "main")[0])

    def test_revision_invalidates_old_action_but_preserves_history(self):
        original = self.event()
        co.emit(self.root, "A", original)
        co.emit(self.root, "main", self.event("MSG-main-v2", "main", "A", "INVALIDATED", revision=2))
        self.assertTrue(co.emit(self.root, "A", original)["stale"])
        for revision in (1, 3):
            with self.assertRaises(ValueError):
                co.emit(self.root, "A", self.event("MSG-A-new", revision=revision))
        co.emit(self.root, "A", self.event("MSG-A-v2", revision=2))
        self.assertEqual(co.inbox(self.root, "main")[0]["status"], "旧修订")

    def test_role_routing_batch_and_path_guards(self):
        variants = [self.event(sender="A", recipient="shared"), self.event(kind="READY"), self.event(kind="RELEASE")]
        wrong_batch = self.event()
        wrong_batch["batch_id"] = "OTHER"
        variants.append(wrong_batch)
        escaped = self.event("../escape")
        variants.append(escaped)
        for event in variants:
            with self.subTest(event=event), self.assertRaises(ValueError):
                co.emit(self.root, "A", event)
        self.assertEqual(co.inbox(self.root, "main"), [])

    def test_concurrent_messages_survive_and_resume_without_memory(self):
        events = [self.event("MSG-A-" + str(index)) for index in range(24)]
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(lambda event: co.emit(self.root, "A", event), events))
        self.assertEqual(len(co.inbox(self.root, "main")), 24)
        program = Path(__file__).with_name("coordination.py")
        result = subprocess.run([os.sys.executable, str(program), "inbox", "--root", str(self.root), "--recipient", "main"], check=True, capture_output=True, text=True)
        self.assertEqual(len(json.loads(result.stdout)), 24)

    def test_tampered_message_and_reinitialization_are_rejected(self):
        co.emit(self.root, "A", self.event())
        path = self.root / "events/A/MSG-A-1.json"
        record = json.loads(path.read_text())
        record["message"]["payload"]["description"] = "被改写"
        path.write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            co.inbox(self.root, "main")
        with self.assertRaises(FileExistsError):
            co.initialize(self.root, self.config)

    def test_cherry_pick_consumers_and_main_integrate_shared_once(self):
        repo = self.directory / "git-fixture"
        repo.mkdir()
        environment = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}

        def git(*arguments):
            result = subprocess.run(["git", "-C", str(repo), "-c", "user.name=协作测试", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=" + str(self.directory / "no-hooks"), *arguments], env=environment, check=True, capture_output=True, text=True)
            return result.stdout.strip()

        def commit(filename, content, message):
            (repo / filename).write_text(content, encoding="utf-8")
            git("add", "--", filename)
            git("commit", "-m", message)
            return git("rev-parse", "HEAD")

        git("init", "-b", "base")
        baseline = commit("base.txt", "共同基线\n", "chore: 建立合成基线")
        git("switch", "-c", "shared-source")
        commit("unrelated.txt", "无关共享能力\n", "feat(shared): 另一共享能力")
        shared = commit("shared-capability.txt", "共享能力\n", "feat(shared): 共享能力")
        receipts, page_commits = {}, []
        for actor in ("a", "b"):
            git("switch", "-c", "worker-" + actor, baseline)
            layout = commit(actor + ".txt", "模块行为\n", "feat(" + actor + "): 模块行为")
            git("cherry-pick", "-x", shared)
            receipts[actor] = git("rev-parse", "HEAD")
            call = commit(actor + ".txt", "模块行为\n调用共享能力\n", "feat(" + actor + "): 接入共享能力")
            page_commits.extend((layout, call))
            self.assertFalse((repo / "unrelated.txt").exists())
        self.assertNotEqual(receipts["a"], receipts["b"])
        git("switch", "-c", "integration", baseline)
        git("cherry-pick", "-x", shared)
        canonical = git("rev-parse", "HEAD")
        for source in page_commits:
            git("cherry-pick", "-x", source)
        self.assertEqual(git("log", "--format=%s").splitlines().count("feat(shared): 共享能力"), 1)
        self.assertFalse((repo / "unrelated.txt").exists())
        self.assertEqual((repo / "shared-capability.txt").read_text(), "共享能力\n")
        for actor in ("a", "b"):
            self.assertIn("调用共享能力", (repo / (actor + ".txt")).read_text())
            self.assertNotEqual(receipts[actor], canonical)


if __name__ == "__main__":
    unittest.main()
