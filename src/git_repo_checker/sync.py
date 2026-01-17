"""Sync tracked repositories across machines."""

from pathlib import Path

import yaml

from git_repo_checker import git_ops
from git_repo_checker.models import (
    SyncAction,
    SyncRepoResult,
    SyncResult,
    TrackedRepo,
)

DEFAULT_REPOS_LOCATIONS = [
    Path("./repos.yml"),
    Path("./repos.yaml"),
    Path.home() / ".config" / "git-repo-checker" / "repos.yml",
    Path.home() / ".config" / "git-repo-checker" / "repos.yaml",
]

REPOS_TEMPLATE = """\
# Tracked repositories for git-repo-checker sync
# These repos will be cloned if missing, pulled if they exist

repos:
  # - path: ~/code/my-project
  #   remote: git@github.com:username/my-project.git
  #   branch: main  # optional, defaults to main
"""


def find_repos_file() -> Path | None:
    """Find repos file in standard locations.

    Returns:
        Path to repos file if found, None otherwise.
    """
    for path in DEFAULT_REPOS_LOCATIONS:
        expanded = path.expanduser()
        if expanded.exists():
            return expanded
    return None


def load_repos_file(repos_path: Path | None = None) -> list[TrackedRepo]:
    """Load tracked repositories from YAML file.

    Args:
        repos_path: Explicit path to repos file. If None, searches default locations.

    Returns:
        List of TrackedRepo objects.

    Raises:
        FileNotFoundError: If no repos file found.
        ValueError: If file format is invalid.
    """
    if repos_path is None:
        repos_path = find_repos_file()

    if repos_path is None:
        raise FileNotFoundError(
            "No repos file found. Create one with 'grc sync --init' or specify with --repos"
        )

    return load_repos_from_path(repos_path)


def load_repos_from_path(repos_path: Path) -> list[TrackedRepo]:
    """Load and parse repos from a specific path.

    Args:
        repos_path: Path to the YAML repos file.

    Returns:
        List of TrackedRepo objects.
    """
    if not repos_path.exists():
        raise FileNotFoundError(f"Repos file not found: {repos_path}")

    with open(repos_path) as f:
        raw = yaml.safe_load(f) or {}

    repos_raw = raw.get("repos", [])
    if not repos_raw:
        return []

    return [parse_tracked_repo(r) for r in repos_raw]


def parse_tracked_repo(raw: dict) -> TrackedRepo:
    """Parse a single tracked repo entry.

    Args:
        raw: Dictionary with path, remote, and optional branch.

    Returns:
        TrackedRepo object with expanded path.
    """
    path = Path(raw["path"]).expanduser().resolve()
    return TrackedRepo(
        path=path,
        remote=raw["remote"],
        branch=raw.get("branch", "main"),
    )


def create_repos_file(output_path: Path) -> None:
    """Create a template repos file.

    Args:
        output_path: Where to write the repos file.

    Raises:
        FileExistsError: If file already exists.
    """
    output_path = output_path.expanduser().resolve()

    if output_path.exists():
        raise FileExistsError(f"Repos file already exists: {output_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(REPOS_TEMPLATE)


def sync_repo(repo: TrackedRepo, pull_existing: bool = True) -> SyncRepoResult:
    """Sync a single tracked repository.

    Clones if missing, optionally pulls if exists.

    Args:
        repo: The tracked repository to sync.
        pull_existing: Whether to pull repos that already exist.

    Returns:
        SyncRepoResult with action taken and message.
    """
    if repo.path.exists():
        return handle_existing_repo(repo, pull_existing)

    return clone_repo(repo)


def handle_existing_repo(repo: TrackedRepo, pull_existing: bool) -> SyncRepoResult:
    """Handle a repo that already exists locally.

    Args:
        repo: The tracked repository.
        pull_existing: Whether to pull updates.

    Returns:
        SyncRepoResult with action taken.
    """
    git_dir = repo.path / ".git"
    if not git_dir.exists():
        return SyncRepoResult(
            repo=repo,
            action=SyncAction.ERROR,
            message=f"Path exists but is not a git repo: {repo.path}",
        )

    if not pull_existing:
        return SyncRepoResult(
            repo=repo,
            action=SyncAction.SKIPPED,
            message="Already exists",
        )

    # Fetch and pull if behind
    try:
        git_ops.fetch_repo(repo.path)
        ahead, behind = git_ops.get_remote_status(repo.path)

        if behind == 0:
            return SyncRepoResult(
                repo=repo,
                action=SyncAction.SKIPPED,
                message="Already up to date",
            )

        result = git_ops.pull_repo(repo.path)
        if result.success:
            return SyncRepoResult(
                repo=repo,
                action=SyncAction.PULLED,
                message=f"Pulled {result.files_changed} files",
            )
        return SyncRepoResult(
            repo=repo,
            action=SyncAction.ERROR,
            message=f"Pull failed: {result.message}",
        )
    except git_ops.GitError as e:
        return SyncRepoResult(
            repo=repo,
            action=SyncAction.ERROR,
            message=str(e),
        )


def clone_repo(repo: TrackedRepo) -> SyncRepoResult:
    """Clone a repository that doesn't exist locally.

    Args:
        repo: The tracked repository to clone.

    Returns:
        SyncRepoResult with clone result.
    """
    try:
        repo.path.parent.mkdir(parents=True, exist_ok=True)
        result = git_ops.clone_repo(repo.remote, repo.path, repo.branch)

        if result.success:
            return SyncRepoResult(
                repo=repo,
                action=SyncAction.CLONED,
                message=f"Cloned from {repo.remote}",
            )
        return SyncRepoResult(
            repo=repo,
            action=SyncAction.ERROR,
            message=f"Clone failed: {result.message}",
        )
    except git_ops.GitError as e:
        return SyncRepoResult(
            repo=repo,
            action=SyncAction.ERROR,
            message=str(e),
        )


def sync_all(repos: list[TrackedRepo], pull_existing: bool = True) -> SyncResult:
    """Sync all tracked repositories.

    Args:
        repos: List of repositories to sync.
        pull_existing: Whether to pull repos that already exist.

    Returns:
        SyncResult with all individual results and counts.
    """
    results: list[SyncRepoResult] = []
    cloned = 0
    pulled = 0
    skipped = 0
    errors = 0

    for repo in repos:
        result = sync_repo(repo, pull_existing)
        results.append(result)

        if result.action == SyncAction.CLONED:
            cloned += 1
        elif result.action == SyncAction.PULLED:
            pulled += 1
        elif result.action == SyncAction.SKIPPED:
            skipped += 1
        else:
            errors += 1

    return SyncResult(
        results=results,
        cloned=cloned,
        pulled=pulled,
        skipped=skipped,
        errors=errors,
    )
