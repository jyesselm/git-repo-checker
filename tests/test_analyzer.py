"""Tests for analyzer module."""

from pathlib import Path

from git_repo_checker import analyzer
from git_repo_checker.models import (
    AutoPullConfig,
    Config,
    RepoInfo,
    RepoStatus,
    WarningType,
)


class TestAnalyzeRepo:
    def test_analyzes_clean_repo(self, temp_git_repo, sample_config):
        result = analyzer.analyze_repo(temp_git_repo, sample_config)
        assert result.path == temp_git_repo
        assert result.status in (RepoStatus.CLEAN, RepoStatus.NO_REMOTE)
        assert result.branch in ["master", "main"]

    def test_analyzes_dirty_repo(self, temp_git_repo_dirty, sample_config):
        result = analyzer.analyze_repo(temp_git_repo_dirty, sample_config)
        assert result.status == RepoStatus.DIRTY
        assert result.changed_files >= 1

    def test_handles_git_error(self, tmp_path, sample_config):
        # Not a git repo
        result = analyzer.analyze_repo(tmp_path, sample_config)
        assert result.status == RepoStatus.ERROR
        assert result.error_message is not None


class TestIsMainBranch:
    def test_main_is_main(self):
        assert analyzer.is_main_branch("main", ["main", "master"]) is True

    def test_master_is_main(self):
        assert analyzer.is_main_branch("master", ["main", "master"]) is True

    def test_feature_not_main(self):
        assert analyzer.is_main_branch("feature-x", ["main", "master"]) is False

    def test_case_insensitive(self):
        assert analyzer.is_main_branch("MAIN", ["main", "master"]) is True
        assert analyzer.is_main_branch("Main", ["main"]) is True


class TestDetectWarnings:
    def test_dirty_main_warning(self):
        warnings = analyzer.detect_warnings(
            branch="main",
            status=RepoStatus.DIRTY,
            is_main=True,
            has_remote=True,
        )
        assert WarningType.DIRTY_MAIN in warnings

    def test_no_remote_warning(self):
        warnings = analyzer.detect_warnings(
            branch="feature",
            status=RepoStatus.CLEAN,
            is_main=False,
            has_remote=False,
        )
        assert WarningType.NO_REMOTE in warnings

    def test_detached_head_warning(self):
        warnings = analyzer.detect_warnings(
            branch="HEAD",
            status=RepoStatus.CLEAN,
            is_main=False,
            has_remote=True,
        )
        assert WarningType.DETACHED in warnings

    def test_no_warnings_for_clean_feature(self):
        warnings = analyzer.detect_warnings(
            branch="feature",
            status=RepoStatus.CLEAN,
            is_main=False,
            has_remote=True,
        )
        assert warnings == []


class TestShouldAutoPull:
    def test_pulls_when_behind_and_clean(self):
        repo = RepoInfo(
            path=Path("/tmp"),
            branch="main",
            status=RepoStatus.CLEAN,
            behind_count=3,
        )
        config = Config(auto_pull=AutoPullConfig(enabled=True, require_clean=True))
        assert analyzer.should_auto_pull(repo, config) is True

    def test_no_pull_when_disabled(self):
        repo = RepoInfo(
            path=Path("/tmp"),
            branch="main",
            status=RepoStatus.CLEAN,
            behind_count=3,
        )
        config = Config(auto_pull=AutoPullConfig(enabled=False))
        assert analyzer.should_auto_pull(repo, config) is False

    def test_no_pull_when_dirty(self):
        repo = RepoInfo(
            path=Path("/tmp"),
            branch="main",
            status=RepoStatus.DIRTY,
            behind_count=3,
        )
        config = Config(auto_pull=AutoPullConfig(enabled=True, require_clean=True))
        assert analyzer.should_auto_pull(repo, config) is False

    def test_no_pull_when_not_behind(self):
        repo = RepoInfo(
            path=Path("/tmp"),
            branch="main",
            status=RepoStatus.CLEAN,
            behind_count=0,
        )
        config = Config(auto_pull=AutoPullConfig(enabled=True))
        assert analyzer.should_auto_pull(repo, config) is False

    def test_no_pull_when_error_status(self):
        repo = RepoInfo(
            path=Path("/tmp"),
            branch="main",
            status=RepoStatus.ERROR,
            behind_count=3,
        )
        config = Config(auto_pull=AutoPullConfig(enabled=True))
        assert analyzer.should_auto_pull(repo, config) is False

    def test_no_pull_when_matches_skip_pattern(self):
        repo = RepoInfo(
            path=Path("/tmp/experimental/repo"),
            branch="main",
            status=RepoStatus.CLEAN,
            behind_count=3,
        )
        config = Config(
            auto_pull=AutoPullConfig(
                enabled=True,
                skip_patterns=["**/experimental/*"],
            )
        )
        assert analyzer.should_auto_pull(repo, config) is False


class TestMatchesSkipPattern:
    def test_matches_pattern(self):
        path = Path("/code/experimental/repo")
        assert analyzer.matches_skip_pattern(path, ["**/experimental/*"])

    def test_no_match(self):
        path = Path("/code/project/repo")
        assert analyzer.matches_skip_pattern(path, ["**/experimental/*"]) is False


class TestScanAndAnalyze:
    def test_scans_and_returns_results(self, nested_repos, sample_config):
        sample_config.scan_paths = [nested_repos]
        sample_config.exclude_patterns = ["**/node_modules"]
        sample_config.auto_pull.enabled = False

        result = analyzer.scan_and_analyze(sample_config, auto_pull=False)

        assert result.total_scanned >= 3
        assert len(result.repos) >= 3
        for repo in result.repos:
            assert isinstance(repo, RepoInfo)

    def test_respects_auto_pull_flag(self, nested_repos, sample_config):
        sample_config.scan_paths = [nested_repos]
        sample_config.auto_pull.enabled = True

        result = analyzer.scan_and_analyze(sample_config, auto_pull=False)

        # No pull results because auto_pull=False was passed
        assert result.pull_results == []
