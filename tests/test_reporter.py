"""Tests for reporter module."""

from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from git_repo_checker.models import (
    OutputConfig,
    PullResult,
    RepoInfo,
    RepoStatus,
    ScanResult,
    WarningType,
)
from git_repo_checker.reporter import Reporter


@pytest.fixture
def console_capture():
    """Create a console that captures output."""
    return Console(file=StringIO(), force_terminal=True, width=120)


@pytest.fixture
def reporter(console_capture):
    """Create a reporter with captured console."""
    config = OutputConfig(show_clean=True, color=True, verbosity="normal")
    return Reporter(console_capture, config)


class TestReporterInit:
    def test_creates_with_config(self, console_capture):
        config = OutputConfig(verbosity="quiet")
        reporter = Reporter(console_capture, config)
        assert reporter.config.verbosity == "quiet"


class TestDisplayResults:
    def test_displays_empty_results(self, reporter, console_capture):
        result = ScanResult()
        reporter.display_results(result)
        output = console_capture.file.getvalue()
        assert "0" in output

    def test_displays_repos(self, reporter, console_capture):
        repo = RepoInfo(
            path=Path("/tmp/test-repo"),
            branch="main",
            status=RepoStatus.CLEAN,
        )
        result = ScanResult(repos=[repo], total_scanned=1)
        reporter.display_results(result)
        output = console_capture.file.getvalue()
        assert "test-repo" in output or "Repositories" in output

    def test_quiet_mode_minimal_output(self, console_capture):
        config = OutputConfig(verbosity="quiet")
        reporter = Reporter(console_capture, config)
        repo = RepoInfo(
            path=Path("/tmp/test-repo"),
            branch="main",
            status=RepoStatus.DIRTY,
        )
        result = ScanResult(repos=[repo], total_scanned=1)
        reporter.display_results(result)
        output = console_capture.file.getvalue()
        assert "dirty" in output


class TestFilterRepos:
    def test_shows_all_when_show_clean(self, reporter):
        repos = [
            RepoInfo(path=Path("/a"), branch="main", status=RepoStatus.CLEAN),
            RepoInfo(path=Path("/b"), branch="main", status=RepoStatus.DIRTY),
        ]
        filtered = reporter.filter_repos(repos)
        assert len(filtered) == 2

    def test_hides_clean_when_disabled(self, console_capture):
        config = OutputConfig(show_clean=False)
        reporter = Reporter(console_capture, config)
        repos = [
            RepoInfo(path=Path("/a"), branch="main", status=RepoStatus.CLEAN),
            RepoInfo(path=Path("/b"), branch="main", status=RepoStatus.DIRTY),
        ]
        filtered = reporter.filter_repos(repos)
        assert len(filtered) == 1
        assert filtered[0].status == RepoStatus.DIRTY


class TestDisplayRepoTable:
    def test_creates_table(self, reporter, console_capture):
        repos = [
            RepoInfo(
                path=Path("/tmp/repo1"),
                branch="main",
                status=RepoStatus.CLEAN,
            ),
            RepoInfo(
                path=Path("/tmp/repo2"),
                branch="feature",
                status=RepoStatus.DIRTY,
                changed_files=3,
            ),
        ]
        reporter.display_repo_table(repos)
        output = console_capture.file.getvalue()
        assert "Repositories" in output


class TestDisplayWarnings:
    def test_displays_warning_panel(self, reporter, console_capture):
        repos = [
            RepoInfo(
                path=Path("/tmp/repo"),
                branch="main",
                status=RepoStatus.DIRTY,
                is_main_branch=True,
                warnings=[WarningType.DIRTY_MAIN],
            ),
        ]
        reporter.display_warnings(repos)
        output = console_capture.file.getvalue()
        assert "Warnings" in output or "main branch" in output


class TestDisplayPullResults:
    def test_displays_successful_pulls(self, reporter, console_capture):
        results = [
            PullResult(path=Path("/tmp/repo"), success=True, message="Pull successful"),
        ]
        reporter.display_pull_results(results)
        output = console_capture.file.getvalue()
        assert "Pulled" in output or "successful" in output

    def test_displays_failed_pulls(self, reporter, console_capture):
        results = [
            PullResult(path=Path("/tmp/repo"), success=False, message="Network error"),
        ]
        reporter.display_pull_results(results)
        output = console_capture.file.getvalue()
        assert "Failed" in output or "error" in output


class TestDisplaySummary:
    def test_shows_counts(self, reporter, console_capture):
        repos = [
            RepoInfo(path=Path("/a"), branch="main", status=RepoStatus.CLEAN),
            RepoInfo(path=Path("/b"), branch="main", status=RepoStatus.DIRTY),
        ]
        result = ScanResult(repos=repos, total_scanned=2)
        reporter.display_summary(result)
        output = console_capture.file.getvalue()
        assert "2" in output


class TestDisplayQuietSummary:
    def test_shows_only_dirty(self, console_capture):
        config = OutputConfig(verbosity="quiet")
        reporter = Reporter(console_capture, config)
        repos = [
            RepoInfo(path=Path("/tmp/clean"), branch="main", status=RepoStatus.CLEAN),
            RepoInfo(path=Path("/tmp/dirty"), branch="main", status=RepoStatus.DIRTY),
        ]
        result = ScanResult(repos=repos, total_scanned=2)
        reporter.display_quiet_summary(result)
        output = console_capture.file.getvalue()
        assert "dirty" in output


class TestFormatChanges:
    def test_formats_modified(self, reporter):
        repo = RepoInfo(
            path=Path("/tmp"),
            branch="main",
            status=RepoStatus.DIRTY,
            changed_files=3,
        )
        result = reporter.format_changes(repo)
        assert "3" in result
        assert "M" in result

    def test_formats_untracked(self, reporter):
        repo = RepoInfo(
            path=Path("/tmp"),
            branch="main",
            status=RepoStatus.UNTRACKED,
            untracked_files=2,
        )
        result = reporter.format_changes(repo)
        assert "2" in result
        assert "?" in result

    def test_returns_dash_for_clean(self, reporter):
        repo = RepoInfo(
            path=Path("/tmp"),
            branch="main",
            status=RepoStatus.CLEAN,
        )
        result = reporter.format_changes(repo)
        assert result == "-"


class TestFormatAheadBehind:
    def test_formats_ahead(self, reporter):
        repo = RepoInfo(
            path=Path("/tmp"),
            branch="main",
            status=RepoStatus.AHEAD,
            ahead_count=2,
        )
        result = reporter.format_ahead_behind(repo)
        assert "+2" in result

    def test_formats_behind(self, reporter):
        repo = RepoInfo(
            path=Path("/tmp"),
            branch="main",
            status=RepoStatus.BEHIND,
            behind_count=3,
        )
        result = reporter.format_ahead_behind(repo)
        assert "-3" in result

    def test_returns_dash_for_none(self, reporter):
        repo = RepoInfo(
            path=Path("/tmp"),
            branch="main",
            status=RepoStatus.CLEAN,
        )
        result = reporter.format_ahead_behind(repo)
        assert result == "-"


class TestShortenPath:
    def test_shortens_home_path(self, reporter):
        home = Path.home()
        path = home / "code" / "project"
        result = reporter.shorten_path(path)
        assert result.startswith("~/")
        assert "code/project" in result

    def test_returns_absolute_for_other(self, reporter):
        path = Path("/some/other/path")
        result = reporter.shorten_path(path)
        assert result == "/some/other/path"


class TestDisplayWarningsMultiple:
    def test_displays_multiple_warnings(self, reporter, console_capture):
        repos = [
            RepoInfo(
                path=Path("/tmp/repo1"),
                branch="main",
                status=RepoStatus.DIRTY,
                is_main_branch=True,
                warnings=[WarningType.DIRTY_MAIN, WarningType.NO_REMOTE],
            ),
        ]
        reporter.display_warnings(repos)
        output = console_capture.file.getvalue()
        assert "Warnings" in output


class TestFormatBoth:
    def test_formats_both_changes_and_untracked(self, reporter):
        repo = RepoInfo(
            path=Path("/tmp"),
            branch="main",
            status=RepoStatus.DIRTY,
            changed_files=2,
            untracked_files=3,
        )
        result = reporter.format_changes(repo)
        assert "2" in result
        assert "3" in result

    def test_formats_both_ahead_and_behind(self, reporter):
        repo = RepoInfo(
            path=Path("/tmp"),
            branch="main",
            status=RepoStatus.DIVERGED,
            ahead_count=2,
            behind_count=3,
        )
        result = reporter.format_ahead_behind(repo)
        assert "+2" in result
        assert "-3" in result
