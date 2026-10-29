// 发布校验、持久领取、实际通知及回执串行执行；异步命令只等原会话，不重跑。
async function dispatchNotification(io, options) {
  if (!options || !Array.isArray(options.messageIds) || !options.messageIds.length ||
      !options.messageIds.every(value => typeof value === "string" && value.trim())) {
    return { status: "blocked", reason: "须提供实际非空消息ID数组" };
  }
  if (typeof io.exec !== "function" || typeof io.send !== "function") {
    return { status: "blocked", reason: "缺少已授权的命令或聊天通知能力" };
  }
  const absolute = value => typeof value === "string" && value.startsWith("/") && !value.includes("\0");
  if (!absolute(options.root) || !absolute(options.scriptPath) ||
      (options.retryVerification != null && !absolute(options.retryVerification))) {
    return { status: "blocked", reason: "批次、工具脚本及重试核验文件须使用绝对路径；未调用命令或通知" };
  }
  const limit = options.commandPollLimit ?? 3, pollMs = options.commandPollMs ?? 1000;
  if (!Number.isInteger(limit) || limit < 0 || limit > 10 ||
      !Number.isInteger(pollMs) || pollMs < 250 || pollMs > 5000) {
    return { status: "blocked", reason: "命令等待须有界：0至10次，每次250至5000毫秒" };
  }
  const quote = value => "'" + String(value).replaceAll("'", "'\\''") + "'";
  const run = args => io.exec({
    cmd: [options.python || "python3", "-B", options.scriptPath, ...args].map(quote).join(" "),
    max_output_tokens: 6000, login: false
  });
  const completed = value => value && value.exit_code === 0 && !value.session_id;
  const binding = { root: options.root, sender: options.sender, messageIds: options.messageIds };
  const resumed = options.resume;
  const validPlan = gate => gate && gate.root === options.root && gate.sender === options.sender &&
    /^[a-f0-9]{64}$/.test(gate.notification_id) && Number.isInteger(gate.attempt) && gate.attempt > 0 &&
    typeof gate.tool_args?.threadId === "string" && gate.tool_args.threadId.trim() &&
    typeof gate.tool_args?.prompt === "string" && gate.tool_args.prompt.trim();
  const sameToolArgs = (left, right) => Object.keys(left).length === Object.keys(right).length &&
    Object.keys(left).every(key => left[key] === right[key]);
  const matchesMessages = gate => Array.isArray(gate?.messages) &&
    JSON.stringify(gate.messages.map(item => item.message_id).sort()) ===
      JSON.stringify([...options.messageIds].sort());
  if (resumed && (resumed.root !== binding.root || resumed.sender !== binding.sender ||
      JSON.stringify(resumed.messageIds) !== JSON.stringify(binding.messageIds) ||
      !["prepare", "claim", "finish"].includes(resumed.stage) || !resumed.session_id ||
      typeof resumed.output !== "string" || (resumed.stage !== "prepare" && (!validPlan(resumed.gate) || !matchesMessages(resumed.gate))) ||
      (resumed.stage === "finish" && (!["sent", "unknown"].includes(resumed.outcome) || typeof resumed.evidence !== "string")))) {
    return { status: "blocked", reason: "异步接续不属于当前批次、发送方、消息组合或阶段" };
  }

  async function settle(initial) {
    let result = initial, output = initial?.output || "";
    const session = initial?.session_id;
    if (!session) return initial;
    // 输出分块返回；拼接原会话输出，不能再次prepare/claim来取代旧命令。
    for (let index = 0; index < limit && result?.session_id && typeof io.wait === "function"; index++) {
      try {
        const next = await io.wait({ session_id: session, chars: "", yield_time_ms: pollMs, max_output_tokens: 6000 });
        if (!next || (next.session_id && next.session_id !== session)) {
          return { ...result, output, session_id: session, wait_error: "原命令会话返回不符，停止并核对" };
        }
        output += next.output || "";
        result = { ...next, output };
      } catch (error) {
        return { ...result, output, session_id: session, wait_error: String(error) };
      }
    }
    return { ...result, output };
  }
  async function command(stage, args) {
    return settle(resumed?.stage === stage
      ? { session_id: resumed.session_id, output: resumed.output }
      : await run(args));
  }
  function pending(stage, result, gate, outcome, evidence) {
    const continuation = { ...binding, stage, session_id: result.session_id, output: result.output || "" };
    if (gate) continuation.gate = gate;
    if (stage === "finish") Object.assign(continuation, { outcome, evidence });
    return { status: stage === "finish" ? "result_unknown" : "command_pending",
      reason: stage === "finish" ? "通知已尝试；只接续原回执命令，禁止重发" : "原命令仍待核对；保存continuation并接续同一会话",
      ...(gate ? { notification_id: gate.notification_id, attempt: gate.attempt } : {}),
      send_attempted: stage === "finish", continuation, command_result: result };
  }

  let gate = resumed?.gate, outcome = resumed?.outcome, evidence = resumed?.evidence;
  if (!resumed || resumed.stage === "prepare") {
    try {
      const args = ["prepare-notification", "--root", options.root, "--sender", options.sender,
        "--message-id", ...options.messageIds];
      if (options.retryVerification) args.push("--retry-verification", options.retryVerification);
      const prepared = await command("prepare", args);
      if (prepared?.session_id) return pending("prepare", prepared);
      if (!completed(prepared)) return { status: "blocked", reason: "通知前置校验未成功结束", command_result: prepared };
      gate = JSON.parse(prepared.output);
      if (gate.can_notify === false) return { status: "not_notified", reason: gate.reason };
      if (gate.can_notify !== true || !validPlan(gate) || !matchesMessages(gate)) {
        return { status: "blocked", reason: "通知计划格式不完整，未调用聊天工具" };
      }
    } catch (error) {
      return { status: "blocked", reason: "通知计划不可读取", detail: String(error) };
    }
  }

  if (!resumed || resumed.stage !== "finish") {
    try {
      const claim = await command("claim", ["claim-notification", "--root", options.root, "--sender", options.sender,
        "--notification-id", gate.notification_id, "--attempt", String(gate.attempt)]);
      if (claim?.session_id) return pending("claim", claim, gate);
      if (!completed(claim)) return { status: "blocked", reason: "发送领取未可靠结束；核对原意图，禁止重发", command_result: claim };
      const permission = JSON.parse(claim.output);
      if (permission.can_send === false) return { status: "not_notified", reason: permission.reason };
      if (permission.can_send !== true || !validPlan(permission) ||
          permission.notification_id !== gate.notification_id || permission.attempt !== gate.attempt ||
          !sameToolArgs(permission.tool_args, gate.tool_args)) {
        return { status: "blocked", reason: "发送领取与原通知计划不符，未调用聊天工具" };
      }
    } catch (error) {
      return { status: "blocked", reason: "发送领取不可读取；先恢复核对", detail: String(error) };
    }

    outcome = "unknown";
    try {
      const response = await io.send(gate.tool_args);
      evidence = JSON.stringify(response);
      const returnedTargets = [response?.threadId, response?.structuredContent?.threadId].filter(Boolean);
      for (const block of response?.content || []) {
        if (block.type !== "text") continue;
        try {
          const target = JSON.parse(block.text).threadId;
          if (target) returnedTargets.push(target);
        } catch (_) { /* 普通文本不能证明通知发往本次目标。 */ }
      }
      if (response && response.isError !== true && returnedTargets.length &&
          returnedTargets.every(target => target === gate.tool_args.threadId)) outcome = "sent";
      else evidence = evidence || "聊天工具返回空结果，送达未知";
    } catch (error) {
      // 抛错可能发生在实际发送之后；领取标记保留，不能重新发送来猜测结果。
      evidence = "聊天工具结果未知：" + String(error);
    }
  }
  try {
    const receipt = await command("finish", ["finish-notification", "--root", options.root, "--sender", options.sender,
      "--notification-id", gate.notification_id, "--attempt", String(gate.attempt), "--status", outcome, "--evidence", evidence]);
    if (receipt?.session_id) return pending("finish", receipt, gate, outcome, evidence);
    if (!completed(receipt) || JSON.parse(receipt.output).status !== outcome) {
      return { status: "result_unknown", notification_id: gate.notification_id, attempt: gate.attempt,
        reason: "通知已尝试，回执未可靠保存；恢复前禁止重发", command_result: receipt };
    }
  } catch (error) {
    return { status: "result_unknown", notification_id: gate.notification_id, attempt: gate.attempt,
      reason: "通知已尝试，回执结果未知；先恢复核对", detail: String(error) };
  }
  return { status: outcome === "sent" ? "notified_waiting_ack" : "result_unknown",
    notification_id: gate.notification_id, attempt: gate.attempt, task_completion_verified: false };
}

// 桌面工具编排直接加载同一函数；Node仅供隔离回归使用。
if (typeof module !== "undefined") module.exports = { dispatchNotification };
