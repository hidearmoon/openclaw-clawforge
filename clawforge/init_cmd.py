"""
clawforge init command - scaffold a new OpenClaw plugin from template.
"""

import json
import re
import sys
from pathlib import Path

import click
from jinja2 import Environment, PackageLoader, select_autoescape
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich.text import Text
from rich import print as rprint

console = Console()

PLUGIN_TYPES = {
    "channel": "Channel  – message platform adapter (Telegram, Slack, Discord…)",
    "memory":  "Memory   – storage backend (vector DB, KV store, SQL…)",
    "tool":    "Tool     – custom capability / function call",
    "provider": "Provider – LLM provider adapter (OpenAI-compat, custom API…)",
}

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
NAME_RE = re.compile(r"^[a-z][a-z0-9\-]{1,62}$")


def _validate_name(name: str) -> str:
    name = name.strip().lower()
    if not NAME_RE.match(name):
        raise click.BadParameter(
            "Plugin name must be lowercase letters, digits, and hyphens, "
            "start with a letter, length 2-63."
        )
    return name


def _validate_version(version: str) -> str:
    version = version.strip()
    if not VERSION_RE.match(version):
        raise click.BadParameter("Version must follow semver, e.g. 0.1.0")
    return version


def _slugify(name: str) -> str:
    """Convert kebab-case plugin name to PascalCase class name."""
    return "".join(part.capitalize() for part in name.split("-"))


def _render_templates(
    env: Environment,
    plugin_type: str,
    context: dict,
    output_dir: Path,
    force: bool,
) -> None:
    """Render all Jinja2 templates for the given plugin type into output_dir."""
    template_map = {
        "plugin.py.j2": f"{context['module_name']}.py",
        "openclaw.plugin.json.j2": "openclaw.plugin.json",
        "test_plugin.py.j2": f"test_{context['module_name']}.py",
        "README.md.j2": "README.md",
        "gitignore.j2": ".gitignore",
    }

    rendered_files = []
    for tmpl_name, out_name in template_map.items():
        tmpl_path = f"{plugin_type}/{tmpl_name}"
        try:
            template = env.get_template(tmpl_path)
        except Exception:
            # Fallback to common templates
            try:
                template = env.get_template(f"common/{tmpl_name}")
            except Exception:
                console.print(f"  [yellow]⚠[/yellow]  Template not found: {tmpl_path}, skipping.")
                continue

        dest = output_dir / out_name
        if dest.exists() and not force:
            overwrite = Confirm.ask(f"  [yellow]{out_name}[/yellow] already exists. Overwrite?", default=False)
            if not overwrite:
                console.print(f"  [dim]Skipped {out_name}[/dim]")
                continue

        content = template.render(**context)
        dest.write_text(content, encoding="utf-8")
        rendered_files.append(out_name)

    return rendered_files


@click.command("init")
@click.option("--type", "plugin_type", type=click.Choice(list(PLUGIN_TYPES.keys())), help="Plugin type.")
@click.option("--name", "plugin_name", help="Plugin name (kebab-case, e.g. my-tool).")
@click.option("--description", "description", default="", help="Short description.")
@click.option("--author", "author", default="", help="Author name.")
@click.option("--version", "plugin_version", default="0.1.0", help="Initial version.")
@click.option("--output-dir", "-o", default=None, help="Output directory (default: ./<plugin-name>).")
@click.option("--force", "-f", is_flag=True, default=False, help="Overwrite existing files without prompting.")
def init(plugin_type, plugin_name, description, author, plugin_version, output_dir, force):
    """Scaffold a new OpenClaw plugin from template.

    \b
    Examples:
      clawforge init                          # interactive mode
      clawforge init --type tool --name my-tool
      clawforge init --type provider --name openrouter-provider --author Alice
    """
    console.print(Panel.fit(
        "[bold cyan]ClawForge[/bold cyan] [white]— OpenClaw Plugin Scaffold[/white]",
        border_style="cyan",
    ))

    # ── Interactive prompts when options are missing ──────────────────────────
    if not plugin_type:
        console.print("\n[bold]Available plugin types:[/bold]")
        table = Table(show_header=False, box=None, padding=(0, 2))
        for key, desc in PLUGIN_TYPES.items():
            table.add_row(f"[cyan]{key}[/cyan]", desc)
        console.print(table)
        plugin_type = Prompt.ask(
            "\n[bold]Plugin type[/bold]",
            choices=list(PLUGIN_TYPES.keys()),
            default="tool",
        )

    if not plugin_name:
        plugin_name = Prompt.ask("[bold]Plugin name[/bold] [dim](kebab-case)[/dim]")
    try:
        plugin_name = _validate_name(plugin_name)
    except click.BadParameter as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    if not description:
        description = Prompt.ask(
            "[bold]Description[/bold] [dim](short, one line)[/dim]",
            default=f"An OpenClaw {plugin_type} plugin",
        )

    if not author:
        author = Prompt.ask("[bold]Author[/bold]", default="Anonymous")

    try:
        plugin_version = _validate_version(plugin_version)
    except click.BadParameter as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    # ── Resolve output directory ──────────────────────────────────────────────
    if output_dir is None:
        output_dir = Path(".") / plugin_name
    else:
        output_dir = Path(output_dir)

    if output_dir.exists() and not force:
        console.print(f"[yellow]Directory {output_dir} already exists.[/yellow]")
        if not Confirm.ask("Continue and write into it?", default=True):
            console.print("[dim]Aborted.[/dim]")
            sys.exit(0)

    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Build Jinja2 context ──────────────────────────────────────────────────
    class_name = _slugify(plugin_name)
    module_name = plugin_name.replace("-", "_")

    context = {
        "plugin_name": plugin_name,
        "plugin_type": plugin_type,
        "plugin_type_upper": plugin_type.capitalize(),
        "class_name": class_name,
        "module_name": module_name,
        "description": description,
        "author": author,
        "version": plugin_version,
        "engine_min": ">=0.1.0",
    }

    # ── Render templates ──────────────────────────────────────────────────────
    env = Environment(
        loader=PackageLoader("clawforge", "templates"),
        autoescape=select_autoescape([]),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    console.print(f"\n[bold]Scaffolding[/bold] [cyan]{plugin_type}[/cyan] plugin → [green]{output_dir}/[/green]\n")

    rendered = _render_templates(env, plugin_type, context, output_dir, force)

    # ── Summary ───────────────────────────────────────────────────────────────
    console.print()
    console.print(Panel(
        "\n".join(f"  [green]✓[/green]  {f}" for f in rendered),
        title="[bold green]Files created[/bold green]",
        border_style="green",
    ))

    console.print(f"""
[bold]Next steps:[/bold]

  [cyan]cd {output_dir}[/cyan]
  [cyan]pip install -e .[/cyan]          [dim]# install plugin in dev mode[/dim]
  [cyan]clawforge dev .[/cyan]           [dim]# start hot-reload sandbox[/dim]

[dim]Plugin manifest:[/dim] {output_dir}/openclaw.plugin.json
[dim]Entry module   :[/dim] {output_dir}/{module_name}.py
""")
