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

def _is_windows_task_installed() -> bool:
    """Return whether the Windows Task Scheduler entry exists."""
    result = _run_system_command(["schtasks", "/query", "/tn", WINDOWS_TASK_NAME])
    return result.returncode == 0

def _install_windows_task() -> str:
    """Create the Windows Task Scheduler entry for the scheduler app."""
    result = _run_system_command(_build_windows_task_command())
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Failed to create Windows task")
    return f"Windows task installed successfully"

def _start_windows_task() -> str:
    """Run the installed Windows Task Scheduler entry now."""
    result = _run_system_command(["schtasks", "/run", "/tn", WINDOWS_TASK_NAME])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Failed to start Windows task")
    return f"STARTED: Windows Task '{WINDOWS_TASK_NAME}'"


def _stop_windows_task() -> str:
    """End the currently running Windows Task Scheduler entry."""
    result = _run_system_command(["schtasks", "/end", "/tn", WINDOWS_TASK_NAME])
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "Failed to stop Windows task"
        if "not currently running" in message.casefold():
            return f"STOPPED: Windows Task '{WINDOWS_TASK_NAME}' already stopped"
        raise RuntimeError(message)
    return f"STOPPED: Windows Task '{WINDOWS_TASK_NAME}'"


def _get_windows_task_status() -> str | None:
    """Return the Windows Task Scheduler status text when the task exists."""
    result = _run_system_command(["schtasks", "/query", "/tn", WINDOWS_TASK_NAME, "/fo", "LIST", "/v"])
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        if line.casefold().startswith("status:"):
            return line.split(":", 1)[1].strip()
    return "installed"


# ============================================
# Public adapter API - stable reusable surface
# ============================================
# Public functions use lifecycle workflow order: check installed state, install/update,
# start, stop, then read status. This matches how an operator thinks about a service.
def is_task_scheduler_service_installed() -> bool:
    """Report whether the scheduler Windows Task Scheduler backend is installed."""
    return _is_windows_task_installed()


def install_task_scheduler_service() -> tuple[str, list[str]]:
    """Install the scheduler Windows Task Scheduler backend."""
    _install_windows_task()
    return (
        f"Windows Task '{WINDOWS_TASK_NAME}' created",
        ["Task will run when the current user logs on and launch the scheduler worker."],
    )


def start_task_scheduler_service() -> str:
    """Start the installed scheduler Windows Task Scheduler backend."""
    return _start_windows_task()


def stop_task_scheduler_service() -> str:
    """Stop the running scheduler Windows Task Scheduler backend."""
    return _stop_windows_task()


def get_task_scheduler_service_status() -> str | None:
    """Return scheduler status from the Windows Task Scheduler backend."""
    return _get_windows_task_status()
