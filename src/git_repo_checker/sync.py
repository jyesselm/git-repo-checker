"""Sync tracked repositories across machines."""

import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml

from git_repo_checker import git_ops
from git_repo_checker.models import (
    RepoInfo,
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

# Path prefix for all repos - override with --path-prefix for different machines
# Example: path_prefix: ~/code  (local) vs  path_prefix: /cluster/user/code  (cluster)
path_prefix: ~

repos:
  # - path: code/my-project           # relative to path_prefix
  #   remote: git@github.com:username/my-project.git
  #   branch: main   # optional, defaults to main
  #   ignore: false  # optional, set to true to skip this repo
"""

LOCAL_CONFIG_PATH = Path.home() / ".config" / "git-repo-checker" / "local.yml"


def fetch_repos_from_url(url: str, output_path: Path | None = None) -> Path:
    """Fetch repos.yml from a URL and save locally.

    Args:
        url: URL to fetch repos.yml from (e.g., GitHub raw URL).
        output_path: Where to save the file. Defaults to ~/.config/git-repo-checker/repos.yml

    Returns:
        Path where the file was saved.

    Raises:
        URLError: If fetch fails.
    """
    if output_path is None:
        output_path = Path.home() / ".config" / "git-repo-checker" / "repos.yml"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with urllib.request.urlopen(url, timeout=30) as response:
        content = response.read().decode("utf-8")

    output_path.write_text(content)
    return output_path


def load_local_config() -> dict:
    """Load local machine config for path overrides.

    Returns:
        Dictionary with local config or empty dict if not found.
    """
    if not LOCAL_CONFIG_PATH.exists():
        return {}

    with open(LOCAL_CONFIG_PATH) as f:
        return yaml.safe_load(f) or {}


def get_effective_path_prefix(file_prefix: str, cli_prefix: str | None = None) -> str:
    """Get the effective path prefix to use.

    Priority: CLI flag > local config > repos file.

    Args:
        file_prefix: Path prefix from repos.yml file.
        cli_prefix: Path prefix from CLI flag (if provided).

    Returns:
        The effective path prefix to use.
    """
    if cli_prefix is not None:
        return cli_prefix

    local_config = load_local_config()
    local_prefix = local_config.get("path_prefix")
    if local_prefix is not None:
        return str(local_prefix)

    return file_prefix


def apply_path_prefix(repo_path: str, prefix: str) -> Path:
    """Apply path prefix to a repo path.

    Args:
        repo_path: The repo path (can be relative or absolute).
        prefix: The path prefix to apply.

    Returns:
        Resolved absolute path.
    """
    path = Path(repo_path)

    # If path is absolute, use it directly
    if path.is_absolute():
        return path.expanduser().resolve()

    # Apply prefix for relative paths
    prefix_path = Path(prefix).expanduser()
    return (prefix_path / path).resolve()


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


def load_repos_file(
    repos_path: Path | None = None,
    path_prefix: str | None = None,
) -> list[TrackedRepo]:
    """Load tracked repositories from YAML file.

    Args:
        repos_path: Explicit path to repos file. If None, searches default locations.
        path_prefix: Override path prefix from CLI.

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

    return load_repos_from_path(repos_path, path_prefix)


def load_repos_from_path(
    repos_path: Path,
    path_prefix: str | None = None,
) -> list[TrackedRepo]:
    """Load and parse repos from a specific path.

    Args:
        repos_path: Path to the YAML repos file.
        path_prefix: Override path prefix from CLI.

    Returns:
        List of TrackedRepo objects.
    """
    if not repos_path.exists():
        raise FileNotFoundError(f"Repos file not found: {repos_path}")

    with open(repos_path) as f:
        raw = yaml.safe_load(f) or {}

    # Get path prefix from file, with possible override
    file_prefix = raw.get("path_prefix", "~")
    effective_prefix = get_effective_path_prefix(file_prefix, path_prefix)

    repos_raw = raw.get("repos", [])
    if not repos_raw:
        return []

    return [parse_tracked_repo(r, effective_prefix) for r in repos_raw]


def parse_tracked_repo(raw: dict, path_prefix: str = "~") -> TrackedRepo:
    """Parse a single tracked repo entry.

    Args:
        raw: Dictionary with path, remote, and optional branch/ignore.
        path_prefix: Path prefix to apply to relative paths.

    Returns:
        TrackedRepo object with expanded path.
    """
    path = apply_path_prefix(raw["path"], path_prefix)
    return TrackedRepo(
        path=path,
        remote=raw["remote"],
        branch=raw.get("branch", "main"),
        ignore=raw.get("ignore", False),
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


def extract_git_error(message: str) -> str:
    """Extract the key error from git output.

    Looks for 'fatal:' or 'error:' lines and returns just that part.

    Args:
        message: Full git error output.

    Returns:
        Cleaned up error message.
    """
    for line in message.split("\n"):
        line = line.strip()
        if line.startswith("fatal:"):
            return line[6:].strip()
        if line.startswith("error:"):
            return line[6:].strip()
    # No fatal/error found, return last non-empty line
    lines = [l.strip() for l in message.split("\n") if l.strip()]
    return lines[-1] if lines else message


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
            message=f"Pull failed: {extract_git_error(result.message)}",
        )
    except git_ops.GitError as e:
        return SyncRepoResult(
            repo=repo,
            action=SyncAction.ERROR,
            message=extract_git_error(str(e)),
        )


def is_branch_not_found_error(message: str) -> bool:
    """Check if error is a branch not found error.

    Args:
        message: Error message from git.

    Returns:
        True if error indicates branch was not found.
    """
    lower_msg = message.lower()
    return "remote branch" in lower_msg and "not found" in lower_msg


def clone_repo(repo: TrackedRepo) -> SyncRepoResult:
    """Clone a repository that doesn't exist locally.

    If the specified branch doesn't exist, falls back to cloning
    the default branch and warns about the missing branch.

    Args:
        repo: The tracked repository to clone.

    Returns:
        SyncRepoResult with clone result.
    """
    import shutil

    try:
        repo.path.parent.mkdir(parents=True, exist_ok=True)
        result = git_ops.clone_repo(repo.remote, repo.path, repo.branch)

        if result.success:
            return SyncRepoResult(
                repo=repo,
                action=SyncAction.CLONED,
                message=f"Cloned ({repo.branch})",
            )

        # Check if it's a branch not found error
        error_msg = extract_git_error(result.message)
        if is_branch_not_found_error(result.message):
            # Clean up failed clone attempt
            if repo.path.exists():
                shutil.rmtree(repo.path)

            # Retry without specifying branch (use default)
            fallback_result = git_ops.clone_repo(repo.remote, repo.path, branch=None)
            if fallback_result.success:
                return SyncRepoResult(
                    repo=repo,
                    action=SyncAction.CLONED,
                    message=f"Cloned (default branch, wanted: {repo.branch})",
                )
            # Fallback also failed
            return SyncRepoResult(
                repo=repo,
                action=SyncAction.ERROR,
                message=extract_git_error(fallback_result.message),
            )

        return SyncRepoResult(
            repo=repo,
            action=SyncAction.ERROR,
            message=error_msg,
        )
    except git_ops.GitError as e:
        return SyncRepoResult(
            repo=repo,
            action=SyncAction.ERROR,
            message=extract_git_error(str(e)),
        )


def sync_all(
    repos: list[TrackedRepo], pull_existing: bool = True, max_workers: int | None = None
) -> SyncResult:
    """Sync all tracked repositories.

    Args:
        repos: List of repositories to sync.
        pull_existing: Whether to pull repos that already exist.
        max_workers: Maximum number of threads for parallel sync.
            Defaults to min(32, cpu_count + 4).

    Returns:
        SyncResult with all individual results and counts.
    """
    results: list[SyncRepoResult] = []
    cloned = 0
    pulled = 0
    skipped = 0
    errors = 0

    # Handle ignored repos first (no I/O needed)
    active_repos = []
    for repo in repos:
        if repo.ignore:
            results.append(
                SyncRepoResult(
                    repo=repo,
                    action=SyncAction.SKIPPED,
                    message="Ignored",
                )
            )
            skipped += 1
        else:
            active_repos.append(repo)

    # Sync active repos in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_repo = {
            executor.submit(sync_repo, repo, pull_existing): repo
            for repo in active_repos
        }

        for future in as_completed(future_to_repo):
            result = future.result()
            results.append(result)

            if result.action == SyncAction.CLONED:
                cloned += 1
            elif result.action == SyncAction.PULLED:
                pulled += 1
            elif result.action == SyncAction.SKIPPED:
                skipped += 1
            else:
                errors += 1

    # Sort results by path for consistent output
    results.sort(key=lambda r: r.repo.path)

    return SyncResult(
        results=results,
        cloned=cloned,
        pulled=pulled,
        skipped=skipped,
        errors=errors,
    )


def repo_to_export_entry(repo: RepoInfo, path_prefix: Path) -> dict | None:
    """Convert a RepoInfo to a repos.yml entry.

    Args:
        repo: RepoInfo from scan results.
        path_prefix: Path prefix to make paths relative to.

    Returns:
        Dictionary for repos.yml entry, or None if no remote found.
    """
    remote = git_ops.get_remote_url(repo.path)
    if not remote:
        return None

    # Make path relative to prefix
    try:
        relative_path = repo.path.relative_to(path_prefix.expanduser().resolve())
        path_str = str(relative_path)
    except ValueError:
        # Path not under prefix, use absolute
        path_str = str(repo.path)

    entry = {
        "path": path_str,
        "remote": remote,
    }

    # Only add branch if not main
    if repo.branch and repo.branch not in ("main", "master"):
        entry["branch"] = repo.branch

    return entry


def export_repos_to_file(
    repos: list[RepoInfo],
    output_path: Path,
    path_prefix: str = "~",
    merge: bool = False,
) -> tuple[int, int, list[tuple[str, str, str]]]:
    """Export scanned repos to a repos.yml file.

    Args:
        repos: List of RepoInfo from scan results.
        output_path: Where to write the repos file.
        path_prefix: Path prefix for relative paths.
        merge: If True, merge with existing file instead of overwriting.

    Returns:
        Tuple of (repos_added, repos_skipped, collisions).
        Collisions are tuples of (path, new_remote, existing_remote).

    Raises:
        FileExistsError: If file exists and merge=False.
    """
    output_path = output_path.expanduser().resolve()
    prefix_path = Path(path_prefix).expanduser().resolve()

    existing_remotes: set[str] = set()
    existing_paths: dict[str, str] = {}
    existing_data: dict = {"path_prefix": path_prefix, "repos": []}
    collisions: list[tuple[str, str, str]] = []  # (path, new_remote, existing_remote)

    if output_path.exists():
        if not merge:
            raise FileExistsError(f"Repos file already exists: {output_path}. Use --merge to add to it.")

        with open(output_path) as f:
            existing_data = yaml.safe_load(f) or {}

        existing_repos = existing_data.get("repos", [])
        existing_remotes = {r.get("remote") for r in existing_repos if r.get("remote")}
        existing_paths = {r.get("path"): r.get("remote") for r in existing_repos if r.get("path")}
        # Keep existing path_prefix if merging
        if "path_prefix" not in existing_data:
            existing_data["path_prefix"] = path_prefix
        if "repos" not in existing_data:
            existing_data["repos"] = []

    added = 0
    skipped = 0

    for repo in repos:
        entry = repo_to_export_entry(repo, prefix_path)
        if entry is None:
            skipped += 1
            continue

        # Skip if remote already tracked
        if entry["remote"] in existing_remotes:
            skipped += 1
            continue

        # Check for path collision (same path, different remote)
        if entry["path"] in existing_paths:
            collisions.append((entry["path"], entry["remote"], existing_paths[entry["path"]]))
            skipped += 1
            continue

        existing_data["repos"].append(entry)
        existing_remotes.add(entry["remote"])
        existing_paths[entry["path"]] = entry["remote"]
        added += 1

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Generate YAML with comments
    header = """\
# Tracked repositories for git-repo-checker sync
# These repos will be cloned if missing, pulled if they exist
#
# Override path_prefix for different machines with --path-prefix or local.yml

"""
    yaml_content = yaml.dump(existing_data, default_flow_style=False, sort_keys=False)

    # Add blank lines between repo entries for readability
    yaml_content = re.sub(r'\n- path:', r'\n\n- path:', yaml_content)

    output_path.write_text(header + yaml_content)

    return added, skipped, collisions
