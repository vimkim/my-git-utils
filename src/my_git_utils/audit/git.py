"""Git subprocess boundary with bounded, noninteractive, read-only local checks."""

from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path


class GitError(Exception):
    pass


def run(path: Path, *args: str, timeout: float = 30) -> str:
    env = dict(os.environ)
    for key in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_COMMON_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    ):
        env.pop(key, None)
    env.update(
        GIT_TERMINAL_PROMPT="0",
        GCM_INTERACTIVE="never",
        GIT_OPTIONAL_LOCKS="0",
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_NO_LAZY_FETCH="1",
        GIT_SSH_COMMAND="ssh -o BatchMode=yes -o StrictHostKeyChecking=yes",
        GIT_ASKPASS="/bin/false",
        SSH_ASKPASS="/bin/false",
    )
    command = [
        "git",
        "-C",
        str(path),
        "-c",
        "credential.interactive=false",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "gc.auto=0",
        "-c",
        "maintenance.auto=false",
        *args,
    ]
    try:
        with subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            start_new_session=True,
        ) as proc:
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.communicate()
                raise GitError(f"timed out after {timeout:g}s") from None
        if proc.returncode:
            raise GitError(
                stderr.decode(errors="replace").strip() or f"git exited {proc.returncode}"
            )
        return stdout.decode(errors="surrogateescape")
    except OSError as err:
        raise GitError(str(err)) from err
