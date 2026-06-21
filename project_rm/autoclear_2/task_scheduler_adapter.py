"""Windows Task Scheduler adapter for autoclear.

This module owns `schtasks` command construction and Windows task installation.
service_adapter.py stays as the cross-platform facade.
"""

import subprocess
import sys

try:
    from .runtime_adapter import get_worker_script_path
except ImportError:
    from runtime_adapter import get_worker_script_path


WINDOWS_TASK_NAME = "Autoclear"


# ============================================
# Task Scheduler adapter - reusable mental map
# ============================================

# ============================================
# Shared private skeleton - start reading here
# ============================================
def _run_system_command(command: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run one external OS command and capture stdout/stderr for adapter-level decisions."""
    return subprocess.run(
        command,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def _build_windows_task_command(interval_secs: int) -> list[str]:
    """Build the `schtasks` command that launches the autoclear worker at logon."""
    # Task Scheduler is native OS scheduling/service integration.
    # process_adapter is only for direct PID-file + detached-process control.
    # Windows Task Scheduler cannot use "every N seconds" as flexibly as systemd timers.
    # Use a startup task that launches the long-running autoclear worker with its interval argument.
    # list2cmdline() converts Python argv pieces into the single Windows command string
    # Task Scheduler expects in its /tr field.
    task_target = subprocess.list2cmdline([sys.executable, str(get_worker_script_path()), str(interval_secs)])
    return [
        "schtasks",
        "/create",
        "/tn",
        WINDOWS_TASK_NAME,
        "/tr",
        task_target,
        "/sc",
        "onlogon",
        "/rl",
        "limited",
        "/f",
    ]


def _install_windows_task(interval_secs: int) -> None:
    """Create the Windows Task Scheduler entry for the autoclear worker."""
    result = _run_system_command(_build_windows_task_command(interval_secs))
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Failed to create Windows task")


# ============================================
# Public adapter API - stable reusable surface
# ============================================
def install_task_scheduler_service(*, interval_secs: int) -> tuple[str, list[str]]:
    """Install the autoclear Windows Task Scheduler backend."""
    _install_windows_task(interval_secs)
    return (
        f"Windows Task '{WINDOWS_TASK_NAME}' created",
        ["Task will run when the current user logs on and launch the autoclear worker."],
    )
