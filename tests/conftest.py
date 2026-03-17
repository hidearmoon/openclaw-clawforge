"""
Shared pytest fixtures for the ClawForge test suite.

Provides factory fixtures used across test_test_cmd.py and other modules
that need pre-built plugin directories with controlled properties.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# ── Plugin source templates ───────────────────────────────────────────────────

GOOD_PLUGIN_SOURCE_TMPL = """\
class {class_name}:
    def init(self, config):
        self.config = config

    def run(self, payload):
        return {{"result": payload}}

    def shutdown(self):
        pass
"""

MISSING_RUN_SOURCE_TMPL = """\
class {class_name}:
    def init(self, config):
        self.config = config

    def shutdown(self):
        pass
    # run() intentionally omitted
"""

SYNTAX_ERROR_SOURCE = """\
class BrokenPlugin:
    def init(self, config)  # missing colon — SyntaxError
        pass
"""

EMPTY_METHODS_SOURCE_TMPL = """\
class {class_name}:
    def init(self):
        pass  # missing config param — signature warning

    def run(self):
        pass  # missing payload param — signature warning

    def shutdown(self):
        pass
"""


# ── Factory fixture ───────────────────────────────────────────────────────────

@pytest.fixture
def make_plugin_dir(tmp_path):
    """
    Factory fixture: create a plugin directory in tmp_path with controlled layout.

    Returns a callable:
        plugin_dir = make_plugin_dir(name="my-plugin", ...)

    Parameters
    ----------
    name            Plugin name (used as sub-directory name under tmp_path)
    version         Semver version string
    plugin_type     OpenClaw plugin type (tool / channel / memory / provider)
    entry           Manifest entry field ("module:ClassName")
    source          Plugin source code (defaults to a working implementation)
    add_readme      Write a README.md
    add_gitignore   Write a .gitignore
    add_tests       Create tests/ directory with a stub test file
    add_requirements  Write a minimal requirements.txt
    manifest_extra  Extra fields merged into the manifest dict
    omit_manifest   Skip manifest creation entirely (for manifest-absent tests)
    """

    def _factory(
        name: str = "test-plugin",
        version: str = "0.1.0",
        plugin_type: str = "tool",
        entry: str = "test_plugin:TestPlugin",
        source: str | None = None,
        add_readme: bool = True,
        add_gitignore: bool = True,
        add_tests: bool = True,
        add_requirements: bool = False,
        manifest_extra: dict | None = None,
        omit_manifest: bool = False,
    ) -> Path:
        plugin_dir = tmp_path / name
        plugin_dir.mkdir(parents=True, exist_ok=True)

        # Derive module / class from entry
        if ":" in entry:
            module_name, class_name = entry.split(":", 1)
        else:
            module_name, class_name = "test_plugin", "TestPlugin"

        # Manifest
        if not omit_manifest:
            manifest: dict = {
                "name": name,
                "version": version,
                "type": plugin_type,
                "engine": ">=0.1.0",
                "entry": entry,
            }
            if manifest_extra:
                manifest.update(manifest_extra)
            (plugin_dir / "openclaw.plugin.json").write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )

        # Plugin source
        if source is None:
            source = GOOD_PLUGIN_SOURCE_TMPL.format(class_name=class_name)
        (plugin_dir / f"{module_name}.py").write_text(source, encoding="utf-8")

        if add_readme:
            (plugin_dir / "README.md").write_text(f"# {name}\n", encoding="utf-8")
        if add_gitignore:
            (plugin_dir / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
        if add_tests:
            tests_dir = plugin_dir / "tests"
            tests_dir.mkdir(exist_ok=True)
            (tests_dir / f"test_{module_name}.py").write_text(
                f"# Tests for {name}\n", encoding="utf-8"
            )
        if add_requirements:
            (plugin_dir / "requirements.txt").write_text("click>=8.0\nrich>=13.0\n", encoding="utf-8")

        return plugin_dir

    return _factory
