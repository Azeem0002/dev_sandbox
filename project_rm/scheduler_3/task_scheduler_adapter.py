"""Windows Task Scheduler adapter for scheduler.

This module owns `schtasks` command construction and Windows task installation.
service_adapter.py stays as the cross-platform facade.
"""

import subprocess
import sys
from pathlib import Path


WINDOWS_TASK_NAME = "Scheduler"


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


def _get_scheduler_script_path() -> Path:
    """Resolve the CLI entry script that the Windows task should launch."""
    return Path(__file__).with_name("scheduler.py").resolve()


def _build_windows_task_command() -> list[str]:
    """Build the `schtasks` command that launches the scheduler at user logon."""
    # Task Scheduler is native OS scheduling/service integration.
    # process_adapter is only for direct PID-file + detached-process control.
    # list2cmdline() converts Python argv pieces into the single Windows command string
    # Task Scheduler expects in its /tr field.
    task_target = subprocess.list2cmdline([sys.executable, str(_get_scheduler_script_path()), "start"])
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


def _install_windows_task() -> None:
    """Create the Windows Task Scheduler entry for the scheduler app."""
    result = _run_system_command(_build_windows_task_command())
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Failed to create Windows task")


# ============================================
# Public adapter API - stable reusable surface
# ============================================
def install_task_scheduler_service() -> tuple[str, list[str]]:
    """Install the scheduler Windows Task Scheduler backend."""
    _install_windows_task()
    return (
        f"Windows Task '{WINDOWS_TASK_NAME}' created",
        ["Task will run when the current user logs on"],
    )
