#!/usr/bin/env python3
"""只读识别 Git 项目，并输出 project-memory 使用的稳定 JSON 身份。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit


DEFAULT_KNOWLEDGE_ROOT = str(
    Path.home() / "Documents" / "Obsidian" / "GS" / "TaskSummary"
)


def git(cwd: str, *args: str) -> str | None:
    result = subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True, check=False
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def choose_remote(cwd: str) -> str | None:
    origin = git(cwd, "config", "--get", "remote.origin.url")
    if origin:
        return origin
    remotes = git(cwd, "remote")
    if not remotes:
        return None
    first = sorted(remotes.splitlines())[0]
    return git(cwd, "config", "--get", f"remote.{first}.url")


def normalize_remote(remote: str) -> tuple[str, str]:
    """返回 canonical project ID 与已移除凭据的展示地址。"""
    value = remote.strip()
    scp = re.fullmatch(r"(?:[^@/:]+@)?([^/:]+):(.+)", value)
    if scp and "://" not in value:
        host = scp.group(1).lower()
        path = scp.group(2)
        port = None
    else:
        parsed = urlsplit(value if "://" in value else f"file://{value}")
        if parsed.scheme == "file" or not parsed.hostname:
            raise ValueError("remote 不是可识别的网络 Git 地址")
        host = parsed.hostname.lower()
        port = parsed.port
        default_port = {"ssh": 22, "http": 80, "https": 443}.get(parsed.scheme.lower())
        if port == default_port:
            port = None
        path = parsed.path

    clean_path = unquote(path).strip("/")
    clean_path = re.sub(r"\.git$", "", clean_path, flags=re.IGNORECASE)
    if not clean_path or any(part in {"", ".", ".."} for part in clean_path.split("/")):
        raise ValueError("remote 缺少有效仓库路径")
    authority = f"{host}:{port}" if port else host
    project_id = f"{authority}/{clean_path}"
    return project_id, project_id


def safe_directory(project_id: str) -> str:
    parts = project_id.split("/")
    cleaned = [re.sub(r"[^\w.-]+", "-", part, flags=re.UNICODE).strip("-") for part in parts]
    if not all(cleaned):
        raise ValueError("项目 ID 无法转换为安全目录名")
    return "--".join(cleaned)


def identify(cwd: str, knowledge_root: str, project_name: str | None = None) -> dict[str, str]:
    root = git(cwd, "rev-parse", "--show-toplevel")
    if not root:
        if project_name and project_name.strip():
            name = project_name.strip()
            project_id = f"manual/{name}"
            directory_name = safe_directory(project_id)
            return {
                "status": "ok",
                "identity_kind": "manual",
                "project_id": project_id,
                "directory_name": directory_name,
                "project_dir": str(Path(knowledge_root).expanduser().resolve() / directory_name),
                "repository_root": str(Path(cwd).resolve()),
                "repository_name": name,
                "repository_remote": "",
            }
        return {
            "status": "non_git",
            "cwd": str(Path(cwd).resolve()),
            "message": "当前目录不在 Git 仓库中，需要用户确认项目名称。",
        }

    root = str(Path(root).resolve())
    repository_name = Path(root).name
    remote = choose_remote(root)
    if remote:
        try:
            project_id, display_remote = normalize_remote(remote)
            identity_kind = "remote"
            repository_name = project_id.rsplit("/", 1)[-1]
        except ValueError:
            remote = None

    if not remote:
        digest = hashlib.sha256(root.encode("utf-8")).hexdigest()[:10]
        project_id = f"local/{repository_name}-{digest}"
        display_remote = ""
        identity_kind = "local"

    directory_name = safe_directory(project_id)
    project_dir = str(Path(knowledge_root).expanduser().resolve() / directory_name)
    return {
        "status": "ok",
        "identity_kind": identity_kind,
        "project_id": project_id,
        "directory_name": directory_name,
        "project_dir": project_dir,
        "repository_root": root,
        "repository_name": repository_name,
        "repository_remote": display_remote,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd", default=os.getcwd(), help="待识别目录")
    parser.add_argument(
        "--knowledge-root", default=DEFAULT_KNOWLEDGE_ROOT, help="知识库根目录"
    )
    parser.add_argument("--project-name", help="非 Git 目录经用户确认后的项目名称")
    args = parser.parse_args()
    result = identify(args.cwd, args.knowledge_root, args.project_name)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
