import getpass
import shlex
import subprocess
import sys
from pathlib import Path

import typer

try:
    from .platform_adapter import _detect_platform
except ImportError:
    from platform_adapter import _detect_platform


def _format_exec_args(args: list[str]) -> str:
    return " ".join(shlex.quote(arg) for arg in args)


def _build_systemd_service(*, system: bool) -> str:
    scheduler_script = Path(__file__).with_name("scheduler.py").resolve()
    service_lines = [
        "[Unit]",
        "Description=Job Scheduler",
        "After=network.target",
        "",
        "[Service]",
        "Type=simple",
    ]

    if system:
        service_lines.append(f"User={getpass.getuser()}")

    service_lines.extend([
        f"WorkingDirectory={scheduler_script.parent}",
        f"ExecStart={_format_exec_args([sys.executable, str(scheduler_script), 'start'])}",
        "Restart=on-failure",
        "RestartSec=10",
        "MemoryMax=200M",
        "CPUQuota=50%",
        "StandardOutput=journal",
        "StandardError=journal",
        "",
        "[Install]",
        f"WantedBy={'multi-user.target' if system else 'default.target'}",
        "",
    ])
    return "\n".join(service_lines)


def _build_windows_task_command() -> list[str]:
    scheduler_script = Path(__file__).with_name("scheduler.py").resolve()
    task_target = subprocess.list2cmdline([sys.executable, str(scheduler_script), "start"])

    return [
        "schtasks",
        "/create",
        "/tn",
        "Scheduler",
        "/tr",
        task_target,
        "/sc",
        "onlogon",
        "/rl",
        "limited",
        "/f",
    ]


def _install_windows_task() -> None:
    command = _build_windows_task_command()
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to create task: {result.stderr.strip()}")


def _install_systemd_user(content: str) -> Path:
    path = Path.home() / ".config/systemd/user/scheduler.service"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _install_systemd_system(content: str) -> Path:
    path = Path("/etc/systemd/system/scheduler.service")

    try:
        result = subprocess.run(
            ["sudo", "tee", str(path)],
            input=content,
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr)
        return path
    except Exception:
        typer.echo("\n✗ Automated install failed. Run manually:")
        typer.echo(f"  echo '{content}' | sudo tee {path}")
        typer.echo("  sudo systemctl daemon-reload")
        typer.echo("  sudo systemctl enable scheduler")
        typer.echo("  sudo systemctl start scheduler")
        raise typer.Exit(1)


def install_scheduler_service(system: bool = False) -> tuple[str, list[str]]:
    platform = _detect_platform()

    if platform == "windows":
        _install_windows_task()
        return (
            "✓ Windows Task 'Scheduler' created",
            ["Task will run when the current user logs on"],
        )

    if platform == "linux":
        content = _build_systemd_service(system=system)
        if system:
            path = _install_systemd_system(content)
            return (
                f"✓ System service installed at {path}",
                [
                    "sudo systemctl daemon-reload",
                    "Then run `scheduler start` to activate the installed service.",
                ],
            )

        path = _install_systemd_user(content)
        return (
            f"✓ User service installed at {path}",
            [
                "systemctl --user daemon-reload",
                f"loginctl enable-linger {getpass.getuser()}",
                "Then run `scheduler start` to activate the installed service.",
            ],
        )

    if platform == "mac":
        return (
            "✗ macOS not yet supported",
            ["Use launchd manually or run with --daemon flag"],
        )

    raise RuntimeError(f"Unsupported platform: {platform}")
