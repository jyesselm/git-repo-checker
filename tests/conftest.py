"""Shared test fixtures."""

import subprocess
from pathlib import Path

import pytest

from git_repo_checker.models import (
    AutoPullConfig,
    Config,
    OutputConfig,
    RepoInfo,
    RepoStatus,
)


@pytest.fixture
def sample_config() -> Config:
    """Create a sample configuration for testing."""
    return Config(
        scan_paths=[Path("/tmp/test-repos")],
        exclude_patterns=["**/node_modules", "**/venv"],
        exclude_paths=[],
        main_branches=["main", "master"],
        auto_pull=AutoPullConfig(enabled=True, require_clean=True),
        output=OutputConfig(show_clean=True, color=True, verbosity="normal"),
    )


@pytest.fixture
def temp_git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository."""
    repo_path = tmp_path / "test-repo"
    repo_path.mkdir()

    subprocess.run(["git", "init"], cwd=repo_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo_path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        capture_output=True,
        check=True,
    )

    # Create initial commit
    readme = repo_path / "README.md"
    readme.write_text("# Test Repo")
    subprocess.run(["git", "add", "."], cwd=repo_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_path,
        capture_output=True,
        check=True,
    )

    return repo_path


@pytest.fixture
def temp_git_repo_dirty(temp_git_repo: Path) -> Path:
    """Create a temp git repo with uncommitted changes."""
    (temp_git_repo / "dirty.txt").write_text("uncommitted changes")
    subprocess.run(
        ["git", "add", "dirty.txt"],
        cwd=temp_git_repo,
        capture_output=True,
        check=True,
    )
    return temp_git_repo


@pytest.fixture
def temp_git_repo_untracked(temp_git_repo: Path) -> Path:
    """Create a temp git repo with untracked files only."""
    (temp_git_repo / "untracked.txt").write_text("untracked file")
    return temp_git_repo


@pytest.fixture
def temp_git_repo_on_main(temp_git_repo: Path) -> Path:
    """Create a temp git repo on main branch."""
    subprocess.run(
        ["git", "branch", "-M", "main"],
        cwd=temp_git_repo,
        capture_output=True,
        check=True,
    )
    return temp_git_repo


@pytest.fixture
def sample_repo_info() -> RepoInfo:
    """Create sample RepoInfo for testing."""
    return RepoInfo(
        path=Path("/tmp/test-repo"),
        branch="feature-branch",
        status=RepoStatus.CLEAN,
        is_main_branch=False,
        ahead_count=0,
        behind_count=0,
        changed_files=0,
        untracked_files=0,
        warnings=[],
    )


@pytest.fixture
def sample_config_yaml(tmp_path: Path) -> Path:
    """Create a sample config YAML file."""
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """\
scan_paths:
  - /tmp/repos

exclude_patterns:
  - "**/node_modules"

exclude_paths: []

main_branches:
  - main
  - master

auto_pull:
  enabled: true
  require_clean: true
  skip_patterns: []

output:
  show_clean: true
  color: true
  verbosity: normal
"""
    )
    return config_path


@pytest.fixture
def nested_repos(tmp_path: Path) -> Path:
    """Create a directory structure with multiple git repos."""
    base = tmp_path / "projects"
    base.mkdir()

    for name in ["repo1", "repo2", "repo3"]:
        repo = base / name
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        readme = repo / "README.md"
        readme.write_text(f"# {name}")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=repo,
            capture_output=True,
            check=True,
        )

    # Create a node_modules dir that should be excluded
    node_modules = base / "repo1" / "node_modules" / "some-package"
    node_modules.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=node_modules, capture_output=True, check=True)

    return base
