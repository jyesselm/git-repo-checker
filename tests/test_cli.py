"""Tests for CLI module."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

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
from git_repo_checker.schedule import ScheduleStatus

runner = CliRunner()

# Patch target for auto_track_repos to prevent file writes in tests
_AUTO_TRACK = "git_repo_checker.cli.sync_module.auto_track_repos"
_NO_OP_TRACK = (_AUTO_TRACK, MagicMock(return_value=(0, 0, [])))


def _scan_result_with_repos(tmp_path: Path) -> ScanResult:
    return ScanResult(
        repos=[RepoInfo(path=tmp_path / "repo1", branch="main", status=RepoStatus.CLEAN)],
        total_scanned=1,
    )


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
        with patch(_AUTO_TRACK, return_value=(0, 0, [])):
            result = runner.invoke(
                app,
                ["scan", str(temp_git_repo.parent), "--config", str(sample_config_yaml)],
            )
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


class TestAddCommand:
    def test_adds_repo(self, tmp_path):
        target = tmp_path / "repos.yml"
        with patch("git_repo_checker.cli.sync_module.add_repo") as mock_add:
            mock_add.return_value = ("added", "git@github.com:u/r.git")
            result = runner.invoke(
                app, ["add", str(tmp_path / "repo"), "--repos", str(target)]
            )
        assert result.exit_code == 0
        assert "Added" in result.stdout

    def test_defaults_to_current_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch("git_repo_checker.cli.sync_module.add_repo") as mock_add:
            mock_add.return_value = ("added", "git@github.com:u/r.git")
            result = runner.invoke(app, ["add", "--repos", str(tmp_path / "repos.yml")])
        assert result.exit_code == 0
        called_path = mock_add.call_args.args[0]
        assert Path(called_path) == Path(".")

    def test_fails_for_non_git(self, tmp_path):
        with patch("git_repo_checker.cli.sync_module.add_repo") as mock_add:
            mock_add.return_value = ("not_git", None)
            result = runner.invoke(app, ["add", str(tmp_path)])
        assert result.exit_code == 1
        assert "Not a git repository" in result.stdout

    def test_fails_for_no_remote(self, tmp_path):
        with patch("git_repo_checker.cli.sync_module.add_repo") as mock_add:
            mock_add.return_value = ("no_remote", None)
            result = runner.invoke(app, ["add", str(tmp_path)])
        assert result.exit_code == 1
        assert "remote" in result.stdout.lower()

    def test_reports_collision(self, tmp_path):
        with patch("git_repo_checker.cli.sync_module.add_repo") as mock_add:
            mock_add.return_value = ("collision", "git@github.com:u/other.git")
            result = runner.invoke(app, ["add", str(tmp_path)])
        assert result.exit_code == 1
        assert "already tracked" in result.stdout.lower()

    def test_already_tracked_succeeds(self, tmp_path):
        with patch("git_repo_checker.cli.sync_module.add_repo") as mock_add:
            mock_add.return_value = ("exists", "git@github.com:u/r.git")
            result = runner.invoke(app, ["add", str(tmp_path)])
        assert result.exit_code == 0
        assert "Already tracked" in result.stdout

    def test_grcignore_marker_reported(self, tmp_path):
        with patch("git_repo_checker.cli.sync_module.add_repo") as mock_add:
            mock_add.return_value = ("ignored", None)
            result = runner.invoke(app, ["add", str(tmp_path)])
        assert result.exit_code == 0
        assert ".grcignore" in result.stdout


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
        with patch("git_repo_checker.sync.DEFAULT_REPOS_LOCATIONS", [Path("./repos.yml")]):
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
            mock_scan.return_value = _scan_result_with_repos(tmp_path)
            with patch(_AUTO_TRACK, return_value=(0, 0, [])):
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
            with patch(_AUTO_TRACK, return_value=(0, 0, [])):
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
                    RepoInfo(path=tmp_path / "repo1", branch="main", status=RepoStatus.CLEAN),
                    RepoInfo(path=tmp_path / "repo2", branch="main", status=RepoStatus.DIRTY),
                ],
                total_scanned=2,
            )
            with patch(_AUTO_TRACK, return_value=(0, 0, [])):
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
                    RepoInfo(path=tmp_path / "repo1", branch="main", status=RepoStatus.CLEAN),
                    RepoInfo(path=tmp_path / "repo2", branch="main", status=RepoStatus.DIRTY),
                    RepoInfo(path=tmp_path / "repo3", branch="main", status=RepoStatus.AHEAD),
                ],
                total_scanned=3,
            )
            with patch(_AUTO_TRACK, return_value=(0, 0, [])):
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
            mock_scan.return_value = _scan_result_with_repos(tmp_path)
            with patch("git_repo_checker.cli._add_ci_status") as mock_ci:
                with patch(_AUTO_TRACK, return_value=(0, 0, [])):
                    result = runner.invoke(
                        app,
                        ["scan", "--ci", "--config", str(sample_config_yaml)],
                    )
                    assert result.exit_code == 0
                    mock_ci.assert_called_once()


class TestSyncDryRunDetails:
    def test_dry_run_shows_pull_targets(self, tmp_path):
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
                repos=[RepoInfo(path=tmp_path / "repo1", branch="main", status=RepoStatus.CLEAN)],
                total_scanned=1,
            )
            with patch(_AUTO_TRACK, return_value=(0, 0, [])):
                result = runner.invoke(
                    app,
                    ["scan", "--status", "invalid_status", "--config", str(sample_config_yaml)],
                )
        assert result.exit_code == 0
        assert "Warning" in result.stdout or "unknown" in result.stdout.lower()


class TestScanAutoTrack:
    def test_auto_track_runs_by_default(self, sample_config_yaml, tmp_path):
        with patch("git_repo_checker.cli.scan_and_analyze") as mock_scan:
            mock_scan.return_value = _scan_result_with_repos(tmp_path)
            with patch(_AUTO_TRACK, return_value=(1, 0, [])) as mock_track:
                with patch(
                    "git_repo_checker.cli.sync_module.default_repos_target",
                    return_value=tmp_path / "repos.yml",
                ):
                    result = runner.invoke(
                        app,
                        ["scan", "--config", str(sample_config_yaml)],
                    )
            assert result.exit_code == 0
            mock_track.assert_called_once()
            assert "Tracked" in result.stdout

    def test_no_track_flag_disables(self, sample_config_yaml, tmp_path):
        with patch("git_repo_checker.cli.scan_and_analyze") as mock_scan:
            mock_scan.return_value = _scan_result_with_repos(tmp_path)
            with patch(_AUTO_TRACK) as mock_track:
                result = runner.invoke(
                    app,
                    ["scan", "--no-track", "--config", str(sample_config_yaml)],
                )
        assert result.exit_code == 0
        mock_track.assert_not_called()

    def test_export_repos_still_works(self, sample_config_yaml, tmp_path):
        export_path = tmp_path / "out.yml"
        with patch("git_repo_checker.cli.scan_and_analyze") as mock_scan:
            mock_scan.return_value = _scan_result_with_repos(tmp_path)
            with patch(
                "git_repo_checker.cli.sync_module.export_repos_to_file",
                return_value=(1, 0, []),
            ) as mock_export:
                with patch(_AUTO_TRACK) as mock_track:
                    result = runner.invoke(
                        app,
                        [
                            "scan",
                            "--export-repos",
                            str(export_path),
                            "--config",
                            str(sample_config_yaml),
                        ],
                    )
        assert result.exit_code == 0
        mock_export.assert_called_once()
        mock_track.assert_not_called()

    def test_auto_track_silent_in_json(self, sample_config_yaml, tmp_path):
        with patch("git_repo_checker.cli.scan_and_analyze") as mock_scan:
            mock_scan.return_value = _scan_result_with_repos(tmp_path)
            with patch(_AUTO_TRACK, return_value=(1, 0, [])):
                with patch(
                    "git_repo_checker.cli.sync_module.default_repos_target",
                    return_value=tmp_path / "repos.yml",
                ):
                    result = runner.invoke(
                        app,
                        ["scan", "--json", "--config", str(sample_config_yaml)],
                    )
        assert result.exit_code == 0
        # Should be valid JSON with no human text mixed in
        data = json.loads(result.stdout)
        assert "total_scanned" in data
        assert "Tracked" not in result.stdout

    def test_auto_track_skipped_when_no_repos(self, sample_config_yaml, tmp_path):
        with patch("git_repo_checker.cli.scan_and_analyze") as mock_scan:
            mock_scan.return_value = ScanResult(repos=[], total_scanned=0)
            with patch(_AUTO_TRACK) as mock_track:
                result = runner.invoke(
                    app,
                    ["scan", "--config", str(sample_config_yaml)],
                )
        assert result.exit_code == 0
        mock_track.assert_not_called()


class TestScanErrorsOutput:
    def test_json_includes_scan_errors(self, sample_config_yaml, tmp_path):
        with patch("git_repo_checker.cli.scan_and_analyze") as mock_scan:
            mock_scan.return_value = ScanResult(
                repos=[RepoInfo(path=tmp_path / "r", branch="main", status=RepoStatus.CLEAN)],
                scan_errors=["Permission denied: /x"],
                total_scanned=1,
            )
            with patch(_AUTO_TRACK, return_value=(0, 0, [])):
                result = runner.invoke(
                    app,
                    ["scan", "--json", "--config", str(sample_config_yaml)],
                )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["scan_errors"] == ["Permission denied: /x"]

    def test_human_output_shows_scan_warnings(self, sample_config_yaml, tmp_path):
        with patch("git_repo_checker.cli.scan_and_analyze") as mock_scan:
            mock_scan.return_value = ScanResult(
                repos=[RepoInfo(path=tmp_path / "r", branch="main", status=RepoStatus.CLEAN)],
                scan_errors=["Permission denied: /x"],
                total_scanned=1,
            )
            with patch(_AUTO_TRACK, return_value=(0, 0, [])):
                result = runner.invoke(
                    app,
                    ["scan", "--config", str(sample_config_yaml)],
                )
        assert result.exit_code == 0
        assert "Scan warnings" in result.stdout


class TestScheduleCommand:
    def test_install_minutes(self, tmp_path):
        with patch("git_repo_checker.cli.schedule_module.install") as mock_install:
            mock_install.return_value = tmp_path / "test.plist"
            result = runner.invoke(
                app,
                ["schedule", "install", "--interval", "30", "--unit", "minutes"],
            )
        assert result.exit_code == 0
        mock_install.assert_called_once_with(1800, [])

    def test_install_seconds(self, tmp_path):
        with patch("git_repo_checker.cli.schedule_module.install") as mock_install:
            mock_install.return_value = tmp_path / "test.plist"
            result = runner.invoke(
                app,
                ["schedule", "install", "--interval", "90", "--unit", "seconds"],
            )
        assert result.exit_code == 0
        mock_install.assert_called_once_with(90, [])

    def test_install_rejects_bad_unit(self):
        result = runner.invoke(
            app,
            ["schedule", "install", "--interval", "5", "--unit", "hours"],
        )
        assert result.exit_code != 0

    def test_install_rejects_zero_interval(self, tmp_path):
        result = runner.invoke(
            app,
            ["schedule", "install", "--interval", "0", "--unit", "minutes"],
        )
        assert result.exit_code != 0

    def test_uninstall_reports_removed(self):
        with patch("git_repo_checker.cli.schedule_module.uninstall", return_value=True):
            result = runner.invoke(app, ["schedule", "uninstall"])
        assert result.exit_code == 0
        assert "Removed" in result.stdout

    def test_uninstall_reports_absent(self):
        with patch("git_repo_checker.cli.schedule_module.uninstall", return_value=False):
            result = runner.invoke(app, ["schedule", "uninstall"])
        assert result.exit_code == 0
        assert "Nothing" in result.stdout

    def test_status_not_installed(self):
        status = ScheduleStatus(
            installed=False,
            loaded=False,
            interval_seconds=None,
            plist_path=Path("/tmp/test.plist"),
        )
        with patch("git_repo_checker.cli.schedule_module.get_status", return_value=status):
            result = runner.invoke(app, ["schedule", "status"])
        assert result.exit_code == 0
        assert "not installed" in result.stdout.lower()

    def test_status_installed(self, tmp_path):
        plist = tmp_path / "test.plist"
        status = ScheduleStatus(
            installed=True,
            loaded=True,
            interval_seconds=3600,
            plist_path=plist,
            program_args=["/grc", "sync", "--quiet"],
        )
        with patch("git_repo_checker.cli.schedule_module.get_status", return_value=status):
            result = runner.invoke(app, ["schedule", "status"])
        assert result.exit_code == 0
        assert "3600" in result.stdout
        assert "test.plist" in result.stdout

    def test_install_with_repos_path(self, tmp_path):
        repos = tmp_path / "repos.yml"
        with patch("git_repo_checker.cli.schedule_module.install") as mock_install:
            mock_install.return_value = tmp_path / "test.plist"
            result = runner.invoke(
                app,
                ["schedule", "install", "--repos", str(repos)],
            )
        assert result.exit_code == 0
        mock_install.assert_called_once_with(3600, ["--repos", str(repos)])

    def test_install_runtime_error(self):
        with patch(
            "git_repo_checker.cli.schedule_module.install",
            side_effect=RuntimeError("launchctl failed"),
        ):
            result = runner.invoke(app, ["schedule", "install"])
        assert result.exit_code == 1
        assert "Error" in result.stdout

    def test_uninstall_runtime_error(self):
        with patch(
            "git_repo_checker.cli.schedule_module.uninstall",
            side_effect=RuntimeError("unload failed"),
        ):
            result = runner.invoke(app, ["schedule", "uninstall"])
        assert result.exit_code == 1
