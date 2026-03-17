"""
Tests for clawforge.watcher — debounce logic and file-change filtering.

The key invariant:
  Rapid consecutive file-system events within the debounce window (0.5 s) must
  collapse into a single reload_callback invocation.

Strategy
--------
We test the ``PluginReloadHandler`` in isolation (no real watchdog Observer)
by calling ``_handle()`` directly with synthetic ``FileSystemEvent`` objects.
After waiting for the debounce window to expire we count how many times the
callback fired.  This keeps tests fast and deterministic.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock, patch, call

import pytest

from clawforge.watcher import (
    DEBOUNCE_SECONDS,
    PluginReloadHandler,
    PluginWatcher,
    WATCH_EXTENSIONS,
)


# ── Synthetic event helpers ───────────────────────────────────────────────────

class _FakeEvent:
    """Minimal stand-in for watchdog.events.FileSystemEvent."""

    def __init__(self, src_path: str, is_directory: bool = False, event_type: str = "modified"):
        self.src_path = src_path
        self.is_directory = is_directory
        self.event_type = event_type


def _py_event(path: str = "/plugin/plugin.py") -> _FakeEvent:
    return _FakeEvent(src_path=path, event_type="modified")


def _json_event(path: str = "/plugin/openclaw.plugin.json") -> _FakeEvent:
    return _FakeEvent(src_path=path, event_type="modified")


def _txt_event(path: str = "/plugin/notes.txt") -> _FakeEvent:
    return _FakeEvent(src_path=path, event_type="modified")


def _dir_event(path: str = "/plugin/subdir") -> _FakeEvent:
    return _FakeEvent(src_path=path, is_directory=True, event_type="modified")


# ── Debounce tests ────────────────────────────────────────────────────────────

class TestDebounce:
    """The handler must collapse rapid events into a single callback."""

    _WAIT = DEBOUNCE_SECONDS + 0.3  # give the timer plenty of room to fire

    def _make_handler(self, callback: Callable) -> PluginReloadHandler:
        return PluginReloadHandler(
            plugin_dir=Path("/plugin"),
            plugin_name="test-plugin",
            reload_callback=callback,
        )

    def test_single_event_fires_callback(self):
        """One event must trigger exactly one callback after the debounce window."""
        callback = MagicMock()
        handler = self._make_handler(callback)

        handler._handle(_py_event())
        time.sleep(self._WAIT)

        callback.assert_called_once_with("test-plugin")

    def test_rapid_events_fire_callback_once(self):
        """
        Five events fired within the debounce window must produce exactly one
        callback invocation — not five.
        """
        callback = MagicMock()
        handler = self._make_handler(callback)

        for _ in range(5):
            handler._handle(_py_event())
            time.sleep(0.05)  # 50 ms gap — still within the 500 ms debounce

        time.sleep(self._WAIT)
        callback.assert_called_once()

    def test_two_bursts_fire_callback_twice(self):
        """
        Two separated bursts of events (each within the debounce window, but the
        bursts themselves are separated by > DEBOUNCE_SECONDS) must produce two
        callbacks.
        """
        callback = MagicMock()
        handler = self._make_handler(callback)

        # First burst
        for _ in range(3):
            handler._handle(_py_event())
            time.sleep(0.05)
        time.sleep(self._WAIT)  # let first burst fire

        # Second burst
        for _ in range(3):
            handler._handle(_py_event())
            time.sleep(0.05)
        time.sleep(self._WAIT)  # let second burst fire

        assert callback.call_count == 2

    def test_debounce_cancels_pending_timer(self):
        """
        Each new event should cancel the previous pending timer.  We verify this
        by checking that the callback isn't called prematurely — it should only
        fire after the *last* event's debounce window expires.
        """
        callback = MagicMock()
        handler = self._make_handler(callback)

        # Fire two events with a gap smaller than the debounce window
        handler._handle(_py_event())
        time.sleep(DEBOUNCE_SECONDS * 0.3)  # 30 % of window
        handler._handle(_py_event())

        # Callback must NOT have fired yet
        callback.assert_not_called()

        # After the full window, exactly one call
        time.sleep(self._WAIT)
        callback.assert_called_once()


# ── File-extension filtering ──────────────────────────────────────────────────

class TestFileFiltering:
    """Events for non-watched extensions must be silently ignored."""

    def _make_handler(self, callback: Callable) -> PluginReloadHandler:
        return PluginReloadHandler(
            plugin_dir=Path("/plugin"),
            plugin_name="test-plugin",
            reload_callback=callback,
        )

    def test_py_file_triggers_reload(self):
        callback = MagicMock()
        handler = self._make_handler(callback)
        handler._handle(_py_event())
        time.sleep(DEBOUNCE_SECONDS + 0.3)
        callback.assert_called_once()

    def test_json_file_triggers_reload(self):
        callback = MagicMock()
        handler = self._make_handler(callback)
        handler._handle(_json_event())
        time.sleep(DEBOUNCE_SECONDS + 0.3)
        callback.assert_called_once()

    def test_txt_file_ignored(self):
        callback = MagicMock()
        handler = self._make_handler(callback)
        handler._handle(_txt_event())
        time.sleep(DEBOUNCE_SECONDS + 0.3)
        callback.assert_not_called()

    def test_directory_event_ignored(self):
        callback = MagicMock()
        handler = self._make_handler(callback)
        handler._handle(_dir_event())
        time.sleep(DEBOUNCE_SECONDS + 0.3)
        callback.assert_not_called()

    def test_watch_extensions_contains_py_and_json(self):
        """Sanity-check the constant so tests stay in sync with production code."""
        assert ".py" in WATCH_EXTENSIONS
        assert ".json" in WATCH_EXTENSIONS


# ── on_modified / on_created / on_deleted dispatch ───────────────────────────

class TestEventDispatch:
    """All three watchdog event types (modified/created/deleted) must trigger reload."""

    _WAIT = DEBOUNCE_SECONDS + 0.3

    def _make_handler(self, callback: Callable) -> PluginReloadHandler:
        return PluginReloadHandler(
            plugin_dir=Path("/plugin"),
            plugin_name="test-plugin",
            reload_callback=callback,
        )

    def test_on_modified_dispatches(self):
        callback = MagicMock()
        handler = self._make_handler(callback)
        handler.on_modified(_FakeEvent("/plugin/a.py", event_type="modified"))
        time.sleep(self._WAIT)
        callback.assert_called_once()

    def test_on_created_dispatches(self):
        callback = MagicMock()
        handler = self._make_handler(callback)
        handler.on_created(_FakeEvent("/plugin/a.py", event_type="created"))
        time.sleep(self._WAIT)
        callback.assert_called_once()

    def test_on_deleted_dispatches(self):
        callback = MagicMock()
        handler = self._make_handler(callback)
        handler.on_deleted(_FakeEvent("/plugin/a.py", event_type="deleted"))
        time.sleep(self._WAIT)
        callback.assert_called_once()


# ── Callback exception isolation ─────────────────────────────────────────────

class TestCallbackIsolation:
    """An exception in the callback must not crash the watcher thread."""

    def test_exception_in_callback_does_not_propagate(self):
        def boom(name):
            raise RuntimeError("callback exploded")

        handler = PluginReloadHandler(
            plugin_dir=Path("/plugin"),
            plugin_name="test-plugin",
            reload_callback=boom,
        )
        # Must not raise
        handler._handle(_py_event())
        time.sleep(DEBOUNCE_SECONDS + 0.3)
        # If we reach here without an unhandled exception, the test passes.


# ── PluginWatcher manager ─────────────────────────────────────────────────────

class TestPluginWatcher:
    """Smoke-test the PluginWatcher start/stop lifecycle (no real fs needed)."""

    def test_start_and_stop(self, tmp_path):
        """PluginWatcher must start and stop without error."""
        callback = MagicMock()
        watcher = PluginWatcher()
        watcher.watch(tmp_path, "test-plugin", callback)
        watcher.start()
        time.sleep(0.1)  # let the observer thread spin up
        watcher.stop()   # must not hang or raise

    def test_double_watch_is_idempotent(self, tmp_path):
        """Calling watch() twice for the same plugin should be a no-op."""
        callback = MagicMock()
        watcher = PluginWatcher()
        watcher.watch(tmp_path, "test-plugin", callback)
        watcher.watch(tmp_path, "test-plugin", callback)  # second call — no error
        watcher.start()
        watcher.stop()

    def test_unwatch_removes_watch(self, tmp_path):
        """unwatch() should remove the plugin without raising."""
        callback = MagicMock()
        watcher = PluginWatcher()
        watcher.watch(tmp_path, "test-plugin", callback)
        watcher.start()
        watcher.unwatch("test-plugin")
        watcher.stop()
