#!/bin/zsh

set -euo pipefail

SCRIPT_DIR=${0:A:h}
SCRIPT="$SCRIPT_DIR/seed_source_packages.sh"
TEST_ROOT=$(/usr/bin/mktemp -d /tmp/prefer-local-spm-cache-test.XXXXXX)

cleanup() {
  if [[ "$TEST_ROOT" == /tmp/prefer-local-spm-cache-test.* ]]; then
    /bin/rm -rf -- "$TEST_ROOT"
  fi
}

assert_file_content() {
  local path=$1
  local expected=$2
  local actual

  actual=$(/bin/cat "$path")
  [[ "$actual" == "$expected" ]] || {
    print -u2 "断言失败：$path 期望 '$expected'，实际 '$actual'"
    exit 1
  }
}

trap cleanup EXIT

/bin/mkdir -p \
  "$TEST_ROOT/archive/SourcePackages/checkouts/ArchiveOnly" \
  "$TEST_ROOT/archive/SourcePackages/checkouts/AlreadyPresent" \
  "$TEST_ROOT/archive/SourcePackages/repositories/ArchiveOnly-repo" \
  "$TEST_ROOT/archive/SourcePackages/artifacts/ArchiveArtifact" \
  "$TEST_ROOT/target/SourcePackages/checkouts/AlreadyPresent" \
  "$TEST_ROOT/target/SourcePackages/checkouts/TargetOnly"

print -r -- 'archive-only' > "$TEST_ROOT/archive/SourcePackages/checkouts/ArchiveOnly/value.txt"
print -r -- 'archive-version' > "$TEST_ROOT/archive/SourcePackages/checkouts/AlreadyPresent/value.txt"
print -r -- 'repository' > "$TEST_ROOT/archive/SourcePackages/repositories/ArchiveOnly-repo/value.txt"
print -r -- 'artifact' > "$TEST_ROOT/archive/SourcePackages/artifacts/ArchiveArtifact/value.txt"
print -r -- 'old-checkout-state' > "$TEST_ROOT/archive/SourcePackages/workspace-state.json"
print -r -- 'current-version' > "$TEST_ROOT/target/SourcePackages/checkouts/AlreadyPresent/value.txt"
print -r -- 'target-only' > "$TEST_ROOT/target/SourcePackages/checkouts/TargetOnly/value.txt"
print -r -- 'current-checkout-state' > "$TEST_ROOT/target/SourcePackages/workspace-state.json"

(
  cd "$TEST_ROOT/archive"
  /usr/bin/zip -qr "$TEST_ROOT/SourcePackages.zip" SourcePackages
)

"$SCRIPT" \
  --archive "$TEST_ROOT/SourcePackages.zip" \
  --source-packages-path "$TEST_ROOT/target/SourcePackages"

assert_file_content "$TEST_ROOT/target/SourcePackages/checkouts/ArchiveOnly/value.txt" 'archive-only'
assert_file_content "$TEST_ROOT/target/SourcePackages/checkouts/AlreadyPresent/value.txt" 'current-version'
assert_file_content "$TEST_ROOT/target/SourcePackages/checkouts/TargetOnly/value.txt" 'target-only'
assert_file_content "$TEST_ROOT/target/SourcePackages/repositories/ArchiveOnly-repo/value.txt" 'repository'
assert_file_content "$TEST_ROOT/target/SourcePackages/artifacts/ArchiveArtifact/value.txt" 'artifact'
assert_file_content "$TEST_ROOT/target/SourcePackages/workspace-state.json" 'current-checkout-state'

"$SCRIPT" \
  --archive "$TEST_ROOT/SourcePackages.zip" \
  --source-packages-path "$TEST_ROOT/custom/MySourcePackages"

assert_file_content "$TEST_ROOT/custom/MySourcePackages/checkouts/ArchiveOnly/value.txt" 'archive-only'
[[ ! -e "$TEST_ROOT/custom/MySourcePackages/workspace-state.json" ]] || {
  print -u2 '新缓存目录不应复制 zip 内的 workspace-state.json'
  exit 1
}

"$SCRIPT" \
  --archive "$TEST_ROOT/missing.zip" \
  --derived-data-path "$TEST_ROOT/fallback-derived-data"

[[ ! -e "$TEST_ROOT/fallback-derived-data/SourcePackages" ]] || {
  print -u2 '本地 zip 缺失时不应创建缓存目录'
  exit 1
}

print 'PASS: 本地 SourcePackages 缓存仅补缺失内容，并允许远程回退'
