"""Tests for models module."""

from pathlib import Path

from git_repo_checker.models import (
    AutoPullConfig,
    Config,
    OutputConfig,
    PullResult,
    RepoInfo,
    RepoStatus,
    ScanResult,
    SyncAction,
    SyncRepoResult,
    SyncResult,
    TrackedRepo,
    WarningType,
)


class TestRepoStatus:
    def test_all_status_values_exist(self):
        expected = ["clean", "dirty", "untracked", "ahead", "behind", "diverged", "no_remote", "error"]
        actual = [s.value for s in RepoStatus]
        assert sorted(actual) == sorted(expected)

    def test_status_is_string_enum(self):
        assert RepoStatus.CLEAN == "clean"
        assert RepoStatus.DIRTY.value == "dirty"


class TestWarningType:
    def test_all_warning_values_exist(self):
        expected = ["dirty_main", "no_remote", "detached"]
        actual = [w.value for w in WarningType]
        assert sorted(actual) == sorted(expected)


class TestRepoInfo:
    def test_create_minimal(self):
        info = RepoInfo(path=Path("/tmp/repo"), branch="main", status=RepoStatus.CLEAN)
        assert info.path == Path("/tmp/repo")
        assert info.branch == "main"
        assert info.status == RepoStatus.CLEAN
        assert info.warnings == []

    def test_create_with_all_fields(self):
        info = RepoInfo(
            path=Path("/tmp/repo"),
            branch="feature",
            status=RepoStatus.DIRTY,
            is_main_branch=False,
            ahead_count=2,
            behind_count=1,
            changed_files=3,
            untracked_files=1,
            warnings=[WarningType.NO_REMOTE],
            error_message=None,
        )
        assert info.ahead_count == 2
        assert info.behind_count == 1
        assert info.changed_files == 3
        assert WarningType.NO_REMOTE in info.warnings

    def test_default_values(self):
        info = RepoInfo(path=Path("/tmp"), branch="main", status=RepoStatus.CLEAN)
        assert info.is_main_branch is False
        assert info.ahead_count == 0
        assert info.behind_count == 0
        assert info.changed_files == 0
        assert info.untracked_files == 0
        assert info.error_message is None


class TestPullResult:
    def test_create_successful(self):
        result = PullResult(
            path=Path("/tmp/repo"),
            success=True,
            message="Pull successful",
            files_changed=5,
        )
        assert result.success is True
        assert result.files_changed == 5

    def test_create_failed(self):
        result = PullResult(path=Path("/tmp/repo"), success=False, message="Network error")
        assert result.success is False
        assert result.files_changed == 0


class TestScanResult:
    def test_create_empty(self):
        result = ScanResult()
        assert result.repos == []
        assert result.pull_results == []
        assert result.total_scanned == 0

    def test_create_with_repos(self):
        repo = RepoInfo(path=Path("/tmp"), branch="main", status=RepoStatus.CLEAN)
        result = ScanResult(repos=[repo], total_scanned=1)
        assert len(result.repos) == 1
        assert result.total_scanned == 1


class TestAutoPullConfig:
    def test_defaults(self):
        config = AutoPullConfig()
        assert config.enabled is True
        assert config.require_clean is True
        assert config.skip_patterns == []

    def test_custom_values(self):
        config = AutoPullConfig(enabled=False, skip_patterns=["**/test"])
        assert config.enabled is False
        assert "**/test" in config.skip_patterns


class TestOutputConfig:
    def test_defaults(self):
        config = OutputConfig()
        assert config.show_clean is True
        assert config.color is True
        assert config.verbosity == "normal"

    def test_quiet_mode(self):
        config = OutputConfig(verbosity="quiet")
        assert config.verbosity == "quiet"


class TestConfig:
    def test_defaults(self):
        config = Config()
        assert config.scan_paths == []
        assert config.exclude_patterns == []
        assert "main" in config.main_branches
        assert "master" in config.main_branches

    def test_with_paths(self):
        config = Config(
            scan_paths=[Path("/home/user/code")],
            exclude_patterns=["**/node_modules"],
        )
        assert len(config.scan_paths) == 1
        assert "**/node_modules" in config.exclude_patterns


class TestTrackedRepo:
    def test_create_minimal(self):
        repo = TrackedRepo(path=Path("/tmp/repo"), remote="git@github.com:u/r.git")
        assert repo.path == Path("/tmp/repo")
        assert repo.branch == "main"
        assert repo.ignore is False

    def test_custom_branch(self):
        repo = TrackedRepo(
            path=Path("/tmp/repo"),
            remote="git@github.com:u/r.git",
            branch="develop",
        )
        assert repo.branch == "develop"

    def test_ignore_flag(self):
        repo = TrackedRepo(
            path=Path("/tmp/repo"),
            remote="git@github.com:u/r.git",
            ignore=True,
        )
        assert repo.ignore is True


class TestSyncAction:
    def test_all_actions_exist(self):
        expected = ["cloned", "pulled", "skipped", "error"]
        actual = [a.value for a in SyncAction]
        assert sorted(actual) == sorted(expected)


class TestSyncRepoResult:
    def test_create(self):
        repo = TrackedRepo(path=Path("/tmp"), remote="git@github.com:u/r.git")
        result = SyncRepoResult(repo=repo, action=SyncAction.CLONED, message="Done")
        assert result.action == SyncAction.CLONED
        assert result.message == "Done"


class TestSyncResultModel:
    def test_defaults(self):
        result = SyncResult()
        assert result.results == []
        assert result.cloned == 0
        assert result.pulled == 0
        assert result.errors == 0

    def test_with_counts(self):
        result = SyncResult(cloned=2, pulled=1, errors=1)
        assert result.cloned == 2
        assert result.pulled == 1
        assert result.errors == 1
