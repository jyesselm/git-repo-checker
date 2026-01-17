"""Tests for sync module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from git_repo_checker import sync
from git_repo_checker.models import PullResult, SyncAction, TrackedRepo


@pytest.fixture
def sample_repos_yaml(tmp_path: Path) -> Path:
    """Create a sample repos.yml file."""
    repos_path = tmp_path / "repos.yml"
    repos_path.write_text(
        """\
repos:
  - path: /tmp/repo1
    remote: git@github.com:user/repo1.git
    branch: main
  - path: /tmp/repo2
    remote: https://github.com/user/repo2.git
"""
    )
    return repos_path


@pytest.fixture
def tracked_repo(tmp_path: Path) -> TrackedRepo:
    """Create a sample tracked repo."""
    return TrackedRepo(
        path=tmp_path / "test-repo",
        remote="git@github.com:user/test-repo.git",
        branch="main",
    )


class TestFindReposFile:
    def test_returns_none_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            sync,
            "DEFAULT_REPOS_LOCATIONS",
            [tmp_path / "nonexistent.yml"],
        )
        assert sync.find_repos_file() is None

    def test_finds_local_file(self, tmp_path, monkeypatch):
        repos_file = tmp_path / "repos.yml"
        repos_file.write_text("repos: []")
        monkeypatch.setattr(
            sync,
            "DEFAULT_REPOS_LOCATIONS",
            [repos_file],
        )
        assert sync.find_repos_file() == repos_file


class TestLoadReposFile:
    def test_raises_when_no_file_found(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            sync,
            "DEFAULT_REPOS_LOCATIONS",
            [tmp_path / "nonexistent.yml"],
        )
        with pytest.raises(FileNotFoundError):
            sync.load_repos_file()

    def test_loads_from_explicit_path(self, sample_repos_yaml):
        repos = sync.load_repos_file(sample_repos_yaml)
        assert len(repos) == 2
        assert repos[0].remote == "git@github.com:user/repo1.git"


class TestLoadReposFromPath:
    def test_raises_for_nonexistent(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            sync.load_repos_from_path(tmp_path / "nonexistent.yml")

    def test_parses_repos(self, sample_repos_yaml):
        repos = sync.load_repos_from_path(sample_repos_yaml)
        assert len(repos) == 2
        assert repos[0].branch == "main"
        assert repos[1].branch == "main"  # default

    def test_handles_empty_file(self, tmp_path):
        empty = tmp_path / "empty.yml"
        empty.write_text("")
        repos = sync.load_repos_from_path(empty)
        assert repos == []

    def test_handles_empty_repos_list(self, tmp_path):
        empty = tmp_path / "empty.yml"
        empty.write_text("repos: []")
        repos = sync.load_repos_from_path(empty)
        assert repos == []


class TestParseTrackedRepo:
    def test_parses_full_entry(self, tmp_path):
        raw = {
            "path": str(tmp_path / "repo"),
            "remote": "git@github.com:user/repo.git",
            "branch": "develop",
        }
        repo = sync.parse_tracked_repo(raw)
        assert repo.path == tmp_path / "repo"
        assert repo.remote == "git@github.com:user/repo.git"
        assert repo.branch == "develop"

    def test_default_branch(self):
        raw = {"path": "/tmp/repo", "remote": "git@github.com:user/repo.git"}
        repo = sync.parse_tracked_repo(raw)
        assert repo.branch == "main"

    def test_expands_home(self):
        raw = {"path": "~/code/repo", "remote": "git@github.com:user/repo.git"}
        repo = sync.parse_tracked_repo(raw)
        assert not str(repo.path).startswith("~")

    def test_parses_ignore_flag(self):
        raw = {
            "path": "/tmp/repo",
            "remote": "git@github.com:user/repo.git",
            "ignore": True,
        }
        repo = sync.parse_tracked_repo(raw)
        assert repo.ignore is True

    def test_ignore_defaults_to_false(self):
        raw = {"path": "/tmp/repo", "remote": "git@github.com:user/repo.git"}
        repo = sync.parse_tracked_repo(raw)
        assert repo.ignore is False


class TestCreateReposFile:
    def test_creates_file(self, tmp_path):
        output = tmp_path / "repos.yml"
        sync.create_repos_file(output)
        assert output.exists()
        content = output.read_text()
        assert "repos:" in content

    def test_raises_if_exists(self, tmp_path):
        existing = tmp_path / "repos.yml"
        existing.write_text("existing")
        with pytest.raises(FileExistsError):
            sync.create_repos_file(existing)

    def test_creates_parent_dirs(self, tmp_path):
        nested = tmp_path / "nested" / "dir" / "repos.yml"
        sync.create_repos_file(nested)
        assert nested.exists()


class TestSyncRepo:
    def test_clones_missing_repo(self, tracked_repo):
        with patch.object(sync, "clone_repo") as mock_clone:
            mock_clone.return_value = sync.SyncRepoResult(
                repo=tracked_repo,
                action=SyncAction.CLONED,
                message="Cloned",
            )
            result = sync.sync_repo(tracked_repo)
            assert result.action == SyncAction.CLONED

    def test_handles_existing_repo(self, temp_git_repo, tracked_repo):
        tracked_repo.path = temp_git_repo
        with patch.object(sync, "handle_existing_repo") as mock_handle:
            mock_handle.return_value = sync.SyncRepoResult(
                repo=tracked_repo,
                action=SyncAction.SKIPPED,
                message="Already exists",
            )
            result = sync.sync_repo(tracked_repo)
            mock_handle.assert_called_once()


class TestHandleExistingRepo:
    def test_skips_when_no_pull(self, temp_git_repo):
        repo = TrackedRepo(
            path=temp_git_repo,
            remote="git@github.com:user/repo.git",
        )
        result = sync.handle_existing_repo(repo, pull_existing=False)
        assert result.action == SyncAction.SKIPPED
        assert result.message == "Already exists"

    def test_error_when_not_git_repo(self, tmp_path):
        not_git = tmp_path / "not-git"
        not_git.mkdir()
        repo = TrackedRepo(path=not_git, remote="git@github.com:user/repo.git")
        result = sync.handle_existing_repo(repo, pull_existing=True)
        assert result.action == SyncAction.ERROR
        assert "not a git repo" in result.message

    def test_skips_when_up_to_date(self, temp_git_repo):
        repo = TrackedRepo(
            path=temp_git_repo,
            remote="git@github.com:user/repo.git",
        )
        with patch("git_repo_checker.sync.git_ops") as mock_git:
            mock_git.fetch_repo.return_value = True
            mock_git.get_remote_status.return_value = (0, 0)
            result = sync.handle_existing_repo(repo, pull_existing=True)
            assert result.action == SyncAction.SKIPPED
            assert "up to date" in result.message


class TestCloneRepo:
    def test_clones_successfully(self, tracked_repo):
        with patch("git_repo_checker.sync.git_ops") as mock_git:
            mock_git.clone_repo.return_value = PullResult(
                path=tracked_repo.path,
                success=True,
                message="Cloned main branch",
            )
            result = sync.clone_repo(tracked_repo)
            assert result.action == SyncAction.CLONED

    def test_handles_clone_failure(self, tracked_repo):
        with patch("git_repo_checker.sync.git_ops") as mock_git:
            mock_git.clone_repo.return_value = PullResult(
                path=tracked_repo.path,
                success=False,
                message="Network error",
            )
            result = sync.clone_repo(tracked_repo)
            assert result.action == SyncAction.ERROR
            assert "Clone failed" in result.message


class TestSyncAll:
    def test_syncs_multiple_repos(self, tmp_path):
        repos = [
            TrackedRepo(path=tmp_path / "repo1", remote="git@github.com:u/r1.git"),
            TrackedRepo(path=tmp_path / "repo2", remote="git@github.com:u/r2.git"),
        ]

        with patch.object(sync, "sync_repo") as mock_sync:
            mock_sync.side_effect = [
                sync.SyncRepoResult(
                    repo=repos[0], action=SyncAction.CLONED, message="Cloned"
                ),
                sync.SyncRepoResult(
                    repo=repos[1], action=SyncAction.SKIPPED, message="Skipped"
                ),
            ]
            result = sync.sync_all(repos)
            assert result.cloned == 1
            assert result.skipped == 1
            assert result.pulled == 0
            assert result.errors == 0
            assert len(result.results) == 2

    def test_counts_errors(self, tmp_path):
        repos = [
            TrackedRepo(path=tmp_path / "repo1", remote="git@github.com:u/r1.git"),
        ]

        with patch.object(sync, "sync_repo") as mock_sync:
            mock_sync.return_value = sync.SyncRepoResult(
                repo=repos[0], action=SyncAction.ERROR, message="Failed"
            )
            result = sync.sync_all(repos)
            assert result.errors == 1

    def test_skips_ignored_repos(self, tmp_path):
        repos = [
            TrackedRepo(
                path=tmp_path / "repo1",
                remote="git@github.com:u/r1.git",
                ignore=True,
            ),
            TrackedRepo(path=tmp_path / "repo2", remote="git@github.com:u/r2.git"),
        ]

        with patch.object(sync, "sync_repo") as mock_sync:
            mock_sync.return_value = sync.SyncRepoResult(
                repo=repos[1], action=SyncAction.CLONED, message="Cloned"
            )
            result = sync.sync_all(repos)
            assert result.skipped == 1
            assert result.cloned == 1
            # sync_repo should only be called once (for non-ignored repo)
            assert mock_sync.call_count == 1

    def test_ignored_repo_message(self, tmp_path):
        repos = [
            TrackedRepo(
                path=tmp_path / "repo1",
                remote="git@github.com:u/r1.git",
                ignore=True,
            ),
        ]

        result = sync.sync_all(repos)
        assert result.skipped == 1
        assert result.results[0].message == "Ignored"
