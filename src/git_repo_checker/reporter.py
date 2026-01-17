"""Rich console output formatting."""

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from git_repo_checker.models import (
    OutputConfig,
    PullResult,
    RepoInfo,
    RepoStatus,
    ScanResult,
    WarningType,
)

STATUS_STYLES = {
    RepoStatus.CLEAN: ("green", "clean"),
    RepoStatus.DIRTY: ("red", "dirty"),
    RepoStatus.UNTRACKED: ("yellow", "untracked"),
    RepoStatus.AHEAD: ("cyan", "ahead"),
    RepoStatus.BEHIND: ("magenta", "behind"),
    RepoStatus.DIVERGED: ("red bold", "diverged"),
    RepoStatus.NO_REMOTE: ("dim", "no remote"),
    RepoStatus.ERROR: ("red bold", "error"),
}

WARNING_MESSAGES = {
    WarningType.DIRTY_MAIN: "Uncommitted changes on main branch",
    WarningType.NO_REMOTE: "No upstream remote configured",
    WarningType.DETACHED: "Detached HEAD state",
}


class Reporter:
    """Formats and displays scan results using Rich."""

    def __init__(self, console: Console, config: OutputConfig) -> None:
        """Initialize reporter.

        Args:
            console: Rich console for output.
            config: Output configuration settings.
        """
        self.console = console
        self.config = config

    def display_results(self, result: ScanResult) -> None:
        """Display full scan results.

        Shows summary, repo table, warnings, and pull results.

        Args:
            result: Scan result to display.
        """
        if self.config.verbosity == "quiet":
            self.display_quiet_summary(result)
            return

        self.display_summary(result)

        repos_to_show = self.filter_repos(result.repos)
        if repos_to_show:
            self.display_repo_table(repos_to_show)

        repos_with_warnings = [r for r in result.repos if r.warnings]
        if repos_with_warnings:
            self.display_warnings(repos_with_warnings)

        if result.pull_results:
            self.display_pull_results(result.pull_results)

    def filter_repos(self, repos: list[RepoInfo]) -> list[RepoInfo]:
        """Filter repos based on output config.

        Args:
            repos: All scanned repos.

        Returns:
            Filtered list based on show_clean setting.
        """
        if self.config.show_clean:
            return repos
        return [r for r in repos if r.status != RepoStatus.CLEAN]

    def display_repo_table(self, repos: list[RepoInfo]) -> None:
        """Display repositories in a table format.

        Args:
            repos: List of repository info to display.
        """
        table = Table(title="Repositories", expand=True)
        table.add_column("Path", style="blue", no_wrap=True)
        table.add_column("Branch", style="cyan")
        table.add_column("Status")
        table.add_column("Changes", justify="right")
        table.add_column("Ahead/Behind", justify="center")

        for repo in repos:
            status_style, status_text = STATUS_STYLES.get(
                repo.status, ("white", str(repo.status.value))
            )
            changes = self.format_changes(repo)
            ahead_behind = self.format_ahead_behind(repo)
            path_str = self.shorten_path(repo.path)

            table.add_row(
                path_str,
                repo.branch,
                f"[{status_style}]{status_text}[/]",
                changes,
                ahead_behind,
            )

        self.console.print(table)

    def display_warnings(self, repos: list[RepoInfo]) -> None:
        """Display warning panel for repos with issues.

        Args:
            repos: Repos with warnings to display.
        """
        warning_lines: list[str] = []

        for repo in repos:
            path_str = self.shorten_path(repo.path)
            for warning in repo.warnings:
                msg = WARNING_MESSAGES.get(warning, str(warning.value))
                warning_lines.append(f"[yellow]![/] {path_str}: {msg}")

        if warning_lines:
            panel = Panel(
                "\n".join(warning_lines),
                title="[bold yellow]Warnings[/]",
                border_style="yellow",
            )
            self.console.print(panel)

    def display_pull_results(self, results: list[PullResult]) -> None:
        """Display auto-pull results.

        Args:
            results: Pull results to display.
        """
        successful = [r for r in results if r.success]
        failed = [r for r in results if not r.success]

        if successful:
            self.console.print(f"\n[green]Pulled {len(successful)} repo(s)[/]")
            for result in successful:
                path_str = self.shorten_path(result.path)
                self.console.print(f"  [green]+[/] {path_str}: {result.message}")

        if failed:
            self.console.print(f"\n[red]Failed to pull {len(failed)} repo(s)[/]")
            for result in failed:
                path_str = self.shorten_path(result.path)
                self.console.print(f"  [red]x[/] {path_str}: {result.message}")

    def display_summary(self, result: ScanResult) -> None:
        """Display summary statistics.

        Args:
            result: Scan result for summary.
        """
        total = result.total_scanned
        clean = sum(1 for r in result.repos if r.status == RepoStatus.CLEAN)
        dirty = sum(1 for r in result.repos if r.status == RepoStatus.DIRTY)
        warnings = sum(1 for r in result.repos if r.warnings)

        self.console.print(f"\nScanned [bold]{total}[/] repositories")
        self.console.print(f"  [green]{clean}[/] clean, [red]{dirty}[/] dirty, ", end="")
        self.console.print(f"[yellow]{warnings}[/] with warnings\n")

    def display_quiet_summary(self, result: ScanResult) -> None:
        """Display minimal summary for quiet mode.

        Args:
            result: Scan result for summary.
        """
        dirty = [r for r in result.repos if r.status == RepoStatus.DIRTY]
        warnings = [r for r in result.repos if r.warnings]

        for repo in dirty:
            path_str = self.shorten_path(repo.path)
            self.console.print(f"[red]dirty[/] {path_str} ({repo.branch})")

        for repo in warnings:
            if repo not in dirty:
                path_str = self.shorten_path(repo.path)
                self.console.print(f"[yellow]warn[/] {path_str} ({repo.branch})")

    def format_changes(self, repo: RepoInfo) -> str:
        """Format change counts for display.

        Args:
            repo: Repository info.

        Returns:
            Formatted string showing modified/untracked counts.
        """
        parts: list[str] = []
        if repo.changed_files > 0:
            parts.append(f"[red]{repo.changed_files}M[/]")
        if repo.untracked_files > 0:
            parts.append(f"[yellow]{repo.untracked_files}?[/]")
        return " ".join(parts) if parts else "-"

    def format_ahead_behind(self, repo: RepoInfo) -> str:
        """Format ahead/behind counts.

        Args:
            repo: Repository info.

        Returns:
            Formatted ahead/behind string.
        """
        if repo.ahead_count == 0 and repo.behind_count == 0:
            return "-"

        parts: list[str] = []
        if repo.ahead_count > 0:
            parts.append(f"[cyan]+{repo.ahead_count}[/]")
        if repo.behind_count > 0:
            parts.append(f"[magenta]-{repo.behind_count}[/]")
        return "/".join(parts)

    def shorten_path(self, path: Path) -> str:
        """Shorten path for display using home directory.

        Args:
            path: Absolute path.

        Returns:
            Shortened path string.
        """
        try:
            return "~/" + str(path.relative_to(Path.home()))
        except ValueError:
            return str(path)
