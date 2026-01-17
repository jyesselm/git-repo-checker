"""Tests for github_ops module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from git_repo_checker import github_ops
from git_repo_checker.models import CIStatus


class TestParseGithubUrl:
    def test_parses_ssh_url(self):
        url = "git@github.com:owner/repo.git"
        result = github_ops.parse_github_url(url)
        assert result == "owner/repo"

    def test_parses_ssh_url_no_git_suffix(self):
        url = "git@github.com:owner/repo"
        result = github_ops.parse_github_url(url)
        assert result == "owner/repo"

    def test_parses_https_url(self):
        url = "https://github.com/owner/repo.git"
        result = github_ops.parse_github_url(url)
        assert result == "owner/repo"

    def test_parses_https_url_no_git_suffix(self):
        url = "https://github.com/owner/repo"
        result = github_ops.parse_github_url(url)
        assert result == "owner/repo"

    def test_returns_none_for_non_github(self):
        url = "git@gitlab.com:owner/repo.git"
        result = github_ops.parse_github_url(url)
        assert result is None

    def test_returns_none_for_bitbucket(self):
        url = "https://bitbucket.org/owner/repo.git"
        result = github_ops.parse_github_url(url)
        assert result is None


class TestParseWorkflowResponse:
    def test_parses_passing(self):
        response = '[{"status": "completed", "conclusion": "success"}]'
        result = github_ops.parse_workflow_response(response)
        assert result == CIStatus.PASSING

    def test_parses_failing(self):
        response = '[{"status": "completed", "conclusion": "failure"}]'
        result = github_ops.parse_workflow_response(response)
        assert result == CIStatus.FAILING

    def test_parses_pending(self):
        response = '[{"status": "in_progress", "conclusion": null}]'
        result = github_ops.parse_workflow_response(response)
        assert result == CIStatus.PENDING

    def test_parses_queued(self):
        response = '[{"status": "queued", "conclusion": null}]'
        result = github_ops.parse_workflow_response(response)
        assert result == CIStatus.PENDING

    def test_empty_response_no_workflows(self):
        response = "[]"
        result = github_ops.parse_workflow_response(response)
        assert result == CIStatus.NO_WORKFLOWS

    def test_invalid_json_unknown(self):
        response = "not json"
        result = github_ops.parse_workflow_response(response)
        assert result == CIStatus.UNKNOWN

    def test_parses_cancelled(self):
        response = '[{"status": "completed", "conclusion": "cancelled"}]'
        result = github_ops.parse_workflow_response(response)
        assert result == CIStatus.FAILING


class TestIsGhAvailable:
    def test_returns_true_when_available(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert github_ops.is_gh_available() is True

    def test_returns_false_when_not_available(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            assert github_ops.is_gh_available() is False

    def test_returns_false_on_os_error(self):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = OSError("Not found")
            assert github_ops.is_gh_available() is False


class TestGetGithubRemote:
    def test_returns_slug_for_github_repo(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="git@github.com:owner/repo.git\n"
            )
            result = github_ops.get_github_remote(tmp_path)
            assert result == "owner/repo"

    def test_returns_none_for_non_github(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="git@gitlab.com:owner/repo.git\n"
            )
            result = github_ops.get_github_remote(tmp_path)
            assert result is None

    def test_returns_none_on_error(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            result = github_ops.get_github_remote(tmp_path)
            assert result is None


class TestQueryWorkflowStatus:
    def test_returns_status_from_gh(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout='[{"status": "completed", "conclusion": "success"}]'
            )
            result = github_ops.query_workflow_status("owner/repo")
            assert result == CIStatus.PASSING

    def test_returns_unknown_on_error(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            result = github_ops.query_workflow_status("owner/repo")
            assert result == CIStatus.UNKNOWN


class TestGetCiStatus:
    def test_returns_unknown_when_gh_not_available(self, tmp_path):
        with patch.object(github_ops, "is_gh_available", return_value=False):
            result = github_ops.get_ci_status(tmp_path)
            assert result == CIStatus.UNKNOWN

    def test_returns_unknown_for_non_github_repo(self, tmp_path):
        with patch.object(github_ops, "is_gh_available", return_value=True):
            with patch.object(github_ops, "get_github_remote", return_value=None):
                result = github_ops.get_ci_status(tmp_path)
                assert result == CIStatus.UNKNOWN

    def test_returns_status_for_github_repo(self, tmp_path):
        with patch.object(github_ops, "is_gh_available", return_value=True):
            with patch.object(github_ops, "get_github_remote", return_value="owner/repo"):
                with patch.object(
                    github_ops, "query_workflow_status", return_value=CIStatus.PASSING
                ):
                    result = github_ops.get_ci_status(tmp_path)
                    assert result == CIStatus.PASSING
