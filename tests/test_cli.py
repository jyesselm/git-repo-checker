"""Tests for CLI module."""

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from git_repo_checker.cli import app
from git_repo_checker.models import ScanResult

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
