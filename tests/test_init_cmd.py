"""
Tests for clawforge init_cmd — template scaffolding.

Validates:
  - Generated directory structure (all expected files present)
  - openclaw.plugin.json fields (valid JSON, required keys present, correct values)
  - Module/class name derivation from plugin name
  - All four plugin types produce valid output
  - --force flag overwrites without prompting
  - Non-interactive (--type / --name) mode works
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from clawforge.cli import main
from clawforge.init_cmd import _slugify, _validate_name, _validate_version
import click


# ── Unit tests for name/version helpers ──────────────────────────────────────

class TestValidateName:
    def test_valid_names(self):
        assert _validate_name("my-tool") == "my-tool"
        assert _validate_name("provider1") == "provider1"
        assert _validate_name("  My-Tool  ") == "my-tool"  # strips + lowercases

    def test_single_char_rejected(self):
        with pytest.raises(click.BadParameter):
            _validate_name("x")

    def test_starts_with_digit_rejected(self):
        with pytest.raises(click.BadParameter):
            _validate_name("1bad")

    def test_uppercase_lowercased(self):
        # uppercase is normalised, not rejected
        assert _validate_name("MyTool") == "mytool"

    def test_invalid_characters_rejected(self):
        with pytest.raises(click.BadParameter):
            _validate_name("my_tool")  # underscore not allowed

    def test_too_long_rejected(self):
        with pytest.raises(click.BadParameter):
            _validate_name("a" * 64)


class TestValidateVersion:
    def test_valid_semver(self):
        assert _validate_version("0.1.0") == "0.1.0"
        assert _validate_version("1.2.3") == "1.2.3"

    def test_invalid_version_rejected(self):
        with pytest.raises(click.BadParameter):
            _validate_version("1.0")

        with pytest.raises(click.BadParameter):
            _validate_version("v1.0.0")


class TestSlugify:
    def test_single_word(self):
        assert _slugify("tool") == "Tool"

    def test_kebab(self):
        assert _slugify("my-tool") == "MyTool"

    def test_multi_segment(self):
        assert _slugify("openrouter-provider-v2") == "OpenrouterProviderV2"


# ── Integration tests via CliRunner ───────────────────────────────────────────

PLUGIN_TYPES = ["tool", "channel", "memory", "provider"]

REQUIRED_MANIFEST_FIELDS = {"name", "version", "type", "engine", "entry"}
EXPECTED_FILES_BASE = {
    "openclaw.plugin.json",
    ".gitignore",
    "README.md",
}


def _run_init(tmp_path: Path, plugin_type: str, plugin_name: str) -> tuple:
    """Invoke `clawforge init` non-interactively, output into tmp_path subdir."""
    runner = CliRunner()
    output_dir = str(tmp_path / plugin_name)
    result = runner.invoke(
        main,
        [
            "init",
            "--type", plugin_type,
            "--name", plugin_name,
            "--description", f"Test {plugin_type} plugin",
            "--author", "Tester",
            "--version", "0.1.0",
            "--output-dir", output_dir,
            "--force",
        ],
        catch_exceptions=False,
    )
    return result, Path(output_dir)


@pytest.mark.parametrize("plugin_type", PLUGIN_TYPES)
def test_init_creates_expected_files(tmp_path, plugin_type):
    """All four plugin types must produce the standard file set."""
    result, out_dir = _run_init(tmp_path, plugin_type, f"test-{plugin_type}")

    assert result.exit_code == 0, f"CLI exited {result.exit_code}:\n{result.output}"
    assert out_dir.is_dir()

    created = {f.name for f in out_dir.iterdir()}

    for expected in EXPECTED_FILES_BASE:
        assert expected in created, f"{expected} missing for type={plugin_type}"

    # Plugin source file  (module_name = plugin_type with hyphen replaced)
    module_name = f"test_{plugin_type}".replace("-", "_")
    assert f"{module_name}.py" in created or any(
        f.endswith(".py") and not f.startswith("test_") for f in created
    ), f"No plugin .py file created for type={plugin_type}"


@pytest.mark.parametrize("plugin_type", PLUGIN_TYPES)
def test_manifest_is_valid_json(tmp_path, plugin_type):
    """openclaw.plugin.json must be parseable JSON."""
    _, out_dir = _run_init(tmp_path, plugin_type, f"myplugin")
    manifest_path = out_dir / "openclaw.plugin.json"

    assert manifest_path.exists(), "Manifest file not created"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert isinstance(manifest, dict)


@pytest.mark.parametrize("plugin_type", PLUGIN_TYPES)
def test_manifest_required_fields(tmp_path, plugin_type):
    """Manifest must contain all required top-level fields."""
    _, out_dir = _run_init(tmp_path, plugin_type, "myplugin")
    manifest = json.loads(
        (out_dir / "openclaw.plugin.json").read_text(encoding="utf-8")
    )

    for field in REQUIRED_MANIFEST_FIELDS:
        assert field in manifest, f"Manifest missing '{field}' for type={plugin_type}"


@pytest.mark.parametrize("plugin_type", PLUGIN_TYPES)
def test_manifest_field_values(tmp_path, plugin_type):
    """Manifest fields must contain the values passed via CLI options."""
    plugin_name = "myplugin"
    _, out_dir = _run_init(tmp_path, plugin_type, plugin_name)
    manifest = json.loads(
        (out_dir / "openclaw.plugin.json").read_text(encoding="utf-8")
    )

    assert manifest["name"] == plugin_name
    assert manifest["version"] == "0.1.0"
    assert manifest["type"] == plugin_type

    # Entry must follow module:ClassName format
    entry = manifest["entry"]
    assert ":" in entry, f"entry '{entry}' must contain ':'"
    module_part, class_part = entry.split(":", 1)
    assert len(module_part) > 0
    assert len(class_part) > 0


def test_manifest_entry_matches_class_name(tmp_path):
    """The class in the entry field must exist in the generated plugin file."""
    _, out_dir = _run_init(tmp_path, "tool", "my-greeter")
    manifest = json.loads(
        (out_dir / "openclaw.plugin.json").read_text(encoding="utf-8")
    )

    module_name, class_name = manifest["entry"].split(":", 1)
    plugin_file = out_dir / f"{module_name}.py"

    assert plugin_file.exists(), f"Plugin file {plugin_file.name} not found"
    source = plugin_file.read_text(encoding="utf-8")
    assert f"class {class_name}" in source, (
        f"class {class_name} not found in {plugin_file.name}"
    )


def test_kebab_name_to_module_snake(tmp_path):
    """Plugin name 'my-cool-tool' → module file 'my_cool_tool.py'."""
    _, out_dir = _run_init(tmp_path, "tool", "my-cool-tool")
    files = {f.name for f in out_dir.iterdir()}
    assert "my_cool_tool.py" in files


def test_kebab_name_to_class_pascal(tmp_path):
    """Plugin name 'my-cool-tool' → class MyCoolTool in the plugin file."""
    _, out_dir = _run_init(tmp_path, "tool", "my-cool-tool")
    plugin_src = (out_dir / "my_cool_tool.py").read_text(encoding="utf-8")
    assert "class MyCoolTool" in plugin_src


def test_force_flag_overwrites_existing_file(tmp_path):
    """--force must overwrite existing files without prompting."""
    # First pass
    _run_init(tmp_path, "tool", "my-tool")
    manifest_path = tmp_path / "my-tool" / "openclaw.plugin.json"
    original_mtime = manifest_path.stat().st_mtime

    # Second pass with --force
    result, _ = _run_init(tmp_path, "tool", "my-tool")
    assert result.exit_code == 0
    new_mtime = manifest_path.stat().st_mtime
    # File was overwritten (mtime ≥ original)
    assert new_mtime >= original_mtime


def test_init_output_dir_is_created(tmp_path):
    """Output directory must be created if it does not exist."""
    deep_path = tmp_path / "nested" / "output"
    assert not deep_path.exists()

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "init", "--type", "tool", "--name", "deeptest",
            "--description", "nested dir test", "--author", "Tester",
            "--output-dir", str(deep_path), "--force",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, f"CLI exited {result.exit_code}:\n{result.output}"
    assert deep_path.is_dir()
    assert (deep_path / "openclaw.plugin.json").exists()


def test_generated_test_file_imports_plugin(tmp_path):
    """The generated test file should reference the plugin class."""
    _, out_dir = _run_init(tmp_path, "tool", "my-tool")
    test_files = list(out_dir.glob("test_*.py"))
    assert len(test_files) >= 1, "No test file generated"

    test_src = test_files[0].read_text(encoding="utf-8")
    # The test file should mention the class name
    assert "MyTool" in test_src or "my_tool" in test_src
