#!/usr/bin/env python3
"""执行资料核验、已有候选分支安全切换及已授权脚本串行运行；不自动集成或通知。"""

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import re

import coordination as co


def file_proof(path):
    co.require(path.is_absolute() and path.resolve() == path and not path.is_symlink(), "须使用规范绝对文件路径")
    co.read_json(path)
    return {"path": str(path), "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def git_context(repo):
    co.require(repo.is_absolute() and repo.resolve() == repo, "须使用仓库根目录的规范绝对路径")
    environment = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    # 拒绝把操作重定向到其他仓库/索引的环境变量，始终使用显式工作区。
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE"):
        co.require(not environment.get(key), "暂存核验不接受重定向环境变量：" + key)

    def git(*args, allowed=(0,)):
        result = subprocess.run(["git", "--no-optional-locks", "-C", str(repo), *args], env=environment, capture_output=True)
        co.require(result.returncode in allowed, "Git操作失败，须核对现场，不自动回滚：" + os.fsdecode(result.stderr))
        return result.stdout

    co.require(os.fsdecode(git("rev-parse", "--show-toplevel")).removesuffix("\n") == str(repo), "请传入真实仓库根目录")
    return git


def staged_paths(repo, expected):
    co.require(isinstance(expected, list) and all(isinstance(p, str) and p and "\0" not in p and
               not p.startswith("/") and str(PurePosixPath(p)) == p and ".." not in PurePosixPath(p).parts
               for p in expected) and len(set(expected)) == len(expected), "预期路径须为不重复的仓库相对原始路径数组")
    git = git_context(repo)
    index = Path(os.fsdecode(git("rev-parse", "--path-format=absolute", "--git-path", "index")).removesuffix("\n"))
    before = index.read_bytes() if index.exists() else b""
    # -z 避免 core.quotepath、空格、制表符或文件名中的换行改变路径身份；重命名按删除+新增核对。
    raw = git("diff", "--cached", "--name-only", "--no-renames", "-z", "--")
    actual = [os.fsdecode(part) for part in raw.split(b"\0") if part]
    unmerged = bool(git("ls-files", "--unmerged", "-z"))
    after = index.read_bytes() if index.exists() else b""
    co.require(before == after, "核验期间索引已变化，请重新读取；未修改索引")
    missing, extra = sorted(set(expected) - set(actual)), sorted(set(actual) - set(expected))
    return {"repo": str(repo), "matches": not missing and not extra and not unmerged,
            "actual_paths": actual, "missing_paths": missing, "extra_paths": extra,
            "unmerged": unmerged, "index_sha256": hashlib.sha256(after).hexdigest(),
            "limitations": "仅核对暂存路径与索引稳定性；仍须审查实际diff，执行写操作前重新核验"}


def candidate_ref(git, branch):
    co.require(isinstance(branch, str) and branch, "须明确候选本地分支")
    co.require(not branch.startswith("refs/") or branch.startswith("refs/heads/"), "候选须为本地分支，不能是远端或标签引用")
    ref = branch if branch.startswith("refs/heads/") else "refs/heads/" + branch
    git("check-ref-format", ref)
    git("check-ref-format", "--branch", ref[len("refs/heads/"):])
    return ref


def full_sha(value):
    co.require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value), "须提供已核实的完整提交SHA")
    return value


def git_operations(git):
    names = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer")
    return [name for name in names if Path(os.fsdecode(git("rev-parse", "--path-format=absolute", "--git-path", name)).rstrip("\n")).exists()]


def candidate_status(repo, branch, expected_head, contains=()):
    git = git_context(repo)
    ref = candidate_ref(git, branch)
    full_sha(expected_head)
    for sha in contains:
        full_sha(sha)
    actual = os.fsdecode(git("symbolic-ref", "--quiet", "HEAD", allowed=(0, 1))).strip()
    head = os.fsdecode(git("rev-parse", "--verify", "HEAD^{commit}")).strip()
    ref_head = os.fsdecode(git("rev-parse", "--verify", ref + "^{commit}")).strip()
    operations = git_operations(git)
    reasons = []
    if actual != ref:
        reasons.append("HEAD处于detached状态" if not actual else "当前分支不是登记候选分支")
    if head != expected_head or ref_head != expected_head:
        reasons.append("HEAD、候选分支引用与预期SHA不一致")
    if operations:
        reasons.append("存在未完成Git操作：" + ",".join(operations))
    if git("status", "--porcelain=v1", "--untracked-files=all", "-z"):
        reasons.append("候选工作区或暂存区不干净")
    missing = [sha for sha in contains if os.fsdecode(git("merge-base", sha, head, allowed=(0, 1))).strip() != sha]
    if missing:
        reasons.append("候选未累积已核实的前序提交")
    return {"can_integrate": not reasons, "repo": str(repo), "candidate_ref": ref,
            "actual_branch": actual or None, "actual_head": head, "ref_head": ref_head,
            "expected_head": expected_head, "missing_ancestors": missing, "in_progress": operations, "reasons": reasons}


def switch_candidate(repo, branch, expected_head, contains=()):
    git = git_context(repo)
    ref = candidate_ref(git, branch)
    full_sha(expected_head)
    for sha in contains:
        full_sha(sha)
    lock = Path(os.fsdecode(git("rev-parse", "--path-format=absolute", "--git-path", "codex-candidate.lock")).rstrip("\n"))
    co.require(not lock.is_symlink(), "候选操作锁不能是软链接")
    with lock.open("a+b") as stream:
        co.fcntl.flock(stream, co.fcntl.LOCK_EX)
        co.require(not git_operations(git), "存在未完成Git操作，禁止切换")
        co.require(git("symbolic-ref", "--quiet", "HEAD", allowed=(0, 1)).strip(), "当前已detached；先保全并核对现存提交，不自动切走")
        co.require(not git("status", "--porcelain=v1", "--untracked-files=all", "-z"), "工作区或暂存区不干净，禁止切换")
        co.require(os.fsdecode(git("rev-parse", "--verify", ref + "^{commit}")).strip() == expected_head, "候选引用已变化，禁止按旧SHA切换")
        # 前序提交缺失时在切换前停止，成功后仍重核，覆盖外部 Git 并发变化。
        for sha in contains:
            co.require(os.fsdecode(git("merge-base", sha, expected_head, allowed=(0, 1))).strip() == sha,
                       "候选未累积已核实的前序提交，禁止切换")
        # 完整ref仅用于身份核对；switch使用已有短分支名，避免checkout完整ref进入detached HEAD。
        # 不创建/重置分支、不强制切换，也不覆盖忽略文件或绕过其他worktree占用。
        command = ["switch", "--no-guess", "--no-overwrite-ignore", "--", ref[len("refs/heads/"):]]
        git(*command)
        result = candidate_status(repo, ref, expected_head, contains)
        co.require(result["can_integrate"], "切换后状态不符，保留现场核对：" + ";".join(result["reasons"]))
        return {**result, "command": ["git", "-C", str(repo), *command]}


def run_scripts(plan, report):
    """预检整个脚本序列；失败不运行下一步，中断后的同一记录不自动重放。"""
    co.require(isinstance(plan, dict) and set(plan) == {"cwd", "steps"}, "脚本计划仅含cwd和steps")
    cwd = Path(plan["cwd"])
    co.require(cwd.is_absolute() and cwd.resolve() == cwd and cwd.is_dir(), "cwd须为已存在的规范绝对目录")
    co.require(report.is_absolute() and report.resolve() == report and report.parent.is_dir(), "报告须为规范绝对路径，父目录须已存在")
    steps = plan["steps"]
    co.require(isinstance(steps, list) and steps, "须提供非空脚本序列")
    prepared = []
    for step in steps:
        co.require(isinstance(step, dict) and set(step) <= {"script", "interpreter", "args"} and "script" in step, "脚本步骤字段无效")
        script = Path(step["script"])
        co.require(script.is_absolute() and script.resolve() == script and script.is_file() and not script.is_symlink(), "所有脚本须为已存在的规范绝对文件路径")
        interpreter = step.get("interpreter", "python")
        co.require(interpreter in ("python", "bash"), "解释器仅支持python或bash")
        args = step.get("args", [])
        co.require(isinstance(args, list) and all(isinstance(arg, str) and "\0" not in arg for arg in args), "脚本args须为原样字符串数组，不解析shell代码")
        prepared.append({"script": str(script), "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
                         "command": [sys.executable if interpreter == "python" else "/bin/bash", str(script), *args]})
    intent = report.with_name(report.name + ".intent.json")
    records = [report, intent] + [report.with_name(report.name + ".step-" + str(i) + ".json") for i in range(1, len(prepared) + 1)]
    co.require(not any(path.exists() or path.is_symlink() for path in records), "执行记录已存在；先核对实际结果，禁止直接重跑脚本")
    co.publish(intent, co.sealed({"cwd": str(cwd), "steps": prepared}))
    results, status, reason = [], "passed", None
    for index, step in enumerate(prepared, 1):
        if hashlib.sha256(Path(step["script"]).read_bytes()).hexdigest() != step["script_sha256"]:
            status, reason = "blocked", "脚本在预检后变化，后续步骤未执行"
            break
        result = subprocess.run(step["command"], cwd=cwd, capture_output=True)
        receipt = {"step": index, "command": step["command"], "exit_code": result.returncode,
                   "stdout": result.stdout.decode("utf-8", errors="replace"), "stderr": result.stderr.decode("utf-8", errors="replace")}
        co.publish(report.with_name(report.name + ".step-" + str(index) + ".json"), co.sealed(receipt))
        results.append(receipt)
        if result.returncode != 0:
            status, reason = "failed", "前一步失败，后续脚本未执行"
            break
    summary = {"status": status, "reason": reason, "planned_steps": len(prepared), "executed_steps": len(results), "results": results}
    co.publish(report, co.sealed(summary))
    return summary


def scope_identity(config):
    return {key: value for key, value in config.items() if key != "scope_freeze"}


def integration_identity(document):
    co.require(isinstance(document, dict), "集成记录须为对象")
    readiness = document.get("readiness", {})
    co.require(isinstance(readiness, dict), "readiness须为对象")
    co.require(isinstance(document.get("repositories", []), list) and all(isinstance(repo, dict) for repo in document.get("repositories", [])), "repositories须为对象数组")
    return {"batch_id": document.get("batch_id"),
            "repositories": [{key: repo.get(key) for key in ("repo_id", "target_branch", "startup_sha", "integration_worktree")}
                             for repo in document.get("repositories", [])],
            "required_tasks": readiness.get("required_tasks"),
            "final_deliveries": readiness.get("final_deliveries"),
            "all_tasks_complete": readiness.get("all_tasks_complete"),
            "shared_releases_frozen": readiness.get("shared_releases_frozen"),
            "open_blockers": readiness.get("open_blockers")}


def validate_inputs(config, events, integration):
    identity = integration_identity(integration)
    co.require(identity["batch_id"] == config["batch_id"], "集成记录批次不符")
    required = identity["required_tasks"]
    participants = set(config["actors"]) - {config["main"]}
    co.require(isinstance(required, list) and required and all(isinstance(x, str) for x in required) and
               len(required) == len(set(required)) and set(required) == participants,
               "required_tasks须完整覆盖本批全部直接参与者；调整范围须先明确修改批次")
    co.require(identity["all_tasks_complete"] is True and identity["open_blockers"] == [], "终版未齐备或仍有阻塞，不可冻结集成")
    if any(config["actors"][actor]["role"] == "shared" for actor in required):
        co.require(identity["shared_releases_frozen"] is True, "实际共享交付尚未封版")
    deliveries = identity["final_deliveries"]
    co.require(isinstance(deliveries, list) and len(deliveries) == len(required), "终版交付须逐参与者登记且不得重复")
    proofs, covered = [], set()
    for item in deliveries:
        co.require(isinstance(item, dict), "终版交付须为对象")
        actor, message_id = item.get("actor"), item.get("message_id")
        co.require(isinstance(actor, str) and actor in required and actor not in covered, "终版参与者缺失、重复或未登记")
        co.require(isinstance(message_id, str) and message_id in events, "终版消息不存在")
        event = events[message_id]
        # 模块的 CONSUMED 只证明公共接入；共享任务仍可按原协议用封版 RELEASE 交付。
        allowed = ("RESULT", "RELEASE") if config["actors"][actor]["role"] == "shared" else ("RESULT",)
        co.require(event["kind"] in allowed and event["sender"] == actor and event["recipient"] == config["main"], "须引用本人终版RESULT或共享封版RELEASE，不能用ACK或CONSUMED替代")
        co.require(event["revision"] == co.current_revision(events, event["entity_id"]), "终版交付已属旧修订")
        co.require(not any(other["payload"].get("supersedes_result") == message_id for other in events.values()), "终版交付已被更正结果取代")
        if event["kind"] == "RESULT" or "verification" in event["payload"]:
            co.validate_verification(event["payload"].get("verification"), require_passed=True)
        artifacts = event["payload"].get("artifacts")
        co.require(isinstance(artifacts, list) and artifacts, "终版RESULT须附实际清单/证据artifacts")
        for artifact in artifacts:
            co.require(isinstance(artifact, dict) and isinstance(artifact.get("path"), str), "交付产物格式无效")
            path = Path(artifact["path"])
            co.require(path.is_absolute() and path.resolve() == path and not path.is_symlink() and path.is_file(), "交付产物缺失或路径不规范")
            co.require(hashlib.sha256(path.read_bytes()).hexdigest() == artifact.get("file_sha256"), "交付产物哈希不符")
        covered.add(actor)
        proofs.append({"actor": actor, "message_id": message_id, "message_sha256": hashlib.sha256(co.canonical(event)).hexdigest()})
    return proofs


def replace_config(path, value):
    """控制资料可更新；原子替换前保存的不可变冻结记录负责中断恢复。"""
    descriptor, temporary = tempfile.mkstemp(prefix=".pending-freeze-", dir=path.parent)
    try:
        os.fchmod(descriptor, path.stat().st_mode & 0o777)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(co.canonical(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def freeze_integration(root, actor, freeze_id, integration_path, inputs_path, supersedes=None):
    co.identifier(freeze_id)
    with co.locked(root):
        config = co.validate_config(co.read_json(root / "batch.json"))
        co.require(not (root / "freezes").is_symlink(), "冻结目录不能是软链接")
        co.require(isinstance(config.get("scope_freeze", {}), dict), "scope_freeze须为对象")
        co.require(actor == config["main"], "仅本组协调者可登记集成冻结")
        events = co.load_events(root, config)
        integration_proof, inputs_proof = file_proof(integration_path), file_proof(inputs_path)
        integration = co.read_json(integration_path)
        proofs = validate_inputs(config, events, integration)
        path = root / "freezes" / (freeze_id + ".json")
        previous = config.get("scope_freeze", {}).get("snapshot_path")
        co.require(previous in (None, str(path), supersedes), "已有冻结；新快照须以--supersedes明确承接旧snapshot_path")
        predecessor_proof = None
        if supersedes:
            predecessor = Path(supersedes)
            co.require(predecessor != path, "新冻结不能承接自己")
            predecessor_proof = file_proof(predecessor)
            if previous == supersedes:
                co.require(predecessor_proof["file_sha256"] == config.get("scope_freeze", {}).get("snapshot_sha256"), "当前旧快照与指针哈希不符，先核对真实证据")
            if predecessor.parent == root / "freezes":
                co.require(co.read_sealed(predecessor).get("batch_id") == config["batch_id"], "须承接本批已存在的工具快照")
            else:
                co.require(previous == supersedes and predecessor_proof["file_sha256"] == config.get("scope_freeze", {}).get("snapshot_sha256"),
                           "旧手工快照须与当前指针及已记录文件哈希一致，不能隐式补造历史")
        data = {"schema_version": 1, "batch_id": config["batch_id"], "freeze_id": freeze_id,
                "scope": scope_identity(config), "integration": {"path": str(integration_path), "identity": integration_identity(integration)},
                "inputs": inputs_proof, "deliveries": proofs, "supersedes_snapshot": supersedes,
                "supersedes_proof": predecessor_proof}
        duplicate = path.exists()
        if duplicate:
            old = co.read_sealed(path)
            co.require({k: v for k, v in old.items() if k != "frozen_at"} == data, "同一freeze_id内容不同；保留旧快照，用新ID并明确承接")
            data = old
        else:
            data["frozen_at"] = datetime.now(timezone.utc).isoformat()
            co.publish(path, co.sealed(data))
        # 快照先落盘，之后才更新指针。若此处中断，recover显示孤立冻结；同参数重放补指针，不重跑Git。
        co.require(file_proof(integration_path) == integration_proof and file_proof(inputs_path) == inputs_proof, "冻结期间输入变化，请核对孤立快照后用新ID重试")
        co.require(co.read_json(root / "batch.json") == config, "冻结期间批次变化，请恢复核对")
        updated = copy.deepcopy(config)
        updated.setdefault("scope_freeze", {}).update(status="已冻结", frozen_at=data["frozen_at"], snapshot_path=str(path),
            snapshot_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), supersedes_snapshot=supersedes)
        replace_config(root / "batch.json", updated)
        co.require(co.read_json(root / "batch.json") == updated, "冻结状态读回不符")
        result = integration_status(root, updated, events)
        co.require(result["can_integrate"], "冻结仍待核对：" + ";".join(result["reasons"]))
        return {**result, "duplicate": duplicate}


def integration_status(root, config, events):
    """恢复扫描也调用此入口；漏指针、旧默认值与陈旧/变动输入均不能当作已冻结。"""
    result = {"can_integrate": False, "registered": False, "reasons": []}
    result["registered"] = bool(config.get("scope_freeze") or (root / "integration.json").exists() or (root / "freezes").exists())
    try:
        freeze = config.get("scope_freeze") or {}
        co.require(isinstance(freeze, dict), "scope_freeze须为对象")
        co.require(not (root / "freezes").is_symlink(), "冻结目录不能是软链接")
        snapshots = list((root / "freezes").glob("*.json"))
        integration_path = root / "integration.json"
        result["registered"] = bool(snapshots or freeze.get("snapshot_path") or
                                    freeze.get("status") == "已冻结" or integration_path.exists())
        legacy = co.read_json(integration_path) if integration_path.exists() else {}
        co.require(isinstance(legacy, dict) and isinstance(legacy.get("readiness", {}), dict), "集成记录或readiness格式无效")
        signalled = bool(snapshots or freeze.get("snapshot_path") or freeze.get("status") == "已冻结" or
                         legacy.get("frozen_inputs_path") or legacy.get("readiness", {}).get("integration_started_at") or
                         legacy.get("readiness", {}).get("all_tasks_complete"))
        result["registered"] = signalled
        co.require(signalled, "尚未登记集成冻结")
        co.require(freeze.get("status") == "已冻结" and freeze.get("snapshot_path"), "已有冻结输入或集成动作，但scope_freeze未登记为已冻结；禁止开始集成")
        path = Path(freeze["snapshot_path"])
        co.require(path.parent == root / "freezes", "旧手工冻结尚未登记工具快照；保留原资料，核对后显式freeze-integration")
        co.require(hashlib.sha256(path.read_bytes()).hexdigest() == freeze.get("snapshot_sha256"), "冻结快照文件哈希不符")
        data = co.read_sealed(path)
        co.require(data["batch_id"] == config["batch_id"] and data["scope"] == scope_identity(config), "冻结后批次身份或范围已变，须明确新冻结")
        co.require(data["frozen_at"] == freeze.get("frozen_at") and data["supersedes_snapshot"] == freeze.get("supersedes_snapshot"), "冻结指针元数据不一致")
        history, current = set(), path
        while current:
            co.require(current.parent == root / "freezes" and str(current) not in history, "冻结承接链越界或成环")
            history.add(str(current))
            record = co.read_sealed(current)
            previous = record.get("supersedes_snapshot")
            if previous:
                co.require(file_proof(Path(previous)) == record.get("supersedes_proof"), "原冻结快照哈希不符")
            current = Path(previous) if previous and Path(previous).parent == root / "freezes" else None
        co.require(all(str(p) in history for p in snapshots), "有冻结快照未登记指针；先恢复原freeze-integration，不得忽略中断记录")
        integration = co.read_json(Path(data["integration"]["path"]))
        co.require(integration_identity(integration) == data["integration"]["identity"], "集成输入/齐备状态与冻结记录不符")
        co.require(file_proof(Path(data["inputs"]["path"])) == data["inputs"], "冻结输入文件哈希不符")
        co.require(validate_inputs(config, events, integration) == data["deliveries"], "终版消息与冻结记录不符")
        result.update(can_integrate=True, snapshot_path=str(path), snapshot_sha256=freeze["snapshot_sha256"])
    except (ValueError, OSError, KeyError, TypeError) as error:
        result["reasons"].append(str(error))
    return result


def main():
    parser = argparse.ArgumentParser(description="执行资料防护；候选切换及脚本运行只用于已授权的隔离工作区")
    sub = parser.add_subparsers(dest="command", required=True)
    staged = sub.add_parser("check-staged")
    staged.add_argument("--repo", type=co.absolute_path, required=True)
    staged.add_argument("--expected", type=co.absolute_path, required=True, help="仓库相对原始路径的JSON数组")
    for name in ("check-candidate", "switch-candidate"):
        command = sub.add_parser(name)
        command.add_argument("--repo", type=co.absolute_path, required=True)
        command.add_argument("--branch", required=True)
        command.add_argument("--expected-head", required=True)
        command.add_argument("--contains", action="append", default=[])
    scripts = sub.add_parser("run-scripts")
    scripts.add_argument("--plan", type=co.absolute_path, required=True)
    scripts.add_argument("--report", type=co.absolute_path, required=True)
    for name in ("freeze-integration", "check-integration"):
        command = sub.add_parser(name)
        command.add_argument("--root", type=co.absolute_path, required=True)
        command.add_argument("--actor", required=True)
        if name == "freeze-integration":
            command.add_argument("--freeze-id", required=True)
            command.add_argument("--integration", type=co.absolute_path, required=True)
            command.add_argument("--inputs", type=co.absolute_path, required=True)
            command.add_argument("--supersedes", type=co.absolute_path)
    args = parser.parse_args()
    try:
        if args.command == "check-staged":
            result = staged_paths(args.repo, co.read_json(args.expected))
            passed = result["matches"]
        elif args.command == "check-candidate":
            result = candidate_status(args.repo, args.branch, args.expected_head, args.contains)
            passed = result["can_integrate"]
        elif args.command == "switch-candidate":
            result = switch_candidate(args.repo, args.branch, args.expected_head, args.contains)
            passed = result["can_integrate"]
        elif args.command == "run-scripts":
            result = run_scripts(co.read_json(args.plan), args.report)
            passed = result["status"] == "passed"
        elif args.command == "freeze-integration":
            result = freeze_integration(args.root, args.actor, args.freeze_id, args.integration, args.inputs,
                                        str(args.supersedes) if args.supersedes else None)
            passed = result["can_integrate"]
        else:
            with co.locked(args.root):
                config = co.validate_config(co.read_json(args.root / "batch.json"))
                co.require(args.actor == config["main"], "仅本组协调者核验集成放行")
                result = integration_status(args.root, config, co.load_events(args.root, config))
            passed = result["can_integrate"]
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if passed else 2
    except (ValueError, OSError, KeyError, TypeError) as error:
        print("执行防护失败：" + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
