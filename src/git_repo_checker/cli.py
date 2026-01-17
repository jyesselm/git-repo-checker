"""git-repo-checker CLI."""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from git_repo_checker import config as config_module
from git_repo_checker import sync as sync_module
from git_repo_checker.analyzer import analyze_repo, scan_and_analyze
from git_repo_checker.models import Config, OutputConfig, SyncAction
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


@app.command()
def sync(
    repos_path: Annotated[
        Path | None,
        typer.Option("-r", "--repos", help="Path to repos.yml file"),
    ] = None,
    init_repos: Annotated[
        bool,
        typer.Option("--init", help="Create a template repos.yml file"),
    ] = False,
    no_pull: Annotated[
        bool,
        typer.Option("--no-pull", help="Only clone missing repos, don't pull existing"),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option("-q", "--quiet", help="Minimal output"),
    ] = False,
) -> None:
    """Sync tracked repositories - clone missing, pull existing.

    Uses repos.yml to define which repositories should exist locally.
    """
    if init_repos:
        _init_repos_file(repos_path)
        return

    repos = _load_repos_or_exit(repos_path)
    if not repos:
        console.print("[yellow]No repositories defined in repos file.[/]")
        return

    console.print(f"Syncing [bold]{len(repos)}[/] tracked repositories...\n")
    result = sync_module.sync_all(repos, pull_existing=not no_pull)
    _display_sync_results(result, quiet)


def _init_repos_file(repos_path: Path | None) -> None:
    """Initialize a new repos file."""
    output_path = repos_path or Path("./repos.yml")
    try:
        sync_module.create_repos_file(output_path)
        console.print(f"[green]Created repos file:[/] {output_path}")
        console.print("Edit this file to add repositories to track.")
    except FileExistsError as e:
        console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1) from e


def _load_repos_or_exit(repos_path: Path | None) -> list:
    """Load repos file or exit with error."""
    try:
        return sync_module.load_repos_file(repos_path)
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1) from e


def _display_sync_results(result: sync_module.SyncResult, quiet: bool) -> None:
    """Display sync results to console."""
    for repo_result in result.results:
        path_str = shorten_path(repo_result.repo.path)
        _print_repo_result(repo_result, path_str, quiet)

    if not quiet:
        _print_sync_summary(result)


def _print_repo_result(repo_result: sync_module.SyncRepoResult, path_str: str, quiet: bool) -> None:
    """Print a single repo sync result."""
    if repo_result.action == SyncAction.CLONED:
        console.print(f"  [green]+[/] {path_str}: {repo_result.message}")
    elif repo_result.action == SyncAction.PULLED:
        console.print(f"  [cyan]↓[/] {path_str}: {repo_result.message}")
    elif repo_result.action == SyncAction.ERROR:
        console.print(f"  [red]✗[/] {path_str}: {repo_result.message}")
    elif not quiet:
        console.print(f"  [dim]·[/] {path_str}: {repo_result.message}")


def _print_sync_summary(result: sync_module.SyncResult) -> None:
    """Print sync summary."""
    console.print("\n[bold]Summary:[/] ", end="")
    parts = []
    if result.cloned:
        parts.append(f"[green]{result.cloned} cloned[/]")
    if result.pulled:
        parts.append(f"[cyan]{result.pulled} pulled[/]")
    if result.skipped:
        parts.append(f"[dim]{result.skipped} skipped[/]")
    if result.errors:
        parts.append(f"[red]{result.errors} errors[/]")
    console.print(", ".join(parts) if parts else "nothing to do")


def shorten_path(path: Path) -> str:
    """Shorten path for display using home directory."""
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)
