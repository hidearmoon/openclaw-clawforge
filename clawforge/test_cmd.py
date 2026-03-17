"""
clawforge test command - run compatibility checks on a plugin directory.

Checks performed:
  1. Manifest validation  - openclaw.plugin.json completeness & correctness
  2. Interface compliance - dynamic import; init/run/shutdown presence + signatures
  3. Directory structure  - README, .gitignore, test files
  4. Dependency listing   - requirements.txt / pyproject.toml parseable
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import click
from rich import box
from rich.console import Console
from rich.table import Table

console = Console()

# semver pattern (e.g. 1.2.3)
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

# Required manifest fields (same as ClawForge init_cmd expectations)
_REQUIRED_MANIFEST_FIELDS = ["name", "version", "type", "engine", "entry"]


@dataclass
class CheckResult:
    name: str
    status: str          # "pass" | "fail" | "warn"
    message: str
    category: str        # "manifest" | "interface" | "structure" | "dependencies"


# ── Individual check suites ───────────────────────────────────────────────────

def check_manifest(plugin_dir: Path) -> List[CheckResult]:
    """Validate openclaw.plugin.json structure and content."""
    results: List[CheckResult] = []
    manifest_path = plugin_dir / "openclaw.plugin.json"

    # File existence
    if not manifest_path.exists():
        results.append(CheckResult(
            "manifest_exists", "fail",
            "openclaw.plugin.json not found — required for OpenClaw plugin discovery",
            "manifest",
        ))
        return results
    results.append(CheckResult("manifest_exists", "pass", "openclaw.plugin.json found", "manifest"))

    # Valid JSON
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        results.append(CheckResult("manifest_valid_json", "fail", f"Invalid JSON: {exc}", "manifest"))
        return results
    results.append(CheckResult("manifest_valid_json", "pass", "Valid JSON", "manifest"))

    if not isinstance(manifest, dict):
        results.append(CheckResult("manifest_is_object", "fail", "Manifest must be a JSON object", "manifest"))
        return results

    # Required fields
    for field_name in _REQUIRED_MANIFEST_FIELDS:
        if field_name not in manifest:
            results.append(CheckResult(
                f"manifest_field_{field_name}", "fail",
                f"Required field '{field_name}' is missing",
                "manifest",
            ))
        else:
            results.append(CheckResult(
                f"manifest_field_{field_name}", "pass",
                f"Field '{field_name}' present",
                "manifest",
            ))

    # Version semver format
    version = manifest.get("version", "")
    if version and not _SEMVER_RE.match(str(version)):
        results.append(CheckResult(
            "manifest_version_semver", "warn",
            f"Version '{version}' should follow semver (x.y.z), e.g. 0.1.0",
            "manifest",
        ))
    elif version:
        results.append(CheckResult("manifest_version_semver", "pass", f"Version '{version}' is valid semver", "manifest"))

    # Entry format & file existence
    entry = manifest.get("entry", "")
    if entry:
        if ":" not in entry:
            results.append(CheckResult(
                "manifest_entry_format", "warn",
                f"Entry '{entry}' should be 'module:ClassName' (e.g. my_plugin:MyPlugin)",
                "manifest",
            ))
        else:
            module_part, class_part = entry.split(":", 1)
            if not module_part or not class_part:
                results.append(CheckResult(
                    "manifest_entry_format", "fail",
                    f"Entry '{entry}' has empty module or class name",
                    "manifest",
                ))
            else:
                results.append(CheckResult("manifest_entry_format", "pass", f"Entry format 'module:ClassName' valid", "manifest"))
                # Check entry file exists
                entry_file = plugin_dir / f"{module_part}.py"
                if not entry_file.exists():
                    results.append(CheckResult(
                        "manifest_entry_file", "fail",
                        f"Entry file '{module_part}.py' not found in plugin directory",
                        "manifest",
                    ))
                else:
                    results.append(CheckResult(
                        "manifest_entry_file", "pass",
                        f"Entry file '{module_part}.py' exists",
                        "manifest",
                    ))

    return results


def check_interface(plugin_dir: Path) -> List[CheckResult]:
    """Dynamically import plugin and verify init/run/shutdown interface."""
    results: List[CheckResult] = []
    manifest_path = plugin_dir / "openclaw.plugin.json"

    # Without a manifest we cannot determine entry point
    if not manifest_path.exists():
        results.append(CheckResult(
            "interface_skipped", "warn",
            "Interface check skipped — openclaw.plugin.json not found",
            "interface",
        ))
        return results

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        results.append(CheckResult(
            "interface_skipped", "warn",
            "Interface check skipped — manifest not parseable",
            "interface",
        ))
        return results

    entry = manifest.get("entry", "")
    if ":" not in entry:
        results.append(CheckResult(
            "interface_skipped", "warn",
            "Interface check skipped — entry not in 'module:ClassName' format",
            "interface",
        ))
        return results

    module_name, class_name = entry.split(":", 1)
    entry_file = plugin_dir / f"{module_name}.py"
    if not entry_file.exists():
        results.append(CheckResult(
            "interface_import", "fail",
            f"Cannot import: '{module_name}.py' not found",
            "interface",
        ))
        return results

    # Namespace-isolated import (mirrors SandboxRegistry strategy)
    unique_key = f"_clawforge_test__{module_name}"
    spec = importlib.util.spec_from_file_location(unique_key, entry_file)
    if spec is None or spec.loader is None:
        results.append(CheckResult(
            "interface_import", "fail",
            f"importlib cannot create spec for '{entry_file.name}'",
            "interface",
        ))
        return results

    try:
        module = importlib.util.module_from_spec(spec)
        sys.modules[unique_key] = module
        spec.loader.exec_module(module)
        results.append(CheckResult(
            "interface_import", "pass",
            f"Module '{module_name}' imported successfully",
            "interface",
        ))
    except SyntaxError as exc:
        results.append(CheckResult("interface_import", "fail", f"Syntax error: {exc}", "interface"))
        sys.modules.pop(unique_key, None)
        return results
    except Exception as exc:
        results.append(CheckResult("interface_import", "fail", f"Import error: {exc}", "interface"))
        sys.modules.pop(unique_key, None)
        return results

    # Class existence
    if not hasattr(module, class_name):
        results.append(CheckResult(
            "interface_class", "fail",
            f"Class '{class_name}' not found in '{module_name}.py'",
            "interface",
        ))
        sys.modules.pop(unique_key, None)
        return results
    results.append(CheckResult(
        "interface_class", "pass",
        f"Class '{class_name}' found",
        "interface",
    ))
    cls = getattr(module, class_name)

    # Method checks
    # Expected signatures (minus self): init(config), run(payload), shutdown()
    method_specs = {
        "init":     {"required": True,  "min_params": 1, "hint": "init(self, config)"},
        "run":      {"required": True,  "min_params": 1, "hint": "run(self, payload)"},
        "shutdown": {"required": True,  "min_params": 0, "hint": "shutdown(self)"},
    }

    for mname, spec_info in method_specs.items():
        if not hasattr(cls, mname):
            status = "fail" if spec_info["required"] else "warn"
            results.append(CheckResult(
                f"interface_method_{mname}", status,
                f"Method '{mname}' not implemented",
                "interface",
            ))
            continue

        method = getattr(cls, mname)
        if not callable(method):
            results.append(CheckResult(
                f"interface_method_{mname}", "fail",
                f"'{mname}' exists but is not callable",
                "interface",
            ))
            continue

        # Signature check
        try:
            sig = inspect.signature(method)
            params = [p for p in sig.parameters if p != "self"]
            if len(params) < spec_info["min_params"]:
                results.append(CheckResult(
                    f"interface_method_{mname}", "warn",
                    f"'{mname}' may be missing parameters — expected: {spec_info['hint']}",
                    "interface",
                ))
            else:
                results.append(CheckResult(
                    f"interface_method_{mname}", "pass",
                    f"Method '{mname}' signature looks correct",
                    "interface",
                ))
        except (ValueError, TypeError):
            # Can't inspect (e.g. built-ins) — treat as pass
            results.append(CheckResult(
                f"interface_method_{mname}", "pass",
                f"Method '{mname}' present",
                "interface",
            ))

    sys.modules.pop(unique_key, None)
    return results


def check_structure(plugin_dir: Path) -> List[CheckResult]:
    """Verify recommended directory structure conventions."""
    results: List[CheckResult] = []

    # README
    readme_names = ["README.md", "README.rst", "README.txt", "readme.md"]
    has_readme = any((plugin_dir / r).exists() for r in readme_names)
    if not has_readme:
        results.append(CheckResult(
            "structure_readme", "warn",
            "No README found — README.md is strongly recommended for discoverability",
            "structure",
        ))
    else:
        results.append(CheckResult("structure_readme", "pass", "README file found", "structure"))

    # .gitignore
    if not (plugin_dir / ".gitignore").exists():
        results.append(CheckResult(
            "structure_gitignore", "warn",
            ".gitignore not found — recommended to avoid committing __pycache__, .venv etc.",
            "structure",
        ))
    else:
        results.append(CheckResult("structure_gitignore", "pass", ".gitignore found", "structure"))

    # Test files (tests/ directory or test_*.py at root)
    has_tests_dir = (plugin_dir / "tests").is_dir() and any((plugin_dir / "tests").iterdir())
    has_root_tests = bool(list(plugin_dir.glob("test_*.py")) + list(plugin_dir.glob("*_test.py")))
    if not has_tests_dir and not has_root_tests:
        results.append(CheckResult(
            "structure_tests", "warn",
            "No test files found — add tests/ directory or test_*.py files",
            "structure",
        ))
    else:
        results.append(CheckResult("structure_tests", "pass", "Test files found", "structure"))

    return results


def check_dependencies(plugin_dir: Path) -> List[CheckResult]:
    """Check requirements.txt / pyproject.toml presence and parseability."""
    results: List[CheckResult] = []

    req_txt = plugin_dir / "requirements.txt"
    pyproject = plugin_dir / "pyproject.toml"

    if not req_txt.exists() and not pyproject.exists():
        results.append(CheckResult(
            "deps_file", "warn",
            "No requirements.txt or pyproject.toml found — dependency listing is recommended",
            "dependencies",
        ))
        return results

    if req_txt.exists():
        results.append(CheckResult("deps_requirements_txt", "pass", "requirements.txt found", "dependencies"))
        try:
            lines = [
                ln.strip() for ln in req_txt.read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.strip().startswith("#")
            ]
            # Warn on obviously malformed lines (no leading package name char)
            bad = [ln for ln in lines if not re.match(r"^[a-zA-Z0-9_\-\.]", ln)]
            if bad:
                results.append(CheckResult(
                    "deps_requirements_format", "warn",
                    f"Unusual requirement line(s): {bad[:3]}",
                    "dependencies",
                ))
            else:
                results.append(CheckResult(
                    "deps_requirements_parseable", "pass",
                    f"{len(lines)} requirement(s) listed",
                    "dependencies",
                ))
        except OSError as exc:
            results.append(CheckResult(
                "deps_requirements_read", "fail",
                f"Cannot read requirements.txt: {exc}",
                "dependencies",
            ))

    if pyproject.exists():
        results.append(CheckResult("deps_pyproject_found", "pass", "pyproject.toml found", "dependencies"))
        # Try to parse TOML (tomllib stdlib on 3.11+, else try tomli, else warn)
        toml_data: Optional[dict] = None
        try:
            import tomllib  # type: ignore  # Python 3.11+
            with open(pyproject, "rb") as fh:
                toml_data = tomllib.load(fh)
        except ImportError:
            try:
                import tomli  # type: ignore  # pip install tomli
                with open(pyproject, "rb") as fh:
                    toml_data = tomli.load(fh)
            except ImportError:
                results.append(CheckResult(
                    "deps_pyproject_parseable", "warn",
                    "tomllib/tomli not available — cannot validate pyproject.toml content",
                    "dependencies",
                ))
        except Exception as exc:
            results.append(CheckResult(
                "deps_pyproject_parseable", "fail",
                f"Invalid TOML in pyproject.toml: {exc}",
                "dependencies",
            ))

        if toml_data is not None:
            results.append(CheckResult(
                "deps_pyproject_parseable", "pass",
                "pyproject.toml is valid TOML",
                "dependencies",
            ))

    return results


# ── Aggregator ────────────────────────────────────────────────────────────────

def run_checks(plugin_dir: Path) -> List[CheckResult]:
    """Run all four check suites and return combined results."""
    results: List[CheckResult] = []
    results.extend(check_manifest(plugin_dir))
    results.extend(check_interface(plugin_dir))
    results.extend(check_structure(plugin_dir))
    results.extend(check_dependencies(plugin_dir))
    return results


# ── Reporting ─────────────────────────────────────────────────────────────────

_CATEGORY_LABELS = {
    "manifest":     "Manifest Validation",
    "interface":    "Interface Compliance",
    "structure":    "Directory Structure",
    "dependencies": "Dependency Check",
}

_CATEGORY_ORDER = ["manifest", "interface", "structure", "dependencies"]


def _print_report(results: List[CheckResult], plugin_dir: Path) -> tuple:
    """Render rich tables; return (pass_count, fail_count, warn_count)."""
    console.print(
        f"\n[bold cyan]ClawForge[/bold cyan] Compatibility Test"
        f" — [dim]{plugin_dir}[/dim]\n"
    )

    by_cat: dict = {}
    for r in results:
        by_cat.setdefault(r.category, []).append(r)

    pass_n = fail_n = warn_n = 0

    for cat in _CATEGORY_ORDER:
        if cat not in by_cat:
            continue
        table = Table(
            title=_CATEGORY_LABELS.get(cat, cat),
            box=box.ROUNDED,
            show_header=True,
            header_style="bold dim",
            title_style="bold",
            expand=False,
        )
        table.add_column("Status", width=9, justify="center", no_wrap=True)
        table.add_column("Check", min_width=32)
        table.add_column("Details")

        for r in by_cat[cat]:
            if r.status == "pass":
                badge = "[green]✓ PASS[/green]"
                pass_n += 1
            elif r.status == "fail":
                badge = "[red]✗ FAIL[/red]"
                fail_n += 1
            else:
                badge = "[yellow]⚠ WARN[/yellow]"
                warn_n += 1
            table.add_row(badge, r.name, r.message)

        console.print(table)
        console.print()

    return pass_n, fail_n, warn_n


# ── CLI command ───────────────────────────────────────────────────────────────

@click.command("test")
@click.argument(
    "plugin_dir",
    default=".",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
)
@click.option(
    "--json", "output_json",
    is_flag=True,
    default=False,
    help="Emit results as JSON (useful for CI and scripting).",
)
def test(plugin_dir: Path, output_json: bool):
    """Run compatibility checks on a plugin directory.

    \b
    Checks performed:
      1. Manifest    — openclaw.plugin.json completeness & correctness
      2. Interface   — init / run / shutdown methods & signatures
      3. Structure   — README, .gitignore, test files
      4. Deps        — requirements.txt / pyproject.toml parseable

    \b
    Exit codes:
      0  All checks passed (warnings are non-blocking)
      1  One or more checks failed

    \b
    Examples:
      clawforge test .
      clawforge test ./my-plugin
      clawforge test ./my-plugin --json | jq .summary
    """
    plugin_dir = plugin_dir.resolve()
    results = run_checks(plugin_dir)

    if output_json:
        import json as _json
        payload = {
            "plugin_dir": str(plugin_dir),
            "results": [
                {
                    "name": r.name,
                    "status": r.status,
                    "message": r.message,
                    "category": r.category,
                }
                for r in results
            ],
            "summary": {
                "pass": sum(1 for r in results if r.status == "pass"),
                "fail": sum(1 for r in results if r.status == "fail"),
                "warn": sum(1 for r in results if r.status == "warn"),
            },
        }
        click.echo(_json.dumps(payload, indent=2))
        sys.exit(1 if payload["summary"]["fail"] > 0 else 0)

    pass_n, fail_n, warn_n = _print_report(results, plugin_dir)
    total = pass_n + fail_n + warn_n

    console.print(
        f"[bold]Summary:[/bold]  "
        f"[green]{pass_n} passed[/green]  "
        f"[red]{fail_n} failed[/red]  "
        f"[yellow]{warn_n} warnings[/yellow]  "
        f"[dim]({total} checks)[/dim]"
    )

    if fail_n > 0:
        console.print("\n[red bold]✗ Plugin is NOT compatible — fix failures before publishing.[/red bold]")
        sys.exit(1)
    elif warn_n > 0:
        console.print("\n[yellow bold]⚠ Plugin passed with warnings — consider addressing them.[/yellow bold]")
    else:
        console.print("\n[green bold]✓ All checks passed — plugin is ready.[/green bold]")
