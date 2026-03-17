"""
ClawForge sandbox runtime — simulates the OpenClaw plugin registry and core
so developers can load and test plugins locally without a full OpenClaw install.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

console = Console()

# ── Logging setup ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.DEBUG,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(console=console, rich_tracebacks=True, markup=True)],
)
logger = logging.getLogger("clawforge.sandbox")


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class PluginRecord:
    name: str
    plugin_type: str
    version: str
    entry: str
    config: dict[str, Any]
    instance: Any
    manifest_path: Path
    source_dir: Path
    loaded: bool = False
    error: str | None = None


# ── Sandbox registry ──────────────────────────────────────────────────────────

class SandboxRegistry:
    """
    Simulates OpenClaw's internal plugin registry.

    Responsibilities:
    - Parse openclaw.plugin.json manifests
    - Dynamically import and instantiate plugin classes
    - Call lifecycle methods (init / shutdown)
    - Track registered plugins with status
    """

    MANIFEST_FILENAME = "openclaw.plugin.json"

    def __init__(self) -> None:
        self._plugins: dict[str, PluginRecord] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    def load_plugin(self, plugin_dir: Path) -> PluginRecord | None:
        """Load (or reload) a plugin from a directory containing a manifest.

        Returns the PluginRecord on success, or None on failure.
        """
        plugin_dir = plugin_dir.resolve()
        manifest_path = plugin_dir / self.MANIFEST_FILENAME

        if not manifest_path.exists():
            logger.error("No %s found in %s", self.MANIFEST_FILENAME, plugin_dir)
            return None

        # ── Parse manifest ────────────────────────────────────────────────────
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.error("Invalid JSON in %s: %s", manifest_path, exc)
            return None

        plugin_name = manifest.get("name", plugin_dir.name)
        plugin_type = manifest.get("type", "tool")
        version = manifest.get("version", "0.0.0")
        entry = manifest.get("entry", "")
        config = manifest.get("config", {})

        # ── Unload existing instance if reloading ─────────────────────────────
        if plugin_name in self._plugins:
            self._unload(plugin_name)

        # ── Dynamic import ────────────────────────────────────────────────────
        instance = self._import_plugin(plugin_dir, entry, plugin_name)
        if instance is None:
            record = PluginRecord(
                name=plugin_name,
                plugin_type=plugin_type,
                version=version,
                entry=entry,
                config=config,
                instance=None,
                manifest_path=manifest_path,
                source_dir=plugin_dir,
                loaded=False,
                error="Import failed — see logs above",
            )
            self._plugins[plugin_name] = record
            return record

        # ── Call init() ───────────────────────────────────────────────────────
        try:
            instance.init(config)
            loaded = True
            error = None
            logger.info("[green]✓[/green] Plugin [bold]%s[/bold] v%s loaded (%s)", plugin_name, version, plugin_type)
        except Exception as exc:
            loaded = False
            error = f"{type(exc).__name__}: {exc}"
            logger.error("Plugin %s init() failed: %s", plugin_name, exc)
            traceback.print_exc()

        record = PluginRecord(
            name=plugin_name,
            plugin_type=plugin_type,
            version=version,
            entry=entry,
            config=config,
            instance=instance,
            manifest_path=manifest_path,
            source_dir=plugin_dir,
            loaded=loaded,
            error=error,
        )
        self._plugins[plugin_name] = record
        return record

    def unload_plugin(self, plugin_name: str) -> bool:
        """Gracefully shut down and remove a plugin."""
        return self._unload(plugin_name)

    def reload_plugin(self, plugin_name: str) -> PluginRecord | None:
        """Reload a previously loaded plugin (hot reload)."""
        record = self._plugins.get(plugin_name)
        if record is None:
            logger.warning("Cannot reload unknown plugin: %s", plugin_name)
            return None
        logger.info("[yellow]↺[/yellow]  Reloading [bold]%s[/bold]…", plugin_name)
        return self.load_plugin(record.source_dir)

    def run_plugin(self, plugin_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Invoke a plugin's run() method with the given payload."""
        record = self._plugins.get(plugin_name)
        if record is None:
            return {"error": f"Plugin '{plugin_name}' not found", "plugins": list(self._plugins.keys())}
        if not record.loaded or record.instance is None:
            return {"error": f"Plugin '{plugin_name}' failed to load: {record.error}"}

        try:
            result = record.instance.run(payload)
            # Ensure JSON-serialisable result
            if not isinstance(result, dict):
                result = {"result": result}
            return {"ok": True, "plugin": plugin_name, "data": result}
        except Exception as exc:
            tb = traceback.format_exc()
            logger.error("Plugin %s run() error: %s", plugin_name, exc)
            return {"ok": False, "plugin": plugin_name, "error": str(exc), "traceback": tb}

    def list_plugins(self) -> list[dict[str, Any]]:
        """Return summary of all registered plugins."""
        return [
            {
                "name": r.name,
                "type": r.plugin_type,
                "version": r.version,
                "loaded": r.loaded,
                "error": r.error,
            }
            for r in self._plugins.values()
        ]

    def print_status(self) -> None:
        """Print a rich table showing all registered plugins."""
        table = Table(title="Sandbox Plugin Registry", border_style="cyan")
        table.add_column("Name", style="bold cyan")
        table.add_column("Type", style="magenta")
        table.add_column("Version")
        table.add_column("Status")
        table.add_column("Error", style="red")

        for r in self._plugins.values():
            status = "[green]✓ loaded[/green]" if r.loaded else "[red]✗ failed[/red]"
            table.add_row(r.name, r.plugin_type, r.version, status, r.error or "")

        console.print(table)

    # ── Private helpers ────────────────────────────────────────────────────────

    def _unload(self, plugin_name: str) -> bool:
        record = self._plugins.get(plugin_name)
        if record is None:
            return False
        if record.instance is not None:
            try:
                record.instance.shutdown()
            except Exception as exc:
                logger.warning("Plugin %s shutdown() raised: %s", plugin_name, exc)
        # Remove cached module so reimport picks up file changes
        module_name = record.entry.split(":")[0] if ":" in record.entry else record.entry
        for key in list(sys.modules.keys()):
            if key == module_name or key.startswith(module_name + "."):
                del sys.modules[key]
        del self._plugins[plugin_name]
        logger.info("[dim]Unloaded plugin %s[/dim]", plugin_name)
        return True

    def _import_plugin(self, plugin_dir: Path, entry: str, plugin_name: str) -> Any | None:
        """
        Dynamically import a plugin class from `entry` string (module:ClassName).
        Adds plugin_dir to sys.path temporarily if not already present.
        """
        if ":" not in entry:
            logger.error("Entry '%s' must be in 'module:ClassName' format", entry)
            return None

        module_path, class_name = entry.rsplit(":", 1)
        plugin_dir_str = str(plugin_dir)

        # Add to sys.path so the module can be imported
        path_added = False
        if plugin_dir_str not in sys.path:
            sys.path.insert(0, plugin_dir_str)
            path_added = True

        try:
            # Force re-import (handles hot reload)
            if module_path in sys.modules:
                del sys.modules[module_path]

            module = importlib.import_module(module_path)
            cls = getattr(module, class_name, None)
            if cls is None:
                logger.error("Class '%s' not found in module '%s'", class_name, module_path)
                return None
            return cls()
        except Exception as exc:
            logger.error("Failed to import plugin %s from %s: %s", plugin_name, entry, exc)
            traceback.print_exc()
            return None
        finally:
            if path_added and plugin_dir_str in sys.path:
                sys.path.remove(plugin_dir_str)
