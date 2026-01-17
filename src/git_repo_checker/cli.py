"""git-repo-checker CLI."""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from git_repo_checker import config as config_module
from git_repo_checker.analyzer import analyze_repo, scan_and_analyze
from git_repo_checker.models import Config, OutputConfig
from git_repo_checker.reporter import Reporter

app = typer.Typer(
    name="git-repo-checker",
    help="Scan and report status of git repositories",
    no_args_is_help=False,
)

console = Console()


def get_config(config_path: Path | None, verbose: bool, quiet: bool) -> Config:
    """Load config and apply CLI overrides.

    Args:
        config_path: Optional explicit config path.
        verbose: Whether verbose output requested.
        quiet: Whether quiet output requested.

    Returns:
        Config with CLI overrides applied.
    """
    config = config_module.load_config(config_path)

    if verbose:
        config.output.verbosity = "verbose"
    elif quiet:
        config.output.verbosity = "quiet"

    return config


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    config_path: Annotated[
        Path | None,
        typer.Option("-c", "--config", help="Path to config file"),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("-v", "--verbose", help="Verbose output"),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option("-q", "--quiet", help="Minimal output"),
    ] = False,
) -> None:
    """Scan configured directories and report git repository status.

    If no subcommand given, runs the default scan.
    """
    if ctx.invoked_subcommand is not None:
        return

    try:
        config = get_config(config_path, verbose, quiet)
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1) from e

    result = scan_and_analyze(config)
    reporter = Reporter(console, config.output)
    reporter.display_results(result)


@app.command()
def scan(
    paths: Annotated[
        list[Path] | None,
        typer.Argument(help="Paths to scan (overrides config)"),
    ] = None,
    config_path: Annotated[
        Path | None,
        typer.Option("-c", "--config", help="Path to config file"),
    ] = None,
    no_pull: Annotated[
        bool,
        typer.Option("--no-pull", help="Disable auto-pull"),
    ] = False,
    warnings_only: Annotated[
        bool,
        typer.Option("--warnings-only", "-w", help="Only show repos with warnings"),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("-v", "--verbose", help="Verbose output"),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option("-q", "--quiet", help="Minimal output"),
    ] = False,
) -> None:
    """Scan directories for git repositories.

    Reports status and optionally auto-pulls clean repos behind remote.
    """
    try:
        config = get_config(config_path, verbose, quiet)
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1) from e

    if paths:
        config.scan_paths = [p.expanduser().resolve() for p in paths]

    if no_pull:
        config.auto_pull.enabled = False

    if warnings_only:
        config.output.show_clean = False

    result = scan_and_analyze(config, auto_pull=config.auto_pull.enabled)
    reporter = Reporter(console, config.output)
    reporter.display_results(result)


@app.command()
def init(
    path: Annotated[
        Path,
        typer.Argument(help="Where to create config file"),
    ] = Path("./git-repo-checker.yml"),
) -> None:
    """Create a default configuration file."""
    try:
        config_module.create_default_config(path)
        console.print(f"[green]Created config file:[/] {path}")
        console.print("Edit this file to configure scan paths and exclusions.")
    except FileExistsError as e:
        console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1) from e


@app.command()
def check(
    repo_path: Annotated[
        Path,
        typer.Argument(help="Repository path to check"),
    ],
    verbose: Annotated[
        bool,
        typer.Option("-v", "--verbose", help="Verbose output"),
    ] = False,
) -> None:
    """Check status of a single repository."""
    repo_path = repo_path.expanduser().resolve()

    if not (repo_path / ".git").exists():
        console.print(f"[red]Error:[/] Not a git repository: {repo_path}")
        raise typer.Exit(1)

    config = Config(main_branches=["main", "master"])
    repo_info = analyze_repo(repo_path, config)

    output_config = OutputConfig(verbosity="verbose" if verbose else "normal")
    reporter = Reporter(console, output_config)
    reporter.display_repo_table([repo_info])

    if repo_info.warnings:
        reporter.display_warnings([repo_info])
