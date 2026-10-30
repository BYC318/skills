"""汇总读取真实登记，拒绝空计划；导出不修改登记，也不冒称实时核验。"""

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import coordination as co


class TaskMapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ["COORDINATION_TEST_ROOT"])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / "长期目录.json"
        self.registry = {"schema_version": 1, "main_task_id": "ios", "custom": {"keep": True}, "tasks": {
            "ios": {"role": "main", "thread_id": "actual-ios", "title": "需求｜iOS 总协调", "workspaces": []},
            "module": {"role": "worker", "thread_id": "actual-module", "title": "需求｜iOS 子模块任务｜登录",
                       "status": "等待下一轮", "workspaces": [{"repo_id": "ios", "path": "/已核实工作区", "branch": "refs/heads/module"}]}}}

    def save(self):
        self.path.write_text(json.dumps(self.registry, ensure_ascii=False))

    def test_cli_exports_registered_children_not_separate_creation_plan(self):
        self.registry["children"] = [{"thread_id": None, "state": "planned"}]
        self.save()
        before = self.path.read_bytes()
        command = [sys.executable, "-B", str(Path(co.__file__)), "task-map", "--registry", str(self.path)]
        run = subprocess.run(command, capture_output=True, text=True, cwd=self.root)
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout)
        self.assertEqual(result["tasks"]["module"]["thread_id"], "actual-module")
        self.assertEqual(result["tasks"]["module"]["workspaces"], self.registry["tasks"]["module"]["workspaces"])
        self.assertEqual(result["registry_file_sha256"], hashlib.sha256(before).hexdigest())
        self.assertFalse(result["live_state_verified"])
        self.assertNotIn("children", result)
        self.assertEqual(before, self.path.read_bytes())

    def test_missing_binding_or_title_does_not_export_a_ready_summary(self):
        for field in ("thread_id", "title"):
            with self.subTest(field=field):
                original = self.registry["tasks"]["module"][field]
                self.registry["tasks"]["module"][field] = None
                self.save()
                before = self.path.read_bytes()
                with self.assertRaisesRegex(ValueError, "创建回执"):
                    co.task_map(self.path)
                self.assertEqual(before, self.path.read_bytes())
                self.registry["tasks"]["module"][field] = original

    def test_duplicate_chat_identity_is_not_two_independent_modules(self):
        self.registry["tasks"]["other"] = copy.deepcopy(self.registry["tasks"]["module"])
        self.save()
        with self.assertRaisesRegex(ValueError, "同一聊天"):
            co.task_map(self.path)

    def test_child_coordinator_can_be_worker_in_parent_and_main_in_own_group(self):
        self.save()
        child = co.task_map(self.path)
        self.registry = {"schema_version": 1, "main_task_id": "main", "tasks": {
            "main": {"role": "main", "thread_id": "actual-top", "title": "需求｜双端总协调"},
            "ios": {"role": "worker", "thread_id": "actual-ios", "title": "需求｜iOS 总协调"}}}
        self.save()
        parent = co.task_map(self.path)
        self.assertEqual(child["tasks"]["ios"]["thread_id"], parent["tasks"]["ios"]["thread_id"])
        self.assertEqual(parent["tasks"]["main"]["workspaces"], [])


if __name__ == "__main__":
    unittest.main()
