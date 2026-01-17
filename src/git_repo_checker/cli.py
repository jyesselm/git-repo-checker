"""git-repo-checker CLI."""

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from git_repo_checker import config as config_module
from git_repo_checker import sync as sync_module
from git_repo_checker.analyzer import analyze_repo, scan_and_analyze
from git_repo_checker.models import CIStatus, Config, OutputConfig, RepoStatus, ScanResult, SyncAction
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
    status_filter: Annotated[
        str | None,
        typer.Option("--status", "-s", help="Filter by status (comma-separated: dirty,ahead,behind)"),
    ] = None,
    check_ci: Annotated[
        bool,
        typer.Option("--ci", help="Check GitHub Actions CI status (requires gh CLI)"),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output results as JSON"),
    ] = False,
    export_repos: Annotated[
        Path | None,
        typer.Option("--export-repos", help="Export scanned repos to a repos.yml file"),
    ] = None,
    merge: Annotated[
        bool,
        typer.Option("--merge", help="Merge with existing repos.yml instead of failing"),
    ] = False,
    path_prefix: Annotated[
        str,
        typer.Option("--path-prefix", "-p", help="Path prefix for exported repos"),
    ] = "~",
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
        if json_output:
            print(json.dumps({"error": str(e)}))
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1) from e

    if paths:
        config.scan_paths = [p.expanduser().resolve() for p in paths]

    if no_pull:
        config.auto_pull.enabled = False

    if warnings_only:
        config.output.show_clean = False

    result = scan_and_analyze(config, auto_pull=config.auto_pull.enabled)

    # Check CI status if requested
    if check_ci:
        _add_ci_status(result)

    # Apply status filter if specified
    if status_filter:
        result = _filter_by_status(result, status_filter)

    # Export repos if requested
    if export_repos:
        try:
            added, skipped, collisions = sync_module.export_repos_to_file(
                result.repos, export_repos, path_prefix, merge
            )
            console.print(f"[green]Exported to:[/] {export_repos}")
            console.print(f"  Added: {added}, Skipped: {skipped} (no remote or already tracked)")
            if collisions:
                console.print(f"\n[yellow]Path collisions detected ({len(collisions)}):[/]")
                for path, new_remote, existing_remote in collisions:
                    console.print(f"  {path}")
                    console.print(f"    [dim]existing:[/] {existing_remote}")
                    console.print(f"    [dim]new (skipped):[/] {new_remote}")
            return
        except FileExistsError as e:
            console.print(f"[red]Error:[/] {e}")
            raise typer.Exit(1) from e

    if json_output:
        _output_json(result)
        return

    reporter = Reporter(console, config.output)
    reporter.display_results(result, show_ci=check_ci)


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
    repos_url: Annotated[
        str | None,
        typer.Option("--repos-url", help="URL to fetch repos.yml from (saves to ~/.config)"),
    ] = None,
    path_prefix: Annotated[
        str | None,
        typer.Option("--path-prefix", "-p", help="Override path prefix for this machine"),
    ] = None,
    init_repos: Annotated[
        bool,
        typer.Option("--init", help="Create a template repos.yml file"),
    ] = False,
    no_pull: Annotated[
        bool,
        typer.Option("--no-pull", help="Only clone missing repos, don't pull existing"),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", "-n", help="Show what would be done without executing"),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option("-q", "--quiet", help="Minimal output"),
    ] = False,
) -> None:
    """Sync tracked repositories - clone missing, pull existing.

    Uses repos.yml to define which repositories should exist locally.
    Override paths for different machines with --path-prefix or local.yml.
    """
    if init_repos:
        _init_repos_file(repos_path)
        return

    if repos_url:
        repos_path = _fetch_repos_from_url(repos_url)

    repos = _load_repos_or_exit(repos_path, path_prefix)
    if not repos:
        console.print("[yellow]No repositories defined in repos file.[/]")
        return

    if dry_run:
        _display_sync_dry_run(repos, not no_pull)
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


def _load_repos_or_exit(repos_path: Path | None, path_prefix: str | None = None) -> list:
    """Load repos file or exit with error."""
    try:
        return sync_module.load_repos_file(repos_path, path_prefix)
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1) from e


def _fetch_repos_from_url(url: str) -> Path:
    """Fetch repos file from URL and return local path."""
    from urllib.error import URLError

    try:
        console.print(f"Fetching repos.yml from [cyan]{url}[/]...")
        path = sync_module.fetch_repos_from_url(url)
        console.print(f"[green]Saved to:[/] {path}\n")
        return path
    except URLError as e:
        console.print(f"[red]Error fetching URL:[/] {e}")
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


def _add_ci_status(result: ScanResult) -> None:
    """Add CI status to all repos in the result.

    Args:
        result: ScanResult to update with CI status.
    """
    from git_repo_checker import github_ops

    if not github_ops.is_gh_available():
        console.print("[yellow]Warning: gh CLI not available, skipping CI status checks[/]")
        return

    for repo in result.repos:
        repo.ci_status = github_ops.get_ci_status(repo.path)


def _filter_by_status(result: ScanResult, status_filter: str) -> ScanResult:
    """Filter scan results by status values.

    Args:
        result: The scan result to filter.
        status_filter: Comma-separated list of status values (e.g., "dirty,ahead,behind").

    Returns:
        Filtered ScanResult with only matching repos.
    """
    statuses = {s.strip().lower() for s in status_filter.split(",")}
    valid_statuses = {s.value for s in RepoStatus}

    # Validate status values
    invalid = statuses - valid_statuses
    if invalid:
        console.print(f"[yellow]Warning: Unknown status values: {', '.join(invalid)}[/]")
        console.print(f"[dim]Valid values: {', '.join(sorted(valid_statuses))}[/]")

    filtered_repos = [r for r in result.repos if r.status.value in statuses]

    return ScanResult(
        repos=filtered_repos,
        pull_results=result.pull_results,
        total_scanned=result.total_scanned,
        scan_errors=result.scan_errors,
    )


def _output_json(result: ScanResult) -> None:
    """Output scan results as JSON.

    Args:
        result: The scan result to output.
    """
    # Convert to dict with string paths for JSON serialization
    output = {
        "total_scanned": result.total_scanned,
        "repos": [
            {
                "path": str(r.path),
                "branch": r.branch,
                "status": r.status.value,
                "is_main_branch": r.is_main_branch,
                "ahead_count": r.ahead_count,
                "behind_count": r.behind_count,
                "changed_files": r.changed_files,
                "untracked_files": r.untracked_files,
                "has_stash": r.has_stash,
                "ci_status": r.ci_status.value if r.ci_status else None,
                "warnings": [w.value for w in r.warnings],
                "error_message": r.error_message,
            }
            for r in result.repos
        ],
        "pull_results": [
            {
                "path": str(p.path),
                "success": p.success,
                "message": p.message,
                "files_changed": p.files_changed,
            }
            for p in result.pull_results
        ],
        "scan_errors": result.scan_errors,
    }
    print(json.dumps(output, indent=2))


def _display_sync_dry_run(repos: list, pull_existing: bool) -> None:
    """Display what sync would do without executing.

    Args:
        repos: List of TrackedRepo objects.
        pull_existing: Whether pulling existing repos is enabled.
    """
    console.print("[bold]Dry run - no changes will be made[/]\n")

    would_clone = []
    would_pull = []
    would_skip = []

    for repo in repos:
        path_str = shorten_path(repo.path)
        if repo.ignore:
            would_skip.append((path_str, "ignored"))
        elif not repo.path.exists():
            would_clone.append((path_str, repo.remote))
        elif pull_existing:
            would_pull.append((path_str, "check for updates"))
        else:
            would_skip.append((path_str, "exists, no-pull mode"))

    if would_clone:
        console.print("[green]Would clone:[/]")
        for path, remote in would_clone:
            console.print(f"  + {path} from {remote}")

    if would_pull:
        console.print("[cyan]Would check/pull:[/]")
        for path, msg in would_pull:
            console.print(f"  ↓ {path}: {msg}")

    if would_skip:
        console.print("[dim]Would skip:[/]")
        for path, reason in would_skip:
            console.print(f"  · {path}: {reason}")

    console.print(f"\n[bold]Summary:[/] {len(would_clone)} to clone, ", end="")
    console.print(f"{len(would_pull)} to check, {len(would_skip)} to skip")
