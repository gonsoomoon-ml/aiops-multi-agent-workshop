"""GitHub tool — Tool #2 of the Rule Optimization Agent.

Two modes, controlled by `OFFLINE_MODE` env var:

- Remote (OFFLINE_MODE=0): PyGithub against real repo specified by `GITHUB_REPO`
  using a PAT in `GITHUB_TOKEN` (repo scope). Reads `rules/` and commits to
  `diagnosis/`.
- Offline (OFFLINE_MODE=1, default for Lab 1 demo): operates against the local
  project's `rules/` and `diagnosis/` directories. Useful for running Lab 1
  without GitHub credentials.

Both modes expose identical function signatures and return shapes so the Agent
can be developed offline and promoted to real GitHub without prompt changes.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

try:
    from strands import tool
except Exception:  # pragma: no cover
    def tool(fn):  # type: ignore
        return fn

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LOCAL_ROOT = _PROJECT_ROOT  # rules/ and diagnosis/ live at project root


def _offline() -> bool:
    return os.environ.get("OFFLINE_MODE", "1") == "1"


def _ensure_local_root() -> Path:
    (_LOCAL_ROOT / "rules").mkdir(exist_ok=True)
    (_LOCAL_ROOT / "diagnosis").mkdir(exist_ok=True)
    return _LOCAL_ROOT


def _remote_repo():
    from github import Github, Auth  # type: ignore

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN not set but OFFLINE_MODE=0")
    repo_full = os.environ.get("GITHUB_REPO")
    if not repo_full:
        raise RuntimeError("GITHUB_REPO not set (expected 'owner/repo')")
    gh = Github(auth=Auth.Token(token))
    return gh.get_repo(repo_full)


@tool
def list_files(path: str = "rules/") -> dict[str, Any]:
    """List files under a directory in the configured repo (or local fs).

    Args:
        path: Repo-relative directory. Typical values: `rules/`, `diagnosis/`.

    Returns:
        {"path": str, "files": [{"name": str, "path": str, "size": int, "sha": str}]}.
        `sha` is present in remote mode; empty string in offline mode.
    """
    if _offline():
        root = _ensure_local_root() / path
        files = []
        if root.exists():
            for p in sorted(root.iterdir()):
                if p.is_file() and not p.name.startswith("."):
                    files.append(
                        {
                            "name": p.name,
                            "path": f"{path.rstrip('/')}/{p.name}",
                            "size": p.stat().st_size,
                            "sha": "",
                        }
                    )
        return {"path": path, "files": files, "mode": "offline"}
    repo = _remote_repo()
    branch = os.environ.get("GITHUB_BRANCH", "main")
    contents = repo.get_contents(path.rstrip("/"), ref=branch)
    if not isinstance(contents, list):
        contents = [contents]
    files = [
        {"name": c.name, "path": c.path, "size": c.size, "sha": c.sha}
        for c in contents
        if c.type == "file"
    ]
    return {"path": path, "files": files, "mode": "remote"}


@tool
def get_file(path: str) -> dict[str, Any]:
    """Return file contents as a string, by repo-relative path."""
    if _offline():
        p = _ensure_local_root() / path
        if not p.is_file():
            return {"path": path, "found": False, "content": ""}
        return {"path": path, "found": True, "content": p.read_text(encoding="utf-8"), "mode": "offline"}
    repo = _remote_repo()
    branch = os.environ.get("GITHUB_BRANCH", "main")
    try:
        blob = repo.get_contents(path, ref=branch)
    except Exception:
        return {"path": path, "found": False, "content": ""}
    if isinstance(blob, list):
        return {"path": path, "found": False, "content": "", "error": "path is a directory"}
    raw = base64.b64decode(blob.content).decode("utf-8") if blob.encoding == "base64" else (blob.decoded_content or b"").decode("utf-8")
    return {"path": path, "found": True, "content": raw, "sha": blob.sha, "mode": "remote"}


@tool
def put_file(path: str, content: str, commit_message: str = "chore: update file") -> dict[str, Any]:
    """Create or update a file.

    Args:
        path: Repo-relative path, e.g., `diagnosis/2026-04-23-noise.md`.
        content: File contents as a string.
        commit_message: Commit message. Default is a chore update.

    Returns:
        {"path": str, "committed": bool, "commit_url": str | None, "mode": str}.
        In offline mode, `commit_url` is the local file:// URL.
    """
    if _offline():
        full = _ensure_local_root() / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        return {"path": path, "committed": True, "commit_url": f"file://{full}", "mode": "offline"}
    repo = _remote_repo()
    branch = os.environ.get("GITHUB_BRANCH", "main")
    try:
        existing = repo.get_contents(path, ref=branch)
        sha = existing.sha if not isinstance(existing, list) else None
        result = repo.update_file(path, commit_message, content, sha, branch=branch)
    except Exception:
        result = repo.create_file(path, commit_message, content, branch=branch)
    commit_sha = result["commit"].sha if isinstance(result, dict) else getattr(result.get("commit"), "sha", None)
    url = f"https://github.com/{os.environ['GITHUB_REPO']}/commit/{commit_sha}" if commit_sha else None
    return {"path": path, "committed": True, "commit_url": url, "mode": "remote"}


if __name__ == "__main__":
    os.environ.setdefault("OFFLINE_MODE", "1")
    print(list_files("rules/"))
    r = put_file("diagnosis/_smoke.md", "# smoke test\n", "chore: smoke")
    print(r)
    print(get_file("diagnosis/_smoke.md"))
