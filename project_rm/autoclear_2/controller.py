#!/usr/bin/env python3
"""CLI boundary for autoclear.

This file translates command-line input/output into calls to the application layer.
Keep real orchestration out of here as much as possible.
"""

import time

import typer

try:
    from .application import (
        get_autoclear_status,
        install_autoclear_service,
        restart_autoclear,
        start_autoclear,
        stop_autoclear,
    )
    from .lifecycle_models import AutoclearStatus
    from .runtime_adapter import is_dev_env, setup_environment, setup_logger
    from .validation import format_duration_seconds
except ImportError:
    from application import (
        get_autoclear_status,
        install_autoclear_service,
        restart_autoclear,
        start_autoclear,
        stop_autoclear,
    )
    from lifecycle_models import AutoclearStatus
    from runtime_adapter import is_dev_env, setup_environment, setup_logger
    from validation import format_duration_seconds


app = typer.Typer(name="autoclear", help="Cross-platform terminal autoclear controller")


# ============================================
# CLI - Thin wrapper around orchestration
# ============================================
# Boundary mental model:
# 1. Typer receives raw terminal strings/options from the user.
# 2. This file does only CLI responsibilities: setup, friendly errors, and printing.
# 3. The application layer parses interval meaning and chooses process/systemd backend.
# 4. The process/systemd adapters do OS work. Keep those side effects out of the CLI.
@app.callback() # runs at app startup
def init() -> None:
    """Initialize the runtime environment for this module."""
    log_file = setup_environment()
    setup_logger(log_file)


def _format_autoclear_status(status: AutoclearStatus) -> str:
    """Format autoclear status."""
    # Status is already a typed app model. The CLI's only job here is to turn
    # that model into readable text for a human at the terminal.
    state = "running" if status.is_running else "stopped"
    parts = [f"Autoclear status: {state}", f"backend: {status.backend}"] # default variables

    if status.pid is not None:
        parts.append(f"pid= {status.pid}")
    if status.interval_seconds is not None:
        parts.append(f"interval= {format_duration_seconds(status.interval_seconds)}")
    if status.last_trigger:
        parts.append(f"last_trigger= {status.last_trigger}")
    if status.pid_file is not None and is_dev_env():
        parts.append(f"pid_file= {status.pid_file}")
    if status.target_tty is not None and is_dev_env():
        parts.append(f"target_tty= {status.target_tty}")
    if status.detail:
        parts.append(f"detail= {status.detail}")

    return " | ".join(parts)


# Typer's Public API

@app.command()
def status(system: bool = typer.Option(False, "--system", help="Check system-level service on Linux")) -> None:
    """Display the current status to the caller."""
    typer.echo(_format_autoclear_status(get_autoclear_status(system=system)))


@app.command()
def stop(system: bool = typer.Option(False, "--system", help="Stop system-level service on Linux")) -> None:
    """Stop the requested runtime path."""
    typer.echo(stop_autoclear(system=system))


@app.command()
def start(
    interval: str = typer.Option("1h", "--interval", "-i", help="Interval e.g. 1m, 1h30m, 2h"),
    system: bool = typer.Option(False, "--system", help="Start system-level service on Linux"),
) -> None:
    """Start the requested runtime path."""
    try:
        # Pass raw user text down to the application. Do not parse it here;
        # parse_interval lives below the boundary so CLI/API can share the rule.
        result = start_autoclear(interval, system=system)
    except (ValueError, RuntimeError, OSError) as error:
        typer.echo(f"Error: {error}")
        raise typer.Exit(code=1)

    time.sleep(1)
    typer.echo(result)


@app.command()
def restart(
    interval: str = typer.Option("1h", "--interval", "-i", help="New interval (e.g. 600, 2h 30m)"),
    system: bool = typer.Option(False, "--system", help="Restart system-level service on Linux"),
) -> None:
    """Restart the requested runtime path."""
    try:
        # Restart follows the same boundary rule as start: CLI accepts text,
        # application validates meaning, adapters perform process/service work.
        result = restart_autoclear(interval, system=system)
    except (ValueError, RuntimeError, OSError) as error:
        typer.echo(f"Error: {error}")
        raise typer.Exit(code=1)

    time.sleep(1)
    typer.echo(result)


@app.command("install-service")
def install_service(
    interval: str = typer.Option("1h", "--interval", "-i", help="Interval e.g. 1m, 5m, 2h"),
    system: bool = typer.Option(False, "--system", help="Install as system-level service on Linux"),
) -> None:
    """Install or update service."""
    try:
        message, steps = install_autoclear_service(interval=interval, system=system)
    except (ValueError, RuntimeError) as error:
        typer.echo(f"Error: {error}")
        raise typer.Exit(code=1)

    typer.echo(message)
    for step in steps:
        typer.echo(step)


def main() -> None:
    """Run the module entrypoint."""
    app()


if __name__ == "__main__":
    main()
