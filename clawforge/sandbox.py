"""
ClawForge sandbox runtime — simulates the OpenClaw plugin registry and core
so developers can load and test plugins locally without a full OpenClaw install.
"""

from __future__ import annotations

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

# Prefix for all plugin modules registered in sys.modules.
# Ensures plugin module names never collide with stdlib or third-party packages.
_MODULE_KEY_PREFIX = "_clawforge_plugin__"


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
    # Internal: namespaced sys.modules key used for this plugin's entry module.
    # Prefixed with _MODULE_KEY_PREFIX to guarantee no collision with real modules.
    _module_key: str = field(default="", repr=False)
    # Internal: sys.path entry added for this plugin (None if already present).
    _sys_path_entry: str | None = field(default=None, repr=False)


# ── Sandbox registry ──────────────────────────────────────────────────────────

class SandboxRegistry:
    """
    Simulates OpenClaw's internal plugin registry.

    Responsibilities:
    - Parse openclaw.plugin.json manifests
    - Dynamically import and instantiate plugin classes
    - Call lifecycle methods (init / shutdown)
    - Track registered plugins with status

    Module isolation strategy
    -------------------------
    Plugin entry modules are loaded via ``importlib.util.spec_from_file_location``
    and registered in ``sys.modules`` under a namespaced key::

        _clawforge_plugin__{plugin_name}__{module_path}

    This means a plugin whose entry module is named ``utils`` will never shadow
    the stdlib ``utils`` (or any other package), and cleanup is 100% scoped —
    no third-party library imported *by* the plugin is ever touched.

    sys.path management
    -------------------
    The plugin directory is added to ``sys.path`` when the plugin is loaded and
    removed when the plugin is unloaded.  Keeping the path live during the plugin
    lifetime allows plugins to use lazy imports (imports inside methods) without
    failure.
    """

    MANIFEST_FILENAME = "openclaw.plugin.json"

    def __init__(self) -> None:
        self._plugins: dict[str, PluginRecord] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    def load_plugin(self, plugin_dir: Path) -> PluginRecord | None:
        """Load (or reload) a plugin from a directory containing a manifest.

        Returns the PluginRecord on success, or None if the manifest is missing
        or cannot be parsed.  Import/init failures produce a PluginRecord with
        ``loaded=False`` rather than raising.
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
        import_result = self._import_plugin(plugin_dir, entry, plugin_name)
        if import_result is None:
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

        instance, module_key, sys_path_entry = import_result

        # ── Call init() ───────────────────────────────────────────────────────
        try:
            instance.init(config)
            loaded = True
            error = None
            logger.info(
                "[green]✓[/green] Plugin [bold]%s[/bold] v%s loaded (%s)",
                plugin_name, version, plugin_type,
            )
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
            _module_key=module_key,
            _sys_path_entry=sys_path_entry,
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

        # Remove only the plugin's own namespaced module keys from sys.modules.
        # Third-party libraries imported by the plugin are registered under their
        # own names (e.g. "requests") and will NOT be touched here.
        if record._module_key:
            prefix = record._module_key
            for key in list(sys.modules.keys()):
                if key == prefix or key.startswith(prefix + "."):
                    del sys.modules[key]

        # Remove the sys.path entry we added for this plugin (if any).
        if record._sys_path_entry and record._sys_path_entry in sys.path:
            sys.path.remove(record._sys_path_entry)

        del self._plugins[plugin_name]
        logger.info("[dim]Unloaded plugin %s[/dim]", plugin_name)
        return True

    def _import_plugin(
        self,
        plugin_dir: Path,
        entry: str,
        plugin_name: str,
    ) -> tuple[Any, str, str | None] | None:
        """
        Dynamically import a plugin class from ``entry`` (``module:ClassName``).

        Returns ``(instance, module_key, sys_path_entry)`` on success or ``None``
        on failure.  The caller is responsible for storing these values in the
        PluginRecord so that ``_unload`` can clean up correctly.

        Isolation guarantees
        --------------------
        * The entry module is loaded via ``spec_from_file_location`` and
          registered in ``sys.modules`` under a namespaced key that starts with
          ``_clawforge_plugin__``.  This prevents the plugin module from
          shadowing any stdlib or third-party package, regardless of what the
          developer chose to name it.
        * The ``plugin_dir`` is added to ``sys.path`` and kept there until the
          plugin is unloaded, so that lazy imports (imports inside methods) and
          sibling-module imports work correctly.
        """
        if ":" not in entry:
            logger.error("Entry '%s' must be in 'module:ClassName' format", entry)
            return None

        module_path, class_name = entry.rsplit(":", 1)
        plugin_dir_str = str(plugin_dir)

        # Build a unique, namespaced key for sys.modules.
        safe_name = plugin_name.replace("-", "_")
        module_key = f"{_MODULE_KEY_PREFIX}{safe_name}__{module_path}"

        # Add plugin_dir to sys.path so sibling imports and lazy imports work.
        # We track whether we added it so _unload can remove it.
        sys_path_entry: str | None = None
        if plugin_dir_str not in sys.path:
            sys.path.insert(0, plugin_dir_str)
            sys_path_entry = plugin_dir_str

        try:
            # Evict any previously cached version under our namespaced key.
            for key in list(sys.modules.keys()):
                if key == module_key or key.startswith(module_key + "."):
                    del sys.modules[key]

            # Locate the module file.
            module_file = plugin_dir / f"{module_path.replace('.', '/')}.py"
            if not module_file.exists():
                logger.error(
                    "Module file '%s' not found in plugin dir '%s'",
                    module_file.name, plugin_dir,
                )
                if sys_path_entry and sys_path_entry in sys.path:
                    sys.path.remove(sys_path_entry)
                return None

            spec = importlib.util.spec_from_file_location(module_key, module_file)
            if spec is None or spec.loader is None:
                logger.error("Cannot create module spec for %s", module_file)
                if sys_path_entry and sys_path_entry in sys.path:
                    sys.path.remove(sys_path_entry)
                return None

            module = importlib.util.module_from_spec(spec)
            # Register before exec so circular imports within the plugin work.
            sys.modules[module_key] = module
            spec.loader.exec_module(module)  # type: ignore[union-attr]

            cls = getattr(module, class_name, None)
            if cls is None:
                logger.error(
                    "Class '%s' not found in module '%s'", class_name, module_path
                )
                del sys.modules[module_key]
                if sys_path_entry and sys_path_entry in sys.path:
                    sys.path.remove(sys_path_entry)
                return None

            return cls(), module_key, sys_path_entry

        except Exception as exc:
            logger.error(
                "Failed to import plugin %s from %s: %s", plugin_name, entry, exc
            )
            traceback.print_exc()
            # Clean up any partial module registration.
            sys.modules.pop(module_key, None)
            if sys_path_entry and sys_path_entry in sys.path:
                sys.path.remove(sys_path_entry)
            return None
