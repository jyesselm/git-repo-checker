"""macOS launchd scheduling for background sync operations."""

import plistlib
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

LAUNCH_AGENT_LABEL = "com.git-repo-checker.sync"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
PLIST_PATH = LAUNCH_AGENTS_DIR / f"{LAUNCH_AGENT_LABEL}.plist"
_LOG_DIR = Path.home() / "Library" / "Logs"
_LOG_OUT = str(_LOG_DIR / "git-repo-checker-sync.out.log")
_LOG_ERR = str(_LOG_DIR / "git-repo-checker-sync.err.log")


@dataclass
class ScheduleStatus:
    """Current state of the installed sync LaunchAgent."""

    installed: bool
    loaded: bool
    interval_seconds: int | None
    plist_path: Path
    program_args: list[str] = field(default_factory=list)


def find_grc_executable() -> str:
    """Resolve the absolute path to the installed grc entrypoint.

    Returns:
        Absolute path string to the grc binary.

    Raises:
        RuntimeError: If grc is not found on PATH.
    """
    path = shutil.which("grc")
    if path is None:
        raise RuntimeError("grc executable not found on PATH; install the package")
    return path


def build_plist(interval_seconds: int, program_args: list[str]) -> str:
    """Build a launchd plist XML string for the sync schedule.

    Args:
        interval_seconds: How often to run the sync job.
        program_args: Full argv for the sync command.

    Returns:
        Plist XML content as a string.
    """
    plist_dict: dict = {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": program_args,
        "StartInterval": interval_seconds,
        "RunAtLoad": False,
        "StandardOutPath": _LOG_OUT,
        "StandardErrorPath": _LOG_ERR,
    }
    return plistlib.dumps(plist_dict).decode()


def _ensure_dirs() -> None:
    """Create LaunchAgents and log directories if missing."""
    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    _LOG_DIR.mkdir(parents=True, exist_ok=True)


def _reload_if_present() -> None:
    """Unload existing job so reinstall with new interval works."""
    if PLIST_PATH.exists():
        _launchctl_unload(PLIST_PATH)


def install(interval_seconds: int, extra_args: list[str] | None = None) -> Path:
    """Install and load the sync LaunchAgent.

    Creates the plist at ~/Library/LaunchAgents and loads it with launchctl.
    If already installed, unloads first so the new interval takes effect.

    Args:
        interval_seconds: Run interval in seconds (must be >= 1).
        extra_args: Additional arguments passed to grc sync after --quiet.

    Returns:
        Path to the installed plist file.

    Raises:
        ValueError: If interval_seconds < 1.
        RuntimeError: If grc is not on PATH or launchctl load fails.
    """
    if interval_seconds < 1:
        raise ValueError(f"interval_seconds must be >= 1, got {interval_seconds}")

    grc = find_grc_executable()
    program_args = [grc, "sync", "--quiet", *(extra_args or [])]

    _ensure_dirs()
    _reload_if_present()

    plist_text = build_plist(interval_seconds, program_args)
    PLIST_PATH.write_text(plist_text)

    _launchctl_load(PLIST_PATH)
    return PLIST_PATH


def uninstall() -> bool:
    """Unload and remove the sync LaunchAgent plist.

    Returns:
        True if a plist was removed, False if nothing was installed.
    """
    if not PLIST_PATH.exists():
        return False

    _launchctl_unload(PLIST_PATH)
    PLIST_PATH.unlink(missing_ok=True)
    return True


def get_status() -> ScheduleStatus:
    """Return the current state of the sync LaunchAgent.

    Returns:
        ScheduleStatus with installed/loaded state and configuration details.
    """
    if not PLIST_PATH.exists():
        return ScheduleStatus(
            installed=False,
            loaded=False,
            interval_seconds=None,
            plist_path=PLIST_PATH,
        )

    with open(PLIST_PATH, "rb") as f:
        data = plistlib.load(f)

    interval: int | None = data.get("StartInterval")
    args: list[str] = data.get("ProgramArguments", [])
    loaded = _launchctl_list_contains(LAUNCH_AGENT_LABEL)

    return ScheduleStatus(
        installed=True,
        loaded=loaded,
        interval_seconds=interval,
        plist_path=PLIST_PATH,
        program_args=args,
    )


def _run_launchctl(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a launchctl subcommand and return the result.

    Args:
        args: Arguments to pass after 'launchctl'.

    Returns:
        CompletedProcess result from subprocess.

    Raises:
        RuntimeError: If the process cannot be started or times out.
    """
    try:
        return subprocess.run(
            ["launchctl", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"launchctl failed: {exc}") from exc


def _launchctl_load(plist: Path) -> None:
    """Load a launchd job from a plist file.

    Args:
        plist: Path to the plist file to load.

    Raises:
        RuntimeError: If launchctl returns a non-zero exit code.
    """
    result = _run_launchctl(["load", "-w", str(plist)])
    if result.returncode != 0:
        raise RuntimeError(result.stderr or f"launchctl load failed (rc={result.returncode})")


def _launchctl_unload(plist: Path) -> None:
    """Unload a launchd job from a plist file.

    Does not raise on non-zero exit because unloading an already-unloaded
    job is a common and harmless case.

    Args:
        plist: Path to the plist file to unload.
    """
    _run_launchctl(["unload", "-w", str(plist)])


def _launchctl_list_contains(label: str) -> bool:
    """Check if a launchd label is currently loaded.

    Args:
        label: The launchd job label to look for.

    Returns:
        True if the label appears in launchctl list output.
    """
    result = _run_launchctl(["list"])
    return label in result.stdout
