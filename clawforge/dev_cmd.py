"""
clawforge dev command — local plugin dev sandbox with hot-reload and HTTP control API.

HTTP endpoints (default port 9621):
  GET  /           → health check + plugin list
  GET  /plugins    → list all registered plugins
  POST /run/{name} → invoke plugin.run(payload)
  POST /reload/{name} → manually trigger reload
  GET  /status     → registry status table (text)
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
import threading
from pathlib import Path
from typing import Any

import click
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from clawforge.sandbox import SandboxRegistry
from clawforge.watcher import PluginWatcher

console = Console()
logger = logging.getLogger("clawforge.dev")

DEV_SERVER_PORT = 9621


# ── FastAPI application factory ───────────────────────────────────────────────

def build_app(registry: SandboxRegistry) -> FastAPI:
    app = FastAPI(
        title="ClawForge Dev Sandbox",
        description="Hot-reload sandbox HTTP control API for OpenClaw plugin development.",
        version="0.1.0",
    )

    @app.get("/", response_class=JSONResponse)
    async def root():
        plugins = registry.list_plugins()
        return {
            "service": "ClawForge Dev Sandbox",
            "version": "0.1.0",
            "plugins_loaded": sum(1 for p in plugins if p["loaded"]),
            "plugins_failed": sum(1 for p in plugins if not p["loaded"]),
            "plugins": plugins,
        }

    @app.get("/plugins", response_class=JSONResponse)
    async def list_plugins():
        return {"plugins": registry.list_plugins()}

    @app.post("/run/{plugin_name}", response_class=JSONResponse)
    async def run_plugin(plugin_name: str, request: Request):
        try:
            body = await request.json()
        except Exception:
            body = {}

        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Request body must be a JSON object.")

        result = registry.run_plugin(plugin_name, body)
        status_code = 200 if result.get("ok", True) else 500
        return JSONResponse(content=result, status_code=status_code)

    @app.post("/reload/{plugin_name}", response_class=JSONResponse)
    async def reload_plugin(plugin_name: str):
        record = registry.reload_plugin(plugin_name)
        if record is None:
            raise HTTPException(status_code=404, detail=f"Plugin '{plugin_name}' not found.")
        return {
            "plugin": plugin_name,
            "loaded": record.loaded,
            "error": record.error,
        }

    @app.get("/status", response_class=PlainTextResponse)
    async def status():
        """Return plain-text registry status (for terminal piping)."""
        plugins = registry.list_plugins()
        lines = ["ClawForge Dev Sandbox — Plugin Registry\n"]
        lines.append(f"{'NAME':<30} {'TYPE':<12} {'VERSION':<10} {'STATUS'}")
        lines.append("-" * 70)
        for p in plugins:
            status_str = "✓ loaded" if p["loaded"] else f"✗ {p.get('error', 'failed')}"
            lines.append(f"{p['name']:<30} {p['type']:<12} {p['version']:<10} {status_str}")
        return "\n".join(lines)

    return app


# ── Dev command ───────────────────────────────────────────────────────────────

@click.command("dev")
@click.argument("plugin_dir", default=".", type=click.Path(exists=True, file_okay=False))
@click.option("--port", "-p", default=DEV_SERVER_PORT, show_default=True, help="HTTP control API port.")
@click.option("--no-watch", is_flag=True, default=False, help="Disable hot-reload file watcher.")
@click.option("--no-server", is_flag=True, default=False, help="Skip HTTP server (CLI-only mode).")
def dev(plugin_dir: str, port: int, no_watch: bool, no_server: bool):
    """Start a local dev sandbox with hot-reload for OpenClaw plugin development.

    \b
    PLUGIN_DIR  Directory containing openclaw.plugin.json (default: current dir)

    \b
    The sandbox will:
      1. Load the plugin from PLUGIN_DIR
      2. Watch for file changes and auto-reload (unless --no-watch)
      3. Expose an HTTP API on port 9621 for manual trigger testing

    \b
    HTTP API:
      GET  http://localhost:9621/           list plugins + status
      POST http://localhost:9621/run/<name> invoke plugin.run(payload)
      POST http://localhost:9621/reload/<name> manually reload

    \b
    Examples:
      clawforge dev .
      clawforge dev ./my-tool-plugin --port 9000
      clawforge dev . --no-watch
    """
    plugin_dir_path = Path(plugin_dir).resolve()

    console.print(Panel.fit(
        "[bold cyan]ClawForge[/bold cyan] [white]Dev Sandbox[/white]",
        border_style="cyan",
    ))
    console.print(f"[dim]Plugin directory:[/dim] {plugin_dir_path}")
    console.print(f"[dim]HTTP port        :[/dim] {port}")
    console.print(f"[dim]Hot-reload       :[/dim] {'disabled' if no_watch else 'enabled'}")
    console.print()

    # ── Load plugin ───────────────────────────────────────────────────────────
    registry = SandboxRegistry()
    record = registry.load_plugin(plugin_dir_path)
    if record is None:
        console.print("[red]✗[/red]  Failed to load plugin — no openclaw.plugin.json found.")
        sys.exit(1)

    registry.print_status()
    console.print()

    # ── Set up watcher ────────────────────────────────────────────────────────
    watcher: PluginWatcher | None = None
    if not no_watch:
        watcher = PluginWatcher()
        watcher.watch(plugin_dir_path, record.name, registry.reload_plugin)
        watcher.start()

    # ── Start HTTP server ─────────────────────────────────────────────────────
    if no_server:
        console.print("[yellow]HTTP server disabled.[/yellow] Press Ctrl+C to stop.\n")
        try:
            _wait_for_interrupt()
        finally:
            if watcher:
                watcher.stop()
        return

    app = build_app(registry)
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)

    console.print(
        f"[bold green]✓[/bold green]  Sandbox running at "
        f"[underline]http://127.0.0.1:{port}[/underline]"
    )
    console.print("[dim]Press Ctrl+C to stop.[/dim]\n")
    _print_quickstart(record.name, port)

    # Run uvicorn in a background thread so we can handle signals cleanly
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    try:
        _wait_for_interrupt()
    except KeyboardInterrupt:
        pass
    finally:
        console.print("\n[dim]Shutting down…[/dim]")
        server.should_exit = True
        server_thread.join(timeout=5)
        if watcher:
            watcher.stop()
        # Shutdown all plugins gracefully
        for plugin_info in registry.list_plugins():
            registry.unload_plugin(plugin_info["name"])
        console.print("[bold]Goodbye.[/bold]")


def _wait_for_interrupt() -> None:
    """Block the main thread until SIGINT / SIGTERM."""
    stop = threading.Event()

    original_sigint = signal.getsignal(signal.SIGINT)
    original_sigterm = signal.getsignal(signal.SIGTERM)

    def _handler(sig, frame):
        stop.set()

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)

    try:
        while not stop.is_set():
            stop.wait(timeout=0.5)
    finally:
        signal.signal(signal.SIGINT, original_sigint)
        signal.signal(signal.SIGTERM, original_sigterm)


def _print_quickstart(plugin_name: str, port: int) -> None:
    table = Table(show_header=True, border_style="dim", header_style="bold")
    table.add_column("Action")
    table.add_column("Command")

    table.add_row("List plugins",  f"curl http://localhost:{port}/plugins")
    table.add_row(
        "Invoke plugin",
        f'curl -X POST http://localhost:{port}/run/{plugin_name} \\\n'
        f'     -H "Content-Type: application/json" \\\n'
        f'     -d \'{{"input": "hello"}}\''
    )
    table.add_row("Hot-reload",    f"curl -X POST http://localhost:{port}/reload/{plugin_name}")
    table.add_row("Status",        f"curl http://localhost:{port}/status")

    console.print(table)
    console.print()
