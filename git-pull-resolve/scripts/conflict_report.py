#!/usr/bin/env python3
"""以 Markdown 输出未解决 Git 索引项；脚本只读，不修改仓库。"""

from __future__ import annotations

import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


CONFLICT_MARKER = re.compile(r"^(<<<<<<<|=======|>>>>>>>)(?: |$)")
STATUS_TYPES = {
    "AA": "双方新增",
    "AU": "当前分支新增/传入分支修改",
    "UA": "当前分支修改/传入分支新增",
    "DD": "双方删除",
    "DU": "当前分支删除/传入分支修改",
    "UD": "当前分支修改/传入分支删除",
    "UU": "内容冲突",
}


def run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """运行只读 Git 命令并捕获文本输出。"""
    return subprocess.run(
        ["git", *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def markdown_path(path: str) -> str:
    """把文件路径格式化为 Markdown 行内代码。"""
    escaped = path.replace("`", "\\`")
    return f"`{escaped}`"


def collect_conflict_statuses() -> dict[str, str]:
    """读取 porcelain 状态并返回所有未合并路径。"""
    result: dict[str, str] = {}
    raw = run_git("status", "--porcelain=v1", "-z").stdout
    fields = raw.split("\0")
    index = 0
    while index < len(fields):
        field = fields[index]
        index += 1
        if not field:
            continue
        status = field[:2]
        path = field[3:]
        if status[0] in "RC" or status[1] in "RC":
            if index < len(fields) and fields[index]:
                path = fields[index]
                index += 1
        if "U" in status or status in {"AA", "DD"}:
            result[path] = status
    return result


def collect_stage_entries() -> dict[str, dict[int, tuple[str, str]]]:
    """读取 base、ours、theirs 三个索引阶段。"""
    entries: dict[str, dict[int, tuple[str, str]]] = defaultdict(dict)
    raw = run_git("ls-files", "-u", "-z").stdout
    for record in raw.split("\0"):
        if not record:
            continue
        metadata, path = record.split("\t", 1)
        mode, object_id, stage = metadata.split()
        entries[path][int(stage)] = (mode, object_id)
    return entries


def find_marker_lines(path: str) -> list[str]:
    """返回文本文件中冲突标记的精确行号。"""
    candidate = Path(path)
    try:
        content = candidate.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    return [
        f"第 {line_number} 行：{line[:120]}"
        for line_number, line in enumerate(content.splitlines(), start=1)
        if CONFLICT_MARKER.match(line)
    ]


def is_rebase_active() -> bool:
    """通过 rebase 状态目录判断是否正在变基，不依赖可能残留的 REBASE_HEAD。"""
    for directory in ("rebase-merge", "rebase-apply"):
        git_path = run_git("rev-parse", "--git-path", directory).stdout.strip()
        if Path(git_path).is_dir():
            return True
    return False


def main() -> int:
    if run_git("rev-parse", "--is-inside-work-tree", check=False).returncode != 0:
        print("错误：请在 Git 工作树内运行此脚本。", file=sys.stderr)
        return 2

    statuses = collect_conflict_statuses()
    entries = collect_stage_entries()
    rebase_active = is_rebase_active()
    paths = sorted(set(statuses) | set(entries))
    if not paths:
        print("# Git 冲突报告\n\n没有未解决的索引项。")
        return 0

    operation = "rebase：ours 是目标基线/upstream，theirs 是正在重放的提交" if rebase_active else "merge 或其他操作：ours 是当前分支，theirs 是传入内容"
    print(f"# Git 冲突报告\n\n操作语义：{operation}\n\n未解决文件数：{len(paths)}")
    for path in paths:
        status = statuses.get(path, "??")
        conflict_type = STATUS_TYPES.get(status, f"未合并状态（{status}）")
        print(f"\n## {markdown_path(path)}\n")
        print(f"- 冲突类型：{conflict_type}")
        available = entries.get(path, {})
        ours_label = "目标基线/upstream（ours）" if rebase_active else "当前分支（ours）"
        theirs_label = "正在重放的提交（theirs）" if rebase_active else "传入内容（theirs）"
        for stage, label in ((1, "共同基线（base）"), (2, ours_label), (3, theirs_label)):
            if stage in available:
                mode, object_id = available[stage]
                print(f"- {label}：`{object_id}`（文件模式 `{mode}`）")
            else:
                print(f"- {label}：不存在")
        markers = find_marker_lines(path)
        if markers:
            print("- 冲突标记位置：")
            for marker in markers:
                print(f"  - {marker}")
        else:
            print("- 冲突标记位置：无；请根据上述索引阶段定位，可能属于二进制、删除、重命名或子模块冲突。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
