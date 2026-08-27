#!/bin/zsh

set -euo pipefail

DEFAULT_ARCHIVE='/Users/kf002/Desktop/SourcePackages.zip'

archive=$DEFAULT_ARCHIVE
derived_data_path=''
source_packages_path=''

usage() {
  /bin/cat <<'USAGE'
用法：
  seed_source_packages.sh --derived-data-path <DerivedData路径> [--archive <zip路径>]
  seed_source_packages.sh --source-packages-path <SourcePackages路径> [--archive <zip路径>]

只补充目标中不存在的 checkout、repository 和 artifact。不会复制
workspace-state.json，也不会禁止后续 xcodebuild 联网补齐缺失依赖。
USAGE
}

while (( $# > 0 )); do
  case "$1" in
    --archive)
      (( $# >= 2 )) || { usage >&2; exit 64; }
      archive=$2
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

if [[ -n "$derived_data_path" ]]; then
  source_packages_path="${derived_data_path:A}/SourcePackages"
elif [[ -n "$source_packages_path" ]]; then
  source_packages_path=${source_packages_path:A}
else
  print -u2 '缺少目标路径。'
  usage >&2
  exit 64
fi

if [[ ! -r "$archive" ]]; then
  print "LOCAL_CACHE_SKIPPED：本地缓存不可读，后续构建可正常联网获取：$archive"
  exit 0
fi

archive=${archive:A}

entries=$(/usr/bin/zipinfo -1 "$archive" 2>/dev/null) || {
  print "LOCAL_CACHE_SKIPPED：无法读取 zip，后续构建可正常联网获取：$archive"
  exit 0
}

if print -r -- "$entries" | /usr/bin/grep -Eq '(^/|(^|/)\.\.(/|$))'; then
  print 'LOCAL_CACHE_SKIPPED：zip 包含不安全路径，后续构建可正常联网获取。'
  exit 0
fi

if ! print -r -- "$entries" | /usr/bin/grep -q '^SourcePackages/checkouts/'; then
  print 'LOCAL_CACHE_SKIPPED：zip 中没有 SourcePackages/checkouts，后续构建可正常联网获取。'
  exit 0
fi

typeset -a extract_patterns
extract_patterns=()

for group in checkouts repositories artifacts; do
  names=("${(@f)$(
    print -r -- "$entries" |
      /usr/bin/awk -F/ -v group="$group" '
        $1 == "SourcePackages" && $2 == group && NF >= 4 && $3 != "" {
          print $3
        }
      ' |
      /usr/bin/sort -u
  )}")

  for name in "${names[@]}"; do
    [[ -n "$name" ]] || continue
    if [[ ! -e "$source_packages_path/$group/$name" ]]; then
      extract_patterns+=("SourcePackages/$group/$name/*")
    fi
  done
done

if (( ${#extract_patterns[@]} == 0 )); then
  print "LOCAL_CACHE_READY：目标已有 zip 中的全部缓存：$source_packages_path"
  exit 0
fi

/bin/mkdir -p "${source_packages_path:h}"
stage=$(/usr/bin/mktemp -d "${source_packages_path:h}/.prefer-local-spm-cache.XXXXXX")

cleanup() {
  if [[ -n "${stage:-}" && "$stage" == ${source_packages_path:h}/.prefer-local-spm-cache.* ]]; then
    /bin/rm -rf -- "$stage"
  fi
}

trap cleanup EXIT

if ! /usr/bin/unzip -q -n "$archive" "${extract_patterns[@]}" -d "$stage"; then
  print 'LOCAL_CACHE_PARTIAL：本地补充未完整完成，后续构建可正常联网修复。'
  exit 0
fi

imported_count=0

for group in checkouts repositories artifacts; do
  /bin/mkdir -p "$source_packages_path/$group"

  for staged_item in "$stage/SourcePackages/$group"/*(N); do
    target_item="$source_packages_path/$group/${staged_item:t}"
    [[ -e "$target_item" ]] && continue
    /bin/mv "$staged_item" "$target_item"
    (( imported_count += 1 ))
  done
done

print "LOCAL_CACHE_READY：已补充 $imported_count 个本地缓存目录：$source_packages_path"
