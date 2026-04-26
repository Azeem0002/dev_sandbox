#!/usr/bin/env python3

import time

import typer

from application import (
    get_autoclear_status,
    install_autoclear_service,
    restart_autoclear,
    start_autoclear,
    stop_autoclear,
)
from lifecycle_models import AutoclearStatus
from runtime_support import _setup_env, _setup_logger


app = typer.Typer(name="autoclear", help="Cross-platform terminal autoclear controller")


@app.callback()
def init() -> None:
    log_file = _setup_env()
    _setup_logger(log_file)


def _format_autoclear_status(status: AutoclearStatus) -> str:
    state = "running" if status.is_running else "stopped"
    parts = [f"Autoclear status: {state}", f"backend={status.backend}"]

    if status.pid is not None:
        parts.append(f"pid={status.pid}")
    if status.interval_seconds is not None:
        parts.append(f"interval={status.interval_seconds}s")
    if status.last_trigger:
        parts.append(f"last_trigger={status.last_trigger}")
    if status.pid_file is not None:
        parts.append(f"pid_file={status.pid_file}")
    if status.detail:
        parts.append(f"detail={status.detail}")

    return " | ".join(parts)


@app.command()
def status() -> None:
    typer.echo(_format_autoclear_status(get_autoclear_status()))


@app.command()
def stop() -> None:
    typer.echo(stop_autoclear())


@app.command()
def start(interval: str = typer.Option("1h", "-i", help="Interval e.g. 10s, 5m, 2h")) -> None:
    try:
        result = start_autoclear(interval)
    except (ValueError, RuntimeError) as error:
        typer.echo(f"Error: {error}")
        raise typer.Exit(code=1)

    time.sleep(1)
    typer.echo(result)


@app.command()
def restart(interval: str = typer.Option("1h", "-i", help="New interval (e.g. 600, 2h 30m)")) -> None:
    try:
        result = restart_autoclear(interval)
    except (ValueError, RuntimeError) as error:
        typer.echo(f"Error: {error}")
        raise typer.Exit(code=1)

    time.sleep(1)
    typer.echo(result)


@app.command("install-service")
def install_service(
    interval: str = typer.Option("1h", "-i", help="Interval e.g. 10s, 5m, 2h"),
    system: bool = typer.Option(False, "--system", help="Install as system-level service on Linux"),
) -> None:
    try:
        message, steps = install_autoclear_service(interval=interval, system=system)
    except (ValueError, RuntimeError) as error:
        typer.echo(f"Error: {error}")
        raise typer.Exit(code=1)

    typer.echo(message)
    for step in steps:
        typer.echo(step)


if __name__ == "__main__":
    app()
