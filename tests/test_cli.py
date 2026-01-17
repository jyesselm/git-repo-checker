"""Tests for CLI module."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from git_repo_checker.cli import app
from git_repo_checker.models import (
    RepoInfo,
    RepoStatus,
    ScanResult,
    SyncAction,
    SyncRepoResult,
    SyncResult,
    TrackedRepo,
)

runner = CliRunner()


class TestMainCommand:
    def test_shows_error_without_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app)
        assert result.exit_code == 1
        assert "Error" in result.stdout or "config" in result.stdout.lower()

    def test_runs_with_config(self, sample_config_yaml, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        with patch("git_repo_checker.cli.scan_and_analyze") as mock_scan:
            mock_scan.return_value = ScanResult(repos=[], total_scanned=0)
            result = runner.invoke(app, ["--config", str(sample_config_yaml)])
            assert result.exit_code == 0


class TestScanCommand:
    def test_scan_with_paths(self, temp_git_repo, sample_config_yaml):
        result = runner.invoke(
            app,
            ["scan", str(temp_git_repo.parent), "--config", str(sample_config_yaml)],
        )
        # Should complete without error
        assert result.exit_code == 0

    def test_scan_no_pull_flag(self, sample_config_yaml, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch("git_repo_checker.cli.scan_and_analyze") as mock_scan:
            mock_scan.return_value = ScanResult(repos=[], total_scanned=0)
            result = runner.invoke(
                app,
                ["scan", "--no-pull", "--config", str(sample_config_yaml)],
            )
            assert result.exit_code == 0
            # Check that auto_pull was disabled
            call_args = mock_scan.call_args
            assert call_args[1]["auto_pull"] is False

    def test_scan_warnings_only(self, sample_config_yaml, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch("git_repo_checker.cli.scan_and_analyze") as mock_scan:
            mock_scan.return_value = ScanResult(repos=[], total_scanned=0)
            result = runner.invoke(
                app,
                ["scan", "--warnings-only", "--config", str(sample_config_yaml)],
            )
            assert result.exit_code == 0


class TestInitCommand:
    def test_creates_config_file(self, tmp_path):
        config_path = tmp_path / "new-config.yml"
        result = runner.invoke(app, ["init", str(config_path)])
        assert result.exit_code == 0
        assert config_path.exists()
        assert "Created" in result.stdout

    def test_fails_if_exists(self, tmp_path):
        config_path = tmp_path / "existing.yml"
        config_path.write_text("existing")
        result = runner.invoke(app, ["init", str(config_path)])
        assert result.exit_code == 1
        assert "Error" in result.stdout


class TestCheckCommand:
    def test_checks_single_repo(self, temp_git_repo):
        result = runner.invoke(app, ["check", str(temp_git_repo)])
        assert result.exit_code == 0

    def test_fails_for_non_repo(self, tmp_path):
        result = runner.invoke(app, ["check", str(tmp_path)])
        assert result.exit_code == 1
        assert "Not a git repository" in result.stdout

    def test_verbose_output(self, temp_git_repo):
        result = runner.invoke(app, ["check", str(temp_git_repo), "--verbose"])
        assert result.exit_code == 0


class TestGetConfig:
    def test_applies_verbose_flag(self, sample_config_yaml):
        from git_repo_checker.cli import get_config

        config = get_config(sample_config_yaml, verbose=True, quiet=False)
        assert config.output.verbosity == "verbose"

    def test_applies_quiet_flag(self, sample_config_yaml):
        from git_repo_checker.cli import get_config

        config = get_config(sample_config_yaml, verbose=False, quiet=True)
        assert config.output.verbosity == "quiet"

    def test_raises_without_config(self, tmp_path, monkeypatch):
        from git_repo_checker.cli import get_config

        monkeypatch.chdir(tmp_path)
        with pytest.raises(FileNotFoundError):
            get_config(None, verbose=False, quiet=False)


class TestSyncCommand:
    def test_init_creates_repos_file(self, tmp_path):
        repos_path = tmp_path / "repos.yml"
        result = runner.invoke(app, ["sync", "--init", "-r", str(repos_path)])
        assert result.exit_code == 0
        assert repos_path.exists()
        assert "Created" in result.stdout

    def test_init_fails_if_exists(self, tmp_path):
        repos_path = tmp_path / "repos.yml"
        repos_path.write_text("existing")
        result = runner.invoke(app, ["sync", "--init", "-r", str(repos_path)])
        assert result.exit_code == 1
        assert "Error" in result.stdout

    def test_sync_no_repos_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["sync"])
        assert result.exit_code == 1
        assert "Error" in result.stdout

    def test_sync_empty_repos(self, tmp_path):
        repos_path = tmp_path / "repos.yml"
        repos_path.write_text("repos: []")
        result = runner.invoke(app, ["sync", "-r", str(repos_path)])
        assert result.exit_code == 0
        assert "No repositories" in result.stdout

    def test_sync_with_repos(self, tmp_path):
        repos_path = tmp_path / "repos.yml"
        repos_path.write_text(
            f"""\
repos:
  - path: {tmp_path}/repo1
    remote: git@github.com:u/r.git
"""
        )
        with patch("git_repo_checker.cli.sync_module.sync_all") as mock_sync:
            mock_sync.return_value = SyncResult(
                results=[
                    SyncRepoResult(
                        repo=TrackedRepo(path=tmp_path / "repo1", remote="git@github.com:u/r.git"),
                        action=SyncAction.CLONED,
                        message="Cloned",
                    )
                ],
                cloned=1,
            )
            result = runner.invoke(app, ["sync", "-r", str(repos_path)])
            assert result.exit_code == 0
            assert "Syncing" in result.stdout

    def test_sync_quiet_mode(self, tmp_path):
        repos_path = tmp_path / "repos.yml"
        repos_path.write_text(
            f"""\
repos:
  - path: {tmp_path}/repo1
    remote: git@github.com:u/r.git
"""
        )
        with patch("git_repo_checker.cli.sync_module.sync_all") as mock_sync:
            mock_sync.return_value = SyncResult(
                results=[
                    SyncRepoResult(
                        repo=TrackedRepo(path=tmp_path / "repo1", remote="git@github.com:u/r.git"),
                        action=SyncAction.SKIPPED,
                        message="Up to date",
                    )
                ],
                skipped=1,
            )
            result = runner.invoke(app, ["sync", "-r", str(repos_path), "-q"])
            assert result.exit_code == 0

    def test_sync_shows_errors(self, tmp_path):
        repos_path = tmp_path / "repos.yml"
        repos_path.write_text(
            f"""\
repos:
  - path: {tmp_path}/repo1
    remote: git@github.com:u/r.git
"""
        )
        with patch("git_repo_checker.cli.sync_module.sync_all") as mock_sync:
            mock_sync.return_value = SyncResult(
                results=[
                    SyncRepoResult(
                        repo=TrackedRepo(path=tmp_path / "repo1", remote="git@github.com:u/r.git"),
                        action=SyncAction.ERROR,
                        message="Network error",
                    )
                ],
                errors=1,
            )
            result = runner.invoke(app, ["sync", "-r", str(repos_path)])
            assert result.exit_code == 0
            assert "error" in result.stdout.lower()

    def test_sync_shows_pulled(self, tmp_path):
        repos_path = tmp_path / "repos.yml"
        repos_path.write_text(
            f"""\
repos:
  - path: {tmp_path}/repo1
    remote: git@github.com:u/r.git
"""
        )
        with patch("git_repo_checker.cli.sync_module.sync_all") as mock_sync:
            mock_sync.return_value = SyncResult(
                results=[
                    SyncRepoResult(
                        repo=TrackedRepo(path=tmp_path / "repo1", remote="git@github.com:u/r.git"),
                        action=SyncAction.PULLED,
                        message="Pulled 3 files",
                    )
                ],
                pulled=1,
            )
            result = runner.invoke(app, ["sync", "-r", str(repos_path)])
            assert result.exit_code == 0

    def test_sync_dry_run(self, tmp_path):
        repos_path = tmp_path / "repos.yml"
        repos_path.write_text(
            f"""\
repos:
  - path: {tmp_path}/repo1
    remote: git@github.com:u/r.git
"""
        )
        result = runner.invoke(app, ["sync", "-r", str(repos_path), "--dry-run"])
        assert result.exit_code == 0
        assert "Dry run" in result.stdout
        assert "Would clone" in result.stdout


class TestScanJsonOutput:
    def test_json_output_flag(self, sample_config_yaml, tmp_path):
        with patch("git_repo_checker.cli.scan_and_analyze") as mock_scan:
            mock_scan.return_value = ScanResult(
                repos=[
                    RepoInfo(
                        path=tmp_path / "repo1",
                        branch="main",
                        status=RepoStatus.CLEAN,
                    )
                ],
                total_scanned=1,
            )
            result = runner.invoke(
                app,
                ["scan", "--json", "--config", str(sample_config_yaml)],
            )
            assert result.exit_code == 0
            data = json.loads(result.stdout)
            assert data["total_scanned"] == 1
            assert len(data["repos"]) == 1
            assert data["repos"][0]["status"] == "clean"

    def test_json_includes_all_fields(self, sample_config_yaml, tmp_path):
        with patch("git_repo_checker.cli.scan_and_analyze") as mock_scan:
            mock_scan.return_value = ScanResult(
                repos=[
                    RepoInfo(
                        path=tmp_path / "repo1",
                        branch="main",
                        status=RepoStatus.DIRTY,
                        changed_files=3,
                        has_stash=True,
                    )
                ],
                total_scanned=1,
            )
            result = runner.invoke(
                app,
                ["scan", "--json", "--config", str(sample_config_yaml)],
            )
            data = json.loads(result.stdout)
            repo = data["repos"][0]
            assert "path" in repo
            assert "branch" in repo
            assert "status" in repo
            assert "has_stash" in repo
            assert repo["has_stash"] is True


class TestScanStatusFilter:
    def test_filters_by_single_status(self, sample_config_yaml, tmp_path):
        with patch("git_repo_checker.cli.scan_and_analyze") as mock_scan:
            mock_scan.return_value = ScanResult(
                repos=[
                    RepoInfo(
                        path=tmp_path / "repo1",
                        branch="main",
                        status=RepoStatus.CLEAN,
                    ),
                    RepoInfo(
                        path=tmp_path / "repo2",
                        branch="main",
                        status=RepoStatus.DIRTY,
                    ),
                ],
                total_scanned=2,
            )
            result = runner.invoke(
                app,
                ["scan", "--json", "--status", "dirty", "--config", str(sample_config_yaml)],
            )
            assert result.exit_code == 0
            data = json.loads(result.stdout)
            assert len(data["repos"]) == 1
            assert data["repos"][0]["status"] == "dirty"

    def test_filters_by_multiple_statuses(self, sample_config_yaml, tmp_path):
        with patch("git_repo_checker.cli.scan_and_analyze") as mock_scan:
            mock_scan.return_value = ScanResult(
                repos=[
                    RepoInfo(
                        path=tmp_path / "repo1",
                        branch="main",
                        status=RepoStatus.CLEAN,
                    ),
                    RepoInfo(
                        path=tmp_path / "repo2",
                        branch="main",
                        status=RepoStatus.DIRTY,
                    ),
                    RepoInfo(
                        path=tmp_path / "repo3",
                        branch="main",
                        status=RepoStatus.AHEAD,
                    ),
                ],
                total_scanned=3,
            )
            result = runner.invoke(
                app,
                [
                    "scan",
                    "--json",
                    "--status",
                    "dirty,ahead",
                    "--config",
                    str(sample_config_yaml),
                ],
            )
            assert result.exit_code == 0
            data = json.loads(result.stdout)
            assert len(data["repos"]) == 2
            statuses = {r["status"] for r in data["repos"]}
            assert statuses == {"dirty", "ahead"}


class TestScanCiFlag:
    def test_ci_flag_adds_status(self, sample_config_yaml, tmp_path):
        with patch("git_repo_checker.cli.scan_and_analyze") as mock_scan:
            mock_scan.return_value = ScanResult(
                repos=[
                    RepoInfo(
                        path=tmp_path / "repo1",
                        branch="main",
                        status=RepoStatus.CLEAN,
                    )
                ],
                total_scanned=1,
            )
            with patch("git_repo_checker.cli._add_ci_status") as mock_ci:
                result = runner.invoke(
                    app,
                    ["scan", "--ci", "--config", str(sample_config_yaml)],
                )
                assert result.exit_code == 0
                mock_ci.assert_called_once()


class TestSyncDryRunDetails:
    def test_dry_run_shows_pull_targets(self, tmp_path):
        # Create a directory that will be treated as existing repo
        repo_dir = tmp_path / "existing_repo"
        repo_dir.mkdir()

        repos_path = tmp_path / "repos.yml"
        repos_path.write_text(
            f"""\
repos:
  - path: {repo_dir}
    remote: git@github.com:u/r.git
"""
        )
        result = runner.invoke(app, ["sync", "-r", str(repos_path), "--dry-run"])
        assert result.exit_code == 0
        assert "check" in result.stdout.lower() or "pull" in result.stdout.lower()

    def test_dry_run_shows_ignored(self, tmp_path):
        repos_path = tmp_path / "repos.yml"
        repos_path.write_text(
            f"""\
repos:
  - path: {tmp_path}/repo1
    remote: git@github.com:u/r.git
    ignore: true
"""
        )
        result = runner.invoke(app, ["sync", "-r", str(repos_path), "--dry-run"])
        assert result.exit_code == 0
        assert "skip" in result.stdout.lower()


class TestFilterByStatusHelper:
    def test_warns_on_invalid_status(self, sample_config_yaml, tmp_path):
        with patch("git_repo_checker.cli.scan_and_analyze") as mock_scan:
            mock_scan.return_value = ScanResult(
                repos=[
                    RepoInfo(
                        path=tmp_path / "repo1",
                        branch="main",
                        status=RepoStatus.CLEAN,
                    )
                ],
                total_scanned=1,
            )
            result = runner.invoke(
                app,
                ["scan", "--status", "invalid_status", "--config", str(sample_config_yaml)],
            )
            assert result.exit_code == 0
            assert "Warning" in result.stdout or "unknown" in result.stdout.lower()
