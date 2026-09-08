#!/bin/zsh

set -u

SCRIPT_DIR=${0:A:h}
SEED_SCRIPT="$SCRIPT_DIR/seed_source_packages.sh"
typeset -a command seed_arguments locked_flags local_command

usage() {
  /bin/cat <<'USAGE'
用法：
  run_xcodebuild.sh -- xcodebuild <原始参数...>

脚本从原始命令读取 -workspace/-project、-derivedDataPath 或
-clonedSourcePackagesDirPath，先补充本机缓存，再使用锁定版本执行。
本地缓存或锁定解析不可用时，会自动重试原始命令并允许正常联网。
USAGE
}

(( $# > 0 )) || { usage >&2; exit 64; }
[[ "$1" == '--' ]] && shift
(( $# > 0 )) || { usage >&2; exit 64; }
command=("$@")

workspace_path=''
project_path=''
derived_data_path=''
source_packages_path=''

for (( index = 1; index <= ${#command[@]}; index += 1 )); do
  case "${command[$index]}" in
    -workspace)
      (( index < ${#command[@]} )) && workspace_path=${command[$(( index + 1 ))]}
      ;;
    -project)
      (( index < ${#command[@]} )) && project_path=${command[$(( index + 1 ))]}
      ;;
    -derivedDataPath)
      (( index < ${#command[@]} )) && derived_data_path=${command[$(( index + 1 ))]}
      ;;
    -clonedSourcePackagesDirPath)
      (( index < ${#command[@]} )) && source_packages_path=${command[$(( index + 1 ))]}
      ;;
  esac
done

seed_arguments=()
if [[ -n "$source_packages_path" ]]; then
  source_packages_path=${source_packages_path:A}
  seed_arguments+=(--source-packages-path "$source_packages_path")
  if [[ -n "$derived_data_path" ]]; then
    derived_data_path=${derived_data_path:A}
    seed_arguments+=(--derived-data-root "${derived_data_path:h}")
  fi
elif [[ -n "$derived_data_path" ]]; then
  derived_data_path=${derived_data_path:A}
  source_packages_path="$derived_data_path/SourcePackages"
  seed_arguments+=(--derived-data-path "$derived_data_path")
else
  print 'LOCAL_CACHE_SKIPPED：原始命令没有显式缓存路径，直接执行并允许联网。'
  exec "${command[@]}"
fi

if [[ -n "$workspace_path" ]]; then
  seed_arguments+=(--workspace "$workspace_path")
elif [[ -n "$project_path" ]]; then
  seed_arguments+=(--project "$project_path")
fi

# 缓存预热失败只是性能问题，不能取代用户要求的构建或测试。
if ! "$SEED_SCRIPT" "${seed_arguments[@]}"; then
  print 'LOCAL_CACHE_SKIPPED：本地缓存预热未完成，直接执行并允许联网。'
  exec "${command[@]}"
fi

locked_flags=()
if (( ${command[(Ie)-onlyUsePackageVersionsFromResolvedFile]} == 0 )); then
  locked_flags+=(-onlyUsePackageVersionsFromResolvedFile)
fi
if (( ${command[(Ie)-skipPackageUpdates]} == 0 )); then
  locked_flags+=(-skipPackageUpdates)
fi

if (( ${#locked_flags[@]} == 0 )); then
  exec "${command[@]}"
fi

log_root=${LOCAL_SPM_LOG_DIR:-${source_packages_path:h}}
/bin/mkdir -p "$log_root" 2>/dev/null || exec "${command[@]}"
attempt_log=$(/usr/bin/mktemp "$log_root/.prefer-local-spm-cache.XXXXXX") || exec "${command[@]}"

cleanup() {
  /bin/rm -f -- "$attempt_log"
}
trap cleanup EXIT

local_command=("${command[@]}" "${locked_flags[@]}")
"${local_command[@]}" >"$attempt_log" 2>&1
local_status=$?

if (( local_status == 0 )); then
  /bin/cat "$attempt_log"
  exit 0
fi

# 只把依赖解析类失败降级到联网重试；代码编译或测试失败应原样返回，避免重复长构建。
if /usr/bin/grep -Eiq \
  'could not resolve package dependencies|package resolution failed|dependencies could not be resolved|package\.resolved|unable to load (the )?package graph|failed to load (the )?package graph|failed to (clone|download|fetch|checkout)|couldn.t (clone|download|fetch|checkout)|check out revision|checkout .*failed|missing package product|package cache is missing|repository .* (corrupt|missing|not found)|the repository could not be found|could not read from remote repository|unable to access .*repository' \
  "$attempt_log"; then
  cleanup
  trap - EXIT
  print 'LOCAL_SPM_REMOTE_FALLBACK：本地缓存或锁定解析不可用，正在使用原始命令联网解析。'
  exec "${command[@]}"
fi

/bin/cat "$attempt_log"
exit "$local_status"
