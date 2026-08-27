#!/bin/bash
set -euo pipefail

COMMAND=""
REPO_INPUT=""
REPO_DIR=""
REPO_EXPLICIT="false"
BRANCH_NAME=""
BASE_BRANCH=""
BASE_EXPLICIT="false"
POD_DIR_INPUT=""
POD_EXPLICIT="false"
WORKTREE_PATH=""
MAIN_WORKTREE_PATH=""
POD_DIR=""
PODS_INSTALLED="false"

print_usage() {
    echo "用法："
    echo "  worktree.sh [--repo=路径] list"
    echo "  worktree.sh [--repo=路径] create 分支名 [--base=分支] [--pod-dir=相对路径]"
    echo "  worktree.sh [--repo=路径] remove 分支名"
    echo
    echo "规则："
    echo "  --repo、--base、--pod-dir 必须使用等号传值。"
    echo "  未指定 --repo 时使用当前目录所在的 Git 仓库。"
    echo "  create 默认使用远端 HEAD 指向的基线；无法识别时必须指定 --base。"
    echo "  新 worktree 创建在主仓库同级目录；remove 不支持强制删除。"
}

die() {
    echo "错误：$*" >&2
    print_usage >&2
    exit 1
}

parse_args() {
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --repo=*) REPO_INPUT="${1#--repo=}"; REPO_EXPLICIT="true" ;;
            --base=*) BASE_BRANCH="${1#--base=}"; BASE_EXPLICIT="true" ;;
            --pod-dir=*) POD_DIR_INPUT="${1#--pod-dir=}"; POD_EXPLICIT="true" ;;
            -h|--help) print_usage; exit 0 ;;
            --repo|--base|--pod-dir)
                die "选项必须使用等号传值：${1}=值"
                ;;
            --*) die "未知选项：${1}" ;;
            create|remove|list)
                if [ -z "${COMMAND}" ]; then
                    COMMAND="$1"
                else
                    [ -z "${BRANCH_NAME}" ] || die "多余参数：${1}"
                    BRANCH_NAME="$1"
                fi
                ;;
            *)
                [ -n "${COMMAND}" ] || die "请先指定 create、remove 或 list"
                [ -z "${BRANCH_NAME}" ] || die "多余参数：${1}"
                BRANCH_NAME="$1"
                ;;
        esac
        shift
    done

    [ -n "${COMMAND}" ] || die "请先指定 create、remove 或 list"
    if [ "${COMMAND}" = "create" ] || [ "${COMMAND}" = "remove" ]; then
        [ -n "${BRANCH_NAME}" ] || die "${COMMAND} 必须指定分支名"
    fi
    [ "${REPO_EXPLICIT}" != "true" ] || [ -n "${REPO_INPUT}" ] || die "--repo 不能使用空值"
    [ "${BASE_EXPLICIT}" != "true" ] || [ -n "${BASE_BRANCH}" ] || die "--base 不能使用空值"
    [ "${POD_EXPLICIT}" != "true" ] || [ -n "${POD_DIR_INPUT}" ] || die "--pod-dir 不能使用空值"

    if [ "${COMMAND}" = "list" ]; then
        [ -z "${BRANCH_NAME}" ] || die "list 不允许分支名"
        [ "${BASE_EXPLICIT}" != "true" ] || die "list 不允许 --base"
        [ "${POD_EXPLICIT}" != "true" ] || die "list 不允许 --pod-dir"
    fi
    if [ "${COMMAND}" = "remove" ]; then
        [ "${BASE_EXPLICIT}" != "true" ] || die "remove 不允许 --base"
        [ "${POD_EXPLICIT}" != "true" ] || die "remove 不允许 --pod-dir"
    fi
}

resolve_repo() {
    local source_dir
    if [ -n "${REPO_INPUT}" ]; then
        source_dir="${REPO_INPUT}"
    else
        source_dir="${PWD}"
    fi

    REPO_DIR="$(git -C "${source_dir}" rev-parse --show-toplevel 2>/dev/null)" ||
        die "不是有效的 Git 仓库：${source_dir}"
    REPO_DIR="$(cd "${REPO_DIR}" && pwd -P)"
}

resolve_base_branch() {
    local default_ref
    [ -n "${BASE_BRANCH}" ] && return 0
    default_ref="$(git -C "${REPO_DIR}" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || true)"
    case "${default_ref}" in
        origin/*) BASE_BRANCH="${default_ref#origin/}" ;;
        *) die "无法识别远端默认基线，请使用 --base=分支指定" ;;
    esac
}

worktree_dir_name() {
    printf '%s\n' "${1//\//-}"
}

resolve_worktree_path() {
    local parent dir_name
    parent="$(dirname "${REPO_DIR}")"
    dir_name="$(worktree_dir_name "${BRANCH_NAME}")"
    WORKTREE_PATH="${parent}/${dir_name}"
}

validate_create() {
    git check-ref-format --branch "${BRANCH_NAME}" >/dev/null 2>&1 ||
        die "分支名不合法：${BRANCH_NAME}"
    [ ! -e "${WORKTREE_PATH}" ] ||
        die "目标目录已存在：${WORKTREE_PATH}"
    git -C "${REPO_DIR}" show-ref --verify --quiet "refs/heads/${BRANCH_NAME}" &&
        die "本地分支已存在：${BRANCH_NAME}"
    git -C "${REPO_DIR}" show-ref --verify --quiet "refs/remotes/origin/${BASE_BRANCH}" ||
        die "远程基准分支不存在：origin/${BASE_BRANCH}"
}

collect_find_results() {
    local label output result
    label="$1"
    shift
    FIND_RESULTS=()

    if ! output="$(find "$@")"; then
        echo "错误：搜索 ${label} 失败" >&2
        [ ! -d "${WORKTREE_PATH}" ] || echo "Worktree 保留位置：${WORKTREE_PATH}" >&2
        return 1
    fi

    while IFS= read -r result; do
        [ -n "${result}" ] && FIND_RESULTS[${#FIND_RESULTS[@]}]="${result}"
    done <<EOF
${output}
EOF
    return 0
}

validate_implicit_pod_dir() {
    local result relative_path
    [ -z "${POD_DIR_INPUT}" ] || return 0

    collect_find_results "Podfile" "${REPO_DIR}" \
        \( -name .git -o -name Pods \) -prune -o \
        -type f -name Podfile -print
    [ "${#FIND_RESULTS[@]}" -le 1 ] && return 0

    for result in "${FIND_RESULTS[@]}"; do
        relative_path="${result#"${REPO_DIR}"/}"
        echo "找到 Podfile：${relative_path}" >&2
    done
    die "找到多个 Podfile，请在创建前使用 --pod-dir=相对路径 指定"
}

validate_pod_dir_input() {
    local candidate component remaining depth future_parent future_root
    local future_candidate source_candidate
    [ -n "${POD_DIR_INPUT}" ] || return 0

    case "${POD_DIR_INPUT}" in
        /*) die "--pod-dir 必须使用相对路径" ;;
    esac

    future_parent="$(cd "$(dirname "${WORKTREE_PATH}")" && pwd -P)" ||
        die "无法解析 worktree 父目录"
    future_root="${future_parent}/$(basename "${WORKTREE_PATH}")"
    future_candidate="${future_root}"
    source_candidate="${REPO_DIR}"
    remaining="${POD_DIR_INPUT}"
    depth=0
    while :; do
        case "${remaining}" in
            */*) component="${remaining%%/*}"; remaining="${remaining#*/}" ;;
            *) component="${remaining}"; remaining="" ;;
        esac

        case "${component}" in
            ""|.) ;;
            ..)
                [ "${depth}" -gt 0 ] || die "--pod-dir 必须位于 worktree 内部"
                depth=$((depth - 1))
                future_candidate="$(dirname "${future_candidate}")"
                source_candidate="$(dirname "${source_candidate}")"
                ;;
            *)
                depth=$((depth + 1))
                future_candidate="${future_candidate}/${component}"
                source_candidate="${source_candidate}/${component}"
                [ ! -L "${source_candidate}" ] ||
                    die "--pod-dir 不允许包含符号链接：${POD_DIR_INPUT}"
                ;;
        esac
        [ -n "${remaining}" ] || break
    done

    case "${future_candidate}" in
        "${future_root}"|"${future_root}"/*) ;;
        *) die "--pod-dir 必须位于 worktree 内部" ;;
    esac

    candidate="${REPO_DIR}/${POD_DIR_INPUT}"
    [ -d "${candidate}" ] || die "--pod-dir 目录不存在：${POD_DIR_INPUT}"
    candidate="$(cd "${candidate}" && pwd -P)" ||
        die "--pod-dir 无法解析：${POD_DIR_INPUT}"
    case "${candidate}" in
        "${REPO_DIR}"|"${REPO_DIR}"/*) ;;
        *) die "--pod-dir 必须位于 worktree 内部" ;;
    esac
    [ -f "${candidate}/Podfile" ] ||
        die "--pod-dir 目录中未找到 Podfile：${POD_DIR_INPUT}"
}

resolve_pod_dir() {
    local candidate
    POD_DIR=""

    if [ -n "${POD_DIR_INPUT}" ]; then
        candidate="${WORKTREE_PATH}/${POD_DIR_INPUT}"
        [ -d "${candidate}" ] || die "--pod-dir 目录不存在：${POD_DIR_INPUT}"
        candidate="$(cd "${candidate}" && pwd -P)" ||
            die "--pod-dir 无法解析：${POD_DIR_INPUT}"
        case "${candidate}" in
            "${WORKTREE_PATH}"|"${WORKTREE_PATH}"/*) ;;
            *) die "--pod-dir 必须位于 worktree 内部" ;;
        esac
        [ -f "${candidate}/Podfile" ] ||
            die "--pod-dir 目录中未找到 Podfile：${POD_DIR_INPUT}"
        POD_DIR="${candidate}"
        return 0
    fi

    collect_find_results "Podfile" "${WORKTREE_PATH}" \
        \( -name .git -o -name Pods \) -prune -o \
        -type f -name Podfile -print
    case "${#FIND_RESULTS[@]}" in
        0) ;;
        1) POD_DIR="$(dirname "${FIND_RESULTS[0]}")" ;;
        *)
            local result
            for result in "${FIND_RESULTS[@]}"; do
                echo "找到 Podfile：${result}" >&2
            done
            echo "Worktree 保留位置：${WORKTREE_PATH}" >&2
            die "找到多个 Podfile，请使用 --pod-dir=相对路径 指定"
            ;;
    esac
}

install_pods() {
    [ -n "${POD_DIR}" ] || return 0
    if ! command -v pod >/dev/null 2>&1; then
        echo "错误：未找到 pod 命令" >&2
        echo "Worktree 保留位置：${WORKTREE_PATH}" >&2
        return 1
    fi
    if ! (cd "${POD_DIR}" && pod install); then
        echo "Worktree 保留位置：${WORKTREE_PATH}" >&2
        return 1
    fi
    PODS_INSTALLED="true"
}

init_codegraph() {
    if ! command -v codegraph >/dev/null 2>&1; then
        echo "警告：未找到 codegraph 命令，跳过 CodeGraph 初始化" >&2
        return 0
    fi
    if ! (cd "${WORKTREE_PATH}" && codegraph init); then
        echo "警告：CodeGraph 初始化失败，继续打开工程" >&2
    fi
}

open_xcode() {
    local search_root candidate result
    if [ -n "${POD_DIR}" ]; then search_root="${POD_DIR}"; else search_root="${WORKTREE_PATH}"; fi
    collect_find_results "Xcode workspace" "${search_root}" \
        \( -name .git -o -name Pods -o -name '*.xcodeproj' \) -prune -o \
        -type d -name '*.xcworkspace' -print
    if [ "${#FIND_RESULTS[@]}" -eq 0 ]; then
        collect_find_results "Xcode project" "${search_root}" \
            \( -name .git -o -name Pods \) -prune -o \
            -type d -name '*.xcodeproj' -print
    fi
    case "${#FIND_RESULTS[@]}" in
        0) echo "未找到 Xcode workspace 或 project" ;;
        1)
            candidate="${FIND_RESULTS[0]}"
            if ! command -v open >/dev/null 2>&1; then
                echo "错误：未找到 open 命令" >&2
                echo "Worktree 保留位置：${WORKTREE_PATH}" >&2
                return 1
            fi
            if ! (cd "$(dirname "${candidate}")" && open "${candidate}"); then
                echo "Worktree 保留位置：${WORKTREE_PATH}" >&2
                return 1
            fi
            ;;
        *)
            for result in "${FIND_RESULTS[@]}"; do echo "找到 Xcode 候选项：${result}" >&2; done
            echo "错误：找到多个 Xcode workspace 或 project" >&2
            echo "Worktree 保留位置：${WORKTREE_PATH}" >&2
            return 1
            ;;
    esac
}

cmd_create() {
    resolve_worktree_path
    validate_create
    validate_pod_dir_input
    validate_implicit_pod_dir
    git -C "${REPO_DIR}" worktree add -b "${BRANCH_NAME}" "${WORKTREE_PATH}" "origin/${BASE_BRANCH}"
    resolve_pod_dir
    install_pods
    init_codegraph
    open_xcode
    echo "Worktree 已创建：${WORKTREE_PATH}"
    [ "${PODS_INSTALLED}" = "true" ] && echo "Pods 已安装"
    return 0
}

resolve_remove_worktree_path() {
    local line porcelain stanza_branch stanza_path found
    porcelain="$(git -C "${REPO_DIR}" worktree list --porcelain)" ||
        die "无法读取当前仓库的 worktree 列表"
    stanza_branch=""; stanza_path=""; found="false"
    MAIN_WORKTREE_PATH=""
    while IFS= read -r line; do
        case "${line}" in
            worktree\ *)
                stanza_path="${line#worktree }"
                [ -n "${MAIN_WORKTREE_PATH}" ] || MAIN_WORKTREE_PATH="${stanza_path}"
                ;;
            branch\ *) stanza_branch="${line#branch }" ;;
            "")
                if [ "${stanza_branch}" = "refs/heads/${BRANCH_NAME}" ]; then
                    [ "${found}" = "false" ] || die "同一分支匹配到多个 worktree：${BRANCH_NAME}"
                    WORKTREE_PATH="${stanza_path}"
                    found="true"
                fi
                stanza_branch=""; stanza_path=""
                ;;
        esac
    done <<EOF
${porcelain}

EOF
    [ "${found}" = "true" ] || die "未找到分支对应的 worktree：${BRANCH_NAME}"
    [ "${WORKTREE_PATH}" != "${MAIN_WORKTREE_PATH}" ] ||
        die "不能通过 remove 删除主工作区：${WORKTREE_PATH}"
}

remove_local_branch_safely() {
    local repo branch
    repo="$1"; branch="$2"
    git -C "${repo}" show-ref --verify --quiet "refs/heads/${branch}" || return 0
    if ! git -C "${repo}" branch -d "${branch}"; then
        echo "本地分支已保留（含未合并提交）：${branch}" >&2
        echo "请在确认后手动处理该分支。" >&2
        return 1
    fi
}

cmd_remove() {
    local branch_retained
    git check-ref-format --branch "${BRANCH_NAME}" >/dev/null 2>&1 || die "分支名不合法：${BRANCH_NAME}"
    resolve_remove_worktree_path
    if ! git -C "${MAIN_WORKTREE_PATH}" worktree remove "${WORKTREE_PATH}"; then
        echo "Worktree 与本地分支均已保留。" >&2
        return 1
    fi
    branch_retained="false"
    remove_local_branch_safely "${MAIN_WORKTREE_PATH}" "${BRANCH_NAME}" || branch_retained="true"
    git -C "${MAIN_WORKTREE_PATH}" worktree prune
    if [ "${branch_retained}" = "true" ]; then
        echo "Worktree 已删除，但本地分支仍保留：${BRANCH_NAME}" >&2
        return 2
    fi
    echo "Worktree 与本地分支已安全删除：${WORKTREE_PATH}"
}

cmd_list() { git -C "${REPO_DIR}" worktree list; }

main() {
    parse_args "$@"
    resolve_repo
    [ "${COMMAND}" = "create" ] && resolve_base_branch
    case "${COMMAND}" in
        create) cmd_create ;;
        remove) cmd_remove ;;
        list) cmd_list ;;
    esac
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then main "$@"; fi
