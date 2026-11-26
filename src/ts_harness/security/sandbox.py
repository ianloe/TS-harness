"""Sandboxed code execution via Docker with no network and read-only FS."""

from __future__ import annotations

import subprocess
from collections.abc import Callable

from pydantic import BaseModel, Field


class SandboxConfig(BaseModel):
    """Resource and network isolation settings for Docker sandbox execution."""

    image: str = Field(default="python:3.12-slim")
    network_enabled: bool = Field(default=False)
    egress_allowlist: list[str] = Field(default_factory=list)
    read_only_fs: bool = Field(default=True)
    cpu_limit: str = Field(default="0.5")
    memory_limit: str = Field(default="256m")
    pids_limit: int = Field(default=64, ge=1)
    timeout_seconds: int = Field(default=30, ge=1, le=300)


class SandboxResult(BaseModel):
    """Output of a sandboxed execution."""

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


CommandRunner = Callable[[list[str], int], tuple[int, str, str]]


def _default_runner(cmd: list[str], timeout_s: int) -> tuple[int, str, str]:
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


class DockerSandboxRunner:
    """Executes untrusted Python snippets inside a locked-down Docker container."""

    def __init__(
        self,
        config: SandboxConfig | None = None,
        runner: CommandRunner | None = None,
    ) -> None:
        self._config = config or SandboxConfig()
        self._runner: CommandRunner = runner or _default_runner

    def build_docker_command(self, script: str) -> list[str]:
        """Construct the locked-down ``docker run`` command."""
        cmd = [
            "docker",
            "run",
            "--rm",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            f"--cpus={self._config.cpu_limit}",
            f"--memory={self._config.memory_limit}",
            f"--pids-limit={self._config.pids_limit}",
            "--tmpfs=/tmp:rw,noexec,nosuid,size=32m",
        ]
        if self._config.read_only_fs:
            cmd.append("--read-only")
        if not self._config.network_enabled:
            cmd.append("--network=none")
        cmd.extend([self._config.image, "python", "-c", script])
        return cmd

    def run_python(self, script: str) -> SandboxResult:
        """Run Python code in the sandbox and return captured output."""
        cmd = self.build_docker_command(script)
        try:
            code, out, err = self._runner(cmd, self._config.timeout_seconds)
            return SandboxResult(exit_code=code, stdout=out, stderr=err, timed_out=False)
        except subprocess.TimeoutExpired:
            return SandboxResult(
                exit_code=124,
                stdout="",
                stderr=f"Sandbox execution timed out after {self._config.timeout_seconds}s.",
                timed_out=True,
            )
