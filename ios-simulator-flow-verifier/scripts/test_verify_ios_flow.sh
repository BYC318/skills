#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
RUNNER="$SCRIPT_DIR/verify_ios_flow.sh"
TEMP_ROOT=$(mktemp -d /tmp/ios-flow-verifier-test.XXXXXX)
FAKE_BIN="$TEMP_ROOT/bin"
REPO="$TEMP_ROOT/repo"
ARTIFACT_ROOT="$TEMP_ROOT/artifacts"
COUNT_FILE="$TEMP_ROOT/xcodebuild-count"

cleanup() {
  rm -rf "$TEMP_ROOT"
}
trap cleanup EXIT

mkdir -p "$FAKE_BIN" "$REPO/App.xcodeproj"

cat > "$FAKE_BIN/xcrun" <<'STUB'
#!/bin/bash
set -euo pipefail

if [[ "${1:-}" == "simctl" && "${2:-}" == "list" ]]; then
  cat <<'JSON'
{"devices":{"com.apple.CoreSimulator.SimRuntime.iOS-26-5":[{"name":"iPhone Test","udid":"00000000-0000-0000-0000-000000000001","state":"Booted","isAvailable":true}]}}
JSON
  exit 0
fi

if [[ "${1:-}" == "simctl" && ( "${2:-}" == "boot" || "${2:-}" == "bootstatus" ) ]]; then
  exit 0
fi

if [[ "${1:-}" == "xcresulttool" && "${2:-}" == "get" ]]; then
  printf '{"result":"Passed","passedTests":1,"failedTests":0,"skippedTests":0}\n'
  exit 0
fi

if [[ "${1:-}" == "xcresulttool" && "${2:-}" == "export" ]]; then
  output=""
  while [[ $# -gt 0 ]]; do
    if [[ "$1" == "--output-path" ]]; then output=${2:?}; shift 2; else shift; fi
  done
  mkdir -p "$output"
  printf 'failure attachment\n' > "$output/failure.txt"
  exit 0
fi

echo "fake xcrun 不支持：$*" >&2
exit 2
STUB

cat > "$FAKE_BIN/xcodebuild" <<'STUB'
#!/bin/bash
set -euo pipefail

if [[ "${1:-}" == "-version" ]]; then
  printf 'Xcode Test\nBuild version TEST\n'
  exit 0
fi

count_file=${FAKE_COUNT_FILE:?}
count=0
if [[ -f "$count_file" ]]; then count=$(<"$count_file"); fi
printf '%s\n' "$((count + 1))" > "$count_file"

result=""
previous=""
for argument in "$@"; do
  if [[ "$previous" == "-resultBundlePath" ]]; then result="$argument"; fi
  previous="$argument"
done
[[ -n "$result" ]] || { echo "缺少 -resultBundlePath" >&2; exit 2; }
mkdir -p "$result"
if [[ -n "${FAKE_XCODEBUILD_SLEEP:-}" ]]; then sleep "$FAKE_XCODEBUILD_SLEEP"; fi
exit "${FAKE_XCODEBUILD_STATUS:-0}"
STUB

chmod +x "$FAKE_BIN/xcrun" "$FAKE_BIN/xcodebuild"

printf 'initial\n' > "$REPO/Source.swift"
git -C "$REPO" init -q
git -C "$REPO" config user.name Test
git -C "$REPO" config user.email test@example.com
git -C "$REPO" add Source.swift App.xcodeproj
git -C "$REPO" commit -qm initial
printf '0\n' > "$COUNT_FILE"

common=(
  --project "$REPO/App.xcodeproj"
  --scheme App
  --headless
)

run_runner() {
  env PATH="$FAKE_BIN:$PATH" \
    FAKE_COUNT_FILE="$COUNT_FILE" \
    IOS_FLOW_VERIFIER_ARTIFACT_ROOT="$ARTIFACT_ROOT" \
    "$RUNNER" "$@"
}

set +e
run_runner "${common[@]}" --only-testing AppUITests/FlowTests/testOne > "$TEMP_ROOT/missing-reason.log" 2>&1
status=$?
set -e
[[ $status -eq 2 ]] || { echo "缺少验证原因应返回 2，实际为 $status" >&2; exit 1; }
[[ $(<"$COUNT_FILE") -eq 0 ]] || { echo "缺少验证原因时不应调用 xcodebuild" >&2; exit 1; }

set +e
run_runner "${common[@]}" --verification-reason ordinary-edit \
  --only-testing AppUITests/FlowTests/testOne > "$TEMP_ROOT/invalid-reason.log" 2>&1
status=$?
set -e
[[ $status -eq 2 ]] || { echo "非法验证原因应返回 2，实际为 $status" >&2; exit 1; }

run_runner "${common[@]}" --only-testing AppUITests/FlowTests/testOne --dry-run > "$TEMP_ROOT/dry-run.log"
[[ $(<"$COUNT_FILE") -eq 0 ]] || { echo "dry-run 不应调用 xcodebuild" >&2; exit 1; }

run_runner --project "$REPO/App.xcodeproj" --scheme App --full --dry-run > "$TEMP_ROOT/visible-full-dry-run.log"
rg -q '显示模式：可视（dry-run' "$TEMP_ROOT/visible-full-dry-run.log"

run_runner "${common[@]}" --verification-reason delivery-checkpoint \
  --only-testing AppUITests/FlowTests/testOne > "$TEMP_ROOT/first.log"
[[ $(<"$COUNT_FILE") -eq 1 ]] || { echo "首次验证应调用一次 xcodebuild" >&2; exit 1; }
rg -q 'xcresult 摘要' "$TEMP_ROOT/first.log"

run_runner "${common[@]}" --verification-reason user-request \
  --only-testing AppUITests/FlowTests/testOne > "$TEMP_ROOT/cache-hit.log"
[[ $(<"$COUNT_FILE") -eq 1 ]] || { echo "缓存命中不应再次调用 xcodebuild" >&2; exit 1; }
rg -q '复用已通过结果' "$TEMP_ROOT/cache-hit.log"

run_runner "${common[@]}" --verification-reason user-request --force \
  --only-testing AppUITests/FlowTests/testOne > "$TEMP_ROOT/force.log"
[[ $(<"$COUNT_FILE") -eq 2 ]] || { echo "--force 应再次调用 xcodebuild" >&2; exit 1; }

set +e
env PATH="$FAKE_BIN:$PATH" FAKE_COUNT_FILE="$COUNT_FILE" FAKE_XCODEBUILD_STATUS=1 \
  IOS_FLOW_VERIFIER_ARTIFACT_ROOT="$ARTIFACT_ROOT" \
  "$RUNNER" "${common[@]}" --verification-reason user-request --force \
  --only-testing AppUITests/FlowTests/testOne > "$TEMP_ROOT/force-failure.log" 2>&1
status=$?
set -e
[[ $status -eq 1 ]] || { echo "强制失败应返回 1，实际为 $status" >&2; exit 1; }
[[ $(<"$COUNT_FILE") -eq 3 ]] || { echo "强制失败应调用 xcodebuild" >&2; exit 1; }

run_runner "${common[@]}" --verification-reason delivery-checkpoint \
  --only-testing AppUITests/FlowTests/testOne > "$TEMP_ROOT/after-force-failure.log"
[[ $(<"$COUNT_FILE") -eq 4 ]] || { echo "强制失败后不应复用旧成功缓存" >&2; exit 1; }

printf 'changed\n' >> "$REPO/Source.swift"
run_runner "${common[@]}" --verification-reason delivery-checkpoint \
  --only-testing AppUITests/FlowTests/testOne > "$TEMP_ROOT/changed.log"
[[ $(<"$COUNT_FILE") -eq 5 ]] || { echo "代码变化后缓存应失效" >&2; exit 1; }

env PATH="$FAKE_BIN:$PATH" FAKE_COUNT_FILE="$COUNT_FILE" \
  FAKE_XCODEBUILD_SLEEP=3 IOS_FLOW_VERIFIER_ARTIFACT_ROOT="$ARTIFACT_ROOT" \
  "$RUNNER" "${common[@]}" --verification-reason delivery-checkpoint --force \
  --only-testing AppUITests/LockTests/testLock > "$TEMP_ROOT/lock-owner.log" 2>&1 &
owner_pid=$!

for _ in 1 2 3 4 5 6 7 8 9 10; do
  compgen -G "$ARTIFACT_ROOT/locks/*.lock" >/dev/null && break
  sleep 0.1
done

set +e
run_runner "${common[@]}" --verification-reason delivery-checkpoint --force \
  --only-testing AppUITests/LockTests/testLock > "$TEMP_ROOT/lock-contender.log" 2>&1
status=$?
set -e
[[ $status -eq 75 ]] || { echo "锁冲突应返回 75，实际为 $status" >&2; kill "$owner_pid" 2>/dev/null || true; exit 1; }
wait "$owner_pid"

env PATH="$FAKE_BIN:$PATH" FAKE_COUNT_FILE="$COUNT_FILE" \
  FAKE_XCODEBUILD_SLEEP=2 IOS_FLOW_VERIFIER_ARTIFACT_ROOT="$ARTIFACT_ROOT" \
  "$RUNNER" "${common[@]}" --verification-reason delivery-checkpoint --force \
  --only-testing AppUITests/FingerprintTests/testStableState > "$TEMP_ROOT/fingerprint-change.log" 2>&1 &
fingerprint_pid=$!
sleep 0.5
printf 'changed-during-verification\n' >> "$REPO/Source.swift"
set +e
wait "$fingerprint_pid"
status=$?
set -e
[[ $status -eq 74 ]] || { echo "验证期间代码变化应返回 74，实际为 $status" >&2; exit 1; }
rg -q '验证期间工作区发生变化' "$TEMP_ROOT/fingerprint-change.log"

set +e
env PATH="$FAKE_BIN:$PATH" FAKE_COUNT_FILE="$COUNT_FILE" FAKE_XCODEBUILD_STATUS=1 \
  IOS_FLOW_VERIFIER_ARTIFACT_ROOT="$ARTIFACT_ROOT" \
  "$RUNNER" "${common[@]}" --verification-reason failure-rerun --force \
  --only-testing AppUITests/FailureTests/testFailure > "$TEMP_ROOT/failure.log" 2>&1
status=$?
set -e
[[ $status -eq 1 ]] || { echo "失败测试应透传状态 1，实际为 $status" >&2; exit 1; }
compgen -G "$ARTIFACT_ROOT/failures/*/failure.txt" >/dev/null || { echo "失败附件未导出" >&2; exit 1; }

printf 'verify_ios_flow.sh 自测通过\n'
