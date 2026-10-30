"""受控调用器的异步接续与真实SIGKILL窗口；聊天传输为本地持久测试收件箱。"""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest

import coordination as co


# 命令运行真实Python信箱；异步模式仅模拟宿主分块会话。kill模式在fsync收件箱后
# 直接杀死整个Node进程，不用抛异常代替崩溃，也不会写发送完成回执。
RUNNER = r"""
const {dispatchNotification}=require(process.argv[2]);
const {spawnSync}=require("child_process");
const fs=require("fs");
const options=JSON.parse(process.argv[3]), mode=process.argv[4], folder=process.argv[5];
const statePath=folder+"/transport-state.json", mailbox=folder+"/mailbox.jsonl";
const state=fs.existsSync(statePath)?JSON.parse(fs.readFileSync(statePath,"utf8")):
  {commands:{},sessions:{},sends:0,nextSession:100,waits:0};
const save=()=>fs.writeFileSync(statePath,JSON.stringify(state));
function execute(args){
  const stage=args.cmd.includes("'prepare-notification'")?"prepare":
    args.cmd.includes("'claim-notification'")?"claim":"finish";
  state.commands[stage]=(state.commands[stage]||0)+1;save();
  const p=spawnSync("/bin/sh",["-c",args.cmd],{encoding:"utf8"});
  const result={exit_code:p.status,output:p.stdout,stderr:p.stderr};
  if(mode.endsWith("-"+stage)){
    const session=state.nextSession++, split=Math.floor(result.output.length/2);
    state.sessions[session]={exit_code:result.exit_code,output:result.output.slice(split)};save();
    return {session_id:session,output:result.output.slice(0,split)};
  }
  return result;
}
const io={
  exec:async args=>execute(args),
  wait:async args=>{
    state.waits++; const next=state.sessions[args.session_id];
    if(!next)throw new Error("原会话不存在；不得重新执行命令");
    delete state.sessions[args.session_id];save();return next;
  },
  send:async args=>{
    state.sends++;save();
    const fd=fs.openSync(mailbox,"a");
    fs.writeSync(fd,JSON.stringify({threadId:args.threadId,prompt:args.prompt})+"\n");
    fs.fsyncSync(fd);fs.closeSync(fd);
    if(mode==="kill-after-send")process.kill(process.pid,"SIGKILL");
    return {threadId:args.threadId};
  }
};
if(mode==="no-wait-prepare")delete io.wait;
(async()=>{const result=await dispatchNotification(io,options);save();
  process.stdout.write(JSON.stringify({result,state}));})();
"""


@unittest.skipUnless(shutil.which("node"), "隔离工具编排验证需要Node")
class DispatchRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ["COORDINATION_TEST_ROOT"])
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name).resolve()
        self.root = self.folder / "批次"
        self.runner = self.folder / "runner.js"
        self.runner.write_text(RUNNER)
        self.script = Path(co.__file__)
        self.adapter = self.script.with_name("notification_dispatch.js")
        self.config = {"schema_version": 1, "batch_id": "ASYNC", "main": "main", "authorization": "本地夹具，不通知真实聊天",
                       "notification_policy": {"check_after_seconds": 0, "max_notification_retries": 2},
                       "actors": {"main": {"role": "main", "thread_id": "fixture-main"},
                                  "A": {"role": "worker", "thread_id": "fixture-a", "host_id": "local"}}}
        co.initialize(self.root, self.config)
        self.event = {"batch_id": "ASYNC", "id": "ASSIGN", "sender": "main", "recipient": "A",
                      "kind": "ASSIGN", "entity_id": "MODULE", "revision": 1,
                      "created_at": "2000-01-01T00:00:00+00:00", "refs": [], "payload": {"description": "测试作业"}}
        co.emit(self.root, "main", self.event)
        self.options = {"root": str(self.root), "sender": "main", "messageIds": ["ASSIGN"],
                        "scriptPath": str(self.script), "python": sys.executable}

    def dispatch(self, mode="normal", **extra):
        return subprocess.run(["node", str(self.runner), str(self.adapter), json.dumps({**self.options, **extra}),
                               mode, str(self.folder)], capture_output=True, text=True)

    def result(self, mode="normal", **extra):
        process = self.dispatch(mode, **extra)
        self.assertEqual(process.returncode, 0, process.stderr)
        return json.loads(process.stdout)

    def test_all_three_command_stages_wait_original_session_and_send_once(self):
        for stage in ("prepare", "claim", "finish"):
            with self.subTest(stage=stage):
                folder = self.folder / stage
                co.initialize(folder, self.config)
                co.emit(folder, "main", self.event)
                self.options["root"] = str(folder)
                result = self.result("async-" + stage)
                self.assertEqual(result["result"]["status"], "notified_waiting_ack")
                self.assertEqual(result["state"]["commands"][stage], 1 if stage == "prepare" else
                                 (2 if stage == "claim" else 3))
                self.assertEqual(result["state"]["sends"], ["prepare", "claim", "finish"].index(stage) + 1)
                self.assertEqual(co.recover(folder, "main")["notifications_pending_verification"], [])
        state = json.loads((self.folder / "transport-state.json").read_text())
        self.assertEqual(state["commands"], {"prepare": 3, "claim": 3, "finish": 3})
        self.assertEqual(state["waits"], 3)

    def test_bounded_prepare_resumes_in_fresh_process_without_new_prepare(self):
        first = self.result("async-prepare", commandPollLimit=0)
        self.assertEqual(first["result"]["status"], "command_pending")
        self.assertEqual(first["state"]["sends"], 0)
        continuation = first["result"]["continuation"]
        (self.folder / "continuation.json").write_text(json.dumps(continuation))
        second = self.result(resume=json.loads((self.folder / "continuation.json").read_text()))
        self.assertEqual(second["result"]["status"], "notified_waiting_ack")
        self.assertEqual(second["state"]["commands"], {"prepare": 1, "claim": 1, "finish": 1})
        replay = self.result(resume=continuation)
        self.assertEqual(replay["state"]["sends"], 1)
        self.assertEqual(replay["state"]["commands"], second["state"]["commands"])

    def test_pending_claim_and_pending_finish_never_repeat_actual_send(self):
        for stage in ("claim", "finish"):
            with self.subTest(stage=stage):
                folder = self.folder / stage
                co.initialize(folder, self.config)
                co.emit(folder, "main", self.event)
                self.options["root"] = str(folder)
                first = self.result("async-" + stage, commandPollLimit=0)
                previous_sends = first["state"]["sends"]
                second = self.result(resume=first["result"]["continuation"])
                self.assertEqual(second["result"]["status"], "notified_waiting_ack")
                self.assertEqual(second["state"]["sends"] - previous_sends, 1 if stage == "claim" else 0)
        self.assertEqual(json.loads((self.folder / "transport-state.json").read_text())["commands"],
                         {"prepare": 2, "claim": 2, "finish": 2})

    def test_missing_wait_and_mismatched_resume_stay_pending_without_new_commands(self):
        first = self.result("no-wait-prepare")
        self.assertEqual(first["result"]["status"], "command_pending")
        changed = {**first["result"]["continuation"], "sender": "A"}
        second = self.result(resume=changed)
        self.assertEqual(second["result"]["status"], "blocked")
        self.assertEqual(second["state"]["sends"], 0)
        self.assertEqual(second["state"]["commands"], {"prepare": 1})

    def test_claim_is_atomic_and_rechecks_revision_and_binding(self):
        plan = co.prepare_notification(self.root, "main", ["ASSIGN"])
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: co.claim_notification(self.root, "main", plan["notification_id"], 1), range(8)))
        self.assertEqual(sum(row["can_send"] for row in results), 1)
        self.assertFalse(co.prepare_notification(self.root, "main", ["ASSIGN"])["can_notify"])
        unknown = co.recover(self.root, "main")["notifications_pending_verification"]
        self.assertEqual(len(unknown), 1)
        fresh = self.folder / "stale"
        co.initialize(fresh, self.config)
        co.emit(fresh, "main", self.event)
        plan = co.prepare_notification(fresh, "main", ["ASSIGN"])
        co.emit(fresh, "main", {**self.event, "id": "NEW", "revision": 2})
        with self.assertRaises(ValueError):
            co.claim_notification(fresh, "main", plan["notification_id"], 1)
        self.assertFalse(list(fresh.glob("notifications/*/*.dispatch.json")))
        rebound = self.folder / "rebound"
        co.initialize(rebound, self.config)
        co.emit(rebound, "main", self.event)
        plan = co.prepare_notification(rebound, "main", ["ASSIGN"])
        config = co.read_json(rebound / "batch.json")
        config["actors"]["A"]["thread_id"] = "replacement-must-not-receive-old-notice"
        (rebound / "batch.json").write_text(json.dumps(config))
        with self.assertRaises(ValueError):
            co.claim_notification(rebound, "main", plan["notification_id"], 1)
        self.assertFalse(list(rebound.glob("notifications/*/*.dispatch.json")))

    def test_process_killed_after_durable_delivery_before_receipt_does_not_resend(self):
        killed = self.dispatch("kill-after-send")
        self.assertEqual(killed.returncode, -signal.SIGKILL)
        mailbox = self.folder / "mailbox.jsonl"
        self.assertEqual(len(mailbox.read_text().splitlines()), 1)
        self.assertEqual(len(list(self.root.glob("notifications/*/*.dispatch.json"))), 1)
        self.assertFalse(list(self.root.glob("notifications/*/*.done.json")))
        command = [sys.executable, "-B", str(self.script), "recover", "--root", str(self.root), "--actor", "main"]
        recovered = json.loads(subprocess.run(command, check=True, capture_output=True, text=True).stdout)
        self.assertEqual(len(recovered["notifications_pending_verification"]), 1)
        again = self.result()
        self.assertEqual(again["result"]["status"], "not_notified")
        self.assertEqual(len(mailbox.read_text().splitlines()), 1)
        pending = recovered["notifications_pending_verification"][0]
        # 先核对实际测试收件箱，再补独立核验；原意图和缺失done均不伪造。
        co.finish_notification(self.root, "main", pending["notification_id"], pending["attempt"],
                               {"status": "sent", "evidence": ["实际持久测试收件箱已有唯一消息，进程死于fsync之后"]},
                               reconcile=True)
        self.assertFalse(list(self.root.glob("notifications/*/*.done.json")))
        self.assertEqual(co.recover(self.root, "main")["notifications_pending_verification"], [])
        co.acknowledge(self.root, "A", "ASSIGN")
        final = self.result()
        self.assertEqual(final["state"]["sends"], 1)
        self.assertEqual(co.recover(self.root, "main")["awaiting_confirmation"], [])
        self.assertEqual(len(mailbox.read_text().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
