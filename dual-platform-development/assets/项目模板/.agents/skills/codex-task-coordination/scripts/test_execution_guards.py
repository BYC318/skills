"""用真实CLI、原始Git路径和可中断的冻结事务验证三项执行防护。"""

from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import coordination as co
import execution_guards as guard


class ExecutionGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ["COORDINATION_TEST_ROOT"])
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name).resolve()
        self.root = self.folder / "协调资料"
        self.config = {"schema_version": 1, "batch_id": "GUARDS", "main": "main",
                       "authorization": "仅隔离合成夹具；不通知聊天、不操作应用源码",
                       "actors": {"main": {"role": "main"}, "A": {"role": "worker"}, "shared": {"role": "shared"}},
                       "scope_freeze": {"status": "未冻结", "pending_next_batch": ["保留项目定制"]}}
        co.initialize(self.root, self.config)
        self.integration = self.root / "integration.json"
        self.inputs = self.folder / "终版输入.json"
        self.write(self.inputs, {"source_head": "a" * 40, "commits": ["a" * 40]})
        for actor in ("A", "shared"):
            file = self.folder / (actor + "-终版清单.json")
            self.write(file, {"目的": actor + "实际合成产物"})
            event = self.event("RESULT-" + actor, actor, "main", "RESULT")
            event["payload"] = {"verification": {"status": "passed", "evidence": ["已核对合成文件"]},
                                "artifacts": [{"path": str(file), "file_sha256": hashlib.sha256(file.read_bytes()).hexdigest()}]}
            co.emit(self.root, actor, event)
        self.document = {"batch_id": "GUARDS", "readiness": {"required_tasks": ["A", "shared"],
                         "final_deliveries": [{"actor": a, "message_id": "RESULT-" + a} for a in ("A", "shared")],
                         "all_tasks_complete": True, "shared_releases_frozen": True, "open_blockers": []},
                         "自定义": "保留"}
        self.write(self.integration, self.document)

    def write(self, path, value):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def event(self, identity, sender="main", recipient="A", kind="ASSIGN", revision=1):
        return {"batch_id": "GUARDS", "id": identity, "sender": sender, "recipient": recipient, "kind": kind,
                "entity_id": "MODULE-" + (sender if sender != "main" else recipient), "revision": revision,
                "created_at": "2000-01-01T00:00:00+00:00", "refs": [], "payload": {}}

    def cli(self, program, *args):
        return subprocess.run([sys.executable, "-B", str(Path(__file__).with_name(program)), *args], capture_output=True, text=True)

    def freeze(self, identity="F1", supersedes=None):
        return guard.freeze_integration(self.root, "main", identity, self.integration, self.inputs, supersedes)

    def status(self):
        return guard.integration_status(self.root, co.read_json(self.root / "batch.json"), co.load_events(self.root, self.config))

    def test_inbox_cli_alias_and_conflict_before_side_effects(self):
        before = {str(p): p.read_bytes() for p in self.root.rglob("*.json")}
        normal = self.cli("coordination.py", "inbox", "--root", str(self.root), "--recipient", "main")
        alias = self.cli("coordination.py", "inbox", "--root", str(self.root), "--actor", "main")
        self.assertEqual(normal.returncode, 0)
        self.assertEqual(alias.returncode, 0)
        self.assertEqual(json.loads(normal.stdout), json.loads(alias.stdout))
        conflict = self.cli("coordination.py", "inbox", "--root", str(self.root), "--recipient", "main", "--actor", "A")
        unknown = self.cli("coordination.py", "inbox", "--root", str(self.root), "--actor", "missing")
        self.assertEqual(conflict.returncode, 2)
        self.assertEqual(unknown.returncode, 2)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob("*.json")})

    def test_raw_chinese_special_paths_and_missing_extra_cli_exit(self):
        repo = self.folder / "中文仓库"
        repo.mkdir()
        env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
        def git(*args):
            return subprocess.run(["git", "-C", str(repo), *args], env=env, capture_output=True, check=True).stdout
        git("init", "-b", "fixture")
        names = ["文档/协作开发说明.md", "a b.txt", "制表\t名称", "换\n行", '引号"与\\反斜线']
        for name in names:
            p = repo / name
            p.parent.mkdir(exist_ok=True)
            p.write_text("合成文件")
        git("add", "--", *names)
        index = repo / ".git/index"
        before = index.read_bytes()
        self.assertIn(b'"', git("diff", "--cached", "--name-only"))
        for quote in ("true", "false"):
            git("config", "core.quotepath", quote)
            result = guard.staged_paths(repo, names)
            self.assertTrue(result["matches"])
            self.assertEqual(set(result["actual_paths"]), set(names))
        expected = self.folder / "expected.json"
        self.write(expected, names[:-1] + ["未暂存"])
        failed = self.cli("execution_guards.py", "check-staged", "--repo", str(repo), "--expected", str(expected))
        self.assertEqual(failed.returncode, 2)
        result = json.loads(failed.stdout)
        self.assertEqual(result["missing_paths"], ["未暂存"])
        self.assertEqual(result["extra_paths"], [names[-1]])
        self.assertEqual(before, index.read_bytes())
        self.assertFalse((repo / ".git/refs/heads/fixture").exists())

    def test_unmerged_and_redirected_indexes_are_rejected(self):
        repo = self.folder / "repo"
        repo.mkdir()
        def git(*args, data=None):
            return subprocess.run(["git", "-C", str(repo), *args], input=data, check=True, capture_output=True).stdout
        git("init", "-b", "fixture")
        sha = git("hash-object", "-w", "--stdin", data=b"synthetic").strip().decode()
        entries = "".join("100644 " + sha + " " + str(stage) + "\t冲突文件\n" for stage in (1, 2, 3))
        git("update-index", "--index-info", data=entries.encode())
        self.assertTrue(guard.staged_paths(repo, ["冲突文件"])["unmerged"])
        self.assertFalse(guard.staged_paths(repo, ["冲突文件"])["matches"])
        with patch.dict(os.environ, {"GIT_INDEX_FILE": str(self.folder / "other-index")}), self.assertRaises(ValueError):
            guard.staged_paths(repo, [])

    def test_freeze_sets_state_preserves_customizations_and_is_idempotent(self):
        result = self.freeze()
        self.assertTrue(result["can_integrate"])
        config = co.read_json(self.root / "batch.json")
        self.assertEqual(config["scope_freeze"]["pending_next_batch"], ["保留项目定制"])
        self.assertEqual({k: v for k, v in config.items() if k != "scope_freeze"}, guard.scope_identity(self.config))
        raw = (self.root / "batch.json").read_bytes()
        self.assertTrue(self.freeze()["duplicate"])
        self.assertEqual(raw, (self.root / "batch.json").read_bytes())
        self.assertEqual(co.recover(self.root, "main")["integration_pending_verification"], [])
        passed = self.cli("execution_guards.py", "check-integration", "--root", str(self.root), "--actor", "main")
        self.assertEqual(passed.returncode, 0)

    def test_missing_freeze_is_visible_even_when_readiness_claims_complete(self):
        self.assertFalse(self.status()["can_integrate"])
        report = co.recover(self.root, "main")
        self.assertEqual(len(report["integration_pending_verification"]), 1)
        self.assertIn("scope_freeze", report["integration_pending_verification"][0]["reasons"][0])
        failed = self.cli("execution_guards.py", "check-integration", "--root", str(self.root), "--actor", "main")
        self.assertEqual(failed.returncode, 2)

    def test_interruption_between_snapshot_and_pointer_recovers_without_git(self):
        before = (self.root / "batch.json").read_bytes()
        with patch.object(guard, "replace_config", side_effect=OSError("合成进程中断")), self.assertRaises(OSError):
            self.freeze()
        snapshot = self.root / "freezes/F1.json"
        captured = snapshot.read_bytes()
        self.assertEqual(before, (self.root / "batch.json").read_bytes())
        report = co.recover(self.root, "main")
        self.assertTrue(report["integration_pending_verification"])
        self.assertTrue(self.freeze()["duplicate"])
        self.assertEqual(captured, snapshot.read_bytes())
        self.assertTrue(self.status()["can_integrate"])

    def test_concurrent_identical_freeze_publishes_one_snapshot(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.freeze(), range(4)))
        self.assertEqual(sum(not x["duplicate"] for x in results), 1)
        self.assertEqual(len(list((self.root / "freezes").glob("*.json"))), 1)

    def test_real_process_killed_after_snapshot_before_state_write(self):
        program = """import os, signal, sys
from pathlib import Path
import execution_guards as guard
def interrupt(*args):
    os.kill(os.getpid(), signal.SIGKILL)
guard.replace_config = interrupt
guard.freeze_integration(Path(sys.argv[1]), 'main', 'CRASH', Path(sys.argv[2]), Path(sys.argv[3]))
"""
        result = subprocess.run([sys.executable, "-B", "-c", program, str(self.root), str(self.integration), str(self.inputs)],
                                cwd=Path(__file__).parent, capture_output=True, text=True)
        self.assertEqual(result.returncode, -9, result.stderr)
        fresh = self.cli("coordination.py", "recover", "--root", str(self.root), "--actor", "main")
        self.assertEqual(fresh.returncode, 0, fresh.stderr)
        self.assertTrue(json.loads(fresh.stdout)["integration_pending_verification"])
        resumed = self.cli("execution_guards.py", "freeze-integration", "--root", str(self.root), "--actor", "main",
                           "--freeze-id", "CRASH", "--integration", str(self.integration), "--inputs", str(self.inputs))
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertTrue(json.loads(resumed.stdout)["duplicate"])

    def test_shared_sealed_release_is_supported_without_extra_result(self):
        release = self.event("SEALED", "shared", "main", "RELEASE")
        release["payload"]["artifacts"] = co.load_events(self.root, self.config)["RESULT-shared"]["payload"]["artifacts"]
        co.emit(self.root, "shared", release)
        self.document["readiness"]["final_deliveries"][1]["message_id"] = "SEALED"
        self.write(self.integration, self.document)
        self.assertTrue(self.freeze()["can_integrate"])

    def test_legacy_manual_snapshot_can_be_explicitly_adopted_preserving_bytes(self):
        cfg = co.read_json(self.root / "batch.json")
        cfg["scope_freeze"].update(status="已冻结", snapshot_path=str(self.inputs),
                                 snapshot_sha256=hashlib.sha256(self.inputs.read_bytes()).hexdigest())
        self.write(self.root / "batch.json", cfg)
        before = self.inputs.read_bytes()
        self.assertFalse(self.status()["can_integrate"])
        result = self.freeze("ADOPTED", str(self.inputs))
        self.assertTrue(result["can_integrate"])
        self.assertEqual(before, self.inputs.read_bytes())

    def test_no_shared_task_requires_no_shared_seal_and_malformed_documents_are_pending(self):
        cfg = co.read_json(self.root / "batch.json")
        del cfg["actors"]["shared"]
        # 此夹具另建纯模块批次，避免把旧消息的发送者从已有批次删除。
        root = self.folder / "no-shared"
        co.initialize(root, cfg)
        event = co.load_events(self.root, self.config)["RESULT-A"]
        co.emit(root, "A", event)
        doc = copy.deepcopy(self.document)
        doc["readiness"].update(required_tasks=["A"], final_deliveries=[{"actor": "A", "message_id": "RESULT-A"}], shared_releases_frozen=False)
        integration = root / "integration.json"
        self.write(integration, doc)
        self.assertTrue(guard.freeze_integration(root, "main", "SOLO", integration, self.inputs)["can_integrate"])
        self.write(integration, [])
        self.assertTrue(co.recover(root, "main")["integration_pending_verification"])

    def test_result_readiness_scope_and_artifact_failures_do_not_freeze(self):
        for variant in ("missing", "duplicate", "incomplete", "blocked", "unsealed", "consumed", "artifact", "stale"):
            doc = copy.deepcopy(self.document)
            if variant == "missing": doc["readiness"]["required_tasks"] = ["A"]
            if variant == "duplicate": doc["readiness"]["final_deliveries"][1] = doc["readiness"]["final_deliveries"][0]
            if variant == "incomplete": doc["readiness"]["all_tasks_complete"] = False
            if variant == "blocked": doc["readiness"]["open_blockers"] = ["未解决"]
            if variant == "unsealed": doc["readiness"]["shared_releases_frozen"] = False
            if variant == "consumed":
                kind = "CONSUMED"
                event = self.event(kind, "shared", "main", kind)
                if variant == "consumed": event["payload"] = {"verification": {"status": "passed", "evidence": ["仅接入"]}}
                co.emit(self.root, "shared", event)
                doc["readiness"]["final_deliveries"][1]["message_id"] = kind
            if variant == "artifact": (self.folder / "A-终版清单.json").write_text("被修改")
            if variant == "stale":
                self.write(self.folder / "A-终版清单.json", {"目的": "A实际合成产物"})
                co.emit(self.root, "main", self.event("NEW", revision=2))
            self.write(self.integration, doc)
            with self.subTest(variant=variant), self.assertRaises(ValueError): self.freeze()
            self.assertFalse((self.root / "freezes/F1.json").exists())

    def test_input_tamper_state_drift_and_new_freeze_require_explicit_successor(self):
        self.freeze()
        raw = (self.root / "freezes/F1.json").read_bytes()
        self.write(self.inputs, {"source_head": "b" * 40})
        self.assertFalse(self.status()["can_integrate"])
        with self.assertRaises(ValueError): self.freeze()
        with self.assertRaises(ValueError): self.freeze("F2")
        next_result = self.freeze("F2", str(self.root / "freezes/F1.json"))
        self.assertTrue(next_result["can_integrate"])
        self.assertEqual(raw, (self.root / "freezes/F1.json").read_bytes())
        cfg = co.read_json(self.root / "batch.json")
        cfg["scope_freeze"]["status"] = "未冻结"
        self.write(self.root / "batch.json", cfg)
        self.assertTrue(co.recover(self.root, "A")["integration_pending_verification"])

    def test_target_progress_and_rebase_results_do_not_invalidate_frozen_inputs(self):
        self.document["repositories"] = [{"repo_id": "repo", "target_branch": "refs/heads/feature", "startup_sha": "a" * 40, "target_head_before": "b" * 40}]
        self.write(self.integration, self.document)
        self.freeze()
        self.document["repositories"][0]["target_head_before"] = "c" * 40
        self.document["rebases"] = [{"status": "completed", "new_head": "d" * 40}]
        self.document["readiness"]["integration_started_at"] = "2000-01-01T00:00:00Z"
        self.write(self.integration, self.document)
        self.assertTrue(self.status()["can_integrate"])
        self.document["repositories"][0]["target_branch"] = "refs/heads/wrong"
        self.write(self.integration, self.document)
        self.assertFalse(self.status()["can_integrate"])

    def test_legacy_no_integration_and_broken_integration_remain_distinguishable(self):
        self.integration.unlink()
        self.assertFalse(self.status()["registered"])
        self.assertEqual(co.recover(self.root, "main")["integration_pending_verification"], [])
        self.integration.write_text("broken")
        self.assertTrue(co.recover(self.root, "main")["integration_pending_verification"])


if __name__ == "__main__":
    unittest.main()
