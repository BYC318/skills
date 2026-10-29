"""候选身份、绝对路径、初始化冲突及失败停止；仅使用外部隔离资料/Git夹具。"""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import coordination as co
import execution_guards as guard


class CandidateSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ["COORDINATION_TEST_ROOT"])
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name).resolve()
        self.config = {"schema_version": 1, "batch_id": "SAFETY", "main": "main", "authorization": "仅外部合成夹具，不通知真实聊天",
                       "actors": {"main": {"role": "main"}, "A": {"role": "worker"}}}
        self.scripts = Path(__file__).parent

    def cli(self, program, *args, cwd=None):
        return subprocess.run([sys.executable, "-B", str(self.scripts / program), *map(str, args)],
                              cwd=cwd or self.folder, capture_output=True, text=True)

    def git(self, *args):
        environment = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        result = subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=协作夹具", "-c", "user.email=fixture@example.invalid",
                                 "-c", "commit.gpgsign=false", *args], env=environment, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        return result.stdout.decode().strip()

    def commit(self, path, content):
        (self.repo / path).write_text(content)
        self.git("add", "--", path)
        self.git("commit", "-m", "test: 更新隔离夹具")
        return self.git("rev-parse", "HEAD")

    def make_repo(self):
        self.repo = self.folder / "中文 工作区"
        self.repo.mkdir()
        self.git("init", "-b", "base")
        self.git("config", "core.hooksPath", str(self.folder / "no-hooks"))
        self.base = self.commit("base.txt", "起点")
        self.git("switch", "-c", "candidate")
        self.head = self.commit("shared.txt", "已纳入公共提交")
        self.git("switch", "base")

    def test_full_ref_switch_attaches_existing_local_branch(self):
        self.make_repo()
        result = guard.switch_candidate(self.repo, "refs/heads/candidate", self.head)
        self.assertTrue(result["can_integrate"])
        self.assertEqual(self.git("symbolic-ref", "HEAD"), "refs/heads/candidate")
        self.assertEqual(result["command"][-1], "candidate")
        self.assertTrue(guard.candidate_status(self.repo, "candidate", self.head, [self.base])["can_integrate"])

    def test_switch_cli_accepts_predecessors_and_keeps_branch_attached(self):
        self.make_repo()
        result = self.cli("execution_guards.py", "switch-candidate", "--repo", self.repo,
                          "--branch", "refs/heads/candidate", "--expected-head", self.head, "--contains", self.base)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["can_integrate"])
        self.assertEqual(self.git("symbolic-ref", "HEAD"), "refs/heads/candidate")

    def test_missing_predecessor_is_rejected_before_switching_or_changing_index(self):
        self.make_repo()
        sibling = self.commit("other.txt", "目标后来独立推进")
        before = (self.repo / ".git/index").read_bytes()
        result = self.cli("execution_guards.py", "switch-candidate", "--repo", self.repo,
                          "--branch", "candidate", "--expected-head", self.head, "--contains", sibling)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.git("symbolic-ref", "HEAD"), "refs/heads/base")
        self.assertEqual(before, (self.repo / ".git/index").read_bytes())

    def test_real_checkout_full_ref_detaches_and_guard_rejects_without_repair(self):
        self.make_repo()
        self.git("checkout", "refs/heads/candidate")
        before = (self.repo / ".git/index").read_bytes()
        result = self.cli("execution_guards.py", "check-candidate", "--repo", self.repo, "--branch", "refs/heads/candidate", "--expected-head", self.head)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIsNone(json.loads(result.stdout)["actual_branch"])
        with self.assertRaisesRegex(ValueError, "detached"):
            guard.switch_candidate(self.repo, "candidate", self.head)
        self.assertEqual(before, (self.repo / ".git/index").read_bytes())
        self.assertEqual(self.git("rev-parse", "HEAD"), self.head)

    def test_stale_expected_head_wrong_branch_and_nonlocal_ref_fail(self):
        self.make_repo()
        for branch, sha in (("candidate", self.base), ("refs/tags/candidate", self.head), ("HEAD", self.head)):
            with self.subTest(branch=branch, sha=sha), self.assertRaises(ValueError):
                guard.switch_candidate(self.repo, branch, sha)
        self.assertEqual(self.git("symbolic-ref", "HEAD"), "refs/heads/base")
        self.assertFalse(guard.candidate_status(self.repo, "candidate", self.head)["can_integrate"])

    def test_required_ancestor_detects_missing_accumulated_module(self):
        self.make_repo()
        other = self.commit("module.txt", "独有模块")
        guard.switch_candidate(self.repo, "candidate", self.head)
        status = guard.candidate_status(self.repo, "candidate", self.head, [other])
        self.assertEqual(status["missing_ancestors"], [other])
        self.assertFalse(status["can_integrate"])
        # 实际把模块rebase到公共候选，再快进；检查应保留之前已经纳入的公共提交。
        self.git("branch", "module", other)
        self.git("rebase", "--onto", "candidate", self.base, "module")
        rebased = self.git("rev-parse", "HEAD")
        guard.switch_candidate(self.repo, "candidate", self.head)
        self.git("merge", "--ff-only", "module")
        self.assertTrue(guard.candidate_status(self.repo, "candidate", rebased, [self.head])["can_integrate"])

    def test_dirty_index_and_untracked_files_are_preserved(self):
        self.make_repo()
        (self.repo / "base.txt").write_text("其他工作")
        self.git("add", "base.txt")
        before = (self.repo / ".git/index").read_bytes()
        with self.assertRaisesRegex(ValueError, "不干净"):
            guard.switch_candidate(self.repo, "candidate", self.head)
        self.assertEqual(before, (self.repo / ".git/index").read_bytes())
        self.assertEqual((self.repo / "base.txt").read_text(), "其他工作")
        self.git("restore", "--staged", "--worktree", "base.txt")
        (self.repo / "untracked.txt").write_text("保留")
        with self.assertRaises(ValueError):
            guard.switch_candidate(self.repo, "candidate", self.head)
        self.assertEqual((self.repo / "untracked.txt").read_text(), "保留")

    def test_git_operation_and_other_worktree_occupancy_are_not_bypassed(self):
        self.make_repo()
        operation = self.repo / ".git/MERGE_HEAD"
        operation.write_text(self.head + "\n")
        with self.assertRaisesRegex(ValueError, "未完成Git操作"):
            guard.switch_candidate(self.repo, "candidate", self.head)
        operation.unlink()
        self.git("worktree", "add", str(self.folder / "occupied"), "candidate")
        with self.assertRaises(ValueError):
            guard.switch_candidate(self.repo, "candidate", self.head)
        self.assertEqual(self.git("symbolic-ref", "HEAD"), "refs/heads/base")

    def test_ignored_file_is_not_overwritten(self):
        self.make_repo()
        with (self.repo / ".git/info/exclude").open("a") as stream:
            stream.write("\nshared.txt\n")
        (self.repo / "shared.txt").write_text("已有忽略资料")
        with self.assertRaises(ValueError):
            guard.switch_candidate(self.repo, "candidate", self.head)
        self.assertEqual((self.repo / "shared.txt").read_text(), "已有忽略资料")
        self.assertEqual(self.git("symbolic-ref", "HEAD"), "refs/heads/base")

    def test_all_cli_input_paths_reject_relative_before_reads_or_locks(self):
        root = self.folder / "batch"
        config = self.folder / "config.json"
        config.write_text(json.dumps(self.config))
        cases = [("coordination.py", ["init", "--root", "relative", "--config", str(config)]),
                 ("coordination.py", ["init", "--root", str(root), "--config", "config.json"]),
                 ("coordination.py", ["emit", "--root", str(root), "--sender", "main", "--event", "event.json"]),
                 ("coordination.py", ["begin-action", "--root", str(root), "--actor", "main", "--plan", "plan.json"]),
                 ("coordination.py", ["recover", "--registry", "registry.json", "--actor", "main"]),
                 ("message_operations.py", ["assign", "--root", str(root), "--actor", "main", "--input", "input.json"]),
                 ("execution_guards.py", ["run-scripts", "--plan", "plan.json", "--report", str(self.folder / "report.json")])]
        for program, args in cases:
            with self.subTest(program=program, args=args):
                result = self.cli(program, *args)
                self.assertEqual(result.returncode, 2)
                self.assertIn("绝对路径", result.stderr)
        self.assertFalse(root.exists())

    def test_notification_relative_paths_invoke_zero_commands_and_sends(self):
        source = self.scripts / "notification_dispatch.js"
        program = """const fs=require('fs');const dispatch=new Function(fs.readFileSync(process.argv[1],'utf8')+';return dispatchNotification')();
let execs=0,sends=0;const io={exec:async()=>{execs++;},send:async()=>{sends++;}};
const base={root:'/absolute/batch',scriptPath:'/absolute/coordination.py',sender:'main',messageIds:['M']};
(async()=>{let results=[];for(const patch of [{root:'relative'},{scriptPath:'scripts/co.py'},{retryVerification:'retry.json'}])results.push(await dispatch(io,{...base,...patch}));process.stdout.write(JSON.stringify({execs,sends,results}));})();"""
        result = subprocess.run(["node", "-e", program, str(source)], capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        self.assertEqual((data["execs"], data["sends"]), (0, 0))
        self.assertTrue(all(item["status"] == "blocked" for item in data["results"]))

    def test_initialize_accepts_existing_empty_directory(self):
        root = self.folder / "empty"
        root.mkdir()
        co.initialize(root, self.config)
        self.assertEqual(co.read_json(root / "batch.json"), self.config)
        self.assertTrue((root / "events/A").is_dir())
        self.assertTrue((root / "deliveries").is_dir())

    def test_initialize_rejects_nonempty_existing_batch_and_symlink_unchanged(self):
        root = self.folder / "existing"
        root.mkdir()
        (root / "other.txt").write_text("其他资料")
        with self.assertRaises(FileExistsError): co.initialize(root, self.config)
        self.assertEqual([p.name for p in root.iterdir()], ["other.txt"])
        real = self.folder / "real"
        real.mkdir()
        link = self.folder / "link"
        link.symlink_to(real, target_is_directory=True)
        with self.assertRaises(ValueError): co.initialize(link, self.config)
        self.assertEqual(list(real.iterdir()), [])
        batch = self.folder / "batch"
        co.initialize(batch, self.config)
        before = {str(p): p.read_bytes() for p in batch.rglob('*') if p.is_file()}
        with self.assertRaises(FileExistsError): co.initialize(batch, self.config)
        self.assertEqual(before, {str(p): p.read_bytes() for p in batch.rglob('*') if p.is_file()})

    def test_concurrent_initialize_only_one_writer_succeeds(self):
        root = self.folder / "concurrent"
        root.mkdir()
        def attempt(_):
            try:
                co.initialize(root, self.config)
                return "created"
            except FileExistsError:
                return "preserved"
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(attempt, range(4)))
        self.assertEqual(results.count("created"), 1)
        self.assertEqual(co.read_json(root / "batch.json"), self.config)

    def script(self, name, code):
        p = self.folder / name
        p.write_text(code)
        return p

    def plan(self, *scripts):
        return {"cwd": str(self.folder), "steps": [{"script": str(s)} for s in scripts]}

    def test_script_sequence_prevalidates_all_absolute_paths(self):
        marker = self.folder / "marker"
        script = self.script("first.py", "from pathlib import Path\nPath('marker').write_text('不应执行')\n")
        for bad in ("missing.py", str(self.folder / "missing.py")):
            plan = self.plan(script)
            plan["steps"].append({"script": bad})
            with self.assertRaises(ValueError): guard.run_scripts(plan, self.folder / "report.json")
        plan = self.plan(script)
        plan["cwd"] = "."
        with self.assertRaises(ValueError): guard.run_scripts(plan, self.folder / "report.json")
        self.assertFalse(marker.exists())
        self.assertFalse((self.folder / "report.json.intent.json").exists())

    def test_script_failure_stops_remaining_steps_and_replay_is_rejected(self):
        failed = self.script("realign.py", "import sys\nprint('合成失败')\nsys.exit(7)\n")
        verify = self.script("verify.py", "from pathlib import Path\nPath('should-not-run').write_text('不应验证旧候选')\n")
        plan = self.folder / "plan.json"
        plan.write_text(json.dumps(self.plan(failed, verify)))
        report = self.folder / "result.json"
        result = self.cli("execution_guards.py", "run-scripts", "--plan", plan, "--report", report)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["results"][0]["exit_code"], 7)
        self.assertFalse((self.folder / "should-not-run").exists())
        with self.assertRaises(ValueError): guard.run_scripts(self.plan(failed, verify), report)
        self.assertEqual(co.read_sealed(report)["executed_steps"], 1)

    def test_script_sequence_uses_explicit_cwd_and_literal_arguments(self):
        script = self.script("中文 脚本.py", "import os,sys,json\nprint(json.dumps([os.getcwd(),sys.argv[1:]],ensure_ascii=False))\n")
        plan = self.plan(script, script)
        literal = "空格 ' $(不会执行) `literal`"
        for step in plan["steps"]: step["args"] = [literal]
        result = guard.run_scripts(plan, self.folder / "success.json")
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["executed_steps"], 2)
        self.assertEqual(json.loads(result["results"][0]["stdout"]), [str(self.folder), [literal]])

    def test_existing_step_record_blocks_before_any_script_runs(self):
        script = self.script("step.py", "from pathlib import Path\nPath('marker').write_text('不应运行')\n")
        report = self.folder / "collision.json"
        step = report.with_name(report.name + ".step-1.json")
        step.write_text("已有资料")
        with self.assertRaises(ValueError): guard.run_scripts(self.plan(script), report)
        self.assertEqual(step.read_text(), "已有资料")
        self.assertFalse((self.folder / "marker").exists())
        self.assertFalse(report.with_name(report.name + ".intent.json").exists())

    def test_real_runner_kill_keeps_intent_and_never_blindly_replays(self):
        script = self.script("interrupt.py", "import os,signal\nfrom pathlib import Path\nf=Path('executed').open('w');f.write('一次');f.flush();os.fsync(f.fileno());f.close()\nos.kill(os.getppid(),signal.SIGKILL)\n")
        plan = self.folder / "crash-plan.json"
        plan.write_text(json.dumps(self.plan(script)))
        report = self.folder / "crash-report.json"
        result = self.cli("execution_guards.py", "run-scripts", "--plan", plan, "--report", report)
        self.assertEqual(result.returncode, -9, result.stderr)
        self.assertTrue(report.with_name(report.name + ".intent.json").exists())
        self.assertFalse(report.exists())
        replay = self.cli("execution_guards.py", "run-scripts", "--plan", plan, "--report", report)
        self.assertEqual(replay.returncode, 2)
        self.assertIn("禁止直接重跑", replay.stderr)
        self.assertEqual((self.folder / "executed").read_text(), "一次")


if __name__ == "__main__":
    unittest.main()
