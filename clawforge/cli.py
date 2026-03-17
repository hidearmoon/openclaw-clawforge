"""
ClawForge CLI main entry point.
"""

import click
from rich.console import Console
from rich.text import Text

from clawforge import __version__
from clawforge.init_cmd import init
from clawforge.dev_cmd import dev
from clawforge.test_cmd import test

console = Console()

BANNER = """
 ██████╗██╗      █████╗ ██╗    ██╗███████╗ ██████╗ ██████╗  ██████╗ ███████╗
██╔════╝██║     ██╔══██╗██║    ██║██╔════╝██╔═══██╗██╔══██╗██╔════╝ ██╔════╝
██║     ██║     ███████║██║ █╗ ██║█████╗  ██║   ██║██████╔╝██║  ███╗█████╗
██║     ██║     ██╔══██║██║███╗██║██╔══╝  ██║   ██║██╔══██╗██║   ██║██╔══╝
╚██████╗███████╗██║  ██║╚███╔███╔╝██║     ╚██████╔╝██║  ██║╚██████╔╝███████╗
 ╚═════╝╚══════╝╚═╝  ╚═╝ ╚══╝╚══╝ ╚═╝      ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚══════╝
"""


@click.group()
@click.version_option(version=__version__, prog_name="clawforge")
def main():
    """ClawForge - OpenClaw Plugin Development Scaffold & Dev Sandbox.

    \b
    Commands:
      init    Scaffold a new OpenClaw plugin from template
      dev     Start local dev sandbox with hot-reload
      test    Run compatibility checks on a plugin directory

    \b
    Quick start:
      clawforge init --type tool --name my-plugin
      cd my-plugin
      clawforge dev .
    """
    pass


main.add_command(init)
main.add_command(dev)
main.add_command(test)


if __name__ == "__main__":
    main()
