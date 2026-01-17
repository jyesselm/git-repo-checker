"""Configuration management for git-repo-checker."""

from pathlib import Path

import yaml

from git_repo_checker.models import AutoPullConfig, Config, OutputConfig

DEFAULT_CONFIG_LOCATIONS = [
    Path("./git-repo-checker.yml"),
    Path("./git-repo-checker.yaml"),
    Path.home() / ".config" / "git-repo-checker" / "config.yml",
    Path.home() / ".config" / "git-repo-checker" / "config.yaml",
]

DEFAULT_CONFIG_TEMPLATE = """\
# Directories to scan for git repositories
scan_paths:
  - ~/code
  - ~/projects

# Glob patterns for directories to exclude
exclude_patterns:
  - "**/node_modules"
  - "**/venv"
  - "**/.venv"
  - "**/vendor"
  - "**/__pycache__"

# Specific directories to exclude (absolute paths)
exclude_paths: []

# Branch names considered "main" branches (warns if dirty)
main_branches:
  - main
  - master

# Auto-pull configuration
auto_pull:
  enabled: true
  require_clean: true
  skip_patterns: []

# Output settings
output:
  show_clean: true
  color: true
  verbosity: normal  # quiet, normal, verbose
"""


def find_config_path() -> Path | None:
    """Find configuration file in standard locations.

    Searches in order: current directory, then ~/.config/git-repo-checker/.

    Returns:
        Path to config file if found, None otherwise.
    """
    for path in DEFAULT_CONFIG_LOCATIONS:
        expanded = path.expanduser()
        if expanded.exists():
            return expanded
    return None


def load_config(config_path: Path | None = None) -> Config:
    """Load configuration from YAML file.

    Args:
        config_path: Explicit path to config. If None, searches default locations.

    Returns:
        Validated Config object with defaults applied.

    Raises:
        FileNotFoundError: If no config file found and none specified.
        ValueError: If config file is invalid YAML or schema.
    """
    if config_path is None:
        config_path = find_config_path()

    if config_path is None:
        raise FileNotFoundError(
            "No config file found. Create one with 'grc init' or specify with --config"
        )

    return load_config_from_path(config_path)


def load_config_from_path(config_path: Path) -> Config:
    """Load and parse config from a specific path.

    Args:
        config_path: Path to the YAML config file.

    Returns:
        Validated Config object.

    Raises:
        FileNotFoundError: If file does not exist.
        ValueError: If YAML is invalid or doesn't match schema.
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path) as f:
        raw_config = yaml.safe_load(f) or {}

    config = parse_raw_config(raw_config)
    return expand_paths(config)


def parse_raw_config(raw: dict) -> Config:
    """Parse raw dictionary into Config object.

    Args:
        raw: Dictionary from YAML parsing.

    Returns:
        Config object with nested models populated.
    """
    auto_pull_raw = raw.get("auto_pull", {})
    output_raw = raw.get("output", {})

    return Config(
        scan_paths=[Path(p) for p in raw.get("scan_paths", [])],
        exclude_patterns=raw.get("exclude_patterns", []),
        exclude_paths=[Path(p) for p in raw.get("exclude_paths", [])],
        main_branches=raw.get("main_branches", ["main", "master"]),
        auto_pull=AutoPullConfig(**auto_pull_raw),
        output=OutputConfig(**output_raw),
    )


def expand_paths(config: Config) -> Config:
    """Expand ~ and resolve all paths to absolute paths.

    Args:
        config: Config with potentially unexpanded paths.

    Returns:
        Config with all paths expanded and resolved.
    """
    return Config(
        scan_paths=[p.expanduser().resolve() for p in config.scan_paths],
        exclude_patterns=config.exclude_patterns,
        exclude_paths=[p.expanduser().resolve() for p in config.exclude_paths],
        main_branches=config.main_branches,
        auto_pull=config.auto_pull,
        output=config.output,
    )


def create_default_config(output_path: Path) -> None:
    """Create a default configuration file with comments.

    Args:
        output_path: Where to write the config file.

    Raises:
        FileExistsError: If file already exists.
    """
    output_path = output_path.expanduser().resolve()

    if output_path.exists():
        raise FileExistsError(f"Config file already exists: {output_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(DEFAULT_CONFIG_TEMPLATE)
