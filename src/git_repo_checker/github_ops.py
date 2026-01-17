"""GitHub operations - CI status checking via gh CLI."""

import json
import re
import subprocess
from pathlib import Path

from git_repo_checker.models import CIStatus

DEFAULT_TIMEOUT = 30


def is_gh_available() -> bool:
    """Check if the gh CLI is installed and available.

    Returns:
        True if gh CLI is available.
    """
    try:
        result = subprocess.run(
            ["gh", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def get_github_remote(repo_path: Path) -> str | None:
    """Extract GitHub owner/repo from git remote URL.

    Args:
        repo_path: Path to repository root.

    Returns:
        String like "owner/repo" or None if not a GitHub repo.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT,
            check=False,
        )

        if result.returncode != 0:
            return None

        url = result.stdout.strip()
        return parse_github_url(url)
    except (OSError, subprocess.TimeoutExpired):
        return None


def parse_github_url(url: str) -> str | None:
    """Parse a GitHub URL to extract owner/repo.

    Handles both HTTPS and SSH URLs:
    - https://github.com/owner/repo.git
    - git@github.com:owner/repo.git

    Args:
        url: Git remote URL.

    Returns:
        String like "owner/repo" or None if not GitHub.
    """
    # SSH format: git@github.com:owner/repo.git
    ssh_match = re.match(r"git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$", url)
    if ssh_match:
        return f"{ssh_match.group(1)}/{ssh_match.group(2)}"

    # HTTPS format: https://github.com/owner/repo.git
    https_match = re.match(r"https://github\.com/([^/]+)/([^/]+?)(?:\.git)?$", url)
    if https_match:
        return f"{https_match.group(1)}/{https_match.group(2)}"

    return None


def get_ci_status(repo_path: Path) -> CIStatus:
    """Get GitHub Actions CI status for a repository.

    Uses the gh CLI to query workflow run status.

    Args:
        repo_path: Path to repository root.

    Returns:
        CIStatus indicating the CI state.
    """
    if not is_gh_available():
        return CIStatus.UNKNOWN

    repo_slug = get_github_remote(repo_path)
    if not repo_slug:
        return CIStatus.UNKNOWN

    return query_workflow_status(repo_slug)


def query_workflow_status(repo_slug: str) -> CIStatus:
    """Query GitHub for the latest workflow run status.

    Args:
        repo_slug: Repository in "owner/repo" format.

    Returns:
        CIStatus based on the latest workflow run.
    """
    try:
        result = subprocess.run(
            [
                "gh",
                "run",
                "list",
                "--repo",
                repo_slug,
                "--limit",
                "1",
                "--json",
                "status,conclusion",
            ],
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT,
            check=False,
        )

        if result.returncode != 0:
            return CIStatus.UNKNOWN

        return parse_workflow_response(result.stdout)
    except (OSError, subprocess.TimeoutExpired):
        return CIStatus.UNKNOWN


def parse_workflow_response(response: str) -> CIStatus:
    """Parse the gh run list JSON response.

    Args:
        response: JSON string from gh run list.

    Returns:
        CIStatus based on the response.
    """
    try:
        runs = json.loads(response)
    except json.JSONDecodeError:
        return CIStatus.UNKNOWN

    if not runs:
        return CIStatus.NO_WORKFLOWS

    run = runs[0]
    status = run.get("status", "")
    conclusion = run.get("conclusion", "")

    if status in ("queued", "in_progress", "waiting", "pending"):
        return CIStatus.PENDING

    if conclusion == "success":
        return CIStatus.PASSING
    if conclusion in ("failure", "cancelled", "timed_out"):
        return CIStatus.FAILING

    return CIStatus.UNKNOWN
