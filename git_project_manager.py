# -*- coding: utf-8 -*-
"""
Git 项目管理器 Pro v2.3
============================================================

定位：
- 管理多个本地项目
- Git 初始化 / 关联 GitHub 远程 / 首次推送
- 日常提交 / 推送
- 查看历史 / 安全回退
- 自动处理 .gitignore
- 自动阻止 log/cache/env/密钥/大文件等误提交
- 批量更新前自动清理缓存和日志
- 提交前执行轻量 CI 检查

运行：
    python git_project_manager.py

打包：
    pip install pyinstaller
    pyinstaller -F -w git_project_manager.py -n Git项目管理器Pro

说明：
- 纯 Python 标准库 + Tkinter，方便打包 exe。
- 不依赖 GitHub API。你需要先在 GitHub 创建空仓库，然后把远程地址填进工具。
"""

from __future__ import annotations

import compileall
import fnmatch
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from tkinter import ttk


# ============================================================
# App Config
# ============================================================

APP_NAME = "Git 项目管理器"
APP_DIR = Path.home() / ".git_project_manager"
CONFIG_FILE = APP_DIR / "projects_pro.json"

DEFAULT_BRANCH = "main"

# 永远不应该提交的规则
DANGEROUS_GIT_PATTERNS = [
    # logs
    "*.log",
    "logs/**",
    "log/**",
    "runtime/logs/**",
    "storage/logs/**",

    # python cache
    "__pycache__/**",
    "*.pyc",
    "*.pyo",
    ".pytest_cache/**",
    ".mypy_cache/**",
    ".ruff_cache/**",
    ".tox/**",
    ".nox/**",

    # node cache/build
    "node_modules/**",
    ".vite/**",
    ".next/**",
    ".nuxt/**",
    "dist/**",
    "build/**",
    "coverage/**",

    # venv
    ".venv/**",
    "venv/**",
    "env/**",
    "ENV/**",
    ".env",
    ".env.*",
    "!.env.example",

    # local db/cache
    "*.sqlite",
    "*.sqlite3",
    "*.db",
    "*.db-shm",
    "*.db-wal",
    "data/*.db",
    "cache/**",
    ".cache/**",
    "tmp/**",
    "temp/**",

    # IDE / OS
    ".idea/**",
    ".vscode/**",
    ".DS_Store",
    "Thumbs.db",

    # secret-ish
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa",
    "id_rsa.pub",
]

DEFAULT_GITIGNORE_LINES = [
    "# ===== Git Project Manager safe defaults =====",
    "",
    "# logs",
    "*.log",
    "logs/",
    "log/",
    "runtime/logs/",
    "storage/logs/",
    "",
    "# Python",
    "__pycache__/",
    "*.py[cod]",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".tox/",
    ".nox/",
    ".coverage",
    "htmlcov/",
    "",
    "# virtual env",
    ".venv/",
    "venv/",
    "env/",
    "ENV/",
    "",
    "# environment",
    ".env",
    ".env.*",
    "!.env.example",
    "",
    "# Node",
    "node_modules/",
    ".vite/",
    ".next/",
    ".nuxt/",
    "dist/",
    "build/",
    "coverage/",
    "",
    "# cache/temp",
    ".cache/",
    "cache/",
    "tmp/",
    "temp/",
    "",
    "# database/local runtime",
    "*.sqlite",
    "*.sqlite3",
    "*.db",
    "*.db-shm",
    "*.db-wal",
    "data/*.db",
    "",
    "# OS / IDE",
    ".DS_Store",
    "Thumbs.db",
    ".idea/",
    ".vscode/",
    "",
    "# secrets",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa",
    "id_rsa.pub",
    "",
    "# ===== End safe defaults =====",
]

SECRET_FILE_PATTERNS = [
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "config/secrets.*",
    "secrets.*",
]

SECRET_CONTENT_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"AIza[0-9A-Za-z\-_]{35}"),
    re.compile(r"ghp_[0-9A-Za-z]{30,}"),
    re.compile(r"github_pat_[0-9A-Za-z_]{50,}"),
    re.compile(r"sk-[0-9A-Za-z]{20,}"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[0-9a-zA-Z_\-]{12,}"),
]

MAX_WARN_FILE_SIZE = 10 * 1024 * 1024  # 10MB


# ============================================================
# Data
# ============================================================

@dataclass
class GitProject:
    name: str
    path: str
    remote_url: str = ""
    default_branch: str = DEFAULT_BRANCH

    @property
    def path_obj(self) -> Path:
        return Path(self.path)


class ProjectStore:
    def __init__(self, file_path: Path = CONFIG_FILE):
        self.file_path = file_path
        self.projects: List[GitProject] = []
        self.load()

    def load(self) -> None:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self.projects = []
            self.save()
            return

        try:
            raw = json.loads(self.file_path.read_text(encoding="utf-8"))
            projects = []
            for item in raw.get("projects", []):
                projects.append(GitProject(
                    name=item.get("name") or Path(item.get("path", "")).name,
                    path=item.get("path", ""),
                    remote_url=item.get("remote_url", ""),
                    default_branch=item.get("default_branch", DEFAULT_BRANCH),
                ))
            self.projects = projects
        except Exception:
            bad_file = self.file_path.with_suffix(f".bad.{int(time.time())}.json")
            self.file_path.rename(bad_file)
            self.projects = []
            self.save()

    def save(self) -> None:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        data = {"projects": [asdict(p) for p in self.projects]}
        self.file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, project: GitProject) -> None:
        normalized = str(Path(project.path).resolve())
        for p in self.projects:
            if str(Path(p.path).resolve()).lower() == normalized.lower():
                p.name = project.name
                p.path = normalized
                p.remote_url = project.remote_url
                p.default_branch = project.default_branch or DEFAULT_BRANCH
                self.save()
                return

        project.path = normalized
        self.projects.append(project)
        self.save()

    def remove_indexes(self, indexes: Sequence[int]) -> None:
        for idx in sorted(indexes, reverse=True):
            if 0 <= idx < len(self.projects):
                self.projects.pop(idx)
        self.save()


# ============================================================
# Git helpers
# ============================================================

class GitCommandError(RuntimeError):
    def __init__(self, command: List[str], cwd: Path, output: str):
        self.command = command
        self.cwd = cwd
        self.output = output
        super().__init__(f"Git 命令失败：{' '.join(command)}\n{output}")


def run_cmd(
    cmd: List[str],
    cwd: Path,
    *,
    check: bool = True,
    timeout: int = 180,
) -> str:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=False,
        timeout=timeout,
    )
    output = proc.stdout or ""
    if check and proc.returncode != 0:
        raise GitCommandError(cmd, cwd, output)
    return output.strip()


def run_git(
    args: List[str],
    cwd: Path,
    *,
    check: bool = True,
    timeout: int = 180,
) -> str:
    return run_cmd(["git"] + args, cwd, check=check, timeout=timeout)


def is_git_available() -> bool:
    try:
        subprocess.run(
            ["git", "--version"],
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
            shell=False,
        )
        return True
    except Exception:
        return False


def is_git_repo(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    try:
        out = run_git(["rev-parse", "--is-inside-work-tree"], path, check=True, timeout=20)
        return out.strip().lower() == "true"
    except Exception:
        return False


def has_head(path: Path) -> bool:
    try:
        out = run_git(["rev-parse", "--verify", "HEAD"], path, check=False, timeout=20)
        return bool(out and "fatal:" not in out.lower())
    except Exception:
        return False


def current_branch(path: Path) -> str:
    out = run_git(["branch", "--show-current"], path, check=False, timeout=20).strip()
    if out:
        return out
    out = run_git(["rev-parse", "--short", "HEAD"], path, check=False, timeout=20).strip()
    return out or "HEAD"


def remote_url(path: Path) -> str:
    out = run_git(["remote", "get-url", "origin"], path, check=False, timeout=20)
    if "No such remote" in out or "error:" in out.lower():
        return ""
    return out.strip()


def github_https_to_ssh(url: str) -> str:
    """
    将 GitHub HTTPS 远程地址转换为 SSH 地址。

    示例：
    https://github.com/Kun686/git-project-manager.git
    -> git@github.com:Kun686/git-project-manager.git

    为什么需要：
    - HTTPS 会触发 GitHub Credential Manager 登录弹窗
    - SSH 才会使用用户本地已经配置好的 SSH key
    """
    raw = (url or "").strip()
    if not raw:
        return raw

    # 兼容用户复制时带尾部斜杠
    raw = raw.rstrip("/")

    prefix = "https://github.com/"
    if not raw.lower().startswith(prefix):
        return raw

    repo_part = raw[len(prefix):].strip("/")
    if not repo_part:
        return raw

    if not repo_part.endswith(".git"):
        repo_part += ".git"

    return f"git@github.com:{repo_part}"


def is_github_https_remote(url: str) -> bool:
    return (url or "").strip().lower().startswith("https://github.com/")


def ensure_ssh_origin_if_github_https(
    path: Path,
    *,
    prefer_ssh: bool,
    emit: Optional[Callable[[str], None]] = None,
) -> str:
    """
    如果 origin 是 GitHub HTTPS，并且用户选择优先 SSH，则自动改成 SSH。
    """
    if not prefer_ssh:
        return "未开启 GitHub HTTPS 自动转 SSH，保持当前远程地址。"

    existing = remote_url(path)
    if not existing:
        return "未配置 origin，跳过远程地址转换。"

    if not is_github_https_remote(existing):
        return f"当前 origin 已不是 GitHub HTTPS，保持不变：{existing}"

    ssh_url = github_https_to_ssh(existing)
    run_git(["remote", "set-url", "origin", ssh_url], path, check=True, timeout=30)
    msg = f"已将 GitHub HTTPS 远程转换为 SSH：{ssh_url}"
    if emit:
        emit(msg)
    return msg


def set_or_add_origin(path: Path, url: str, *, prefer_ssh: bool = False) -> str:
    url = url.strip()
    if not url:
        raise ValueError("远程地址不能为空。")

    if prefer_ssh:
        converted = github_https_to_ssh(url)
        url = converted

    existing = remote_url(path)
    if existing:
        run_git(["remote", "set-url", "origin", url], path, check=True, timeout=30)
        return f"已更新 origin：{url}"

    run_git(["remote", "add", "origin", url], path, check=True, timeout=30)
    return f"已添加 origin：{url}"


def ensure_git_repo(path: Path, branch: str = DEFAULT_BRANCH) -> List[str]:
    logs = []
    if not path.exists() or not path.is_dir():
        raise ValueError(f"项目路径不存在：{path}")

    if is_git_repo(path):
        logs.append("已是 Git 仓库，跳过 git init。")
    else:
        logs.append(run_git(["init"], path, check=True, timeout=60))
        logs.append("已执行 git init。")

    # 仓库可能刚 init，还没有分支；有 HEAD 后再改名更稳。
    if branch:
        # git branch -M main 在无 HEAD 时可能失败，所以失败不致命，后续首次 commit 后再执行一次
        out = run_git(["branch", "-M", branch], path, check=False, timeout=30)
        if out:
            logs.append(out)
        logs.append(f"默认分支目标：{branch}")

    return logs


def get_changed_files(path: Path) -> List[Tuple[str, str]]:
    out = run_git(["status", "--short", "--untracked-files=all"], path, check=True, timeout=60)
    rows = []
    for line in out.splitlines():
        if not line.strip():
            continue
        status = line[:2].strip() or line[:2]
        file_path = line[3:].strip()
        rows.append((status, file_path))
    return rows


def git_history(path: Path, limit: int = 100) -> List[Tuple[str, str, str]]:
    if not is_git_repo(path) or not has_head(path):
        return []
    out = run_git(
        ["log", f"-n{limit}", "--date=iso", "--pretty=format:%h%x09%ad%x09%s"],
        path,
        check=False,
        timeout=60,
    )
    rows = []
    for line in out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            rows.append((parts[0], parts[1], parts[2]))
    return rows


def make_backup_branch(path: Path, prefix: str = "backup") -> Optional[str]:
    if not has_head(path):
        return None
    ts = time.strftime("%Y%m%d%H%M%S")
    suffix = str(int(time.time() * 1000))[-3:]
    name = f"{prefix}-{ts}-{suffix}"
    run_git(["branch", name], path, check=True, timeout=60)
    return name


def stage_files(path: Path, files: Optional[List[str]]) -> None:
    if files is None:
        run_git(["add", "-A"], path, check=True, timeout=180)
        return

    if not files:
        raise ValueError("没有选择要提交的文件。")
    run_git(["add", "-A", "--"] + files, path, check=True, timeout=180)


def commit_staged(path: Path, subject: str, body: str = "") -> str:
    final_subject = subject.strip() or f"update {time.strftime('%Y%m%d%H%M%S')}"
    body = body.strip()

    diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=str(path),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=False,
    )

    if diff.returncode == 0:
        return "暂存区没有变化，跳过 commit。"

    cmd = ["commit", "-m", final_subject]
    if body:
        cmd += ["-m", body]
    return run_git(cmd, path, check=True, timeout=180)


def push_current_branch(
    path: Path,
    branch: str = DEFAULT_BRANCH,
    set_upstream: bool = True,
    emit: Optional[Callable[[str], None]] = None,
) -> str:
    branch = branch or current_branch(path) or DEFAULT_BRANCH
    if set_upstream:
        if emit:
            emit(f"正在推送到远程：git push -u origin {branch}")
        return run_git(["push", "-u", "origin", branch], path, check=True, timeout=300)

    if emit:
        emit(f"正在推送到远程：git push origin {branch}")
    return run_git(["push", "origin", branch], path, check=True, timeout=300)


def remote_branch_exists(path: Path, branch: str) -> bool:
    """
    检测远程 origin/<branch> 是否存在。
    用于处理 GitHub 仓库不是空仓库的情况，例如远程已经有 README/LICENSE。
    """
    if not remote_url(path):
        return False

    out = run_git(["ls-remote", "--heads", "origin", branch], path, check=False, timeout=120)
    lower = out.lower()
    if "fatal:" in lower or "error:" in lower or "repository not found" in lower:
        return False
    return bool(out.strip())


def pull_remote_before_push(
    path: Path,
    branch: str = DEFAULT_BRANCH,
    emit: Optional[Callable[[str], None]] = None,
) -> str:
    """
    推送前自动拉取并合并远程非空仓库。

    场景：
    - GitHub 上创建仓库时勾选了 README/LICENSE/.gitignore
    - 本地已有项目第一次推送时，远程不是空仓库
    - 日常提交时，远程比本地多了一些提交

    策略：
    - 如果 origin/<branch> 不存在，跳过
    - 如果存在，执行 git pull --no-rebase --allow-unrelated-histories origin <branch>
    - 如果冲突，让 Git 报错并停止，避免工具擅自吞掉冲突
    """
    branch = branch or current_branch(path) or DEFAULT_BRANCH

    if not remote_url(path):
        msg = "未配置 origin，跳过远程拉取合并。"
        if emit:
            emit(msg)
        return msg

    if not remote_branch_exists(path, branch):
        msg = f"远程 origin/{branch} 不存在或为空，跳过远程拉取合并。"
        if emit:
            emit(msg)
        return msg

    logs = [f"检测到远程 origin/{branch} 已存在，开始拉取合并。"]
    if emit:
        emit(logs[-1])
        emit(f"正在执行：git fetch origin {branch}")

    fetch_out = run_git(["fetch", "origin", branch], path, check=True, timeout=180)
    if fetch_out:
        logs.append(fetch_out)
        if emit:
            emit(fetch_out)

    if emit:
        emit(f"正在执行：git pull --no-rebase --allow-unrelated-histories origin {branch}")

    out = run_git(
        ["pull", "--no-rebase", "--allow-unrelated-histories", "origin", branch],
        path,
        check=True,
        timeout=300,
    )
    final = out or "远程内容已合并。"
    logs.append(final)
    if emit:
        emit(final)

    return "\n".join([x for x in logs if x])


def rollback_to_commit(
    path: Path,
    commit_hash: str,
    *,
    force_push: bool = False,
    create_backup: bool = True,
) -> str:
    logs = []
    if create_backup:
        backup = make_backup_branch(path, prefix="rollback-backup")
        if backup:
            logs.append(f"回退前备份分支：{backup}")

    logs.append(run_git(["reset", "--hard", commit_hash], path, check=True, timeout=120))

    if force_push:
        branch = current_branch(path)
        if branch and branch != "HEAD":
            logs.append(run_git(["push", "--force-with-lease", "origin", branch], path, check=True, timeout=300))
        else:
            logs.append("当前不是正常分支，跳过远程强推。")

    return "\n".join(logs)


# ============================================================
# Ignore / clean / check
# ============================================================

def normalize_rel(path: str) -> str:
    return path.replace("\\", "/").strip()


def load_gitignore_patterns(project_path: Path) -> List[str]:
    gitignore = project_path / ".gitignore"
    if not gitignore.exists():
        return []
    lines = []
    for raw in gitignore.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def ensure_gitignore(
    project_path: Path,
    *,
    include_defaults: bool = True,
    extra_lines: Optional[List[str]] = None,
) -> str:
    gitignore = project_path / ".gitignore"
    old = ""
    if gitignore.exists():
        old = gitignore.read_text(encoding="utf-8", errors="replace")

    existing = set(line.strip() for line in old.splitlines())
    additions = []

    if include_defaults:
        for line in DEFAULT_GITIGNORE_LINES:
            if line.strip() and line.strip() not in existing:
                additions.append(line)
            elif not line.strip():
                # 空行可以保留，但不要连续堆太多
                if additions and additions[-1] != "":
                    additions.append("")

    if extra_lines:
        if additions and additions[-1] != "":
            additions.append("")
        additions.append("# user selected ignores")
        for line in extra_lines:
            line = line.strip().replace("\\", "/")
            if line and line not in existing:
                additions.append(line)

    if not additions:
        return ".gitignore 已经包含安全规则，无需更新。"

    new_text = old.rstrip() + "\n\n" + "\n".join(additions).rstrip() + "\n"
    gitignore.write_text(new_text, encoding="utf-8")
    return f"已更新 .gitignore，新增 {len([x for x in additions if x.strip()])} 条规则。"


def is_dangerous_by_pattern(rel_path: str) -> Optional[str]:
    rel = normalize_rel(rel_path)
    rel_lower = rel.lower()

    for pat in DANGEROUS_GIT_PATTERNS:
        pat_norm = pat.replace("\\", "/")
        if pat_norm.startswith("!"):
            continue
        # fnmatch 对 ** 不完美，但足够用于这里的安全拦截
        if fnmatch.fnmatch(rel_lower, pat_norm.lower()):
            return pat

        # 目录规则补充
        if pat_norm.endswith("/**"):
            prefix = pat_norm[:-3].lower()
            if rel_lower.startswith(prefix):
                return pat

    return None


def looks_like_secret_file(rel_path: str) -> Optional[str]:
    rel = normalize_rel(rel_path)
    name = Path(rel).name
    for pat in SECRET_FILE_PATTERNS:
        if fnmatch.fnmatch(name.lower(), pat.lower()) or fnmatch.fnmatch(rel.lower(), pat.lower()):
            return pat
    return None


def scan_file_content_for_secrets(file_path: Path) -> List[str]:
    issues = []
    if not file_path.exists() or not file_path.is_file():
        return issues

    try:
        if file_path.stat().st_size > 2 * 1024 * 1024:
            return issues
    except Exception:
        return issues

    try:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return issues

    for pattern in SECRET_CONTENT_PATTERNS:
        if pattern.search(text):
            issues.append(f"疑似密钥内容：{pattern.pattern}")
    return issues


def detect_risky_files(project_path: Path, files: Optional[List[str]] = None) -> Tuple[List[str], List[str]]:
    """
    返回 (fatal_issues, warnings)
    fatal 会阻止提交。
    warnings 只提示。
    """
    fatal = []
    warnings = []

    if files is None:
        changed = get_changed_files(project_path)
        target_files = [p for _s, p in changed]
    else:
        target_files = files

    for rel in target_files:
        rel = normalize_rel(rel)
        if not rel or " -> " in rel:
            # rename 场景取新路径
            rel = rel.split(" -> ")[-1].strip()

        pattern = is_dangerous_by_pattern(rel)
        if pattern:
            fatal.append(f"{rel} 命中禁止提交规则：{pattern}")
            continue

        secret_pat = looks_like_secret_file(rel)
        if secret_pat:
            fatal.append(f"{rel} 看起来是敏感文件：{secret_pat}")
            continue

        abs_path = project_path / rel
        try:
            if abs_path.exists() and abs_path.is_file() and abs_path.stat().st_size >= MAX_WARN_FILE_SIZE:
                warnings.append(f"{rel} 文件较大：{abs_path.stat().st_size / 1024 / 1024:.1f}MB")
        except Exception:
            pass

        for issue in scan_file_content_for_secrets(abs_path):
            fatal.append(f"{rel} {issue}")

        # Git 冲突标记检测
        # 旧逻辑只要源码里出现 "<<<<<<<" / "=======" / ">>>>>>>" 字符串就会误报。
        # 新逻辑只检测真实冲突标记：必须出现在行首。
        try:
            if abs_path.exists() and abs_path.is_file() and abs_path.stat().st_size < 2 * 1024 * 1024:
                text = abs_path.read_text(encoding="utf-8", errors="ignore")
                has_conflict_start = False
                has_conflict_middle = False
                has_conflict_end = False

                for line in text.splitlines():
                    stripped = line.rstrip()
                    if stripped.startswith("<<<<<<< "):
                        has_conflict_start = True
                    elif stripped == "=======":
                        has_conflict_middle = True
                    elif stripped.startswith(">>>>>>> "):
                        has_conflict_end = True

                if has_conflict_start and has_conflict_middle and has_conflict_end:
                    fatal.append(f"{rel} 可能包含 Git 冲突标记。")
        except Exception:
            pass

    return fatal, warnings


def remove_if_exists(path: Path) -> bool:
    try:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
            return True
        if path.is_file():
            path.unlink(missing_ok=True)
            return True
    except Exception:
        return False
    return False


def clean_cache_and_logs(project_path: Path) -> List[str]:
    targets = [
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".cache",
        ".vite",
        ".next/cache",
        "logs",
        "log",
        "runtime/logs",
        "storage/logs",
        "tmp",
        "temp",
    ]

    removed = []
    for t in targets:
        p = project_path / t
        if remove_if_exists(p):
            removed.append(t)

    # 递归删除 __pycache__ 和 *.pyc
    for p in project_path.rglob("__pycache__"):
        if ".git" in p.parts:
            continue
        if remove_if_exists(p):
            removed.append(str(p.relative_to(project_path)))

    for p in project_path.rglob("*.pyc"):
        if ".git" in p.parts:
            continue
        if remove_if_exists(p):
            removed.append(str(p.relative_to(project_path)))

    for p in list(project_path.rglob("*.log")):
        if ".git" in p.parts:
            continue
        if remove_if_exists(p):
            removed.append(str(p.relative_to(project_path)))

    return removed


def run_light_ci_checks(project_path: Path) -> Tuple[bool, List[str]]:
    """
    轻量提交前检查：
    - Git 是否可用
    - 检查误提交
    - Python 项目做语法编译检查
    - Node 项目如果有 package.json，只做提示，不自动 npm install/test
    """
    logs = []
    ok = True

    if not is_git_available():
        return False, ["没有检测到 Git，请先安装 Git 并加入 PATH。"]

    fatal, warnings = detect_risky_files(project_path)
    if fatal:
        ok = False
        logs.append("误提交检查失败：")
        logs.extend([f"  - {x}" for x in fatal])
    if warnings:
        logs.append("警告：")
        logs.extend([f"  - {x}" for x in warnings])

    # Python 语法检查
    py_files = []
    for p in project_path.rglob("*.py"):
        rel = normalize_rel(str(p.relative_to(project_path)))
        if is_dangerous_by_pattern(rel):
            continue
        if ".git" in p.parts:
            continue
        py_files.append(p)

    if py_files:
        logs.append(f"检测到 Python 文件 {len(py_files)} 个，执行 compileall 语法检查。")
        success = compileall.compile_dir(str(project_path), quiet=1, maxlevels=20)
        if not success:
            ok = False
            logs.append("Python compileall 失败，请检查语法错误。")
        else:
            logs.append("Python compileall 通过。")

    if (project_path / "package.json").exists():
        logs.append("检测到 package.json：建议你本地确认 npm run build/test。工具当前只做轻量检查，不自动安装依赖。")

    if ok:
        logs.append("提交前检查通过。")

    return ok, logs


def write_basic_github_actions(project_path: Path) -> str:
    """
    可选：生成一个通用 GitHub Actions CI。
    不强制执行，避免覆盖复杂项目配置。
    """
    workflow_dir = project_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    ci_file = workflow_dir / "ci.yml"

    if ci_file.exists():
        return "已存在 .github/workflows/ci.yml，未覆盖。"

    content = """name: CI

on:
  push:
  pull_request:

jobs:
  basic-check:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Detect project
        run: |
          echo "Basic CI started"
          ls -la

      - name: Python syntax check
        if: hashFiles('**/*.py') != ''
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Compile Python
        if: hashFiles('**/*.py') != ''
        run: python -m compileall .

      - name: Node install and build
        if: hashFiles('package.json') != ''
        uses: actions/setup-node@v4
        with:
          node-version: '20'

      - name: Node build if available
        if: hashFiles('package.json') != ''
        run: |
          npm ci || npm install
          npm run build --if-present
          npm test --if-present
"""
    ci_file.write_text(content, encoding="utf-8")
    return "已生成 .github/workflows/ci.yml。"


def commit_and_push_project(
    project: GitProject,
    *,
    subject: str,
    body: str,
    files: Optional[List[str]],
    push: bool,
    backup: bool,
    clean_before: bool,
    update_gitignore_first: bool,
    precheck: bool,
    allow_risky: bool,
    auto_pull_before_push: bool = True,
    prefer_ssh_remote: bool = True,
    emit: Optional[Callable[[str], None]] = None,
) -> str:
    path = project.path_obj
    logs: List[str] = []

    def add(message: str) -> None:
        logs.append(message)
        if emit:
            emit(message)

    add(f"项目：{project.name}")
    add(f"路径：{project.path}")

    if not is_git_repo(path):
        raise ValueError("当前目录还不是 Git 仓库。请先到【初始化 / GitHub】页初始化。")

    if clean_before:
        add("开始清理 cache/log。")
        removed = clean_cache_and_logs(path)
        if removed:
            add(f"已清理缓存/日志 {len(removed)} 项。")
        else:
            add("没有需要清理的缓存/日志。")

    if update_gitignore_first:
        add("开始维护 .gitignore。")
        add(ensure_gitignore(path, include_defaults=True))

    add("开始读取 Git 改动文件。")
    changed = get_changed_files(path)
    if not changed:
        add("没有检测到文件变化。")
        if push:
            add(ensure_ssh_origin_if_github_https(path, prefer_ssh=prefer_ssh_remote, emit=emit))
            if auto_pull_before_push:
                add(pull_remote_before_push(path, project.default_branch, emit=emit))
            add(push_current_branch(path, project.default_branch, set_upstream=False, emit=emit))
        return "\n".join(logs)

    add(f"检测到改动文件 {len(changed)} 个。")

    target_files = files
    add("开始扫描误提交风险。")
    fatal, warnings = detect_risky_files(path, target_files)

    if warnings:
        add("警告：")
        for item in warnings:
            add(f"  - {item}")

    if fatal and not allow_risky:
        add("已阻止提交：检测到疑似误提交文件。")
        for item in fatal:
            add(f"  - {item}")
        add("处理方式：加入 .gitignore、删除缓存/日志、或明确勾选【允许风险提交】。")
        return "\n".join(logs)

    if precheck:
        add("开始执行提交前 CI/安全检查。")
        ok, ci_logs = run_light_ci_checks(path)
        for line in ci_logs:
            add(line)
        if not ok and not allow_risky:
            add("提交前检查未通过，已停止。")
            return "\n".join(logs)

    if backup:
        add("开始创建提交前备份分支。")
        backup_branch = make_backup_branch(path)
        if backup_branch:
            add(f"提交前备份分支：{backup_branch}")
        else:
            add("当前仓库无 HEAD，跳过备份分支。")

    add("开始暂存文件：git add。")
    stage_files(path, target_files)

    add("开始创建提交：git commit。")
    add(commit_staged(path, subject, body))

    if push:
        add(ensure_ssh_origin_if_github_https(path, prefer_ssh=prefer_ssh_remote, emit=emit))
        if auto_pull_before_push:
            add(pull_remote_before_push(path, project.default_branch, emit=emit))
        add(push_current_branch(path, project.default_branch, set_upstream=False, emit=emit))
    else:
        add("未开启 push，已跳过远程推送。")

    return "\n".join(logs)

def init_remote_and_push(
    project: GitProject,
    *,
    remote: str,
    branch: str,
    commit_message: str,
    update_gitignore_first: bool,
    clean_before: bool,
    create_ci: bool,
    precheck: bool,
    allow_risky: bool,
    auto_pull_before_push: bool = True,
    prefer_ssh_remote: bool = True,
    emit: Optional[Callable[[str], None]] = None,
) -> str:
    path = project.path_obj
    logs: List[str] = []

    def add(message: str) -> None:
        logs.append(message)
        if emit:
            emit(message)

    add(f"初始化 / 绑定远程：{project.name}")
    add(f"路径：{path}")

    add("开始检查 Git 仓库状态。")
    for line in ensure_git_repo(path, branch=branch):
        add(line)

    if clean_before:
        add("开始清理 cache/log。")
        removed = clean_cache_and_logs(path)
        add(f"已清理缓存/日志 {len(removed)} 项。")

    if update_gitignore_first:
        add("开始维护 .gitignore。")
        add(ensure_gitignore(path, include_defaults=True))

    if create_ci:
        add("开始检查/生成 GitHub Actions CI。")
        add(write_basic_github_actions(path))

    if prefer_ssh_remote and is_github_https_remote(remote):
        converted_remote = github_https_to_ssh(remote)
        add(f"检测到 GitHub HTTPS 地址，已自动改用 SSH：{converted_remote}")
        remote = converted_remote

    add("开始关联远程 origin。")
    add(set_or_add_origin(path, remote, prefer_ssh=False))

    add("开始扫描误提交风险。")
    fatal, warnings = detect_risky_files(path)
    if warnings:
        add("警告：")
        for item in warnings:
            add(f"  - {item}")
    if fatal and not allow_risky:
        add("已阻止首次提交：检测到疑似误提交文件。")
        for item in fatal:
            add(f"  - {item}")
        return "\n".join(logs)

    if precheck:
        add("开始执行提交前 CI/安全检查。")
        ok, ci_logs = run_light_ci_checks(path)
        for line in ci_logs:
            add(line)
        if not ok and not allow_risky:
            add("提交前检查未通过，已停止。")
            return "\n".join(logs)

    add("开始暂存文件：git add。")
    stage_files(path, None)

    add("开始创建首次提交：git commit。")
    add(commit_staged(path, commit_message or "initial commit", ""))

    # 首次 commit 后再确保分支名
    if branch:
        add(f"确保当前分支为：{branch}")
        out = run_git(["branch", "-M", branch], path, check=False, timeout=30)
        if out:
            add(out)

    if auto_pull_before_push:
        add(pull_remote_before_push(path, branch, emit=emit))

    add(push_current_branch(path, branch, set_upstream=True, emit=emit))
    return "\n".join(logs)



# ============================================================
# UI
# ============================================================

class Colors:
    BG = "#F5F5F7"
    SIDEBAR = "#ECECF1"
    CARD = "#FFFFFF"
    CARD_ALT = "#FAFAFC"
    TEXT = "#1D1D1F"
    MUTED = "#6E6E73"
    BORDER = "#D2D2D7"
    BLUE = "#007AFF"
    BLUE_HOVER = "#0A84FF"
    RED = "#FF3B30"
    RED_BG = "#FFF1F0"
    GREEN = "#34C759"
    DARK = "#111827"
    DARK_TEXT = "#D1D5DB"


class ModernButton(tk.Button):
    def __init__(self, master, text, command=None, variant="normal", **kwargs):
        if variant == "primary":
            bg = Colors.BLUE
            fg = "white"
            active = Colors.BLUE_HOVER
        elif variant == "danger":
            bg = Colors.RED_BG
            fg = Colors.RED
            active = "#FFE4E1"
        else:
            bg = Colors.CARD
            fg = Colors.TEXT
            active = "#E9E9ED"

        super().__init__(
            master,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=active,
            activeforeground=fg,
            bd=0,
            relief="flat",
            padx=16,
            pady=10,
            cursor="hand2",
            font=("Microsoft YaHei UI", 10),
            **kwargs,
        )


class Card(tk.Frame):
    def __init__(self, master, **kwargs):
        super().__init__(
            master,
            bg=Colors.CARD,
            highlightbackground=Colors.BORDER,
            highlightthickness=1,
            bd=0,
            **kwargs,
        )


class SwitchRow(tk.Frame):
    """
    苹果风格开关，替代 Windows 原生 Checkbutton。
    原生 Checkbutton 在 Windows 上容易出现黑色小方框、文字偏移、选中态不统一的问题。
    """
    def __init__(self, master, text: str, variable: tk.BooleanVar, *, danger: bool = False):
        super().__init__(master, bg=Colors.CARD)
        self.variable = variable
        self.danger = danger

        self.text_label = tk.Label(
            self,
            text=text,
            bg=Colors.CARD,
            fg=Colors.RED if danger else Colors.TEXT,
            font=("Microsoft YaHei UI", 9),
            anchor="w",
            cursor="hand2",
        )
        self.text_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.canvas = tk.Canvas(
            self,
            width=44,
            height=24,
            bg=Colors.CARD,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.canvas.pack(side=tk.RIGHT)

        self.text_label.bind("<Button-1>", self.toggle)
        self.canvas.bind("<Button-1>", self.toggle)
        self.bind("<Button-1>", self.toggle)

        self.variable.trace_add("write", lambda *_: self.draw())
        self.draw()

    def toggle(self, _event=None) -> None:
        self.variable.set(not self.variable.get())

    def draw(self) -> None:
        self.canvas.delete("all")
        on = bool(self.variable.get())

        bg = Colors.BLUE if on else "#D1D1D6"
        knob_x = 22 if on else 2

        # pill background
        self.canvas.create_oval(1, 1, 23, 23, fill=bg, outline=bg)
        self.canvas.create_oval(21, 1, 43, 23, fill=bg, outline=bg)
        self.canvas.create_rectangle(12, 1, 32, 23, fill=bg, outline=bg)

        # knob
        self.canvas.create_oval(knob_x, 2, knob_x + 20, 22, fill="#FFFFFF", outline="#FFFFFF")


class GitManagerProApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title(APP_NAME)
        self.geometry("1320x820")
        self.minsize(1120, 700)
        self.configure(bg=Colors.BG)

        self.store = ProjectStore()
        self.task_queue: queue.Queue[Tuple[Callable[[object], None], object]] = queue.Queue()

        self._setup_style()
        self._build_layout()
        self.load_projects()
        self.after(100, self.poll_queue)

    # ---------- style ----------

    def _setup_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("TNotebook", background=Colors.BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(18, 10), font=("Microsoft YaHei UI", 10), background=Colors.CARD_ALT)
        style.map("TNotebook.Tab", background=[("selected", Colors.CARD)], foreground=[("selected", Colors.TEXT)])

        style.configure("Treeview", font=("Microsoft YaHei UI", 10), rowheight=30, background=Colors.CARD, fieldbackground=Colors.CARD)
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"), background=Colors.CARD_ALT, foreground=Colors.TEXT)

        style.configure("TCheckbutton", background=Colors.CARD, font=("Microsoft YaHei UI", 10), foreground=Colors.TEXT)
        style.configure("TEntry", padding=8)

    def label(self, master, text, size=10, weight="normal", color=None, bg=None):
        return tk.Label(
            master,
            text=text,
            font=("Microsoft YaHei UI", size, weight),
            fg=color or Colors.TEXT,
            bg=bg or master.cget("bg"),
            anchor="w",
        )

    # ---------- layout ----------

    def _build_layout(self) -> None:
        # Header
        header = tk.Frame(self, bg=Colors.BG)
        header.pack(fill=tk.X, padx=24, pady=(18, 10))

        title_box = tk.Frame(header, bg=Colors.BG)
        title_box.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.label(title_box, "Git 项目管理器 Pro v2.3", size=18, weight="bold", bg=Colors.BG).pack(anchor="w")
        self.label(
            title_box,
            "管理本地仓库、初始化 GitHub 远程、自动拉取合并、提交前检查、误提交拦截、历史回退。",
            size=10,
            color=Colors.MUTED,
            bg=Colors.BG,
        ).pack(anchor="w", pady=(4, 0))

        ModernButton(header, "更新全部项目", command=self.update_all_projects, variant="primary").pack(side=tk.RIGHT, padx=(12, 0))

        # Main
        main = tk.Frame(self, bg=Colors.BG)
        main.pack(fill=tk.BOTH, expand=True, padx=24, pady=(0, 24))

        self.sidebar = Card(main)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 18))

        self.content = tk.Frame(main, bg=Colors.BG)
        self.content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._build_sidebar()
        self._build_tabs()

    def _build_sidebar(self) -> None:
        self.sidebar.configure(width=310)
        self.sidebar.pack_propagate(False)

        top = tk.Frame(self.sidebar, bg=Colors.CARD)
        top.pack(fill=tk.X, padx=18, pady=(18, 10))

        self.label(top, "项目", size=13, weight="bold", bg=Colors.CARD).pack(anchor="w")
        self.label(top, "导入路径会保存，下次打开继续使用。", size=9, color=Colors.MUTED, bg=Colors.CARD).pack(anchor="w", pady=(4, 0))

        list_frame = tk.Frame(self.sidebar, bg=Colors.CARD)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=18, pady=(4, 14))

        self.project_list = tk.Listbox(
            list_frame,
            selectmode=tk.EXTENDED,
            exportselection=False,
            bd=0,
            highlightthickness=1,
            highlightbackground=Colors.BORDER,
            selectbackground=Colors.BLUE,
            selectforeground="white",
            bg="#FBFBFD",
            fg=Colors.TEXT,
            font=("Microsoft YaHei UI", 10),
            activestyle="none",
        )
        self.project_list.pack(fill=tk.BOTH, expand=True)
        self.project_list.bind("<<ListboxSelect>>", lambda _e: self.refresh_current_project())

        btn_grid = tk.Frame(self.sidebar, bg=Colors.CARD)
        btn_grid.pack(fill=tk.X, padx=18, pady=(0, 14))

        ModernButton(btn_grid, "导入", command=self.add_project).grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=(0, 8))
        ModernButton(btn_grid, "移除", command=self.remove_project, variant="danger").grid(row=0, column=1, sticky="ew", pady=(0, 8))
        ModernButton(btn_grid, "刷新", command=self.refresh_current_project).grid(row=1, column=0, sticky="ew", padx=(0, 8))
        ModernButton(btn_grid, "更新选中", command=self.update_selected_projects, variant="primary").grid(row=1, column=1, sticky="ew")

        btn_grid.columnconfigure(0, weight=1)
        btn_grid.columnconfigure(1, weight=1)

        options = tk.Frame(self.sidebar, bg=Colors.CARD)
        options.pack(fill=tk.X, padx=18, pady=(0, 18))

        self.push_var = tk.BooleanVar(value=True)
        self.prefer_ssh_var = tk.BooleanVar(value=True)
        self.auto_pull_var = tk.BooleanVar(value=True)
        self.backup_var = tk.BooleanVar(value=True)
        self.clean_var = tk.BooleanVar(value=True)
        self.gitignore_var = tk.BooleanVar(value=True)
        self.precheck_var = tk.BooleanVar(value=True)
        self.allow_risky_var = tk.BooleanVar(value=False)

        for text, var, danger in [
            ("提交后 push 到远程", self.push_var, False),
            ("GitHub HTTPS 自动转 SSH", self.prefer_ssh_var, False),
            ("远程非空自动拉取合并", self.auto_pull_var, False),
            ("提交前创建备份分支", self.backup_var, False),
            ("提交前清理 cache/log", self.clean_var, False),
            ("自动维护 .gitignore", self.gitignore_var, False),
            ("提交前 CI/安全检查", self.precheck_var, False),
            ("允许风险提交", self.allow_risky_var, True),
        ]:
            SwitchRow(options, text, var, danger=danger).pack(fill=tk.X, pady=5)

    def _build_tabs(self) -> None:
        self.tabs = ttk.Notebook(self.content)
        self.tabs.pack(fill=tk.BOTH, expand=True)

        self.tab_commit = tk.Frame(self.tabs, bg=Colors.CARD)
        self.tab_init = tk.Frame(self.tabs, bg=Colors.CARD)
        self.tab_ignore = tk.Frame(self.tabs, bg=Colors.CARD)
        self.tab_history = tk.Frame(self.tabs, bg=Colors.CARD)
        self.tab_check = tk.Frame(self.tabs, bg=Colors.CARD)
        self.tab_log = tk.Frame(self.tabs, bg=Colors.CARD)

        self.tabs.add(self.tab_commit, text="更新 / 提交")
        self.tabs.add(self.tab_init, text="初始化 / GitHub")
        self.tabs.add(self.tab_ignore, text=".gitignore / 清理")
        self.tabs.add(self.tab_history, text="历史 / 回退")
        self.tabs.add(self.tab_check, text="检查 / CI")
        self.tabs.add(self.tab_log, text="运行日志")

        self._build_commit_tab()
        self._build_init_tab()
        self._build_ignore_tab()
        self._build_history_tab()
        self._build_check_tab()
        self._build_log_tab()

    def _card_inner(self, tab):
        frame = tk.Frame(tab, bg=Colors.CARD)
        frame.pack(fill=tk.BOTH, expand=True, padx=22, pady=22)
        return frame

    def _build_commit_tab(self) -> None:
        root = self._card_inner(self.tab_commit)

        self.label(root, "当前项目", size=12, weight="bold", bg=Colors.CARD).grid(row=0, column=0, sticky="w")
        self.current_project_label = self.label(root, "未选择", size=10, color=Colors.MUTED, bg=Colors.CARD)
        self.current_project_label.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(4, 18))

        self.label(root, "提交标题", bg=Colors.CARD).grid(row=2, column=0, sticky="w")
        self.subject_entry = tk.Entry(
            root,
            bd=0,
            highlightthickness=1,
            highlightbackground=Colors.BORDER,
            highlightcolor=Colors.BLUE,
            font=("Microsoft YaHei UI", 11),
            bg="#FBFBFD",
        )
        self.subject_entry.grid(row=2, column=1, columnspan=3, sticky="ew", ipady=9, padx=(12, 0))
        self.label(root, "留空则在 commit 时自动生成，例如：update 20260608180409", size=9, color=Colors.MUTED, bg=Colors.CARD).grid(row=3, column=1, columnspan=3, sticky="w", padx=(12, 0), pady=(6, 16))

        self.label(root, "提交解释", bg=Colors.CARD).grid(row=4, column=0, sticky="nw")
        self.body_text = tk.Text(
            root,
            height=4,
            bd=0,
            highlightthickness=1,
            highlightbackground=Colors.BORDER,
            highlightcolor=Colors.BLUE,
            font=("Microsoft YaHei UI", 10),
            bg="#FBFBFD",
            wrap="word",
        )
        self.body_text.grid(row=4, column=1, columnspan=3, sticky="ew", padx=(12, 0))
        self.body_text.insert("1.0", "说明本次更新内容，例如：修复页面样式、更新后端逻辑、同步配置文件。")

        file_header = tk.Frame(root, bg=Colors.CARD)
        file_header.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(26, 8))
        self.label(file_header, "改动文件", size=12, weight="bold", bg=Colors.CARD).pack(side=tk.LEFT)
        ModernButton(file_header, "刷新改动", command=self.refresh_changes).pack(side=tk.RIGHT, padx=(8, 0))
        ModernButton(file_header, "选择全部", command=self.select_all_changes).pack(side=tk.RIGHT)

        self.change_list = tk.Listbox(
            root,
            selectmode=tk.EXTENDED,
            exportselection=False,
            bd=0,
            highlightthickness=1,
            highlightbackground=Colors.BORDER,
            bg="#FBFBFD",
            fg=Colors.TEXT,
            selectbackground=Colors.BLUE,
            selectforeground="white",
            font=("Consolas", 10),
            activestyle="none",
        )
        self.change_list.grid(row=6, column=0, columnspan=4, sticky="nsew")

        actions = tk.Frame(root, bg=Colors.CARD)
        actions.grid(row=7, column=0, columnspan=4, sticky="e", pady=(14, 0))
        ModernButton(actions, "只提交选中文件", command=self.update_current_selected_files).pack(side=tk.LEFT, padx=(0, 10))
        ModernButton(actions, "提交当前项目全部文件", command=self.update_current_all_files, variant="primary").pack(side=tk.LEFT)

        root.columnconfigure(1, weight=1)
        root.rowconfigure(6, weight=1)

    def _build_init_tab(self) -> None:
        root = self._card_inner(self.tab_init)

        self.label(root, "把现有项目加入 GitHub", size=14, weight="bold", bg=Colors.CARD).grid(row=0, column=0, columnspan=3, sticky="w")
        self.label(root, "先在 GitHub 创建一个空仓库，然后把仓库地址填到这里。工具会检查是否已是 Git 仓库，必要时自动初始化、关联远程；远程非空时可自动 pull 合并后再推送。", size=9, color=Colors.MUTED, bg=Colors.CARD).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 20))

        self.label(root, "GitHub 远程地址", bg=Colors.CARD).grid(row=2, column=0, sticky="w")
        self.remote_entry = tk.Entry(root, bd=0, highlightthickness=1, highlightbackground=Colors.BORDER, highlightcolor=Colors.BLUE, bg="#FBFBFD", font=("Consolas", 10))
        self.remote_entry.grid(row=2, column=1, columnspan=2, sticky="ew", ipady=9, padx=(12, 0))

        self.label(root, "分支名", bg=Colors.CARD).grid(row=3, column=0, sticky="w", pady=(12, 0))
        self.branch_entry = tk.Entry(root, bd=0, highlightthickness=1, highlightbackground=Colors.BORDER, highlightcolor=Colors.BLUE, bg="#FBFBFD", font=("Consolas", 10))
        self.branch_entry.grid(row=3, column=1, sticky="ew", ipady=9, padx=(12, 0), pady=(12, 0))
        self.branch_entry.insert(0, DEFAULT_BRANCH)

        self.label(root, "首次提交说明", bg=Colors.CARD).grid(row=4, column=0, sticky="w", pady=(12, 0))
        self.initial_commit_entry = tk.Entry(root, bd=0, highlightthickness=1, highlightbackground=Colors.BORDER, highlightcolor=Colors.BLUE, bg="#FBFBFD", font=("Microsoft YaHei UI", 10))
        self.initial_commit_entry.grid(row=4, column=1, columnspan=2, sticky="ew", ipady=9, padx=(12, 0), pady=(12, 0))
        self.initial_commit_entry.insert(0, "initial commit")

        self.create_ci_var = tk.BooleanVar(value=True)
        create_ci_switch = SwitchRow(root, "生成基础 GitHub Actions CI 文件", self.create_ci_var)
        create_ci_switch.grid(row=5, column=1, sticky="ew", padx=(12, 0), pady=(14, 0))

        status_card = tk.Frame(root, bg=Colors.CARD_ALT, highlightbackground=Colors.BORDER, highlightthickness=1)
        status_card.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(24, 12))
        self.repo_status_label = self.label(status_card, "仓库状态：未检测", size=10, color=Colors.MUTED, bg=Colors.CARD_ALT)
        self.repo_status_label.pack(anchor="w", padx=14, pady=12)

        actions = tk.Frame(root, bg=Colors.CARD)
        actions.grid(row=7, column=0, columnspan=3, sticky="e")
        ModernButton(actions, "检测当前项目", command=self.detect_current_repo_status).pack(side=tk.LEFT, padx=(0, 10))
        ModernButton(actions, "初始化 / 关联远程 / 推送", command=self.init_current_remote_push, variant="primary").pack(side=tk.LEFT)

        root.columnconfigure(1, weight=1)

    def _build_ignore_tab(self) -> None:
        root = self._card_inner(self.tab_ignore)

        self.label(root, ".gitignore 与清理", size=14, weight="bold", bg=Colors.CARD).grid(row=0, column=0, columnspan=3, sticky="w")
        self.label(root, "自动加入常见忽略规则：日志、缓存、虚拟环境、node_modules、数据库、本地密钥。也可以选择额外要忽略的文件夹。", size=9, color=Colors.MUTED, bg=Colors.CARD).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 18))

        self.ignore_extra_list = tk.Listbox(
            root,
            selectmode=tk.EXTENDED,
            exportselection=False,
            bd=0,
            highlightthickness=1,
            highlightbackground=Colors.BORDER,
            bg="#FBFBFD",
            font=("Consolas", 10),
        )
        self.ignore_extra_list.grid(row=2, column=0, columnspan=3, sticky="nsew")

        actions = tk.Frame(root, bg=Colors.CARD)
        actions.grid(row=3, column=0, columnspan=3, sticky="e", pady=(14, 0))
        ModernButton(actions, "选择要忽略的文件夹", command=self.add_ignore_folder).pack(side=tk.LEFT, padx=(0, 10))
        ModernButton(actions, "移除选中", command=self.remove_selected_ignore_extra, variant="danger").pack(side=tk.LEFT, padx=(0, 10))
        ModernButton(actions, "写入 .gitignore", command=self.apply_gitignore_current, variant="primary").pack(side=tk.LEFT, padx=(0, 10))
        ModernButton(actions, "清理 cache/log", command=self.clean_current_cache_log).pack(side=tk.LEFT)

        self.gitignore_preview = tk.Text(
            root,
            height=12,
            bd=0,
            highlightthickness=1,
            highlightbackground=Colors.BORDER,
            bg="#FBFBFD",
            font=("Consolas", 9),
            wrap="none",
        )
        self.gitignore_preview.grid(row=4, column=0, columnspan=3, sticky="nsew", pady=(18, 0))
        self.gitignore_preview.insert("1.0", "\n".join(DEFAULT_GITIGNORE_LINES))

        root.rowconfigure(2, weight=1)
        root.rowconfigure(4, weight=1)
        root.columnconfigure(0, weight=1)

    def _build_history_tab(self) -> None:
        root = self._card_inner(self.tab_history)

        top = tk.Frame(root, bg=Colors.CARD)
        top.pack(fill=tk.X)
        self.label(top, "提交历史", size=14, weight="bold", bg=Colors.CARD).pack(side=tk.LEFT)
        ModernButton(top, "刷新历史", command=self.refresh_history).pack(side=tk.RIGHT)

        columns = ("hash", "date", "message")
        self.history_tree = ttk.Treeview(root, columns=columns, show="headings")
        self.history_tree.heading("hash", text="提交")
        self.history_tree.heading("date", text="时间")
        self.history_tree.heading("message", text="说明")
        self.history_tree.column("hash", width=110)
        self.history_tree.column("date", width=230)
        self.history_tree.column("message", width=680)
        self.history_tree.pack(fill=tk.BOTH, expand=True, pady=(12, 12))

        bottom = tk.Frame(root, bg=Colors.CARD)
        bottom.pack(fill=tk.X)
        self.force_push_rollback_var = tk.BooleanVar(value=False)
        SwitchRow(bottom, "回退后强推远程（危险）", self.force_push_rollback_var, danger=True).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ModernButton(bottom, "回退到选中提交", command=self.rollback_selected_commit, variant="danger").pack(side=tk.RIGHT)

    def _build_check_tab(self) -> None:
        root = self._card_inner(self.tab_check)

        self.label(root, "安全检查 / CI", size=14, weight="bold", bg=Colors.CARD).pack(anchor="w")
        self.label(root, "提交前扫描日志、缓存、虚拟环境、密钥、大文件、冲突标记，并对 Python 项目做语法检查。", size=9, color=Colors.MUTED, bg=Colors.CARD).pack(anchor="w", pady=(6, 14))

        actions = tk.Frame(root, bg=Colors.CARD)
        actions.pack(fill=tk.X)
        ModernButton(actions, "扫描当前项目误提交", command=self.scan_current_risky).pack(side=tk.LEFT, padx=(0, 10))
        ModernButton(actions, "运行提交前检查", command=self.run_current_precheck, variant="primary").pack(side=tk.LEFT, padx=(0, 10))
        ModernButton(actions, "生成 GitHub Actions CI", command=self.create_ci_current).pack(side=tk.LEFT)

        self.check_text = tk.Text(
            root,
            bd=0,
            highlightthickness=1,
            highlightbackground=Colors.BORDER,
            bg="#FBFBFD",
            font=("Consolas", 10),
            wrap="word",
        )
        self.check_text.pack(fill=tk.BOTH, expand=True, pady=(14, 0))

    def _build_log_tab(self) -> None:
        root = self._card_inner(self.tab_log)

        top = tk.Frame(root, bg=Colors.CARD)
        top.pack(fill=tk.X)
        self.label(top, "运行日志", size=14, weight="bold", bg=Colors.CARD).pack(side=tk.LEFT)
        ModernButton(top, "清空", command=lambda: self.log_text.delete("1.0", tk.END)).pack(side=tk.RIGHT)

        self.log_text = tk.Text(
            root,
            bd=0,
            highlightthickness=1,
            highlightbackground="#1F2937",
            bg=Colors.DARK,
            fg=Colors.DARK_TEXT,
            insertbackground=Colors.DARK_TEXT,
            font=("Consolas", 10),
            wrap="word",
        )
        self.log_text.pack(fill=tk.BOTH, expand=True, pady=(12, 0))

    # ---------- common ----------

    def current_project(self) -> Optional[GitProject]:
        indexes = list(self.project_list.curselection())
        if not indexes:
            return None
        idx = indexes[0]
        if 0 <= idx < len(self.store.projects):
            return self.store.projects[idx]
        return None

    def selected_projects(self) -> List[GitProject]:
        result = []
        for idx in self.project_list.curselection():
            if 0 <= idx < len(self.store.projects):
                result.append(self.store.projects[idx])
        return result

    def load_projects(self) -> None:
        self.project_list.delete(0, tk.END)
        for p in self.store.projects:
            mark = "●" if is_git_repo(p.path_obj) else "○"
            display = f"{mark}  {p.name}\n    {p.path}"
            self.project_list.insert(tk.END, display)

    def add_project(self) -> None:
        folder = filedialog.askdirectory(title="选择项目目录")
        if not folder:
            return

        path = Path(folder).resolve()
        name = simpledialog.askstring("项目名称", "项目名称：", initialvalue=path.name)
        if not name:
            return

        remote = ""
        branch = DEFAULT_BRANCH
        if is_git_repo(path):
            remote = remote_url(path)
            branch = current_branch(path)
            if branch == "HEAD":
                branch = DEFAULT_BRANCH

        self.store.add(GitProject(name=name.strip(), path=str(path), remote_url=remote, default_branch=branch))
        self.load_projects()
        self.log(f"已导入项目：{name} -> {path}")

    def remove_project(self) -> None:
        indexes = list(self.project_list.curselection())
        if not indexes:
            messagebox.showinfo("提示", "请先选择项目。")
            return
        if not messagebox.askyesno("确认", "只从工具列表移除，不会删除本地文件。确定继续？"):
            return
        self.store.remove_indexes(indexes)
        self.load_projects()
        self.refresh_current_project()

    def refresh_current_project(self) -> None:
        p = self.current_project()
        if not p:
            self.current_project_label.config(text="未选择")
            self.repo_status_label.config(text="仓库状态：未检测")
            self.change_list.delete(0, tk.END)
            self.clear_history()
            return

        self.current_project_label.config(text=f"{p.name}    {p.path}")
        if hasattr(self, "remote_entry"):
            self.remote_entry.delete(0, tk.END)
            self.remote_entry.insert(0, p.remote_url or (remote_url(p.path_obj) if is_git_repo(p.path_obj) else ""))
        if hasattr(self, "branch_entry"):
            self.branch_entry.delete(0, tk.END)
            self.branch_entry.insert(0, p.default_branch or DEFAULT_BRANCH)

        self.detect_current_repo_status(silent=True)
        self.refresh_changes()
        self.refresh_history()

    def get_subject_body(self) -> Tuple[str, str]:
        return self.subject_entry.get().strip(), self.body_text.get("1.0", tk.END).strip()

    def selected_change_files(self) -> List[str]:
        files = []
        for idx in self.change_list.curselection():
            item = self.change_list.get(idx)
            if "工作区干净" in item:
                continue
            if len(item) >= 4:
                rel = item[4:].strip()
                if " -> " in rel:
                    rel = rel.split(" -> ")[-1].strip()
                if rel:
                    files.append(rel)
        return files

    def log(self, text: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"\n[{ts}]\n{text}\n")
        self.log_text.see(tk.END)
        self.tabs.select(self.tab_log)

    def log_error(self, exc: Exception) -> None:
        if isinstance(exc, GitCommandError):
            self.log(f"Git 命令失败\n目录：{exc.cwd}\n命令：{' '.join(exc.command)}\n输出：\n{exc.output}")
        else:
            self.log(f"错误：{exc}")

    def emit_realtime_log(self, text: str) -> None:
        """
        后台线程不能直接操作 Tk 控件。
        这里把日志投递回主线程，由 poll_queue 统一写入日志框。
        """
        self.task_queue.put((self.log, str(text)))

    def format_exception_for_log(self, exc: Exception) -> str:
        if isinstance(exc, GitCommandError):
            return f"Git 命令失败\n目录：{exc.cwd}\n命令：{' '.join(exc.command)}\n输出：\n{exc.output}"
        return f"错误：{exc}"

    def run_background(self, job: Callable[[], object], done: Callable[[object], None]) -> None:
        def runner():
            try:
                result = job()
            except Exception as exc:
                result = exc
            self.task_queue.put((done, result))
        threading.Thread(target=runner, daemon=True).start()

    def poll_queue(self) -> None:
        try:
            while True:
                done, result = self.task_queue.get_nowait()
                done(result)
        except queue.Empty:
            pass
        self.after(100, self.poll_queue)

    # ---------- commit ----------

    def refresh_changes(self) -> None:
        p = self.current_project()
        self.change_list.delete(0, tk.END)
        if not p:
            return

        def job():
            if not is_git_repo(p.path_obj):
                return [("!", "当前目录还不是 Git 仓库，请先初始化。")]
            return get_changed_files(p.path_obj)

        def done(result):
            if isinstance(result, Exception):
                self.log_error(result)
                return
            self.change_list.delete(0, tk.END)
            if not result:
                self.change_list.insert(tk.END, "工作区干净，没有改动。")
                return
            for status, rel in result:
                self.change_list.insert(tk.END, f"{status:>2}  {rel}")

        self.run_background(job, done)

    def select_all_changes(self) -> None:
        self.change_list.select_set(0, tk.END)

    def update_current_all_files(self) -> None:
        p = self.current_project()
        if not p:
            messagebox.showinfo("提示", "请先选择项目。")
            return
        self.update_projects([p], files=None)

    def update_current_selected_files(self) -> None:
        p = self.current_project()
        if not p:
            messagebox.showinfo("提示", "请先选择项目。")
            return
        files = self.selected_change_files()
        if not files:
            messagebox.showinfo("提示", "请先选择要提交的文件。")
            return
        self.update_projects([p], files=files)

    def update_selected_projects(self) -> None:
        projects = self.selected_projects()
        if not projects:
            messagebox.showinfo("提示", "请先选择项目。")
            return
        self.update_projects(projects, files=None)

    def update_all_projects(self) -> None:
        if not self.store.projects:
            messagebox.showinfo("提示", "还没有导入项目。")
            return
        if not messagebox.askyesno("确认", "确定更新全部项目？会按设置自动清理 cache/log、检查误提交、commit、push。"):
            return
        self.update_projects(self.store.projects, files=None)

    def update_projects(self, projects: List[GitProject], files: Optional[List[str]]) -> None:
        subject, body = self.get_subject_body()

        def job():
            emit = self.emit_realtime_log
            emit("=" * 72)
            emit("开始更新项目。")
            for p in projects:
                emit("=" * 72)
                try:
                    project_files = files if len(projects) == 1 else None
                    commit_and_push_project(
                        p,
                        subject=subject,
                        body=body,
                        files=project_files,
                        push=self.push_var.get(),
                        backup=self.backup_var.get(),
                        clean_before=self.clean_var.get(),
                        update_gitignore_first=self.gitignore_var.get(),
                        precheck=self.precheck_var.get(),
                        allow_risky=self.allow_risky_var.get(),
                        auto_pull_before_push=self.auto_pull_var.get(),
                        prefer_ssh_remote=self.prefer_ssh_var.get(),
                        emit=emit,
                    )
                except Exception as exc:
                    emit(f"失败：{p.name}\n{self.format_exception_for_log(exc)}")
            emit("=" * 72)
            emit("全部处理完成。")
            return {"realtime": True}

        def done(result):
            if isinstance(result, Exception):
                self.log_error(result)
            else:
                self.load_projects()
                self.refresh_current_project()

        self.run_background(job, done)


    # ---------- init / GitHub ----------

    def detect_current_repo_status(self, silent: bool = False) -> None:
        p = self.current_project()
        if not p:
            if not silent:
                messagebox.showinfo("提示", "请先选择项目。")
            return

        path = p.path_obj
        if not path.exists():
            text = "仓库状态：路径不存在。"
        elif is_git_repo(path):
            branch = current_branch(path)
            remote = remote_url(path) or "未关联 origin"
            text = f"仓库状态：已是 Git 仓库｜分支：{branch}｜远程：{remote}"
        else:
            text = "仓库状态：还不是 Git 仓库，可执行初始化。"

        self.repo_status_label.config(text=text)
        if not silent:
            self.log(text)

    def init_current_remote_push(self) -> None:
        p = self.current_project()
        if not p:
            messagebox.showinfo("提示", "请先选择项目。")
            return

        remote = self.remote_entry.get().strip()
        branch = self.branch_entry.get().strip() or DEFAULT_BRANCH
        initial_message = self.initial_commit_entry.get().strip() or "initial commit"

        if not remote:
            messagebox.showinfo("提示", "请填写 GitHub 远程仓库地址。")
            return

        if not messagebox.askyesno("确认", "即将初始化/绑定远程并推送当前项目。继续？"):
            return

        def job():
            emit = self.emit_realtime_log
            emit("=" * 72)
            emit("开始初始化 / 绑定远程 / 推送。")
            try:
                init_remote_and_push(
                    p,
                    remote=remote,
                    branch=branch,
                    commit_message=initial_message,
                    update_gitignore_first=self.gitignore_var.get(),
                    clean_before=self.clean_var.get(),
                    create_ci=self.create_ci_var.get(),
                    precheck=self.precheck_var.get(),
                    allow_risky=self.allow_risky_var.get(),
                    auto_pull_before_push=self.auto_pull_var.get(),
                    prefer_ssh_remote=self.prefer_ssh_var.get(),
                    emit=emit,
                )
                emit("初始化 / 绑定远程 / 推送流程结束。")
                return {"ok": True, "realtime": True}
            except Exception as exc:
                emit(self.format_exception_for_log(exc))
                return {"ok": False, "realtime": True}

        def done(result):
            if isinstance(result, Exception):
                self.log_error(result)
            else:
                if isinstance(result, dict) and result.get("ok"):
                    p.remote_url = remote
                    p.default_branch = branch
                    self.store.save()
                self.load_projects()
                self.refresh_current_project()

        self.run_background(job, done)


    # ---------- gitignore / clean ----------

    def add_ignore_folder(self) -> None:
        p = self.current_project()
        initial = str(p.path_obj) if p else None
        folder = filedialog.askdirectory(title="选择要忽略的文件夹", initialdir=initial)
        if not folder:
            return

        rel = folder
        if p:
            try:
                rel = str(Path(folder).resolve().relative_to(p.path_obj.resolve()))
            except Exception:
                rel = Path(folder).name

        rel = normalize_rel(rel).rstrip("/") + "/"
        self.ignore_extra_list.insert(tk.END, rel)

    def remove_selected_ignore_extra(self) -> None:
        for idx in reversed(self.ignore_extra_list.curselection()):
            self.ignore_extra_list.delete(idx)

    def extra_ignore_lines(self) -> List[str]:
        return [self.ignore_extra_list.get(i).strip() for i in range(self.ignore_extra_list.size()) if self.ignore_extra_list.get(i).strip()]

    def apply_gitignore_current(self) -> None:
        p = self.current_project()
        if not p:
            messagebox.showinfo("提示", "请先选择项目。")
            return

        def job():
            return ensure_gitignore(p.path_obj, include_defaults=True, extra_lines=self.extra_ignore_lines())

        def done(result):
            if isinstance(result, Exception):
                self.log_error(result)
            else:
                self.log(str(result))
                self.refresh_changes()

        self.run_background(job, done)

    def clean_current_cache_log(self) -> None:
        p = self.current_project()
        if not p:
            messagebox.showinfo("提示", "请先选择项目。")
            return

        if not messagebox.askyesno("确认", "确定清理当前项目中的 cache/log/__pycache__/*.pyc/*.log？"):
            return

        def job():
            removed = clean_cache_and_logs(p.path_obj)
            if not removed:
                return "没有发现需要清理的 cache/log。"
            return "已清理：\n" + "\n".join(f"  - {x}" for x in removed[:300])

        def done(result):
            if isinstance(result, Exception):
                self.log_error(result)
            else:
                self.log(str(result))
                self.refresh_changes()

        self.run_background(job, done)

    # ---------- check / CI ----------

    def write_check(self, text: str) -> None:
        self.check_text.delete("1.0", tk.END)
        self.check_text.insert("1.0", text)

    def scan_current_risky(self) -> None:
        p = self.current_project()
        if not p:
            messagebox.showinfo("提示", "请先选择项目。")
            return

        def job():
            fatal, warnings = detect_risky_files(p.path_obj)
            lines = []
            if not fatal and not warnings:
                lines.append("未发现明显误提交风险。")
            if fatal:
                lines.append("阻止级风险：")
                lines.extend([f"  - {x}" for x in fatal])
            if warnings:
                lines.append("")
                lines.append("警告：")
                lines.extend([f"  - {x}" for x in warnings])
            return "\n".join(lines)

        def done(result):
            if isinstance(result, Exception):
                self.write_check(f"错误：{result}")
            else:
                self.write_check(str(result))

        self.run_background(job, done)

    def run_current_precheck(self) -> None:
        p = self.current_project()
        if not p:
            messagebox.showinfo("提示", "请先选择项目。")
            return

        def job():
            ok, logs = run_light_ci_checks(p.path_obj)
            return ("通过" if ok else "未通过") + "\n\n" + "\n".join(logs)

        def done(result):
            if isinstance(result, Exception):
                self.write_check(f"错误：{result}")
            else:
                self.write_check(str(result))

        self.run_background(job, done)

    def create_ci_current(self) -> None:
        p = self.current_project()
        if not p:
            messagebox.showinfo("提示", "请先选择项目。")
            return

        def job():
            return write_basic_github_actions(p.path_obj)

        def done(result):
            if isinstance(result, Exception):
                self.write_check(f"错误：{result}")
            else:
                self.write_check(str(result))
                self.refresh_changes()

        self.run_background(job, done)

    # ---------- history ----------

    def clear_history(self) -> None:
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)

    def refresh_history(self) -> None:
        p = self.current_project()
        self.clear_history()
        if not p:
            return

        def job():
            return git_history(p.path_obj)

        def done(result):
            if isinstance(result, Exception):
                self.log_error(result)
                return
            self.clear_history()
            for h, d, m in result:
                self.history_tree.insert("", tk.END, values=(h, d, m))

        self.run_background(job, done)

    def rollback_selected_commit(self) -> None:
        p = self.current_project()
        if not p:
            messagebox.showinfo("提示", "请先选择项目。")
            return
        selected = self.history_tree.selection()
        if not selected:
            messagebox.showinfo("提示", "请先选择一个历史提交。")
            return

        values = self.history_tree.item(selected[0], "values")
        commit_hash = str(values[0])
        commit_msg = str(values[2]) if len(values) > 2 else ""

        force_push = self.force_push_rollback_var.get()

        msg = (
            f"即将回退到：\n{commit_hash}  {commit_msg}\n\n"
            "会执行 git reset --hard，未提交改动会被清掉。\n"
            "工具会先创建 rollback-backup-* 本地备份分支。"
        )
        if force_push:
            msg += "\n\n你勾选了强推远程，会影响 GitHub 远程历史。"

        if not messagebox.askyesno("危险操作确认", msg):
            return

        def job():
            return rollback_to_commit(p.path_obj, commit_hash, force_push=force_push, create_backup=True)

        def done(result):
            if isinstance(result, Exception):
                self.log_error(result)
            else:
                self.log(str(result))
                self.refresh_current_project()

        self.run_background(job, done)


def main() -> None:
    app = GitManagerProApp()
    app.mainloop()


if __name__ == "__main__":
    main()
