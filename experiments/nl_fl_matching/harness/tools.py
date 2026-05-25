"""Bash-wrappers around the `aristotle` CLI exposed as Python functions.

Each function returns a dict that's both (a) the tool_result the
subagent sees and (b) the row we append to the JSONL trajectory.

The aristotle CLI is async-by-default: `submit` returns a project_id;
`show` polls; `ask` instructs an existing project. We do almost
everything synchronously by passing `--wait` to `submit` (the
aristotlelib client blocks until the job finishes server-side).

Invocation pattern: `uv run aristotle <subcommand> ...`. UV resolves
aristotlelib via the local pyproject / tool-install and launches it in
its own env. We DO NOT assume `aristotle` is on PATH directly.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any


# How long we let `aristotle submit --wait` block. The Aristotle docs
# say jobs can run for hours, but the smoke test should converge fast
# or we abort.
SUBMIT_WAIT_TIMEOUT_S = 30 * 60   # 30 min

# Make sure `uv` itself is findable. Common klone install paths.
_UV_PATH_EXTRAS = [
    f"{os.path.expanduser('~')}/.local/bin",
    f"{os.path.expanduser('~')}/.cargo/bin",
]


def _env_with_uv() -> dict[str, str]:
    env = dict(os.environ)
    existing = env.get("PATH", "")
    extras = ":".join(p for p in _UV_PATH_EXTRAS if p not in existing)
    if extras:
        env["PATH"] = f"{extras}:{existing}"
    return env


def _run_cli(args: list[str], cwd: str | None = None,
             stdin_text: str | None = None,
             timeout: int | None = None) -> dict[str, Any]:
    """Run the aristotle CLI via `uv run aristotle ...`.

    cwd matters: `uv run` looks for a pyproject.toml in the cwd hierarchy
    to resolve aristotlelib. Pass the lean project root (where the user
    has `uv run aristotle submit ... --project-dir .` working) or
    omit to use process cwd.
    """
    t0 = time.time()
    try:
        proc = subprocess.run(
            ["uv", "run", "aristotle", *args],
            capture_output=True, text=True,
            timeout=timeout, input=stdin_text,
            env=_env_with_uv(),
            cwd=cwd,
        )
        ok = proc.returncode == 0
        return {
            "ok": ok,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-8000:],   # truncate to keep trajectories sane
            "stderr": proc.stderr[-2000:],
            "duration_s": time.time() - t0,
        }
    except subprocess.TimeoutExpired as e:
        return {"ok": False, "returncode": -1,
                "stdout": (e.stdout.decode() if e.stdout else "")[-4000:],
                "stderr": f"TIMEOUT after {timeout}s",
                "duration_s": time.time() - t0}


def aristotle_submit(prompt: str, project_dir: str, destination: str,
                     wait: bool = True) -> dict[str, Any]:
    """Submit the lean project at `project_dir`. If wait=True, blocks
    until completion and writes the filled-in source to `destination`.

    Run with cwd=project_dir so `uv run` resolves the right env.
    """
    Path(destination).mkdir(parents=True, exist_ok=True)
    # When invoked from inside project_dir we can pass "." for the
    # --project-dir flag (matches the documented "uv run aristotle
    # submit ... --project-dir ." pattern) and an absolute path for
    # --destination.
    args = ["submit", prompt, "--project-dir", ".", "--destination", destination]
    if wait:
        args.append("--wait")
    r = _run_cli(args, cwd=project_dir,
                 timeout=SUBMIT_WAIT_TIMEOUT_S if wait else 120)
    r["tool"] = "aristotle_submit"
    r["project_id"] = _extract_project_id(r.get("stdout", ""))
    r["status"] = _extract_status(r.get("stdout", ""))
    return r


def aristotle_ask(project_id: str, prompt: str,
                  cwd: str | None = None) -> dict[str, Any]:
    """Send a follow-up instruction to an existing project."""
    r = _run_cli(["ask", project_id, prompt], cwd=cwd, timeout=120)
    r["tool"] = "aristotle_ask"
    r["project_id"] = project_id
    return r


def aristotle_show(project_id: str, limit: int = 10,
                   cwd: str | None = None) -> dict[str, Any]:
    """Pull recent events / status for a project."""
    r = _run_cli(["show", project_id, "--limit", str(limit)],
                 cwd=cwd, timeout=60)
    r["tool"] = "aristotle_show"
    r["project_id"] = project_id
    r["status"] = _extract_status(r.get("stdout", ""))
    return r


# Local file-IO tools so the subagent can read / edit the target lean file.

def read_target_file(path: str) -> dict[str, Any]:
    try:
        content = Path(path).read_text()
        return {"tool": "read_target_file", "ok": True, "path": path,
                "n_sorries": content.count("sorry"), "content": content}
    except Exception as e:
        return {"tool": "read_target_file", "ok": False, "path": path, "error": str(e)}


def write_target_file(path: str, content: str) -> dict[str, Any]:
    try:
        Path(path).write_text(content)
        return {"tool": "write_target_file", "ok": True, "path": path,
                "bytes_written": len(content),
                "n_sorries": content.count("sorry")}
    except Exception as e:
        return {"tool": "write_target_file", "ok": False, "path": path, "error": str(e)}


def lean_typecheck(project_dir: str, file_relpath: str) -> dict[str, Any]:
    """Best-effort: run `lake env lean` on one file to confirm well-typedness.
    Useful before burning an Aristotle submission on something that doesn't
    even elaborate.
    """
    t0 = time.time()
    try:
        proc = subprocess.run(
            ["lake", "env", "lean", file_relpath],
            cwd=project_dir, capture_output=True, text=True, timeout=600,
        )
        return {"tool": "lean_typecheck", "ok": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:],
                "duration_s": time.time() - t0}
    except subprocess.TimeoutExpired:
        return {"tool": "lean_typecheck", "ok": False,
                "stderr": "TIMEOUT", "duration_s": time.time() - t0}


# === parsers ===

_PROJECT_ID_RE = re.compile(r"project[_ -]?id[:\s]+([a-z0-9-]{8,})", re.I)
_STATUS_RE = re.compile(r"status[:\s]+([A-Z_]+)")


def _extract_project_id(text: str) -> str | None:
    m = _PROJECT_ID_RE.search(text)
    return m.group(1) if m else None


def _extract_status(text: str) -> str | None:
    m = _STATUS_RE.search(text)
    return m.group(1) if m else None
