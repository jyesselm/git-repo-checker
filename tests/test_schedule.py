"""Tests for schedule module."""

import plistlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from git_repo_checker import schedule


@pytest.fixture(autouse=True)
def patch_schedule_paths(tmp_path, monkeypatch):
    """Redirect LaunchAgents dir and plist path to tmp_path for all tests."""
    agents_dir = tmp_path / "LaunchAgents"
    plist = agents_dir / f"{schedule.LAUNCH_AGENT_LABEL}.plist"
    monkeypatch.setattr(schedule, "LAUNCH_AGENTS_DIR", agents_dir)
    monkeypatch.setattr(schedule, "PLIST_PATH", plist)
    return agents_dir, plist


class TestBuildPlist:
    def test_contains_label_and_interval(self):
        args = ["/usr/bin/grc", "sync", "--quiet"]
        xml = schedule.build_plist(3600, args)
        data = plistlib.loads(xml.encode())
        assert data["Label"] == schedule.LAUNCH_AGENT_LABEL
        assert data["StartInterval"] == 3600
        assert data["RunAtLoad"] is False

    def test_program_args_round_trip(self):
        args = ["/usr/bin/grc", "sync", "--quiet", "--repos", "/tmp/repos.yml"]
        xml = schedule.build_plist(60, args)
        data = plistlib.loads(xml.encode())
        assert data["ProgramArguments"] == args

    def test_log_paths_are_absolute(self):
        xml = schedule.build_plist(60, ["/grc"])
        data = plistlib.loads(xml.encode())
        assert data["StandardOutPath"].startswith("/")
        assert data["StandardErrorPath"].startswith("/")


class TestFindGrcExecutable:
    def test_returns_which_path(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/grc")
        result = schedule.find_grc_executable()
        assert result == "/usr/local/bin/grc"

    def test_raises_when_missing(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: None)
        with pytest.raises(RuntimeError, match="not found on PATH"):
            schedule.find_grc_executable()


class TestInstall:
    def test_writes_plist_and_loads(self, tmp_path, monkeypatch):
        monkeypatch.setattr(schedule, "find_grc_executable", lambda: "/usr/bin/grc")
        with (
            patch.object(schedule, "_launchctl_load") as mock_load,
            patch.object(schedule, "_launchctl_unload"),
        ):
            result = schedule.install(1800)

        assert result == schedule.PLIST_PATH
        assert schedule.PLIST_PATH.exists()

        with open(schedule.PLIST_PATH, "rb") as f:
            data = plistlib.load(f)

        assert data["StartInterval"] == 1800
        assert data["ProgramArguments"][1] == "sync"
        mock_load.assert_called_once_with(schedule.PLIST_PATH)

    def test_rejects_nonpositive_interval(self, monkeypatch):
        monkeypatch.setattr(schedule, "find_grc_executable", lambda: "/usr/bin/grc")
        with pytest.raises(ValueError):
            schedule.install(0)

    def test_rejects_negative_interval(self, monkeypatch):
        monkeypatch.setattr(schedule, "find_grc_executable", lambda: "/usr/bin/grc")
        with pytest.raises(ValueError):
            schedule.install(-5)

    def test_reload_when_already_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr(schedule, "find_grc_executable", lambda: "/usr/bin/grc")
        # Pre-create plist to simulate already-installed state
        schedule.PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        schedule.PLIST_PATH.write_text("existing")

        with (
            patch.object(schedule, "_launchctl_unload") as mock_unload,
            patch.object(schedule, "_launchctl_load"),
        ):
            schedule.install(900)

        mock_unload.assert_called_once_with(schedule.PLIST_PATH)

    def test_raises_when_load_fails(self, monkeypatch):
        monkeypatch.setattr(schedule, "find_grc_executable", lambda: "/usr/bin/grc")

        def _fail_load(plist):
            raise RuntimeError("launchctl failed")

        with (
            patch.object(schedule, "_launchctl_load", side_effect=_fail_load),
            patch.object(schedule, "_launchctl_unload"),
        ):
            with pytest.raises(RuntimeError, match="launchctl failed"):
                schedule.install(60)

    def test_passes_extra_args(self, monkeypatch):
        monkeypatch.setattr(schedule, "find_grc_executable", lambda: "/grc")
        with (
            patch.object(schedule, "_launchctl_load"),
            patch.object(schedule, "_launchctl_unload"),
        ):
            schedule.install(120, extra_args=["--repos", "/tmp/repos.yml"])

        with open(schedule.PLIST_PATH, "rb") as f:
            data = plistlib.load(f)
        assert "--repos" in data["ProgramArguments"]


class TestUninstall:
    def test_removes_existing_plist(self):
        schedule.PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        schedule.PLIST_PATH.write_text("plist content")

        with patch.object(schedule, "_launchctl_unload"):
            result = schedule.uninstall()

        assert result is True
        assert not schedule.PLIST_PATH.exists()

    def test_returns_false_when_absent(self):
        result = schedule.uninstall()
        assert result is False


class TestGetStatus:
    def test_reports_not_installed(self):
        status = schedule.get_status()
        assert status.installed is False
        assert status.loaded is False
        assert status.interval_seconds is None

    def test_reports_installed_and_loaded(self):
        schedule.PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        plist_dict = {
            "Label": schedule.LAUNCH_AGENT_LABEL,
            "ProgramArguments": ["/grc", "sync", "--quiet"],
            "StartInterval": 3600,
            "RunAtLoad": False,
            "StandardOutPath": "/tmp/out.log",
            "StandardErrorPath": "/tmp/err.log",
        }
        with open(schedule.PLIST_PATH, "wb") as f:
            plistlib.dump(plist_dict, f)

        with patch.object(schedule, "_launchctl_list_contains", return_value=True):
            status = schedule.get_status()

        assert status.installed is True
        assert status.loaded is True
        assert status.interval_seconds == 3600
        assert status.program_args[1] == "sync"

    def test_reports_installed_but_not_loaded(self):
        schedule.PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        plist_dict = {
            "Label": schedule.LAUNCH_AGENT_LABEL,
            "ProgramArguments": ["/grc", "sync"],
            "StartInterval": 60,
            "RunAtLoad": False,
            "StandardOutPath": "/tmp/out.log",
            "StandardErrorPath": "/tmp/err.log",
        }
        with open(schedule.PLIST_PATH, "wb") as f:
            plistlib.dump(plist_dict, f)

        with patch.object(schedule, "_launchctl_list_contains", return_value=False):
            status = schedule.get_status()

        assert status.installed is True
        assert status.loaded is False


class TestRunLaunchctl:
    def test_wraps_oserror(self):
        with patch("subprocess.run", side_effect=OSError("no launchctl")):
            with pytest.raises(RuntimeError, match="launchctl failed"):
                schedule._run_launchctl(["list"])

    def test_wraps_timeout(self):
        import subprocess

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("launchctl", 30)):
            with pytest.raises(RuntimeError, match="launchctl failed"):
                schedule._run_launchctl(["list"])

    def test_returns_result_on_success(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "output"
        with patch("subprocess.run", return_value=mock_result):
            result = schedule._run_launchctl(["list"])
        assert result.returncode == 0


class TestLaunchctlHelpers:
    def test_launchctl_load_raises_on_nonzero(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "load failed"
        with patch.object(schedule, "_run_launchctl", return_value=mock_result):
            with pytest.raises(RuntimeError, match="load failed"):
                schedule._launchctl_load(Path("/tmp/test.plist"))

    def test_launchctl_load_raises_with_fallback_msg(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = ""
        with patch.object(schedule, "_run_launchctl", return_value=mock_result):
            with pytest.raises(RuntimeError, match="launchctl load failed"):
                schedule._launchctl_load(Path("/tmp/test.plist"))

    def test_launchctl_unload_does_not_raise(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        with patch.object(schedule, "_run_launchctl", return_value=mock_result):
            # Must not raise
            schedule._launchctl_unload(Path("/tmp/test.plist"))

    def test_launchctl_list_contains_true(self):
        mock_result = MagicMock()
        mock_result.stdout = f"  {schedule.LAUNCH_AGENT_LABEL}\t123\t-"
        with patch.object(schedule, "_run_launchctl", return_value=mock_result):
            assert schedule._launchctl_list_contains(schedule.LAUNCH_AGENT_LABEL) is True

    def test_launchctl_list_contains_false(self):
        mock_result = MagicMock()
        mock_result.stdout = "something-else\t456\t-"
        with patch.object(schedule, "_run_launchctl", return_value=mock_result):
            assert schedule._launchctl_list_contains(schedule.LAUNCH_AGENT_LABEL) is False
