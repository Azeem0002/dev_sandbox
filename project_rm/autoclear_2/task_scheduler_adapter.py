"""Windows Task Scheduler adapter for autoclear.

This module owns `schtasks` command construction and Windows task installation.
service_adapter.py stays as the cross-platform facade.
"""

import subprocess
import sys

try:
    from .lifecycle_models import AutoclearStatus
    from .runtime_adapter import get_worker_script_path
except ImportError:
    from lifecycle_models import AutoclearStatus
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

def _is_windows_task_installed() -> bool:
    """Return whether the Windows Task Scheduler entry exists."""
    result = _run_system_command(["schtasks", "/query", "/tn", WINDOWS_TASK_NAME])
    return result.returncode == 0

def _install_windows_task(interval_secs: int) -> str:
    """Create the Windows Task Scheduler entry for the autoclear worker."""
    result = _run_system_command(_build_windows_task_command(interval_secs))
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


def _get_status_from_task_scheduler() -> AutoclearStatus:
    """Summarize the Windows task state into one app-facing status model."""
    # Keep this model-building in the Windows adapter, the same way systemd_adapter.py
    # owns Linux status model-building. service_adapter.py should only choose the OS
    # backend, not understand how `schtasks` status text maps to app status fields.
    task_status = _get_windows_task_status()
    if task_status is None:
        return AutoclearStatus(
            backend="task_scheduler",  # The adapter checked the Windows Task Scheduler backend.
            is_running=False,  # Missing task means Windows cannot be running this app as a task.
            pid=None,  # Task Scheduler status does not expose a stable app PID here.
            interval_seconds=None,  # The installed task stores the interval in its launch command.
            last_trigger=None,  # The simple status path does not parse last-run timestamp yet.
            detail="Autoclear Windows task not installed",
        )

    return AutoclearStatus(
        backend="task_scheduler",
        is_running=task_status.casefold() == "running",
        pid=None,
        interval_seconds=None,
        last_trigger=None,
        detail=f"task={task_status}",
    )


# ============================================
# Public adapter API - stable reusable surface
# ============================================
# Public functions use lifecycle workflow order: check installed state, install/update,
# start, stop, then read status. This matches how an operator thinks about a service.
def is_task_scheduler_service_installed() -> bool:
    """Report whether the autoclear Windows Task Scheduler backend is installed."""
    return _is_windows_task_installed()


def install_task_scheduler_service(*, interval_secs: int) -> tuple[str, list[str]]:
    """Install the autoclear Windows Task Scheduler backend."""
    _install_windows_task(interval_secs)
    return (
        f"Windows Task '{WINDOWS_TASK_NAME}' created",
        ["Task will run when the current user logs on and launch the autoclear worker."],
    )


def start_task_scheduler_service() -> str:
    """Start the installed autoclear Windows Task Scheduler backend."""
    return _start_windows_task()


def stop_task_scheduler_service() -> str:
    """Stop the running autoclear Windows Task Scheduler backend."""
    return _stop_windows_task()


def get_status_from_task_scheduler() -> AutoclearStatus:
    """Return autoclear status from the Windows Task Scheduler backend."""
    return _get_status_from_task_scheduler()
