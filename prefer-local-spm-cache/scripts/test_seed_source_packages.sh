#!/bin/zsh

set -euo pipefail

SCRIPT_DIR=${0:A:h}
SCRIPT="$SCRIPT_DIR/seed_source_packages.sh"
RUN_SCRIPT="$SCRIPT_DIR/run_xcodebuild.sh"
TEST_ARTIFACT_ROOT=${TEST_ARTIFACT_ROOT:-${TMPDIR:-/tmp}}
/bin/mkdir -p "$TEST_ARTIFACT_ROOT"
TEST_ARTIFACT_ROOT=${TEST_ARTIFACT_ROOT:A}
TEST_ROOT=$(/usr/bin/mktemp -d "$TEST_ARTIFACT_ROOT/prefer-local-spm-cache-test.XXXXXX")
export LOCAL_SPM_DISABLE_DERIVED_DATA_AUTODISCOVERY=1

cleanup() {
  if [[ "$TEST_ROOT" == "$TEST_ARTIFACT_ROOT"/prefer-local-spm-cache-test.* ]]; then
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
  "$TEST_ROOT/target/SourcePackages/checkouts/TargetOnly" \
  "$TEST_ROOT/derived-data/Zeco-first/SourcePackages/checkouts/DerivedFirst" \
  "$TEST_ROOT/derived-data/Zeco-second/SourcePackages/repositories/DerivedSecond" \
  "$TEST_ROOT/derived-data/OtherProject-random/SourcePackages/checkouts/OtherProject" \
  "$TEST_ROOT/project/Zeco.xcworkspace"

print -r -- 'archive-only' > "$TEST_ROOT/archive/SourcePackages/checkouts/ArchiveOnly/value.txt"
print -r -- 'archive-version' > "$TEST_ROOT/archive/SourcePackages/checkouts/AlreadyPresent/value.txt"
print -r -- 'repository' > "$TEST_ROOT/archive/SourcePackages/repositories/ArchiveOnly-repo/value.txt"
print -r -- 'artifact' > "$TEST_ROOT/archive/SourcePackages/artifacts/ArchiveArtifact/value.txt"
print -r -- 'old-checkout-state' > "$TEST_ROOT/archive/SourcePackages/workspace-state.json"
print -r -- 'current-version' > "$TEST_ROOT/target/SourcePackages/checkouts/AlreadyPresent/value.txt"
print -r -- 'target-only' > "$TEST_ROOT/target/SourcePackages/checkouts/TargetOnly/value.txt"
print -r -- 'current-checkout-state' > "$TEST_ROOT/target/SourcePackages/workspace-state.json"
print -r -- 'derived-first' > "$TEST_ROOT/derived-data/Zeco-first/SourcePackages/checkouts/DerivedFirst/value.txt"
print -r -- 'derived-second' > "$TEST_ROOT/derived-data/Zeco-second/SourcePackages/repositories/DerivedSecond/value.txt"
print -r -- 'other-project' > "$TEST_ROOT/derived-data/OtherProject-random/SourcePackages/checkouts/OtherProject/value.txt"
print -r -- 'foreign-state' > "$TEST_ROOT/derived-data/Zeco-first/SourcePackages/workspace-state.json"

# 让 zip 清单明显超过管道缓冲区，覆盖历史上 `pipefail + grep -q` 的 SIGPIPE 误判。
for index in {1..1800}; do
  print -r -- "$index" > "$TEST_ROOT/archive/SourcePackages/checkouts/ArchiveOnly/padding-$index.txt"
done

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

HOME="$TEST_ROOT/no-default-home" LOCAL_SPM_CACHE_ARCHIVE='' "$SCRIPT" \
  --workspace "$TEST_ROOT/project/Zeco.xcworkspace" \
  --derived-data-root "$TEST_ROOT/derived-data" \
  --source-packages-path "$TEST_ROOT/derived-target/SourcePackages"
assert_file_content "$TEST_ROOT/derived-target/SourcePackages/checkouts/DerivedFirst/value.txt" 'derived-first'
assert_file_content "$TEST_ROOT/derived-target/SourcePackages/repositories/DerivedSecond/value.txt" 'derived-second'
[[ ! -e "$TEST_ROOT/derived-target/SourcePackages/checkouts/OtherProject" ]] || {
  print -u2 '不得导入其他项目的 DerivedData 缓存'
  exit 1
}
[[ ! -e "$TEST_ROOT/derived-target/SourcePackages/workspace-state.json" ]] || {
  print -u2 '不得复制其他 DerivedData 的 workspace-state.json'
  exit 1
}

HOME="$TEST_ROOT/no-default-home" \
LOCAL_SPM_CACHE_ARCHIVE='' \
LOCAL_SPM_DERIVED_DATA_ROOTS="$TEST_ROOT/derived-data" \
  "$SCRIPT" \
    --workspace "$TEST_ROOT/project/Zeco.xcworkspace" \
    --source-packages-path "$TEST_ROOT/environment-derived/SourcePackages"
assert_file_content "$TEST_ROOT/environment-derived/SourcePackages/checkouts/DerivedFirst/value.txt" 'derived-first'

/bin/mkdir -p "$TEST_ROOT/discovery-home/Desktop"
/bin/cp "$TEST_ROOT/SourcePackages.zip" "$TEST_ROOT/discovery-home/Desktop/SourcePackages.zip"
HOME="$TEST_ROOT/discovery-home" LOCAL_SPM_CACHE_ARCHIVE='' "$SCRIPT" \
  --source-packages-path "$TEST_ROOT/discovered/MySourcePackages"
assert_file_content "$TEST_ROOT/discovered/MySourcePackages/checkouts/ArchiveOnly/value.txt" 'archive-only'

HOME="$TEST_ROOT/no-default-home" \
LOCAL_SPM_CACHE_ARCHIVE="$TEST_ROOT/SourcePackages.zip" \
  "$SCRIPT" --source-packages-path "$TEST_ROOT/environment/MySourcePackages"
assert_file_content "$TEST_ROOT/environment/MySourcePackages/checkouts/ArchiveOnly/value.txt" 'archive-only'

"$SCRIPT" \
  --archive "$TEST_ROOT/missing.zip" \
  --derived-data-path "$TEST_ROOT/fallback-derived-data"

[[ ! -e "$TEST_ROOT/fallback-derived-data/SourcePackages" ]] || {
  print -u2 '本地 zip 缺失时不应创建缓存目录'
  exit 1
}

fake_xcodebuild="$TEST_ROOT/fake-xcodebuild"
/bin/mkdir -p "$TEST_ROOT/Zeco-sibling/SourcePackages/checkouts/WrapperDerived"
print -r -- 'wrapper-derived' > "$TEST_ROOT/Zeco-sibling/SourcePackages/checkouts/WrapperDerived/value.txt"
{
  print '#!/bin/zsh'
  print 'locked=0'
  print 'for argument in "$@"; do'
  print '  [[ "$argument" == "-skipPackageUpdates" ]] && locked=1'
  print 'done'
  print 'if (( locked )); then'
  print '  print locked >> "$FAKE_MARKER"'
  print '  case "$FAKE_MODE" in'
  print '    success) print "locked build succeeded"; exit 0 ;;'
  print '    package) print -u2 "Could not resolve package dependencies"; exit 74 ;;'
  print '    compile) print -u2 "SwiftCompile error: test failure"; exit 65 ;;'
  print '  esac'
  print 'fi'
  print 'print remote >> "$FAKE_MARKER"'
  print 'print "remote build succeeded"'
} > "$fake_xcodebuild"
/bin/chmod +x "$fake_xcodebuild"

FAKE_MODE=success FAKE_MARKER="$TEST_ROOT/success.marker" \
HOME="$TEST_ROOT/no-default-home" LOCAL_SPM_CACHE_ARCHIVE='' LOCAL_SPM_LOG_DIR="$TEST_ROOT/logs" \
  "$RUN_SCRIPT" -- "$fake_xcodebuild" \
    -workspace "$TEST_ROOT/project/Zeco.xcworkspace" \
    -derivedDataPath "$TEST_ROOT/run-success" \
    -clonedSourcePackagesDirPath "$TEST_ROOT/run-source/SourcePackages" build \
    > "$TEST_ROOT/success.output"
assert_file_content "$TEST_ROOT/success.marker" 'locked'
assert_file_content "$TEST_ROOT/run-source/SourcePackages/checkouts/WrapperDerived/value.txt" 'wrapper-derived'
/usr/bin/grep -q 'locked build succeeded' "$TEST_ROOT/success.output" || {
  print -u2 '本地优先构建应返回成功输出'
  exit 1
}

FAKE_MODE=package FAKE_MARKER="$TEST_ROOT/fallback.marker" \
HOME="$TEST_ROOT/no-default-home" LOCAL_SPM_CACHE_ARCHIVE='' LOCAL_SPM_LOG_DIR="$TEST_ROOT/logs" \
  "$RUN_SCRIPT" -- "$fake_xcodebuild" \
    -workspace "$TEST_ROOT/project/Zeco.xcworkspace" \
    -derivedDataPath "$TEST_ROOT/run-fallback" build \
    > "$TEST_ROOT/fallback.output"
assert_file_content "$TEST_ROOT/fallback.marker" $'locked\nremote'
if /usr/bin/grep -q 'Could not resolve package dependencies' "$TEST_ROOT/fallback.output"; then
  print -u2 '联网回退成功时不应泄露内部本地解析错误'
  exit 1
fi

FAKE_MODE=compile FAKE_MARKER="$TEST_ROOT/compile.marker" \
HOME="$TEST_ROOT/no-default-home" LOCAL_SPM_CACHE_ARCHIVE='' LOCAL_SPM_LOG_DIR="$TEST_ROOT/logs" \
  "$RUN_SCRIPT" -- "$fake_xcodebuild" \
    -workspace "$TEST_ROOT/project/Zeco.xcworkspace" \
    -derivedDataPath "$TEST_ROOT/run-compile" build \
    > "$TEST_ROOT/compile.output" 2>&1 && {
      print -u2 '普通编译错误不应触发联网重试或返回成功'
      exit 1
    }
assert_file_content "$TEST_ROOT/compile.marker" 'locked'
/usr/bin/grep -q 'SwiftCompile error' "$TEST_ROOT/compile.output" || {
  print -u2 '普通编译错误必须原样返回'
  exit 1
}

print 'PASS: DerivedData/zip 动态发现、非覆盖导入、本地优先和依赖失败联网回退均符合预期'
