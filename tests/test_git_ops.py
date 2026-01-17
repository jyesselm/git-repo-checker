"""Tests for git_ops module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from git_repo_checker import git_ops
from git_repo_checker.models import RepoStatus


class TestRunGitCommand:
    def test_runs_command_successfully(self, temp_git_repo):
        result = git_ops.run_git_command(temp_git_repo, ["status"])
        assert result.returncode == 0

    def test_raises_on_timeout(self, temp_git_repo):
        with patch("subprocess.run") as mock_run:
            import subprocess

            mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=1)
            with pytest.raises(git_ops.GitError) as exc_info:
                git_ops.run_git_command(temp_git_repo, ["status"], timeout=1)
            assert "timed out" in str(exc_info.value)

    def test_raises_on_os_error(self, temp_git_repo):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = OSError("Command not found")
            with pytest.raises(git_ops.GitError):
                git_ops.run_git_command(temp_git_repo, ["status"])


class TestGetCurrentBranch:
    def test_returns_branch_name(self, temp_git_repo):
        branch = git_ops.get_current_branch(temp_git_repo)
        # Git init creates master or main depending on config
        assert branch in ["master", "main"]

    def test_returns_head_when_detached(self, temp_git_repo):
        import subprocess

        # Get current commit hash and checkout detached
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=temp_git_repo,
            capture_output=True,
            text=True,
        )
        commit_hash = result.stdout.strip()
        subprocess.run(
            ["git", "checkout", commit_hash],
            cwd=temp_git_repo,
            capture_output=True,
        )

        branch = git_ops.get_current_branch(temp_git_repo)
        assert branch == "HEAD"


class TestGetRepoStatus:
    def test_clean_repo(self, temp_git_repo):
        status, changed, untracked = git_ops.get_repo_status(temp_git_repo)
        assert status == RepoStatus.CLEAN
        assert changed == 0
        assert untracked == 0

    def test_dirty_repo(self, temp_git_repo_dirty):
        status, changed, untracked = git_ops.get_repo_status(temp_git_repo_dirty)
        assert status == RepoStatus.DIRTY
        assert changed >= 1

    def test_untracked_only(self, temp_git_repo_untracked):
        status, changed, untracked = git_ops.get_repo_status(temp_git_repo_untracked)
        assert status == RepoStatus.UNTRACKED
        assert changed == 0
        assert untracked >= 1


class TestHasUpstream:
    def test_no_upstream(self, temp_git_repo):
        # Local repo without remote
        assert git_ops.has_upstream(temp_git_repo) is False


class TestGetRemoteStatus:
    def test_no_upstream_returns_zeros(self, temp_git_repo):
        ahead, behind = git_ops.get_remote_status(temp_git_repo)
        assert ahead == 0
        assert behind == 0


class TestDetermineRemoteStatus:
    def test_clean_stays_clean(self):
        result = git_ops.determine_remote_status(0, 0, RepoStatus.CLEAN)
        assert result == RepoStatus.CLEAN

    def test_dirty_stays_dirty(self):
        result = git_ops.determine_remote_status(1, 0, RepoStatus.DIRTY)
        assert result == RepoStatus.DIRTY

    def test_ahead_when_only_ahead(self):
        result = git_ops.determine_remote_status(2, 0, RepoStatus.CLEAN)
        assert result == RepoStatus.AHEAD

    def test_behind_when_only_behind(self):
        result = git_ops.determine_remote_status(0, 3, RepoStatus.CLEAN)
        assert result == RepoStatus.BEHIND

    def test_diverged_when_both(self):
        result = git_ops.determine_remote_status(2, 3, RepoStatus.CLEAN)
        assert result == RepoStatus.DIVERGED


class TestPullRepo:
    def test_pull_no_remote(self, temp_git_repo):
        result = git_ops.pull_repo(temp_git_repo)
        # No remote configured, so pull should fail
        assert result.success is False

    def test_pull_result_structure(self, temp_git_repo):
        result = git_ops.pull_repo(temp_git_repo)
        assert result.path == temp_git_repo
        assert isinstance(result.message, str)


class TestParsePullFilesChanged:
    def test_parses_file_count(self):
        output = "Updating abc123..def456\nFast-forward\n 3 files changed"
        assert git_ops.parse_pull_files_changed(output) == 3

    def test_returns_zero_for_no_changes(self):
        output = "Already up to date."
        assert git_ops.parse_pull_files_changed(output) == 0


class TestFetchRepo:
    def test_fetch_no_remote_succeeds(self, temp_git_repo):
        # Git fetch with no remote still returns success (just nothing to fetch)
        result = git_ops.fetch_repo(temp_git_repo)
        assert result is True


class TestGitError:
    def test_stores_repo_path(self):
        path = Path("/tmp/repo")
        error = git_ops.GitError("test error", path)
        assert error.repo_path == path
        assert "test error" in str(error)


class TestGetRepoStatusError:
    def test_returns_error_on_failure(self, tmp_path):
        # Not a git repo, should return error
        status, changed, untracked = git_ops.get_repo_status(tmp_path)
        assert status == RepoStatus.ERROR
        assert changed == 0
        assert untracked == 0


class TestGetRemoteStatusWithMock:
    def test_returns_zeros_on_command_failure(self, temp_git_repo):
        with patch.object(git_ops, "has_upstream", return_value=True):
            with patch.object(git_ops, "run_git_command") as mock_cmd:
                mock_cmd.return_value = MagicMock(returncode=1, stdout="")
                ahead, behind = git_ops.get_remote_status(temp_git_repo)
                assert ahead == 0
                assert behind == 0

    def test_returns_zeros_on_invalid_output(self, temp_git_repo):
        with patch.object(git_ops, "has_upstream", return_value=True):
            with patch.object(git_ops, "run_git_command") as mock_cmd:
                mock_cmd.return_value = MagicMock(returncode=0, stdout="invalid")
                ahead, behind = git_ops.get_remote_status(temp_git_repo)
                assert ahead == 0
                assert behind == 0

    def test_returns_zeros_on_value_error(self, temp_git_repo):
        with patch.object(git_ops, "has_upstream", return_value=True):
            with patch.object(git_ops, "run_git_command") as mock_cmd:
                mock_cmd.return_value = MagicMock(returncode=0, stdout="not num")
                ahead, behind = git_ops.get_remote_status(temp_git_repo)
                assert ahead == 0
                assert behind == 0

    def test_parses_valid_output(self, temp_git_repo):
        with patch.object(git_ops, "has_upstream", return_value=True):
            with patch.object(git_ops, "run_git_command") as mock_cmd:
                mock_cmd.return_value = MagicMock(returncode=0, stdout="3\t5\n")
                ahead, behind = git_ops.get_remote_status(temp_git_repo)
                assert ahead == 5
                assert behind == 3


class TestPullRepoSuccess:
    def test_pull_already_up_to_date(self, temp_git_repo):
        with patch.object(git_ops, "run_git_command") as mock_cmd:
            mock_cmd.return_value = MagicMock(
                returncode=0,
                stdout="Already up to date.\n",
                stderr="",
            )
            result = git_ops.pull_repo(temp_git_repo)
            assert result.success is True
            assert result.message == "Already up to date"

    def test_pull_with_changes(self, temp_git_repo):
        with patch.object(git_ops, "run_git_command") as mock_cmd:
            mock_cmd.return_value = MagicMock(
                returncode=0,
                stdout="Updating abc..def\n3 files changed, 10 insertions(+)\n",
                stderr="",
            )
            result = git_ops.pull_repo(temp_git_repo)
            assert result.success is True
            assert result.message == "Pull successful"
            assert result.files_changed == 3
