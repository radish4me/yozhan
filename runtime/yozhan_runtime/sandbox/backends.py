"""Sandbox backends.

SubprocessSandbox is the default and the realistic floor for a bare VPS: a
separate interpreter, a scrubbed environment, a working directory confined to
the workspace, and a wall-clock timeout. It is process isolation, not kernel
isolation — it stops credential leakage and runaway tools, not a determined
attacker with local code execution.

DockerSandbox is the hardened option: same scrubbed env, plus a container with
no network and a read-only mount of the tool, so a tool cannot reach the
runtime's filesystem or exfiltrate over the network at all.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from yozhan_runtime.sandbox.types import (
    DEFAULT_TIMEOUT_SECONDS,
    Sandbox,
    SandboxResult,
    child_environment,
)

_DEFAULT_IMAGE = "python:3.12-slim"


def _workspace() -> Path:
    workspace = Path(os.environ.get("YOZHAN_WORKSPACE_DIR", "workspace")).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def _finish(proc: subprocess.CompletedProcess) -> SandboxResult:
    if proc.returncode == 0:
        return SandboxResult(ok=True, output=proc.stdout)
    detail = (proc.stderr or proc.stdout or "").strip() or f"exited with code {proc.returncode}"
    return SandboxResult(ok=False, output=detail)


class SubprocessSandbox(Sandbox):
    name = "subprocess"

    def run_tool(self, tool_path: str, arguments: dict, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> SandboxResult:
        workspace = _workspace()
        env = child_environment({"YOZHAN_WORKSPACE_DIR": str(workspace)})
        # The runtime package must be importable in the child even with a
        # scrubbed env, since the runner lives inside it.
        package_root = str(Path(__file__).resolve().parents[2])
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [package_root, env.get("PYTHONPATH", "")]))

        try:
            proc = subprocess.run(
                [sys.executable, "-m", "yozhan_runtime.sandbox.runner", tool_path, json.dumps(arguments)],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=workspace,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(ok=False, output=f"tool timed out after {timeout}s")
        return _finish(proc)


class DockerSandbox(Sandbox):
    name = "docker"

    def __init__(self, image: str = _DEFAULT_IMAGE, runtime_cmd: str = "docker"):
        self.image = image
        self.runtime_cmd = runtime_cmd

    def run_tool(self, tool_path: str, arguments: dict, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> SandboxResult:
        workspace = _workspace()
        tool = Path(tool_path).resolve()
        # runner.py is deliberately dependency-free, so the container needs
        # nothing but a stock python image and these two read-only mounts.
        runner = Path(__file__).resolve().parent / "runner.py"
        command = [
            self.runtime_cmd, "run", "--rm",
            "--network", "none",
            "--memory", "512m",
            "--pids-limit", "128",
            "-v", f"{runner}:/sandbox/runner.py:ro",
            "-v", f"{tool}:/sandbox/tool.py:ro",
            "-v", f"{workspace}:/workspace",
            "-w", "/workspace",
            "-e", "YOZHAN_WORKSPACE_DIR=/workspace",
            self.image,
            "python", "/sandbox/runner.py", "/sandbox/tool.py", json.dumps(arguments),
        ]
        # The container gets no host env beyond what's passed with -e above.
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=child_environment(),
            )
        except FileNotFoundError:
            return SandboxResult(
                ok=False,
                output=f"sandbox backend '{self.runtime_cmd}' is not installed on this host",
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(ok=False, output=f"tool timed out after {timeout}s")
        return _finish(proc)
