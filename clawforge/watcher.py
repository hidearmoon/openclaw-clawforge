"""
ClawForge file watcher — uses watchdog to monitor plugin source files
and trigger hot-reload when changes are detected.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger("clawforge.watcher")

# File patterns that trigger a reload
WATCH_EXTENSIONS = {".py", ".json"}
# Debounce window: ignore events that arrive within this many seconds of each other
DEBOUNCE_SECONDS = 0.5


class PluginReloadHandler(FileSystemEventHandler):
    """
    Watchdog event handler that calls `reload_callback` when a watched
    source file is created, modified, or deleted.

    A simple debounce prevents flooding when an editor writes multiple
    temp files atomically.
    """

    def __init__(
        self,
        plugin_dir: Path,
        plugin_name: str,
        reload_callback: Callable[[str], None],
    ) -> None:
        super().__init__()
        self.plugin_dir = plugin_dir.resolve()
        self.plugin_name = plugin_name
        self.reload_callback = reload_callback
        self._last_event_time: float = 0.0
        self._debounce_timer: threading.Timer | None = None
        self._lock = threading.Lock()

    # ── watchdog event handlers ───────────────────────────────────────────────

    def on_modified(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def on_created(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def on_deleted(self, event: FileSystemEvent) -> None:
        self._handle(event)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _handle(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(str(event.src_path))
        if path.suffix not in WATCH_EXTENSIONS:
            return

        logger.debug("FS event: %s %s", event.event_type, path)

        with self._lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
            self._debounce_timer = threading.Timer(
                DEBOUNCE_SECONDS, self._fire_reload, args=(str(path),)
            )
            self._debounce_timer.daemon = True
            self._debounce_timer.start()

    def _fire_reload(self, changed_path: str) -> None:
        logger.info(
            "[yellow]↺[/yellow]  Change detected in [bold]%s[/bold] → reloading plugin [cyan]%s[/cyan]",
            Path(changed_path).name,
            self.plugin_name,
        )
        try:
            self.reload_callback(self.plugin_name)
        except Exception as exc:
            logger.error("Reload callback raised: %s", exc)


# ── Watcher manager ───────────────────────────────────────────────────────────

class PluginWatcher:
    """
    Manages one watchdog Observer per plugin directory.
    Multiple plugins can be watched simultaneously.
    """

    def __init__(self) -> None:
        self._observer = Observer()
        self._watches: dict[str, object] = {}  # plugin_name → watchdog watch handle

    def watch(
        self,
        plugin_dir: Path,
        plugin_name: str,
        reload_callback: Callable[[str], None],
    ) -> None:
        """Start watching a plugin directory for file changes."""
        plugin_dir = plugin_dir.resolve()
        if plugin_name in self._watches:
            logger.debug("Already watching %s, skipping.", plugin_name)
            return

        handler = PluginReloadHandler(plugin_dir, plugin_name, reload_callback)
        watch = self._observer.schedule(handler, str(plugin_dir), recursive=True)
        self._watches[plugin_name] = watch
        logger.info("[dim]Watching %s for changes…[/dim]", plugin_dir)

    def unwatch(self, plugin_name: str) -> None:
        """Stop watching a plugin directory."""
        watch = self._watches.pop(plugin_name, None)
        if watch is not None:
            self._observer.unschedule(watch)

    def start(self) -> None:
        """Start the underlying watchdog observer thread."""
        if not self._observer.is_alive():
            self._observer.start()
            logger.debug("Watchdog observer started.")

    def stop(self) -> None:
        """Stop the watchdog observer and join the thread."""
        self._observer.stop()
        self._observer.join(timeout=5)
        logger.debug("Watchdog observer stopped.")
