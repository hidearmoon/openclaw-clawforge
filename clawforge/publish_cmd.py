"""
clawforge publish — Package and publish an OpenClaw plugin.

Workflow:
  1. Load & validate openclaw.plugin.json
  2. Run pre-flight compatibility checks  (clawforge test logic)
  3. Generate / prepend a CHANGELOG.md entry from git log
  4. Build wheel + sdist  (python -m build)
  5. Upload to PyPI        (twine, needs PYPI_TOKEN)
  6. Create GitHub Release (httpx, needs GITHUB_TOKEN + GITHUB_REPOSITORY)
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import List, Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .test_cmd import run_checks, CheckResult

_console = Console()


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class PublishResult:
    plugin_name: str
    version: str
    plugin_dir: Path
    checks_passed: bool = False
    wheel_built: bool = False
    sdist_built: bool = False
    changelog_written: bool = False
    pypi_published: bool = False
    github_release_created: bool = False
    dry_run: bool = False
    errors: List[str] = field(default_factory=list)
    artifacts: List[Path] = field(default_factory=list)
    github_release_url: str = ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_manifest(plugin_dir: Path) -> dict:
    """Load openclaw.plugin.json and return its contents as a dict."""
    manifest_path = plugin_dir / "openclaw.plugin.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"openclaw.plugin.json not found in {plugin_dir}"
        )
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _run_preflight_checks(plugin_dir: Path):
    """Run all test-suite checks; return (all_passed: bool, results: list)."""
    results = run_checks(plugin_dir)
    all_passed = not any(r.status == "fail" for r in results)
    return all_passed, results


def _git_log_since_last_tag(plugin_dir: Path) -> str:
    """Return formatted commit lines since the most recent git tag, or ''."""
    try:
        tag_proc = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            cwd=plugin_dir,
            capture_output=True,
            text=True,
        )
        log_range = (
            f"{tag_proc.stdout.strip()}..HEAD"
            if tag_proc.returncode == 0
            else "HEAD"
        )
        log_proc = subprocess.run(
            ["git", "log", log_range, "--pretty=format:- %s", "--no-merges"],
            cwd=plugin_dir,
            capture_output=True,
            text=True,
        )
        return log_proc.stdout.strip() if log_proc.returncode == 0 else ""
    except (FileNotFoundError, subprocess.SubprocessError):
        return ""


def _generate_changelog_entry(plugin_dir: Path, version: str) -> str:
    """Build a CHANGELOG.md section string for *version*."""
    commits = _git_log_since_last_tag(plugin_dir) or "- Initial release"
    return f"## [{version}] - {date.today().isoformat()}\n\n{commits}\n"


def _write_changelog(plugin_dir: Path, entry: str, version: str) -> Path:
    """Prepend *entry* to CHANGELOG.md; no-op if version already present."""
    changelog_path = plugin_dir / "CHANGELOG.md"
    if changelog_path.exists():
        existing = changelog_path.read_text(encoding="utf-8")
        if f"## [{version}]" in existing:
            return changelog_path  # already written; skip
        # Strip existing header to avoid duplication
        header = "# Changelog"
        body = existing[len(header):].lstrip("\n") if existing.startswith(header) else existing
        changelog_path.write_text(
            f"# Changelog\n\n{entry}\n{body}", encoding="utf-8"
        )
    else:
        changelog_path.write_text(
            f"# Changelog\n\n{entry}", encoding="utf-8"
        )
    return changelog_path


def _check_build_tool() -> None:
    """Raise RuntimeError when the 'build' package is not importable."""
    proc = subprocess.run(
        [sys.executable, "-c", "import build"],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "The 'build' package is required. Install it with:\n"
            "  pip install build\n"
            "  # or: pip install 'clawforge[publish]'"
        )


def _check_twine() -> None:
    """Raise RuntimeError when twine is not importable."""
    proc = subprocess.run(
        [sys.executable, "-c", "import twine"],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "The 'twine' package is required for PyPI upload. Install it with:\n"
            "  pip install twine\n"
            "  # or: pip install 'clawforge[publish]'"
        )


def _build_package(plugin_dir: Path) -> List[Path]:
    """Build wheel + sdist with 'python -m build'; return artifact Paths."""
    dist_dir = plugin_dir / "dist"
    if dist_dir.exists():
        shutil.rmtree(dist_dir)

    proc = subprocess.run(
        [sys.executable, "-m", "build", "--outdir", str(dist_dir)],
        cwd=plugin_dir,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Build failed:\n{proc.stderr.strip()}")

    return sorted(dist_dir.glob("*.whl")) + sorted(dist_dir.glob("*.tar.gz"))


def _publish_to_pypi(
    artifacts: List[Path],
    token: str,
    repository_url: Optional[str] = None,
) -> None:
    """Upload *artifacts* to PyPI (or a custom index) using twine."""
    cmd = [
        sys.executable, "-m", "twine", "upload",
        "--username", "__token__",
        "--password", token,
        "--non-interactive",
    ]
    if repository_url:
        cmd += ["--repository-url", repository_url]
    cmd += [str(a) for a in artifacts]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"PyPI upload failed:\n{proc.stderr.strip()}")


def _create_github_release(
    plugin_name: str,
    version: str,
    body: str,
    token: str,
    repo: str,
    artifacts: List[Path],
) -> str:
    """Create a GitHub Release and upload artifacts; return the HTML URL."""
    import httpx  # project dependency — always present

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    api_base = f"https://api.github.com/repos/{repo}"
    tag = f"v{version}"

    resp = httpx.post(
        f"{api_base}/releases",
        json={
            "tag_name": tag,
            "name": f"{plugin_name} {tag}",
            "body": body,
            "draft": False,
            "prerelease": False,
        },
        headers=headers,
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"GitHub API error {resp.status_code}: {resp.text[:300]}"
        )

    release = resp.json()
    upload_url = release["upload_url"].split("{")[0]
    release_url = release["html_url"]

    upload_headers = {**headers, "Content-Type": "application/octet-stream"}
    for artifact in artifacts:
        up = httpx.post(
            f"{upload_url}?name={artifact.name}",
            content=artifact.read_bytes(),
            headers=upload_headers,
            timeout=120,
        )
        if up.status_code not in (200, 201):
            _console.print(
                f"[yellow]Warning: could not upload {artifact.name} "
                f"(HTTP {up.status_code})[/yellow]"
            )

    return release_url


# ---------------------------------------------------------------------------
# Core orchestration  (separated for testability)
# ---------------------------------------------------------------------------

def _do_publish(
    plugin_path: Path,
    token: Optional[str],
    github_token: Optional[str],
    repo: Optional[str],
    dry_run: bool,
    skip_test: bool,
    skip_changelog: bool,
    repository_url: Optional[str],
    con: Console,
) -> PublishResult:

    # ── Step 0: load manifest ──────────────────────────────────────────────
    try:
        manifest = _load_manifest(plugin_path)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        con.print(f"[red]✗[/red] {exc}")
        r = PublishResult(plugin_name="unknown", version="unknown", plugin_dir=plugin_path)
        r.errors.append(str(exc))
        return r

    plugin_name = manifest.get("name", "unknown")
    version = manifest.get("version", "0.1.0")

    result = PublishResult(
        plugin_name=plugin_name,
        version=version,
        plugin_dir=plugin_path,
        dry_run=dry_run,
    )

    title = f"[bold]{plugin_name}[/bold] [dim]v{version}[/dim]"
    if dry_run:
        title += "  [yellow](dry run)[/yellow]"
    con.print(Panel(title, title="ClawForge Publish", border_style="blue"))

    # ── Step 1: pre-flight checks ──────────────────────────────────────────
    con.print("\n[bold]Step 1/4[/bold]  Pre-flight checks")
    if not skip_test:
        passed, check_results = _run_preflight_checks(plugin_path)
        result.checks_passed = passed
        if not passed:
            for r in check_results:
                if r.status == "fail":
                    con.print(f"  [red]✗[/red] [{r.category}] {r.message}")
            con.print(
                "[red]Pre-flight failed. Fix the errors above, "
                "or use --no-test to bypass.[/red]"
            )
            result.errors.append("Pre-flight checks failed")
            return result
        con.print("  [green]✓[/green] All checks passed")
    else:
        result.checks_passed = True
        con.print("  [dim]skipped (--no-test)[/dim]")

    # ── Step 2: CHANGELOG ──────────────────────────────────────────────────
    con.print("\n[bold]Step 2/4[/bold]  CHANGELOG")
    changelog_entry: Optional[str] = None
    if not skip_changelog:
        try:
            changelog_entry = _generate_changelog_entry(plugin_path, version)
            _write_changelog(plugin_path, changelog_entry, version)
            result.changelog_written = True
            con.print("  [green]✓[/green] CHANGELOG.md updated")
        except Exception as exc:
            con.print(f"  [yellow]⚠[/yellow] Could not write changelog: {exc}")
    else:
        con.print("  [dim]skipped (--no-changelog)[/dim]")

    # ── Step 3: build ──────────────────────────────────────────────────────
    con.print("\n[bold]Step 3/4[/bold]  Building package")
    try:
        _check_build_tool()
        artifacts = _build_package(plugin_path)
        result.artifacts = artifacts
        result.wheel_built = any(a.suffix == ".whl" for a in artifacts)
        result.sdist_built = any(str(a).endswith(".tar.gz") for a in artifacts)
        for a in artifacts:
            con.print(f"  [green]✓[/green] {a.name}")
    except RuntimeError as exc:
        con.print(f"  [red]✗[/red] {exc}")
        result.errors.append(str(exc))
        return result

    # ── Step 4: publish ────────────────────────────────────────────────────
    con.print("\n[bold]Step 4/4[/bold]  Publishing")

    if dry_run:
        con.print("  [yellow]⚠[/yellow]  Dry run — skipping all uploads")
        _print_summary(result, con)
        return result

    if token:
        try:
            _check_twine()
            _publish_to_pypi(result.artifacts, token, repository_url)
            result.pypi_published = True
            con.print("  [green]✓[/green] Published to PyPI")
        except RuntimeError as exc:
            con.print(f"  [red]✗[/red] PyPI: {exc}")
            result.errors.append(str(exc))
    else:
        con.print("  [dim]PyPI skipped — set PYPI_TOKEN or pass --token[/dim]")

    if github_token and repo:
        try:
            url = _create_github_release(
                plugin_name=plugin_name,
                version=version,
                body=changelog_entry or f"Release v{version}",
                token=github_token,
                repo=repo,
                artifacts=result.artifacts,
            )
            result.github_release_created = True
            result.github_release_url = url
            con.print(f"  [green]✓[/green] GitHub Release: {url}")
        except RuntimeError as exc:
            con.print(f"  [red]✗[/red] GitHub Release: {exc}")
            result.errors.append(str(exc))
    else:
        con.print(
            "  [dim]GitHub Release skipped — "
            "set GITHUB_TOKEN + GITHUB_REPOSITORY or pass --github-token + --repo[/dim]"
        )

    _print_summary(result, con)
    return result


def _print_summary(result: PublishResult, con: Console) -> None:
    table = Table(title="Publish Summary", show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold dim")
    table.add_column()

    def _s(ok: bool) -> str:
        return "[green]✓[/green]" if ok else "[red]✗[/red]"

    table.add_row("Pre-flight checks", _s(result.checks_passed))
    table.add_row(
        "CHANGELOG.md",
        _s(result.changelog_written) if result.changelog_written else "[dim]—[/dim]",
    )
    table.add_row("Wheel (.whl)", _s(result.wheel_built))
    table.add_row("Source dist (.tar.gz)", _s(result.sdist_built))

    if result.dry_run:
        table.add_row("Uploads", "[yellow]dry run[/yellow]")
    else:
        table.add_row(
            "PyPI",
            _s(result.pypi_published) if result.pypi_published else "[dim]—[/dim]",
        )
        table.add_row(
            "GitHub Release",
            _s(result.github_release_created) if result.github_release_created else "[dim]—[/dim]",
        )

    con.print("\n")
    con.print(table)
    if result.errors:
        con.print(f"\n[red]✗ Publish finished with {len(result.errors)} error(s).[/red]")
    else:
        mode = "dry-run build" if result.dry_run else "publish"
        con.print(
            f"\n[green]✓ {result.plugin_name} v{result.version} {mode} complete![/green]"
        )


# ---------------------------------------------------------------------------
# Click command
# ---------------------------------------------------------------------------

@click.command("publish")
@click.argument("plugin_dir", default=".", type=click.Path(exists=True))
@click.option(
    "--token", envvar="PYPI_TOKEN",
    help="PyPI API token (env: PYPI_TOKEN).",
)
@click.option(
    "--github-token", "github_token", envvar="GITHUB_TOKEN",
    help="GitHub personal access token for Release creation (env: GITHUB_TOKEN).",
)
@click.option(
    "--repo", envvar="GITHUB_REPOSITORY",
    help="GitHub repository owner/name, e.g. myorg/my-plugin (env: GITHUB_REPOSITORY).",
)
@click.option(
    "--dry-run", is_flag=True,
    help="Build artifacts but skip all uploads.",
)
@click.option(
    "--no-test", "skip_test", is_flag=True,
    help="Skip pre-flight compatibility checks.",
)
@click.option(
    "--no-changelog", "skip_changelog", is_flag=True,
    help="Skip CHANGELOG.md generation.",
)
@click.option(
    "--repository-url", default=None,
    help="Custom PyPI endpoint, e.g. https://test.pypi.org/legacy/",
)
@click.option(
    "--json", "json_output", is_flag=True,
    help="Emit a machine-readable JSON summary to stdout.",
)
def publish(
    plugin_dir,
    token,
    github_token,
    repo,
    dry_run,
    skip_test,
    skip_changelog,
    repository_url,
    json_output,
):
    """Package and publish an OpenClaw plugin to PyPI and GitHub Releases.

    PLUGIN_DIR defaults to the current directory.

    \b
    Publish steps (in order):
      1. Pre-flight checks  (same as `clawforge test`)
      2. CHANGELOG.md       generated from git log
      3. Build              wheel + source dist via `python -m build`
      4. PyPI upload        via twine   (requires PYPI_TOKEN)
         GitHub Release     via API     (requires GITHUB_TOKEN + GITHUB_REPOSITORY)

    \b
    Required extras for uploading:
      pip install 'clawforge[publish]'   # installs build + twine

    \b
    Environment variables:
      PYPI_TOKEN           PyPI API token
      GITHUB_TOKEN         GitHub personal access token
      GITHUB_REPOSITORY    Target repo in owner/name format
    """
    plugin_path = Path(plugin_dir).resolve()
    result = _do_publish(
        plugin_path=plugin_path,
        token=token,
        github_token=github_token,
        repo=repo,
        dry_run=dry_run,
        skip_test=skip_test,
        skip_changelog=skip_changelog,
        repository_url=repository_url,
        con=_console,
    )

    if json_output:
        click.echo(json.dumps({
            "plugin_name": result.plugin_name,
            "version": result.version,
            "dry_run": result.dry_run,
            "checks_passed": result.checks_passed,
            "wheel_built": result.wheel_built,
            "sdist_built": result.sdist_built,
            "changelog_written": result.changelog_written,
            "pypi_published": result.pypi_published,
            "github_release_created": result.github_release_created,
            "github_release_url": result.github_release_url,
            "artifacts": [str(a) for a in result.artifacts],
            "errors": result.errors,
        }, indent=2))

    if result.errors:
        sys.exit(1)
