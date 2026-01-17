"""Git operations - status, pull, branch detection."""

import re
import subprocess
from pathlib import Path

from git_repo_checker.models import PullResult, RepoStatus

DEFAULT_TIMEOUT = 30


class GitError(Exception):
    """Exception raised for git command failures."""

    def __init__(self, message: str, repo_path: Path) -> None:
        """Initialize GitError.

        Args:
            message: Error description.
            repo_path: Path to the repository where error occurred.
        """
        self.repo_path = repo_path
        super().__init__(message)


def run_git_command(
    repo_path: Path,
    args: list[str],
    timeout: int = DEFAULT_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    """Run a git command in a repository.

    Args:
        repo_path: Path to repository root.
        args: Git command arguments (without 'git' prefix).
        timeout: Command timeout in seconds.

    Returns:
        CompletedProcess with stdout/stderr as strings.

    Raises:
        GitError: If command fails or times out.
    """
    cmd = ["git", "-C", str(repo_path), *args]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result
    except subprocess.TimeoutExpired as e:
        raise GitError(f"Command timed out after {timeout}s: {' '.join(args)}", repo_path) from e
    except OSError as e:
        raise GitError(f"Failed to run git: {e}", repo_path) from e


def get_current_branch(repo_path: Path) -> str:
    """Get the current branch name for a repository.

    Args:
        repo_path: Path to repository root.

    Returns:
        Branch name, or "HEAD" if in detached state.

    Raises:
        GitError: If git command fails.
    """
    result = run_git_command(repo_path, ["rev-parse", "--abbrev-ref", "HEAD"])

    if result.returncode != 0:
        raise GitError(f"Failed to get branch: {result.stderr.strip()}", repo_path)

    return result.stdout.strip()


def get_repo_status(repo_path: Path) -> tuple[RepoStatus, int, int]:
    """Get the working tree status of a repository.

    Uses `git status --porcelain` to determine state.

    Args:
        repo_path: Path to repository root.

    Returns:
        Tuple of (RepoStatus, changed_files_count, untracked_files_count).
    """
    result = run_git_command(repo_path, ["status", "--porcelain"])

    if result.returncode != 0:
        return RepoStatus.ERROR, 0, 0

    lines = [line for line in result.stdout.strip().split("\n") if line]

    if not lines:
        return RepoStatus.CLEAN, 0, 0

    changed = 0
    untracked = 0

    for line in lines:
        if line.startswith("??"):
            untracked += 1
        else:
            changed += 1

    if changed > 0:
        return RepoStatus.DIRTY, changed, untracked
    return RepoStatus.UNTRACKED, 0, untracked


def has_upstream(repo_path: Path) -> bool:
    """Check if current branch has an upstream configured.

    Args:
        repo_path: Path to repository root.

    Returns:
        True if upstream is configured.
    """
    result = run_git_command(
        repo_path, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"]
    )
    return result.returncode == 0


def get_remote_status(repo_path: Path) -> tuple[int, int]:
    """Get ahead/behind counts relative to upstream.

    Fetches first to ensure accurate counts.

    Args:
        repo_path: Path to repository root.

    Returns:
        Tuple of (ahead_count, behind_count). Both 0 if no upstream.
    """
    if not has_upstream(repo_path):
        return 0, 0

    cmd_args = ["rev-list", "--left-right", "--count", "@{upstream}...HEAD"]
    result = run_git_command(repo_path, cmd_args)

    if result.returncode != 0:
        return 0, 0

    parts = result.stdout.strip().split()
    if len(parts) != 2:
        return 0, 0

    try:
        behind = int(parts[0])
        ahead = int(parts[1])
        return ahead, behind
    except ValueError:
        return 0, 0


def determine_remote_status(ahead: int, behind: int, base_status: RepoStatus) -> RepoStatus:
    """Determine final status based on ahead/behind counts.

    Args:
        ahead: Commits ahead of upstream.
        behind: Commits behind upstream.
        base_status: Status from working tree check.

    Returns:
        Final RepoStatus considering remote state.
    """
    if base_status not in (RepoStatus.CLEAN, RepoStatus.UNTRACKED):
        return base_status

    if ahead > 0 and behind > 0:
        return RepoStatus.DIVERGED
    if ahead > 0:
        return RepoStatus.AHEAD
    if behind > 0:
        return RepoStatus.BEHIND

    return base_status


def pull_repo(repo_path: Path) -> PullResult:
    """Execute git pull on a repository.

    Args:
        repo_path: Path to repository root.

    Returns:
        PullResult with success status, message, and files changed.
    """
    result = run_git_command(repo_path, ["pull", "--ff-only"], timeout=60)

    if result.returncode != 0:
        return PullResult(
            path=repo_path,
            success=False,
            message=result.stderr.strip() or "Pull failed",
            files_changed=0,
        )

    output = result.stdout.strip()
    files_changed = parse_pull_files_changed(output)

    if "Already up to date" in output:
        message = "Already up to date"
    else:
        message = "Pull successful"

    return PullResult(
        path=repo_path,
        success=True,
        message=message,
        files_changed=files_changed,
    )


def parse_pull_files_changed(output: str) -> int:
    """Parse git pull output to extract files changed count.

    Args:
        output: Git pull stdout.

    Returns:
        Number of files changed, or 0 if not found.
    """
    match = re.search(r"(\d+)\s+file", output)
    if match:
        return int(match.group(1))
    return 0


def fetch_repo(repo_path: Path) -> bool:
    """Fetch updates from remote without merging.

    Args:
        repo_path: Path to repository root.

    Returns:
        True if fetch succeeded.
    """
    result = run_git_command(repo_path, ["fetch"], timeout=60)
    return result.returncode == 0
