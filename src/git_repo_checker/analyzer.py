"""Analyze repository state and detect issues."""

from pathlib import Path

from git_repo_checker import git_ops, scanner
from git_repo_checker.models import (
    Config,
    PullResult,
    RepoInfo,
    RepoStatus,
    ScanResult,
    WarningType,
)


def analyze_repo(repo_path: Path, config: Config) -> RepoInfo:
    """Analyze a single repository and return its info.

    Gathers branch, status, remote state, and generates warnings.

    Args:
        repo_path: Path to repository root.
        config: Application configuration for main branch detection.

    Returns:
        RepoInfo with all gathered information.
    """
    try:
        branch = git_ops.get_current_branch(repo_path)
        status, changed, untracked = git_ops.get_repo_status(repo_path)
        has_remote = git_ops.has_upstream(repo_path)

        # Fetch to get latest remote state before checking ahead/behind
        if has_remote:
            git_ops.fetch_repo(repo_path)

        ahead, behind = git_ops.get_remote_status(repo_path)

        final_status = git_ops.determine_remote_status(ahead, behind, status)
        is_main = is_main_branch(branch, config.main_branches)
        warnings = detect_warnings(branch, status, is_main, has_remote)

        return RepoInfo(
            path=repo_path,
            branch=branch,
            status=final_status,
            is_main_branch=is_main,
            ahead_count=ahead,
            behind_count=behind,
            changed_files=changed,
            untracked_files=untracked,
            warnings=warnings,
        )
    except git_ops.GitError as e:
        return RepoInfo(
            path=repo_path,
            branch="unknown",
            status=RepoStatus.ERROR,
            error_message=str(e),
        )


def is_main_branch(branch: str, main_branches: list[str]) -> bool:
    """Check if branch name is considered a main branch.

    Args:
        branch: Current branch name.
        main_branches: List of main branch names from config.

    Returns:
        True if branch is a main branch.
    """
    return branch.lower() in [b.lower() for b in main_branches]


def detect_warnings(
    branch: str,
    status: RepoStatus,
    is_main: bool,
    has_remote: bool,
) -> list[WarningType]:
    """Detect warning conditions for a repository.

    Args:
        branch: Current branch name.
        status: Repository working tree status.
        is_main: Whether currently on main branch.
        has_remote: Whether upstream is configured.

    Returns:
        List of applicable warnings.
    """
    warnings: list[WarningType] = []

    if is_main and status == RepoStatus.DIRTY:
        warnings.append(WarningType.DIRTY_MAIN)

    if not has_remote:
        warnings.append(WarningType.NO_REMOTE)

    if branch == "HEAD":
        warnings.append(WarningType.DETACHED)

    return warnings


def should_auto_pull(repo_info: RepoInfo, config: Config) -> bool:
    """Determine if a repository should be auto-pulled.

    Args:
        repo_info: Repository information.
        config: Application configuration.

    Returns:
        True if repo should be auto-pulled.
    """
    if not config.auto_pull.enabled:
        return False

    if repo_info.status == RepoStatus.ERROR:
        return False

    if config.auto_pull.require_clean and repo_info.status not in (
        RepoStatus.CLEAN,
        RepoStatus.BEHIND,
    ):
        return False

    if repo_info.behind_count == 0:
        return False

    if matches_skip_pattern(repo_info.path, config.auto_pull.skip_patterns):
        return False

    return True


def matches_skip_pattern(path: Path, patterns: list[str]) -> bool:
    """Check if path matches any skip pattern.

    Args:
        path: Repository path.
        patterns: Skip patterns from config.

    Returns:
        True if path should be skipped.
    """
    return scanner.matches_any_pattern(path, patterns)


def scan_and_analyze(config: Config, auto_pull: bool = True) -> ScanResult:
    """Scan all configured paths and analyze each repository.

    Main orchestration function that ties scanning, analysis,
    and optional auto-pull together.

    Args:
        config: Application configuration.
        auto_pull: Whether to perform auto-pull on eligible repos.

    Returns:
        ScanResult with all repos and pull results.
    """
    repos: list[RepoInfo] = []
    pull_results: list[PullResult] = []
    scan_errors: list[str] = []

    repo_paths = list(
        scanner.find_git_repos(
            scan_paths=config.scan_paths,
            exclude_patterns=config.exclude_patterns,
            exclude_paths=config.exclude_paths,
        )
    )

    for repo_path in repo_paths:
        repo_info = analyze_repo(repo_path, config)
        repos.append(repo_info)

        if auto_pull and should_auto_pull(repo_info, config):
            result = git_ops.pull_repo(repo_path)
            pull_results.append(result)

            if result.success:
                repo_info.status = RepoStatus.CLEAN
                repo_info.behind_count = 0

    return ScanResult(
        repos=repos,
        pull_results=pull_results,
        total_scanned=len(repos),
        scan_errors=scan_errors,
    )
