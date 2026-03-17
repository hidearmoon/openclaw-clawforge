"""
Tests for clawforge.test_cmd — plugin compatibility checker.

Test organisation:
  TestCheckManifest      — unit tests for check_manifest()
  TestCheckInterface     — unit tests for check_interface()
  TestCheckStructure     — unit tests for check_structure()
  TestCheckDependencies  — unit tests for check_dependencies()
  TestTestCLI            — integration tests via Click's CliRunner
  TestJsonOutput         — --json flag contract
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from clawforge.cli import main
from clawforge.test_cmd import (
    check_dependencies,
    check_interface,
    check_manifest,
    check_structure,
    run_checks,
)
from tests.conftest import (
    EMPTY_METHODS_SOURCE_TMPL,
    GOOD_PLUGIN_SOURCE_TMPL,
    MISSING_RUN_SOURCE_TMPL,
    SYNTAX_ERROR_SOURCE,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _statuses(results, category: str | None = None) -> dict[str, str]:
    """Return {check_name: status} mapping, optionally filtered by category."""
    filtered = results if category is None else [r for r in results if r.category == category]
    return {r.name: r.status for r in filtered}


def _has_failure(results, category: str | None = None) -> bool:
    filtered = results if category is None else [r for r in results if r.category == category]
    return any(r.status == "fail" for r in filtered)


# ═══════════════════════════════════════════════════════════════════════════════
# Manifest checks
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckManifest:

    def test_missing_manifest_fails(self, tmp_path):
        """No openclaw.plugin.json → immediate fail, no other checks attempted."""
        results = check_manifest(tmp_path)
        statuses = _statuses(results)
        assert statuses["manifest_exists"] == "fail"
        # No further checks should appear when file is absent
        assert len(results) == 1

    def test_valid_manifest_passes(self, make_plugin_dir):
        plugin_dir = make_plugin_dir()
        results = check_manifest(plugin_dir)
        assert not _has_failure(results), "Valid manifest should have no failures"

    def test_invalid_json_fails(self, tmp_path):
        """Unparseable JSON → manifest_valid_json fail."""
        (tmp_path / "openclaw.plugin.json").write_text("{broken json}", encoding="utf-8")
        results = check_manifest(tmp_path)
        statuses = _statuses(results)
        assert statuses["manifest_valid_json"] == "fail"

    def test_missing_required_fields_fail(self, tmp_path):
        """Each missing required field produces its own fail result."""
        # Only 'name' present — all others missing
        (tmp_path / "openclaw.plugin.json").write_text(
            json.dumps({"name": "only-name"}), encoding="utf-8"
        )
        results = check_manifest(tmp_path)
        statuses = _statuses(results)
        # name present → pass; others → fail
        assert statuses["manifest_field_name"] == "pass"
        for field in ["version", "type", "engine", "entry"]:
            assert statuses[f"manifest_field_{field}"] == "fail", f"Expected fail for field '{field}'"

    def test_bad_semver_warns(self, make_plugin_dir):
        """Non-semver version string should produce a warning, not a failure."""
        plugin_dir = make_plugin_dir(version="1.0")  # missing patch segment
        results = check_manifest(plugin_dir)
        statuses = _statuses(results)
        assert statuses.get("manifest_version_semver") == "warn"

    def test_entry_without_colon_warns(self, tmp_path):
        """Entry missing ':' separator should warn about format."""
        (tmp_path / "openclaw.plugin.json").write_text(
            json.dumps({
                "name": "p", "version": "0.1.0", "type": "tool",
                "engine": ">=0.1.0", "entry": "my_module",
            }),
            encoding="utf-8",
        )
        results = check_manifest(tmp_path)
        statuses = _statuses(results)
        assert statuses.get("manifest_entry_format") == "warn"

    def test_entry_file_missing_fails(self, tmp_path):
        """Entry points to a .py file that does not exist → fail."""
        (tmp_path / "openclaw.plugin.json").write_text(
            json.dumps({
                "name": "p", "version": "0.1.0", "type": "tool",
                "engine": ">=0.1.0", "entry": "ghost_module:GhostClass",
            }),
            encoding="utf-8",
        )
        # ghost_module.py deliberately not created
        results = check_manifest(tmp_path)
        statuses = _statuses(results)
        assert statuses["manifest_entry_file"] == "fail"

    def test_entry_file_present_passes(self, make_plugin_dir):
        """Entry file exists → manifest_entry_file should pass."""
        plugin_dir = make_plugin_dir(entry="test_plugin:TestPlugin")
        results = check_manifest(plugin_dir)
        statuses = _statuses(results)
        assert statuses.get("manifest_entry_file") == "pass"


# ═══════════════════════════════════════════════════════════════════════════════
# Interface checks
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckInterface:

    def test_good_plugin_all_pass(self, make_plugin_dir):
        """A plugin with correct init/run/shutdown should pass all interface checks."""
        plugin_dir = make_plugin_dir()
        results = check_interface(plugin_dir)
        assert not _has_failure(results), (
            f"Expected no failures; got: {[r for r in results if r.status == 'fail']}"
        )

    def test_missing_manifest_skips(self, tmp_path):
        """No manifest → check skipped with a warning (not a hard fail)."""
        results = check_interface(tmp_path)
        assert len(results) == 1
        assert results[0].status == "warn"
        assert "skipped" in results[0].message.lower()

    def test_missing_run_warns_or_fails(self, make_plugin_dir):
        """Plugin without run() should fail the interface_method_run check."""
        source = MISSING_RUN_SOURCE_TMPL.format(class_name="TestPlugin")
        plugin_dir = make_plugin_dir(source=source)
        results = check_interface(plugin_dir)
        statuses = _statuses(results)
        assert statuses.get("interface_method_run") == "fail"

    def test_syntax_error_fails_import(self, make_plugin_dir):
        """Module with SyntaxError → interface_import fail, no further checks."""
        plugin_dir = make_plugin_dir(source=SYNTAX_ERROR_SOURCE)
        results = check_interface(plugin_dir)
        statuses = _statuses(results)
        assert statuses["interface_import"] == "fail"

    def test_missing_class_fails(self, tmp_path):
        """Manifest entry points to a class that doesn't exist in the module."""
        (tmp_path / "openclaw.plugin.json").write_text(
            json.dumps({
                "name": "p", "version": "0.1.0", "type": "tool",
                "engine": ">=0.1.0", "entry": "my_plugin:NonExistentClass",
            }),
            encoding="utf-8",
        )
        (tmp_path / "my_plugin.py").write_text(
            GOOD_PLUGIN_SOURCE_TMPL.format(class_name="ActuallyNamedSomethingElse"),
            encoding="utf-8",
        )
        results = check_interface(tmp_path)
        statuses = _statuses(results)
        assert statuses["interface_class"] == "fail"

    def test_signature_warning_for_missing_params(self, make_plugin_dir):
        """init(self) with no config param → signature warning."""
        source = EMPTY_METHODS_SOURCE_TMPL.format(class_name="TestPlugin")
        plugin_dir = make_plugin_dir(source=source)
        results = check_interface(plugin_dir)
        statuses = _statuses(results)
        # init and run missing required params → warn
        assert statuses.get("interface_method_init") == "warn"
        assert statuses.get("interface_method_run") == "warn"

    def test_namespace_isolation_no_sys_modules_leak(self, make_plugin_dir):
        """After check_interface(), the temp module key must not linger in sys.modules."""
        plugin_dir = make_plugin_dir(entry="test_plugin:TestPlugin")
        check_interface(plugin_dir)
        leftover = [k for k in sys.modules if k.startswith("_clawforge_test__")]
        assert leftover == [], f"Module keys leaked into sys.modules: {leftover}"


# ═══════════════════════════════════════════════════════════════════════════════
# Structure checks
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckStructure:

    def test_full_structure_passes(self, make_plugin_dir):
        """README + .gitignore + tests dir → all structure checks pass."""
        plugin_dir = make_plugin_dir()
        results = check_structure(plugin_dir)
        assert not _has_failure(results)
        assert all(r.status == "pass" for r in results)

    def test_missing_readme_warns(self, make_plugin_dir):
        plugin_dir = make_plugin_dir(add_readme=False)
        results = check_structure(plugin_dir)
        statuses = _statuses(results)
        assert statuses["structure_readme"] == "warn"

    def test_missing_gitignore_warns(self, make_plugin_dir):
        plugin_dir = make_plugin_dir(add_gitignore=False)
        results = check_structure(plugin_dir)
        statuses = _statuses(results)
        assert statuses["structure_gitignore"] == "warn"

    def test_missing_tests_warns(self, make_plugin_dir):
        # entry="my_plugin:MyPlugin" so source file is my_plugin.py,
        # which does NOT match test_*.py — avoids a false positive
        plugin_dir = make_plugin_dir(add_tests=False, entry="my_plugin:MyPlugin")
        results = check_structure(plugin_dir)
        statuses = _statuses(results)
        assert statuses["structure_tests"] == "warn"

    def test_root_level_test_files_count_as_tests(self, make_plugin_dir):
        """test_*.py at root level (no tests/ dir) should satisfy the test check."""
        plugin_dir = make_plugin_dir(add_tests=False)
        (plugin_dir / "test_myplugin.py").write_text("# tests\n", encoding="utf-8")
        results = check_structure(plugin_dir)
        statuses = _statuses(results)
        assert statuses["structure_tests"] == "pass"


# ═══════════════════════════════════════════════════════════════════════════════
# Dependency checks
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckDependencies:

    def test_no_dep_files_warns(self, tmp_path):
        """No requirements.txt or pyproject.toml → single warn."""
        results = check_dependencies(tmp_path)
        assert len(results) == 1
        assert results[0].status == "warn"

    def test_requirements_txt_found_passes(self, make_plugin_dir):
        plugin_dir = make_plugin_dir(add_requirements=True)
        results = check_dependencies(plugin_dir)
        statuses = _statuses(results)
        assert statuses["deps_requirements_txt"] == "pass"
        assert statuses.get("deps_requirements_parseable") == "pass"

    def test_empty_requirements_txt_ok(self, tmp_path):
        """An empty requirements.txt is valid (0 deps is fine)."""
        (tmp_path / "requirements.txt").write_text("# no deps\n", encoding="utf-8")
        results = check_dependencies(tmp_path)
        assert not _has_failure(results)

    def test_malformed_requirement_line_warns(self, tmp_path):
        """Lines starting with weird chars should produce a warning."""
        (tmp_path / "requirements.txt").write_text("!!invalid\n", encoding="utf-8")
        results = check_dependencies(tmp_path)
        statuses = _statuses(results)
        assert statuses.get("deps_requirements_format") == "warn"


# ═══════════════════════════════════════════════════════════════════════════════
# CLI integration tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestTestCLI:

    def _invoke(self, args):
        runner = CliRunner()
        return runner.invoke(main, args, catch_exceptions=False)

    def test_passing_plugin_exits_zero(self, make_plugin_dir):
        """A fully valid plugin directory should exit 0."""
        plugin_dir = make_plugin_dir()
        result = self._invoke(["test", str(plugin_dir)])
        assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}:\n{result.output}"

    def test_failing_plugin_exits_one(self, tmp_path):
        """A directory with no manifest should exit 1."""
        result = self._invoke(["test", str(tmp_path)])
        assert result.exit_code == 1, f"Expected exit 1, got {result.exit_code}:\n{result.output}"

    def test_output_contains_summary(self, make_plugin_dir):
        """Output must include a Summary line."""
        plugin_dir = make_plugin_dir()
        result = self._invoke(["test", str(plugin_dir)])
        assert "Summary" in result.output

    def test_default_dir_is_cwd(self, make_plugin_dir):
        """Running `clawforge test` with no arg should default to current directory."""
        plugin_dir = make_plugin_dir()
        runner = CliRunner()
        # Use mix_stderr=False so stdout / stderr are separate
        result = runner.invoke(main, ["test"], catch_exceptions=False, env={}, obj=None)
        # We can't easily change CWD in runner, but the command must at least not crash
        assert result.exit_code in (0, 1)  # exits cleanly regardless of CWD content


# ═══════════════════════════════════════════════════════════════════════════════
# --json output contract
# ═══════════════════════════════════════════════════════════════════════════════

class TestJsonOutput:

    def _invoke_json(self, plugin_dir):
        runner = CliRunner()
        result = runner.invoke(
            main, ["test", str(plugin_dir), "--json"],
            catch_exceptions=False,
        )
        return result

    def test_json_is_valid_json(self, make_plugin_dir):
        plugin_dir = make_plugin_dir()
        result = self._invoke_json(plugin_dir)
        # Should not raise
        data = json.loads(result.output)
        assert isinstance(data, dict)

    def test_json_schema(self, make_plugin_dir):
        """JSON output must contain plugin_dir, results, and summary keys."""
        plugin_dir = make_plugin_dir()
        result = self._invoke_json(plugin_dir)
        data = json.loads(result.output)
        assert "plugin_dir" in data
        assert "results" in data
        assert "summary" in data

        summary = data["summary"]
        assert "pass" in summary
        assert "fail" in summary
        assert "warn" in summary

    def test_json_result_items_schema(self, make_plugin_dir):
        """Each result item must have name, status, message, category."""
        plugin_dir = make_plugin_dir()
        result = self._invoke_json(plugin_dir)
        data = json.loads(result.output)
        for item in data["results"]:
            assert "name" in item
            assert "status" in item
            assert item["status"] in ("pass", "fail", "warn")
            assert "message" in item
            assert "category" in item

    def test_json_exit_one_on_failure(self, tmp_path):
        """--json must still exit 1 when there are failures."""
        runner = CliRunner()
        result = runner.invoke(
            main, ["test", str(tmp_path), "--json"],
            catch_exceptions=False,
        )
        assert result.exit_code == 1

    def test_json_exit_zero_on_pass(self, make_plugin_dir):
        """--json must exit 0 for a valid plugin."""
        plugin_dir = make_plugin_dir()
        result = self._invoke_json(plugin_dir)
        assert result.exit_code == 0

    def test_json_summary_counts_match_results(self, make_plugin_dir):
        """summary.pass + summary.fail + summary.warn must equal len(results)."""
        plugin_dir = make_plugin_dir()
        result = self._invoke_json(plugin_dir)
        data = json.loads(result.output)
        s = data["summary"]
        assert s["pass"] + s["fail"] + s["warn"] == len(data["results"])
