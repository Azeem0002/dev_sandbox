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
        watch_autoclear,
    )
    from .lifecycle_models import AutoclearStatus
    from .runtime_adapter import is_dev_env, setup_environment, setup_logger
    from .validation import format_duration_seconds, parse_interval
except ImportError:
    from application import (
        get_autoclear_status,
        install_autoclear_service,
        restart_autoclear,
        start_autoclear,
        stop_autoclear,
        watch_autoclear,
    )
    from lifecycle_models import AutoclearStatus
    from runtime_adapter import is_dev_env, setup_environment, setup_logger
    from validation import format_duration_seconds, parse_interval


app = typer.Typer(name="autoclear", help="Cross-platform terminal autoclear controller")


# ============================================
# CLI - Thin wrapper around orchestration
# ============================================
@app.callback() # runs at app startup
def init() -> None:
    """Initialize the runtime environment for this module."""
    log_file = setup_environment()
    setup_logger(log_file)


def _format_autoclear_status(status: AutoclearStatus) -> str:
    """Format autoclear status."""
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


@app.command()
def status() -> None:
    """Display the current status to the caller."""
    typer.echo(_format_autoclear_status(get_autoclear_status()))


@app.command()
def stop() -> None:
    """Stop the requested runtime path."""
    typer.echo(stop_autoclear())


@app.command()
def start(interval: str = typer.Option("1h", "--interval", "-i", help="Interval e.g. 1m, 5m, 2h")) -> None:
    """Start the requested runtime path."""
    try:
        result = start_autoclear(interval)
    except (ValueError, RuntimeError, OSError) as error:
        typer.echo(f"Error: {error}")
        raise typer.Exit(code=1)

    time.sleep(1)
    typer.echo(result)


@app.command()
def restart(interval: str = typer.Option("1h", "--interval", "-i", help="New interval (e.g. 600, 2h 30m)")) -> None:
    """Restart the requested runtime path."""
    try:
        result = restart_autoclear(interval)
    except (ValueError, RuntimeError, OSError) as error:
        typer.echo(f"Error: {error}")
        raise typer.Exit(code=1)

    time.sleep(1)
    typer.echo(result)


@app.command()
def watch(interval: str = typer.Option("1m", "--interval", "-i", help="Interval e.g. 1m, 5m, 2h")) -> None:
    """Clear the current terminal from a foreground loop."""
    try:
        interval_label = format_duration_seconds(parse_interval(interval))
        typer.echo(f"Autoclear watch running in this terminal with interval {interval_label}. Press Ctrl+C to stop.")
        watch_autoclear(interval)
    except KeyboardInterrupt:
        typer.echo("Autoclear watch stopped")
    except (ValueError, RuntimeError, OSError) as error:
        typer.echo(f"Error: {error}")
        raise typer.Exit(code=1)


@app.command("install-service")
def install_service(
    interval: str = typer.Option("1h", "--interval", "-i", help="Interval e.g. 1m, 5m, 2h"),
    system: bool = typer.Option(False, "--system", help="Install as system-level service on Linux"),
) -> None:
    """Install service."""
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
