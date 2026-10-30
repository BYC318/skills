"""在全新外部目录模拟请求、两次修订、接入后进程被杀及恢复；不操作真实 Codex 任务。"""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

import coordination as co


def simulate(output):
    co.require(output.is_absolute(), "验证产物目录须为绝对路径")
    output.mkdir(parents=True, exist_ok=False)
    root = output / "coordination"
    program = Path(__file__).with_name("coordination.py").resolve()
    config = {"schema_version": 1, "batch_id": "SIM-CAPABILITY-RECOVERY", "main": "main", "authorization": "仅合成消息和外部Git夹具验证，不创建真实聊天，不操作应用源码", "actors": {"main": {"role": "main"}, "shared": {"role": "shared"}, "A": {"role": "worker"}}}
    co.initialize(root, config)

    def send(identity, sender="A", recipient="main", kind="REQUEST", revision=1, refs=None, payload=None, entity="CAPABILITY"):
        event = {"batch_id": config["batch_id"], "id": identity, "sender": sender, "recipient": recipient, "kind": kind, "entity_id": entity, "revision": revision, "created_at": "2000-01-01T00:00:00+00:00", "refs": refs or [], "payload": payload or {"description": "模块请求共享能力"}}
        co.emit(root, sender, event)
        return event

    def acknowledge(event):
        return send("ACK-" + event["id"], event["recipient"], event["sender"], "ACK", event["revision"], [event["id"]], entity=event["entity_id"])

    def snapshot(name, actor="main", registry=None):
        # 每次用新进程恢复，只允许从磁盘读取，排除 Python/聊天内存替我们保留请求。
        scope = ["--registry", str(registry)] if registry else ["--root", str(root)]
        result = subprocess.run([sys.executable, str(program), "recover", *scope, "--actor", actor], check=True, capture_output=True, text=True)
        report = json.loads(result.stdout)
        (output / (name + ".json")).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (output / (name + ".md")).write_text(co.recovery_markdown(report), encoding="utf-8")
        return report

    request = send("REQ-CAPABILITY-1")
    before = snapshot("01-请求已落盘但尚未确认")
    assert len(before["open_requests"]) == 1 and len(before["pending_messages"]) == 1
    acknowledge(request)
    assignment = send("ASSIGN-CAPABILITY-1", "main", "shared", "ASSIGN", refs=[request["id"]], payload={"consumers": ["A"], "description": "开发共享能力"})
    acknowledge(assignment)
    request_ids = [request["id"]]
    layout_ids = []
    for revision, correction in ((2, "调整输出格式"), (3, "增加边界处理，仍使用共享能力")):
        change = send("REQ-CHANGE-" + str(revision), revision=revision - 1, payload={"description": correction, "proposed_revision": revision, "authorization_source": "合成用户纠正"})
        request_ids.append(change["id"])
        acknowledge(change)
        assignment = send("ASSIGN-CAPABILITY-" + str(revision), "main", "shared", "ASSIGN", revision, [change["id"], request["id"]], {"consumers": ["A"], "description": correction})
        acknowledge(assignment)
        unrelated = send("ASSIGN-LAYOUT-" + str(revision), "main", "A", "ASSIGN", revision, payload={"description": "另行调整模块行为"}, entity="MODULE-CHANGE")
        layout_ids.append(unrelated["id"])
        acknowledge(unrelated)
    cancelled_layout = send("CANCEL-LAYOUT", "main", "A", "INVALIDATED", 4, layout_ids, {"recovery": {"resolution": "cancelled", "consumer": "A", "request_ids": layout_ids, "reason": "合成用户取消独立模块调整，保留共享能力需求"}}, entity="MODULE-CHANGE")
    acknowledge(cancelled_layout)
    after_changes = snapshot("02-中断并多次调整后恢复")
    capability = after_changes["open_requests"][0]
    assert len(after_changes["open_requests"]) == 1 and capability["revision"] == 3
    assert set(capability["request_ids"]) == set(request_ids)
    next_root = output / "next-batch"
    co.initialize(next_root, {**config, "batch_id": "SIM-NEXT"})
    registry_path = output / "长期任务目录.json"
    registry_path.write_text(json.dumps({"schema_version": 1, "tasks": config["actors"], "batches": [{"batch_id": config["batch_id"], "coordination_root": str(root), "status": "已完成"}, {"batch_id": "SIM-NEXT", "coordination_root": str(next_root)}]}, ensure_ascii=False, indent=2), encoding="utf-8")
    project_report = snapshot("02b-跨批扫描仍发现旧批依赖请求", registry=registry_path)
    assert project_report["scan_complete"] and len(project_report["open_requests"]) == 1
    assert project_report["open_requests"][0]["batch_id"] == config["batch_id"]

    repository = output / "shared-source"
    repository.mkdir()
    environment = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    options = ["-c", "user.name=恢复模拟", "-c", "user.email=recovery@example.invalid", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=" + str(output / "no-hooks")]

    def git(directory, *arguments):
        return subprocess.run(["git", "-C", str(directory), *options, *arguments], env=environment, check=True, capture_output=True, text=True).stdout.strip()

    git(repository, "init", "-b", "shared")
    (repository / "base.txt").write_text("合成共享基线\n", encoding="utf-8")
    git(repository, "add", "--", "base.txt")
    git(repository, "commit", "-m", "chore: 合成恢复基线")
    baseline = git(repository, "rev-parse", "HEAD")
    expected = "共享能力：修订3；输出格式已调整；支持边界处理\n"
    (repository / "shared-capability.txt").write_text(expected, encoding="utf-8")
    git(repository, "add", "--", "shared-capability.txt")
    git(repository, "commit", "-m", "feat(shared): 合成共享能力")
    source = git(repository, "rev-parse", "HEAD")
    worktree = output / "consumer-A"
    git(repository, "worktree", "add", "-b", "consumer-a", str(worktree), baseline)
    release = send("RELEASE-3", "shared", "main", "RELEASE", 3, [assignment["id"]], {"description": "共享能力修订3", "source_sha": source})
    acknowledge(release)
    ready = send("READY-3", "main", "A", "READY", 3, [release["id"]], {"source_sha": source})
    acknowledge(ready)
    plan = {"actor": "A", "entity_id": "CAPABILITY", "revision": 3, "operation": "cherry_pick", "repo_id": "fixture-repo", "worktree": str(worktree), "source_sha": source}
    plan_path = output / "接入意图.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    # 只杀掉这个合成子进程：Git 已完成而完成回执尚未落盘，复现最容易重复接入的窗口。
    child = """import json,os,signal,subprocess,sys
sys.path.insert(0,sys.argv[1])
import coordination as co
from pathlib import Path
plan=json.loads(Path(sys.argv[3]).read_text())
start=co.begin_action(Path(sys.argv[2]),'A',plan)
assert start['can_execute']
subprocess.run(['git','-C',plan['worktree'],*json.loads(sys.argv[4]),'cherry-pick','-x',plan['source_sha']],check=True,capture_output=True)
os.kill(os.getpid(),signal.SIGKILL)
"""
    interrupted = subprocess.run([sys.executable, "-c", child, str(program.parent), str(root), str(plan_path), json.dumps(options)], env=environment, capture_output=True, text=True)
    assert interrupted.returncode == -signal.SIGKILL, interrupted.stderr
    after_kill = snapshot("03-接入后被强制中断再恢复", "A")
    assert len(after_kill["actions_pending_verification"]) == 1
    assert not after_kill["actions_pending_verification"][0]["can_execute"]
    assert len(after_kill["open_requests"]) == 1
    repeat_start = co.begin_action(root, "A", plan)
    assert not repeat_start["can_execute"]
    assert co.emit(root, "main", ready)["duplicate"]
    local_sha = git(worktree, "rev-parse", "HEAD")
    imported = git(worktree, "log", "--format=%H", "--fixed-strings", "--grep=(cherry picked from commit " + source + ")").splitlines()
    assert len(imported) == 1 and imported[0] == local_sha
    assert (worktree / "shared-capability.txt").read_text(encoding="utf-8") == expected
    assert git(worktree, "status", "--porcelain") == ""
    proof = {"source_sha": source, "local_sha": local_sha, "import_count": len(imported), "content_matches_revision_3": True, "worktree_clean": True, "interrupted_returncode": interrupted.returncode}
    proof_path = output / "Git实际核验.json"
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
    result = {"local_sha": local_sha, "verification": {"status": "passed", "evidence": [str(proof_path)]}}
    co.finish_action(root, "A", repeat_start["action_id"], result)
    receipt = send("CONSUMED-3", kind="CONSUMED", revision=3, refs=[ready["id"]], payload={"source_sha": source, "local_sha": local_sha, "verification": result["verification"]})
    acknowledge(receipt)
    before_close = snapshot("04-核验Git并补回执仍待主任务关闭")
    assert before_close["actions_pending_verification"] == [] and len(before_close["open_requests"]) == 1
    closed = send("CLOSE-CAPABILITY-3", "main", "A", "RESOLVED", 3, request_ids + [receipt["id"]], {"recovery": {"resolution": "completed", "consumer": "A", "request_ids": request_ids, "evidence_refs": [receipt["id"]], "reason": "已核验修订3的消费、内容及唯一接入记录；仅合成验证，不代表App验收"}})
    acknowledge(closed)
    final = snapshot("05-主任务核验关闭后恢复")
    assert final["open_requests"] == [] and len(final["closed_requests"]) == 2
    assert not co.begin_action(root, "A", plan)["can_execute"]
    assert len(git(worktree, "log", "--format=%H", "--fixed-strings", "--grep=(cherry picked from commit " + source + ")").splitlines()) == 1
    frozen = {str(path): path.read_bytes() for path in root.rglob("*.json")}
    assert co.recover(root, "main") == final
    assert frozen == {str(path): path.read_bytes() for path in root.rglob("*.json")}
    summary = {"passed": True, "current_revision": 3, "original_request_preserved": request["id"] in final["closed_requests"][0]["request_ids"], "adjustment_requests_preserved": len(request_ids) == 3, "independent_layout_cancellation_preserved": any(item["entity_id"] == "MODULE-CHANGE" for item in final["closed_requests"]), "cross_batch_old_request_preserved": True, "fresh_process_recoveries": 6, "forced_interruption": "SIGKILL after cherry-pick before receipt", "git_import_count": 1, "repeated_notification_reexecutes": 0, "final_open_requests": 0, "real_codex_tasks_created": 0, "real_app_screenshots": 0}
    (output / "验证结果.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    text = """# 共享能力恢复对账验证

本报告使用合成消息和独立 Git 夹具；没有创建真实 Codex 任务或修改 调用项目源码。

| 阶段 | 核验结果 |
| --- | --- |
| 原始请求落盘，中断前未确认 | 自动找到未完成的共享能力请求及待确认消息 |
| 两次修改共享能力要求，另行多次调整模块 | 原始请求仍在，当前有效修订为 3，三条请求全部保留 |
| 新批次已开始，旧批目录误标“已完成” | 跨批扫描仍找出旧批未完成依赖请求，不相信错误完成标记 |
| 共享能力接入后进程被 SIGKILL，尚未写完成回执 | 新进程恢复发现执行意图，要求核验 Git，不直接重做 |
| 重发同一通知并重复申请接入 | 通知幂等，重复接入许可被拒绝；Git 中实际接入仍为 1 次 |
| 核验实际 Git 并补消费回执 | 仍保留请求，等待主任务明确核验关闭 |
| 主任务关联原请求与验证回执后关闭 | 原请求和两次调整历史保留，未完成请求归零；再次恢复不重复执行 |

每阶段的 JSON 和 Markdown 对账报告、消息原件、执行意图与回执，以及 Git 核验结果均在本目录。

工具仅对已落盘记录对账和提出下一步，不读取未登记的聊天纠正、不自动执行 Git，也不证明真实业务或 UI 验收通过。
"""
    (output / "验证报告.md").write_text(text, encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="模拟共享能力请求在中断及多次需求调整后的恢复")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    co.require(args.output.is_absolute(), "验证产物目录须为绝对路径")
    print(json.dumps(simulate(args.output.resolve()), ensure_ascii=False, indent=2))
