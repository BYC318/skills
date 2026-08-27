#!/bin/bash
set -euo pipefail

usage() {
  cat <<'EOF'
用法：
  verify_ios_flow.sh (--workspace PATH | --project PATH) --scheme NAME [options]

选项：
  --workspace PATH         Xcode Workspace 路径
  --project PATH           Xcode Project 路径
  --scheme NAME            要测试的共享 Scheme
  --device-id UUID         使用指定的可用模拟器
  --device-name NAME       没有已启动设备时优先选择此模拟器型号
  --only-testing ID        运行指定测试；可重复传入多个
  --full                   运行 Scheme 的完整测试操作
  --derived-data PATH      DerivedData 路径
  --result PATH            xcresult 结果包路径
  --verification-reason VALUE 实际执行原因：user-request、delivery-checkpoint、
                           runtime-diagnosis 或 failure-rerun
  --force                  忽略相同代码和测试范围的成功缓存
  --launch-arg VALUE       记录交付所需的应用启动参数；可重复传入
  --visible                可视验证模式（默认）：打开并置前指定模拟器
  --headless               无头模式：不打开 Simulator，适用于 CI
  --observe-seconds N      可视模式中间页面观察秒数，默认 2
  --final-observe-seconds N 可视模式最终页面观察秒数，默认 5
  --no-observation         可视运行但不增加人工观察停留
  --verbose                显示完整 xcodebuild 日志
  --dry-run                只解析并输出命令，不实际运行
  --help                   显示帮助

示例：
  verify_ios_flow.sh --workspace App.xcworkspace --scheme App \
    --verification-reason delivery-checkpoint \
    --only-testing AppUITests/JourneyTests/testSaveProfile
  verify_ios_flow.sh --workspace App.xcworkspace --scheme App \
    --verification-reason user-request --visible \
    --only-testing AppUITests/JourneyTests/testChangedFlow
  verify_ios_flow.sh --project App.xcodeproj --scheme App --full --dry-run
EOF
}

workspace=""
project=""
scheme=""
device_id=""
device_name=""
artifact_root="${IOS_FLOW_VERIFIER_ARTIFACT_ROOT:-/tmp/ios-simulator-flow-verifier}"
derived_data="$artifact_root/DerivedData"
result_path=""
full=0
dry_run=0
verbose=0
visible=1
observation_enabled=1
observe_seconds="2"
final_observe_seconds="5"
verification_reason=""
force=0
only_tests=()
launch_args=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace) workspace=${2:?}; shift 2 ;;
    --project) project=${2:?}; shift 2 ;;
    --scheme) scheme=${2:?}; shift 2 ;;
    --device-id) device_id=${2:?}; shift 2 ;;
    --device-name) device_name=${2:?}; shift 2 ;;
    --only-testing) only_tests+=("${2:?}"); shift 2 ;;
    --full) full=1; shift ;;
    --derived-data) derived_data=${2:?}; shift 2 ;;
    --result) result_path=${2:?}; shift 2 ;;
    --verification-reason) verification_reason=${2:?}; shift 2 ;;
    --force) force=1; shift ;;
    --launch-arg) launch_args+=("${2:?}"); shift 2 ;;
    --visible) visible=1; shift ;;
    --headless) visible=0; shift ;;
    --observe-seconds) observe_seconds=${2:?}; shift 2 ;;
    --final-observe-seconds) final_observe_seconds=${2:?}; shift 2 ;;
    --no-observation) observation_enabled=0; shift ;;
    --verbose) verbose=1; shift ;;
    --dry-run) dry_run=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "未知参数：$1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$scheme" ]] || { echo "必须提供 --scheme" >&2; exit 2; }
if [[ -n "$workspace" && -n "$project" ]]; then
  echo "--workspace 和 --project 只能选择一个" >&2
  exit 2
fi
[[ -n "$workspace" || -n "$project" ]] || { echo "必须提供 --workspace 或 --project" >&2; exit 2; }
if [[ $full -eq 0 && ${#only_tests[@]} -eq 0 ]]; then
  echo "请选择 --full，或至少提供一个 --only-testing" >&2
  exit 2
fi
case "$verification_reason" in
  ""|user-request|delivery-checkpoint|runtime-diagnosis|failure-rerun) ;;
  *)
    echo "--verification-reason 不支持：$verification_reason" >&2
    echo "允许值：user-request、delivery-checkpoint、runtime-diagnosis、failure-rerun" >&2
    exit 2
    ;;
esac
if [[ $dry_run -eq 0 && -z "$verification_reason" ]]; then
  echo "实际执行必须提供 --verification-reason；普通代码修改不得自动启动模拟器。" >&2
  exit 2
fi
number_pattern='^[0-9]+([.][0-9]+)?$'
[[ "$observe_seconds" =~ $number_pattern ]] || { echo "--observe-seconds 必须是非负数字" >&2; exit 2; }
[[ "$final_observe_seconds" =~ $number_pattern ]] || { echo "--final-observe-seconds 必须是非负数字" >&2; exit 2; }
if [[ $visible -eq 0 ]]; then observation_enabled=0; fi

container_flag="-workspace"
container_path="$workspace"
if [[ -n "$project" ]]; then container_flag="-project"; container_path="$project"; fi
container_path=$(cd "$(dirname "$container_path")" && pwd)/$(basename "$container_path")
[[ -e "$container_path" ]] || { echo "找不到 Xcode 工程容器：$container_path" >&2; exit 2; }

mkdir -p "$derived_data" "$artifact_root/results"
if [[ -z "$result_path" ]]; then
  stamp=$(date +%Y%m%d-%H%M%S)
  result_path="$artifact_root/results/${scheme}-${stamp}-$$.xcresult"
fi
[[ "$result_path" == *.xcresult ]] || { echo "--result 必须以 .xcresult 结尾" >&2; exit 2; }

visible_device_id=""
if [[ $visible -eq 1 ]]; then
  visible_device_id=$(defaults read com.apple.iphonesimulator CurrentDeviceUDID 2>/dev/null || true)
fi

if [[ -z "$device_id" ]]; then
  device_id=$(python3 - "$device_name" "$visible_device_id" <<'PY'
import json, subprocess, sys
preferred = sys.argv[1]
visible = sys.argv[2]
data = json.loads(subprocess.check_output(["xcrun", "simctl", "list", "devices", "available", "-j"]))
devices = [
    d for runtime, values in data.get("devices", {}).items()
    if ".iOS-" in runtime
    for d in values if d.get("isAvailable")
]
booted = [d for d in devices if d.get("state") == "Booted"]
matches = [d for d in devices if preferred and d.get("name") == preferred]
visible_matches = [d for d in devices if visible and d.get("udid") == visible]
choices = matches or visible_matches or booted or devices
if not choices:
    raise SystemExit("没有可用的 iOS 模拟器")
print(choices[0]["udid"])
PY
  )
fi

state=$(xcrun simctl list devices available -j | python3 -c 'import json,sys; uid=sys.argv[1]; d=json.load(sys.stdin); print(next(x.get("state", "") for xs in d.get("devices",{}).values() for x in xs if x.get("udid")==uid))' "$device_id")

cache_root="$artifact_root/cache"
lock_root="$artifact_root/locks"
mkdir -p "$cache_root" "$lock_root"

project_dir=$(dirname "$container_path")
repo_root=$(git -C "$project_dir" rev-parse --show-toplevel 2>/dev/null || true)
cache_enabled=0
code_fingerprint="unavailable"
compute_code_fingerprint() {
  (
    cd "$repo_root"
    git rev-parse HEAD
    git diff --binary HEAD --
    git ls-files --others --exclude-standard | LC_ALL=C sort | while IFS= read -r file; do
      [[ -f "$file" ]] || continue
      printf 'untracked\t%s\t' "$file"
      shasum -a 256 "$file" | awk '{print $1}'
    done
  ) | shasum -a 256 | awk '{print $1}'
}
if [[ -n "$repo_root" ]] && git -C "$repo_root" rev-parse --verify HEAD >/dev/null 2>&1; then
  cache_enabled=1
  code_fingerprint=$(compute_code_fingerprint)
fi

scope_fingerprint=$(
  {
    printf 'container\t%s\n' "$container_path"
    printf 'scheme\t%s\n' "$scheme"
    printf 'full\t%s\n' "$full"
    printf 'device\t%s\n' "$device_id"
    printf 'visible\t%s\n' "$visible"
    printf 'observation-enabled\t%s\n' "$observation_enabled"
    printf 'observe-seconds\t%s\n' "$observe_seconds"
    printf 'final-observe-seconds\t%s\n' "$final_observe_seconds"
    printf 'xcode\t%s\n' "$(xcodebuild -version | tr '\n' ' ')"
    if [[ ${#only_tests[@]} -gt 0 ]]; then
      printf '%s\n' "${only_tests[@]}" | LC_ALL=C sort | sed 's/^/test\t/'
    fi
    if [[ ${#launch_args[@]} -gt 0 ]]; then
      printf '%s\n' "${launch_args[@]}" | sed 's/^/launch-arg\t/'
    fi
  } | shasum -a 256 | awk '{print $1}'
)
cache_key=$(printf '%s\n%s\n' "$code_fingerprint" "$scope_fingerprint" | shasum -a 256 | awk '{print $1}')
cache_dir="$cache_root/$cache_key"
cache_record="$cache_dir/success.tsv"
repo_lock_key=$(printf '%s' "${repo_root:-$container_path}" | shasum -a 256 | awk '{print $1}')
lock_dir="$lock_root/$repo_lock_key.lock"

echo "验证原因：${verification_reason:-dry-run（未要求）}"
echo "代码指纹：$code_fingerprint"
echo "测试范围指纹：$scope_fingerprint"
if [[ $force -eq 1 ]]; then echo "结果复用：已通过 --force 关闭"; fi

if [[ $dry_run -eq 0 && $cache_enabled -eq 1 && $force -eq 0 && -f "$cache_record" ]]; then
  cached_result=$(awk -F '\t' '$1 == "result" {sub(/^result\t/, ""); print; exit}' "$cache_record")
  if [[ -n "$cached_result" && -d "$cached_result" ]]; then
    echo "复用已通过结果：$cached_result"
    echo "相同代码状态和测试范围不重复启动模拟器；如需强制重跑请使用 --force。"
    xcrun xcresulttool get test-results summary --path "$cached_result" || true
    exit 0
  fi
fi

lock_acquired=0
cleanup_lock() {
  if [[ $lock_acquired -eq 1 ]]; then
    rm -f "$lock_dir/owner.tsv"
    rmdir "$lock_dir" 2>/dev/null || true
  fi
}

acquire_lock() {
  if mkdir "$lock_dir" 2>/dev/null; then
    lock_acquired=1
  else
    owner_pid=$(awk -F '\t' '$1 == "pid" {print $2; exit}' "$lock_dir/owner.tsv" 2>/dev/null || true)
    if [[ -n "$owner_pid" ]] && kill -0 "$owner_pid" 2>/dev/null; then
      echo "已有唯一验证代理正在运行：PID=$owner_pid" >&2
      echo "锁：$lock_dir" >&2
      echo "当前调用不会启动第二个模拟器验证；请等待现有代理交付 xcresult。" >&2
      exit 75
    fi

    rm -f "$lock_dir/owner.tsv"
    rmdir "$lock_dir" 2>/dev/null || true
    if ! mkdir "$lock_dir" 2>/dev/null; then
      echo "无法取得唯一验证锁：$lock_dir" >&2
      exit 75
    fi
    lock_acquired=1
  fi

  {
    printf 'pid\t%s\n' "$$"
    printf 'reason\t%s\n' "$verification_reason"
    printf 'cache-key\t%s\n' "$cache_key"
    printf 'result\t%s\n' "$result_path"
  } > "$lock_dir/owner.tsv"
  trap cleanup_lock EXIT
  trap 'cleanup_lock; exit 130' INT
  trap 'cleanup_lock; exit 143' TERM
}

if [[ $dry_run -eq 0 ]]; then
  acquire_lock
  if [[ $force -eq 1 && $cache_enabled -eq 1 ]]; then
    rm -f "$cache_record"
  fi
fi

if [[ $dry_run -eq 0 ]]; then
  if [[ "$state" != "Booted" ]]; then
    xcrun simctl boot "$device_id"
  fi
  xcrun simctl bootstatus "$device_id" -b

  if [[ $visible -eq 1 ]]; then
    # CoreSimulator 可以在没有图形窗口时运行；可视模式必须单独打开并激活 Simulator。
    open -a Simulator --args -CurrentDeviceUDID "$device_id"
    osascript -e 'tell application "Simulator" to activate' >/dev/null 2>&1 || true
    if ! pgrep -x Simulator >/dev/null; then
      echo "无法启动 Simulator 图形界面；测试尚未执行。可改用 --headless，或手动打开 Simulator。" >&2
      exit 3
    fi

    window_count=$(xcrun swift -e 'import CoreGraphics
let rows = (CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]]) ?? []
let windows = rows.filter { ($0[kCGWindowOwnerName as String] as? String) == "Simulator" && (($0[kCGWindowLayer as String] as? Int) ?? -1) == 0 }
print(windows.count)' 2>/dev/null || echo "unknown")
    if [[ "$window_count" =~ ^[0-9]+$ ]] && [[ $window_count -eq 0 ]]; then
      echo "Simulator 进程已启动，但没有检测到屏幕上的设备窗口；测试尚未执行。请检查最小化窗口或其他桌面空间。" >&2
      exit 3
    fi

    current_visible_id=$(defaults read com.apple.iphonesimulator CurrentDeviceUDID 2>/dev/null || true)
    if [[ -n "$current_visible_id" && "$current_visible_id" != "$device_id" ]]; then
      echo "Simulator 当前窗口设备与测试设备不一致：窗口=$current_visible_id，测试=$device_id。" >&2
      echo "请在 Simulator 中打开测试设备，或不指定设备让脚本自动选择当前窗口设备。" >&2
      exit 3
    fi
  fi
fi

# 启动后重新读取状态，避免输出启动前的 Shutdown 状态。
device_json=$(xcrun simctl list devices available -j)
device_description=$(python3 - "$device_id" "$device_json" <<'PY'
import json, sys
uid, raw = sys.argv[1], sys.argv[2]
data = json.loads(raw)
for runtime, devices in data.get("devices", {}).items():
    for device in devices:
        if device.get("udid") == uid:
            print(f"{device.get('name')} | {runtime.rsplit('.', 1)[-1]} | {device.get('state')} | {uid}")
            raise SystemExit(0)
raise SystemExit(f"模拟器不可用：{uid}")
PY
)

command=(xcodebuild "$container_flag" "$container_path" -scheme "$scheme"
  -destination "platform=iOS Simulator,id=$device_id"
  -derivedDataPath "$derived_data"
  CODE_SIGNING_ALLOWED=NO test -resultBundlePath "$result_path")
if [[ $verbose -eq 0 ]]; then command+=("-quiet"); fi
if [[ ${#only_tests[@]} -gt 0 ]]; then
  for test_id in "${only_tests[@]}"; do command+=("-only-testing:$test_id"); done
fi

echo "模拟器：$device_description"
if [[ $visible -eq 1 && $dry_run -eq 0 ]]; then
  echo "显示模式：可视（已打开并置前指定 UUID 的 Simulator，测试结束后保持打开）"
elif [[ $visible -eq 1 ]]; then
  echo "显示模式：可视（dry-run，仅解析设备，未打开 Simulator）"
else
  echo "显示模式：无头（Simulator 窗口不会自动打开）"
fi
if [[ $observation_enabled -eq 1 ]]; then
  echo "人工观察：中间页面 ${observe_seconds}s，最终页面 ${final_observe_seconds}s（断言成功后停留）"
else
  echo "人工观察：关闭"
fi
echo "结果：$result_path"
if [[ ${#launch_args[@]} -gt 0 ]]; then
  printf '请求的应用启动参数：'; printf ' %q' "${launch_args[@]}"; printf '\n'
  echo "请确保 UI 测试把这些值赋给 XCUIApplication.launchArguments。"
fi
printf '命令：'; printf ' %q' "${command[@]}"; printf '\n'

if [[ $dry_run -eq 1 ]]; then exit 0; fi
rm -rf "$result_path"
set +e
IOS_FLOW_OBSERVATION_ENABLED="$observation_enabled" \
IOS_FLOW_STEP_OBSERVE_SECONDS="$observe_seconds" \
IOS_FLOW_FINAL_OBSERVE_SECONDS="$final_observe_seconds" \
"${command[@]}"
status=$?
set -e

if [[ -d "$result_path" ]]; then
  echo "xcresult 摘要："
  xcrun xcresulttool get test-results summary --path "$result_path" || true
else
  echo "没有生成 xcresult 结果包。" >&2
fi

worktree_changed=0
if [[ $status -eq 0 && $cache_enabled -eq 1 ]]; then
  final_code_fingerprint=$(compute_code_fingerprint)
  if [[ "$final_code_fingerprint" != "$code_fingerprint" ]]; then
    worktree_changed=1
    status=74
    echo "验证期间工作区发生变化；本次结果不写入成功缓存，请在改动稳定后重新验证。" >&2
    echo "开始指纹：$code_fingerprint" >&2
    echo "结束指纹：$final_code_fingerprint" >&2
  fi
fi

if [[ $status -eq 0 && -d "$result_path" && $cache_enabled -eq 1 ]]; then
  mkdir -p "$cache_dir"
  {
    printf 'result\t%s\n' "$result_path"
    printf 'verified-at\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'reason\t%s\n' "$verification_reason"
    printf 'code-fingerprint\t%s\n' "$code_fingerprint"
    printf 'scope-fingerprint\t%s\n' "$scope_fingerprint"
    printf 'simulator\t%s\n' "$device_description"
  } > "$cache_record"
  echo "已记录成功缓存：$cache_record"
fi

if [[ $status -ne 0 && $worktree_changed -eq 0 && -d "$result_path" ]]; then
  failure_dir="$artifact_root/failures/$cache_key"
  rm -rf "$failure_dir"
  mkdir -p "$failure_dir"
  echo "导出失败附件：$failure_dir"
  xcrun xcresulttool export attachments \
    --path "$result_path" --output-path "$failure_dir" --only-failures || true
  echo "仅在失败时继续检查 test-results activities 和相关运行日志。"
fi
exit "$status"
