"""
Tests for clawforge.sandbox — dynamic plugin import and registry.

Covers three core cases the CEO flagged:
  1. Normal plugin  — all lifecycle methods present, loads successfully
  2. Missing method — plugin class lacks run(); import succeeds but run_plugin
                      returns a structured error (no exception escapes)
  3. Syntax error   — module file is unparseable; load_plugin returns a
                      PluginRecord with loaded=False (no exception escapes)

Plus:
  4. init() raises  — plugin loads but init raises; record.loaded=False
  5. Namespace isolation — plugin module named "json" does NOT clobber
                           sys.modules["json"] (the stdlib module)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from clawforge.sandbox import SandboxRegistry, _MODULE_KEY_PREFIX


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_manifest(plugin_dir: Path, *, name: str, entry: str) -> None:
    manifest = {
        "name": name,
        "version": "0.1.0",
        "type": "tool",
        "engine": ">=0.1.0",
        "entry": entry,
        "config": {"timeout": 5},
    }
    (plugin_dir / "openclaw.plugin.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )


def _write_plugin_module(plugin_dir: Path, filename: str, source: str) -> None:
    (plugin_dir / filename).write_text(source, encoding="utf-8")


# ── Case 1: Normal plugin ─────────────────────────────────────────────────────

NORMAL_PLUGIN_SRC = """\
class GoodPlugin:
    def init(self, config):
        self.config = config
        self.ready = True

    def run(self, payload):
        return {"echo": payload, "ready": self.ready}

    def shutdown(self):
        self.ready = False
"""


def test_normal_plugin_loads(tmp_path):
    """A plugin with init/run/shutdown should load with record.loaded=True."""
    _write_manifest(tmp_path, name="good-plugin", entry="good_plugin:GoodPlugin")
    _write_plugin_module(tmp_path, "good_plugin.py", NORMAL_PLUGIN_SRC)

    registry = SandboxRegistry()
    record = registry.load_plugin(tmp_path)

    assert record is not None
    assert record.loaded is True
    assert record.error is None
    assert record.name == "good-plugin"
    assert record.instance is not None


def test_normal_plugin_run_returns_data(tmp_path):
    """run_plugin should invoke the plugin and return structured data."""
    _write_manifest(tmp_path, name="good-plugin", entry="good_plugin:GoodPlugin")
    _write_plugin_module(tmp_path, "good_plugin.py", NORMAL_PLUGIN_SRC)

    registry = SandboxRegistry()
    registry.load_plugin(tmp_path)
    result = registry.run_plugin("good-plugin", {"input": "hello"})

    assert result["ok"] is True
    assert result["data"]["echo"] == {"input": "hello"}


def test_normal_plugin_unloads(tmp_path):
    """unload_plugin should call shutdown() and remove the plugin from the registry."""
    _write_manifest(tmp_path, name="good-plugin", entry="good_plugin:GoodPlugin")
    _write_plugin_module(tmp_path, "good_plugin.py", NORMAL_PLUGIN_SRC)

    registry = SandboxRegistry()
    registry.load_plugin(tmp_path)
    assert len(registry.list_plugins()) == 1

    registry.unload_plugin("good-plugin")
    assert registry.list_plugins() == []


# ── Case 2: Plugin missing run() ──────────────────────────────────────────────

MISSING_RUN_SRC = """\
class NoRunPlugin:
    def init(self, config):
        self.ready = True

    def shutdown(self):
        self.ready = False
    # run() intentionally omitted
"""


def test_plugin_missing_run_still_loads(tmp_path):
    """
    A plugin that has init/shutdown but no run() should still import and
    init() should succeed (record.loaded=True).  Only calling run_plugin()
    will surface the error.
    """
    _write_manifest(tmp_path, name="no-run-plugin", entry="no_run_plugin:NoRunPlugin")
    _write_plugin_module(tmp_path, "no_run_plugin.py", MISSING_RUN_SRC)

    registry = SandboxRegistry()
    record = registry.load_plugin(tmp_path)

    assert record is not None
    assert record.loaded is True  # init succeeded


def test_plugin_missing_run_returns_error(tmp_path):
    """run_plugin on a plugin without run() must return a structured error dict
    rather than raising an AttributeError up the call stack."""
    _write_manifest(tmp_path, name="no-run-plugin", entry="no_run_plugin:NoRunPlugin")
    _write_plugin_module(tmp_path, "no_run_plugin.py", MISSING_RUN_SRC)

    registry = SandboxRegistry()
    registry.load_plugin(tmp_path)
    result = registry.run_plugin("no-run-plugin", {})

    # Must return a dict — no exception escapes.
    assert isinstance(result, dict)
    assert result.get("ok") is False
    assert "error" in result


# ── Case 3: Syntax error module ───────────────────────────────────────────────

SYNTAX_ERROR_SRC = """\
class BrokenPlugin:
    def init(self, config)  # <-- missing colon, SyntaxError
        pass
"""


def test_syntax_error_does_not_crash(tmp_path):
    """load_plugin must not raise when the module has a syntax error.
    It should return a PluginRecord with loaded=False."""
    _write_manifest(tmp_path, name="broken-plugin", entry="broken_plugin:BrokenPlugin")
    _write_plugin_module(tmp_path, "broken_plugin.py", SYNTAX_ERROR_SRC)

    registry = SandboxRegistry()
    record = registry.load_plugin(tmp_path)  # Must not raise

    assert record is not None
    assert record.loaded is False
    assert record.error is not None  # Error description stored


def test_syntax_error_run_returns_error(tmp_path):
    """Calling run_plugin on a plugin that failed to import returns an error dict."""
    _write_manifest(tmp_path, name="broken-plugin", entry="broken_plugin:BrokenPlugin")
    _write_plugin_module(tmp_path, "broken_plugin.py", SYNTAX_ERROR_SRC)

    registry = SandboxRegistry()
    registry.load_plugin(tmp_path)
    result = registry.run_plugin("broken-plugin", {})

    assert isinstance(result, dict)
    assert "error" in result


# ── Case 4: init() raises ─────────────────────────────────────────────────────

INIT_RAISES_SRC = """\
class InitRaisesPlugin:
    def init(self, config):
        raise RuntimeError("intentional init failure")

    def run(self, payload):
        return {}

    def shutdown(self):
        pass
"""


def test_init_exception_does_not_crash(tmp_path):
    """load_plugin must not propagate an exception thrown by plugin.init()."""
    _write_manifest(tmp_path, name="init-fails", entry="init_raises:InitRaisesPlugin")
    _write_plugin_module(tmp_path, "init_raises.py", INIT_RAISES_SRC)

    registry = SandboxRegistry()
    record = registry.load_plugin(tmp_path)  # Must not raise

    assert record is not None
    assert record.loaded is False
    assert "RuntimeError" in (record.error or "")


def test_init_exception_stored_in_record(tmp_path):
    """The error message from init() should be captured in record.error."""
    _write_manifest(tmp_path, name="init-fails", entry="init_raises:InitRaisesPlugin")
    _write_plugin_module(tmp_path, "init_raises.py", INIT_RAISES_SRC)

    registry = SandboxRegistry()
    record = registry.load_plugin(tmp_path)

    assert record.error is not None
    assert "intentional init failure" in record.error


# ── Case 5: Namespace isolation ───────────────────────────────────────────────

STDLIB_NAME_PLUGIN_SRC = """\
# A plugin whose file is deliberately named 'json.py' — this would clobber
# the stdlib 'json' module if we used naive importlib.import_module("json").
class JsonPlugin:
    def init(self, config):
        pass

    def run(self, payload):
        return {}

    def shutdown(self):
        pass
"""


def test_plugin_named_json_does_not_shadow_stdlib(tmp_path):
    """
    Loading a plugin whose entry module is named 'json' (same as stdlib) must
    NOT evict sys.modules['json'].  The namespaced import key (_clawforge_plugin__*)
    ensures zero collision with real module names.
    """
    import json as stdlib_json  # capture reference before loading plugin

    _write_manifest(tmp_path, name="json-plugin", entry="json:JsonPlugin")
    _write_plugin_module(tmp_path, "json.py", STDLIB_NAME_PLUGIN_SRC)

    registry = SandboxRegistry()
    record = registry.load_plugin(tmp_path)

    # Plugin loaded under our namespace, not "json"
    assert record is not None
    assert record.loaded is True

    # stdlib json still intact
    assert sys.modules.get("json") is stdlib_json

    # Our namespaced key is present
    ns_key = f"{_MODULE_KEY_PREFIX}json_plugin__json"
    assert ns_key in sys.modules

    # After unload, the namespaced key is gone but stdlib json is still there
    registry.unload_plugin("json-plugin")
    assert ns_key not in sys.modules
    assert sys.modules.get("json") is stdlib_json


def test_unload_does_not_delete_third_party_module(tmp_path):
    """
    When a plugin is unloaded, only its own namespaced sys.modules entries are
    removed.  A third-party library that happens to be in sys.modules (e.g.
    'pathlib', 'threading') must not be touched.
    """
    import pathlib  # pre-load to guarantee it's in sys.modules

    _write_manifest(tmp_path, name="good-plugin", entry="good_plugin:GoodPlugin")
    _write_plugin_module(tmp_path, "good_plugin.py", NORMAL_PLUGIN_SRC)

    registry = SandboxRegistry()
    registry.load_plugin(tmp_path)

    pathlib_before = sys.modules.get("pathlib")
    registry.unload_plugin("good-plugin")
    pathlib_after = sys.modules.get("pathlib")

    assert pathlib_before is pathlib_after  # untouched


# ── Hot reload ────────────────────────────────────────────────────────────────

def test_reload_plugin_picks_up_changes(tmp_path):
    """reload_plugin should pick up source changes (simulated by rewriting the file)."""
    _write_manifest(tmp_path, name="good-plugin", entry="good_plugin:GoodPlugin")
    _write_plugin_module(tmp_path, "good_plugin.py", NORMAL_PLUGIN_SRC)

    registry = SandboxRegistry()
    registry.load_plugin(tmp_path)

    # Overwrite the plugin with a different implementation
    updated_src = """\
class GoodPlugin:
    def init(self, config):
        self.version = "v2"

    def run(self, payload):
        return {"version": self.version}

    def shutdown(self):
        pass
"""
    _write_plugin_module(tmp_path, "good_plugin.py", updated_src)
    record = registry.reload_plugin("good-plugin")

    assert record is not None
    assert record.loaded is True
    result = registry.run_plugin("good-plugin", {})
    assert result["data"]["version"] == "v2"


def test_reload_unknown_plugin_returns_none(tmp_path):
    """reload_plugin on an unknown name should return None without raising."""
    registry = SandboxRegistry()
    result = registry.reload_plugin("does-not-exist")
    assert result is None
