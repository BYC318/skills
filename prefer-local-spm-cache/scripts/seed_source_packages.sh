#!/bin/zsh

set -euo pipefail

archive=''
derived_data_path=''
source_packages_path=''
workspace_path=''
project_path=''
project_name=''
imported_count=0
partial_count=0

typeset -a explicit_cache_sources
typeset -a derived_data_roots
typeset -a source_packages_candidates

usage() {
  /bin/cat <<'USAGE'
用法：
  seed_source_packages.sh --derived-data-path <DerivedData路径> [选项]
  seed_source_packages.sh --source-packages-path <SourcePackages路径> [选项]

项目定位（用于只发现同项目的 DerivedData）：
  --workspace <xcworkspace路径>
  --project <xcodeproj路径>

可重复指定的本地来源：
  --cache-source <SourcePackages路径>
  --derived-data-root <DerivedData根目录>

归档来源：
  --archive <SourcePackages.zip路径>

只补充目标中不存在的 checkout、repository 和 artifact，不复制
workspace-state.json。任何本地来源缺失或不可读都会被忽略，后续构建仍可联网。

环境变量：
  LOCAL_SPM_CACHE_ARCHIVE          指定 SourcePackages.zip
  LOCAL_SPM_CACHE_SOURCES          冒号分隔的 SourcePackages 路径
  LOCAL_SPM_DERIVED_DATA_ROOTS     冒号分隔的 DerivedData 根目录
  LOCAL_SPM_CACHE_SEARCH_ROOTS     冒号分隔的 zip 搜索根目录
  LOCAL_SPM_DISABLE_DERIVED_DATA_AUTODISCOVERY=1  关闭 Xcode/系统默认目录发现
USAGE
}

add_derived_data_root() {
  local candidate=$1
  local existing

  [[ -n "$candidate" ]] || return 0
  candidate=${candidate:A}
  for existing in "${derived_data_roots[@]}"; do
    [[ "$existing" == "$candidate" ]] && return 0
  done
  derived_data_roots+=("$candidate")
}

add_source_candidate() {
  local candidate=$1
  local existing

  [[ -d "$candidate" ]] || return 0
  candidate=${candidate:A}
  [[ "$candidate" == "$source_packages_path" ]] && return 0
  for existing in "${source_packages_candidates[@]}"; do
    [[ "$existing" == "$candidate" ]] && return 0
  done
  source_packages_candidates+=("$candidate")
}

import_directory_source() {
  local source=$1
  local group source_item target_item

  for group in checkouts repositories artifacts; do
    for source_item in "$source/$group"/*(N); do
      target_item="$source_packages_path/$group/${source_item:t}"
      [[ -e "$target_item" ]] && continue

      /bin/mkdir -p "$source_packages_path/$group"
      # 单个缓存损坏不应阻断其他来源，更不应阻断随后由 SwiftPM 联网修复。
      if /bin/cp -R "$source_item" "$target_item" 2>/dev/null; then
        (( imported_count += 1 ))
      else
        /bin/rm -rf -- "$target_item" 2>/dev/null || true
        (( partial_count += 1 ))
      fi
    done
  done
}

import_archive_source() {
  local archive_path=$1
  local entries group name staged_item target_item stage
  typeset -a extract_patterns names

  [[ -r "$archive_path" ]] || return 0
  archive_path=${archive_path:A}
  entries=$(/usr/bin/zipinfo -1 "$archive_path" 2>/dev/null) || {
    (( partial_count += 1 ))
    return 0
  }

  # 完整读取清单，避免 pipefail 下 grep -q 提前关闭大清单造成 SIGPIPE 误判。
  if print -r -- "$entries" | /usr/bin/env LC_ALL=C /usr/bin/awk '
    BEGIN { unsafe = 0 }
    /^\// || /(^|\/)\.\.(\/|$)/ { unsafe = 1 }
    END { exit unsafe ? 0 : 1 }
  '; then
    (( partial_count += 1 ))
    return 0
  fi

  extract_patterns=()
  for group in checkouts repositories artifacts; do
    names=("${(@f)$(
      print -r -- "$entries" |
        /usr/bin/env LC_ALL=C /usr/bin/awk -F/ -v group="$group" '
          $1 == "SourcePackages" && $2 == group && NF >= 4 && $3 != "" {
            print $3
          }
        ' |
        /usr/bin/env LC_ALL=C /usr/bin/sort -u
    )}")

    for name in "${names[@]}"; do
      [[ -n "$name" ]] || continue
      if [[ ! -e "$source_packages_path/$group/$name" ]]; then
        extract_patterns+=("SourcePackages/$group/$name/*")
      fi
    done
  done

  (( ${#extract_patterns[@]} > 0 )) || return 0

  /bin/mkdir -p "${source_packages_path:h}"
  stage=$(/usr/bin/mktemp -d "${source_packages_path:h}/.prefer-local-spm-cache.XXXXXX") || {
    (( partial_count += 1 ))
    return 0
  }

  if ! /usr/bin/unzip -q -n "$archive_path" "${extract_patterns[@]}" -d "$stage"; then
    /bin/rm -rf -- "$stage"
    (( partial_count += 1 ))
    return 0
  fi

  for group in checkouts repositories artifacts; do
    for staged_item in "$stage/SourcePackages/$group"/*(N); do
      target_item="$source_packages_path/$group/${staged_item:t}"
      [[ -e "$target_item" ]] && continue
      /bin/mkdir -p "$source_packages_path/$group"
      if /bin/mv "$staged_item" "$target_item" 2>/dev/null; then
        (( imported_count += 1 ))
      else
        (( partial_count += 1 ))
      fi
    done
  done

  /bin/rm -rf -- "$stage"
}

while (( $# > 0 )); do
  case "$1" in
    --archive)
      (( $# >= 2 )) || { usage >&2; exit 64; }
      archive=$2
      shift 2
      ;;
    --cache-source)
      (( $# >= 2 )) || { usage >&2; exit 64; }
      explicit_cache_sources+=("$2")
      shift 2
      ;;
    --derived-data-root)
      (( $# >= 2 )) || { usage >&2; exit 64; }
      add_derived_data_root "$2"
      shift 2
      ;;
    --derived-data-path)
      (( $# >= 2 )) || { usage >&2; exit 64; }
      derived_data_path=$2
      shift 2
      ;;
    --source-packages-path)
      (( $# >= 2 )) || { usage >&2; exit 64; }
      source_packages_path=$2
      shift 2
      ;;
    --workspace)
      (( $# >= 2 )) || { usage >&2; exit 64; }
      workspace_path=$2
      shift 2
      ;;
    --project)
      (( $# >= 2 )) || { usage >&2; exit 64; }
      project_path=$2
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      print -u2 "未知参数：$1"
      usage >&2
      exit 64
      ;;
  esac
done

if [[ -n "$derived_data_path" && -n "$source_packages_path" ]]; then
  print -u2 '只能指定 --derived-data-path 或 --source-packages-path 之一。'
  exit 64
fi

if [[ -n "$workspace_path" && -n "$project_path" ]]; then
  print -u2 '只能指定 --workspace 或 --project 之一。'
  exit 64
fi

if [[ -n "$derived_data_path" ]]; then
  derived_data_path=${derived_data_path:A}
  source_packages_path="$derived_data_path/SourcePackages"
  add_derived_data_root "${derived_data_path:h}"
elif [[ -n "$source_packages_path" ]]; then
  source_packages_path=${source_packages_path:A}
else
  print -u2 '缺少目标路径。'
  usage >&2
  exit 64
fi

if [[ -n "$workspace_path" ]]; then
  project_name=${workspace_path:t:r}
elif [[ -n "$project_path" ]]; then
  project_name=${project_path:t:r}
fi

for candidate in "${explicit_cache_sources[@]}"; do
  add_source_candidate "$candidate"
done

if [[ -n "${LOCAL_SPM_CACHE_SOURCES:-}" ]]; then
  for candidate in "${(@s/:/)LOCAL_SPM_CACHE_SOURCES}"; do
    add_source_candidate "$candidate"
  done
fi

if [[ -n "${LOCAL_SPM_DERIVED_DATA_ROOTS:-}" ]]; then
  for candidate in "${(@s/:/)LOCAL_SPM_DERIVED_DATA_ROOTS}"; do
    add_derived_data_root "$candidate"
  done
fi

# 自动发现默认开启；隔离测试或受控环境可显式关闭，本次目标的同级目录仍会保留。
if [[ "${LOCAL_SPM_DISABLE_DERIVED_DATA_AUTODISCOVERY:-0}" != '1' ]]; then
  xcode_derived_data_root=$(/usr/bin/defaults read com.apple.dt.Xcode IDECustomDerivedDataLocation 2>/dev/null || true)
  if [[ "$xcode_derived_data_root" == /* ]]; then
    add_derived_data_root "$xcode_derived_data_root"
  fi

  if [[ -n "${HOME:-}" ]]; then
    add_derived_data_root "$HOME/Library/Developer/Xcode/DerivedData"
  fi
fi

# 只遍历当前 workspace/project 同名前缀，避免把另一个项目的 checkout 当成可信源码。
if [[ -n "$project_name" ]]; then
  for root in "${derived_data_roots[@]}"; do
    [[ -d "$root" ]] || continue
    for candidate in \
      "$root/$project_name"-*/SourcePackages(N) \
      "$root/$project_name/SourcePackages"(N); do
      add_source_candidate "$candidate"
    done
  done
fi

for candidate in "${source_packages_candidates[@]}"; do
  import_directory_source "$candidate"
done

if [[ -z "$archive" && -n "${LOCAL_SPM_CACHE_ARCHIVE:-}" ]]; then
  archive=$LOCAL_SPM_CACHE_ARCHIVE
fi

if [[ -z "$archive" && -n "${LOCAL_SPM_CACHE_SEARCH_ROOTS:-}" ]]; then
  for root in "${(@s/:/)LOCAL_SPM_CACHE_SEARCH_ROOTS}"; do
    for candidate in "$root/SourcePackages.zip" "$root"/*/SourcePackages.zip(N); do
      if [[ -r "$candidate" ]]; then
        archive=$candidate
        break 2
      fi
    done
  done
fi

if [[ -z "$archive" && -n "${HOME:-}" ]]; then
  for candidate in \
    "$HOME/Desktop/SourcePackages.zip" \
    "$HOME/Downloads/SourcePackages.zip" \
    "$HOME/SourcePackages.zip" \
    "$HOME"/*/SourcePackages.zip(N); do
    if [[ -r "$candidate" ]]; then
      archive=$candidate
      break
    fi
  done
fi

if [[ -n "$archive" ]]; then
  import_archive_source "$archive"
fi

if (( imported_count > 0 )); then
  if (( partial_count > 0 )); then
    print "LOCAL_CACHE_PARTIAL：已补充 $imported_count 个缓存目录；其余依赖交由 SwiftPM 联网修复：$source_packages_path"
  else
    print "LOCAL_CACHE_READY：已补充 $imported_count 个本地缓存目录：$source_packages_path"
  fi
elif [[ -d "$source_packages_path/checkouts" && -n "$(/bin/ls -A "$source_packages_path/checkouts" 2>/dev/null)" ]]; then
  print "LOCAL_CACHE_READY：目标已包含本地 checkout：$source_packages_path"
else
  print "LOCAL_CACHE_SKIPPED：未发现可复用的本地缓存，后续构建将正常联网：$source_packages_path"
fi
